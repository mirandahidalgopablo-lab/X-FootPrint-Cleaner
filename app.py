import os
import json
import tweepy
import time
import google.generativeai as genai
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

def analizar_lote_con_ia(tweets_lote, temas):
    if not GEMINI_API_KEY:
        return [], "Sin clave GEMINI_API_KEY configurada"

    modelo = genai.GenerativeModel("gemini-2.0-flash-lite")

    lista_tweets = ""
    for tw in tweets_lote:
        lista_tweets += f'ID:{tw["id"]} | TEXTO: {tw["texto"]}\n'

    criterio = f"contenido relacionado con: {', '.join(temas)}" if temas else "contenido ofensivo, toxico, agresivo o polemico"

    prompt = f"""Eres un auditor. Analiza los tweets y devuelve SOLO un array JSON con los IDs de los que contienen {criterio}.
    Si no hay ninguno responde: []
    Tweets:
    {lista_tweets}"""

    try:
        respuesta = modelo.generate_content(prompt)
        texto = respuesta.text.strip().replace("```json", "").replace("```", "").strip()
        ids_polemicos = json.loads(texto)
        return [str(i) for i in ids_polemicos], None
    except Exception as e:
        return [], str(e)

@app.route("/")
def index():
    login_url = oauth2_handler.get_authorization_url()
    return render_template("index.html", login_url=login_url)

@app.route("/callback")
def callback():
    try:
        url_segura = request.url
        if REDIRECT_URI and REDIRECT_URI.startswith("https") and url_segura.startswith("http:"):
            url_segura = url_segura.replace("http:", "https:", 1)
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
    todos_los_tweets = [{"id": i.get("tweet",{}).get("id_str"), "texto": i.get("tweet",{}).get("full_text", "")} 
                        for i in datos if i.get("tweet",{}).get("id_str")]

    polemicos = []

    if palabra:
        for tw in todos_los_tweets:
            if palabra in tw["texto"].lower():
                polemicos.append({"id": tw["id"], "texto": tw["texto"], "motivo": f"Palabra: {palabra}"})
        return render_template("resultados.html", polemicos=polemicos)

    TAMANO_LOTE = 20
    ids_encontrados_total = []
    error_ia = None

    for i in range(0, len(todos_los_tweets), TAMANO_LOTE):
        lote = todos_los_tweets[i:i + TAMANO_LOTE]
        ids, error = analizar_lote_con_ia(lote, temas)
        if error:
            error_ia = error
            break
        ids_encontrados_total.extend(ids)
        if i + TAMANO_LOTE < len(todos_los_tweets):
            time.sleep(5)

    mapa_tweets = {tw["id"]: tw["texto"] for tw in todos_los_tweets}
    for id_pol in ids_encontrados_total:
        if str(id_pol) in mapa_tweets:
            polemicos.append({"id": str(id_pol), "texto": mapa_tweets[str(id_pol)], "motivo": "Detectado por IA"})

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
            time.sleep(0.3)
        except: errores += 1
    return render_template("resultado_borrado.html", borrados=borrados, errores=errores)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
