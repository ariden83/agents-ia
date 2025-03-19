import logging
import re
import time
import json
import re
import threading
import time
import os
from threading import Event
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

# Dossier de travail pour les projets Android
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'developpeurandroid.log')

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
                3. Utiliser une approche plus standard pour ce type de problème
                
                Je vais faire de mon mieux pour poursuivre l'analyse avec les informations disponibles.
                """
                
                return fallback_response
    
    # Ce code ne devrait jamais être atteint, mais par sécurité
    socketio.emit('loading_end')
    return "Erreur inattendue lors de l'invocation du modèle"

def extract_code_blocks(text):
    """
    Extrait les blocs de code Kotlin/Java à partir d'un texte Markdown.
    
    Args:
        text (str): Texte contenant des blocs de code
        
    Returns:
        list: Liste des blocs de code extraits
    """
    if not text:
        return []
    
    # Pattern principal pour les blocs de code Kotlin/Java (```kotlin ... ```, ```java ... ```)
    code_patterns = [
        r'```(?:kotlin)?\s*(.*?)\s*```',
        r'```(?:java)?\s*(.*?)\s*```'
    ]
    
    # Rechercher tous les blocs de code explicites
    code_blocks = []
    for pattern in code_patterns:
        blocks = re.findall(pattern, text, re.DOTALL)
        code_blocks.extend(blocks)
    
    # Si aucun bloc spécifique n'est trouvé, chercher des blocs génériques
    if not code_blocks:
        generic_pattern = r'```\s*(.*?)\s*```'
        code_blocks = re.findall(generic_pattern, text, re.DOTALL)
    
    # Chercher aussi les blocs indentés avec 4 espaces (style markdown)
    if not code_blocks:
        indent_blocks = []
        lines = text.split('\n')
        current_block = []
        in_block = False
        
        for line in lines:
            if line.startswith('    ') and not line.startswith('     '):
                if not in_block:
                    in_block = True
                current_block.append(line[4:])  # Enlever l'indentation
            else:
                if in_block and current_block:
                    indent_blocks.append('\n'.join(current_block))
                    current_block = []
                    in_block = False
        
        # Ajouter le dernier bloc s'il existe
        if in_block and current_block:
            indent_blocks.append('\n'.join(current_block))
        
        code_blocks.extend(indent_blocks)
    
    # Dernier recours: chercher tout ce qui ressemble à du code Kotlin ou Java par heuristique
    if not code_blocks:
        # Chercher des sections qui contiennent des mots-clés Kotlin/Java fréquents
        code_keywords = [
            "import ", "class ", "interface ", "fun ", "override ", "val ", "var ",
            "public ", "private ", "protected ", "static ", "final ", "void ", "@Override"
        ]
        
        sections = re.split(r'\n\n+', text)
        for section in sections:
            if any(keyword in section for keyword in code_keywords) and len(section.strip()) > 20:
                # Éviter d'extraire de simples mentions de mots-clés dans le texte
                if section.count('\n') >= 2:  # Au moins quelques lignes
                    code_blocks.append(section.strip())
    
    return code_blocks

def create_android_project(project_name, code_analysis):
    """
    Crée un projet Android à partir de l'analyse du code avec organisation en fichiers.
    
    Args:
        project_name (str): Nom du projet
        code_analysis (str): Analyse du code contenant des explications et des implémentations
    
    Returns:
        dict: Informations sur le projet créé
    """
    socketio.emit('log', {'type': 'info', 'message': "Création du projet Android..."})
    
    # Normaliser le nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    # Dossiers standard d'un projet Android
    app_dir = os.path.join(project_dir, "app")
    src_dir = os.path.join(app_dir, "src", "main")
    java_dir = os.path.join(src_dir, "java", "com", "example", safe_project_name)
    res_dir = os.path.join(src_dir, "res", "layout")
    
    # Création des dossiers nécessaires
    for directory in [app_dir, src_dir, java_dir, res_dir]:
        os.makedirs(directory, exist_ok=True)
    
    # Liste des fichiers générés
    generated_files = []
    
    # Extraction des blocs de code
    code_blocks = extract_code_blocks(code_analysis)
    
    if not code_blocks:
        socketio.emit('log', {'type': 'warning', 'message': "Aucun bloc de code Kotlin/Java trouvé dans l'analyse. Tentative de récupération..."})
        # Tentative de récupération en considérant tout le texte
        sections = re.split(r'\n#{1,3}\s+', code_analysis)
        if sections and len(sections) > 1:
            # Prendre la section la plus longue comme code potentiel
            sections.sort(key=len, reverse=True)
            code_blocks = [sections[0]]
    
    # Analyse de la structure du projet à partir du texte
    # Recherche des noms de fichiers potentiels dans le texte
    file_patterns = [r'[\w_]+\.kt', r'[\w_]+\.java', r'[\w_]+\.xml']
    file_names = []
    
    for pattern in file_patterns:
        file_names.extend(re.findall(pattern, code_analysis))
    
    file_names = list(set(file_names))  # Supprimer les doublons
    
    # Si aucun nom de fichier n'est trouvé, chercher dans les sections de titres
    if not file_names:
        heading_pattern = r'#+\s+(.*?)\s*\n'
        headings = re.findall(heading_pattern, code_analysis)
        for heading in headings:
            for ext in ['.kt', '.java', '.xml']:
                file_match = re.search(r'(\w+' + ext + ')', heading)
                if file_match:
                    file_names.append(file_match.group(1))
    
    # Si toujours aucun nom de fichier, utiliser des noms par défaut
    if not file_names:
        file_names = [f"MainActivity.kt", f"activity_main.xml"]
    
    # Organisation des blocs de code dans les fichiers trouvés
    # Détecter les sections de code qui indiquent un fichier spécifique
    file_sections = {}
    current_section = None
    
    # Diviser l'analyse en sections
    analysis_sections = re.split(r'\n#{1,3}\s+', code_analysis)
    
    for i, section in enumerate(analysis_sections):
        if i == 0:  # Ignorer l'introduction
            continue
            
        # Chercher les noms de fichiers au début de la section
        section_lines = section.strip().split('\n')
        if not section_lines:
            continue
            
        section_title = section_lines[0].strip()
        
        # Si le titre contient un nom de fichier, associer cette section à ce fichier
        for file_name in file_names:
            if file_name in section_title:
                current_section = file_name
                if current_section not in file_sections:
                    file_sections[current_section] = []
                break
        
        # Extraire les blocs de code de cette section
        section_code_blocks = extract_code_blocks('\n'.join(section_lines))
        
        # Si un fichier est associé à cette section, ajouter les blocs de code
        if current_section and section_code_blocks:
            file_sections[current_section].extend(section_code_blocks)
    
    # Traiter chaque fichier
    for file_name in file_names:
        file_extension = os.path.splitext(file_name)[1].lower()
        
        # Déterminer le dossier de destination en fonction de l'extension
        if file_extension in ['.kt', '.java']:
            file_path = os.path.join(java_dir, file_name)
        elif file_extension == '.xml':
            file_path = os.path.join(res_dir, file_name)
        else:
            file_path = os.path.join(project_dir, file_name)
        
        # Si le fichier a des sections de code spécifiques, les utiliser
        if file_name in file_sections and file_sections[file_name]:
            file_content = "\n\n".join(file_sections[file_name])
        # Sinon, pour les fichiers .kt/.java, utiliser le premier bloc de code
        elif file_extension in ['.kt', '.java'] and code_blocks and file_name == file_names[0]:
            file_content = code_blocks[0]
        # Pour les fichiers XML, utiliser un contenu par défaut
        elif file_extension == '.xml' and file_name.startswith('activity_'):
            file_content = """<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout 
    xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    xmlns:tools="http://schemas.android.com/tools"
    android:layout_width="match_parent"
    android:layout_height="match_parent">

    <TextView
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:text="Hello World!"
        app:layout_constraintBottom_toBottomOf="parent"
        app:layout_constraintLeft_toLeftOf="parent"
        app:layout_constraintRight_toRightOf="parent"
        app:layout_constraintTop_toTopOf="parent" />

</androidx.constraintlayout.widget.ConstraintLayout>"""
        else:
            continue  # Ignorer les fichiers sans contenu
        
        # Ajouter le package et les imports pour les fichiers Kotlin/Java
        if file_extension == '.kt' and "package " not in file_content:
            file_content = f"package com.example.{safe_project_name}\n\n" + file_content
        elif file_extension == '.java' and "package " not in file_content:
            file_content = f"package com.example.{safe_project_name};\n\n" + file_content
        
        # Créer le dossier parent s'il n'existe pas
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Écrire le fichier avec son contenu
        with open(file_path, 'w') as f:
            if file_extension in ['.kt', '.java']:
                f.write(f"/**\n * {file_name}\n * {safe_project_name}\n *\n * Généré par l'Agent Développeur Android\n */\n\n")
            elif file_extension == '.xml':
                f.write(f"<!-- {file_name} - Généré par l'Agent Développeur Android -->\n")
            f.write(file_content)
        
        generated_files.append(file_path)
        
        socketio.emit('log', {'type': 'success', 'message': f"Fichier créé: {file_path}"})
    
    # Création d'un README.md pour le projet
    readme_path = os.path.join(project_dir, "README.md")
    
    # Analyse de l'code_analysis pour en extraire une description
    description_match = re.search(r'^(?:#\s+.*?)\n(.*?)(?=\n#|\n```|\Z)', code_analysis, re.MULTILINE | re.DOTALL)
    description = ""
    if description_match:
        description = description_match.group(1).strip()
    
    # Si pas de description, extraire la première section de texte non-code
    if not description:
        sections = re.split(r'```.*?```', code_analysis, flags=re.DOTALL)
        if sections and sections[0].strip():
            description = sections[0].strip()
    
    # Construction du contenu du README
    readme_content = f"""# {project_name}

{description}

## Prérequis

- Android Studio Arctic Fox ou supérieur
- Gradle 7.0+
- Android SDK 31+
- Kotlin 1.6+ ou Java 11+

## Installation

1. Clonez ce dépôt
2. Ouvrez le projet dans Android Studio
3. Compilez et exécutez l'application sur un émulateur ou un appareil
"""
    
    # Écrire le README
    with open(readme_path, 'w') as f:
        f.write(readme_content)
    
    generated_files.append(readme_path)
    
    # Créer un fichier build.gradle simple
    build_gradle_path = os.path.join(app_dir, "build.gradle")
    build_gradle_content = """plugins {
    id 'com.android.application'
    id 'kotlin-android'
}

android {
    compileSdkVersion 33
    
    defaultConfig {
        applicationId "com.example.${safe_project_name}"
        minSdkVersion 21
        targetSdkVersion 33
        versionCode 1
        versionName "1.0"
        
        testInstrumentationRunner "androidx.test.runner.AndroidJUnitRunner"
    }
    
    buildTypes {
        release {
            minifyEnabled false
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
        }
    }
    
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_1_8
        targetCompatibility JavaVersion.VERSION_1_8
    }
    
    kotlinOptions {
        jvmTarget = '1.8'
    }
}

dependencies {
    implementation 'androidx.core:core-ktx:1.7.0'
    implementation 'androidx.appcompat:appcompat:1.4.1'
    implementation 'com.google.android.material:material:1.5.0'
    implementation 'androidx.constraintlayout:constraintlayout:2.1.3'
    testImplementation 'junit:junit:4.13.2'
    androidTestImplementation 'androidx.test.ext:junit:1.1.3'
    androidTestImplementation 'androidx.test.espresso:espresso-core:3.4.0'
}"""
    
    with open(build_gradle_path, 'w') as f:
        f.write(build_gradle_content)
    
    generated_files.append(build_gradle_path)
    
    socketio.emit('log', {'type': 'success', 'message': f"Projet Android créé dans {project_dir}"})
    
    return {
        "project_dir": project_dir,
        "files": generated_files,
        "main_file": generated_files[0] if generated_files else None
    }

def analyze_android_problem(specs, requirements=None):
    """
    Analyse un problème de développement Android et génère une solution.
    
    Args:
        specs (str): Spécifications du projet
        requirements (str, optional): Exigences techniques spécifiques
        
    Returns:
        str: Analyse du problème avec implémentation Kotlin/Java
    """
    socketio.emit('log', {'type': 'info', 'message': "Analyse du problème de développement Android en cours..."})
    
    # Système prompt pour guider Claude à fournir une solution Android
    system_prompt = """
    Vous êtes un expert en développement Android spécialisé dans la conception et l'implémentation de solutions robustes et idiomates.
    Votre tâche est d'analyser les spécifications fournies et de proposer une solution Android complète et optimale.
    
    Voici comment structurer votre réponse:
    
    1. Commencez par une analyse des exigences, identifiant les fonctionnalités clés et les défis techniques
    2. Proposez une architecture adaptée au problème (MVVM, Clean Architecture, etc.)
    3. Fournissez une implémentation complète de préférence en Kotlin (ou Java si demandé)
    4. Incluez les fichiers XML nécessaires pour les layouts et autres ressources
    5. Abordez les questions de performance, maintenabilité, et extensibilité
    
    Organisez votre réponse par fichiers, avec une indication claire de la structure du projet.
    Pour chaque fichier, fournissez le code complet dans des blocs de code (```kotlin...``` ou ```java...```)
    et des explications sur le fonctionnement et les choix d'implémentation.
    
    Assurez-vous que votre solution:
    - Suit les conventions Kotlin/Java et les bonnes pratiques Android
    - Inclut la gestion des erreurs appropriée
    - Est modulaire et facilement maintenable
    - Utilise les bibliothèques et APIs Android les plus adaptées
    - Est complète et prête à être utilisée
    """
    
    # Construction du prompt
    prompt = f"""
    Je travaille sur un projet de développement Android et j'ai besoin d'une solution complète.
    
    Voici les spécifications du projet:
    
    {specs}
    """
    
    # Ajout des exigences techniques si fournies
    if requirements:
        prompt += f"""
        
        Exigences techniques spécifiques:
        
        {requirements}
        """
    
    prompt += """
    
    Veuillez me fournir une analyse détaillée avec une implémentation Kotlin/Java complète 
    qui résout ce problème. Précisez les noms des fichiers à créer et leur contenu.
    """
    
    # Invoquer Claude pour l'analyse
    analysis = invoke_claude(prompt, system_prompt, max_tokens=8000)
    
    socketio.emit('log', {'type': 'success', 'message': "Analyse Android terminée"})
    
    return analysis

def generate_android_project(project_name, specs, requirements=None):
    """
    Génère un projet Android complet à partir des spécifications.
    
    Args:
        project_name (str): Nom du projet
        specs (str): Spécifications du projet
        requirements (str, optional): Exigences techniques spécifiques
        
    Returns:
        dict: Informations sur le projet généré
    """
    socketio.emit('log', {'type': 'info', 'message': f"Génération du projet Android '{project_name}'..."})
    
    # Analyser le problème
    code_analysis = analyze_android_problem(specs, requirements)
    
    # Créer le projet Android
    project_info = create_android_project(project_name, code_analysis)
    
    # Ajouter l'analyse à l'objet de retour
    project_info["analysis"] = code_analysis
    
    socketio.emit('log', {'type': 'success', 'message': f"Projet Android '{project_name}' généré avec succès"})
    socketio.emit('android_complete', {
        'project_dir': project_info['project_dir'],
        'files': project_info['files']
    })
    
    return project_info

@app.route('/android_request', methods=['POST'])
def android_request():
    """Endpoint pour recevoir et traiter les demandes de développement Android directes"""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande de développement Android"})
    
    data = request.json
    project_name = data.get('project_name', 'android-project')
    specs = data.get('specs', '')
    requirements = data.get('requirements', None)
    
    if not specs:
        return jsonify({'error': "Les spécifications du projet sont requises", 'status': 'error'})
    
    try:
        # Générer le projet Android
        project_info = generate_android_project(project_name, specs, requirements)
        
        return jsonify({
            'project_name': project_name,
            'project_dir': project_info['project_dir'],
            'files': project_info['files'],
            'main_file': project_info.get('main_file', ''),
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande Android: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

@app.route('/code_request', methods=['POST'])
def code_request():
    """API endpoint pour les demandes de code Android provenant d'autres agents"""
    data = request.json
    project_name = data.get('project_name', 'android-project')
    specs = data.get('specs', '')
    requirements = data.get('requirements', None)
    
    if not specs:
        return jsonify({'error': "Les spécifications du projet sont requises", 'status': 'error'})
    
    socketio.emit('log', {'type': 'info', 'message': f"Réception d'une demande d'API pour {project_name}"})
    
    try:
        # Générer le projet Android
        project_info = generate_android_project(project_name, specs, requirements)
        
        # Lire le contenu des fichiers générés pour l'inclure dans la réponse
        files_content = {}
        for file_path in project_info['files']:
            try:
                with open(file_path, 'r') as f:
                    file_name = os.path.basename(file_path)
                    files_content[file_name] = f.read()
            except Exception as e:
                socketio.emit('log', {'type': 'warning', 'message': f"Impossible de lire le fichier {file_path}: {str(e)}"})
        
        return jsonify({
            'project_name': project_name,
            'project_dir': project_info['project_dir'],
            'files': project_info['files'],
            'files_content': files_content,
            'main_file': project_info.get('main_file', ''),
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande Android: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5014)


@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent developpeurandroid"})
    
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
            log_path = os.path.join(log_dir, 'developpeurandroid.log')
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