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

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
ia_model = genai.GenerativeModel('gemini-1.5-flash')

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
        url_segura = request.url
        if REDIRECT_URI and REDIRECT_URI.startswith("https") and url_segura.startswith("http:"):
            url_segura = url_segura.replace("http:", "https:", 1)
        access_token = oauth2_handler.fetch_token(url_segura)
        session['token'] = access_token
        return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Error: {e}"

@app.route('/dashboard')
def dashboard():
    if 'token' not in session: return redirect(url_for('index'))
    return render_template('dashboard.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'token' not in session: return redirect(url_for('index'))
    
    palabra = request.form.get('palabra', '').strip().lower()
    temas = request.form.getlist('temas')
    archivo = request.files.get('archivo_tweets')
    
    if not archivo: return "Error: Sube un archivo .json", 400
    
    datos = json.load(archivo)
    polemicos = []

    for item in datos:
        t = item.get('tweet', {})
        texto = t.get('full_text', '')
        id_tweet = t.get('id_str')
        
        es_polemico = False
        motivo = ""

        if palabra != "" and palabra in texto.lower():
            es_polemico = True
            motivo = f"Palabra clave: {palabra}"
        
        else:
            try:
                if not palabra and not temas:
                    prompt = f"Eres un auditor imparcial. Analiza si este tweet es ofensivo, tóxico, agresivo, machista, racista o inapropiado. Responde solo con la palabra SI o la palabra NO: '{texto}'"
                else:
                    prompt = f"Eres un auditor imparcial. ¿Este tweet tiene un tono de {', '.join(temas)}? Responde solo con la palabra SI o la palabra NO: '{texto}'"
            
                response = ia_model.generate_content(
                    prompt,
                    safety_settings={
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }
                )
                
                if "SI" in response.text.upper():
                    es_polemico = True
                    motivo = "Auditado por IA"
                
                time.sleep(4)
            except Exception as e:
                print(f"Error IA: {e}")
                time.sleep(4)
                continue

        if es_polemico:
            polemicos.append({'id': id_tweet, 'texto': texto, 'motivo': motivo})

    return render_template('resultados.html', polemicos=polemicos)

@app.route('/delete', methods=['POST'])
def delete():
    if 'token' not in session: return redirect(url_for('index'))
    ids = request.form.getlist('ids_borrar')
    token_data = session['token']
    access_token = token_data.get('access_token') if isinstance(token_data, dict) else token_data
    
    client = tweepy.Client(access_token=access_token, consumer_key=CLIENT_ID, consumer_secret=CLIENT_SECRET)
    
    borrados, errores = 0, 0
    for tid in ids:
        try:
            client.delete_tweet(tid)
            borrados += 1
            time.sleep(0.5)
        except:
            errores += 1
            
    return render_template('resultados_borrado.html', borrados=borrados, errores=errores)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
