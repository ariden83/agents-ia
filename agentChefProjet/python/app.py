# Activer le monkey-patching d'eventlet AVANT d'importer quoi que ce soit d'autre
try:
    import eventlet
    eventlet.monkey_patch()
except ImportError:
    pass  # On continue sans eventlet si non disponible

import json
import os
import re
import sys
import threading
import time
import requests
import logging
from threading import Event
from dotenv import load_dotenv
from pathlib import Path

import boto3
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'chef_projet.log')

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

# Charger les variables d'environnement du fichier .env
dotenv_path = Path(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))
load_dotenv(dotenv_path=dotenv_path)

# Configuration AWS - utiliser le profil spécifié dans le .env ou utiliser les identifiants par défaut si non spécifié
aws_profile = os.getenv("AWS_PROFILE")
if aws_profile:
    try:
        boto3.setup_default_session(profile_name=aws_profile)
        logger.info(f"Session AWS initialisée avec le profil '{aws_profile}'")
    except Exception as e:
        logger.warning(f"Impossible d'utiliser le profil AWS spécifié ({aws_profile}): {str(e)}")
        logger.info("Utilisation des identifiants AWS par défaut")
else:
    logger.info("Aucun profil AWS spécifié dans .env, utilisation des identifiants par défaut")

# Configuration du modèle Claude depuis les variables d'environnement
REGION_NAME = os.getenv("REGION_NAME", "eu-west-3")
MODEL_ID = os.getenv("MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")  # Utilise la valeur du .env ou la valeur par défaut

# Configuration des URL des agents
AGENT_DEV_PYTHON_URL = "http://localhost:5001/code_request"  # Agent Développeur Python
AGENT_QA_URL = "http://localhost:5002/qa_api_request"  # Agent QAClaude
AGENT_FRONTEND_URL = "http://localhost:5003/frontend_request"  # Agent Développeur Frontend
AGENT_GO_BACKEND_URL = "http://localhost:5001/go_code_request"  # Agent Développeur Go Backend - Corrigé pour port 5001
AGENT_DEVOPS_CONFIG_URL = "http://localhost:5005/api/devops_config"  # Agent DevOps
AGENT_DEVOPS_CICD_URL = "http://localhost:5005/api/ci_cd_pipeline"  # Agent DevOps

# Alias pour la clarté du code
AGENT_DEV_URL = AGENT_GO_BACKEND_URL  # Pour la compatibilité avec interface_with_developer_agent
AGENT_PERF_URL = "http://localhost:5006/api/performance_audit"  # Agent Performance
AGENT_ML_URL = "http://localhost:5007/api/ml_analysis"  # Agent Machine Learning
AGENT_ANALYTICS_URL = "http://localhost:5008/api/analytics_monitoring"  # Agent Analytics/Monitoring
AGENT_PRODUCT_OWNER_URL = "http://localhost:5009/api/product_requirements"  # Agent Product Owner
AGENT_UX_DESIGNER_URL = "http://localhost:5010/api/ux_design"  # Agent UX Designer
AGENT_IOS_URL = "http://localhost:5013/code_request"  # Agent Développeur iOS
AGENT_ANDROID_URL = "http://localhost:5014/code_request"  # Agent Développeur Android

# Dictionnaire des agents disponibles avec leurs descriptions
AVAILABLE_AGENTS = {
    "python": {
        "name": "Développeur Python",
        "description": "Développement d'applications Python, création de scripts, traitement de données, backend web",
        "url": AGENT_DEV_PYTHON_URL
    },
    "qa": {
        "name": "QAClaude",
        "description": "Tests fonctionnels et automatisés d'applications web",
        "url": AGENT_QA_URL
    },
    "frontend": {
        "name": "Développeur Frontend",
        "description": "Développement d'interfaces utilisateur avec HTML, CSS, JavaScript, React, Vue, Angular",
        "url": AGENT_FRONTEND_URL
    },
    "go": {
        "name": "Développeur Go Backend",
        "description": "Développement de services et API backend en Go, microservices performants",
        "url": AGENT_GO_BACKEND_URL
    },
    "devops": {
        "name": "DevOps",
        "description": "Configuration Docker, Kubernetes, CI/CD, infrastructure as code",
        "url": AGENT_DEVOPS_CONFIG_URL
    },
    "performance": {
        "name": "Performance",
        "description": "Audit et optimisation des performances d'applications web",
        "url": AGENT_PERF_URL
    },
    "ml": {
        "name": "Machine Learning",
        "description": "Modèles ML, analyse prédictive, traitement du langage naturel, vision par ordinateur",
        "url": AGENT_ML_URL
    },
    "analytics": {
        "name": "Analytics & Monitoring",
        "description": "Mise en place d'outils d'analytics, dashboards, monitoring et alerting",
        "url": AGENT_ANALYTICS_URL
    },
    "product_owner": {
        "name": "Product Owner",
        "description": "Définition des exigences produit, priorisation des fonctionnalités, user stories",
        "url": AGENT_PRODUCT_OWNER_URL
    },
    "ux_designer": {
        "name": "UX Designer",
        "description": "Design d'interfaces, wireframes, prototypes, tests d'utilisabilité",
        "url": AGENT_UX_DESIGNER_URL
    },
    "ios": {
        "name": "Développeur iOS",
        "description": "Développement d'applications mobiles pour iOS (iPhone, iPad) en Swift",
        "url": AGENT_IOS_URL
    },
    "android": {
        "name": "Développeur Android",
        "description": "Développement d'applications mobiles pour Android en Kotlin ou Java",
        "url": AGENT_ANDROID_URL
    }
}

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
user_action_event = Event()

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': "Connexion établie avec l'agent Chef de Projet"})
    
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
            log_path = os.path.join(log_dir, 'chef_projet.log')
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

def wait_for_user_confirmation():
    """Met en pause le script jusqu'à confirmation de l'utilisateur."""
    user_action_event.clear()
    safe_emit('wait_for_user_action', {})
    user_action_event.wait()
    time.sleep(1)

@socketio.on('user_action_done')
def handle_user_action_done():
    """Déclenchement après confirmation de l'utilisateur."""
    user_action_event.set()

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

def invoke_claude(prompt, system_prompt=None, max_tokens=4096, temperature=0.7):
    """
    Invoque Claude via AWS Bedrock avec le prompt fourni.
    
    Args:
        prompt (str): Le prompt principal à envoyer au modèle
        system_prompt (str, optional): Instructions système pour guider le comportement du modèle
        max_tokens (int, optional): Nombre maximum de tokens pour la réponse
        temperature (float, optional): Niveau de créativité (0.0-1.0)
    
    Returns:
        dict: Dictionnaire contenant la réponse ou l'erreur
              Format: {"success": bool, "content": str, "error": str}
    """
    safe_emit('loading_start')
    safe_emit('log', {'type': 'info', 'message': "Invocation de Claude en cours..."})
    
    # Mode de test sans AWS - simuler une réponse pour permettre le test de communication
    safe_emit('log', {'type': 'warning', 'message': "Fonctionnement en mode test sans AWS"})
    safe_emit('loading_end')
    
    # Simuler une réponse pour le type de prompt
    if "analyse" in prompt.lower():
        return {
            "success": True, 
            "content": json.dumps({
                "recommended_agents": ["go"],
                "project_framework": "Go API",
                "project_complexity": "Simple"
            })
        }
    elif "plan de" in prompt.lower() or "planification" in prompt.lower():
        # Simuler une réponse pour la planification
        return {
            "success": True,
            "content": json.dumps({
                "phases": [{"phase": "Phase 1", "tasks": [{"task_name": "Mise en place", "description": "Structure du projet"}]}],
                "architecture": "Architecture REST simple",
                "components": [{"name": "API Server", "description": "Serveur HTTP simple"}],
                "implementation_phases": [{"phase": "Développement", "tasks": [{"task_name": "Endpoints", "description": "Créer les endpoints", "technical_requirements": "Utiliser net/http standard"}]}],
                "technical_considerations": ["Go standard library", "RESTful principles"]
            })
        }
    elif "test" in prompt.lower():
        # Simuler une réponse pour le plan de test
        return {
            "success": True,
            "content": json.dumps({
                "test_strategy": "Tests unitaires et d'intégration",
                "test_categories": [
                    {"category": "API Tests", "test_cases": [{"title": "Test Hello Endpoint", "description": "Vérifier que /hello renvoie le bon message"}]}
                ]
            })
        }
    else:
        # Réponse par défaut
        return {
            "success": True,
            "content": "Réponse simulée pour prompt: " + prompt[:50] + "..."
        }
    
    try:
        # Création du client Bedrock avec des logs pour le débogage
        logger.info(f"Création du client Bedrock avec region_name={REGION_NAME}")
        try:
            bedrock_client = boto3.client(
                service_name='bedrock-runtime',
                region_name=REGION_NAME
            )
            logger.info("Client Bedrock créé avec succès")
        except Exception as client_err:
            logger.error(f"Erreur lors de la création du client Bedrock: {str(client_err)}")
            raise
        
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

        safe_emit('log', {'type': 'info', 'message': f"Send prompt à Claude en cours... (system_prompt: {system_prompt})"})
        logger.info(f"Invocation du modèle avec MODEL_ID={MODEL_ID}")
        logger.info(f"Requête: {json.dumps(request_body)[:500]}...")  # Log partiel pour éviter d'afficher des prompts trop longs
        
        # Invocation du modèle avec timeout
        try:
            # Invocation du modèle
            response = bedrock_client.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps(request_body)
            )
            logger.info("Réponse brute reçue du modèle")
        except Exception as invoke_err:
            logger.error(f"Erreur lors de l'invocation du modèle: {str(invoke_err)}")
            raise
        
        # Traitement de la réponse
        response_body = json.loads(response.get('body').read())
        generated_text = response_body.get('content')[0].get('text')
        
        # Log de la réponse pour debug (en tronquant si trop longue)
        truncated_response = generated_text[:500] + "..." if len(generated_text) > 500 else generated_text
        logger.info(f"Réponse de Bedrock reçue: {truncated_response}")
        
        safe_emit('log', {'type': 'success', 'message': "Réponse de Claude reçue"})
        safe_emit('loading_end')
        
        return {"success": True, "content": generated_text, "error": None}
    
    except Exception as e:
        error_message = f"Erreur lors de l'invocation de Claude: {str(e)}"
        logger.error(f"Exception détaillée: {type(e).__name__} - {str(e)}")
        
        # Détection d'erreurs spécifiques d'AWS
        if "Unable to locate credentials" in str(e):
            error_message = f"Erreur d'identification AWS: Impossible de trouver les credentials. Vérifiez la configuration AWS dans .env. Modèle: {MODEL_ID}, Région: {REGION_NAME}, Profil AWS: {aws_profile or 'Non spécifié (utilisant credentials par défaut)'}"
            logger.error(f"Credentials AWS non trouvés. Modèle: {MODEL_ID}, Région: {REGION_NAME}, Profil AWS: {aws_profile or 'Non spécifié'}")
        elif "AccessDenied" in str(e):
            error_message = "Erreur d'accès AWS: vérifiez les permissions du profil et les clés d'API."
            logger.error("Problème d'authentification AWS détecté")
        elif "ResourceNotFoundException" in str(e):
            error_message = f"Modèle non trouvé: {MODEL_ID}. Vérifiez l'ID du modèle dans le fichier .env."
            logger.error(f"Le modèle {MODEL_ID} n'existe pas ou n'est pas accessible")
        elif "ValidationException" in str(e) and "model" in str(e).lower():
            error_message = f"Format d'ID de modèle invalide: {MODEL_ID}. Vérifiez le format dans le fichier .env."
            logger.error(f"Format d'ID de modèle invalide: {MODEL_ID}")
        elif "ExpiredTokenException" in str(e) or "InvalidSignatureException" in str(e):
            error_message = "Jetons AWS expirés. Les informations d'identification doivent être renouvelées."
            logger.error("Problème de jetons/credentials AWS")
        elif "ConnectionError" in str(e) or "ConnectTimeout" in str(e):
            error_message = "Impossible de se connecter au service AWS Bedrock. Vérifiez votre connexion réseau."
            logger.error("Problème de connexion réseau vers AWS")
        
        safe_emit('log', {'type': 'error', 'message': error_message})
        safe_emit('loading_end')
        
        # Notification au frontend pour afficher une alerte d'erreur
        safe_emit('critical_error', {
            'message': error_message,
            'title': 'Erreur critique - AWS Bedrock',
            'details': f"Détails techniques: {str(e)}"
        })
        
        return {"success": False, "content": None, "error": error_message}

def analyze_and_suggest_improvements(project_description):
    """
    Analyse la demande et suggère des améliorations potentielles.
    
    Args:
        project_description (str): Description brute du projet par l'utilisateur
    
    Returns:
        dict: Dictionnaire contenant la demande originale et les suggestions d'amélioration
    """
    safe_emit('log', {'type': 'info', 'message': "Analyse de la demande pour suggestions d'amélioration..."})
    
    # Système prompt pour guider Claude à analyser et suggérer des améliorations
    system_prompt = """
    Vous êtes un chef de projet technique expert qui analyse les demandes des utilisateurs 
    pour proposer des améliorations pertinentes. Votre objectif est d'identifier les points 
    qui pourraient être clarifiés ou enrichis afin d'obtenir des spécifications plus complètes.
    
    Format de sortie:
    ```json
    {
        "original_request": "Résumé de la demande originale",
        "analysis": "Votre analyse de la demande, avec les forces et faiblesses identifiées",
        "suggestions": [
            {
                "title": "Titre court de la suggestion 1",
                "description": "Description détaillée de la suggestion 1",
                "improved_request": "Version améliorée de la demande intégrant cette suggestion"
            },
            {
                "title": "Titre court de la suggestion 2",
                "description": "Description détaillée de la suggestion 2",
                "improved_request": "Version améliorée de la demande intégrant cette suggestion"
            },
            {
                "title": "Titre court de la suggestion 3",
                "description": "Description détaillée de la suggestion 3",
                "improved_request": "Version améliorée de la demande intégrant cette suggestion"
            }
        ],
        "comprehensive_improvement": "Version améliorée intégrant toutes les suggestions"
    }
    ```
    
    Directives:
    1. Proposez 2 à 3 suggestions distinctes et pertinentes.
    2. Chaque suggestion doit se concentrer sur un aspect différent à améliorer.
    3. Les suggestions doivent être constructives et apporter une réelle valeur ajoutée.
    4. Pour chaque suggestion, proposez une version améliorée de la demande intégrant cette suggestion spécifique.
    5. Proposez également une version complète intégrant toutes les suggestions.
    """
    
    # Construction du prompt pour analyser et suggérer des améliorations
    prompt = f"""
    Voici la demande d'un utilisateur pour un projet:
    
    {project_description}
    
    Veuillez analyser cette demande et suggérer des améliorations pertinentes qui 
    permettraient d'obtenir des spécifications plus complètes et précises.
    
    Pour chaque suggestion, proposez une version améliorée de la demande qui l'intègre.
    Proposez également une version complète qui intègre toutes vos suggestions.
    """
    
    # Invocation de Claude
    claude_response = invoke_claude(prompt, system_prompt)
    
    # Vérifier si l'appel a réussi
    if not claude_response["success"]:
        # Une erreur critique s'est produite - arrêter le traitement
        error_message = claude_response["error"]
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors de l'analyse du projet: {error_message}"})
        
        # Retourner un objet d'erreur qui indique clairement que le processus doit s'arrêter
        return {
            "error": True,
            "message": error_message,
            "original_request": project_description,
            "analysis": "Erreur lors de l'analyse - Impossible de continuer",
            "suggestions": [],
            "comprehensive_improvement": project_description
        }
    
    # Si l'appel a réussi, continuer avec le traitement normal
    response = claude_response["content"]
    
    # Extraction du JSON de la réponse
    try:
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            suggestions_json = json.loads(json_match.group(1))
            safe_emit('log', {'type': 'success', 'message': "Suggestions d'amélioration générées avec succès"})
            return suggestions_json
        else:
            # Tenter de trouver un JSON sans les backticks
            json_match = re.search(r'({.*})', response, re.DOTALL)
            if json_match:
                suggestions_json = json.loads(json_match.group(1))
                return suggestions_json
            else:
                safe_emit('log', {'type': 'warning', 'message': "Format JSON non trouvé, utilisation de la réponse brute"})
                return {
                    "original_request": project_description,
                    "analysis": "Analyse non disponible",
                    "suggestions": [],
                    "comprehensive_improvement": project_description,
                    "raw_response": response
                }
    except Exception as e:
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors du parsing JSON: {str(e)}"})
        logger.error(f"Traceback de l'erreur JSON: Type de response = {type(response)}, Début de response = {str(response)[:200]}")
        return {
            "original_request": project_description,
            "analysis": "Erreur lors de l'analyse",
            "suggestions": [],
            "comprehensive_improvement": project_description,
            "raw_response": response
        }

def determine_relevant_agents(project_description):
    """
    Analyse la description du projet et détermine quels agents sont les plus pertinents.
    
    Args:
        project_description (str): Description brute du projet par l'utilisateur
    
    Returns:
        dict: Dictionnaire contenant les agents recommandés avec leur score de pertinence
    """
    safe_emit('log', {'type': 'info', 'message': "Analyse de la demande pour déterminer les agents pertinents..."})
    
    # Créer une liste formatée des agents disponibles
    agents_list = "\n".join([f"- {key}: {value['name']} - {value['description']}" for key, value in AVAILABLE_AGENTS.items()])
    
    # Système prompt pour guider Claude à analyser la demande et recommander des agents
    system_prompt = """
    Vous êtes un chef de projet technique expert qui analyse des demandes utilisateur
    pour déterminer quels spécialistes doivent être impliqués dans un projet.
    
    Votre tâche est d'examiner la description du projet et d'identifier les agents 
    les plus pertinents pour répondre à la demande, en attribuant un score de pertinence 
    à chacun (0 à 100).
    
    Format de sortie:
    ```json
    {
        "project_analysis": "Analyse concise du projet et de ses besoins techniques",
        "recommended_agents": [
            {
                "id": "id_agent",
                "name": "Nom de l'agent",
                "relevance": 95,
                "justification": "Justification de la pertinence"
            },
            {
                "id": "id_agent_2",
                "name": "Nom de l'agent 2",
                "relevance": 80,
                "justification": "Justification de la pertinence"
            }
        ],
        "optional_agents": [
            {
                "id": "id_agent_3",
                "name": "Nom de l'agent 3",
                "relevance": 40,
                "justification": "Raison pour laquelle cet agent pourrait être utile mais n'est pas essentiel"
            }
        ]
    }
    ```
    
    Les agents "recommended_agents" sont ceux qui ont un score de pertinence ≥ 70.
    Les agents "optional_agents" sont ceux qui ont un score de pertinence entre 30 et 69.
    N'incluez pas les agents avec un score < 30.
    
    Chaque agent doit avoir une justification claire et spécifique en lien avec les besoins du projet.
    """
    
    # Construction du prompt pour déterminer les agents pertinents
    prompt = f"""
    Voici la description d'un projet par un utilisateur:
    
    {project_description}
    
    Voici la liste des agents spécialisés disponibles:
    
    {agents_list}
    
    Veuillez analyser la description du projet et déterminer quels agents devraient être 
    impliqués pour répondre efficacement à cette demande. Attribuez un score de pertinence 
    (0-100) à chaque agent que vous jugez utile et justifiez votre choix.
    """
    
    # Invocation de Claude
    claude_response = invoke_claude(prompt, system_prompt)
    
    # Vérifier si l'appel a réussi
    if not claude_response["success"]:
        # Une erreur critique s'est produite - arrêter le traitement
        error_message = claude_response["error"]
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors de la détermination des agents: {error_message}"})
        
        # Retourner un objet d'erreur qui indique clairement que le processus doit s'arrêter
        return {
            "error": True,
            "message": error_message,
            "raw_analysis": "Erreur lors de l'analyse - Impossible de continuer",
            "recommended_agents": [],
            "optional_agents": []
        }
    
    # Si l'appel a réussi, continuer avec le traitement normal
    response = claude_response["content"]
    
    # Extraction du JSON de la réponse
    try:
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            agents_json = json.loads(json_match.group(1))
            safe_emit('log', {'type': 'success', 'message': "Agents pertinents identifiés avec succès"})
            
            # Vérifier si c'est une demande valide de projet technique
            project_analysis = agents_json.get("project_analysis", "")
            recommended_agents = agents_json.get("recommended_agents", [])
            
            # Si l'analyse indique qu'il n'y a pas de projet ou si aucun agent n'est recommandé
            if (("Il n'y a pas de projet" in project_analysis or 
                 "n'est pas un projet" in project_analysis or 
                 "question générale" in project_analysis or 
                 "demande non technique" in project_analysis) and
                len(recommended_agents) == 0):
                
                # Notifier l'utilisateur que sa demande n'est pas un projet valide
                safe_emit('log', {'type': 'warning', 'message': "La demande ne semble pas décrire un projet technique valide."})
                safe_emit('critical_error', {
                    'message': "Votre demande ne semble pas décrire un projet technique. Veuillez fournir des détails spécifiques sur le projet que vous souhaitez développer.",
                    'title': 'Demande non technique détectée',
                    'details': project_analysis
                })
                
                # Retourner un objet d'erreur pour arrêter le traitement
                return {
                    "error": True,
                    "message": "Demande non technique détectée",
                    "project_analysis": project_analysis,
                    "recommended_agents": [],
                    "optional_agents": []
                }
            
            return agents_json
        else:
            # Tenter de trouver un JSON sans les backticks
            json_match = re.search(r'({.*})', response, re.DOTALL)
            if json_match:
                agents_json = json.loads(json_match.group(1))
                
                # Même vérification pour cette méthode d'extraction
                project_analysis = agents_json.get("project_analysis", "")
                recommended_agents = agents_json.get("recommended_agents", [])
                
                if (("Il n'y a pas de projet" in project_analysis or 
                     "n'est pas un projet" in project_analysis or 
                     "question générale" in project_analysis or 
                     "demande non technique" in project_analysis) and
                    len(recommended_agents) == 0):
                    
                    safe_emit('log', {'type': 'warning', 'message': "La demande ne semble pas décrire un projet technique valide."})
                    safe_emit('critical_error', {
                        'message': "Votre demande ne semble pas décrire un projet technique. Veuillez fournir des détails spécifiques sur le projet que vous souhaitez développer.",
                        'title': 'Demande non technique détectée',
                        'details': project_analysis
                    })
                    
                    return {
                        "error": True,
                        "message": "Demande non technique détectée",
                        "project_analysis": project_analysis,
                        "recommended_agents": [],
                        "optional_agents": []
                    }
                
                return agents_json
            else:
                safe_emit('log', {'type': 'warning', 'message': "Format JSON non trouvé, utilisation de la réponse brute"})
                return {"raw_analysis": response, "recommended_agents": [], "optional_agents": []}
    except Exception as e:
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors du parsing JSON: {str(e)}"})
        logger.error(f"Traceback de l'erreur JSON: Type de response = {type(response)}, Début de response = {str(response)[:200]}")
        return {"raw_analysis": response, "recommended_agents": [], "optional_agents": []}

def extract_specifications(project_description):
    """
    Extrait des spécifications détaillées à partir de la description du projet.
    
    Args:
        project_description (str): Description brute du projet par l'utilisateur
    
    Returns:
        dict: Dictionnaire contenant les spécifications structurées
    """
    safe_emit('log', {'type': 'info', 'message': "Extraction des spécifications..."})
    
    # Système prompt pour guider Claude à structurer les spécifications
    system_prompt = """
    Vous êtes un chef de projet technique expert qui analyse des demandes utilisateur
    pour les transformer en spécifications structurées. Votre tâche est d'extraire
    les éléments clés et de les organiser en sections cohérentes.
    
    Format de sortie:
    ```json
    {
        "title": "Titre du projet",
        "description": "Description générale",
        "objectives": ["Objectif 1", "Objectif 2", ...],
        "functional_requirements": ["Req 1", "Req 2", ...],
        "technical_requirements": ["Tech 1", "Tech 2", ...],
        "constraints": ["Contrainte 1", "Contrainte 2", ...],
        "required_testing": ["Test 1", "Test 2", ...]
    }
    ```
    
    Assurez-vous d'extraire toutes les informations pertinentes, et d'ajouter des
    éléments implicites qui pourraient être nécessaires pour une bonne compréhension.
    """
    
    # Construction du prompt pour extraire les spécifications
    prompt = f"""
    Voici la description d'un projet par un utilisateur:
    
    {project_description}
    
    Veuillez analyser cette description et extraire des spécifications structurées
    selon le format demandé. Si certaines informations manquent, faites des suggestions
    raisonnables basées sur le contexte.
    """
    
    # Invocation de Claude
    claude_response = invoke_claude(prompt, system_prompt)
    
    # Vérifier si l'appel a réussi
    if not claude_response["success"]:
        # Une erreur critique s'est produite - arrêter le traitement
        error_message = claude_response["error"]
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors de l'extraction des spécifications: {error_message}"})
        
        # Retourner un objet d'erreur qui indique clairement que le processus doit s'arrêter
        return {
            "error": True,
            "message": error_message,
            "raw_specs": "Erreur lors de l'extraction des spécifications - Impossible de continuer"
        }
    
    # Si l'appel a réussi, continuer avec le traitement normal
    response = claude_response["content"]
    
    # Extraction du JSON de la réponse
    try:
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            specs_json = json.loads(json_match.group(1))
            safe_emit('log', {'type': 'success', 'message': "Spécifications extraites avec succès"})
            return specs_json
        else:
            # Tenter de trouver un JSON sans les backticks
            json_match = re.search(r'({.*})', response, re.DOTALL)
            if json_match:
                specs_json = json.loads(json_match.group(1))
                return specs_json
            else:
                safe_emit('log', {'type': 'warning', 'message': "Format JSON non trouvé, utilisation de la réponse brute"})
                return {"raw_specs": response}
    except Exception as e:
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors du parsing JSON: {str(e)}"})
        logger.error(f"Traceback de l'erreur JSON: Type de response = {type(response)}, Début de response = {str(response)[:200]}")
        return {"raw_specs": response}

def create_coding_tasks(specs):
    """
    Crée des tâches de développement structurées à partir des spécifications.
    
    Args:
        specs (dict): Spécifications structurées du projet
    
    Returns:
        dict: Tâches de développement organisées
    """
    safe_emit('log', {'type': 'info', 'message': "Création des tâches de développement..."})
    
    # Système prompt pour guider Claude à créer des tâches de développement
    system_prompt = """
    Vous êtes un chef de projet technique expert qui organise le travail de développement.
    Votre tâche est de créer un plan de développement structuré avec des tâches spécifiques.
    
    Format de sortie:
    ```json
    {
        "architecture": "Description de l'architecture recommandée",
        "components": [
            {
                "name": "Nom du composant",
                "description": "Description",
                "technical_details": "Détails techniques",
                "implementation_notes": "Notes pour l'implémentation"
            }
        ],
        "implementation_phases": [
            {
                "phase": "Nom de la phase",
                "tasks": [
                    {
                        "task_name": "Nom de la tâche",
                        "description": "Description détaillée",
                        "technical_requirements": "Exigences techniques",
                        "acceptance_criteria": ["Critère 1", "Critère 2", ...],
                        "estimated_effort": "Estimation de l'effort (Faible/Moyen/Élevé)"
                    }
                ]
            }
        ],
        "technical_considerations": ["Considération 1", "Considération 2", ...]
    }
    ```
    
    Assurez-vous que les tâches sont claires, précises et directement exploitables par l'équipe de développement.
    """
    
    # Construction du prompt pour créer des tâches de développement
    prompt = f"""
    Voici les spécifications structurées d'un projet:
    
    {json.dumps(specs, indent=2)}
    
    Veuillez analyser ces spécifications et créer un plan de développement
    détaillé avec des tâches spécifiques selon le format demandé.
    """
    
    # Invocation de Claude
    claude_response = invoke_claude(prompt, system_prompt)
    
    # Vérifier si l'appel a réussi
    if not claude_response["success"]:
        # Une erreur critique s'est produite - arrêter le traitement
        error_message = claude_response["error"]
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors de la création des tâches de développement: {error_message}"})
        
        # Retourner un objet d'erreur qui indique clairement que le processus doit s'arrêter
        return {
            "error": True,
            "message": error_message,
            "raw_tasks": "Erreur lors de la création des tâches de développement - Impossible de continuer"
        }
    
    # Si l'appel a réussi, continuer avec le traitement normal
    response = claude_response["content"]
    
    # Extraction du JSON de la réponse
    try:
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            tasks_json = json.loads(json_match.group(1))
            safe_emit('log', {'type': 'success', 'message': "Tâches de développement créées avec succès"})
            return tasks_json
        else:
            # Tenter de trouver un JSON sans les backticks
            json_match = re.search(r'({.*})', response, re.DOTALL)
            if json_match:
                tasks_json = json.loads(json_match.group(1))
                return tasks_json
            else:
                safe_emit('log', {'type': 'warning', 'message': "Format JSON non trouvé, utilisation de la réponse brute"})
                return {"raw_tasks": response}
    except Exception as e:
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors du parsing JSON: {str(e)}"})
        logger.error(f"Traceback de l'erreur JSON: Type de response = {type(response)}, Début de response = {str(response)[:200]}")
        return {"raw_tasks": response}

def create_testing_plan(specs, coding_tasks):
    """
    Crée un plan de test à partir des spécifications et des tâches de développement.
    
    Args:
        specs (dict): Spécifications structurées du projet
        coding_tasks (dict): Tâches de développement organisées
    
    Returns:
        dict: Plan de test détaillé
    """
    safe_emit('log', {'type': 'info', 'message': "Création du plan de test..."})
    
    # Système prompt pour guider Claude à créer un plan de test
    system_prompt = """
    Vous êtes un expert en assurance qualité logicielle. Votre tâche est de créer
    un plan de test complet à partir des spécifications et des tâches de développement.
    
    Format de sortie:
    ```json
    {
        "test_strategy": "Description de la stratégie de test",
        "test_environments": ["Env 1", "Env 2", ...],
        "test_categories": [
            {
                "category": "Nom de la catégorie",
                "description": "Description",
                "test_cases": [
                    {
                        "id": "TC-001",
                        "title": "Titre du cas de test",
                        "description": "Description détaillée",
                        "preconditions": ["Précondition 1", "Précondition 2", ...],
                        "steps": ["Étape 1", "Étape 2", ...],
                        "expected_results": ["Résultat 1", "Résultat 2", ...],
                        "priority": "Haute/Moyenne/Basse",
                        "feature_coverage": "Fonctionnalité couverte"
                    }
                ]
            }
        ],
        "automation_recommendations": ["Recommandation 1", "Recommandation 2", ...]
    }
    ```
    
    Assurez-vous que le plan de test couvre tous les aspects fonctionnels et non-fonctionnels
    importants du projet.
    """
    
    # Construction du prompt pour créer un plan de test
    prompt = f"""
    Voici les spécifications d'un projet:
    
    {json.dumps(specs, indent=2)}
    
    Et voici les tâches de développement prévues:
    
    {json.dumps(coding_tasks, indent=2)}
    
    Veuillez créer un plan de test complet selon le format demandé.
    """
    
    # Invocation de Claude
    claude_response = invoke_claude(prompt, system_prompt)
    
    # Vérifier si l'appel a réussi
    if not claude_response["success"]:
        # Une erreur critique s'est produite - arrêter le traitement
        error_message = claude_response["error"]
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors de la création du plan de test: {error_message}"})
        
        # Retourner un objet d'erreur qui indique clairement que le processus doit s'arrêter
        return {
            "error": True,
            "message": error_message,
            "raw_test_plan": "Erreur lors de la création du plan de test - Impossible de continuer"
        }
    
    # Si l'appel a réussi, continuer avec le traitement normal
    response = claude_response["content"]
    
    # Extraction du JSON de la réponse
    try:
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            test_plan_json = json.loads(json_match.group(1))
            safe_emit('log', {'type': 'success', 'message': "Plan de test créé avec succès"})
            return test_plan_json
        else:
            # Tenter de trouver un JSON sans les backticks
            json_match = re.search(r'({.*})', response, re.DOTALL)
            if json_match:
                test_plan_json = json.loads(json_match.group(1))
                return test_plan_json
            else:
                safe_emit('log', {'type': 'warning', 'message': "Format JSON non trouvé, utilisation de la réponse brute"})
                return {"raw_test_plan": response}
    except Exception as e:
        safe_emit('log', {'type': 'error', 'message': f"Erreur lors du parsing JSON: {str(e)}"})
        logger.error(f"Traceback de l'erreur JSON: Type de response = {type(response)}, Début de response = {str(response)[:200]}")
        return {"raw_test_plan": response}

def interface_with_developer_agent(coding_tasks):
    """
    Envoie des tâches de développement à l'agent développeur Go Backend.
    
    Args:
        coding_tasks (dict): Tâches de développement organisées
    
    Returns:
        dict: Réponse de l'agent développeur Go Backend
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent développeur Go Backend..."})
    
    # Préparation des données à envoyer à l'agent développeur Go Backend
    specs = ""
    requirements = ""
    
    # Extraction des spécifications
    if "architecture" in coding_tasks:
        specs += f"# Architecture\n{coding_tasks['architecture']}\n\n"
    
    if "components" in coding_tasks:
        specs += "# Composants\n"
        for component in coding_tasks['components']:
            specs += f"## {component['name']}\n"
            specs += f"{component['description']}\n\n"
    
    if "implementation_phases" in coding_tasks:
        specs += "# Phases d'implémentation\n"
        for phase in coding_tasks['implementation_phases']:
            specs += f"## {phase['phase']}\n"
            for task in phase['tasks']:
                specs += f"### {task['task_name']}\n"
                specs += f"{task['description']}\n\n"
    
    # Extraction des exigences techniques
    if "technical_considerations" in coding_tasks:
        requirements += "# Considérations techniques\n"
        for consideration in coding_tasks['technical_considerations']:
            requirements += f"- {consideration}\n"
    
    if "implementation_phases" in coding_tasks:
        requirements += "\n# Exigences techniques par tâche\n"
        for phase in coding_tasks['implementation_phases']:
            for task in phase['tasks']:
                if 'technical_requirements' in task:
                    requirements += f"## {task['task_name']}\n"
                    requirements += f"{task['technical_requirements']}\n\n"
    
    try:
        # Générer un nom de projet par défaut
        project_name = "go-project"  # Le nom de projet est maintenant requis pour l'agent Go Backend
        
        # Envoi de la requête à l'agent développeur Go Backend
        dev_response = requests.post(
            AGENT_DEV_URL,
            json={"project_name": project_name, "specs": specs, "requirements": requirements},
            timeout=300  # Délai augmenté car la génération de code Go peut prendre plus de temps
        )
        
        # Traitement de la réponse
        if dev_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent développeur Go Backend"})
            return dev_response.json()
        else:
            error_message = f"Erreur de l'agent développeur Go Backend: {dev_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent développeur Go Backend: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_qa_agent(test_plan, url):
    """
    Envoie un plan de test à l'agent QAClaude.
    
    Args:
        test_plan (dict): Plan de test détaillé
        url (str): URL de l'application à tester
    
    Returns:
        dict: Réponse de l'agent QAClaude
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent QAClaude..."})
    
    # Préparation de la demande de test formatée pour l'agent QAClaude
    test_request = ""
    
    if "test_strategy" in test_plan:
        test_request += f"Stratégie de test: {test_plan['test_strategy']}\n\n"
    
    if "test_categories" in test_plan:
        test_request += "Cas de tests à exécuter:\n"
        for category in test_plan['test_categories']:
            test_request += f"Catégorie: {category['category']}\n"
            for test_case in category['test_cases']:
                test_request += f"- {test_case['title']}: {test_case['description']}\n"
                if 'steps' in test_case:
                    test_request += "  Étapes:\n"
                    for step in test_case['steps']:
                        test_request += f"  * {step}\n"
                test_request += "\n"
    
    try:
        # Envoi de la requête à l'agent QAClaude
        qa_response = requests.post(
            AGENT_QA_URL,
            json={"url": url, "input": test_request},
            timeout=300  # Délai augmenté car QAClaude peut prendre plus de temps pour les tests
        )
        
        # Traitement de la réponse
        if qa_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent QAClaude"})
            return qa_response.json()
        else:
            error_message = f"Erreur de l'agent QAClaude: {qa_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent QAClaude: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_performance_agent(url, audit_type='full'):
    """
    Envoie une demande d'audit de performance à l'agent Performance.
    
    Args:
        url (str): URL de l'application à auditer
        audit_type (str): Type d'audit ('full', 'basic', 'pagespeed')
    
    Returns:
        dict: Réponse de l'agent Performance avec les résultats de l'audit
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent Performance..."})
    
    try:
        # Envoi de la requête à l'agent Performance
        perf_response = requests.post(
            AGENT_PERF_URL,
            json={"url": url, "audit_type": audit_type},
            timeout=300  # Timeout plus long car l'audit complet peut prendre du temps
        )
        
        # Traitement de la réponse
        if perf_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent Performance"})
            return perf_response.json()
        else:
            error_message = f"Erreur de l'agent Performance: {perf_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent Performance: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_devops_agent(project_name, specifications, config_type='complete'):
    """
    Envoie des spécifications à l'agent DevOps pour générer des configurations.
    
    Args:
        project_name (str): Nom du projet
        specifications (dict/str): Spécifications du projet
        config_type (str): Type de configuration ('complete', 'docker', 'ci_cd', 'kubernetes', 'iac', 'monitoring')
    
    Returns:
        dict: Réponse de l'agent DevOps avec les configurations générées
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent DevOps pour les configurations..."})
    
    # Extraire les spécifications sous forme de texte
    if isinstance(specifications, dict):
        specs_text = json.dumps(specifications, indent=2)
    else:
        specs_text = str(specifications)
    
    try:
        # Envoi de la requête à l'agent DevOps
        devops_response = requests.post(
            AGENT_DEVOPS_CONFIG_URL,
            json={
                "project_name": project_name,
                "specs": specs_text,
                "config_type": config_type
            },
            timeout=300  # Timeout plus long car la génération peut prendre du temps
        )
        
        # Traitement de la réponse
        if devops_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent DevOps"})
            return devops_response.json()
        else:
            error_message = f"Erreur de l'agent DevOps: {devops_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent DevOps: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def manage_ci_cd_pipeline(project_name, action='status', environment='dev'):
    """
    Interagit avec l'agent DevOps pour gérer les pipelines CI/CD.
    
    Args:
        project_name (str): Nom du projet
        action (str): Action à effectuer ('status', 'run', 'deploy', 'rollback')
        environment (str): Environnement cible ('dev', 'staging', 'prod')
    
    Returns:
        dict: Réponse de l'agent DevOps avec les informations sur l'action demandée
    """
    safe_emit('log', {'type': 'info', 'message': f"Communication avec l'agent DevOps pour {action} du pipeline CI/CD..."})
    
    try:
        # Envoi de la requête à l'agent DevOps
        cicd_response = requests.post(
            AGENT_DEVOPS_CICD_URL,
            json={
                "project_name": project_name,
                "action": action,
                "environment": environment
            },
            timeout=60
        )
        
        # Traitement de la réponse
        if cicd_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': f"Réponse reçue de l'agent DevOps pour l'action {action}"})
            return cicd_response.json()
        else:
            error_message = f"Erreur de l'agent DevOps CI/CD: {cicd_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent DevOps CI/CD: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_ml_agent(project_name, specifications):
    """
    Envoie des spécifications à l'agent Machine Learning pour générer des solutions ML.
    
    Args:
        project_name (str): Nom du projet
        specifications (dict/str): Spécifications du projet
    
    Returns:
        dict: Réponse de l'agent ML avec les solutions générées
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent Machine Learning..."})
    
    # Extraire les spécifications sous forme de texte
    if isinstance(specifications, dict):
        specs_text = json.dumps(specifications, indent=2)
    else:
        specs_text = str(specifications)
    
    try:
        # Envoi de la requête à l'agent ML
        ml_response = requests.post(
            AGENT_ML_URL,
            json={
                "project_name": project_name,
                "specs": specs_text
            },
            timeout=300  # Timeout plus long car la génération ML peut prendre du temps
        )
        
        # Traitement de la réponse
        if ml_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent Machine Learning"})
            return ml_response.json()
        else:
            error_message = f"Erreur de l'agent Machine Learning: {ml_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent Machine Learning: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_python_agent(project_name, specifications, requirements=None):
    """
    Envoie des spécifications à l'agent Développeur Python pour générer des solutions Python.
    
    Args:
        project_name (str): Nom du projet
        specifications (dict/str): Spécifications du projet
        requirements (str, optional): Exigences techniques spécifiques
    
    Returns:
        dict: Réponse de l'agent Développeur Python avec les solutions générées
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent Développeur Python..."})
    
    # Extraire les spécifications sous forme de texte
    if isinstance(specifications, dict):
        specs_text = json.dumps(specifications, indent=2)
    else:
        specs_text = str(specifications)
    
    # Construire le corps de la requête
    request_body = {
        "project_name": project_name,
        "specs": specs_text
    }
    
    # Ajouter les exigences techniques si fournies
    if requirements:
        request_body["requirements"] = requirements
    
    try:
        # Envoi de la requête à l'agent Python
        python_response = requests.post(
            AGENT_DEV_PYTHON_URL,
            json=request_body,
            timeout=300  # Timeout plus long car la génération de code peut prendre du temps
        )
        
        # Traitement de la réponse
        if python_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent Développeur Python"})
            return python_response.json()
        else:
            error_message = f"Erreur de l'agent Développeur Python: {python_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent Développeur Python: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_analytics_monitoring_agent(project_name, specifications, stack_info=None):
    """
    Envoie des spécifications à l'agent Analytics & Monitoring pour générer des configurations.
    
    Args:
        project_name (str): Nom du projet
        specifications (dict/str): Spécifications du projet
        stack_info (str, optional): Informations sur la stack technique
    
    Returns:
        dict: Réponse de l'agent Analytics & Monitoring avec les configurations générées
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent Analytics & Monitoring..."})
    
    # Extraire les spécifications sous forme de texte
    if isinstance(specifications, dict):
        specs_text = json.dumps(specifications, indent=2)
    else:
        specs_text = str(specifications)
    
    # Construire le corps de la requête
    request_body = {
        "project_name": project_name,
        "specs": specs_text
    }
    
    # Ajouter les informations de stack si fournies
    if stack_info:
        request_body["stack_info"] = stack_info
    
    try:
        # Envoi de la requête à l'agent Analytics & Monitoring
        analytics_response = requests.post(
            AGENT_ANALYTICS_URL,
            json=request_body,
            timeout=300  # Timeout plus long car la génération de configurations peut prendre du temps
        )
        
        # Traitement de la réponse
        if analytics_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent Analytics & Monitoring"})
            return analytics_response.json()
        else:
            error_message = f"Erreur de l'agent Analytics & Monitoring: {analytics_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent Analytics & Monitoring: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_frontend_agent(specifications, open_cursor=False):
    """
    Envoie des spécifications à l'agent développeur frontend.
    
    Args:
        specifications (dict): Spécifications structurées du projet
        open_cursor (bool): Indique si Cursor doit être ouvert après la génération du code
    
    Returns:
        dict: Réponse de l'agent frontend
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent développeur frontend..."})
    
    try:
        # Envoi de la requête à l'agent frontend
        frontend_response = requests.post(
            AGENT_FRONTEND_URL,
            json={"specs": specifications, "open_cursor": open_cursor},
            timeout=300  # Timeout plus long car la génération de code frontend peut prendre du temps
        )
        
        # Traitement de la réponse
        if frontend_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent développeur frontend"})
            return frontend_response.json()
        else:
            error_message = f"Erreur de l'agent développeur frontend: {frontend_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent développeur frontend: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def test_interface_with_go_backend(project_name, specifications):
    """
    Version simplifiée pour tester la communication avec l'agent Go.
    Envoie une requête basique à l'agent développeur Go backend.
    
    Args:
        project_name (str): Nom du projet Go
        specifications (str): Spécifications du projet en texte simple
    
    Returns:
        dict: Réponse de l'agent Go backend
    """
    safe_emit('log', {'type': 'info', 'message': "Test de communication avec l'agent développeur Go backend..."})
    
    try:
        # Simplifier au maximum pour éviter les erreurs
        response = requests.post(
            AGENT_GO_BACKEND_URL,
            json={
                "project_name": str(project_name),
                "specs": str(specifications),
                "requirements": "API REST simple en Go"
            },
            timeout=30
        )
        
        if response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent développeur Go backend"})
            return response.json()
        else:
            error_message = f"Erreur de l'agent développeur Go backend: {response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message, "status_code": response.status_code}
    
    except Exception as e:
        error_message = f"Erreur lors de la communication avec l'agent développeur Go backend: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_go_backend_agent(project_name, specifications, requirements):
    """
    IMPORTANT: Cette fonction est maintenue pour la compatibilité, mais utilise maintenant le même agent
    que interface_with_developer_agent. Les deux fonctions appellent le même endpoint de l'agent développeur Go backend.
    
    Envoie des spécifications à l'agent développeur Go backend.
    
    Args:
        project_name (str): Nom du projet Go
        specifications (str): Spécifications du projet
        requirements (str): Exigences techniques
    
    Returns:
        dict: Réponse de l'agent Go backend
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent développeur Go backend..."})
    
    try:
        # Extraction des spécifications sous forme de texte
        specs_text = ""
        if isinstance(specifications, dict):
            for key, value in specifications.items():
                if key != 'raw_specs':  # Éviter les doublons avec raw_specs
                    if isinstance(value, list):
                        specs_text += f"## {key}:\n"
                        for item in value:
                            specs_text += f"- {item}\n"
                        specs_text += "\n"
                    else:
                        specs_text += f"## {key}:\n{value}\n\n"
        else:
            specs_text = str(specifications)
        
        # Envoi de la requête à l'agent Go backend
        go_response = requests.post(
            AGENT_GO_BACKEND_URL,
            json={
                "project_name": project_name,
                "specs": specs_text,
                "requirements": requirements
            },
            timeout=300  # Timeout plus long car la génération de code peut prendre du temps
        )
        
        # Traitement de la réponse
        if go_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent développeur Go backend"})
            return go_response.json()
        else:
            error_message = f"Erreur de l'agent développeur Go backend: {go_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent développeur Go backend: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_product_owner_agent(project_name, specifications):
    """
    Envoie des spécifications à l'agent Product Owner pour affiner les exigences du produit.
    
    Args:
        project_name (str): Nom du projet
        specifications (dict/str): Spécifications initiales du projet
    
    Returns:
        dict: Réponse de l'agent Product Owner avec les exigences affinées
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent Product Owner..."})
    
    # Extraire les spécifications sous forme de texte
    if isinstance(specifications, dict):
        specs_text = json.dumps(specifications, indent=2)
    else:
        specs_text = str(specifications)
    
    try:
        # Envoi de la requête à l'agent Product Owner
        po_response = requests.post(
            AGENT_PRODUCT_OWNER_URL,
            json={
                "project_name": project_name,
                "specs": specs_text
            },
            timeout=300  # Timeout plus long car l'analyse peut prendre du temps
        )
        
        # Traitement de la réponse
        if po_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent Product Owner"})
            return po_response.json()
        else:
            error_message = f"Erreur de l'agent Product Owner: {po_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent Product Owner: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_ux_designer_agent(project_name, specifications, user_personas=None):
    """
    Envoie des spécifications à l'agent UX Designer pour générer des maquettes et wireframes.
    
    Args:
        project_name (str): Nom du projet
        specifications (dict/str): Spécifications du projet
        user_personas (str, optional): Informations sur les personas utilisateurs
    
    Returns:
        dict: Réponse de l'agent UX Designer avec les designs générés
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent UX Designer..."})
    
    # Extraire les spécifications sous forme de texte
    if isinstance(specifications, dict):
        specs_text = json.dumps(specifications, indent=2)
    else:
        specs_text = str(specifications)
    
    # Construire le corps de la requête
    request_body = {
        "project_name": project_name,
        "specs": specs_text
    }
    
    # Ajouter les informations sur les personas si fournies
    if user_personas:
        request_body["user_personas"] = user_personas
    
    try:
        # Envoi de la requête à l'agent UX Designer
        ux_response = requests.post(
            AGENT_UX_DESIGNER_URL,
            json=request_body,
            timeout=300  # Timeout plus long car la génération de designs peut prendre du temps
        )
        
        # Traitement de la réponse
        if ux_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent UX Designer"})
            return ux_response.json()
        else:
            error_message = f"Erreur de l'agent UX Designer: {ux_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent UX Designer: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_ios_agent(project_name, specifications, requirements=None):
    """
    Envoie des spécifications à l'agent Développeur iOS pour générer des solutions Swift.
    
    Args:
        project_name (str): Nom du projet
        specifications (dict/str): Spécifications du projet
        requirements (str, optional): Exigences techniques spécifiques
    
    Returns:
        dict: Réponse de l'agent Développeur iOS avec les solutions générées
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent Développeur iOS..."})
    
    # Extraire les spécifications sous forme de texte
    if isinstance(specifications, dict):
        specs_text = json.dumps(specifications, indent=2)
    else:
        specs_text = str(specifications)
    
    # Construire le corps de la requête
    request_body = {
        "project_name": project_name,
        "specs": specs_text
    }
    
    # Ajouter les exigences techniques si fournies
    if requirements:
        request_body["requirements"] = requirements
    
    try:
        # Envoi de la requête à l'agent iOS
        ios_response = requests.post(
            AGENT_IOS_URL,
            json=request_body,
            timeout=300  # Timeout plus long car la génération de code peut prendre du temps
        )
        
        # Traitement de la réponse
        if ios_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent Développeur iOS"})
            return ios_response.json()
        else:
            error_message = f"Erreur de l'agent Développeur iOS: {ios_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent Développeur iOS: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

def interface_with_android_agent(project_name, specifications, requirements=None):
    """
    Envoie des spécifications à l'agent Développeur Android pour générer des solutions Kotlin/Java.
    
    Args:
        project_name (str): Nom du projet
        specifications (dict/str): Spécifications du projet
        requirements (str, optional): Exigences techniques spécifiques
    
    Returns:
        dict: Réponse de l'agent Développeur Android avec les solutions générées
    """
    safe_emit('log', {'type': 'info', 'message': "Communication avec l'agent Développeur Android..."})
    
    # Extraire les spécifications sous forme de texte
    if isinstance(specifications, dict):
        specs_text = json.dumps(specifications, indent=2)
    else:
        specs_text = str(specifications)
    
    # Construire le corps de la requête
    request_body = {
        "project_name": project_name,
        "specs": specs_text
    }
    
    # Ajouter les exigences techniques si fournies
    if requirements:
        request_body["requirements"] = requirements
    
    try:
        # Envoi de la requête à l'agent Android
        android_response = requests.post(
            AGENT_ANDROID_URL,
            json=request_body,
            timeout=300  # Timeout plus long car la génération de code peut prendre du temps
        )
        
        # Traitement de la réponse
        if android_response.status_code == 200:
            safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent Développeur Android"})
            return android_response.json()
        else:
            error_message = f"Erreur de l'agent Développeur Android: {android_response.status_code}"
            safe_emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la communication avec l'agent Développeur Android: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

@app.route('/analyze_request', methods=['POST'])
def analyze_request():
    """Endpoint pour analyser une demande et suggérer des améliorations"""
    safe_emit('log', {'type': 'info', 'message': "Analyse de la demande initiale..."})
    
    data = request.json
    project_description = data.get('description', '')
    
    if not project_description:
        return jsonify({'error': "Une description du projet est requise", 'status': 'error'})
        
    try:
        # Analyse de la demande et suggestions d'amélioration
        suggestions = analyze_and_suggest_improvements(project_description)
        safe_emit('suggestions_update', {'suggestions': suggestions})
        
        return jsonify({
            'status': 'success',
            'suggestions': suggestions
        })
    
    except Exception as e:
        error_message = f"Erreur lors de l'analyse de la demande: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

@app.route('/project_request', methods=['POST'])
def project_request():
    """Endpoint pour recevoir et traiter les demandes de projet"""
    safe_emit('log', {'type': 'info', 'message': "Traitement de la demande de projet"})
    
    # Capturer l'exception au niveau le plus élevé pour garantir une réponse
    try:
        data = request.json or {}  # Éviter None si request.json est None
        project_description = data.get('description', '')
        app_url = data.get('app_url', '')
        project_name = data.get('project_name', 'my-project')
        project_type = data.get('type', '')
        
        # Log des données reçues
        safe_emit('log', {'type': 'info', 'message': f"Données de la requête reçues: project_name={project_name}, type={project_type}"})
        
        # Pour les projets de type Go, utiliser un flux simplifié
        if project_type == 'go':
            safe_emit('log', {'type': 'info', 'message': "Projet Go détecté, traitement simplifié"})
            
            # Préparer les données pour l'agent Go
            go_specs = project_description
            go_requirements = "Utiliser la bibliothèque standard Go pour créer une API REST simple"
            
            # Appel direct à l'agent Go
            safe_emit('log', {'type': 'info', 'message': f"Envoi de la demande à l'agent Go sur {AGENT_GO_BACKEND_URL}"})
            
            try:
                # Utiliser requests directement pour éviter les couches intermédiaires
                response = requests.post(
                    AGENT_GO_BACKEND_URL,
                    json={
                        "project_name": project_name,
                        "specs": go_specs,
                        "requirements": go_requirements
                    },
                    timeout=60
                )
                
                if response.status_code == 200:
                    safe_emit('log', {'type': 'success', 'message': "Réponse reçue de l'agent Go"})
                    go_response = response.json()
                    
                    return jsonify({
                        "success": True,
                        "message": "Projet Go généré avec succès",
                        "dev_response": go_response
                    })
                else:
                    error_msg = f"Erreur HTTP {response.status_code} de l'agent Go"
                    safe_emit('log', {'type': 'error', 'message': error_msg})
                    return jsonify({
                        "success": False,
                        "error": error_msg,
                        "status_code": response.status_code
                    })
            except Exception as e:
                error_msg = f"Erreur de communication avec l'agent Go: {str(e)}"
                safe_emit('log', {'type': 'error', 'message': error_msg})
                return jsonify({
                    "success": False,
                    "error": error_msg
                })
        
        # Pour les autres types de projets, continuer avec le flux normal
        # Vérifier si on utilise une suggestion améliorée
        selected_suggestion = data.get('selected_suggestion', None)
        if selected_suggestion:
            # Vérifier que selected_suggestion est bien un dictionnaire
            if isinstance(selected_suggestion, dict):
                safe_emit('log', {'type': 'info', 'message': f"Utilisation de la suggestion améliorée: {selected_suggestion.get('title', 'Sans titre')}"})
                project_description = selected_suggestion.get('improved_request', project_description)
            else:
                # Si c'est une chaîne, la traiter différemment ou logger l'erreur
                safe_emit('log', {'type': 'warning', 'message': "Format de suggestion invalide, utilisation de la description originale"})
        
        # Si ce n'est pas un test Go, continuer avec le flux normal
        safe_emit('log', {'type': 'info', 'message': "Appel de determine_relevant_agents..."})
        
        # En mode de test ou de développement, simuler la réponse pour éviter les erreurs
        agents_analysis = {
            "recommended_agents": ["python", "frontend"],
            "project_framework": "Application web",
            "project_complexity": "Moyenne"
        }
        
        # Vérifier si une erreur s'est produite ou si ce n'est pas un projet technique
        if agents_analysis.get('error', False):
            error_message = agents_analysis.get('message', 'Erreur non spécifiée')
            project_analysis = agents_analysis.get('project_analysis', 'Analyse non disponible')
            
            safe_emit('log', {'type': 'warning', 'message': f"Traitement arrêté: {error_message}"})
            
            # Si ce n'est pas déjà fait, envoyer une notification critique à l'interface utilisateur
            if "Demande non technique détectée" in error_message:
                # Notification déjà envoyée par determine_relevant_agents()
                pass
            else:
                safe_emit('critical_error', {
                    'message': f"Le traitement a été interrompu: {error_message}",
                    'title': 'Traitement arrêté',
                    'details': project_analysis
                })
            
            return jsonify({"success": False, "message": error_message})
        
        safe_emit('agents_analysis_update', {'agents_analysis': agents_analysis})
        
        # Créer une liste d'IDs des agents recommandés
        recommended_agent_ids = [agent['id'] for agent in agents_analysis.get('recommended_agents', [])]
        optional_agent_ids = [agent['id'] for agent in agents_analysis.get('optional_agents', [])]
        
        # Phase 1: Extraction des spécifications
        specifications = extract_specifications(project_description)
        safe_emit('specifications_update', {'specifications': specifications})
        
        # Phase 2: Interface avec l'agent Product Owner (si recommandé ou demandé explicitement)
        product_owner_response = None
        if data.get('launch_product_owner', False) or 'product_owner' in recommended_agent_ids:
            product_owner_response = interface_with_product_owner_agent(project_name, specifications)
            safe_emit('product_owner_response_update', {'product_owner_response': product_owner_response})
            
            # Mise à jour des spécifications si des améliorations sont proposées
            if product_owner_response and 'refined_specs' in product_owner_response:
                specifications = product_owner_response['refined_specs']
                safe_emit('specifications_update', {'specifications': specifications})
        
        # Phase 3: Interface avec l'agent UX Designer (si recommandé ou demandé explicitement)
        ux_designer_response = None
        if data.get('launch_ux_designer', False) or 'ux_designer' in recommended_agent_ids:
            # Extraire les informations utilisateurs si disponibles
            user_personas = None
            if "user_requirements" in specifications:
                user_personas = specifications["user_requirements"]
            
            ux_designer_response = interface_with_ux_designer_agent(project_name, specifications, user_personas)
            safe_emit('ux_designer_response_update', {'ux_designer_response': ux_designer_response})
        
        # Phase 4: Création des tâches de développement
        coding_tasks = create_coding_tasks(specifications)
        safe_emit('tasks_update', {'tasks': coding_tasks})
        
        # Phase 5: Création du plan de test
        test_plan = create_testing_plan(specifications, coding_tasks)
        safe_emit('test_plan_update', {'test_plan': test_plan})
        
        # Extraire les exigences techniques communes à partir des tâches de développement
        tech_requirements = ""
        if "technical_considerations" in coding_tasks:
            tech_requirements += "# Considérations techniques\n"
            for consideration in coding_tasks['technical_considerations']:
                tech_requirements += f"- {consideration}\n"
        
        # Phase 6: Interface avec les agents de développement selon les recommandations
        
        # Agent développeur Go Backend
        dev_response = None
        if data.get('launch_dev', False) or 'go' in recommended_agent_ids:
            dev_response = interface_with_developer_agent(coding_tasks)
            safe_emit('dev_response_update', {'dev_response': dev_response})
        
        # Agent développeur Go backend (ancienne méthode)
        go_response = None
        if data.get('launch_go', False) or ('go' in recommended_agent_ids and 'go' not in data.keys()):
            go_response = interface_with_go_backend_agent(
                project_name, 
                specifications, 
                tech_requirements
            )
            safe_emit('go_response_update', {'go_response': go_response})
        
        # Agent développeur frontend
        frontend_response = None
        if data.get('launch_frontend', False) or 'frontend' in recommended_agent_ids:
            frontend_response = interface_with_frontend_agent(specifications, data.get('open_cursor', False))
            safe_emit('frontend_response_update', {'frontend_response': frontend_response})
        
        # Agent Développeur Python
        python_response = None
        if data.get('launch_python', False) or 'python' in recommended_agent_ids:
            python_response = interface_with_python_agent(
                project_name, 
                specifications, 
                tech_requirements
            )
            safe_emit('python_response_update', {'python_response': python_response})
        
        # Agent Développeur iOS
        ios_response = None
        if data.get('launch_ios', False) or 'ios' in recommended_agent_ids:
            ios_response = interface_with_ios_agent(
                project_name, 
                specifications, 
                tech_requirements
            )
            safe_emit('ios_response_update', {'ios_response': ios_response})
        
        # Agent Développeur Android
        android_response = None
        if data.get('launch_android', False) or 'android' in recommended_agent_ids:
            android_response = interface_with_android_agent(
                project_name, 
                specifications, 
                tech_requirements
            )
            safe_emit('android_response_update', {'android_response': android_response})
        
        # Phase 7: Agents de test et qualité
        
        # Agent QAClaude
        qa_response = None
        if (data.get('launch_qa', False) or 'qa' in recommended_agent_ids) and app_url:
            qa_response = interface_with_qa_agent(test_plan, app_url)
            safe_emit('qa_response_update', {'qa_response': qa_response})
        
        # Agent Performance
        performance_response = None
        if (data.get('launch_performance', False) or 'performance' in recommended_agent_ids) and app_url:
            audit_type = data.get('audit_type', 'full')
            performance_response = interface_with_performance_agent(app_url, audit_type)
            safe_emit('performance_response_update', {'performance_response': performance_response})
        
        # Phase 8: Agents d'infrastructure et opérations
        
        # Agent DevOps pour les configurations
        devops_response = None
        if data.get('launch_devops', False) or 'devops' in recommended_agent_ids:
            config_type = data.get('devops_config_type', 'complete')
            devops_response = interface_with_devops_agent(project_name, specifications, config_type)
            safe_emit('devops_response_update', {'devops_response': devops_response})
        
        # Agent DevOps pour le CI/CD
        cicd_response = None
        if data.get('launch_cicd', False) or ('devops' in recommended_agent_ids and not devops_response):
            cicd_action = data.get('cicd_action', 'status')
            cicd_environment = data.get('cicd_environment', 'dev')
            cicd_response = manage_ci_cd_pipeline(project_name, cicd_action, cicd_environment)
            safe_emit('cicd_response_update', {'cicd_response': cicd_response})
        
        # Phase 9: Agents spécialisés
        
        # Agent Machine Learning
        ml_response = None
        if data.get('launch_ml', False) or 'ml' in recommended_agent_ids:
            ml_response = interface_with_ml_agent(project_name, specifications)
            safe_emit('ml_response_update', {'ml_response': ml_response})
        
        # Agent Analytics & Monitoring
        analytics_response = None
        if data.get('launch_analytics', False) or 'analytics' in recommended_agent_ids:
            # Extraire les informations de stack technique
            stack_info = ""
            if "technical_considerations" in coding_tasks:
                stack_info += "# Stack technique\n"
                for consideration in coding_tasks['technical_considerations']:
                    if any(tech in consideration.lower() for tech in 
                           ["frontend", "backend", "database", "infrastructure", "framework", 
                            "language", "server", "cloud", "kubernetes", "docker"]):
                        stack_info += f"- {consideration}\n"
            
            analytics_response = interface_with_analytics_monitoring_agent(
                project_name,
                specifications,
                stack_info
            )
            safe_emit('analytics_response_update', {'analytics_response': analytics_response})
        
        # Préparation de la réponse complète
        response = {
            'agents_analysis': agents_analysis,
            'specifications': specifications,
            'coding_tasks': coding_tasks,
            'test_plan': test_plan
        }
        
        # Ajouter chaque réponse d'agent si disponible
        if product_owner_response:
            response['product_owner_response'] = product_owner_response
            
        if ux_designer_response:
            response['ux_designer_response'] = ux_designer_response
            
        if dev_response:
            response['dev_response'] = dev_response
        
        if go_response:
            response['go_response'] = go_response
        
        if frontend_response:
            response['frontend_response'] = frontend_response
            
        if python_response:
            response['python_response'] = python_response
            
        if ios_response:
            response['ios_response'] = ios_response
            
        if android_response:
            response['android_response'] = android_response
        
        if qa_response:
            response['qa_response'] = qa_response
            
        if performance_response:
            response['performance_response'] = performance_response
            
        if devops_response:
            response['devops_response'] = devops_response
            
        if cicd_response:
            response['cicd_response'] = cicd_response
            
        if ml_response:
            response['ml_response'] = ml_response
            
        if analytics_response:
            response['analytics_response'] = analytics_response
        
        safe_emit('log', {'type': 'success', 'message': "Projet traité avec succès"})
        safe_emit('project_complete')
        
        return jsonify(response)
    
    except Exception as e:
        error_message = f"Erreur lors du traitement du projet: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message})

@app.route('/devops_request', methods=['POST'])
def devops_request():
    """Endpoint spécifique pour les demandes DevOps et CI/CD"""
    safe_emit('log', {'type': 'info', 'message': "Traitement de la demande DevOps"})
    
    data = request.json
    project_name = data.get('project_name', 'devops-project')
    action = data.get('action', 'generate')  # generate, status, run, deploy, rollback
    specifications = data.get('specifications', '')
    config_type = data.get('config_type', 'complete')
    environment = data.get('environment', 'dev')
    
    try:
        response = {'project_name': project_name}
        
        if action == 'generate':
            # Générer des configurations DevOps
            if not specifications:
                # Si aucune spécification n'est fournie, utiliser le modèle Claude pour en extraire
                if 'description' in data:
                    safe_emit('log', {'type': 'info', 'message': "Extraction des spécifications à partir de la description..."})
                    specifications = extract_specifications(data['description'])
                    safe_emit('specifications_update', {'specifications': specifications})
                else:
                    return jsonify({'error': "Les spécifications ou une description du projet sont requises", 'status': 'error'})
            
            # Appeler l'agent DevOps pour générer les configurations
            devops_response = interface_with_devops_agent(project_name, specifications, config_type)
            safe_emit('devops_response_update', {'devops_response': devops_response})
            
            response['devops_response'] = devops_response
            
        elif action in ['status', 'run', 'deploy', 'rollback']:
            # Communiquer avec l'agent DevOps pour les actions CI/CD
            cicd_response = manage_ci_cd_pipeline(project_name, action, environment)
            safe_emit('cicd_response_update', {'cicd_response': cicd_response})
            
            response['cicd_response'] = cicd_response
        
        else:
            return jsonify({'error': f"Action non reconnue: {action}", 'status': 'error'})
        
        safe_emit('log', {'type': 'success', 'message': "Demande DevOps traitée avec succès"})
        return jsonify(response)
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande DevOps: {str(e)}"
        safe_emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

def is_port_in_use(port):
    """Vérifie si un port est déjà utilisé."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def write_pid_file():
    """Écrit le PID du processus actuel dans le fichier PID."""
    import os
    pid_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'pids')
    os.makedirs(pid_dir, exist_ok=True)
    pid_file = os.path.join(pid_dir, 'chef_projet.pid')
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))
    logger.info(f"PID {os.getpid()} écrit dans {pid_file}")

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    logger.info("===============================================")
    logger.info("Démarrage de l'agent Chef de Projet")
    logger.info(f"Fichier de log: {log_file}")
    logger.info(f"ID du modèle Claude: {MODEL_ID}")
    logger.info(f"Région AWS: {REGION_NAME}")
    logger.info("===============================================")
    
    # Vérifier si le port est déjà utilisé
    port = 5000
    if is_port_in_use(port):
        logger.error(f"ERREUR: Le port {port} est déjà utilisé par un autre processus!")
        logger.error("Utilisez 'make stop-chef-projet' ou le script clean_processes.sh pour nettoyer les processus existants.")
        logger.error("L'agent Chef de Projet ne peut pas démarrer sur ce port.")
        return
    
    # Écrire le PID dans le fichier
    write_pid_file()
    
    try:
        # Vérifier si eventlet est disponible (il a déjà été importé et configuré au début du fichier)
        if 'eventlet' in sys.modules:
            logger.info("Mode Eventlet activé pour SocketIO")
        else:
            logger.warning("Eventlet n'est pas disponible, utilisation du mode SocketIO par défaut")
        
        # Ajouter un gestionnaire de signal pour les erreurs de pipe cassé
        import signal
        
        # Ignorer l'erreur SIGPIPE pour éviter le crash du serveur
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        
        # Gestionnaire pour arrêter proprement le serveur
        def signal_handler(sig, frame):
            logger.info("Signal d'arrêt reçu, arrêt propre du serveur...")
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        logger.info(f"Démarrage du serveur SocketIO sur le port 5000...")
        # Utiliser des options différentes selon que eventlet est disponible ou non
        if 'eventlet' in sys.modules:
            socketio.run(app, host='0.0.0.0', debug=False, use_reloader=False, port=5000, allow_unsafe_werkzeug=True)
        else:
            # Mode de secours sans eventlet
            logger.info("Utilisation du mode de secours sans eventlet")
            app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du serveur SocketIO: {str(e)}")
        logger.warning("Tentative de redémarrage en mode dégradé...")
        try:
            # Essayer en mode de secours avec debug=False
            socketio.run(app, debug=False, use_reloader=False, port=5000, allow_unsafe_werkzeug=True)
        except Exception as e2:
            logger.error(f"Erreur lors du redémarrage en mode dégradé: {str(e2)}")
            logger.warning("Démarrage du serveur Flask standard sans SocketIO")
            app.run(host='0.0.0.0', port=5000, debug=False)

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
    
    # Démarrer le serveur Flask avec SocketIO
    start_socketio()