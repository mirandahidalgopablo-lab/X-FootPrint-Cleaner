import os
import json
import tweepy
import time
from flask import Flask, redirect, url_for, session, request, render_template, jsonify
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
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

@app.route("/api/analyze_batch", methods=["POST"])
def analyze_batch():
    if "token" not in session: return jsonify({"error": "No autorizado"}), 401
    if not GEMINI_API_KEY: return jsonify({"error": "Falta GEMINI_API_KEY en Render"}), 500

    datos = request.json
    tweets = datos.get("tweets", [])
    temas = datos.get("temas", [])

    if not tweets: return jsonify({"ids_polemicos": []})

    modelo = genai.GenerativeModel("gemini-flash-latest")
    lista_tweets = "\n".join([f'ID:"{tw["id"]}" | TEXTO: {tw["texto"]}' for tw in tweets])
    criterio = f"contenido de {', '.join(temas)}" if temas else "contenido ofensivo, toxico o polemico"

    prompt = f"""Analiza estos tweets y devuelve SOLO un array JSON con los IDs de los que sean {criterio}.
    Si no hay ninguno, devuelve []. No escribas nada mas.
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
        ids_detectados = json.loads(respuesta.text.strip())
        return jsonify({"ids_polemicos": [str(i) for i in ids_detectados], "error": None})
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg: return jsonify({"error": "Límite de Google alcanzado. Espera unos minutos."})
        return jsonify({"error": error_msg})

@app.route("/delete", methods=["POST"])
def delete():
    if "token" not in session: return redirect(url_for("index"))
    
    ids = request.form.getlist("ids_borrar")
    token_data = session["token"]
    
    access_token = token_data.get('access_token') if isinstance(token_data, dict) else token_data
    
    import time

    client = tweepy.Client(bearer_token=access_token)
    
    borrados, errores = 0, 0
    for tid in ids:
        try:
      
            client.delete_tweet(tid)
            borrados += 1
            time.sleep(0.4)
        except Exception as e:
            print(f"Error al borrar {tid}: {e}") 
            errores += 1
            
    return render_template("resultado_borrado.html", borrados=borrados, errores=errores)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
