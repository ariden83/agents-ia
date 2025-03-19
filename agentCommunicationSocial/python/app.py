import logging
import re
import time
import json
import re
import threading
import time
import os
import datetime
import random
from threading import Event
from dotenv import load_dotenv
from pathlib import Path

import boto3
import requests
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

# Identifiants des réseaux sociaux (idéalement à placer dans le fichier .env)
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET", "")

LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")

INSTAGRAM_API_KEY = os.getenv("INSTAGRAM_API_KEY", "")
INSTAGRAM_API_SECRET = os.getenv("INSTAGRAM_API_SECRET", "")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")

# Dossier de travail pour les communications
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'communicationsocial.log')

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

# Liste des planifications de communications
scheduled_communications = []
communication_thread = None
communication_active = False

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

def create_communication_strategy(project_info):
    """
    Crée une stratégie de communication pour un projet à partir de ses spécifications.
    
    Args:
        project_info (dict): Informations détaillées sur le projet
    
    Returns:
        dict: Stratégie de communication structurée
    """
    socketio.emit('log', {'type': 'info', 'message': "Création de la stratégie de communication..."})
    
    # Extraire les informations pertinentes du projet
    project_name = project_info.get('project_name', 'Projet')
    project_description = ""
    
    # Extraire la description du projet si disponible
    if 'specifications' in project_info:
        specs = project_info['specifications']
        if isinstance(specs, dict):
            if 'title' in specs:
                project_name = specs['title']
            if 'description' in specs:
                project_description = specs['description']
    
    # Si pas de description mais des tâches de développement, les utiliser
    if not project_description and 'coding_tasks' in project_info:
        coding_tasks = project_info['coding_tasks']
        if isinstance(coding_tasks, dict) and 'architecture' in coding_tasks:
            project_description = coding_tasks['architecture']
    
    # Système prompt pour guider Claude à créer une stratégie de communication
    system_prompt = """
    Vous êtes un expert en communication digitale, spécialisé dans la promotion de projets technologiques sur les réseaux sociaux.
    Votre tâche est de créer une stratégie de communication complète adaptée au projet présenté.
    
    Format de sortie:
    ```json
    {
        "strategy_overview": "Résumé de la stratégie de communication",
        "target_audience": ["Segment 1", "Segment 2", "Segment 3"],
        "tone_and_voice": "Description du ton et de la voix à adopter",
        "key_messages": ["Message clé 1", "Message clé 2", "Message clé 3"],
        "platforms": [
            {
                "name": "Twitter",
                "relevance": 95,
                "frequency": "3 fois par semaine",
                "content_types": ["Annonces", "Mises à jour techniques", "Citations inspirantes"]
            },
            {
                "name": "LinkedIn",
                "relevance": 90,
                "frequency": "2 fois par semaine",
                "content_types": ["Articles détaillés", "Mises à jour de fonctionnalités", "Témoignages"]
            },
            {
                "name": "Instagram",
                "relevance": 75,
                "frequency": "1 fois par semaine",
                "content_types": ["Infographies", "Screenshots du produit", "Témoignages visuels"]
            }
        ],
        "content_calendar": [
            {
                "week": 1,
                "theme": "Thème de la semaine 1",
                "posts": [
                    {
                        "platform": "Twitter",
                        "content_type": "Annonce",
                        "suggested_content": "Exemple de contenu pour Twitter",
                        "ideal_posting_time": "Mardi 10h",
                        "hashtags": ["#hashtag1", "#hashtag2"]
                    },
                    {
                        "platform": "LinkedIn",
                        "content_type": "Article détaillé",
                        "suggested_content": "Exemple de contenu pour LinkedIn",
                        "ideal_posting_time": "Jeudi 14h",
                        "hashtags": ["#hashtag1", "#hashtag3"]
                    }
                ]
            }
        ],
        "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4"],
        "success_metrics": ["Engagement rate", "Click-through rate", "Conversion rate", "Audience growth"]
    }
    ```
    
    Directives :
    1. Créez une stratégie réaliste et professionnelle qui s'aligne sur les objectifs du projet.
    2. Adaptez le ton et le style au secteur d'activité et au public cible.
    3. Sélectionnez les plateformes les plus pertinentes avec des scores de pertinence (0-100).
    4. Créez un calendrier éditorial pour les 4 prochaines semaines.
    5. Proposez des exemples concrets de contenu adaptés à chaque plateforme.
    6. Incluez des hashtags pertinents et spécifiques au secteur.
    """
    
    # Construction du prompt pour créer une stratégie de communication
    prompt = f"""
    Je travaille sur un projet technologique et j'ai besoin d'une stratégie de communication pour sa promotion sur les réseaux sociaux.
    
    Nom du projet : {project_name}
    
    Description du projet :
    {project_description}
    
    Je souhaite développer une stratégie de communication cohérente et efficace pour ce projet.
    Veuillez créer une stratégie de communication détaillée selon le format demandé.
    """
    
    # Invocation de Claude
    response = invoke_claude(prompt, system_prompt)
    
    # Extraction du JSON de la réponse
    try:
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            strategy_json = json.loads(json_match.group(1))
            socketio.emit('log', {'type': 'success', 'message': "Stratégie de communication créée avec succès"})
            return strategy_json
        else:
            # Tenter de trouver un JSON sans les backticks
            json_match = re.search(r'({.*})', response, re.DOTALL)
            if json_match:
                strategy_json = json.loads(json_match.group(1))
                return strategy_json
            else:
                socketio.emit('log', {'type': 'warning', 'message': "Format JSON non trouvé, utilisation de la réponse brute"})
                return {"strategy_overview": response}
    except Exception as e:
        socketio.emit('log', {'type': 'error', 'message': f"Erreur lors du parsing JSON: {str(e)}"})
        return {"strategy_overview": response}

def generate_social_media_content(platform, content_type, project_info, previous_posts=None, special_event=None):
    """
    Génère du contenu pour les réseaux sociaux adapté à la plateforme et au type de contenu.
    
    Args:
        platform (str): Plateforme cible (Twitter, LinkedIn, Instagram, etc.)
        content_type (str): Type de contenu à générer
        project_info (dict): Informations sur le projet
        previous_posts (list, optional): Posts précédents pour assurer la variété
        special_event (str, optional): Événement spécial à mentionner
    
    Returns:
        dict: Contenu généré pour les réseaux sociaux
    """
    socketio.emit('log', {'type': 'info', 'message': f"Génération de contenu pour {platform}..."})
    
    # Extraire les informations pertinentes du projet
    project_name = project_info.get('project_name', 'Projet')
    project_description = ""
    strategy = project_info.get('communication_strategy', {})
    tone = strategy.get('tone_and_voice', 'Professionnel et informatif')
    key_messages = strategy.get('key_messages', [])
    hashtags = strategy.get('hashtags', [])
    
    # Extraire la description du projet si disponible
    if 'specifications' in project_info:
        specs = project_info['specifications']
        if isinstance(specs, dict):
            if 'title' in specs:
                project_name = specs['title']
            if 'description' in specs:
                project_description = specs['description']
    
    # Formater les posts précédents pour le contexte
    previous_content = ""
    if previous_posts and len(previous_posts) > 0:
        previous_content = "Posts précédents (pour éviter les répétitions):\n"
        for post in previous_posts[-5:]:  # Limiter aux 5 derniers posts
            previous_content += f"- {post.get('content', '')}\n"
    
    # Système prompt pour guider Claude à générer du contenu social media
    system_prompt = f"""
    Vous êtes un expert en communication digitale, spécialisé dans la création de contenu pour {platform}.
    Votre tâche est de créer un post {content_type} qui soit accrocheur, pertinent et adapté au format de {platform}.
    
    Format de sortie:
    ```json
    {{
        "content": "Le contenu principal du post",
        "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3"],
        "media_suggestion": "Description du visuel ou du média qui devrait accompagner le post",
        "call_to_action": "L'action que vous voulez que le lecteur entreprenne"
    }}
    ```
    
    Directives pour {platform}:
    """
    
    # Ajouter des directives spécifiques à chaque plateforme
    if platform.lower() == "twitter":
        system_prompt += """
        - Limitez votre contenu à 280 caractères maximum
        - Utilisez 2-3 hashtags pertinents
        - Soyez direct et incisif
        - Un visuel vaut mieux que de longs discours
        - Incluez un appel à l'action clair
        """
    elif platform.lower() == "linkedin":
        system_prompt += """
        - Privilégiez un ton professionnel mais chaleureux
        - Structurez votre contenu avec des paragraphes courts
        - Posez une question provocante pour susciter l'engagement
        - Limitez les hashtags à 3-5 très pertinents
        - Ajoutez une valeur professionnelle claire
        """
    elif platform.lower() == "instagram":
        system_prompt += """
        - Mettez l'accent sur le visuel, le contenu est secondaire
        - Décrivez en détail l'image qui devrait accompagner le texte
        - Utilisez des émojis judicieusement pour dynamiser le texte
        - 5-10 hashtags pertinents et populaires
        - Adressez-vous directement à l'utilisateur
        """
    else:
        system_prompt += """
        - Adaptez le contenu au format et au ton de la plateforme
        - Soyez concis et précis
        - Incluez des appels à l'action clairs
        - Utilisez des hashtags pertinents
        """
    
    # Construction du prompt pour générer du contenu
    prompt = f"""
    Je dois créer un post de type "{content_type}" pour {platform} concernant le projet suivant:
    
    Nom du projet: {project_name}
    Description: {project_description}
    
    Ton et voix à adopter: {tone}
    
    Messages clés à intégrer (un ou plusieurs):
    {", ".join(key_messages) if key_messages else "Informer sur le projet et ses avancées"}
    
    Hashtags suggérés: {", ".join(hashtags) if hashtags else "À déterminer selon pertinence"}
    
    {previous_content}
    
    {f"Événement spécial à mentionner: {special_event}" if special_event else ""}
    
    Veuillez générer un post {content_type} pour {platform} selon le format demandé.
    """
    
    # Invocation de Claude
    response = invoke_claude(prompt, system_prompt)
    
    # Extraction du JSON de la réponse
    try:
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            content_json = json.loads(json_match.group(1))
            socketio.emit('log', {'type': 'success', 'message': f"Contenu pour {platform} généré avec succès"})
            return content_json
        else:
            # Tenter de trouver un JSON sans les backticks
            json_match = re.search(r'({.*})', response, re.DOTALL)
            if json_match:
                content_json = json.loads(json_match.group(1))
                return content_json
            else:
                socketio.emit('log', {'type': 'warning', 'message': "Format JSON non trouvé, utilisation de la réponse brute"})
                return {"content": response}
    except Exception as e:
        socketio.emit('log', {'type': 'error', 'message': f"Erreur lors du parsing JSON: {str(e)}"})
        return {"content": response}

def post_to_twitter(content, media_path=None):
    """
    Publie un contenu sur Twitter en utilisant l'API Twitter.
    
    Args:
        content (str): Contenu textuel du tweet
        media_path (str, optional): Chemin vers le média à joindre
    
    Returns:
        dict: Réponse de l'API Twitter
    """
    socketio.emit('log', {'type': 'info', 'message': "Publication sur Twitter..."})
    
    # Vérifier que les clés d'API sont configurées
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        error_message = "Configuration Twitter incomplète. Veuillez configurer les clés d'API dans le fichier .env"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message, "success": False}
    
    try:
        # Simuler la publication sur Twitter (à remplacer par l'appel API réel)
        # Dans un environnement de production, utiliser tweepy ou l'API Twitter directement
        
        # Ici, on simule une publication réussie
        response = {
            "created_at": datetime.datetime.now().isoformat(),
            "id": f"tweet_{int(time.time())}",
            "text": content,
            "media": media_path if media_path else None,
            "success": True
        }
        
        socketio.emit('log', {'type': 'success', 'message': "Publication sur Twitter réussie"})
        return response
    
    except Exception as e:
        error_message = f"Erreur lors de la publication sur Twitter: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message, "success": False}

def post_to_linkedin(content, media_path=None):
    """
    Publie un contenu sur LinkedIn en utilisant l'API LinkedIn.
    
    Args:
        content (str): Contenu textuel du post
        media_path (str, optional): Chemin vers le média à joindre
    
    Returns:
        dict: Réponse de l'API LinkedIn
    """
    socketio.emit('log', {'type': 'info', 'message': "Publication sur LinkedIn..."})
    
    # Vérifier que les clés d'API sont configurées
    if not all([LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_ACCESS_TOKEN]):
        error_message = "Configuration LinkedIn incomplète. Veuillez configurer les clés d'API dans le fichier .env"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message, "success": False}
    
    try:
        # Simuler la publication sur LinkedIn (à remplacer par l'appel API réel)
        # Dans un environnement de production, utiliser l'API LinkedIn directement
        
        # Ici, on simule une publication réussie
        response = {
            "created_at": datetime.datetime.now().isoformat(),
            "id": f"linkedin_{int(time.time())}",
            "text": content,
            "media": media_path if media_path else None,
            "success": True
        }
        
        socketio.emit('log', {'type': 'success', 'message': "Publication sur LinkedIn réussie"})
        return response
    
    except Exception as e:
        error_message = f"Erreur lors de la publication sur LinkedIn: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message, "success": False}

def post_to_instagram(content, media_path):
    """
    Publie un contenu sur Instagram en utilisant l'API Instagram.
    
    Args:
        content (str): Contenu textuel de la publication (légende)
        media_path (str): Chemin vers le média à publier (obligatoire pour Instagram)
    
    Returns:
        dict: Réponse de l'API Instagram
    """
    socketio.emit('log', {'type': 'info', 'message': "Publication sur Instagram..."})
    
    # Vérifier que les clés d'API sont configurées
    if not all([INSTAGRAM_API_KEY, INSTAGRAM_API_SECRET, INSTAGRAM_ACCESS_TOKEN]):
        error_message = "Configuration Instagram incomplète. Veuillez configurer les clés d'API dans le fichier .env"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message, "success": False}
    
    # Vérifier qu'un média est fourni (obligatoire pour Instagram)
    if not media_path:
        error_message = "Un média est obligatoire pour publier sur Instagram"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message, "success": False}
    
    try:
        # Simuler la publication sur Instagram (à remplacer par l'appel API réel)
        # Dans un environnement de production, utiliser l'API Instagram directement
        
        # Ici, on simule une publication réussie
        response = {
            "created_at": datetime.datetime.now().isoformat(),
            "id": f"instagram_{int(time.time())}",
            "caption": content,
            "media": media_path,
            "success": True
        }
        
        socketio.emit('log', {'type': 'success', 'message': "Publication sur Instagram réussie"})
        return response
    
    except Exception as e:
        error_message = f"Erreur lors de la publication sur Instagram: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message, "success": False}

def post_to_social_media(platform, content_data):
    """
    Publie un contenu sur la plateforme de médias sociaux spécifiée.
    
    Args:
        platform (str): Plateforme sur laquelle publier (Twitter, LinkedIn, Instagram)
        content_data (dict): Données du contenu à publier
    
    Returns:
        dict: Résultat de la publication
    """
    content = content_data.get('content', '')
    hashtags = content_data.get('hashtags', [])
    media_suggestion = content_data.get('media_suggestion', '')
    
    # Ajouter les hashtags au contenu
    if hashtags:
        if platform.lower() == "twitter":
            # Pour Twitter, les hashtags font partie du contenu et sont limités
            content += ' ' + ' '.join(hashtags[:3])  # Limiter à 3 hashtags
        elif platform.lower() == "linkedin":
            # Pour LinkedIn, les hashtags sont ajoutés à la fin
            content += '\n\n' + ' '.join(hashtags[:5])  # Limiter à 5 hashtags
        elif platform.lower() == "instagram":
            # Pour Instagram, on peut utiliser plus de hashtags
            content += '\n\n' + ' '.join(hashtags[:15])  # Limiter à 15 hashtags
    
    # Simuler le chemin vers un média (à remplacer par la génération réelle d'images)
    media_path = None
    if media_suggestion:
        # Dans une implémentation réelle, on pourrait générer une image avec DALL-E ou Stable Diffusion
        # ici, on simule juste un chemin de fichier
        media_path = f"/path/to/generated/media_{int(time.time())}.jpg"
    
    # Publier sur la plateforme appropriée
    if platform.lower() == "twitter":
        return post_to_twitter(content, media_path)
    elif platform.lower() == "linkedin":
        return post_to_linkedin(content, media_path)
    elif platform.lower() == "instagram":
        # Instagram nécessite un média
        media_path = media_path or f"/path/to/default/image_{int(time.time())}.jpg"
        return post_to_instagram(content, media_path)
    else:
        error_message = f"Plateforme non prise en charge: {platform}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message, "success": False}

def schedule_social_media_posts(communication_strategy, project_info):
    """
    Planifie des publications sur les réseaux sociaux en fonction de la stratégie de communication.
    
    Args:
        communication_strategy (dict): Stratégie de communication
        project_info (dict): Informations sur le projet
    
    Returns:
        list: Liste des publications planifiées
    """
    global scheduled_communications
    
    # Vider les anciennes planifications
    scheduled_communications = []
    
    # Récupérer les plateformes et leurs fréquences
    platforms = communication_strategy.get('platforms', [])
    content_calendar = communication_strategy.get('content_calendar', [])
    
    # Planifier les publications à partir du calendrier éditorial
    if content_calendar:
        for week_plan in content_calendar:
            week_number = week_plan.get('week', 1)
            posts = week_plan.get('posts', [])
            
            for post in posts:
                platform = post.get('platform', '')
                content_type = post.get('content_type', '')
                ideal_time = post.get('ideal_posting_time', '')
                
                # Convertir le temps idéal en décalage par rapport à maintenant
                # Par défaut, poster dans une semaine * numéro de semaine
                time_offset = week_number * 7 * 24 * 60 * 60  # en secondes
                
                # Si un temps idéal est spécifié, affiner le décalage
                if ideal_time:
                    try:
                        # Exemple: "Mardi 10h" -> ajouter des jours si nécessaire
                        day_mapping = {
                            "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
                            "vendredi": 4, "samedi": 5, "dimanche": 6
                        }
                        
                        parts = ideal_time.lower().split()
                        if len(parts) >= 2:
                            day = parts[0]
                            hour = parts[1].replace('h', '')
                            
                            if day in day_mapping:
                                # Calculer le prochain jour correspondant
                                current_weekday = datetime.datetime.now().weekday()
                                days_to_add = (day_mapping[day] - current_weekday) % 7
                                if days_to_add == 0:
                                    days_to_add = 7  # Passer à la semaine suivante
                                
                                # Ajouter les jours et l'heure
                                time_offset = days_to_add * 24 * 60 * 60  # jours en secondes
                                if hour.isdigit():
                                    target_hour = int(hour)
                                    current_hour = datetime.datetime.now().hour
                                    hours_to_add = (target_hour - current_hour) % 24
                                    time_offset += hours_to_add * 60 * 60  # heures en secondes
                    except:
                        # Si erreur de parsing, conserver le décalage par défaut
                        pass
                
                # Calculer la date de publication prévue
                scheduled_time = datetime.datetime.now() + datetime.timedelta(seconds=time_offset)
                
                # Planifier la publication
                scheduled_post = {
                    "platform": platform,
                    "content_type": content_type,
                    "scheduled_time": scheduled_time.isoformat(),
                    "processed": False,
                    "post_data": None
                }
                
                scheduled_communications.append(scheduled_post)
    
    # Si pas de calendrier, utiliser les plateformes et leurs fréquences
    elif platforms:
        current_time = datetime.datetime.now()
        
        for platform_info in platforms:
            platform = platform_info.get('name', '')
            frequency = platform_info.get('frequency', '')
            content_types = platform_info.get('content_types', ['Mise à jour'])
            
            # Extraire le nombre de publications par semaine
            posts_per_week = 1  # valeur par défaut
            if frequency:
                try:
                    # Exemple: "3 fois par semaine" -> 3
                    parts = frequency.split()
                    if parts and parts[0].isdigit():
                        posts_per_week = int(parts[0])
                except:
                    pass
            
            # Planifier les publications sur 4 semaines
            for week in range(1, 5):
                for post_num in range(posts_per_week):
                    # Sélectionner un type de contenu au hasard
                    content_type = random.choice(content_types) if content_types else "Mise à jour"
                    
                    # Calculer le décalage temporel (répartir sur la semaine)
                    days_offset = week * 7 + post_num * (7 / max(posts_per_week, 1))
                    hours_offset = random.randint(9, 17)  # Entre 9h et 17h
                    
                    scheduled_time = current_time + datetime.timedelta(days=days_offset, hours=hours_offset)
                    
                    # Planifier la publication
                    scheduled_post = {
                        "platform": platform,
                        "content_type": content_type,
                        "scheduled_time": scheduled_time.isoformat(),
                        "processed": False,
                        "post_data": None
                    }
                    
                    scheduled_communications.append(scheduled_post)
    
    # Trier les publications par date
    scheduled_communications.sort(key=lambda x: x["scheduled_time"])
    
    # Enregistrer la planification dans un fichier JSON
    communication_plan_path = os.path.join(WORKSPACE_DIR, f"communication_plan_{int(time.time())}.json")
    with open(communication_plan_path, 'w') as f:
        json.dump(scheduled_communications, f, indent=2)
    
    socketio.emit('log', {'type': 'success', 'message': f"Planification créée avec {len(scheduled_communications)} publications"})
    socketio.emit('scheduled_posts_update', {'scheduled_posts': scheduled_communications})
    
    return scheduled_communications

def communication_worker(project_info):
    """
    Fonction de travail pour le thread de communication qui gère les publications planifiées.
    """
    global communication_active
    
    posted_content = []  # Historique des publications
    
    while communication_active:
        try:
            # Vérifier s'il y a des publications à traiter
            now = datetime.datetime.now()
            
            for i, post in enumerate(scheduled_communications):
                if post["processed"]:
                    continue
                
                # Convertir la date planifiée en objet datetime
                scheduled_time = datetime.datetime.fromisoformat(post["scheduled_time"])
                
                # Si l'heure de publication est passée
                if now >= scheduled_time:
                    socketio.emit('log', {'type': 'info', 'message': f"Traitement du post planifié pour {post['platform']}..."})
                    
                    # Générer le contenu
                    content_data = generate_social_media_content(
                        post["platform"],
                        post["content_type"],
                        project_info,
                        posted_content
                    )
                    
                    # Publier sur la plateforme
                    post_result = post_to_social_media(post["platform"], content_data)
                    
                    # Mettre à jour le statut du post
                    scheduled_communications[i]["processed"] = True
                    scheduled_communications[i]["post_data"] = content_data
                    scheduled_communications[i]["post_result"] = post_result
                    
                    # Ajouter à l'historique
                    if post_result.get("success", False):
                        posted_content.append({
                            "platform": post["platform"],
                            "content": content_data.get("content", ""),
                            "posted_at": now.isoformat()
                        })
                    
                    # Mettre à jour l'interface
                    socketio.emit('scheduled_posts_update', {'scheduled_posts': scheduled_communications})
            
            # Attendre avant la prochaine vérification
            time.sleep(60)  # Vérifier toutes les minutes
            
        except Exception as e:
            error_message = f"Erreur dans le thread de communication: {str(e)}"
            socketio.emit('log', {'type': 'error', 'message': error_message})
            time.sleep(300)  # Attendre 5 minutes en cas d'erreur

def start_communication_thread(project_info):
    """
    Démarre le thread de communication qui gère les publications planifiées.
    
    Args:
        project_info (dict): Informations sur le projet
    """
    global communication_thread, communication_active
    
    # Arrêter le thread existant s'il est actif
    if communication_thread and communication_thread.is_alive():
        stop_communication_thread()
    
    # Démarrer un nouveau thread
    communication_active = True
    communication_thread = threading.Thread(target=communication_worker, args=(project_info,))
    communication_thread.daemon = True
    communication_thread.start()
    
    socketio.emit('log', {'type': 'success', 'message': "Thread de communication démarré"})
    return {"status": "started"}

def stop_communication_thread():
    """
    Arrête le thread de communication.
    """
    global communication_active
    
    communication_active = False
    if communication_thread:
        # Attendre que le thread se termine
        if communication_thread.is_alive():
            communication_thread.join(timeout=5)
    
    socketio.emit('log', {'type': 'info', 'message': "Thread de communication arrêté"})
    return {"status": "stopped"}

@app.route('/communication_request', methods=['POST'])
def communication_request():
    """Endpoint pour recevoir et traiter les demandes de communication"""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande de communication"})
    
    data = request.json
    project_info = data.get('project_info', {})
    action = data.get('action', 'create_strategy')
    
    try:
        if action == 'create_strategy':
            # Créer une stratégie de communication
            communication_strategy = create_communication_strategy(project_info)
            
            # Ajouter la stratégie au projet
            project_info['communication_strategy'] = communication_strategy
            
            return jsonify({
                'status': 'success',
                'project_info': project_info,
                'communication_strategy': communication_strategy
            })
        
        elif action == 'schedule_posts':
            # Vérifier si une stratégie de communication existe
            communication_strategy = project_info.get('communication_strategy', None)
            
            if not communication_strategy:
                # Si pas de stratégie, en créer une
                communication_strategy = create_communication_strategy(project_info)
                project_info['communication_strategy'] = communication_strategy
            
            # Planifier les publications
            scheduled_posts = schedule_social_media_posts(communication_strategy, project_info)
            
            return jsonify({
                'status': 'success',
                'project_info': project_info,
                'scheduled_posts': scheduled_posts
            })
        
        elif action == 'start_communication':
            # Démarrer le thread de communication
            start_communication_thread(project_info)
            
            return jsonify({
                'status': 'success',
                'message': 'Communication thread started'
            })
        
        elif action == 'stop_communication':
            # Arrêter le thread de communication
            stop_communication_thread()
            
            return jsonify({
                'status': 'success',
                'message': 'Communication thread stopped'
            })
        
        elif action == 'generate_post':
            # Générer un post spécifique
            platform = data.get('platform', 'Twitter')
            content_type = data.get('content_type', 'Mise à jour')
            special_event = data.get('special_event', None)
            
            # Générer le contenu
            content_data = generate_social_media_content(
                platform,
                content_type,
                project_info,
                special_event=special_event
            )
            
            return jsonify({
                'status': 'success',
                'content_data': content_data
            })
        
        elif action == 'post_now':
            # Publier immédiatement
            platform = data.get('platform', 'Twitter')
            content_data = data.get('content_data', {})
            
            # Publier sur la plateforme
            post_result = post_to_social_media(platform, content_data)
            
            return jsonify({
                'status': 'success',
                'post_result': post_result
            })
        
        else:
            return jsonify({
                'status': 'error',
                'message': f'Action non reconnue: {action}'
            })
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande de communication: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return jsonify({'error': error_message, 'status': 'error'})

@app.route('/get_scheduled_posts', methods=['GET'])
def get_scheduled_posts():
    """Endpoint pour récupérer les publications planifiées"""
    return jsonify({
        'status': 'success',
        'scheduled_posts': scheduled_communications
    })

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
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent communicationsocial"})
    
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
            log_path = os.path.join(log_dir, 'communicationsocial.log')
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