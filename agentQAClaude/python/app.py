import logging
import re
import time
import re
import json
import threading
import time
from threading import Event
import base64
import os
import asyncio
from browser_use import Browser
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

# Initialisation de l'application Flask

# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'qaclaude.log')

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

# Instance du navigateur
browser = None
browser_lock = threading.Lock()

@app.route('/')
def index():
    return render_template('index.html')

# Fonction supprimée - remplacée par une logique de retry automatique
# def wait_for_user_confirmation():
#     """Met en pause le script jusqu'à confirmation de l'utilisateur."""
#     user_action_event.clear()
#     socketio.emit('wait_for_user_action', {})
#     user_action_event.wait()
#     time.sleep(1)

# Événement toujours présent pour support de l'interface, mais sans attente
@socketio.on('user_action_done')
def handle_user_action_done():
    """Déclenchement reçu de l'interface, mais notre agent est autonome."""
    user_action_event.set()
    socketio.emit('log', {'type': 'info', 'message': "Confirmation utilisateur reçue, mais non requise - l'agent est autonome."})

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
                3. Utiliser des méthodes standard de test pour cette interface
                
                Je vais faire de mon mieux pour poursuivre l'analyse avec les informations disponibles.
                """
                
                return fallback_response
    
    # Ce code ne devrait jamais être atteint, mais par sécurité
    socketio.emit('loading_end')
    return "Erreur inattendue lors de l'invocation du modèle"

async def initialize_browser(max_retries=3, retry_delay=2):
    """
    Initialise l'instance du navigateur BrowserUse avec retry automatique.
    
    Args:
        max_retries (int): Nombre maximum de tentatives d'initialisation
        retry_delay (int): Délai en secondes entre les tentatives
    
    Returns:
        bool: True si l'initialisation a réussi, False sinon
    """
    global browser
    
    socketio.emit('log', {'type': 'info', 'message': "Initialisation du navigateur..."})
    
    for attempt in range(1, max_retries + 1):
        try:
            # Initialiser le navigateur avec Playwright en mode headless pour plus de stabilité
            # En environnement autonome, le mode headless est préférable pour éviter les problèmes d'affichage
            browser = await Browser.create(headless=True)
            
            # Configuration des timeouts pour plus de robustesse
            await browser.set_default_timeout(30000)  # 30 secondes de timeout par défaut
            
            # Configuration de la taille de la fenêtre pour assurer une expérience de test cohérente
            await browser.set_viewport_size(width=1280, height=800)
            
            socketio.emit('log', {'type': 'success', 'message': "Navigateur initialisé avec succès"})
            return True
            
        except Exception as e:
            error_message = f"Erreur lors de l'initialisation du navigateur (tentative {attempt}/{max_retries}): {str(e)}"
            
            if attempt < max_retries:
                socketio.emit('log', {'type': 'warning', 'message': f"{error_message} - Nouvelle tentative dans {retry_delay}s"})
                
                # Vérifier si un navigateur existe déjà et le fermer proprement
                if browser:
                    try:
                        await browser.close()
                    except:
                        pass
                    browser = None
                
                # Attendre avant la prochaine tentative
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5  # Augmentation progressive du délai
            else:
                socketio.emit('log', {'type': 'error', 'message': f"{error_message} - Échec après {max_retries} tentatives"})
                return False
    
    return False  # Ne devrait jamais être atteint, mais par sécurité

async def close_browser():
    """Ferme l'instance du navigateur."""
    global browser
    
    if browser:
        socketio.emit('log', {'type': 'info', 'message': "Fermeture du navigateur..."})
        try:
            await browser.close()
            browser = None
            socketio.emit('log', {'type': 'success', 'message': "Navigateur fermé avec succès"})
        except Exception as e:
            socketio.emit('log', {'type': 'error', 'message': f"Erreur lors de la fermeture du navigateur: {str(e)}"})

async def navigate_to_url(url, max_retries=3, retry_delay=2):
    """
    Navigue vers l'URL spécifiée et capture une capture d'écran.
    Inclut une logique de retry automatique.
    
    Args:
        url (str): URL à visiter
        max_retries (int): Nombre maximum de tentatives de navigation
        retry_delay (int): Délai en secondes entre les tentatives
    
    Returns:
        str: HTML de la page ou None en cas d'erreur après toutes les tentatives
    """
    global browser
    
    socketio.emit('log', {'type': 'info', 'message': f"Navigation vers: {url}"})
    
    for attempt in range(1, max_retries + 1):
        try:
            # Si ce n'est pas la première tentative, afficher un message
            if attempt > 1:
                socketio.emit('log', {'type': 'info', 'message': f"Tentative de navigation #{attempt}..."})
            
            # Naviguer vers l'URL avec un timeout
            await asyncio.wait_for(browser.goto(url), timeout=30)
            
            # Attendre que la page soit chargée avec un délai supplémentaire pour les éléments dynamiques
            await browser.wait_for_page_to_load()
            
            # Vérifier que la page a bien chargé
            current_url = await browser.get_current_url()
            if not current_url:
                raise Exception("URL vide après navigation")
                
            # Attendre un délai supplémentaire pour les éléments dynamiques
            await asyncio.sleep(1)
            
            # Capture d'écran pour référence
            try:
                screenshot = await browser.screenshot()
                screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                socketio.emit('screenshot_update', {'screenshot': screenshot_base64})
            except Exception as screenshot_error:
                socketio.emit('log', {'type': 'warning', 'message': f"Impossible de capturer l'écran: {str(screenshot_error)}"})
            
            # Récupérer le HTML de la page avec retry au cas où
            html = None
            html_attempts = 0
            while html_attempts < 3 and not html:
                try:
                    html = await browser.get_page_html()
                except:
                    html_attempts += 1
                    await asyncio.sleep(0.5)
            
            if not html:
                raise Exception("Impossible de récupérer le HTML de la page")
            
            socketio.emit('log', {'type': 'success', 'message': f"Page chargée avec succès (taille HTML: {len(html)} caractères)"})
            return html
        
        except asyncio.TimeoutError:
            error_message = f"Timeout lors de la navigation (tentative {attempt}/{max_retries})"
            
            if attempt < max_retries:
                socketio.emit('log', {'type': 'warning', 'message': f"{error_message} - Nouvelle tentative dans {retry_delay}s"})
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5  # Augmentation progressive du délai
            else:
                socketio.emit('log', {'type': 'error', 'message': f"{error_message} - Échec après {max_retries} tentatives"})
                return None
        
        except Exception as e:
            error_message = f"Erreur lors de la navigation: {str(e)} (tentative {attempt}/{max_retries})"
            
            if attempt < max_retries:
                socketio.emit('log', {'type': 'warning', 'message': f"{error_message} - Nouvelle tentative dans {retry_delay}s"})
                
                # Vérifier si la page a quand même chargé partiellement
                try:
                    current_url = await browser.get_current_url()
                    if current_url and current_url != "about:blank":
                        socketio.emit('log', {'type': 'info', 'message': f"Page partiellement chargée: {current_url}"})
                        
                        # Capturer une capture d'écran pour le diagnostic
                        try:
                            screenshot = await browser.screenshot()
                            screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                            socketio.emit('screenshot_update', {'screenshot': screenshot_base64})
                        except:
                            pass
                        
                        # Essayer de récupérer le HTML même en cas d'erreur
                        try:
                            html = await browser.get_page_html()
                            if html and len(html) > 100:  # Vérifier que le HTML est significatif
                                socketio.emit('log', {'type': 'success', 'message': "HTML récupéré malgré l'erreur"})
                                return html
                        except:
                            pass
                except:
                    pass
                
                # Attendre avant la prochaine tentative
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5  # Augmentation progressive du délai
            else:
                socketio.emit('log', {'type': 'error', 'message': f"{error_message} - Échec après {max_retries} tentatives"})
                
                # Essayer une dernière fois de récupérer le HTML, même partiel
                try:
                    html = await browser.get_page_html()
                    if html and len(html) > 100:
                        socketio.emit('log', {'type': 'warning', 'message': "HTML partiel récupéré malgré l'échec de navigation"})
                        return html
                except:
                    pass
                
                return None
    
    return None  # Ne devrait jamais être atteint, mais par sécurité

async def extract_task_description(task):
    """
    Extrait une description détaillée de la tâche à partir de l'entrée utilisateur.
    
    Args:
        task (str): Description de la tâche fournie par l'utilisateur
    
    Returns:
        str: Description détaillée de la tâche
    """
    # Système prompt pour guider Claude à comprendre la tâche
    system_prompt = """
    Vous êtes un expert QA qui aide à analyser et structurer les tâches de test.
    Votre rôle est de transformer les demandes de test brutes en plans de test clairs.
    
    Veuillez analyser la demande de test fournie et:
    1. Identifier les objectifs principaux du test
    2. Déterminer les étapes nécessaires pour accomplir ces objectifs
    3. Identifier les critères de succès
    
    Votre réponse doit être concise et se concentrer uniquement sur la tâche de test.
    """
    
    # Construction du prompt pour comprendre la tâche
    prompt = f"""
    Voici une demande de test sur une application web:
    
    {task}
    
    Veuillez analyser cette demande et me fournir:
    1. Un résumé clair de l'objectif du test
    2. Les étapes principales que je dois suivre
    3. Comment je saurai que le test est réussi
    """
    
    # Invoquer Claude pour analyser la tâche
    response = invoke_claude(prompt, system_prompt)
    socketio.emit('task_analysis', {'analysis': response})
    
    return response

async def execute_browser_action(action_description, html_context, max_attempts=3):
    """
    Exécute une action de navigation en utilisant Claude pour générer les commandes browser_use.
    Inclut une logique de retry et d'alternatives automatiques en cas d'échec.
    
    Args:
        action_description (str): Description de l'action à exécuter
        html_context (str): HTML de la page courante
        max_attempts (int): Nombre maximum de tentatives pour cette action
    
    Returns:
        dict: Résultat de l'action (succès, message, etc.)
    """
    # Système prompt pour guider Claude à générer des commandes browser_use
    system_prompt = """
    Vous êtes un expert en automatisation de tests qui utilise la bibliothèque browser_use pour Python.
    Votre tâche est de générer le code Python utilisant browser_use pour effectuer des actions dans un navigateur web.
    
    Voici les méthodes principales de browser_use que vous pouvez utiliser:
    - browser.click(selector) - Clique sur un élément
    - browser.type(selector, text) - Tape du texte dans un champ
    - browser.select(selector, value) - Sélectionne une option dans un menu déroulant
    - browser.hover(selector) - Survole un élément
    - browser.navigate(url) - Navigue vers une URL
    - browser.get_text(selector) - Obtient le texte d'un élément
    - browser.wait_for_element(selector, timeout) - Attend qu'un élément apparaisse
    - browser.wait_for_navigation() - Attend que la navigation soit terminée
    - browser.evaluate_javascript(script) - Exécute du JavaScript dans la page
    - browser.screenshot() - Prend une capture d'écran
    
    Votre réponse doit contenir uniquement le code Python nécessaire pour accomplir l'action décrite,
    sans explications ni commentaires. Le code doit être dans un bloc de code Python précédé par
    "CODE:" et doit être utilisable directement avec la bibliothèque browser_use.
    
    Pour une meilleure fiabilité:
    - Utilisez des sélecteurs robustes (ID > attributs data > classes)
    - Utilisez browser.wait_for_element() avant d'interagir avec un élément
    - Utilisez browser.wait_for_navigation() après les actions qui déclenchent une navigation
    - Préférez des sélecteurs plus génériques avec timeout si les éléments sont dynamiques
    
    Exemple de réponse:
    CODE:
    await browser.wait_for_element("button#submit", timeout=5000)
    await browser.click("button#submit")
    await browser.wait_for_navigation()
    """
    
    # Tentatives successives
    for attempt in range(1, max_attempts + 1):
        try:
            # Mettre à jour le HTML à chaque tentative pour avoir le contexte le plus récent
            if attempt > 1:
                try:
                    html_context = await browser.get_page_html()
                except:
                    pass  # En cas d'échec, on garde le HTML précédent
                
                # Ajout de contexte pour les tentatives suivantes
                action_description_with_context = f"""
                {action_description}
                
                CONTEXTE SUPPLÉMENTAIRE: Ceci est la tentative #{attempt}. 
                Les tentatives précédentes ont échoué pour cette action.
                Essayez une approche différente, comme:
                - Utiliser des sélecteurs plus génériques
                - Ajouter des délais ou waitFor
                - Utiliser des attributs ou des textes visibles pour sélectionner les éléments
                - Tester l'existence de l'élément avant d'interagir avec
                """
            else:
                action_description_with_context = action_description
            
            # Construction du prompt pour générer le code browser_use
            prompt = f"""
            Action à réaliser: {action_description_with_context}
            
            Voici le HTML actuel de la page:
            ```html
            {html_context[:50000]}  # Limiter la taille du HTML pour éviter les problèmes de tokens
            ```
            
            Générez le code Python robuste utilisant browser_use pour effectuer cette action.
            """
            
            # Invoquer Claude pour générer le code
            response = invoke_claude(prompt, system_prompt)
            
            # Extraire le code de la réponse
            code_match = re.search(r'CODE:\s*(.*?)(?=\s*CODE:|$)', response, re.DOTALL)
            
            if not code_match:
                if attempt < max_attempts:
                    socketio.emit('log', {'type': 'warning', 'message': f"Aucun code valide trouvé dans la réponse (tentative {attempt}/{max_attempts})"})
                    continue
                else:
                    error_message = "Aucun code valide trouvé dans la réponse après plusieurs tentatives"
                    socketio.emit('log', {'type': 'error', 'message': error_message})
                    return {"success": False, "message": error_message}
            
            code = code_match.group(1).strip()
            socketio.emit('log', {'type': 'code', 'message': code})
            
            # Ajouter de la robustesse en ajoutant un try-except au code
            if "try:" not in code:
                # Envelopper le code dans un bloc try-except pour une meilleure gestion d'erreur
                code_lines = code.split('\n')
                indented_code = '\n    '.join(code_lines)
                code = f"""
try:
    # Ajout d'un délai court pour stabiliser l'interface avant l'action
    await asyncio.sleep(0.5)
    {indented_code}
except Exception as e:
    # Essayer de récupérer de certaines erreurs courantes
    if "TimeoutError" in str(e) or "ElementNotFound" in str(e):
        # Attendre un peu plus et essayer de stabiliser la page
        await asyncio.sleep(1)
        await browser.wait_for_page_to_load()
        raise e
    else:
        raise e
"""
            
            # Préparation du code pour l'exécution
            exec_code = f"""
async def execute_action(browser):
    try:
{code.replace('\n', '\n        ')}
        return {{"success": True, "message": "Action exécutée avec succès (tentative {attempt})"}}
    except Exception as e:
        return {{"success": False, "message": f"Erreur: {{str(e)}}"}}
"""
            
            # Créer un environnement d'exécution avec notre browser et asyncio
            exec_globals = {"browser": browser, "asyncio": asyncio}
            
            # Exécuter le code pour définir la fonction
            exec(exec_code, exec_globals)
            
            # Appeler la fonction définie avec un timeout
            try:
                result = await asyncio.wait_for(exec_globals["execute_action"](browser), timeout=30)
            except asyncio.TimeoutError:
                result = {"success": False, "message": "Timeout lors de l'exécution de l'action"}
            
            if result["success"]:
                socketio.emit('log', {'type': 'success', 'message': result["message"]})
                
                # Capture d'écran après l'action pour voir le résultat
                try:
                    screenshot = await browser.screenshot()
                    screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                    socketio.emit('screenshot_update', {'screenshot': screenshot_base64})
                except:
                    # La capture d'écran n'est pas critique, on continue même en cas d'échec
                    socketio.emit('log', {'type': 'warning', 'message': "Impossible de prendre une capture d'écran"})
                
                return result
            else:
                # Action échouée
                error_msg = result["message"]
                socketio.emit('log', {'type': 'warning', 'message': f"Échec de l'action (tentative {attempt}/{max_attempts}): {error_msg}"})
                
                # Si c'est la dernière tentative, on capture quand même une capture d'écran pour le diagnostic
                if attempt == max_attempts:
                    try:
                        screenshot = await browser.screenshot()
                        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                        socketio.emit('screenshot_update', {'screenshot': screenshot_base64})
                    except:
                        pass
                
                # Si nous avons encore des tentatives, attendre un peu avant de réessayer
                if attempt < max_attempts:
                    await asyncio.sleep(2)  # Pause entre les tentatives
                else:
                    return result  # Échec final après toutes les tentatives
        except Exception as e:
            # Erreur au niveau du processus général
            error_message = f"Erreur lors de l'exécution du code (tentative {attempt}/{max_attempts}): {str(e)}"
            socketio.emit('log', {'type': 'error', 'message': error_message})
            
            if attempt < max_attempts:
                await asyncio.sleep(2)  # Pause entre les tentatives
            else:
                return {"success": False, "message": error_message}
    
    # Cette ligne ne devrait pas être atteinte normalement, mais par sécurité
    return {"success": False, "message": "Échec de l'action après plusieurs tentatives"}

async def analyze_results(task_description, test_results):
    """
    Analyse les résultats du test et génère un rapport.
    
    Args:
        task_description (str): Description de la tâche
        test_results (list): Liste des résultats des actions exécutées
    
    Returns:
        str: Rapport d'analyse
    """
    # Système prompt pour guider Claude à analyser les résultats
    system_prompt = """
    Vous êtes un analyste QA expert qui évalue les résultats de tests d'applications web.
    Votre tâche est d'analyser les résultats d'un test et de produire un rapport concis et informatif.
    
    Votre rapport doit inclure:
    1. Un résumé de la tâche de test
    2. Une évaluation du succès du test
    3. Des observations sur les problèmes rencontrés, le cas échéant
    4. Des recommandations pour améliorer le test ou l'application
    
    Utilisez un ton professionnel et factuel. Votre rapport doit être clair et utile pour l'équipe de développement.
    """
    
    # Construction du rapport de résultats
    results_report = "Résultats des actions:\n\n"
    for i, result in enumerate(test_results, 1):
        status = "✅ Succès" if result["success"] else "❌ Échec"
        results_report += f"Action {i}: {status} - {result['message']}\n"
    
    # Construction du prompt pour analyser les résultats
    prompt = f"""
    Description de la tâche de test:
    {task_description}
    
    {results_report}
    
    Veuillez analyser ces résultats et produire un rapport de test.
    """
    
    # Invoquer Claude pour analyser les résultats
    report = invoke_claude(prompt, system_prompt)
    
    return report

@app.route('/claude_qa_request', methods=['POST'])
async def claude_qa_request():
    """Endpoint pour recevoir et traiter les demandes de test QA avec Claude et browser_use."""
    socketio.emit('log', {'type': 'info', 'message': "Traitement de la demande de test QA"})
    
    data = request.json
    webpage_url = data.get('url', '')
    user_input = data.get('input', '')
    
    if not webpage_url:
        return jsonify({'error': "L'URL de la page web est requise"})
    
    if not user_input:
        return jsonify({'error': "La description de la tâche est requise"})
    
    # Initialiser les variables de résultat
    test_results = []
    final_report = ""
    
    try:
        # Phase 1: Initialiser le navigateur
        with browser_lock:
            init_result = await initialize_browser()
            if not init_result:
                return jsonify({'error': "Échec de l'initialisation du navigateur"})
        
        # Phase 2: Analyser la tâche
        task_analysis = await extract_task_description(user_input)
        
        # Phase 3: Naviguer vers l'URL
        html = await navigate_to_url(webpage_url)
        if not html:
            await close_browser()
            return jsonify({'error': "Erreur lors de la navigation vers l'URL"})
        
        # Phase 4: Générer un plan d'actions à partir de l'analyse de la tâche
        action_plan_prompt = f"""
        Voici l'analyse d'une tâche de test QA:
        {task_analysis}
        
        Basé sur cette analyse, veuillez décomposer la tâche en une séquence d'actions spécifiques que je dois exécuter sur le navigateur.
        Chaque action doit être décrite en détail, étape par étape.
        
        Format de réponse souhaité:
        1. Action 1: [Description détaillée]
        2. Action 2: [Description détaillée]
        3. ...
        """
        
        action_plan = invoke_claude(action_plan_prompt)
        socketio.emit('action_plan', {'plan': action_plan})
        
        # Phase 5: Extraire les actions individuelles du plan
        actions = re.findall(r'\d+\.\s*Action\s*\d*\s*:\s*(.*?)(?=\d+\.\s*Action|\Z)', action_plan, re.DOTALL)
        if not actions:
            # Essai avec un format alternatif
            actions = re.findall(r'\d+\.\s*(.*?)(?=\d+\.\s*|\Z)', action_plan, re.DOTALL)
        
        # Si toujours pas d'actions, considérer le plan complet comme une seule action
        if not actions:
            actions = [action_plan]
        
        # Phase 6: Exécuter chaque action
        for i, action in enumerate(actions, 1):
            # Mettre à jour le HTML avant chaque action
            html = await browser.get_page_html()
            
            socketio.emit('log', {'type': 'info', 'message': f"Exécution de l'action {i}: {action.strip()}"})
            
            result = await execute_browser_action(action.strip(), html)
            test_results.append(result)
            
            # En cas d'échec, demander à Claude d'essayer une approche alternative
            if not result["success"]:
                retry_prompt = f"""
                J'ai essayé d'exécuter l'action suivante mais j'ai rencontré une erreur:
                {action.strip()}
                
                Erreur: {result["message"]}
                
                Voici le HTML actuel de la page:
                ```html
                {html}
                ```
                
                Pouvez-vous me donner une approche alternative pour accomplir cette action?
                Générez un code browser_use différent qui pourrait contourner ce problème.
                """
                
                retry_response = invoke_claude(retry_prompt, system_prompt=None)
                
                # Extraire le code alternatif
                retry_code_match = re.search(r'CODE:\s*(.*?)(?=\s*CODE:|$)', retry_response, re.DOTALL)
                if retry_code_match:
                    retry_code = retry_code_match.group(1).strip()
                    socketio.emit('log', {'type': 'retry', 'message': retry_code})
                    
                    # Tenter d'exécuter le code alternatif
                    exec_code = f"""
async def execute_retry_action(browser):
    try:
{retry_code.replace('await browser', 'await browser').replace('\n', '\n        ')}
        return {{"success": True, "message": "Action alternative exécutée avec succès"}}
    except Exception as e:
        return {{"success": False, "message": str(e)}}
"""
                    
                    exec_globals = {"browser": browser}
                    exec(exec_code, exec_globals)
                    
                    retry_result = await exec_globals["execute_retry_action"](browser)
                    test_results.append(retry_result)
                    
                    # Capture d'écran après l'action pour voir le résultat
                    screenshot = await browser.screenshot()
                    screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                    socketio.emit('screenshot_update', {'screenshot': screenshot_base64})
            
            # Après chaque action, vérifier si l'URL a changé
            current_url = await browser.get_current_url()
            if current_url != webpage_url:
                socketio.emit('log', {'type': 'info', 'message': f"Changement de page détecté: {current_url}"})
                webpage_url = current_url
                
                # Attendre que la page soit chargée
                await browser.wait_for_page_to_load()
        
        # Phase 7: Analyser les résultats
        final_report = await analyze_results(task_analysis, test_results)
        socketio.emit('test_report', {'report': final_report})
        
        # Phase 8: Fermer le navigateur
        await close_browser()
        
        # Préparation de la réponse complète
        response = {
            'url': webpage_url,
            'task': user_input,
            'analysis': task_analysis,
            'action_plan': action_plan,
            'results': test_results,
            'report': final_report
        }
        
        socketio.emit('log', {'type': 'success', 'message': "Test QA terminé avec succès"})
        socketio.emit('test_complete')
        
        return jsonify(response)
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande QA: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        
        # S'assurer que le navigateur est fermé en cas d'erreur
        if browser:
            await close_browser()
        
        return jsonify({'error': error_message})

@app.route('/qa_claude_request', methods=['POST'])
async def qa_claude_request():
    # Log explicite ajouté ici
    with open('/home/adrien.parrochia/go/src/github.com/agentsIA/logs/qaclaude.log', 'a') as log_file:
        log_file.write("2025-03-18 [INFO] Traitement de la requête QA en cours...\n")

    # Log explicite ajouté ici
    with open('/home/adrien.parrochia/go/src/github.com/agentsIA/logs/qaclaude.log', 'a') as log_file:
        log_file.write("2025-03-18 [INFO] Traitement de la requête QA en cours...\n")

    """
    Endpoint pour recevoir les demandes de test QA de l'agent Chef de Projet.
    Utilise Claude Sonnet via Bedrock et browser_use pour effectuer des tests automatisés.
    """
    socketio.emit('log', {'type': 'info', 'message': "Réception d'une demande de l'agent Chef de Projet"})
    
    data = request.json
    webpage_url = data.get('url', '')
    user_input = data.get('input', '')
    
    if not webpage_url:
        return jsonify({'error': "L'URL de la page web est requise"})
    
    if not user_input:
        return jsonify({'error': "La description de la tâche est requise"})
    
    # Initialiser les variables de résultat
    test_results = []
    final_report = ""
    
    try:
        # Phase 1: Initialiser le navigateur
        with browser_lock:
            init_result = await initialize_browser()
            if not init_result:
                return jsonify({'error': "Échec de l'initialisation du navigateur"})
        
        # Phase 2: Analyser la tâche
        task_analysis = await extract_task_description(user_input)
        
        # Phase 3: Naviguer vers l'URL
        html = await navigate_to_url(webpage_url)
        if not html:
            await close_browser()
            return jsonify({'error': "Erreur lors de la navigation vers l'URL"})
        
        # Phase 4: Générer un plan d'actions à partir de l'analyse de la tâche
        action_plan_prompt = f"""
        Voici l'analyse d'une tâche de test QA:
        {task_analysis}
        
        Basé sur cette analyse, veuillez décomposer la tâche en une séquence d'actions spécifiques que je dois exécuter sur le navigateur.
        Chaque action doit être décrite en détail, étape par étape.
        
        Format de réponse souhaité:
        1. Action 1: [Description détaillée]
        2. Action 2: [Description détaillée]
        3. ...
        """
        
        action_plan = invoke_claude(action_plan_prompt)
        socketio.emit('action_plan', {'plan': action_plan})
        
        # Phase 5: Extraire les actions individuelles du plan
        actions = re.findall(r'\d+\.\s*Action\s*\d*\s*:\s*(.*?)(?=\d+\.\s*Action|\Z)', action_plan, re.DOTALL)
        if not actions:
            # Essai avec un format alternatif
            actions = re.findall(r'\d+\.\s*(.*?)(?=\d+\.\s*|\Z)', action_plan, re.DOTALL)
        
        # Si toujours pas d'actions, considérer le plan complet comme une seule action
        if not actions:
            actions = [action_plan]
        
        # Phase 6: Exécuter chaque action
        for i, action in enumerate(actions, 1):
            # Mettre à jour le HTML avant chaque action
            html = await browser.get_page_html()
            
            socketio.emit('log', {'type': 'info', 'message': f"Exécution de l'action {i}: {action.strip()}"})
            
            result = await execute_browser_action(action.strip(), html)
            test_results.append(result)
            
            # En cas d'échec, demander à Claude d'essayer une approche alternative
            if not result["success"]:
                retry_prompt = f"""
                J'ai essayé d'exécuter l'action suivante mais j'ai rencontré une erreur:
                {action.strip()}
                
                Erreur: {result["message"]}
                
                Voici le HTML actuel de la page:
                ```html
                {html}
                ```
                
                Pouvez-vous me donner une approche alternative pour accomplir cette action?
                Générez un code browser_use différent qui pourrait contourner ce problème.
                """
                
                retry_response = invoke_claude(retry_prompt, system_prompt=None)
                
                # Extraire le code alternatif
                retry_code_match = re.search(r'CODE:\s*(.*?)(?=\s*CODE:|$)', retry_response, re.DOTALL)
                if retry_code_match:
                    retry_code = retry_code_match.group(1).strip()
                    socketio.emit('log', {'type': 'retry', 'message': retry_code})
                    
                    # Tenter d'exécuter le code alternatif
                    exec_code = f"""
async def execute_retry_action(browser):
    try:
{retry_code.replace('await browser', 'await browser').replace('\n', '\n        ')}
        return {{"success": True, "message": "Action alternative exécutée avec succès"}}
    except Exception as e:
        return {{"success": False, "message": str(e)}}
"""
                    
                    exec_globals = {"browser": browser}
                    exec(exec_code, exec_globals)
                    
                    retry_result = await exec_globals["execute_retry_action"](browser)
                    test_results.append(retry_result)
                    
                    # Capture d'écran après l'action pour voir le résultat
                    screenshot = await browser.screenshot()
                    screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                    socketio.emit('screenshot_update', {'screenshot': screenshot_base64})
            
            # Après chaque action, vérifier si l'URL a changé
            current_url = await browser.get_current_url()
            if current_url != webpage_url:
                socketio.emit('log', {'type': 'info', 'message': f"Changement de page détecté: {current_url}"})
                webpage_url = current_url
                
                # Attendre que la page soit chargée
                await browser.wait_for_page_to_load()
        
        # Phase 7: Analyser les résultats
        final_report = await analyze_results(task_analysis, test_results)
        socketio.emit('test_report', {'report': final_report})
        
        # Phase 8: Fermer le navigateur
        await close_browser()
        
        # Préparation de la réponse complète pour l'agent Chef de Projet
        response = {
            'url': webpage_url,
            'task': user_input,
            'analysis': task_analysis,
            'action_plan': action_plan,
            'results': test_results,
            'report': final_report,
            'status': 'success'
        }
        
        socketio.emit('log', {'type': 'success', 'message': "Test QA terminé avec succès"})
        socketio.emit('test_complete')
        
        return jsonify(response)
    
    except Exception as e:
        error_message = f"Erreur lors du traitement de la demande QA: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        
        # S'assurer que le navigateur est fermé en cas d'erreur
        if browser:
            await close_browser()
        
        return jsonify({'error': error_message, 'status': 'error'})

def run_async_task(coroutine):
    """Exécute une coroutine async dans le contexte d'une application Flask."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(coroutine)
    loop.close()
    return result

# Adapter les routes Flask pour exécuter des coroutines async
@app.route('/qa_request', methods=['POST'])
def qa_request():
    """Wrapper pour exécuter la fonction async claude_qa_request."""
    return run_async_task(claude_qa_request())

@app.route('/qa_api_request', methods=['POST'])
def qa_api_request():
    # Log explicite ajouté ici
    with open('/home/adrien.parrochia/go/src/github.com/agentsIA/logs/qaclaude.log', 'a') as log_file:
        log_file.write("2025-03-18 [INFO] Requête QA reçue via l'API\n")
    # Log explicite ajouté ici
    with open('/home/adrien.parrochia/go/src/github.com/agentsIA/logs/qaclaude.log', 'a') as log_file:
        log_file.write("2025-03-18 [INFO] Requête QA reçue via l'API\n")
    """Wrapper pour exécuter la fonction async qa_claude_request pour les appels API."""
    return run_async_task(qa_claude_request())

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5002, allow_unsafe_werkzeug=True)


@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent qaclaude"})
    
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
            log_path = os.path.join(log_dir, 'qaclaude.log')
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
    
    # Démarrer le serveur Flask avec SocketIO
    start_socketio()