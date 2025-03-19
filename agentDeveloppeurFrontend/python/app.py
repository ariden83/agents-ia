import logging
import re
import time
import json
import re
import subprocess
import threading
import time
import os
from threading import Event
from pathlib import Path
from dotenv import load_dotenv

import boto3
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# Charger les variables d'environnement du fichier .env
dotenv_path = Path(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))
load_dotenv(dotenv_path=dotenv_path)

# Configuration AWS - utiliser le profil spécifié dans le .env ou utiliser les identifiants par défaut si non spécifié
aws_profile = os.getenv("AWS_PROFILE")
if aws_profile:
    try:
        boto3.setup_default_session(profile_name=aws_profile)
        print(f"Session AWS initialisée avec le profil '{aws_profile}'")
    except Exception as e:
        print(f"Impossible d'utiliser le profil AWS spécifié ({aws_profile}): {str(e)}")
        print("Utilisation des identifiants AWS par défaut")
else:
    print("Aucun profil AWS spécifié dans .env, utilisation des identifiants AWS par défaut")

# Configuration du modèle Claude depuis les variables d'environnement
REGION_NAME = os.getenv("REGION_NAME", "eu-west-3")
MODEL_ID = os.getenv("MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")  # Utilise la valeur du .env ou la valeur par défaut

# Chemin vers l'exécutable Cursor
CURSOR_PATH = "/home/adrien.parrochia/go/src/github.com/agentsIA/agentDeveloppeurFrontend/cursor/cursor-0.45.14x86_64.AppImage"

# Dossier de travail pour les projets
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'developpeurfrontend.log')

# Configuration du logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()  # Pour afficher les logs aussi dans la console
    ]
)
logger = logging.getLogger(__name__)
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

def safe_emit(event, data=None):
    """
    Émet un événement SocketIO de manière sécurisée, en capturant les erreurs potentielles.
    
    Args:
        event (str): Nom de l'événement à émettre
        data (dict, optional): Données à envoyer avec l'événement
    """
    try:
        # Émettre l'événement à tous les clients
        socketio.emit(event, data)
        time.sleep(0.01)  # Petit délai pour permettre à l'événement d'être traité
        
        # Journalisation des événements
        if event == 'log' and data and 'type' in data and 'message' in data:
            log_type = data['type']
            message = data['message']
            
            if log_type == 'error':
                logger.error(message)
            elif log_type == 'warning':
                logger.warning(message)
            elif log_type == 'success':
                logger.info(f"SUCCESS: {message}")
            else:
                logger.info(message)
        else:
            # Journaliser les autres événements
            if data is not None:
                logger.debug(f"Event émis: {event}, data: {str(data)[:200]}...")
            else:
                logger.debug(f"Event émis: {event}, data: None")
            
    except Exception as e:
        error_msg = f"Erreur lors de l'émission de l'événement {event}: {str(e)}"
        logger.error(error_msg)
        
        # Tentative de réémission avec un délai
        try:
            time.sleep(0.5)  # Attendre un peu avant de réessayer
            socketio.emit(event, data)
            logger.info(f"Réémission réussie de l'événement {event}")
        except Exception as retry_err:
            logger.error(f"Échec de la réémission de l'événement {event}: {str(retry_err)}")
            # Continuer l'exécution malgré l'erreur

user_action_event = Event()

# Créer le dossier workspace s'il n'existe pas
if not os.path.exists(WORKSPACE_DIR):
    os.makedirs(WORKSPACE_DIR)

@app.route('/')
def index():
    return render_template('index.html')

def wait_for_user_confirmation():
    """Met en pause le script jusqu'à confirmation de l'utilisateur."""
    user_action_event.clear()
    socketio.emit('wait_for_user_action', {})
    user_action_event.wait()
    time.sleep(1)

@socketio.on('user_action_done')
def handle_user_action_done():
    """Déclenchement après confirmation de l'utilisateur."""
    user_action_event.set()

def invoke_claude(prompt, system_prompt=None, max_tokens=4096, temperature=0.7):
    """
    Invoque Claude via AWS Bedrock avec le prompt fourni.
    
    Args:
        prompt (str): Le prompt principal à envoyer au modèle
        system_prompt (str, optional): Instructions système pour guider le comportement du modèle
        max_tokens (int, optional): Nombre maximum de tokens pour la réponse
        temperature (float, optional): Niveau de créativité (0.0-1.0)
    
    Returns:
        str: Réponse du modèle
    """
    socketio.emit('loading_start')
    socketio.emit('log', {'type': 'info', 'message': "Invocation de Claude en cours..."})
    
    try:
        bedrock_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=REGION_NAME
        )
        
        # Construction du corps de la requête
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        # Ajout du système prompt si fourni
        if system_prompt:
            request_body["system"] = system_prompt
        
        # Invocation du modèle
        response = bedrock_client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(request_body)
        )
        
        # Traitement de la réponse
        response_body = json.loads(response.get('body').read())
        generated_text = response_body.get('content')[0].get('text')
        
        socketio.emit('log', {'type': 'success', 'message': "Réponse de Claude reçue"})
        socketio.emit('loading_end')
        
        return generated_text
    
    except Exception as e:
        error_message = f"Erreur lors de l'invocation de Claude: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        socketio.emit('loading_end')
        return error_message

def create_project_structure(project_name):
    """
    Crée la structure de base d'un projet frontend
    
    Args:
        project_name (str): Nom du projet
        
    Returns:
        str: Chemin du projet créé
    """
    socketio.emit('log', {'type': 'info', 'message': f"Création de la structure du projet {project_name}..."})
    
    # Créer un nom de dossier valide à partir du nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    # Créer les sous-dossiers standard
    for subdir in ['src', 'public', 'src/components', 'src/assets', 'src/styles']:
        os.makedirs(os.path.join(project_dir, subdir), exist_ok=True)
    
    socketio.emit('log', {'type': 'success', 'message': f"Structure du projet créée dans {project_dir}"})
    return project_dir

def generate_frontend_code(specs, project_dir):
    """
    Génère le code frontend en utilisant Claude
    
    Args:
        specs (dict): Spécifications du projet
        project_dir (str): Chemin vers le dossier du projet
        
    Returns:
        dict: Structure des fichiers générés
    """
    socketio.emit('log', {'type': 'info', 'message': "Génération du code frontend..."})
    
    # Système prompt pour guider Claude à générer du code frontend
    system_prompt = """
    Vous êtes un développeur frontend expert. Vous devez générer le code pour une application
    web moderne en fonction des spécifications fournies.
    
    Voici les instructions à suivre:
    
    1. Analysez attentivement les spécifications et les exigences techniques
    2. Utilisez React, Vue.js ou un autre framework moderne selon les spécifications
    3. Créez une architecture propre et maintenable
    4. Privilégiez les composants réutilisables et modulaires
    5. Ajoutez des commentaires explicatifs pour faciliter la compréhension
    6. Générez un design responsive et moderne
    7. Implémentez les meilleures pratiques d'accessibilité
    
    Pour chaque fichier, vous devez fournir le chemin relatif et le contenu complet.
    Votre réponse doit être au format suivant:
    
    ```json
    [
      {
        "file_path": "chemin/relatif/du/fichier.js",
        "content": "contenu complet du fichier"
      },
      ...
    ]
    ```
    
    Le chemin relatif doit être basé sur la racine du projet. Par exemple, pour un fichier
    dans le dossier src/components, le chemin sera "src/components/MonComposant.js".
    """
    
    # Construction du prompt pour générer le code frontend
    prompt = f"""
    Voici les spécifications d'un projet frontend:
    
    {json.dumps(specs, indent=2)}
    
    Veuillez générer le code complet pour cette application frontend selon les spécifications.
    Fournissez tous les fichiers nécessaires (HTML, CSS, JavaScript, etc.) pour que l'application
    soit fonctionnelle.
    
    Assurez-vous d'inclure:
    - Les fichiers de configuration (package.json, etc.)
    - Les composants React/Vue.js
    - Les fichiers CSS/SCSS
    - Les assets nécessaires (à décrire)
    """
    
    # Invocation de Claude
    response = invoke_claude(prompt, system_prompt, max_tokens=8000)
    
    # Extraction du JSON de la réponse
    try:
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        
        if json_match:
            files_json = json.loads(json_match.group(1))
            
            # Écriture des fichiers
            for file_info in files_json:
                file_path = os.path.join(project_dir, file_info['file_path'])
                
                # Créer les dossiers parents si nécessaire
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                
                # Écrire le contenu du fichier
                with open(file_path, 'w') as f:
                    f.write(file_info['content'])
                
                socketio.emit('log', {'type': 'info', 'message': f"Fichier créé: {file_info['file_path']}"})
            
            socketio.emit('log', {'type': 'success', 'message': f"Code frontend généré avec succès ({len(files_json)} fichiers)"})
            return files_json
        else:
            # Tentative d'extraction manuelle si le format JSON n'est pas trouvé
            files_matches = re.findall(r'fichier\s*:\s*`([^`]+)`\s*```[a-z]*\s*(.*?)\s*```', response, re.DOTALL)
            
            if files_matches:
                files_json = []
                for file_path, content in files_matches:
                    files_json.append({
                        "file_path": file_path.strip(),
                        "content": content.strip()
                    })
                
                # Écriture des fichiers
                for file_info in files_json:
                    file_path = os.path.join(project_dir, file_info['file_path'])
                    
                    # Créer les dossiers parents si nécessaire
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    
                    # Écrire le contenu du fichier
                    with open(file_path, 'w') as f:
                        f.write(file_info['content'])
                    
                    socketio.emit('log', {'type': 'info', 'message': f"Fichier créé: {file_info['file_path']}"})
                
                socketio.emit('log', {'type': 'success', 'message': f"Code frontend généré avec succès ({len(files_json)} fichiers)"})
                return files_json
            else:
                # Fallback: Créer un seul fichier avec la réponse complète
                fallback_path = os.path.join(project_dir, "claude_response.md")
                with open(fallback_path, 'w') as f:
                    f.write(response)
                
                socketio.emit('log', {'type': 'warning', 'message': "Format JSON non trouvé, réponse brute sauvegardée"})
                return [{"file_path": "claude_response.md", "content": response}]
    
    except Exception as e:
        error_message = f"Erreur lors de la génération du code: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        
        # Créer un fichier d'erreur
        error_path = os.path.join(project_dir, "error.txt")
        with open(error_path, 'w') as f:
            f.write(f"Error: {str(e)}\n\nResponse:\n{response}")
        
        return [{"file_path": "error.txt", "content": error_message, "error": True}]

def open_with_cursor(project_dir):
    """
    Ouvre le projet avec Cursor
    
    Args:
        project_dir (str): Chemin vers le dossier du projet
        
    Returns:
        bool: True si Cursor a été ouvert avec succès, False sinon
    """
    socketio.emit('log', {'type': 'info', 'message': "Ouverture du projet avec Cursor..."})
    
    try:
        # Vérifier si le chemin vers Cursor existe
        if not os.path.exists(CURSOR_PATH):
            socketio.emit('log', {'type': 'error', 'message': f"Cursor non trouvé à l'emplacement: {CURSOR_PATH}"})
            return False
        
        # Lancer Cursor en arrière-plan
        subprocess.Popen([CURSOR_PATH, project_dir], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL, 
                         start_new_session=True)
        
        socketio.emit('log', {'type': 'success', 'message': "Projet ouvert avec Cursor"})
        return True
    
    except Exception as e:
        error_message = f"Erreur lors de l'ouverture avec Cursor: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return False

def extract_code_blocks(text):
    """
    Extrait les blocs de code d'un texte markdown
    
    Args:
        text (str): Le texte contenant potentiellement des blocs de code
    
    Returns:
        list: Liste des blocs de code extraits
    """
    code_blocks = re.findall(r'```(?:[a-zA-Z]*\n)?(.*?)```', text, re.DOTALL)
    return code_blocks

@app.route('/frontend_request', methods=['POST'])
def frontend_request():
    """Endpoint pour recevoir et traiter les demandes de développement frontend"""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande de développement frontend"})
    
    data = request.json
    specs = data.get('specs', {})
    project_name = specs.get('title', 'frontend-project') if isinstance(specs, dict) else 'frontend-project'
    open_cursor = data.get('open_cursor', False)
    
    try:
        # Phase 1: Créer la structure du projet
        project_dir = create_project_structure(project_name)
        socketio.emit('project_dir_update', {'project_dir': project_dir})
        
        # Phase 2: Générer le code frontend
        generated_files = generate_frontend_code(specs, project_dir)
        socketio.emit('files_update', {'files': generated_files})
        
        # Phase 3: Ouvrir avec Cursor si demandé
        cursor_result = False
        if open_cursor:
            cursor_result = open_with_cursor(project_dir)
        
        # Préparation de la réponse
        response = {
            'project_dir': project_dir,
            'files': generated_files,
            'cursor_opened': cursor_result
        }
        
        socketio.emit('log', {'type': 'success', 'message': "Développement frontend terminé"})
        socketio.emit('frontend_complete')
        
        return jsonify(response)
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message})

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5003)


@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent developpeurfrontend"})
    
    except Exception as e:
        logger.error(f"Erreur lors de la gestion de la connexion: {str(e)}")

@socketio.on('request_logs')
def handle_request_logs():
    """Gestionnaire d'événement pour la demande de logs"""
    try:
        logger.info("Demande de logs reçue")
        # Envoyer un accusé de réception
        safe_emit('log', {'type': 'info', 'message': "Chargement des logs en cours..."})
        
        # Lire les dernières entrées du fichier de log pour les afficher dans l'interface
        try:
            log_path = os.path.join(log_dir, 'developpeurfrontend.log')
            if os.path.exists(log_path):
                with open(log_path, 'r') as log_file:
                    # Lire les 50 dernières lignes du fichier
                    lines = log_file.readlines()
                    last_lines = lines[-50:] if len(lines) > 50 else lines
                    
                    for line in last_lines:
                        # Ajouter un petit délai pour éviter la saturation
                        time.sleep(0.01)
                        
                        # Déterminer le type de log (info, error, warning) basé sur le contenu
                        log_type = 'info'
                        if '[ERROR]' in line:
                            log_type = 'error'
                        elif '[WARNING]' in line:
                            log_type = 'warning'
                        elif 'SUCCESS' in line:
                            log_type = 'success'
                        
                        # Extraire le message (tout après le niveau de log)
                        message_match = re.search(r'\[(INFO|ERROR|WARNING)\]\s*(.*)', line)
                        if message_match:
                            message = message_match.group(2)
                        else:
                            message = line.strip()
                        
                        # Envoyer au client
                        safe_emit('log', {'type': log_type, 'message': f"[LOG] {message}"})
                
                safe_emit('log', {'type': 'info', 'message': "---- Fin des logs précédents ----"})
            else:
                safe_emit('log', {'type': 'warning', 'message': "Fichier de log introuvable"})
        except Exception as log_err:
            logger.error(f"Erreur lors de la lecture des logs: {str(log_err)}")
            safe_emit('log', {'type': 'error', 'message': f"Impossible de charger les logs précédents: {str(log_err)}"})
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement de la demande de logs: {str(e)}")

if __name__ == '__main__':
    # Initialiser le client Bedrock
    bedrock_client = boto3.client(
        service_name='bedrock-runtime',
        region_name=REGION_NAME,
    )
    
    # Créer le dossier workspace s'il n'existe pas
    if not os.path.exists(WORKSPACE_DIR):
        os.makedirs(WORKSPACE_DIR)
    
    # Démarrer le serveur Flask avec SocketIO
    start_socketio()