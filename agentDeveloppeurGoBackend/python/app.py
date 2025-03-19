import logging
import re
import time
import json
import re
import threading
import time
import os
import subprocess
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

# Dossier de travail pour les projets Go
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'developpeurgobackend.log')

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

def invoke_claude(prompt, system_prompt=None, max_tokens=4096, temperature=0.7, retry_count=2):
    """
    Invoque Claude via AWS Bedrock avec le prompt fourni.
    
    Args:
        prompt (str): Le prompt principal à envoyer au modèle
        system_prompt (str, optional): Instructions système pour guider le comportement du modèle
        max_tokens (int, optional): Nombre maximum de tokens pour la réponse
        temperature (float, optional): Niveau de créativité (0.0-1.0)
        retry_count (int, optional): Nombre de tentatives en cas d'erreur
    
    Returns:
        str: Réponse du modèle
    """
    socketio.emit('loading_start')
    socketio.emit('log', {'type': 'info', 'message': "Invocation de Claude en cours..."})
    
    for attempt in range(retry_count + 1):
        try:
            if attempt > 0:
                socketio.emit('log', {'type': 'warning', 
                                     'message': f"Nouvelle tentative d'invocation ({attempt}/{retry_count})..."})
            
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
            
            # Vérification simple pour la validité de la réponse
            if generated_text and len(generated_text) > 100:  # Une réponse valide devrait avoir une taille minimale
                socketio.emit('log', {'type': 'success', 'message': "Réponse de Claude reçue"})
                socketio.emit('loading_end')
                return generated_text
            else:
                error_message = "Réponse de Claude trop courte ou invalide"
                socketio.emit('log', {'type': 'warning', 'message': error_message})
                if attempt == retry_count:
                    socketio.emit('loading_end')
                    return f"Erreur: {error_message}. Voici la réponse reçue: {generated_text}"
                # Sinon, continuer avec la prochaine tentative
                time.sleep(2)  # Petite pause avant de réessayer
        
        except Exception as e:
            error_message = f"Erreur lors de l'invocation de Claude: {str(e)}"
            socketio.emit('log', {'type': 'error', 'message': error_message})
            
            if attempt == retry_count:
                socketio.emit('loading_end')
                return error_message
            
            # Pause avant de réessayer
            time.sleep(2)
    
    # Ce code ne devrait pas être atteint, mais au cas où
    socketio.emit('loading_end')
    return "Erreur: Toutes les tentatives d'invocation de Claude ont échoué."

def extract_code_blocks(text):
    """
    Extrait les blocs de code d'un texte markdown
    
    Args:
        text (str): Le texte contenant potentiellement des blocs de code
    
    Returns:
        list: Liste des blocs de code extraits
    """
    # Capture les blocs de code délimités par ```
    code_blocks = re.findall(r'```(?:[a-zA-Z]*\n)?(.*?)```', text, re.DOTALL)
    return code_blocks

def extract_go_files(text):
    """
    Extrait les fichiers Go d'une réponse Claude
    
    Args:
        text (str): La réponse de Claude contenant les fichiers Go
    
    Returns:
        dict: Dictionnaire de fichiers Go extraits (chemin -> contenu)
    """
    # Recherche des motifs comme: "fichier: main.go" suivi d'un bloc de code
    file_matches = re.findall(r'(?:fichier|file)\s*:\s*`?([^`\n]+\.go)`?\s*```(?:go)?\s*(.*?)```', text, re.DOTALL | re.IGNORECASE)
    
    files = {}
    for file_path, content in file_matches:
        files[file_path.strip()] = content.strip()
    
    # Pattern alternatif: recherche des noms de fichiers suivi d'un bloc de code (sans le mot "fichier:" ou "file:")
    if not files:
        alternative_matches = re.findall(r'[\n\r]`?([^`\n\r]+\.go)`?[\n\r\s]*```(?:go)?\s*(.*?)```', text, re.DOTALL)
        for file_path, content in alternative_matches:
            files[file_path.strip()] = content.strip()
    
    # Si pas de fichiers trouvés avec les patterns précédents, essayer de trouver des blocs de code Go
    if not files:
        go_blocks = re.findall(r'```go\s*(.*?)```', text, re.DOTALL)
        if go_blocks:
            files["main.go"] = go_blocks[0].strip()
    
    return files

def create_project_structure(project_name):
    """
    Crée la structure de base d'un projet Go
    
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
    for subdir in ['cmd', 'internal', 'pkg', 'api', 'configs', 'docs', 'test']:
        os.makedirs(os.path.join(project_dir, subdir), exist_ok=True)
    
    # Créer les fichiers de base
    with open(os.path.join(project_dir, 'go.mod'), 'w') as f:
        f.write(f'module github.com/agentsIA/{safe_project_name}\n\ngo 1.20\n')
    
    with open(os.path.join(project_dir, 'README.md'), 'w') as f:
        f.write(f'# {project_name}\n\nGénéré par l\'agent développeur Go Backend avec Claude.\n')
    
    socketio.emit('log', {'type': 'success', 'message': f"Structure du projet créée dans {project_dir}"})
    return project_dir

def validate_go_code(code, file_path):
    """
    Valide que le code Go est syntaxiquement correct
    
    Args:
        code (str): Le code Go à valider
        file_path (str): Chemin du fichier pour les messages d'erreur
        
    Returns:
        tuple: (bool, str) - (est_valide, message_erreur_ou_code_corrigé)
    """
    # Vérification de base: présence des accolades ouvrantes et fermantes
    opening_braces = code.count('{')
    closing_braces = code.count('}')
    
    if opening_braces != closing_braces:
        socketio.emit('log', {'type': 'warning', 
                             'message': f"Déséquilibre d'accolades dans {file_path}: {opening_braces} ouvrantes, {closing_braces} fermantes"})
        # Tentative simple de correction
        if opening_braces > closing_braces:
            # Ajouter les accolades manquantes
            return False, code + ('}' * (opening_braces - closing_braces))
        else:
            # Cas plus complexe à gérer
            return False, code
            
    # Vérification de la présence de 'package' au début du fichier
    lines = code.strip().split('\n')
    if not lines or not any(line.strip().startswith('package ') for line in lines[:5]):
        socketio.emit('log', {'type': 'warning', 
                             'message': f"Pas de déclaration 'package' au début de {file_path}"})
        # Tenter de déterminer un nom de package à partir du chemin
        package_name = os.path.basename(os.path.dirname(file_path))
        if package_name == '.' or not package_name:
            package_name = 'main'
        corrected_code = f"package {package_name}\n\n{code}"
        return False, corrected_code
    
    # Vérification des imports
    if 'import (' in code and not ')' in code.split('import (')[1].split('\n', 1)[1]:
        socketio.emit('log', {'type': 'warning', 
                             'message': f"Bloc d'import non fermé dans {file_path}"})
        # Corriger en ajoutant la parenthèse fermante
        parts = code.split('import (')
        corrected_code = parts[0] + 'import (' + parts[1].replace('\n', '\n)\n', 1)
        return False, corrected_code
        
    return True, code

def generate_go_code(project_specs, requirements, project_dir):
    """
    Génère du code Go en utilisant Claude avec validation automatique et correction des erreurs
    
    Args:
        project_specs (str): Spécifications du projet
        requirements (str): Exigences techniques
        project_dir (str): Chemin vers le dossier du projet
        
    Returns:
        dict: Structure des fichiers générés avec validation
    """
    socketio.emit('log', {'type': 'info', 'message': "Génération du code Go..."})
    
    # Système prompt pour guider Claude à générer du code Go
    system_prompt = """
    Vous êtes un expert en développement backend avec Go (Golang). Votre rôle est de coder des solutions
    selon les spécifications fournies par un chef de projet. Vous devez respecter ces directives:
    
    1. Suivez strictement la structure standard des projets Go:
       - cmd/: Points d'entrée de l'application
       - internal/: Code privé spécifique à l'application
       - pkg/: Bibliothèques réutilisables publiques
       - api/: Définitions d'API, protobuf, etc.
       - configs/: Fichiers de configuration
    
    2. Appliquez les principes suivants:
       - Utilisation de modules Go pour la gestion des dépendances
       - Code idiomatique respectant les conventions Go
       - Gestion d'erreurs explicite (pas de panic dans le code de production)
       - Tests unitaires avec le package testing
       - Documentation appropriée avec godoc
       - Respect des principes SOLID et de l'architecture hexagonale si applicable
    
    3. Utilisez les bibliothèques standards Go quand c'est possible, et pour les besoins spécifiques:
       - HTTP: net/http ou frameworks comme gin, echo, fiber
       - Base de données: database/sql avec des pilotes comme pgx, go-sql-driver
       - CLI: cobra, urfave/cli
       - Configuration: viper
       - Logging: zap, logrus
       - Tests: testify
    
    IMPORTANT: Vérifiez soigneusement votre code pour garantir qu'il est syntaxiquement correct:
    - Toutes les accolades ouvrantes { doivent avoir leur accolade fermante } correspondante
    - Tous les fichiers doivent commencer par une déclaration de package
    - Les imports doivent être correctement formatés
    - Les fonctions et méthodes doivent avoir des signatures complètes
    
    Pour chaque fichier Go, vous devez fournir le nom du fichier et son contenu complet.
    Votre réponse doit être structurée ainsi:
    
    fichier: `chemin/relatif/du/fichier.go`
    ```go
    // Code Go complet
    ```
    
    fichier: `autre/fichier.go`
    ```go
    // Code Go complet
    ```
    
    Et ainsi de suite pour tous les fichiers nécessaires.
    """
    
    # Construction du prompt pour générer le code Go
    prompt = f"""
    En tant qu'agent développeur Go backend, voici les spécifications du projet:
    
    {project_specs}
    
    Voici les exigences techniques:
    
    {requirements}
    
    Veuillez développer une application Go complète selon ces spécifications.
    Fournissez tous les fichiers nécessaires (go.mod, .go, etc.) pour que l'application soit fonctionnelle.
    Assurez-vous d'inclure:
    - La structure de projet Go standard
    - La gestion des dépendances (go.mod)
    - Les tests unitaires
    - Une documentation claire
    - Des commentaires pertinents
    
    IMPORTANT: Vérifiez soigneusement votre code avant de le soumettre pour vous assurer qu'il est syntaxiquement correct.
    """
    
    # Invocation de Claude
    response = invoke_claude(prompt, system_prompt, max_tokens=8000)
    
    # Extraction des fichiers Go
    go_files = extract_go_files(response)
    
    if not go_files:
        socketio.emit('log', {'type': 'warning', 'message': "Aucun fichier Go trouvé dans la réponse. Tentative de récupération..."})
        
        # Essayer d'extraire à nouveau avec une heuristique plus permissive
        code_blocks = extract_code_blocks(response)
        if code_blocks:
            socketio.emit('log', {'type': 'info', 'message': f"Récupération de {len(code_blocks)} blocs de code"})
            # Créer des noms de fichiers à partir de la position du bloc dans la réponse
            for i, block in enumerate(code_blocks):
                # Essayer de déterminer si c'est un fichier go.mod ou un fichier Go
                if block.strip().startswith('module '):
                    go_files['go.mod'] = block.strip()
                elif 'package ' in block[:100]:  # Chercher une déclaration package dans les 100 premiers caractères
                    # Essayer de déterminer un nom de fichier plus précis
                    file_lines = block.split('\n')
                    package_line = next((line for line in file_lines if line.startswith('package ')), None)
                    if package_line:
                        package_name = package_line.split(' ')[1].strip()
                        if package_name == 'main':
                            go_files[f'cmd/main.go'] = block.strip()
                        else:
                            go_files[f'pkg/{package_name}/{package_name}.go'] = block.strip()
                    else:
                        go_files[f'recovered_file_{i+1}.go'] = block.strip()
        
        # Si toujours pas de fichiers, sauvegarder la réponse brute et retourner
        if not go_files:
            socketio.emit('log', {'type': 'error', 'message': "Impossible de récupérer du code Go valide"})
            fallback_path = os.path.join(project_dir, "claude_response.md")
            with open(fallback_path, 'w') as f:
                f.write(response)
            return {"claude_response.md": response}
    
    # Écriture des fichiers Go avec validation
    file_infos = []
    validation_issues = 0
    
    for file_path, content in go_files.items():
        # Valider et corriger le code si nécessaire
        if file_path.endswith('.go') and file_path != 'go.mod':
            is_valid, validated_content = validate_go_code(content, file_path)
            if not is_valid:
                validation_issues += 1
                socketio.emit('log', {'type': 'info', 'message': f"Correction automatique appliquée pour {file_path}"})
                content = validated_content
        
        full_path = os.path.join(project_dir, file_path)
        
        # Créer les dossiers parents si nécessaire
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Écrire le contenu du fichier
        with open(full_path, 'w') as f:
            f.write(content)
        
        socketio.emit('log', {'type': 'info', 'message': f"Fichier créé: {file_path}"})
        file_infos.append({"file_path": file_path, "content": content})
    
    # Écrire aussi la réponse complète de Claude
    with open(os.path.join(project_dir, "claude_full_response.md"), 'w') as f:
        f.write(response)
    
    if validation_issues > 0:
        socketio.emit('log', {'type': 'warning', 
                             'message': f"Code Go généré avec {validation_issues} problèmes corrigés automatiquement"})
    else:
        socketio.emit('log', {'type': 'success', 'message': f"Code Go généré avec succès ({len(go_files)} fichiers)"})
    
    # Mise à jour du fichier go.mod avec go mod tidy
    try:
        socketio.emit('log', {'type': 'info', 'message': "Exécution de 'go mod tidy'..."})
        process = subprocess.run(['go', 'mod', 'tidy'], cwd=project_dir, capture_output=True, text=True)
        
        if process.returncode != 0:
            socketio.emit('log', {'type': 'warning', 
                                 'message': f"Erreur lors de 'go mod tidy': {process.stderr}"})
            
            # Vérifier si go.mod existe, sinon le créer avec un contenu minimal
            go_mod_path = os.path.join(project_dir, "go.mod")
            if not os.path.exists(go_mod_path):
                project_name = os.path.basename(project_dir)
                with open(go_mod_path, 'w') as f:
                    f.write(f'module github.com/agentsIA/{project_name}\n\ngo 1.21\n')
                socketio.emit('log', {'type': 'info', 'message': "Fichier go.mod créé manuellement"})
                
                # Réessayer go mod tidy
                socketio.emit('log', {'type': 'info', 'message': "Nouvelle tentative de 'go mod tidy'..."})
                subprocess.run(['go', 'mod', 'tidy'], cwd=project_dir, check=False)
        else:
            socketio.emit('log', {'type': 'success', 'message': "Dépendances Go mises à jour"})
    except Exception as e:
        socketio.emit('log', {'type': 'warning', 
                             'message': f"Erreur lors de la gestion des dépendances: {str(e)}"})
    
    return {"files": file_infos, "raw_response": response}

@app.route('/go_code_request', methods=['POST'])
def go_code_request():
    """Endpoint pour recevoir et traiter les demandes de code Go"""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande de code Go"})
    
    data = request.json
    project_name = data.get('project_name', 'go-project')
    project_specs = data.get('specs', '')
    requirements = data.get('requirements', '')
    
    try:
        # Phase 1: Créer la structure du projet
        project_dir = create_project_structure(project_name)
        socketio.emit('project_dir_update', {'project_dir': project_dir})
        
        # Phase 2: Générer le code Go
        generated_code = generate_go_code(project_specs, requirements, project_dir)
        socketio.emit('code_update', {'code': generated_code})
        
        # Préparer la réponse à envoyer au client
        response = {
            'project_dir': project_dir,
            'generated_code': generated_code
        }
        
        socketio.emit('log', {'type': 'success', 'message': "Code Go généré avec succès"})
        socketio.emit('end')
        
        return jsonify(response)
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message})

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5001)


@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent developpeurgobackend"})
    
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
            log_path = os.path.join(log_dir, 'developpeurgobackend.log')
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
    try:
        # Initialiser le client Bedrock
        bedrock_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=REGION_NAME,
        )
    except Exception as e:
        logger.warning(f"Impossible d'initialiser le client Bedrock: {str(e)}")
        logger.info("Fonctionnement en mode dégradé sans AWS")
        # Définir un client factice pour éviter les erreurs
        class FakeClient:
            def invoke_model(self, **kwargs):
                return {"body": type('obj', (object,), {"read": lambda: json.dumps({"content": [{"text": "Réponse simulée en mode dégradé"}]})})()}
        bedrock_client = FakeClient()
    
    # Créer le dossier workspace s'il n'existe pas
    if not os.path.exists(WORKSPACE_DIR):
        os.makedirs(WORKSPACE_DIR)
    
    # Démarrer le serveur Flask avec SocketIO
    start_socketio()