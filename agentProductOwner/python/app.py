import logging
import re
import time
import json
import re
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

# Dossier de travail pour les suggestions du PO
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'productowner.log')

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

# Création du dossier workspace s'il n'existe pas
if not os.path.exists(WORKSPACE_DIR):
    os.makedirs(WORKSPACE_DIR)

@app.route('/')
def index():
    return render_template('index.html')

def invoke_claude(prompt, system_prompt=None, max_tokens=4096, temperature=0.8, max_retries=3, retry_delay=2):
    """
    Invoque Claude via AWS Bedrock avec le prompt fourni et une logique de retry automatique.
    
    Args:
        prompt (str): Le prompt principal à envoyer au modèle
        system_prompt (str, optional): Instructions système pour guider le comportement du modèle
        max_tokens (int, optional): Nombre maximum de tokens pour la réponse
        temperature (float, optional): Niveau de créativité (0.0-1.0)
        max_retries (int, optional): Nombre maximum de tentatives en cas d'échec
        retry_delay (int, optional): Délai en secondes entre les tentatives
    
    Returns:
        str: Réponse du modèle
    """
    socketio.emit('loading_start')
    socketio.emit('log', {'type': 'info', 'message': "Invocation de Claude en cours..."})
    
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
    
    # Tentatives avec retry automatique
    attempts = 0
    last_error = None
    
    while attempts < max_retries:
        try:
            # Incrémentation du compteur de tentatives
            attempts += 1
            
            # Création du client Bedrock (peut être regénéré à chaque tentative en cas de problème de session)
            bedrock_client = boto3.client(
                service_name='bedrock-runtime',
                region_name=REGION_NAME
            )
            
            # Invocation du modèle
            response = bedrock_client.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps(request_body)
            )
            
            # Traitement de la réponse
            response_body = json.loads(response.get('body').read())
            generated_text = response_body.get('content')[0].get('text')
            
            # Vérification que le texte généré est valide et non vide
            if not generated_text or len(generated_text.strip()) == 0:
                raise ValueError("Réponse vide reçue du modèle")
            
            socketio.emit('log', {'type': 'success', 'message': "Réponse de Claude reçue"})
            socketio.emit('loading_end')
            
            return generated_text
        
        except Exception as e:
            last_error = str(e)
            remaining_attempts = max_retries - attempts
            
            if remaining_attempts > 0:
                # Message de log informant de la nouvelle tentative
                retry_message = f"Erreur lors de l'invocation de Claude: {last_error}. Nouvelle tentative dans {retry_delay}s ({remaining_attempts} restantes)"
                socketio.emit('log', {'type': 'warning', 'message': retry_message})
                
                # Si le prompt est trop long, on peut essayer de le réduire pour la prochaine tentative
                if "too many tokens" in last_error.lower() or "exceeds the maximum token count" in last_error.lower():
                    # Réduire le prompt de 20% en conservant le début et la fin
                    original_length = len(prompt)
                    reduced_length = int(original_length * 0.8)
                    half_length = reduced_length // 2
                    prompt = prompt[:half_length] + "\n...[contenu réduit pour respecter les limites de tokens]...\n" + prompt[-half_length:]
                    
                    # Mettre à jour le corps de la requête
                    request_body["messages"][0]["content"] = prompt
                    socketio.emit('log', {'type': 'info', 'message': "Prompt réduit pour la nouvelle tentative"})
                
                # Attendre avant la prochaine tentative
                time.sleep(retry_delay)
                # Augmenter le délai de façon exponentielle pour les tentatives suivantes
                retry_delay = retry_delay * 2
            else:
                # Plus de tentatives disponibles, on renvoie un message d'erreur formaté
                error_message = f"Échec après {max_retries} tentatives d'invocation de Claude. Dernière erreur: {last_error}"
                socketio.emit('log', {'type': 'error', 'message': error_message})
                socketio.emit('loading_end')
                
                # Créer une réponse de secours expliquant l'échec mais permettant de continuer
                fallback_response = """
                Je n'ai pas pu générer une réponse complète en raison de problèmes techniques.
                
                Voici ce que je peux suggérer en alternative:
                1. Essayer de décomposer le problème différemment
                2. Simplifier la requête
                3. Utiliser une approche plus standard pour ce type de suggestions
                
                Je vais faire de mon mieux pour poursuivre l'analyse avec les informations disponibles.
                """
                
                return fallback_response
    
    # Ce code ne devrait jamais être atteint, mais par sécurité
    socketio.emit('loading_end')
    return "Erreur inattendue lors de l'invocation du modèle"

def generate_feature_suggestions(project_description, industry=None, target_audience=None, additional_context=None):
    """
    Génère des suggestions de fonctionnalités et de tendances pour un projet.
    
    Args:
        project_description (str): Description du projet
        industry (str, optional): Secteur d'activité
        target_audience (str, optional): Public cible
        additional_context (str, optional): Contexte supplémentaire
    
    Returns:
        str: Analyse et suggestions générées
    """
    socketio.emit('log', {'type': 'info', 'message': "Analyse des tendances et génération de suggestions..."})
    
    # Système prompt pour guider Claude à fournir des suggestions de qualité
    system_prompt = """
    Vous êtes un Product Owner expert, à la pointe des tendances technologiques et d'usage.
    Votre mission est d'analyser un projet et de recommander des fonctionnalités innovantes,
    pertinentes et alignées avec les tendances actuelles et émergentes.
    
    Dans votre réponse, vous devez:
    
    1. Analyser le projet pour comprendre son essence, ses objectifs et son contexte
    2. Identifier 5 à 8 tendances pertinentes dans ce domaine (technologiques, UX, business)
    3. Proposer 3 à 5 fonctionnalités clés inspirées de ces tendances, qui apporteraient une réelle valeur au projet
    4. Pour chaque fonctionnalité, expliquer:
       - Son alignement avec les tendances identifiées
       - Sa valeur ajoutée pour les utilisateurs
       - Sa faisabilité technique (facilité d'implémentation: Facile/Moyenne/Complexe)
       - Son potentiel ROI ou impact business (Faible/Moyen/Élevé)
    5. Conclure avec une recommandation hiérarchisée des fonctionnalités les plus prometteuses
    
    Structurez votre réponse avec les sections suivantes, en utilisant le format Markdown:
    - **Analyse du projet**
    - **Tendances pertinentes**
    - **Suggestions de fonctionnalités**
      - *Fonctionnalité 1*: Description, valeur, faisabilité, impact
      - *Fonctionnalité 2*: ...
    - **Recommandations prioritaires**
    
    Soyez créatif, mais réaliste. Vos suggestions doivent être innovantes tout en restant pertinentes et réalisables.
    """
    
    # Construction du prompt principal
    prompt = f"""
    Je cherche des idées pour enrichir mon projet avec des fonctionnalités innovantes et basées sur les tendances actuelles.
    
    Voici la description de mon projet:
    
    {project_description}
    """
    
    # Ajout des informations supplémentaires si fournies
    if industry:
        prompt += f"""
        
        Secteur d'activité: {industry}
        """
    
    if target_audience:
        prompt += f"""
        
        Public cible: {target_audience}
        """
    
    if additional_context:
        prompt += f"""
        
        Informations complémentaires:
        
        {additional_context}
        """
    
    prompt += """
    
    Veuillez me suggérer des fonctionnalités innovantes et pertinentes qui pourraient enrichir ce projet,
    en vous basant sur les tendances actuelles et émergentes dans ce domaine.
    """
    
    # Invoquer Claude pour l'analyse et les suggestions
    suggestions = invoke_claude(prompt, system_prompt, max_tokens=4000, temperature=0.8)
    
    socketio.emit('log', {'type': 'success', 'message': "Suggestions de fonctionnalités générées"})
    
    return suggestions

def save_suggestions_to_file(project_name, suggestions, project_description):
    """
    Sauvegarde les suggestions générées dans un fichier Markdown.
    
    Args:
        project_name (str): Nom du projet
        suggestions (str): Suggestions générées par Claude
        project_description (str): Description du projet
    
    Returns:
        str: Chemin vers le fichier créé
    """
    socketio.emit('log', {'type': 'info', 'message': "Sauvegarde des suggestions..."})
    
    # Normaliser le nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    
    # Créer un dossier pour le projet
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    # Créer un nom de fichier avec horodatage
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    file_name = f"suggestions_{timestamp}.md"
    file_path = os.path.join(project_dir, file_name)
    
    # Construire le contenu du fichier
    content = f"""# Suggestions pour le projet: {project_name}

## Description du projet

{project_description}

## Suggestions et idées de fonctionnalités

{suggestions}

---
*Généré par l'Agent Product Owner le {time.strftime("%d/%m/%Y à %H:%M:%S")}*
"""
    
    # Écrire le contenu dans le fichier
    with open(file_path, 'w') as f:
        f.write(content)
    
    socketio.emit('log', {'type': 'success', 'message': f"Suggestions sauvegardées dans {file_path}"})
    
    return file_path

def generate_po_suggestions(project_name, project_description, industry=None, target_audience=None, additional_context=None):
    """
    Génère des suggestions de PO pour un projet.
    
    Args:
        project_name (str): Nom du projet
        project_description (str): Description du projet
        industry (str, optional): Secteur d'activité
        target_audience (str, optional): Public cible
        additional_context (str, optional): Contexte supplémentaire
    
    Returns:
        dict: Informations sur les suggestions générées
    """
    socketio.emit('log', {'type': 'info', 'message': f"Génération de suggestions PO pour {project_name}..."})
    
    # Générer les suggestions
    suggestions = generate_feature_suggestions(
        project_description, 
        industry, 
        target_audience, 
        additional_context
    )
    
    # Sauvegarder les suggestions dans un fichier
    suggestions_file = save_suggestions_to_file(project_name, suggestions, project_description)
    
    result = {
        "project_name": project_name,
        "suggestions_file": suggestions_file,
        "suggestions": suggestions
    }
    
    socketio.emit('po_complete', {
        'project_name': project_name,
        'suggestions_file': suggestions_file
    })
    
    return result

@app.route('/po_request', methods=['POST'])
def po_request():
    """Endpoint pour recevoir et traiter les demandes de suggestions du PO"""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande de suggestions PO"})
    
    data = request.json
    project_name = data.get('project_name', 'Mon Projet')
    project_description = data.get('description', '')
    industry = data.get('industry', None)
    target_audience = data.get('target_audience', None)
    additional_context = data.get('additional_context', None)
    
    if not project_description:
        return jsonify({'error': "La description du projet est requise", 'status': 'error'})
    
    try:
        # Générer les suggestions
        result = generate_po_suggestions(
            project_name,
            project_description,
            industry,
            target_audience,
            additional_context
        )
        
        return jsonify({
            'project_name': project_name,
            'suggestions_file': result['suggestions_file'],
            'suggestions': result['suggestions'],
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande de suggestions PO: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

@app.route('/api/po_suggestions', methods=['POST'])
def api_po_suggestions():
    """API endpoint pour les demandes de suggestions PO provenant d'autres agents"""
    data = request.json
    project_name = data.get('project_name', 'Mon Projet')
    project_description = data.get('description', '')
    industry = data.get('industry', None)
    target_audience = data.get('target_audience', None)
    additional_context = data.get('additional_context', None)
    
    if not project_description:
        return jsonify({'error': "La description du projet est requise", 'status': 'error'})
    
    socketio.emit('log', {'type': 'info', 'message': f"Réception d'une demande d'API pour {project_name}"})
    
    try:
        # Générer les suggestions
        result = generate_po_suggestions(
            project_name,
            project_description,
            industry,
            target_audience,
            additional_context
        )
        
        # Lire le contenu du fichier généré
        try:
            with open(result['suggestions_file'], 'r') as f:
                file_content = f.read()
        except Exception as e:
            socketio.emit('log', {'type': 'warning', 'message': f"Impossible de lire le fichier {result['suggestions_file']}: {str(e)}"})
            file_content = ""
        
        return jsonify({
            'project_name': project_name,
            'suggestions_file': result['suggestions_file'],
            'suggestions': result['suggestions'],
            'file_content': file_content,
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande de suggestions PO: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5012)


@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent productowner"})
    
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
            log_path = os.path.join(log_dir, 'productowner.log')
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