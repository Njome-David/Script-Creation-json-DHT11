from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from dotenv import load_dotenv
import os
import requests
import json
import logging

# Chargement des variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="API DHT11 Data Receiver", version="1.0")

# --- CONFIGURATION DEPUIS .env ---
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GIST_ID = os.getenv('GIST_ID')
FILE_NAME = os.getenv('FILE_NAME', 'data.json')
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

# Vérification que les variables sont définies
if not GITHUB_TOKEN or not GIST_ID:
    logger.error("❌ GITHUB_TOKEN ou GIST_ID non définis dans .env")
    raise ValueError("Variables d'environnement manquantes")

headers = {"Authorization": f"token {GITHUB_TOKEN}"}
gist_url = f"https://api.github.com/gists/{GIST_ID}"

logger.info(f"✅ Configuration chargée depuis .env")
logger.info(f"📁 Fichier cible: {FILE_NAME}")
logger.info(f"🐛 Mode DEBUG: {DEBUG}")

# --- MODÈLES DE DONNÉES ---
class SensorData(BaseModel):
    raw_values: list

class DataResponse(BaseModel):
    status: str
    message: str
    timestamp: str = None
    record_count: int = None

# --- FONCTIONS UTILITAIRES ---
def get_gist_content():
    """Récupère le contenu actuel du Gist"""
    try:
        response = requests.get(gist_url, headers=headers, timeout=10)
        if response.status_code == 200:
            gist_data = response.json()
            content = gist_data['files'][FILE_NAME]['content']
            return json.loads(content)
        else:
            logger.error(f"❌ Erreur lecture Gist: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"❌ Erreur lors de la lecture du Gist: {e}")
        return None

def update_gist_content(new_entry):
    """Met à jour le Gist avec la nouvelle entrée"""
    try:
        # Lecture du contenu actuel
        current_content = get_gist_content()
        if current_content is None:
            current_content = []
        
        # Ajout de la nouvelle entrée
        current_content.append(new_entry)
        
        # PAS DE LIMITE - On garde TOUTES les données
        # (Si vous voulez quand même une limite, décommentez la ligne ci-dessous)
        # if len(current_content) > 1000:
        #     current_content = current_content[-1000:]
        
        # Préparation de la mise à jour
        payload = {
            "files": {
                FILE_NAME: {
                    "content": json.dumps(current_content, indent=4, ensure_ascii=False)
                }
            }
        }
        
        # Envoi de la mise à jour
        patch_response = requests.patch(
            gist_url, 
            headers=headers, 
            json=payload, 
            timeout=10
        )
        
        if patch_response.status_code == 200:
            return True, len(current_content)
        else:
            logger.error(f"❌ Échec écriture Gist: {patch_response.status_code}")
            logger.debug(f"Réponse: {patch_response.text}")
            return False, len(current_content)
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de la mise à jour: {e}")
        return False, 0

# --- ROUTES API ---
@app.get("/")
async def root():
    """Endpoint de vérification"""
    return {
        "status": "online",
        "message": "API DHT11 Data Receiver",
        "version": "1.0",
        "config": {
            "gist_id": GIST_ID[:10] + "..." if GIST_ID else None,
            "file": FILE_NAME,
            "debug": DEBUG
        }
    }

@app.get("/health")
async def health():
    """Vérification de la santé du service et de la connexion GitHub"""
    try:
        test = requests.get(gist_url, headers=headers, timeout=5)
        return {
            "status": "healthy",
            "github_connection": test.status_code == 200,
            "github_status": test.status_code
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "github_connection": False,
            "error": str(e)
        }

@app.get("/data/count")
async def get_record_count():
    """Retourne le nombre d'enregistrements dans le Gist"""
    content = get_gist_content()
    if content is not None:
        return {"count": len(content)}
    raise HTTPException(status_code=500, detail="Impossible de lire le Gist")

@app.post("/api/data")
async def receive_and_save_data(data: SensorData):
    """
    Reçoit les données du capteur et les sauvegarde dans le Gist
    """
    # Validation
    if len(data.raw_values) < 2:
        raise HTTPException(status_code=400, detail="Données incomplètes")
    
    try:
        # Conversion et création de l'entrée
        humidity = float(data.raw_values[0])
        temperature = float(data.raw_values[1])
    except ValueError:
        raise HTTPException(status_code=400, detail="Données invalides (nombres attendus)")
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    new_entry = {
        "timestamp": current_time,
        "humidite(%)": humidity,
        "temperature(°C)": temperature
    }
    
    logger.info(f"📊 Nouvelle mesure: H:{humidity}% T:{temperature}°C")
    
    if DEBUG:
        logger.debug(f"Détails: {new_entry}")
    
    # Sauvegarde sur GitHub
    success, count = update_gist_content(new_entry)
    
    if success:
        return DataResponse(
            status="success",
            message="Donnée enregistrée sur GitHub",
            timestamp=current_time,
            record_count=count
        )
    else:
        raise HTTPException(
            status_code=500, 
            detail="Erreur lors de l'écriture sur GitHub"
        )

# Gestion des erreurs
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"⚠️ Erreur non gérée: {exc}")
    return HTTPException(
        status_code=500,
        detail=f"Erreur interne: {str(exc)}"
    )

# Point d'entrée pour le lancement direct
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)