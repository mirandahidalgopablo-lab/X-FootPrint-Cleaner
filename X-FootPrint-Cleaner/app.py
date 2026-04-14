import os
import json
import tweepy
import time
from flask import Flask, redirect, url_for, session, request, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

# --- SEGURIDAD 4: Proxy Fix para servidores (Render) ---
# Le dice a Flask que confíe en el HTTPS que proporciona el servidor de Render
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# --- SEGURIDAD 1: Variables de Entorno (Ocultar Secretos) ---
app.secret_key = os.environ.get("SECRET_KEY", "clave_super_secreta_local")
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
# En Render pondrás tu URL pública, en local usará 127.0.0.1
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://127.0.0.1:5000/callback")

# --- SEGURIDAD 3: HTTPS y Cookies ---
app.config['SESSION_COOKIE_HTTPONLY'] = True

if REDIRECT_URI.startswith("https"):
    app.config['SESSION_COOKIE_SECURE'] = True
else:

    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

oauth2_handler = tweepy.OAuth2UserHandler(
    client_id=CLIENT_ID,
    redirect_uri=REDIRECT_URI,
    scope=["tweet.read", "tweet.write", "users.read", "offline.access"],
    client_secret=CLIENT_SECRET
)

@app.route('/')
def index():
    login_url = oauth2_handler.get_authorization_url()

    return render_template('index.html', login_url=login_url)

@app.route('/callback')
def callback():
    try:
        access_token = oauth2_handler.fetch_token(request.url)
        session['token'] = access_token
        return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Error de seguridad en login: {e}"

@app.route('/dashboard')
def dashboard():
    if 'token' not in session: return redirect(url_for('index'))
    return render_template('dashboard.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'token' not in session: return redirect(url_for('index'))
    
    palabra = request.form.get('palabra', '').lower()
    temas = request.form.getlist('temas')
    
    archivo = request.files.get('archivo_tweets')
    if not archivo or not archivo.filename.endswith('.json'):
        return "Por favor, sube un archivo .json válido.", 400
    datos = json.load(archivo)
    
    polemicos = []
    for item in datos:
        t = item.get('tweet', {})
        texto = t.get('full_text', '')
        id_tweet = t.get('id_str')
        
        es_polemico = False
        motivo = ""

        if palabra and palabra in texto.lower():
            es_polemico = True
            motivo = f"Palabra '{palabra}'"
        elif any(tema.lower() in texto.lower() for tema in temas):
            es_polemico = True
            motivo = "Coincidencia de categoría"

        if es_polemico:
            polemicos.append({'id': id_tweet, 'texto': texto, 'motivo': motivo})

    return render_template('resultados.html', polemicos=polemicos[:100])

@app.route('/delete', methods=['POST'])
def delete():
    if 'token' not in session: return redirect(url_for('index'))
    
    ids = request.form.getlist('ids_borrar')
    access_token = session['token']['access_token']
    client = tweepy.Client(bearer_token=access_token)
    
    borrados = 0
    for tid in ids:
        try:
            client.delete_tweet(tid, user_auth=False)
            borrados += 1
            time.sleep(0.2) 
        except Exception:
            continue
            
    return f"<h3>Proceso terminado</h3><p>Se borraron {borrados} tweets.</p><a href='/dashboard'>Volver</a>"

if __name__ == '__main__':
    app.run(port=5000)