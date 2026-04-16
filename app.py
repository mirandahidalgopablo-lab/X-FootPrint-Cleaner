import os
import json
import tweepy
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from flask import Flask, redirect, url_for, session, request, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.environ.get("SECRET_KEY", "clave_secreta_provisional")
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

oauth2_handler = tweepy.OAuth2UserHandler(
    client_id=CLIENT_ID,
    redirect_uri=REDIRECT_URI,
    scope=["tweet.read", "tweet.write", "users.read", "offline.access"],
    client_secret=CLIENT_SECRET
)

def analizar_todo_con_ia(tweets_lote, temas):
    if not GEMINI_API_KEY:
        return [], "Falta la API KEY en Render"

    modelo = genai.GenerativeModel("gemini-flash-latest")

    lista_tweets = ""
    for tw in tweets_lote:
        lista_tweets += f'ID:"{tw["id"]}" | TEXTO: {tw["texto"]}\n'

    criterio = f"contenido de {', '.join(temas)}" if temas else "contenido ofensivo, toxico o polemico"

    prompt = f"""Analiza estos tweets y devuelve SOLO un array JSON con los IDs de los que sean {criterio}.
    Si no hay ninguno, devuelve []. No escribas nada mas que el JSON.
    Tweets:
    {lista_tweets}"""

    try:
        respuesta = modelo.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
            safety_settings={
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        return json.loads(respuesta.text.strip()), None
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg: return [], "Has superado el límite de cuota gratuita. Intenta más tarde."
        if "404" in error_msg: return [], "Modelo de IA no encontrado en esta cuenta."
        return [], error_msg

@app.route("/")
def index():
    login_url = oauth2_handler.get_authorization_url()
    return render_template("index.html", login_url=login_url)

@app.route("/callback")
def callback():
    try:
        url_segura = request.url.replace("http:", "https:", 1) if REDIRECT_URI and REDIRECT_URI.startswith("https") else request.url
        access_token = oauth2_handler.fetch_token(url_segura)
        session["token"] = access_token
        return redirect(url_for("dashboard"))
    except Exception as e:
        return f"Error login: {e}"

@app.route("/dashboard")
def dashboard():
    if "token" not in session: return redirect(url_for("index"))
    return render_template("dashboard.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    if "token" not in session: return redirect(url_for("index"))
    palabra = request.form.get("palabra", "").strip().lower()
    temas = request.form.getlist("temas")
    archivo = request.files.get("archivo_tweets")
    
    if not archivo: 
        return "Error: sube un archivo", 400

    try:
        contenido_crudo = archivo.read().decode('utf-8').strip()
        
        if contenido_crudo.startswith("window.YTD"):
            inicio = contenido_crudo.find('[')
            if inicio != -1:
                contenido_crudo = contenido_crudo[inicio:]
                
        datos = []
        decoder = json.JSONDecoder()
        idx = 0
        longitud = len(contenido_crudo)
        
        while idx < longitud:
            while idx < longitud and (contenido_crudo[idx].isspace() or contenido_crudo[idx] in [',', ';']):
                idx += 1
            if idx >= longitud: break
            try:
                obj, avance = decoder.raw_decode(contenido_crudo[idx:])
                if isinstance(obj, list): datos.extend(obj)
                else: datos.append(obj)
                idx += avance
            except Exception as e:
                if len(datos) > 0: break
                else: raise Exception(f"Formato ilegible: {str(e)}")
                    
        if len(datos) == 0: raise Exception("El archivo estaba vacío.")

    except Exception as e:
        return f"<h3>Error leyendo el archivo</h3><p><b>Detalle técnico:</b> {str(e)}</p>", 400

    todos_los_tweets = []
    for item in datos:
        if isinstance(item, dict):
            t = item.get("tweet", item)
            id_str = t.get("id_str") or t.get("id")
            texto = t.get("full_text") or t.get("text")
            if id_str and texto:
                todos_los_tweets.append({"id": str(id_str), "texto": str(texto)})
                
    # LIMITAMOS A LOS PRIMEROS 30 TWEETS DEL ARCHIVO
    todos_los_tweets = todos_los_tweets[:30]
    polemicos = []

    # Busqueda por palabra clave manual
    if palabra:
        for tw in todos_los_tweets:
            if palabra in tw["texto"].lower():
                polemicos.append({"id": tw["id"], "texto": tw["texto"], "motivo": f"Palabra: {palabra}"})
        return render_template("resultados.html", polemicos=polemicos)

    # ATAQUE RELÁMPAGO: Le enviamos todo a la IA de una sola vez
    error_ia = None
    if todos_los_tweets:
        ids_encontrados, error = analizar_todo_con_ia(todos_los_tweets, temas)
        if error:
            error_ia = error
        else:
            mapa_tweets = {tw["id"]: tw["texto"] for tw in todos_los_tweets}
            for id_pol in ids_encontrados:
                id_s = str(id_pol)
                if id_s in mapa_tweets:
                    polemicos.append({"id": id_s, "texto": mapa_tweets[id_s], "motivo": "Detectado por IA"})

    return render_template("resultados.html", polemicos=polemicos, error=error_ia)

@app.route("/delete", methods=["POST"])
def delete():
    if "token" not in session: return redirect(url_for("index"))
    ids = request.form.getlist("ids_borrar")
    token_data = session["token"]
    access_token = token_data.get('access_token') if isinstance(token_data, dict) else token_data
    import time
    client = tweepy.Client(access_token=access_token, consumer_key=CLIENT_ID, consumer_secret=CLIENT_SECRET)
    borrados, errores = 0, 0
    for tid in ids:
        try:
            client.delete_tweet(tid)
            borrados += 1
            time.sleep(0.3)
        except: errores += 1
    return render_template("resultado_borrado.html", borrados=borrados, errores=errores)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
