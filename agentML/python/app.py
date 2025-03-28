import logging
import re
import time
import json
import re
import threading
import time
import os
import asyncio
from threading import Event
import numpy as np
import pandas as pd
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

# Dossier de travail pour les projets ML
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'ml.log')

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
                2. Simplifier la requête ou fournir un dataset moins volumineux
                3. Utiliser une approche plus standard pour ce type de problème ML
                
                Je vais faire de mon mieux pour poursuivre l'analyse avec les informations disponibles.
                """
                
                return fallback_response
    
    # Ce code ne devrait jamais être atteint, mais par sécurité
    socketio.emit('loading_end')
    return "Erreur inattendue lors de l'invocation du modèle"

def extract_code_blocks(text):
    """
    Extrait les blocs de code Python à partir d'un texte Markdown.
    
    Args:
        text (str): Texte contenant des blocs de code
        
    Returns:
        list: Liste des blocs de code extraits
    """
    # Pattern pour les blocs de code Python (```python ... ```)
    pattern = r'```(?:python)?\s*(.*?)\s*```'
    
    # Rechercher tous les blocs de code
    code_blocks = re.findall(pattern, text, re.DOTALL)
    
    return code_blocks

def create_notebook_file(project_name, ml_analysis):
    """
    Crée un fichier Jupyter Notebook à partir de l'analyse ML.
    
    Args:
        project_name (str): Nom du projet
        ml_analysis (str): Analyse ML contenant du code et des explications
        
    Returns:
        str: Chemin vers le fichier notebook créé
    """
    socketio.emit('log', {'type': 'info', 'message': "Création du notebook Jupyter..."})
    
    # Normaliser le nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    # Chemin du notebook
    notebook_path = os.path.join(project_dir, f"{safe_project_name}_analysis.ipynb")
    
    # Analyser le texte pour séparer les blocs de code et le texte explicatif
    sections = re.split(r'```(?:python)?\s*(.*?)\s*```', ml_analysis, flags=re.DOTALL)
    
    # Préparer les cellules du notebook
    cells = []
    
    # Cellule de titre
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": f"# Analyse Machine Learning: {project_name}\n\nCréé par l'Agent ML"
    })
    
    # Cellules d'importation standards
    cells.append({
        "cell_type": "code",
        "metadata": {},
        "source": "import numpy as np\nimport pandas as pd\nimport matplotlib.pyplot as plt\nimport seaborn as sns\nfrom sklearn.model_selection import train_test_split\nfrom sklearn.preprocessing import StandardScaler\nfrom sklearn.metrics import accuracy_score, confusion_matrix, classification_report\nimport warnings\nwarnings.filterwarnings('ignore')\n\n# Configuration pour les visualisations\nplt.style.use('ggplot')\nplt.rcParams['figure.figsize'] = (12, 8)\nsns.set(style='whitegrid')",
        "execution_count": None,
        "outputs": []
    })
    
    # Traiter les sections alternant entre texte et code
    for i, section in enumerate(sections):
        if i % 2 == 0:  # Texte explicatif
            if section.strip():
                cells.append({
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": section.strip()
                })
        else:  # Bloc de code
            cells.append({
                "cell_type": "code",
                "metadata": {},
                "source": section,
                "execution_count": None,
                "outputs": []
            })
    
    # Structure du notebook
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "codemirror_mode": {
                    "name": "ipython",
                    "version": 3
                },
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": "3.8.10"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 4
    }
    
    # Écrire le notebook dans un fichier
    with open(notebook_path, 'w') as f:
        json.dump(notebook, f, indent=2)
    
    socketio.emit('log', {'type': 'success', 'message': f"Notebook créé: {notebook_path}"})
    
    return notebook_path

def create_ml_script(project_name, ml_analysis):
    """
    Crée un script Python à partir de l'analyse ML.
    
    Args:
        project_name (str): Nom du projet
        ml_analysis (str): Analyse ML contenant du code et des explications
        
    Returns:
        str: Chemin vers le fichier script créé
    """
    socketio.emit('log', {'type': 'info', 'message': "Création du script Python..."})
    
    # Normaliser le nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    # Chemin du script
    script_path = os.path.join(project_dir, f"{safe_project_name}_model.py")
    
    # Extraire les blocs de code Python
    code_blocks = extract_code_blocks(ml_analysis)
    
    # Préparer le script avec tous les imports au début
    script_content = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
    script_content += f"""
# ML Model for {project_name}
# Generated by Agent ML

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report
import warnings
warnings.filterwarnings('ignore')

# Configuration pour les visualisations
plt.style.use('ggplot')
plt.rcParams['figure.figsize'] = (12, 8)
sns.set(style='whitegrid')

"""
    
    # Ajouter tous les blocs de code
    for i, code_block in enumerate(code_blocks):
        script_content += f"\n# Block {i+1}\n"
        script_content += code_block
        script_content += "\n"
    
    # Ajouter un main pour l'exécution directe
    script_content += """

@socketio.on('connect')
def handle_connect():
    '''Gestionnaire d\'événement de connexion client.'''
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent ml"})
    
    except Exception as e:
        logger.error(f"Erreur lors de la gestion de la connexion: {str(e)}")

@socketio.on('request_logs')
def handle_request_logs():
    '''Gestionnaire pour la demande de logs'''
    try:
        logger.info("Demande de logs reçue")
        # Envoyer un accusé de réception
        safe_emit('log', {'type': 'info', 'message': "Chargement des logs en cours..."})
        
        # Lire les dernières entrées du fichier de log pour les afficher dans l'interface
        try:
            log_path = os.path.join(log_dir, 'ml.log')
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

if __name__ == "__main__":
    logger.info("Exécution du modèle ML...")
    # Code principal d'exécution
"""
    
    # Écrire le script dans un fichier
    with open(script_path, 'w') as f:
        f.write(script_content)
    
    socketio.emit('log', {'type': 'success', 'message': f"Script créé: {script_path}"})
    
    return script_path

def create_requirements_file(project_name, ml_analysis):
    """
    Crée un fichier requirements.txt pour les dépendances du projet ML.
    
    Args:
        project_name (str): Nom du projet
        ml_analysis (str): Analyse ML contenant du code et des explications
        
    Returns:
        str: Chemin vers le fichier requirements.txt créé
    """
    socketio.emit('log', {'type': 'info', 'message': "Création du fichier requirements.txt..."})
    
    # Normaliser le nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    # Chemin du fichier requirements
    req_path = os.path.join(project_dir, "requirements.txt")
    
    # Liste des dépendances de base
    dependencies = [
        "numpy",
        "pandas",
        "matplotlib",
        "seaborn",
        "scikit-learn",
        "jupyter",
        "statsmodels"
    ]
    
    # Détecter les frameworks supplémentaires mentionnés dans l'analyse
    if "tensorflow" in ml_analysis.lower() or "keras" in ml_analysis.lower():
        dependencies.append("tensorflow")
    
    if "torch" in ml_analysis.lower() or "pytorch" in ml_analysis.lower():
        dependencies.append("torch")
        dependencies.append("torchvision")
    
    if "xgboost" in ml_analysis.lower():
        dependencies.append("xgboost")
    
    if "lightgbm" in ml_analysis.lower():
        dependencies.append("lightgbm")
    
    if "catboost" in ml_analysis.lower():
        dependencies.append("catboost")
    
    if "nltk" in ml_analysis.lower():
        dependencies.append("nltk")
    
    if "spacy" in ml_analysis.lower():
        dependencies.append("spacy")
    
    if "gensim" in ml_analysis.lower():
        dependencies.append("gensim")
    
    if "transformers" in ml_analysis.lower() or "huggingface" in ml_analysis.lower():
        dependencies.append("transformers")
    
    if "opencv" in ml_analysis.lower() or "cv2" in ml_analysis.lower():
        dependencies.append("opencv-python")
    
    # Écrire le fichier requirements.txt
    with open(req_path, 'w') as f:
        for dep in dependencies:
            f.write(f"{dep}\n")
    
    socketio.emit('log', {'type': 'success', 'message': f"Fichier requirements.txt créé: {req_path}"})
    
    return req_path

def create_readme_file(project_name, ml_analysis, files_generated):
    """
    Crée un fichier README.md pour le projet ML.
    
    Args:
        project_name (str): Nom du projet
        ml_analysis (str): Analyse ML contenant du code et des explications
        files_generated (list): Liste des fichiers générés
        
    Returns:
        str: Chemin vers le fichier README.md créé
    """
    socketio.emit('log', {'type': 'info', 'message': "Création du fichier README.md..."})
    
    # Normaliser le nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    # Chemin du fichier README
    readme_path = os.path.join(project_dir, "README.md")
    
    # Créer le contenu du README
    readme_content = f"""# {project_name}

Ce projet a été généré par l'Agent ML.

## Description

Ce projet contient une analyse de Machine Learning basée sur les spécifications demandées.

## Fichiers générés

"""
    
    for file in files_generated:
        file_name = os.path.basename(file)
        readme_content += f"- **{file_name}**: "
        
        if file_name.endswith(".ipynb"):
            readme_content += "Notebook Jupyter avec l'analyse complète\n"
        elif file_name.endswith(".py"):
            readme_content += "Script Python contenant le modèle ML\n"
        elif file_name == "requirements.txt":
            readme_content += "Liste des dépendances requises\n"
        else:
            readme_content += "Fichier supplémentaire\n"
    
    # Ajouter les instructions d'installation et d'utilisation
    readme_content += """
## Installation

Pour installer les dépendances requises, exécutez:

```bash
pip install -r requirements.txt
```

## Utilisation

1. Pour l'analyse interactive, ouvrez le notebook Jupyter:

```bash
jupyter notebook *.ipynb
```

2. Pour exécuter directement le modèle:

```bash
python *_model.py
```

## Licence

Ce projet est sous licence MIT.
"""
    
    # Écrire le README dans un fichier
    with open(readme_path, 'w') as f:
        f.write(readme_content)
    
    socketio.emit('log', {'type': 'success', 'message': f"Fichier README.md créé: {readme_path}"})
    
    return readme_path

def analyze_ml_problem(project_specs):
    """
    Analyse un problème de ML et génère une solution.
    
    Args:
        project_specs (str): Spécifications du projet ML
        
    Returns:
        str: Analyse du problème ML
    """
    socketio.emit('log', {'type': 'info', 'message': "Analyse du problème ML en cours..."})
    
    system_prompt = """
    Vous êtes un expert en Machine Learning et Data Science spécialisé dans la création de solutions complètes.
    Votre tâche est d'analyser le problème décrit et de fournir une solution détaillée avec du code Python fonctionnel.
    
    Votre réponse doit inclure:
    1. Une exploration et analyse des données avec visualisations (en supposant que les données sont disponibles)
    2. Une sélection justifiée des modèles et algorithmes appropriés
    3. Une implémentation complète avec prétraitement, entraînement et évaluation
    4. Des visualisations des résultats et métriques de performance
    5. Des recommandations pour améliorer le modèle
    
    Présentez votre analyse de façon structurée avec du texte explicatif entre des blocs de code Python exécutable.
    Utilisez les bibliothèques standards (NumPy, Pandas, Scikit-learn, Matplotlib, etc.) ainsi que des frameworks spécialisés si nécessaire.
    
    Le code doit être prêt à être exécuté dans un notebook Jupyter ou comme un script Python.
    """
    
    prompt = f"""
    Je travaille sur un projet de Machine Learning et j'ai besoin d'une solution complète.
    
    Voici les spécifications du projet:
    
    {project_specs}
    
    Veuillez me fournir une analyse détaillée avec du code Python fonctionnel qui résout ce problème.
    
    Si certaines informations sont manquantes ou si les données ne sont pas spécifiées, faites des hypothèses raisonnables
    et proposez comment les données pourraient être structurées pour ce problème.
    """
    
    # Invoquer Claude pour l'analyse ML
    analysis = invoke_claude(prompt, system_prompt, max_tokens=8000)
    
    socketio.emit('log', {'type': 'success', 'message': "Analyse ML terminée"})
    
    return analysis

def generate_ml_pipeline(project_name, project_specs):
    """
    Génère un pipeline ML complet pour le projet.
    
    Args:
        project_name (str): Nom du projet
        project_specs (str): Spécifications du projet ML
        
    Returns:
        dict: Résultat de la génération
    """
    # Normaliser le nom du projet
    safe_project_name = re.sub(r'[^\w\-\.]', '_', project_name.lower())
    project_dir = os.path.join(WORKSPACE_DIR, safe_project_name)
    
    # Créer le dossier du projet s'il n'existe pas
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
    
    socketio.emit('log', {'type': 'info', 'message': f"Génération du pipeline ML pour {project_name}..."})
    
    # Analyser le problème ML
    ml_analysis = analyze_ml_problem(project_specs)
    
    # Générer les fichiers du projet
    files_generated = []
    
    # Créer le notebook Jupyter
    notebook_path = create_notebook_file(project_name, ml_analysis)
    files_generated.append(notebook_path)
    
    # Créer le script Python
    script_path = create_ml_script(project_name, ml_analysis)
    files_generated.append(script_path)
    
    # Créer le fichier requirements.txt
    req_path = create_requirements_file(project_name, ml_analysis)
    files_generated.append(req_path)
    
    # Créer le fichier README.md
    readme_path = create_readme_file(project_name, ml_analysis, files_generated)
    files_generated.append(readme_path)
    
    # Résultats de la génération
    results = {
        "project_dir": project_dir,
        "files_generated": files_generated,
        "analysis": ml_analysis
    }
    
    socketio.emit('ml_complete', {
        'project_dir': project_dir,
        'files': files_generated
    })
    
    return results

@app.route('/ml_request', methods=['POST'])
def ml_request():
    """Endpoint pour recevoir et traiter les demandes ML directes"""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande ML"})
    
    data = request.json
    project_name = data.get('project_name', 'ML-Project')
    project_specs = data.get('specs', '')
    
    if not project_specs:
        return jsonify({'error': "Les spécifications du projet sont requises", 'status': 'error'})
    
    try:
        # Générer le pipeline ML
        results = generate_ml_pipeline(project_name, project_specs)
        
        return jsonify({
            'project_name': project_name,
            'project_dir': results['project_dir'],
            'files': results['files_generated'],
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande ML: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

@app.route('/api/ml_analysis', methods=['POST'])
def api_ml_analysis():
    """API endpoint pour les demandes d'analyse ML provenant d'autres agents"""
    data = request.json
    project_name = data.get('project_name', 'ML-Project')
    project_specs = data.get('specs', '')
    
    if not project_specs:
        return jsonify({'error': "Les spécifications du projet sont requises", 'status': 'error'})
    
    socketio.emit('log', {'type': 'info', 'message': f"Réception d'une demande d'API pour {project_name}"})
    
    try:
        # Générer le pipeline ML
        results = generate_ml_pipeline(project_name, project_specs)
        
        return jsonify({
            'project_name': project_name,
            'project_dir': results['project_dir'],
            'files': results['files_generated'],
            'status': 'success'
        })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande ML: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5007)

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