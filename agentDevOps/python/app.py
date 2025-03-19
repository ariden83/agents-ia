import logging
import re
import time
import json
import re
import threading
import time
import os
import subprocess
import asyncio
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

# Dossier de travail pour les projets DevOps
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'devops.log')

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
                1. Continuer avec une approche simplifiée
                2. Essayer de décomposer le problème différemment
                3. Utiliser des configurations standard pour ce type de projet
                
                Je vais faire de mon mieux pour poursuivre l'analyse avec les informations disponibles.
                """
                
                return fallback_response
    
    # Ce code ne devrait jamais être atteint, mais par sécurité
    socketio.emit('loading_end')
    return "Erreur inattendue lors de l'invocation du modèle"

def extract_files_from_response(response, base_dir):
    """
    Extrait les fichiers de configuration depuis la réponse de Claude et les sauvegarde.
    
    Args:
        response (str): Réponse de Claude contenant des définitions de fichiers
        base_dir (str): Répertoire de base où sauvegarder les fichiers
    
    Returns:
        list: Liste des fichiers extraits et sauvegardés
    """
    socketio.emit('log', {'type': 'info', 'message': "Extraction des fichiers de configuration..."})
    
    files_saved = []
    
    # Regex pour extraire les fichiers - format: "fichier: `chemin/du/fichier`\n```[langage]\ncontenu\n```"
    file_patterns = [
        # Format standard avec ```
        r'(?:fichier|file|filename)\s*:\s*(?:`)?([^`\n]+)(?:`)?\s*```(?:\w+)?\s*(.*?)```',
        
        # Format avec juste le chemin suivi d'un bloc de code
        r'([^\n]+\.[^\n]+)\s*:\s*```(?:\w+)?\s*(.*?)```',
        
        # Format alternatif sans backticks
        r'(?:fichier|file|filename)\s*:\s*([^\n]+)\s*\n\s*```(?:\w+)?\s*(.*?)```'
    ]
    
    # Tenter d'extraire les fichiers avec les différents patterns
    extracted_files = []
    for pattern in file_patterns:
        matches = re.finditer(pattern, response, re.DOTALL)
        for match in matches:
            file_path, content = match.groups()
            file_path = file_path.strip()
            content = content.strip()
            
            # Éviter les doublons
            if not any(f[0] == file_path for f in extracted_files):
                extracted_files.append((file_path, content))
    
    # Sauvegarder les fichiers extraits
    for file_path, content in extracted_files:
        # Normaliser le chemin du fichier
        if file_path.startswith('./'):
            file_path = file_path[2:]
        
        full_path = os.path.join(base_dir, file_path)
        
        # Créer les dossiers parents si nécessaire
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Écrire le contenu dans le fichier
        with open(full_path, 'w') as f:
            f.write(content)
        
        socketio.emit('log', {'type': 'success', 'message': f"Fichier créé: {file_path}"})
        files_saved.append(file_path)
    
    # Si aucun fichier n'a été extrait, essayer une approche différente
    if not files_saved:
        # Chercher des blocs de code avec des commentaires indiquant le nom du fichier
        code_blocks = re.finditer(r'```(?:\w+)?\s*(.*?)```', response, re.DOTALL)
        current_filename = None
        
        for i, block in enumerate(code_blocks):
            content = block.group(1).strip()
            
            # Chercher un nom de fichier dans les 5 lignes précédant le bloc
            prev_text = response[:block.start()].split('\n')[-5:]
            for line in prev_text:
                file_match = re.search(r'(?:fichier|file|filename|path)\s*:\s*(?:`)?([^`\n]+)(?:`)?', line)
                if file_match:
                    current_filename = file_match.group(1).strip()
                    break
            
            # Si aucun nom trouvé, utiliser un nom générique basé sur le type de contenu
            if not current_filename:
                # Déterminer le type de fichier à partir du contenu
                if "Dockerfile" in content.split('\n')[0]:
                    current_filename = "Dockerfile"
                elif "apiVersion:" in content and ("kind:" in content or "metadata:" in content):
                    current_filename = f"kubernetes-manifest-{i}.yaml"
                elif "version:" in content and ("services:" in content or "build:" in content):
                    current_filename = "docker-compose.yml"
                elif "pipeline {" in content or "stages {" in content:
                    current_filename = "Jenkinsfile"
                elif "name:" in content and "on:" in content and "jobs:" in content:
                    current_filename = ".github/workflows/workflow.yml"
                elif "steps:" in content and ("uses:" in content or "run:" in content):
                    current_filename = ".github/workflows/action.yml"
                else:
                    # Format générique
                    current_filename = f"config-file-{i}.txt"
            
            # Sauvegarder le fichier
            full_path = os.path.join(base_dir, current_filename)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write(content)
            
            socketio.emit('log', {'type': 'success', 'message': f"Fichier créé: {current_filename}"})
            files_saved.append(current_filename)
            current_filename = None
    
    if files_saved:
        socketio.emit('log', {'type': 'success', 'message': f"{len(files_saved)} fichiers extraits et sauvegardés"})
    else:
        socketio.emit('log', {'type': 'warning', 'message': "Aucun fichier extrait de la réponse"})
        
        # Sauvegarder la réponse complète dans un fichier texte
        full_response_path = os.path.join(base_dir, "claude_response.md")
        with open(full_response_path, 'w') as f:
            f.write(response)
        socketio.emit('log', {'type': 'info', 'message': f"Réponse complète sauvegardée dans claude_response.md"})
        files_saved.append("claude_response.md")
    
    return files_saved

def run_command(cmd, cwd=None, timeout=60):
    """
    Exécute une commande shell et retourne le résultat.
    
    Args:
        cmd (str): Commande à exécuter
        cwd (str, optional): Répertoire de travail
        timeout (int, optional): Timeout en secondes
    
    Returns:
        dict: Résultat de la commande (status, stdout, stderr)
    """
    socketio.emit('log', {'type': 'info', 'message': f"Exécution de la commande: {cmd}"})
    
    try:
        process = subprocess.Popen(
            cmd, 
            shell=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            cwd=cwd,
            text=True
        )
        
        stdout, stderr = process.communicate(timeout=timeout)
        status = process.returncode
        
        if status == 0:
            socketio.emit('log', {'type': 'success', 'message': f"Commande exécutée avec succès (code: {status})"})
        else:
            socketio.emit('log', {'type': 'error', 'message': f"Erreur lors de l'exécution de la commande (code: {status})"})
        
        return {
            "status": status,
            "stdout": stdout,
            "stderr": stderr
        }
    
    except subprocess.TimeoutExpired:
        socketio.emit('log', {'type': 'error', 'message': f"Timeout lors de l'exécution de la commande (>{timeout}s)"})
        return {
            "status": -1,
            "stdout": "",
            "stderr": f"Timeout après {timeout} secondes"
        }
    
    except Exception as e:
        socketio.emit('log', {'type': 'error', 'message': f"Erreur lors de l'exécution de la commande: {str(e)}"})
        return {
            "status": -1,
            "stdout": "",
            "stderr": str(e)
        }

def detect_technologies(project_files):
    """
    Détecte les technologies utilisées dans le projet en analysant les fichiers.
    
    Args:
        project_files (list): Liste de chemins de fichiers du projet
    
    Returns:
        dict: Technologies détectées
    """
    tech_stack = {
        "languages": set(),
        "frameworks": set(),
        "build_tools": set(),
        "databases": set(),
        "cloud_providers": set(),
        "container_tech": set(),
        "ci_cd_tools": set()
    }
    
    # Vérifier l'existence de fichiers spécifiques
    file_paths = [os.path.basename(f) for f in project_files]
    
    # Langages
    if any(f.endswith('.js') or f.endswith('.jsx') for f in project_files):
        tech_stack["languages"].add("javascript")
    if any(f.endswith('.ts') or f.endswith('.tsx') for f in project_files):
        tech_stack["languages"].add("typescript")
    if any(f.endswith('.py') for f in project_files):
        tech_stack["languages"].add("python")
    if any(f.endswith('.java') for f in project_files):
        tech_stack["languages"].add("java")
    if any(f.endswith('.go') for f in project_files):
        tech_stack["languages"].add("go")
    if any(f.endswith('.php') for f in project_files):
        tech_stack["languages"].add("php")
    if any(f.endswith('.rb') for f in project_files):
        tech_stack["languages"].add("ruby")
    
    # Frameworks et outils
    if 'package.json' in file_paths:
        with open(os.path.join(os.path.dirname(project_files[0]), 'package.json'), 'r') as f:
            try:
                package_json = json.load(f)
                deps = {**package_json.get('dependencies', {}), **package_json.get('devDependencies', {})}
                
                # Frameworks JS
                if 'react' in deps:
                    tech_stack["frameworks"].add("react")
                if 'vue' in deps:
                    tech_stack["frameworks"].add("vue")
                if 'angular' in deps or '@angular/core' in deps:
                    tech_stack["frameworks"].add("angular")
                if 'next' in deps:
                    tech_stack["frameworks"].add("next.js")
                if 'nuxt' in deps:
                    tech_stack["frameworks"].add("nuxt.js")
                
                # Build tools
                if 'webpack' in deps:
                    tech_stack["build_tools"].add("webpack")
                if 'parcel' in deps:
                    tech_stack["build_tools"].add("parcel")
                if 'rollup' in deps:
                    tech_stack["build_tools"].add("rollup")
                if 'vite' in deps:
                    tech_stack["build_tools"].add("vite")
                
                # CI/CD tools in scripts
                scripts = package_json.get('scripts', {})
                for script_cmd in scripts.values():
                    if 'docker' in script_cmd:
                        tech_stack["container_tech"].add("docker")
                    if 'aws' in script_cmd or 'cloudformation' in script_cmd:
                        tech_stack["cloud_providers"].add("aws")
                    if 'gcloud' in script_cmd or 'gsutil' in script_cmd:
                        tech_stack["cloud_providers"].add("gcp")
                    if 'az ' in script_cmd:
                        tech_stack["cloud_providers"].add("azure")
            except json.JSONDecodeError:
                pass
    
    # Python spécifique
    if 'requirements.txt' in file_paths:
        with open(os.path.join(os.path.dirname(project_files[0]), 'requirements.txt'), 'r') as f:
            requirements = f.read().lower()
            if 'django' in requirements:
                tech_stack["frameworks"].add("django")
            if 'flask' in requirements:
                tech_stack["frameworks"].add("flask")
            if 'fastapi' in requirements:
                tech_stack["frameworks"].add("fastapi")
    
    # Docker
    if 'dockerfile' in file_paths or 'Dockerfile' in file_paths:
        tech_stack["container_tech"].add("docker")
    if 'docker-compose.yml' in file_paths or 'docker-compose.yaml' in file_paths:
        tech_stack["container_tech"].add("docker-compose")
    
    # Kubernetes
    if any(f.endswith('.yaml') or f.endswith('.yml') for f in project_files):
        for f in project_files:
            if f.endswith('.yaml') or f.endswith('.yml'):
                with open(f, 'r') as yaml_file:
                    content = yaml_file.read()
                    if 'apiVersion:' in content and 'kind:' in content:
                        tech_stack["container_tech"].add("kubernetes")
                        break
    
    # CI/CD
    if '.github/workflows' in str(project_files):
        tech_stack["ci_cd_tools"].add("github-actions")
    if '.gitlab-ci.yml' in file_paths:
        tech_stack["ci_cd_tools"].add("gitlab-ci")
    if 'Jenkinsfile' in file_paths:
        tech_stack["ci_cd_tools"].add("jenkins")
    if '.travis.yml' in file_paths:
        tech_stack["ci_cd_tools"].add("travis-ci")
    if 'azure-pipelines.yml' in file_paths:
        tech_stack["ci_cd_tools"].add("azure-devops")
    if 'bitbucket-pipelines.yml' in file_paths:
        tech_stack["ci_cd_tools"].add("bitbucket-pipelines")
    if 'cloudbuild.yaml' in file_paths or 'cloudbuild.yml' in file_paths:
        tech_stack["ci_cd_tools"].add("cloud-build")
        tech_stack["cloud_providers"].add("gcp")
    if 'buildspec.yml' in file_paths or 'buildspec.yaml' in file_paths:
        tech_stack["ci_cd_tools"].add("aws-codebuild")
        tech_stack["cloud_providers"].add("aws")
    
    # Convertir les sets en listes pour la sérialisation JSON
    for key in tech_stack:
        tech_stack[key] = list(tech_stack[key])
    
    return tech_stack

def generate_ci_cd_pipeline(project_specs, tech_stack, project_dir):
    """
    Génère une configuration CI/CD adaptée au stack technologique détecté.
    
    Args:
        project_specs (str): Spécifications du projet
        tech_stack (dict): Technologies détectées
        project_dir (str): Répertoire du projet
        
    Returns:
        dict: Résultat de la génération
    """
    socketio.emit('log', {'type': 'info', 'message': "Génération de pipeline CI/CD..."})
    
    # Détecter les préférences de CI/CD si spécifiées
    ci_cd_preferences = []
    if 'github-actions' in tech_stack.get('ci_cd_tools', []):
        ci_cd_preferences.append('github-actions')
    if 'gitlab-ci' in tech_stack.get('ci_cd_tools', []):
        ci_cd_preferences.append('gitlab-ci')
    if 'jenkins' in tech_stack.get('ci_cd_tools', []):
        ci_cd_preferences.append('jenkins')
    
    # Si aucune préférence n'est détectée, utilisez GitHub Actions par défaut
    if not ci_cd_preferences:
        ci_cd_preferences = ['github-actions']
    
    system_prompt = """
    Vous êtes un expert DevOps spécialisé dans la création de pipelines CI/CD robustes.
    Votre tâche est de générer des configurations de pipeline CI/CD adaptées au projet décrit.
    
    Suivez ces instructions:
    1. Analysez soigneusement le stack technologique et les spécifications du projet
    2. Créez des pipelines CI/CD complets et fonctionnels pour les plateformes demandées
    3. Incluez les étapes essentielles: build, test, analyse statique, sécurité, déploiement
    4. Ajoutez des commentaires explicatifs pour chaque section importante
    5. Utilisez les meilleures pratiques DevOps: parallélisation, caching, optimisation
    
    Pour chaque fichier de configuration, fournissez:
    - Le chemin complet du fichier
    - Le contenu complet formaté avec la syntaxe correcte
    - Une brève description de ce que fait le pipeline
    
    Format de réponse:
    ```
    # Pipeline CI/CD pour [Nom du Projet]
    
    ## Vue d'ensemble
    [Description du pipeline et de ses objectifs]
    
    ## Fichiers de configuration:
    
    fichier: `.github/workflows/ci-cd.yml`
    ```yaml
    [contenu YAML complet]
    ```
    
    fichier: `[autre fichier si applicable]`
    ```
    [contenu]
    ```
    
    ## Instructions d'utilisation
    [Comment utiliser et personnaliser ces pipelines]
    ```
    """
    
    prompt = f"""
    Je dois créer des pipelines CI/CD pour un projet avec le stack technologique suivant:
    
    {json.dumps(tech_stack, indent=2)}
    
    Voici les spécifications du projet:
    
    {project_specs}
    
    Générez des configurations CI/CD complètes pour les plateformes suivantes: {', '.join(ci_cd_preferences)}.
    
    Pour chaque pipeline, incluez:
    1. Étapes de build adapté au langage/framework
    2. Exécution des tests automatisés
    3. Analyse de qualité de code
    4. Scans de sécurité
    5. Build et push d'images Docker (si pertinent)
    6. Déploiement vers les environnements appropriés
    7. Notifications
    
    Assurez-vous d'utiliser les bonnes pratiques CI/CD: caching, parallélisation, matrices de test, etc.
    """
    
    # Invoquer Claude pour générer les configurations
    response = invoke_claude(prompt, system_prompt, max_tokens=8000)
    
    # Extraire et sauvegarder les fichiers
    files_saved = extract_files_from_response(response, project_dir)
    
    return {
        "files": files_saved,
        "raw_response": response
    }

def generate_docker_config(project_specs, tech_stack, project_dir):
    """
    Génère des configurations Docker pour le projet.
    
    Args:
        project_specs (str): Spécifications du projet
        tech_stack (dict): Technologies détectées
        project_dir (str): Répertoire du projet
        
    Returns:
        dict: Résultat de la génération
    """
    socketio.emit('log', {'type': 'info', 'message': "Génération de configurations Docker..."})
    
    system_prompt = """
    Vous êtes un expert DevOps spécialisé dans la conteneurisation d'applications.
    Votre tâche est de créer des configurations Docker optimisées, sécurisées et efficaces.
    
    Suivez ces directives:
    1. Utilisez des images de base officielles et légères (alpine quand possible)
    2. Appliquez les meilleures pratiques de sécurité Docker
    3. Optimisez les couches pour le cache et la taille des images
    4. Configurez les utilisateurs non-root
    5. Incluez des healthchecks appropriés
    6. Optimisez pour la production (multi-stage builds)
    
    Format de réponse:
    ```
    # Configuration Docker pour [Nom du Projet]
    
    ## Vue d'ensemble
    [Description de l'architecture containerisée]
    
    ## Fichiers:
    
    fichier: `Dockerfile`
    ```dockerfile
    [contenu dockerfile complet]
    ```
    
    fichier: `docker-compose.yml`
    ```yaml
    [contenu docker-compose complet]
    ```
    
    fichier: `.dockerignore`
    ```
    [contenu]
    ```
    
    ## Instructions d'utilisation
    [Comment construire et exécuter les conteneurs]
    ```
    """
    
    prompt = f"""
    Je dois créer des configurations Docker pour un projet avec le stack technologique suivant:
    
    {json.dumps(tech_stack, indent=2)}
    
    Voici les spécifications du projet:
    
    {project_specs}
    
    Générez les fichiers Docker suivants:
    1. Un Dockerfile optimisé pour la production (multi-stage si approprié)
    2. Un fichier docker-compose.yml pour le développement et le déploiement
    3. Un fichier .dockerignore adapté
    
    Si pertinent pour le projet, incluez:
    - Configuration de services additionnels (base de données, cache, etc.)
    - Variables d'environnement nécessaires
    - Configuration des volumes
    - Configuration réseau
    - Healthchecks
    
    Assurez-vous que la configuration est optimisée pour:
    - Sécurité (utilisateurs non-root, images minimales)
    - Performance (caching des couches, optimisation)
    - Maintenabilité (commentaires clairs, structure logique)
    """
    
    # Invoquer Claude pour générer les configurations
    response = invoke_claude(prompt, system_prompt, max_tokens=4096)
    
    # Extraire et sauvegarder les fichiers
    files_saved = extract_files_from_response(response, project_dir)
    
    return {
        "files": files_saved,
        "raw_response": response
    }

def generate_kubernetes_manifests(project_specs, tech_stack, project_dir):
    """
    Génère des manifestes Kubernetes pour le projet.
    
    Args:
        project_specs (str): Spécifications du projet
        tech_stack (dict): Technologies détectées
        project_dir (str): Répertoire du projet
        
    Returns:
        dict: Résultat de la génération
    """
    socketio.emit('log', {'type': 'info', 'message': "Génération de manifestes Kubernetes..."})
    
    system_prompt = """
    Vous êtes un expert Kubernetes spécialisé dans la conception d'architectures cloud-native.
    Votre mission est de créer des manifestes Kubernetes complets, robustes et optimisés.
    
    Suivez ces directives:
    1. Créez une architecture scalable et résiliente
    2. Appliquez les meilleures pratiques Kubernetes
    3. Configurez correctement les ressources (CPU, mémoire)
    4. Implémentez des liveness et readiness probes
    5. Utilisez des secrets et configMaps pour la configuration
    6. Organisez les ressources avec des labels et namespaces
    7. Configurez les stratégies de déploiement appropriées
    
    Format de réponse:
    ```
    # Architecture Kubernetes pour [Nom du Projet]
    
    ## Vue d'ensemble
    [Description de l'architecture Kubernetes]
    
    ## Fichiers:
    
    fichier: `k8s/deployment.yaml`
    ```yaml
    [contenu YAML complet]
    ```
    
    fichier: `k8s/service.yaml`
    ```yaml
    [contenu YAML complet]
    ```
    
    fichier: `k8s/ingress.yaml`
    ```yaml
    [contenu YAML complet]
    ```
    
    [autres fichiers selon besoin]
    
    ## Instructions de déploiement
    [Comment déployer ces ressources]
    ```
    """
    
    prompt = f"""
    Je dois créer des manifestes Kubernetes pour un projet avec le stack technologique suivant:
    
    {json.dumps(tech_stack, indent=2)}
    
    Voici les spécifications du projet:
    
    {project_specs}
    
    Générez les manifestes Kubernetes suivants dans un dossier k8s/:
    
    1. Manifestes de base:
       - Deployment ou StatefulSet selon les besoins
       - Service
       - Ingress ou Route
       - ConfigMap et Secrets
    
    2. Manifestes additionnels si nécessaire:
       - HorizontalPodAutoscaler
       - PersistentVolumeClaim
       - ServiceAccount et RBAC
       - NetworkPolicy
    
    Assurez-vous que la configuration est:
    - Scalable et hautement disponible
    - Résiliente (probes, stratégies de redémarrage, etc.)
    - Sécurisée (contexte non-root, RBAC, etc.)
    - Optimisée pour les ressources (limites et requêtes)
    - Prête pour les environnements multiples (dev, staging, prod)
    
    Incluez des commentaires explicatifs pour les parties complexes.
    """
    
    # Invoquer Claude pour générer les configurations
    response = invoke_claude(prompt, system_prompt, max_tokens=6000)
    
    # Créer le dossier k8s
    k8s_dir = os.path.join(project_dir, 'k8s')
    os.makedirs(k8s_dir, exist_ok=True)
    
    # Extraire et sauvegarder les fichiers
    files_saved = extract_files_from_response(response, project_dir)
    
    return {
        "files": files_saved,
        "raw_response": response
    }

def generate_infra_as_code(project_specs, tech_stack, project_dir, iac_type="terraform"):
    """
    Génère une configuration Infrastructure as Code (Terraform, CloudFormation, etc.)
    
    Args:
        project_specs (str): Spécifications du projet
        tech_stack (dict): Technologies détectées
        project_dir (str): Répertoire du projet
        iac_type (str): Type d'IaC ("terraform", "cloudformation", "pulumi")
        
    Returns:
        dict: Résultat de la génération
    """
    socketio.emit('log', {'type': 'info', 'message': f"Génération de configuration {iac_type.title()}..."})
    
    # Déterminer le fournisseur cloud principal
    cloud_providers = tech_stack.get('cloud_providers', [])
    primary_provider = "aws"  # Par défaut
    
    if cloud_providers:
        if 'aws' in cloud_providers:
            primary_provider = "aws"
        elif 'gcp' in cloud_providers:
            primary_provider = "gcp"
        elif 'azure' in cloud_providers:
            primary_provider = "azure"
    
    system_prompt = f"""
    Vous êtes un expert DevOps spécialisé en Infrastructure as Code avec {iac_type.title()}.
    Votre mission est de créer des configurations {iac_type.title()} complètes et robustes.
    
    Suivez ces directives:
    1. Concevez une infrastructure cloud standardisée et modulaire
    2. Appliquez les meilleures pratiques {iac_type.title()} et DevSecOps
    3. Utilisez une approche modulaire et réutilisable
    4. Configurez correctement les ressources, la sécurité et le réseau
    5. Incluez des commentaires explicatifs pour les parties complexes
    
    Format de réponse:
    ```
    # Infrastructure as Code ({iac_type.title()}) pour [Nom du Projet]
    
    ## Vue d'ensemble
    [Description de l'infrastructure]
    
    ## Fichiers:
    
    fichier: `[chemin fichier 1]`
    ```
    [contenu complet avec indentation et formatage appropriés]
    ```
    
    fichier: `[chemin fichier 2]`
    ```
    [contenu complet]
    ```
    
    [autres fichiers selon besoin]
    
    ## Instructions de déploiement
    [Comment déployer cette infrastructure]
    ```
    """
    
    if iac_type == "terraform":
        provider_code = {
            "aws": "aws",
            "gcp": "google",
            "azure": "azurerm"
        }.get(primary_provider, "aws")
        
        prompt = f"""
        Je dois créer une configuration Terraform pour un projet avec le stack technologique suivant:
        
        {json.dumps(tech_stack, indent=2)}
        
        Le cloud provider principal est: {primary_provider}
        
        Voici les spécifications du projet:
        
        {project_specs}
        
        Générez une configuration Terraform complète dans une structure modulaire:
        
        1. Structure de base:
           - main.tf - Configuration principale
           - variables.tf - Définition des variables
           - outputs.tf - Sorties de l'infrastructure
           - providers.tf - Configuration des providers
           - backend.tf - Configuration du backend (état)
        
        2. Modules selon les besoins:
           - Réseau (VPC, subnets, security groups)
           - Calcul (EC2, ECS, GKE, AKS selon le provider)
           - Base de données (RDS, Cloud SQL, etc.)
           - Stockage (S3, GCS, etc.)
           - Autres services pertinents
        
        3. Environnements:
           - Structure pour gérer dev, staging, prod
        
        Utilisez la version récente de Terraform (>=1.0) et du provider {provider_code}.
        Incluez des commentaires explicatifs dans le code.
        Suivez les meilleures pratiques: nommage cohérent, tagging, structure modulaire, etc.
        """
    
    elif iac_type == "cloudformation":
        prompt = f"""
        Je dois créer des templates CloudFormation pour un projet AWS avec le stack technologique suivant:
        
        {json.dumps(tech_stack, indent=2)}
        
        Voici les spécifications du projet:
        
        {project_specs}
        
        Générez des templates CloudFormation complets et modulaires:
        
        1. Template principal (master.yaml) qui référence les templates imbriqués
        2. Templates imbriqués organisés par composant:
           - Réseau (VPC, subnets, security groups)
           - Calcul (EC2, ECS, etc.)
           - Base de données (RDS, etc.)
           - Stockage (S3, etc.)
           - Autres services pertinents
        
        3. Paramètres et outputs pour connecter les templates
        4. Mappings pour les configurations spécifiques aux environnements
        
        Utilisez les fonctionnalités CloudFormation modernes (YAML, intrinsèques).
        Incluez des descriptions claires pour les ressources et paramètres.
        Suivez les meilleures pratiques: dépendances explicites, conditions, paramètres, etc.
        """
    
    else:  # Pulumi ou autre
        prompt = f"""
        Je dois créer une configuration Pulumi pour un projet avec le stack technologique suivant:
        
        {json.dumps(tech_stack, indent=2)}
        
        Le cloud provider principal est: {primary_provider}
        
        Voici les spécifications du projet:
        
        {project_specs}
        
        Générez une configuration Pulumi complète en TypeScript:
        
        1. Structure de base:
           - index.ts - Point d'entrée principal
           - Pulumi.yaml - Configuration du projet
           - Pulumi.dev.yaml, Pulumi.prod.yaml - Configurations par environnement
        
        2. Modules organisés par composant:
           - Réseau (VPC, subnets, security groups)
           - Calcul (instances, services, etc.)
           - Base de données 
           - Stockage
           - Autres services pertinents
        
        3. Utilisez des classes et des fonctions pour modulariser le code
        
        Utilisez la version récente de Pulumi avec TypeScript.
        Incluez des commentaires explicatifs dans le code.
        Suivez les meilleures pratiques: nommage cohérent, tagging, structure modulaire, etc.
        """
    
    # Invoquer Claude pour générer les configurations
    response = invoke_claude(prompt, system_prompt, max_tokens=8000)
    
    # Créer le dossier pour le code IaC
    iac_dir = os.path.join(project_dir, iac_type)
    os.makedirs(iac_dir, exist_ok=True)
    
    # Extraire et sauvegarder les fichiers
    files_saved = extract_files_from_response(response, project_dir)
    
    return {
        "files": files_saved,
        "raw_response": response
    }

def create_monitoring_config(project_specs, tech_stack, project_dir):
    """
    Génère des configurations de monitoring et observabilité.
    
    Args:
        project_specs (str): Spécifications du projet
        tech_stack (dict): Technologies détectées
        project_dir (str): Répertoire du projet
        
    Returns:
        dict: Résultat de la génération
    """
    socketio.emit('log', {'type': 'info', 'message': "Génération de configurations de monitoring..."})
    
    system_prompt = """
    Vous êtes un expert en observabilité et monitoring d'applications cloud-native.
    Votre mission est de créer des configurations de monitoring complètes, précises et utiles.
    
    Suivez ces directives:
    1. Configurez des métriques importantes pour l'application et l'infrastructure
    2. Créez des dashboards cohérents et informatifs
    3. Établissez des alertes pertinentes avec des seuils appropriés
    4. Implémentez du tracing distribué si pertinent
    5. Configurez la collecte et l'agrégation de logs
    
    Format de réponse:
    ```
    # Monitoring et Observabilité pour [Nom du Projet]
    
    ## Vue d'ensemble
    [Description de la stratégie de monitoring]
    
    ## Fichiers:
    
    fichier: `monitoring/prometheus/prometheus.yml`
    ```yaml
    [contenu YAML complet]
    ```
    
    fichier: `monitoring/grafana/dashboard.json`
    ```json
    [contenu JSON complet]
    ```
    
    [autres fichiers selon besoin]
    
    ## Métriques clés à surveiller
    [Liste des métriques importantes avec justification]
    
    ## Alertes recommandées
    [Description des alertes à configurer]
    ```
    """
    
    prompt = f"""
    Je dois créer des configurations de monitoring pour un projet avec le stack technologique suivant:
    
    {json.dumps(tech_stack, indent=2)}
    
    Voici les spécifications du projet:
    
    {project_specs}
    
    Générez des configurations complètes pour:
    
    1. Prometheus:
       - Configuration principale (prometheus.yml)
       - Rules d'alerte (alerts.yml)
       - Cibles de scraping adaptées au stack
    
    2. Grafana:
       - Dashboard principal au format JSON
       - Sources de données
    
    3. Intégration avec la stack technologique:
       - Exporters spécifiques aux technologies utilisées
       - Configuration pour l'application elle-même
    
    4. Si pertinent pour le projet:
       - Configuration Loki pour les logs
       - Configuration Jaeger ou Tempo pour le tracing
    
    Incluez également:
    - Documentation des métriques clés à surveiller
    - Alertes recommandées avec seuils
    - Comment intégrer les outils de monitoring dans l'infrastructure
    """
    
    # Invoquer Claude pour générer les configurations
    response = invoke_claude(prompt, system_prompt, max_tokens=6000)
    
    # Créer le dossier monitoring
    monitoring_dir = os.path.join(project_dir, 'monitoring')
    os.makedirs(monitoring_dir, exist_ok=True)
    
    # Extraire et sauvegarder les fichiers
    files_saved = extract_files_from_response(response, project_dir)
    
    return {
        "files": files_saved,
        "raw_response": response
    }

def create_complete_devops_pipeline(project_name, project_specs, output_dir):
    """
    Crée une solution DevOps/CI-CD complète pour un projet.
    
    Args:
        project_name (str): Nom du projet
        project_specs (str): Spécifications du projet
        output_dir (str): Répertoire de sortie
        
    Returns:
        dict: Résultat de la génération
    """
    # Normaliser le nom du projet pour le nom de dossier
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(output_dir, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    socketio.emit('log', {'type': 'info', 'message': f"Création d'une solution DevOps complète pour le projet {project_name}"})
    
    # Préanalyse pour identifier les technologies (à ce stade, nous avons peu d'information)
    initial_tech_stack = {
        "languages": [],
        "frameworks": [],
        "build_tools": [],
        "databases": [],
        "cloud_providers": [],
        "container_tech": ["docker"],  # Supposer Docker par défaut
        "ci_cd_tools": ["github-actions"]  # Supposer GitHub Actions par défaut
    }
    
    # Étape 1: Génération des configurations Docker de base
    docker_results = generate_docker_config(project_specs, initial_tech_stack, project_dir)
    
    # Étape 2: Génération des pipelines CI/CD
    ci_cd_results = generate_ci_cd_pipeline(project_specs, initial_tech_stack, project_dir)
    
    # À ce stade, nous avons plus de fichiers pour analyser les technologies
    project_files = [os.path.join(project_dir, f) for f in os.listdir(project_dir) 
                    if os.path.isfile(os.path.join(project_dir, f))]
    
    # Détecter les technologies à partir des fichiers générés
    detected_tech_stack = detect_technologies(project_files)
    
    # Étape 3: Génération des manifestes Kubernetes
    kubernetes_results = generate_kubernetes_manifests(project_specs, detected_tech_stack, project_dir)
    
    # Étape 4: Génération de l'infrastructure as code (Terraform par défaut)
    iac_results = generate_infra_as_code(project_specs, detected_tech_stack, project_dir, "terraform")
    
    # Étape 5: Configuration de monitoring
    monitoring_results = create_monitoring_config(project_specs, detected_tech_stack, project_dir)
    
    # Créer un README.md pour le projet
    readme_path = os.path.join(project_dir, "README.md")
    
    readme_system_prompt = """
    Vous êtes un expert en documentation technique, spécialisé dans la création de README clairs, 
    informatifs et bien structurés pour les projets DevOps. Votre objectif est de créer une 
    documentation qui aide les utilisateurs à comprendre et utiliser la configuration DevOps.
    
    Concentrez-vous sur:
    1. Une introduction claire au projet et à sa configuration DevOps
    2. Des instructions d'installation et d'utilisation précises
    3. Une documentation bien structurée avec des sections logiques
    4. Des exemples pratiques et des commandes concrètes
    5. Une documentation technique accessible aux développeurs et aux DevOps
    
    Format de la réponse:
    Un document markdown complet et bien formaté, prêt à être utilisé comme README.md.
    """
    
    readme_prompt = f"""
    Veuillez créer un README.md complet pour la configuration DevOps du projet suivant:
    
    Nom du projet: {project_name}
    
    Spécifications du projet:
    {project_specs}
    
    Technologies détectées:
    {json.dumps(detected_tech_stack, indent=2)}
    
    Configuration DevOps générée:
    - Fichiers Docker: {docker_results["files"]}
    - Pipelines CI/CD: {ci_cd_results["files"]}
    - Manifestes Kubernetes: {kubernetes_results["files"]}
    - Infrastructure as Code: {iac_results["files"]}
    - Configuration de monitoring: {monitoring_results["files"]}
    
    Le README doit inclure:
    1. Une introduction au projet et à sa configuration DevOps
    2. Prérequis et dépendances
    3. Instructions d'installation et de configuration
    4. Guide d'utilisation pour chaque composant (Docker, CI/CD, K8s, etc.)
    5. Structure de la configuration et description des fichiers
    6. Bonnes pratiques et recommandations
    7. Troubleshooting commun
    
    Assurez-vous que le README est clair, bien structuré, et contient des exemples concrets de commandes.
    """
    
    # Invoquer Claude pour générer le README
    readme_content = invoke_claude(readme_prompt, readme_system_prompt, max_tokens=4096)
    
    with open(readme_path, 'w') as f:
        f.write(readme_content)
    
    socketio.emit('log', {'type': 'success', 'message': "README.md généré avec succès"})
    
    # Résumé de la configuration générée
    all_files = docker_results["files"] + ci_cd_results["files"] + kubernetes_results["files"] + iac_results["files"] + monitoring_results["files"] + ["README.md"]
    
    results = {
        "project_dir": project_dir,
        "detected_tech_stack": detected_tech_stack,
        "files_generated": all_files,
        "components": {
            "docker": docker_results["files"],
            "ci_cd": ci_cd_results["files"],
            "kubernetes": kubernetes_results["files"],
            "iac": iac_results["files"],
            "monitoring": monitoring_results["files"],
            "documentation": ["README.md"]
        }
    }
    
    socketio.emit('log', {'type': 'success', 'message': f"Configuration DevOps complète générée avec succès dans {project_dir}"})
    socketio.emit('devops_complete', {'project_dir': project_dir, 'files': all_files})
    
    return results

@app.route('/devops_request', methods=['POST'])
def devops_request():
    """Endpoint pour recevoir et traiter les demandes de configuration DevOps"""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande DevOps"})
    
    data = request.json
    project_name = data.get('project_name', 'DevOps-Project')
    project_specs = data.get('specs', '')
    
    if not project_specs:
        return jsonify({'error': "Les spécifications du projet sont requises"})
    
    try:
        # Créer une configuration DevOps complète
        results = create_complete_devops_pipeline(project_name, project_specs, WORKSPACE_DIR)
        
        return jsonify({
            'project_dir': results['project_dir'],
            'files': results['files_generated'],
            'tech_stack': results['detected_tech_stack']
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande DevOps: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message})

@app.route('/api/devops_config', methods=['POST'])
def api_devops_config():
    """API endpoint pour les demandes de configuration DevOps provenant d'autres agents"""
    data = request.json
    project_name = data.get('project_name', 'DevOps-Project')
    project_specs = data.get('specs', '')
    config_type = data.get('config_type', 'complete')  # complete, docker, ci_cd, kubernetes, iac, monitoring
    
    if not project_specs:
        return jsonify({'error': "Les spécifications du projet sont requises", 'status': 'error'})
    
    socketio.emit('log', {'type': 'info', 'message': f"Réception d'une demande d'API pour {project_name} (type: {config_type})"})
    
    try:
        # Normaliser le nom du projet pour le nom de dossier
        safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
        project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
        
        # Créer le dossier du projet s'il n'existe pas
        if not os.path.exists(project_dir):
            os.makedirs(project_dir)
        
        # Configuration de base
        initial_tech_stack = {
            "languages": [],
            "frameworks": [],
            "build_tools": [],
            "databases": [],
            "cloud_providers": [],
            "container_tech": ["docker"],  # Supposer Docker par défaut
            "ci_cd_tools": ["github-actions"]  # Supposer GitHub Actions par défaut
        }
        
        results = {}
        
        if config_type == 'complete':
            # Générer une configuration complète
            results = create_complete_devops_pipeline(project_name, project_specs, WORKSPACE_DIR)
        elif config_type == 'docker':
            # Uniquement la configuration Docker
            docker_results = generate_docker_config(project_specs, initial_tech_stack, project_dir)
            results = {
                "project_dir": project_dir,
                "files_generated": docker_results["files"],
                "raw_response": docker_results["raw_response"]
            }
        elif config_type == 'ci_cd':
            # Uniquement les pipelines CI/CD
            ci_cd_results = generate_ci_cd_pipeline(project_specs, initial_tech_stack, project_dir)
            results = {
                "project_dir": project_dir,
                "files_generated": ci_cd_results["files"],
                "raw_response": ci_cd_results["raw_response"]
            }
        elif config_type == 'kubernetes':
            # Uniquement les manifestes Kubernetes
            kubernetes_results = generate_kubernetes_manifests(project_specs, initial_tech_stack, project_dir)
            results = {
                "project_dir": project_dir,
                "files_generated": kubernetes_results["files"],
                "raw_response": kubernetes_results["raw_response"]
            }
        elif config_type == 'iac':
            # Uniquement l'infrastructure as code
            iac_type = data.get('iac_type', 'terraform')
            iac_results = generate_infra_as_code(project_specs, initial_tech_stack, project_dir, iac_type)
            results = {
                "project_dir": project_dir,
                "files_generated": iac_results["files"],
                "raw_response": iac_results["raw_response"]
            }
        elif config_type == 'monitoring':
            # Uniquement la configuration de monitoring
            monitoring_results = create_monitoring_config(project_specs, initial_tech_stack, project_dir)
            results = {
                "project_dir": project_dir,
                "files_generated": monitoring_results["files"],
                "raw_response": monitoring_results["raw_response"]
            }
        
        return jsonify({
            'project_name': project_name,
            'project_dir': results.get('project_dir', project_dir),
            'files': results.get('files_generated', []),
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande DevOps: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

@app.route('/api/ci_cd_pipeline', methods=['POST'])
def api_ci_cd_pipeline():
    """API endpoint pour l'exécution des pipelines CI/CD"""
    data = request.json
    project_name = data.get('project_name', 'DevOps-Project')
    action = data.get('action', 'status')  # status, run, deploy, rollback
    environment = data.get('environment', 'dev')  # dev, staging, prod
    
    socketio.emit('log', {'type': 'info', 'message': f"Réception d'une demande CI/CD pour {project_name} (action: {action}, env: {environment})"})
    
    # Normaliser le nom du projet pour le nom de dossier
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Vérifier que le projet existe
    if not os.path.exists(project_dir):
        error_message = f"Projet {project_name} non trouvé"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})
    
    try:
        result = {
            'project_name': project_name,
            'action': action,
            'environment': environment,
            'status': 'success',
            'details': {}
        }
        
        if action == 'status':
            # Vérifier l'état du pipeline
            socketio.emit('log', {'type': 'info', 'message': f"Vérification de l'état du pipeline pour {project_name}"})
            
            # Simuler une vérification d'état (à remplacer par une vraie implémentation)
            result['details'] = {
                'pipeline_state': 'active',
                'last_run': '2025-03-14T10:30:00Z',
                'last_status': 'success',
                'environments': {
                    'dev': {'status': 'deployed', 'version': '1.2.3'},
                    'staging': {'status': 'deployed', 'version': '1.2.1'},
                    'prod': {'status': 'deployed', 'version': '1.2.0'}
                }
            }
            
        elif action == 'run':
            # Exécuter le pipeline
            socketio.emit('log', {'type': 'info', 'message': f"Exécution du pipeline pour {project_name}"})
            
            # Simuler l'exécution du pipeline (à remplacer par une vraie implémentation)
            run_id = f"run-{int(time.time())}"
            
            # Créer un thread pour simuler l'exécution du pipeline
            def run_pipeline_simulation():
                stages = ['build', 'test', 'package', 'deploy-prep']
                
                for stage in stages:
                    socketio.emit('log', {'type': 'info', 'message': f"Pipeline {run_id}: Exécution de l'étape '{stage}'..."})
                    socketio.emit('pipeline_update', {
                        'project_name': project_name,
                        'run_id': run_id,
                        'stage': stage,
                        'status': 'running'
                    })
                    
                    # Simuler le temps d'exécution
                    time.sleep(2)
                    
                    socketio.emit('log', {'type': 'success', 'message': f"Pipeline {run_id}: Étape '{stage}' terminée"})
                    socketio.emit('pipeline_update', {
                        'project_name': project_name,
                        'run_id': run_id,
                        'stage': stage,
                        'status': 'success'
                    })
                
                socketio.emit('log', {'type': 'success', 'message': f"Pipeline {run_id}: Exécution terminée avec succès"})
                socketio.emit('pipeline_complete', {
                    'project_name': project_name,
                    'run_id': run_id,
                    'status': 'success'
                })
            
            pipeline_thread = threading.Thread(target=run_pipeline_simulation)
            pipeline_thread.daemon = True
            pipeline_thread.start()
            
            result['details'] = {
                'run_id': run_id,
                'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'status': 'running',
                'message': 'Pipeline démarré'
            }
            
        elif action == 'deploy':
            # Déployer vers l'environnement spécifié
            socketio.emit('log', {'type': 'info', 'message': f"Déploiement de {project_name} vers {environment}"})
            
            # Simuler un déploiement (à remplacer par une vraie implémentation)
            deploy_id = f"deploy-{int(time.time())}"
            
            # Créer un thread pour simuler le déploiement
            def run_deployment_simulation():
                stages = ['prepare', 'validate', 'deploy', 'verify']
                
                for stage in stages:
                    socketio.emit('log', {'type': 'info', 'message': f"Déploiement {deploy_id}: Exécution de l'étape '{stage}'..."})
                    socketio.emit('deployment_update', {
                        'project_name': project_name,
                        'deploy_id': deploy_id,
                        'environment': environment,
                        'stage': stage,
                        'status': 'running'
                    })
                    
                    # Simuler le temps d'exécution
                    time.sleep(1.5)
                    
                    socketio.emit('log', {'type': 'success', 'message': f"Déploiement {deploy_id}: Étape '{stage}' terminée"})
                    socketio.emit('deployment_update', {
                        'project_name': project_name,
                        'deploy_id': deploy_id,
                        'environment': environment,
                        'stage': stage,
                        'status': 'success'
                    })
                
                socketio.emit('log', {'type': 'success', 'message': f"Déploiement {deploy_id}: Application déployée avec succès vers {environment}"})
                socketio.emit('deployment_complete', {
                    'project_name': project_name,
                    'deploy_id': deploy_id,
                    'environment': environment,
                    'status': 'success'
                })
            
            deployment_thread = threading.Thread(target=run_deployment_simulation)
            deployment_thread.daemon = True
            deployment_thread.start()
            
            result['details'] = {
                'deploy_id': deploy_id,
                'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'status': 'running',
                'message': f'Déploiement vers {environment} démarré'
            }
            
        elif action == 'rollback':
            # Effectuer un rollback sur l'environnement spécifié
            socketio.emit('log', {'type': 'info', 'message': f"Rollback de {project_name} sur {environment}"})
            
            # Simuler un rollback (à remplacer par une vraie implémentation)
            rollback_id = f"rollback-{int(time.time())}"
            
            # Créer un thread pour simuler le rollback
            def run_rollback_simulation():
                stages = ['prepare', 'stop-current', 'restore-previous', 'verify']
                
                for stage in stages:
                    socketio.emit('log', {'type': 'info', 'message': f"Rollback {rollback_id}: Exécution de l'étape '{stage}'..."})
                    socketio.emit('rollback_update', {
                        'project_name': project_name,
                        'rollback_id': rollback_id,
                        'environment': environment,
                        'stage': stage,
                        'status': 'running'
                    })
                    
                    # Simuler le temps d'exécution
                    time.sleep(1.5)
                    
                    socketio.emit('log', {'type': 'success', 'message': f"Rollback {rollback_id}: Étape '{stage}' terminée"})
                    socketio.emit('rollback_update', {
                        'project_name': project_name,
                        'rollback_id': rollback_id,
                        'environment': environment,
                        'stage': stage,
                        'status': 'success'
                    })
                
                socketio.emit('log', {'type': 'success', 'message': f"Rollback {rollback_id}: Application restaurée avec succès sur {environment}"})
                socketio.emit('rollback_complete', {
                    'project_name': project_name,
                    'rollback_id': rollback_id,
                    'environment': environment,
                    'status': 'success'
                })
            
            rollback_thread = threading.Thread(target=run_rollback_simulation)
            rollback_thread.daemon = True
            rollback_thread.start()
            
            result['details'] = {
                'rollback_id': rollback_id,
                'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'status': 'running',
                'message': f'Rollback sur {environment} démarré'
            }
        
        return jsonify(result)
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande CI/CD: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5005)


@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent devops"})
    
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
            log_path = os.path.join(log_dir, 'devops.log')
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