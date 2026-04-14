import os
import json
import tweepy
import time
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

# CONFIGURACIÓN REFORZADA
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

oauth2_handler = tweepy.OAuth2UserHandler(
    client_id=CLIENT_ID,
    redirect_uri=REDIRECT_URI,
    scope=["tweet.read", "tweet.write", "users.read", "offline.access"],
    client_secret=CLIENT_SECRET
)

def analizar_lote_con_ia(tweets_lote, temas):
    if not GEMINI_API_KEY:
        return [], "Falta GEMINI_API_KEY"

    # Probamos con el nombre base sin prefijos
    modelo = genai.GenerativeModel("gemini-1.5-flash")

    lista_tweets = ""
    for tw in tweets_lote:
        lista_tweets += f'ID:{tw["id"]} TEXTO:{tw["texto"]}\n'

    criterio = f"contenido de {', '.join(temas)}" if temas else "contenido toxico o polemico"

    prompt = f"""Analiza estos tweets y devuelve SOLO un array JSON con los IDs de los que sean {criterio}.
    Si no hay ninguno, devuelve []. No escribas nada mas que el JSON.
    Tweets:
    {lista_tweets}"""

    try:
        # Quitamos el response_mime_type temporalmente para maximizar compatibilidad
        respuesta = modelo.generate_content(
            prompt,
            safety_settings={
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        
        texto_limpio = respuesta.text.strip().replace("```json", "").replace("```", "").strip()
        ids_raw = json.loads(texto_limpio)
        return [str(i) for i in ids_raw], None
    except Exception as e:
        return [], f"Error detectado: {str(e)}"

@app.route("/")
def index():
    login_url = oauth2_handler.get_authorization_url()
    return render_template("index.html", login_url=login_url)

@app.route("/callback")
def callback():
    try:
        url_segura = request.url.replace("http:", "https:", 1) if REDIRECT_URI.startswith("https") else request.url
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
    if not archivo: return "Error: sube un archivo .json", 400

    datos = json.load(archivo)
    todos_los_tweets = [{"id": i.get("tweet",{}).get("id_str"), "texto": i.get("tweet",{}).get("full_text", "")} for i in datos if i.get("tweet",{}).get("id_str")]

    polemicos = []
    if palabra:
        for tw in todos_los_tweets:
            if palabra in tw["texto"].lower():
                polemicos.append({"id": tw["id"], "texto": tw["texto"], "motivo": f"Palabra clave: {palabra}"})
        return render_template("resultados.html", polemicos=polemicos)

    # Lotes pequeños y esperas para no quemar la cuota
    TAMANO_LOTE = 10
    ids_polemicos_total = []
    error_ia = None

    for i in range(0, len(todos_los_tweets), TAMANO_LOTE):
        lote = todos_los_tweets[i:i + TAMANO_LOTE]
        ids, error = analizar_lote_con_ia(lote, temas)
        if error:
            error_ia = error
            break
        ids_polemicos_total.extend(ids)
        time.sleep(5)

    mapa_tweets = {tw["id"]: tw["texto"] for tw in todos_los_tweets}
    for id_pol in ids_polemicos_total:
        if id_pol in mapa_tweets:
            polemicos.append({"id": id_pol, "texto": mapa_tweets[id_pol], "motivo": "Detectado por IA"})

    return render_template("resultados.html", polemicos=polemicos, error=error_ia)

@app.route("/delete", methods=["POST"])
def delete():
    if "token" not in session: return redirect(url_for("index"))
    ids = request.form.getlist("ids_borrar")
    token_data = session["token"]
    access_token = token_data.get("access_token") if isinstance(token_data, dict) else token_data
    client = tweepy.Client(access_token=access_token, consumer_key=CLIENT_ID, consumer_secret=CLIENT_SECRET)
    borrados, errores = 0, 0
    for tid in ids:
        try:
            client.delete_tweet(tid)
            borrados += 1
            time.sleep(0.4)
        except: errores += 1
    return render_template("resultado_borrado.html", borrados=borrados, errores=errores)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
