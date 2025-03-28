import logging
import re
import time
import json
import re
import threading
import time
import os
from threading import Event
import base64
import io
from PIL import Image
from dotenv import load_dotenv
from pathlib import Path

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

# Dossier de travail pour les projets UX
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'uxdesigner.log')

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

def invoke_claude(prompt, system_prompt=None, max_tokens=4096, temperature=0.7, max_retries=3, retry_delay=2):
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
                1. Essayer de décomposer la demande différemment
                2. Simplifier la requête
                3. Utiliser une approche plus standard pour ce type de conception
                
                Je vais faire de mon mieux pour poursuivre l'analyse avec les informations disponibles.
                """
                
                return fallback_response
    
    # Ce code ne devrait jamais être atteint, mais par sécurité
    socketio.emit('loading_end')
    return "Erreur inattendue lors de l'invocation du modèle"

def extract_design_elements(text):
    """
    Extrait les éléments de design (mocks, wireframes, diagrammes) d'une réponse markdown.
    
    Args:
        text (str): Texte contenant les descriptions et les éléments de design
        
    Returns:
        dict: Dictionnaire avec les noms d'éléments comme clés et contenu comme valeur
    """
    # Extraire les descriptions d'éléments UX (wireframes, mockups, personas, etc.)
    elements = {}
    
    # Chercher des sections avec des titres qui semblent être des éléments UX
    section_pattern = r'#+\s+(.*(?:wireframe|mockup|diagram|persona|user flow|journey map|prototype).*?)\s*\n(.*?)(?=\n#+\s+|\Z)'
    section_matches = re.findall(section_pattern, text, re.DOTALL | re.IGNORECASE)
    
    for title, content in section_matches:
        element_name = title.strip()
        elements[element_name] = content.strip()
    
    # Chercher des éléments markdown décrivant des images ou diagrammes
    image_pattern = r'!\[(.*?)\]\((.*?)\)'
    image_matches = re.findall(image_pattern, text)
    
    for alt_text, image_url in image_matches:
        if alt_text.strip():
            elements[alt_text.strip()] = {"type": "image_reference", "url": image_url.strip()}
    
    # Chercher des blocs de code HTML qui pourraient contenir des wireframes ou mockups
    html_pattern = r'```(?:html)?\s*(<!DOCTYPE html>.*?)<\/html>\s*```'
    html_matches = re.findall(html_pattern, text, re.DOTALL | re.IGNORECASE)
    
    for i, html_content in enumerate(html_matches):
        elements[f"HTML Mockup {i+1}"] = {"type": "html", "content": html_content.strip()}
    
    # Chercher des descriptions textuelles détaillées d'interfaces
    interface_pattern = r'(?:Interface|Screen|View|Page)\s*:\s*(.*?)(?=\n\n|$)'
    interface_matches = re.findall(interface_pattern, text, re.DOTALL | re.IGNORECASE)
    
    for i, interface_desc in enumerate(interface_matches):
        elements[f"Interface Description {i+1}"] = interface_desc.strip()
    
    return elements

def extract_ascii_wireframes(text):
    """
    Extrait les wireframes ASCII d'une réponse markdown.
    
    Args:
        text (str): Texte contenant potentiellement des wireframes ASCII
        
    Returns:
        list: Liste des wireframes ASCII extraits
    """
    # Pattern pour les blocs de code contenant des wireframes ASCII
    ascii_pattern = r'```(?:ascii|text)?\s*([\+\-\|\[\]\(\)\{\}\/\\\s_=:;,.<>*#@]+?)```'
    ascii_matches = re.findall(ascii_pattern, text, re.DOTALL)
    
    # Si aucun bloc n'est trouvé, chercher des blocs qui contiennent beaucoup de caractères structurels
    if not ascii_matches:
        # Chercher tous les blocs de code génériques
        blocks = re.findall(r'```\s*(.*?)```', text, re.DOTALL)
        
        for block in blocks:
            # Vérifier si c'est probablement un wireframe ASCII
            structural_chars = sum(1 for c in block if c in '+-|[](){}/<>_=:;,.')
            total_chars = len(block.strip())
            
            if total_chars > 0 and structural_chars / total_chars > 0.15:  # Au moins 15% de caractères structurels
                ascii_matches.append(block)
    
    return ascii_matches

def process_ux_design(project_name, ux_specs, constraints=None):
    """
    Génère une conception UX basée sur les spécifications fournies
    
    Args:
        project_name (str): Nom du projet
        ux_specs (str): Spécifications détaillées de conception UX
        constraints (str, optional): Contraintes de design (plateforme, accessibilité, etc.)
        
    Returns:
        dict: Les éléments de design générés
    """
    socketio.emit('log', {'type': 'info', 'message': "Analyse des besoins et génération de conception UX..."})
    
    # Système prompt pour guider Claude à fournir une conception UX complète
    system_prompt = """
    Vous êtes un expert en conception UX/UI avec une vaste expérience en création d'interfaces utilisateur intuitives et attrayantes.
    
    Pour cette tâche, vous allez générer une conception UX complète basée sur les spécifications fournies.
    Votre réponse doit inclure:
    
    1. Analyse des besoins utilisateurs: Identifiez les utilisateurs cibles, leurs besoins, et les problèmes que le design doit résoudre.
    
    2. Architecture de l'information: Organisez le contenu et les fonctionnalités de manière logique et intuitive.
    
    3. Wireframes: Créez des représentations visuelles simplifiées des interfaces principales. Utilisez l'ASCII art pour représenter ces wireframes:
       - Utilisez +, -, |, /, \, et autres caractères pour dessiner les contours
       - Utilisez des espaces pour représenter les zones vides
       - Utilisez des symboles comme [Button], {Image}, <Input>, etc. pour représenter les éléments UI
       - Incluez au moins 3-5 wireframes pour les écrans/vues principales
    
    4. Flow utilisateur: Décrivez comment les utilisateurs navigueront entre les différentes parties de l'interface.
    
    5. Principes de design: Expliquez les principes de design UI que vous recommandez (palette de couleurs, typographie, style visuel).
    
    6. Recommandations d'accessibilité: Assurez-vous que votre conception suit les meilleures pratiques d'accessibilité.
    
    7. Prochaines étapes: Suggérez les étapes suivantes pour affiner et valider cette conception (tests utilisateurs, prototypage, etc.)
    
    N'utilisez pas d'images - concentrez-vous sur des descriptions textuelles détaillées et des wireframes ASCII art.
    Structurez votre réponse avec des titres clairs pour chaque section.
    """
    
    # Construction du prompt pour la conception UX
    prompt = f"""
    J'ai besoin d'une conception UX pour le projet suivant: "{project_name}".
    
    Voici les spécifications détaillées:
    
    {ux_specs}
    """
    
    # Ajout des contraintes si fournies
    if constraints:
        prompt += f"""
        Contraintes de design à respecter:
        
        {constraints}
        """
    
    prompt += """
    Veuillez me fournir une conception UX complète selon les directives.
    Concentrez-vous particulièrement sur les wireframes ASCII et l'organisation logique des informations.
    """
    
    # Invoquer Claude pour la conception UX
    ux_analysis = invoke_claude(prompt, system_prompt, max_tokens=8000)
    
    # Traitement de la réponse
    socketio.emit('log', {'type': 'info', 'message': "Extraction des éléments de design..."})
    
    # Extraire les éléments de design
    design_elements = extract_design_elements(ux_analysis)
    
    # Extraire les wireframes ASCII
    ascii_wireframes = extract_ascii_wireframes(ux_analysis)
    
    # Organiser les éléments de conception UX
    project_dir = create_ux_project(project_name, ux_analysis, design_elements, ascii_wireframes)
    
    socketio.emit('log', {'type': 'success', 'message': "Conception UX générée avec succès"})
    
    return {
        "project_name": project_name,
        "project_dir": project_dir,
        "analysis": ux_analysis,
        "design_elements": design_elements,
        "ascii_wireframes": ascii_wireframes
    }

def create_ux_project(project_name, ux_analysis, design_elements, ascii_wireframes):
    """
    Crée un projet UX en sauvegardant tous les éléments générés
    
    Args:
        project_name (str): Nom du projet
        ux_analysis (str): Analyse UX complète
        design_elements (dict): Éléments de design extraits
        ascii_wireframes (list): Wireframes ASCII extraits
        
    Returns:
        str: Chemin du répertoire du projet
    """
    socketio.emit('log', {'type': 'info', 'message': "Création du projet UX..."})
    
    # Normaliser le nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    # Créer un dossier pour les wireframes
    wireframes_dir = os.path.join(project_dir, "wireframes")
    if not os.path.exists(wireframes_dir):
        os.makedirs(wireframes_dir)
    
    # Sauvegarder l'analyse UX complète
    analysis_path = os.path.join(project_dir, "ux_analysis.md")
    with open(analysis_path, 'w', encoding='utf-8') as f:
        f.write(f"# Analyse UX pour {project_name}\n\n")
        f.write(ux_analysis)
    
    socketio.emit('log', {'type': 'info', 'message': f"Analyse UX sauvegardée dans {analysis_path}"})
    
    # Sauvegarder les wireframes ASCII
    for i, wireframe in enumerate(ascii_wireframes):
        wireframe_path = os.path.join(wireframes_dir, f"wireframe_{i+1}.txt")
        with open(wireframe_path, 'w', encoding='utf-8') as f:
            f.write(wireframe)
        
        socketio.emit('log', {'type': 'info', 'message': f"Wireframe {i+1} sauvegardé dans {wireframe_path}"})
    
    # Créer un README.md pour le projet
    readme_path = os.path.join(project_dir, "README.md")
    
    # Extraire une description du projet à partir de l'analyse
    description = ""
    intro_match = re.search(r'^#.*?\n(.*?)(?=\n#)', ux_analysis, re.DOTALL)
    if intro_match:
        description = intro_match.group(1).strip()
    
    # Construction du contenu du README
    readme_content = f"""# Conception UX pour {project_name}

{description}

## Structure du projet

- **ux_analysis.md**: Analyse UX complète, incluant les besoins utilisateurs, l'architecture de l'information, et les recommandations de design
- **wireframes/**: Dossier contenant les wireframes ASCII

## Wireframes

Le projet contient {len(ascii_wireframes)} wireframes ASCII représentant les interfaces principales.

## Éléments de design

Le projet inclut les éléments de design suivants:

{', '.join(design_elements.keys()) if design_elements else "Aucun élément spécifique extrait"}

## Prochaines étapes recommandées

- Transformer les wireframes ASCII en maquettes haute-fidélité
- Réaliser des tests utilisateurs avec les wireframes
- Développer un prototype interactif
- Valider la conception auprès des parties prenantes
"""
    
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    socketio.emit('log', {'type': 'success', 'message': f"Projet UX créé dans {project_dir}"})
    
    return project_dir

@app.route('/ux_request', methods=['POST'])
def ux_request():
    """Endpoint pour recevoir et traiter les demandes de conception UX"""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande de conception UX"})
    
    data = request.json
    project_name = data.get('project_name', 'ux-design-project')
    ux_specs = data.get('specs', '')
    constraints = data.get('constraints', None)
    
    if not ux_specs:
        return jsonify({'error': "Les spécifications UX sont requises", 'status': 'error'})
    
    try:
        # Générer la conception UX
        ux_design = process_ux_design(project_name, ux_specs, constraints)
        
        # Envoyer les résultats au client
        socketio.emit('ux_complete', {
            'project_name': project_name,
            'project_dir': ux_design['project_dir']
        })
        
        return jsonify({
            'project_name': project_name,
            'project_dir': ux_design['project_dir'],
            'analysis': ux_design['analysis'],
            'ascii_wireframes': ux_design['ascii_wireframes'],
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande UX: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5015)


@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent uxdesigner"})
    
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
            log_path = os.path.join(log_dir, 'uxdesigner.log')
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