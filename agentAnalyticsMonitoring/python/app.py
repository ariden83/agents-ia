import logging
import re
import time
import json
import re
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

# Dossier de travail pour les configurations d'analytics et monitoring
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'analyticsmonitoring.log')

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
                1. Essayer de décomposer le problème différemment
                2. Simplifier la requête
                3. Utiliser une approche plus standard pour ce type de configuration
                
                Je vais faire de mon mieux pour poursuivre l'analyse avec les informations disponibles.
                """
                
                return fallback_response
    
    # Ce code ne devrait jamais être atteint, mais par sécurité
    socketio.emit('loading_end')
    return "Erreur inattendue lors de l'invocation du modèle"

def extract_code_blocks(text):
    """
    Extrait les blocs de code à partir d'un texte Markdown.
    
    Args:
        text (str): Texte contenant des blocs de code
        
    Returns:
        dict: Dictionnaire des blocs de code extraits par langage
    """
    # Pattern pour les blocs de code avec spécification de langage (```yaml, ```json, etc.)
    pattern = r'```(\w+)?\s*(.*?)\s*```'
    
    # Rechercher tous les blocs de code
    matches = re.findall(pattern, text, re.DOTALL)
    
    # Organiser les blocs par langage
    code_blocks = {}
    for lang, code in matches:
        lang = lang.lower() if lang else "text"
        if lang not in code_blocks:
            code_blocks[lang] = []
        code_blocks[lang].append(code.strip())
    
    return code_blocks

def create_analytics_project(project_name, analysis_response):
    """
    Crée un projet de configuration d'analytics et de monitoring à partir de l'analyse.
    
    Args:
        project_name (str): Nom du projet
        analysis_response (str): Réponse d'analyse contenant configurations et explications
    
    Returns:
        dict: Informations sur les fichiers créés
    """
    socketio.emit('log', {'type': 'info', 'message': "Création du projet d'analytics et monitoring..."})
    
    # Normaliser le nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    # Liste des fichiers générés
    generated_files = []
    
    # Extraction des blocs de code
    code_blocks = extract_code_blocks(analysis_response)
    
    # Créer un dictionnaire pour mapper les extensions de fichier par langage
    lang_extensions = {
        "yaml": ".yaml",
        "yml": ".yaml",
        "json": ".json",
        "javascript": ".js",
        "js": ".js",
        "python": ".py",
        "bash": ".sh",
        "shell": ".sh",
        "dockerfile": "Dockerfile",
        "docker": "Dockerfile",
        "hcl": ".tf",
        "terraform": ".tf",
        "conf": ".conf",
        "toml": ".toml",
        "ini": ".ini"
    }
    
    # Fonction pour déterminer le nom de fichier approprié
    def determine_filename(lang, content, index):
        # Chercher un nom de fichier dans le contenu
        file_match = re.search(r'filename:\s*([^\s]+)', content, re.IGNORECASE)
        if file_match:
            return file_match.group(1)
        
        # Chercher un nom de fichier commun selon le langage
        common_filenames = {
            "yaml": ["prometheus.yaml", "grafana.yaml", "docker-compose.yaml", "config.yaml"],
            "dockerfile": ["Dockerfile"],
            "json": ["config.json", "package.json", "settings.json"],
            "js": ["analytics.js", "monitoring.js", "setup.js"],
            "py": ["analytics.py", "monitoring.py", "setup.py"],
            "sh": ["setup.sh", "install.sh", "monitor.sh"]
        }
        
        if lang in common_filenames:
            # Rechercher des mots clés dans le contenu pour déterminer le nom de fichier
            for filename in common_filenames[lang]:
                keyword = filename.split('.')[0].lower()
                if keyword in content.lower():
                    return filename
        
        # Utiliser un nom par défaut
        ext = lang_extensions.get(lang, f".{lang}")
        if lang == "dockerfile":
            return "Dockerfile"
        else:
            return f"{safe_project_name}_{lang}_{index+1}{ext}"
    
    # Créer un dossier pour chaque type de configuration
    config_types = {
        "monitoring": ["prometheus", "grafana", "alertmanager", "zabbix", "nagios"],
        "analytics": ["google", "analytics", "matomo", "piwik", "amplitude", "heap"],
        "logging": ["elasticsearch", "logstash", "kibana", "fluentd", "loki"]
    }
    
    # Création des sous-dossiers pour les différentes catégories
    for config_type in config_types:
        type_dir = os.path.join(project_dir, config_type)
        if not os.path.exists(type_dir):
            os.makedirs(type_dir)
    
    # Fonction pour déterminer le dossier approprié pour un fichier
    def determine_folder(content):
        content_lower = content.lower()
        for folder, keywords in config_types.items():
            for keyword in keywords:
                if keyword.lower() in content_lower:
                    return folder
        return "general"  # Dossier par défaut
    
    # Créer les fichiers pour chaque langage et bloc de code
    for lang, blocks in code_blocks.items():
        for i, content in enumerate(blocks):
            # Déterminer le nom du fichier
            filename = determine_filename(lang, content, i)
            
            # Déterminer le dossier approprié
            folder = determine_folder(content)
            folder_path = os.path.join(project_dir, folder)
            
            # Créer le dossier s'il n'existe pas
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
            
            # Chemin complet du fichier
            file_path = os.path.join(folder_path, filename)
            
            # Écrire le contenu dans le fichier
            with open(file_path, 'w') as f:
                f.write(content)
            
            generated_files.append(file_path)
            socketio.emit('log', {'type': 'success', 'message': f"Fichier créé: {file_path}"})
    
    # Création d'un README.md pour le projet
    readme_path = os.path.join(project_dir, "README.md")
    
    # Extraction du titre et de la description à partir de la réponse
    title_match = re.search(r'^#\s+(.+)$', analysis_response, re.MULTILINE)
    title = title_match.group(1) if title_match else f"Configuration Analytics & Monitoring pour {project_name}"
    
    # Chercher un paragraphe après le titre pour la description
    description_match = re.search(r'^#\s+.+\n\n(.+?)(?=\n\n|$)', analysis_response, re.MULTILINE | re.DOTALL)
    description = description_match.group(1) if description_match else "Configuration d'analytics et de monitoring générée par l'Agent Analytics & Monitoring."
    
    # Construction du contenu du README
    readme_content = f"""# {title}

{description}

## Structure du projet

Ce projet contient des configurations pour les systèmes suivants:

"""
    
    # Ajouter la structure de dossiers au README
    for folder in os.listdir(project_dir):
        folder_path = os.path.join(project_dir, folder)
        if os.path.isdir(folder_path) and not folder.startswith('.'):
            readme_content += f"### {folder.capitalize()}\n\n"
            files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
            if files:
                readme_content += "Fichiers:\n\n"
                for file in files:
                    readme_content += f"- `{file}`\n"
                readme_content += "\n"
    
    # Ajouter des instructions pour l'utilisation
    readme_content += """## Utilisation

Ces fichiers fournissent des configurations pour mettre en place un système complet d'analytics et de monitoring. Voici comment utiliser ces configurations:

1. Consultez les fichiers spécifiques pour chaque outil
2. Adaptez les configurations à votre environnement spécifique
3. Déployez les configurations selon les instructions de chaque outil

## Outils inclus

- **Monitoring**: Configuration pour la surveillance des performances et de la disponibilité
- **Analytics**: Configuration pour le suivi et l'analyse des comportements utilisateurs
- **Logging**: Configuration pour la gestion centralisée des logs

## Notes d'installation

Consultez les fichiers README spécifiques dans chaque sous-dossier pour plus de détails sur l'installation et la configuration.
"""
    
    # Écrire le README
    with open(readme_path, 'w') as f:
        f.write(readme_content)
    
    generated_files.append(readme_path)
    
    socketio.emit('log', {'type': 'success', 'message': f"Projet d'analytics et monitoring créé dans {project_dir}"})
    
    return {
        "project_dir": project_dir,
        "files": generated_files
    }

def analyze_analytics_monitoring_requirements(project_specs, stack_info=None):
    """
    Analyse les besoins en analytics et monitoring et génère une solution complète.
    
    Args:
        project_specs (str): Spécifications du projet
        stack_info (str, optional): Informations sur la stack technique
        
    Returns:
        str: Analyse et configurations générées
    """
    socketio.emit('log', {'type': 'info', 'message': "Analyse des besoins en analytics et monitoring..."})
    
    # Système prompt pour guider Claude à fournir une solution complète
    system_prompt = """
    Vous êtes un expert en analyse, monitoring et observabilité des applications web et systèmes.
    Votre mission est de fournir des configurations complètes pour l'analytics, le monitoring et la gestion des logs d'un projet web.
    
    Dans votre réponse, vous devez:
    
    1. Analyser les besoins spécifiques en observabilité et analytics du projet
    2. Recommander les outils les plus adaptés (Prometheus, Grafana, ELK, Loki, Google Analytics, etc.)
    3. Fournir des configurations complètes et prêtes à l'emploi dans des blocs de code spécifiques
    4. Expliquer clairement comment intégrer ces configurations dans le projet
    5. Ajouter des dashboards et alertes pour les métriques clés
    
    Structurez votre réponse avec:
    - Une introduction et vue d'ensemble de la solution
    - Des sections dédiées à chaque outil avec leurs configurations dans des blocs de code appropriés
    - Pour chaque fichier de configuration, précisez un nom de fichier approprié en commentaire
    - Des instructions d'utilisation et d'installation claires
    
    Utilisez le format Markdown avec des blocs de code appropriés pour chaque langage:
    ```yaml
    # filename: prometheus.yml
    # Configuration Prometheus
    ```
    
    ```json
    // filename: grafana-datasources.json
    // Configuration des sources de données Grafana
    ```
    
    Veillez à adapter votre réponse à la stack technique mentionnée et aux besoins spécifiques du projet.
    """
    
    # Construction du prompt principal
    prompt = f"""
    Je travaille sur un projet web et j'ai besoin d'une configuration complète d'analytics et de monitoring.
    
    Voici les spécifications du projet:
    
    {project_specs}
    """
    
    # Ajout des informations de stack technique si fournies
    if stack_info:
        prompt += f"""
        
        Informations sur notre stack technique:
        
        {stack_info}
        """
    
    prompt += """
    
    Veuillez me fournir:
    
    1. Une configuration complète pour le monitoring (métriques, alertes, dashboards)
    2. Une configuration pour l'analytics web (suivi utilisateur, événements, conversions)
    3. Une configuration pour la gestion centralisée des logs
    4. Des instructions d'installation et d'intégration
    
    Fournissez tous les fichiers de configuration nécessaires dans des blocs de code avec le langage approprié, 
    avec un commentaire indiquant le nom de fichier suggéré pour chaque configuration.
    """
    
    # Invoquer Claude pour l'analyse
    analysis = invoke_claude(prompt, system_prompt, max_tokens=4000)
    
    socketio.emit('log', {'type': 'success', 'message': "Analyse des besoins en analytics et monitoring terminée"})
    
    return analysis

def generate_analytics_monitoring_config(project_name, project_specs, stack_info=None):
    """
    Génère une configuration complète d'analytics et monitoring pour un projet.
    
    Args:
        project_name (str): Nom du projet
        project_specs (str): Spécifications du projet
        stack_info (str, optional): Informations sur la stack technique
        
    Returns:
        dict: Informations sur le projet généré
    """
    socketio.emit('log', {'type': 'info', 'message': f"Génération de la configuration d'analytics et monitoring pour {project_name}..."})
    
    # Analyser les besoins en analytics et monitoring
    analysis_response = analyze_analytics_monitoring_requirements(project_specs, stack_info)
    
    # Créer le projet de configuration
    project_info = create_analytics_project(project_name, analysis_response)
    
    # Ajouter l'analyse à l'objet de retour
    project_info["analysis"] = analysis_response
    
    socketio.emit('log', {'type': 'success', 'message': f"Configuration d'analytics et monitoring pour {project_name} générée avec succès"})
    socketio.emit('analytics_complete', {
        'project_dir': project_info['project_dir'],
        'files': project_info['files']
    })
    
    return project_info

@app.route('/analytics_monitoring_request', methods=['POST'])
def analytics_monitoring_request():
    """Endpoint pour recevoir et traiter les demandes d'analytics et monitoring directes"""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande d'analytics et monitoring"})
    
    data = request.json
    project_name = data.get('project_name', 'web-analytics')
    project_specs = data.get('specs', '')
    stack_info = data.get('stack_info', None)
    
    if not project_specs:
        return jsonify({'error': "Les spécifications du projet sont requises", 'status': 'error'})
    
    try:
        # Générer la configuration d'analytics et monitoring
        project_info = generate_analytics_monitoring_config(project_name, project_specs, stack_info)
        
        return jsonify({
            'project_name': project_name,
            'project_dir': project_info['project_dir'],
            'files': project_info['files'],
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande d'analytics et monitoring: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

@app.route('/api/analytics_monitoring', methods=['POST'])
def api_analytics_monitoring():
    """API endpoint pour les demandes d'analytics et monitoring provenant d'autres agents"""
    data = request.json
    project_name = data.get('project_name', 'web-analytics')
    project_specs = data.get('specs', '')
    stack_info = data.get('stack_info', None)
    
    if not project_specs:
        return jsonify({'error': "Les spécifications du projet sont requises", 'status': 'error'})
    
    socketio.emit('log', {'type': 'info', 'message': f"Réception d'une demande d'API pour {project_name}"})
    
    try:
        # Générer la configuration d'analytics et monitoring
        project_info = generate_analytics_monitoring_config(project_name, project_specs, stack_info)
        
        # Lire le contenu des fichiers générés pour l'inclure dans la réponse
        files_content = {}
        for file_path in project_info['files']:
            try:
                with open(file_path, 'r') as f:
                    file_name = os.path.relpath(file_path, project_info['project_dir'])
                    files_content[file_name] = f.read()
            except Exception as e:
                socketio.emit('log', {'type': 'warning', 'message': f"Impossible de lire le fichier {file_path}: {str(e)}"})
        
        return jsonify({
            'project_name': project_name,
            'project_dir': project_info['project_dir'],
            'files': project_info['files'],
            'files_content': files_content,
            'analysis': project_info['analysis'],
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande d'analytics et monitoring: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5011)


@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent analyticsmonitoring"})
    
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
            log_path = os.path.join(log_dir, 'analyticsmonitoring.log')
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