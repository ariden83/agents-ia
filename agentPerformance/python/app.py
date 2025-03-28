import logging
import re
import time
import json
import re
import threading
import time
import base64
import os
import asyncio
import requests
from threading import Event
from urllib.parse import urlparse
from pathlib import Path
from dotenv import load_dotenv

import boto3
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from browser_use import Browser

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


# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'performance.log')

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

def invoke_claude(prompt, system_prompt=None, max_tokens=4096, temperature=0.7):
    """
    Invoque Claude via AWS Bedrock avec le prompt fourni.
    
    Args:
        prompt (str): Le prompt principal à envoyer au modèle
        system_prompt (str, optional): Instructions système pour guider le comportement du modèle
        max_tokens (int, optional): Nombre maximum de tokens pour la réponse
        temperature (float, optional): Niveau de créativité (0.0-1.0)
    
    Returns:
        str: Réponse du modèle
    """
    socketio.emit('loading_start')
    socketio.emit('log', {'type': 'info', 'message': "Invocation de Claude en cours..."})
    
    try:
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
        
        socketio.emit('log', {'type': 'success', 'message': "Réponse de Claude reçue"})
        socketio.emit('loading_end')
        
        return generated_text
    
    except Exception as e:
        error_message = f"Erreur lors de l'invocation de Claude: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        socketio.emit('loading_end')
        return error_message

async def initialize_browser():
    """Initialise l'instance du navigateur BrowserUse."""
    global browser
    
    socketio.emit('log', {'type': 'info', 'message': "Initialisation du navigateur..."})
    try:
        # Initialiser le navigateur avec Playwright en mode visible (headless=False)
        browser = await Browser.create(headless=True)
        socketio.emit('log', {'type': 'success', 'message': "Navigateur initialisé avec succès"})
        return True
    except Exception as e:
        error_message = f"Erreur lors de l'initialisation du navigateur: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return False

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

async def analyze_page_speed(url, device_type="desktop"):
    """
    Analyse la vitesse de chargement d'une page web en utilisant l'API PageSpeed Insights.
    
    Args:
        url (str): URL de la page à analyser
        device_type (str): Type d'appareil ('desktop' ou 'mobile')
    
    Returns:
        dict: Résultats de l'analyse
    """
    socketio.emit('log', {'type': 'info', 'message': f"Analyse de la vitesse de page pour: {url} ({device_type})"})
    
    try:
        # Utilisation de l'API PageSpeed Insights (version gratuite)
        api_url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}&strategy={device_type}"
        
        response = requests.get(api_url)
        
        if response.status_code == 200:
            results = response.json()
            socketio.emit('log', {'type': 'success', 'message': "Analyse PageSpeed Insights complétée"})
            return {
                'lighthouse_scores': results.get('lighthouseResult', {}).get('categories', {}),
                'load_metrics': results.get('lighthouseResult', {}).get('audits', {}).get('metrics', {}).get('details', {}).get('items', [{}])[0],
                'opportunities': results.get('lighthouseResult', {}).get('audits', {})
            }
        else:
            error_message = f"Erreur API PageSpeed: {response.status_code}"
            socketio.emit('log', {'type': 'error', 'message': error_message})
            return {"error": error_message}
    
    except Exception as e:
        error_message = f"Erreur lors de l'analyse PageSpeed: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

async def navigate_to_url(url):
    """
    Navigue vers l'URL spécifiée et collecte des métriques de performance.
    
    Args:
        url (str): URL à visiter
    
    Returns:
        dict: Métriques de performance collectées
    """
    global browser
    
    socketio.emit('log', {'type': 'info', 'message': f"Navigation vers: {url}"})
    
    try:
        # Configuration de la collecte des métriques de performance
        await browser.set_performance_metrics(enabled=True)
        
        # Naviguer vers l'URL
        await browser.goto(url)
        
        # Attendre que la page soit complètement chargée
        await browser.wait_for_page_to_load()
        
        # Capture d'écran pour référence
        screenshot = await browser.screenshot()
        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
        socketio.emit('screenshot_update', {'screenshot': screenshot_base64})
        
        # Collecter les métriques de performance
        perf_metrics = await browser.get_performance_metrics()
        
        # Exécuter des scripts pour obtenir des métriques supplémentaires
        timing_metrics = await browser.evaluate_javascript("""
        {
            const timing = performance.timing;
            const navigationStart = timing.navigationStart;
            return {
                loadTime: timing.loadEventEnd - navigationStart,
                domContentLoaded: timing.domContentLoadedEventEnd - navigationStart,
                firstPaint: performance.getEntriesByType('paint').find(entry => entry.name === 'first-paint')?.startTime,
                firstContentfulPaint: performance.getEntriesByType('paint').find(entry => entry.name === 'first-contentful-paint')?.startTime,
                resourcesCount: performance.getEntriesByType('resource').length,
                resourcesSize: performance.getEntriesByType('resource').reduce((total, resource) => total + resource.transferSize, 0) / 1024,
                scriptDuration: performance.getEntriesByType('resource')
                    .filter(resource => resource.initiatorType === 'script')
                    .reduce((total, script) => total + script.duration, 0),
                cssCount: performance.getEntriesByType('resource')
                    .filter(resource => resource.initiatorType === 'css').length,
                imageCount: performance.getEntriesByType('resource')
                    .filter(resource => resource.initiatorType === 'img').length,
                imageSize: performance.getEntriesByType('resource')
                    .filter(resource => resource.initiatorType === 'img')
                    .reduce((total, img) => total + img.transferSize, 0) / 1024
            };
        }
        """)
        
        # Collecter des informations sur le DOM
        dom_metrics = await browser.evaluate_javascript("""
        {
            return {
                domSize: document.querySelectorAll('*').length,
                scriptTags: document.querySelectorAll('script').length,
                stylesheetTags: document.querySelectorAll('link[rel="stylesheet"]').length,
                imageCount: document.querySelectorAll('img').length,
                iframeCount: document.querySelectorAll('iframe').length,
                domDepth: (function() {
                    let max = 0;
                    function getDepth(node, depth) {
                        if (!node) return depth;
                        max = Math.max(max, depth);
                        for (let child of node.children) {
                            getDepth(child, depth + 1);
                        }
                        return max;
                    }
                    return getDepth(document.documentElement, 0);
                })()
            };
        }
        """)
        
        # Combiner toutes les métriques
        combined_metrics = {
            "pageUrl": url,
            "performance": perf_metrics,
            "timing": timing_metrics,
            "dom": dom_metrics
        }
        
        socketio.emit('log', {'type': 'success', 'message': "Page chargée et métriques collectées"})
        return combined_metrics
    
    except Exception as e:
        error_message = f"Erreur lors de la navigation: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

async def analyze_resource_usage(url):
    """
    Analyse l'utilisation des ressources d'une page web.
    
    Args:
        url (str): URL de la page à analyser
    
    Returns:
        dict: Informations sur les ressources
    """
    global browser
    
    socketio.emit('log', {'type': 'info', 'message': f"Analyse des ressources pour: {url}"})
    
    try:
        # Naviguer vers l'URL si pas déjà fait
        current_url = await browser.get_current_url()
        if current_url != url:
            await browser.goto(url)
            await browser.wait_for_page_to_load()
        
        # Collecter des informations sur les ressources de la page
        resources = await browser.evaluate_javascript("""
        const resources = performance.getEntriesByType('resource').map(resource => {
            return {
                name: resource.name,
                type: resource.initiatorType,
                duration: Math.round(resource.duration),
                size: Math.round(resource.transferSize / 1024 * 100) / 100,
                startTime: Math.round(resource.startTime)
            };
        });
        return resources;
        """)
        
        # Organisation des ressources par type
        resource_types = {}
        for res in resources:
            res_type = res.get('type', 'other')
            if res_type not in resource_types:
                resource_types[res_type] = []
            resource_types[res_type].append(res)
        
        # Statistiques globales par type
        resource_stats = {}
        for res_type, res_list in resource_types.items():
            resource_stats[res_type] = {
                "count": len(res_list),
                "total_size_kb": sum(res.get('size', 0) for res in res_list),
                "total_duration_ms": sum(res.get('duration', 0) for res in res_list),
                "avg_duration_ms": sum(res.get('duration', 0) for res in res_list) / len(res_list) if len(res_list) > 0 else 0,
                "slowest_resources": sorted(res_list, key=lambda x: x.get('duration', 0), reverse=True)[:3]
            }
        
        socketio.emit('log', {'type': 'success', 'message': "Analyse des ressources terminée"})
        
        return {
            "resource_stats": resource_stats,
            "all_resources": resources
        }
    
    except Exception as e:
        error_message = f"Erreur lors de l'analyse des ressources: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

async def analyze_render_performance(url):
    """
    Analyse la performance de rendu d'une page web.
    
    Args:
        url (str): URL de la page à analyser
    
    Returns:
        dict: Informations sur la performance de rendu
    """
    global browser
    
    socketio.emit('log', {'type': 'info', 'message': f"Analyse de la performance de rendu pour: {url}"})
    
    try:
        # Naviguer vers l'URL si pas déjà fait
        current_url = await browser.get_current_url()
        if current_url != url:
            await browser.goto(url)
            await browser.wait_for_page_to_load()
        
        # Collecter des métriques de rendu
        render_metrics = await browser.evaluate_javascript("""
        const paintMetrics = performance.getEntriesByType('paint');
        const lcpEntries = performance.getEntriesByType('largest-contentful-paint');
        const layoutShiftEntries = performance.getEntriesByType('layout-shift');
        
        return {
            firstPaint: paintMetrics.find(entry => entry.name === 'first-paint')?.startTime,
            firstContentfulPaint: paintMetrics.find(entry => entry.name === 'first-contentful-paint')?.startTime,
            largestContentfulPaint: lcpEntries.length > 0 ? lcpEntries[lcpEntries.length - 1].startTime : null,
            cumulativeLayoutShift: layoutShiftEntries.reduce((total, entry) => total + entry.value, 0),
            longTasks: performance.getEntriesByType('longtask').map(task => {
                return {
                    duration: task.duration,
                    startTime: task.startTime
                };
            })
        };
        """)
        
        # Collecter des informations sur le "layout"
        layout_info = await browser.evaluate_javascript("""
        return {
            viewport: {
                width: window.innerWidth,
                height: window.innerHeight
            },
            reflows: (function() {
                let count = 0;
                const originalGetComputedStyle = window.getComputedStyle;
                window.getComputedStyle = function() {
                    count++;
                    return originalGetComputedStyle.apply(this, arguments);
                };
                
                // Forcer un petit nombre de reflows
                for (let i = 0; i < 5; i++) {
                    document.body.getBoundingClientRect();
                }
                
                window.getComputedStyle = originalGetComputedStyle;
                return count;
            })()
        };
        """)
        
        # Collecter des informations sur les animations
        animation_info = await browser.evaluate_javascript("""
        return {
            requestAnimationFrameCount: (function() {
                let count = 0;
                const original = window.requestAnimationFrame;
                window.requestAnimationFrame = function() {
                    count++;
                    return original.apply(this, arguments);
                };
                
                // Attendre un peu pour compter les RAF
                return new Promise(resolve => {
                    setTimeout(() => {
                        window.requestAnimationFrame = original;
                        resolve(count);
                    }, 1000);
                });
            })(),
            cssAnimationCount: document.querySelectorAll('*').length > 0 ? 
                Array.from(document.querySelectorAll('*')).filter(el => {
                    const style = window.getComputedStyle(el);
                    return style.animationName !== 'none' || style.transition !== 'none';
                }).length : 0
        };
        """)
        
        socketio.emit('log', {'type': 'success', 'message': "Analyse du rendu terminée"})
        
        return {
            "render_metrics": render_metrics,
            "layout_info": layout_info,
            "animation_info": animation_info
        }
    
    except Exception as e:
        error_message = f"Erreur lors de l'analyse du rendu: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

async def performance_audit(url, audit_name=None):
    """
    Effectue un audit de performance complet d'une page web.
    
    Args:
        url (str): URL de la page à analyser
        audit_name (str, optional): Nom de l'audit pour référence
    
    Returns:
        dict: Résultats complets de l'audit de performance
    """
    global browser
    
    audit_name = audit_name or f"Audit_{int(time.time())}"
    results = {
        "audit_name": audit_name,
        "url": url,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": {},
        "pagespeed": {},
        "resources": {},
        "render": {},
        "recommendations": None
    }
    
    try:
        socketio.emit('log', {'type': 'info', 'message': f"Démarrage de l'audit de performance pour {url}..."})
        
        # Phase 1: Initialiser le navigateur
        with browser_lock:
            init_result = await initialize_browser()
            if not init_result:
                return {"error": "Échec de l'initialisation du navigateur"}
        
        # Phase 2: Collecter les métriques de performance de base
        metrics = await navigate_to_url(url)
        results["metrics"] = metrics
        
        # Phase 3: Analyser les ressources
        resources = await analyze_resource_usage(url)
        results["resources"] = resources
        
        # Phase 4: Analyser le rendu
        render = await analyze_render_performance(url)
        results["render"] = render
        
        # Phase 5: Analyser avec PageSpeed Insights (desktop)
        pagespeed_desktop = await analyze_page_speed(url, "desktop")
        results["pagespeed"]["desktop"] = pagespeed_desktop
        
        # Phase 6: Analyser avec PageSpeed Insights (mobile)
        pagespeed_mobile = await analyze_page_speed(url, "mobile")
        results["pagespeed"]["mobile"] = pagespeed_mobile
        
        # Phase 7: Générer des recommandations avec Claude
        recommendations = await generate_recommendations(results)
        results["recommendations"] = recommendations
        
        socketio.emit('log', {'type': 'success', 'message': "Audit de performance terminé avec succès"})
        socketio.emit('audit_complete', {'audit_name': audit_name})
        
        # Phase 8: Fermer le navigateur
        await close_browser()
        
        return results
    
    except Exception as e:
        error_message = f"Erreur lors de l'audit de performance: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        
        # S'assurer que le navigateur est fermé en cas d'erreur
        if browser:
            await close_browser()
        
        return {"error": error_message}

async def run_stress_test(url, concurrent_users=10, duration_seconds=30):
    """
    Exécute un test de charge simple sur une URL.
    
    Args:
        url (str): URL à tester
        concurrent_users (int): Nombre d'utilisateurs simultanés simulés
        duration_seconds (int): Durée du test en secondes
    
    Returns:
        dict: Résultats du test de charge
    """
    socketio.emit('log', {'type': 'info', 'message': f"Démarrage du test de charge: {concurrent_users} utilisateurs pendant {duration_seconds}s"})
    
    try:
        async def load_page():
            try:
                start_time = time.time()
                response = requests.get(url)
                response_time = time.time() - start_time
                return {
                    "status_code": response.status_code,
                    "response_time": response_time,
                    "content_size": len(response.content)
                }
            except Exception as e:
                return {"error": str(e)}
        
        results = []
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        # Créer un pool de tâches pour simuler des utilisateurs concurrents
        tasks = []
        current_time = time.time()
        
        while current_time < end_time:
            if len(tasks) < concurrent_users:
                # Ajouter de nouvelles tâches jusqu'à atteindre le nombre d'utilisateurs concurrents
                while len(tasks) < concurrent_users:
                    tasks.append(asyncio.create_task(load_page()))
                    
            # Vérifier les tâches terminées
            completed_tasks = []
            for task in tasks:
                if task.done():
                    results.append(task.result())
                    completed_tasks.append(task)
            
            # Retirer les tâches terminées de la liste
            for task in completed_tasks:
                tasks.remove(task)
            
            # Petite pause pour éviter de surcharger le CPU
            await asyncio.sleep(0.1)
            current_time = time.time()
        
        # Attendre que toutes les tâches restantes se terminent
        for task in tasks:
            if not task.done():
                try:
                    results.append(await task)
                except Exception as e:
                    results.append({"error": str(e)})
        
        # Analyser les résultats
        total_requests = len(results)
        successful_requests = sum(1 for r in results if "status_code" in r and 200 <= r["status_code"] < 400)
        failed_requests = total_requests - successful_requests
        
        if successful_requests > 0:
            avg_response_time = sum(r.get("response_time", 0) for r in results if "response_time" in r) / successful_requests
            min_response_time = min((r.get("response_time", float('inf')) for r in results if "response_time" in r), default=0)
            max_response_time = max((r.get("response_time", 0) for r in results if "response_time" in r), default=0)
        else:
            avg_response_time = min_response_time = max_response_time = 0
        
        stress_results = {
            "url": url,
            "concurrent_users": concurrent_users,
            "duration_seconds": duration_seconds,
            "total_requests": total_requests,
            "requests_per_second": total_requests / duration_seconds,
            "successful_requests": successful_requests,
            "failed_requests": failed_requests,
            "success_rate": (successful_requests / total_requests) * 100 if total_requests > 0 else 0,
            "avg_response_time": avg_response_time,
            "min_response_time": min_response_time,
            "max_response_time": max_response_time
        }
        
        socketio.emit('log', {'type': 'success', 'message': f"Test de charge terminé - {successful_requests}/{total_requests} requêtes réussies"})
        return stress_results
    
    except Exception as e:
        error_message = f"Erreur lors du test de charge: {str(e)}"
        socketio.emit('log', {'type': 'error', 'message': error_message})
        return {"error": error_message}

async def generate_recommendations(audit_results):
    """
    Génère des recommandations d'optimisation de performance basées sur les résultats d'audit.
    
    Args:
        audit_results (dict): Résultats complets de l'audit de performance
    
    Returns:
        dict: Recommandations d'optimisation
    """
    socketio.emit('log', {'type': 'info', 'message': "Génération des recommandations d'optimisation..."})
    
    # Système prompt pour guider Claude à analyser les résultats
    system_prompt = """
    Vous êtes un expert en performance web qui analyse les résultats d'audits de performance pour fournir
    des recommandations d'optimisation actionables. Votre expertise comprend:
    
    1. L'optimisation du chargement initial (First Paint, First Contentful Paint, Largest Contentful Paint)
    2. La réduction des ressources (bundling, minification, compression d'images)
    3. L'optimisation de rendu (éviter les reflows, optimiser CSS, utiliser des animations efficaces)
    4. L'amélioration des scores PageSpeed Insights
    5. L'optimisation pour desktop et mobile
    
    Votre réponse doit être structurée en plusieurs sections:
    
    1. Résumé de performance - Une synthèse concise des performances actuelles du site
    2. Points forts - Ce qui est déjà bien optimisé
    3. Problèmes critiques - Les problèmes de performance les plus importants à résoudre en priorité
    4. Recommandations détaillées - Des conseils précis pour chaque aspect (chargement, ressources, rendu, etc.)
    5. Plan d'action - Une liste d'actions prioritaires, du plus important au moins important
    
    Pour chaque recommandation, précisez:
    - Le problème identifié
    - L'impact sur la performance
    - Une solution concrète avec des exemples de mise en œuvre si possible
    
    Vos recommandations doivent être pratiques, précises et immédiatement applicables par un développeur.
    """
    
    # Filtrer et formater les données pertinentes pour l'analyse
    filtered_data = {}
    
    # Inclure les métriques clés
    if "metrics" in audit_results and not isinstance(audit_results["metrics"], str):
        metrics = audit_results["metrics"]
        if "timing" in metrics:
            filtered_data["timing"] = metrics["timing"]
        if "dom" in metrics:
            filtered_data["dom"] = metrics["dom"]
    
    # Inclure les statistiques de ressources
    if "resources" in audit_results and "resource_stats" in audit_results["resources"]:
        filtered_data["resources"] = audit_results["resources"]["resource_stats"]
    
    # Inclure les métriques de rendu
    if "render" in audit_results and "render_metrics" in audit_results["render"]:
        filtered_data["render"] = audit_results["render"]["render_metrics"]
    
    # Inclure les résultats PageSpeed
    if "pagespeed" in audit_results:
        pagespeed = audit_results["pagespeed"]
        filtered_data["pagespeed"] = {
            "desktop": pagespeed.get("desktop", {}).get("lighthouse_scores", {}),
            "mobile": pagespeed.get("mobile", {}).get("lighthouse_scores", {})
        }
    
    # Construction du prompt pour l'analyse
    prompt = f"""
    Voici les résultats d'un audit de performance pour le site web: {audit_results.get('url', 'URL non spécifiée')}
    
    Métriques de timing et DOM:
    ```json
    {json.dumps(filtered_data.get('timing', {}), indent=2)}
    {json.dumps(filtered_data.get('dom', {}), indent=2)}
    ```
    
    Statistiques des ressources:
    ```json
    {json.dumps(filtered_data.get('resources', {}), indent=2)}
    ```
    
    Métriques de rendu:
    ```json
    {json.dumps(filtered_data.get('render', {}), indent=2)}
    ```
    
    Scores PageSpeed Insights:
    ```json
    {json.dumps(filtered_data.get('pagespeed', {}), indent=2)}
    ```
    
    Veuillez analyser ces données et fournir des recommandations détaillées pour optimiser la performance de ce site web.
    """
    
    # Invocation de Claude
    recommendations = invoke_claude(prompt, system_prompt)
    socketio.emit('log', {'type': 'success', 'message': "Recommandations générées avec succès"})
    
    return recommendations

def run_async_task(coroutine):
    """Exécute une coroutine async dans le contexte d'une application Flask."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(coroutine)
    loop.close()
    return result

@app.route('/performance_request', methods=['POST'])
def performance_request():
    """Endpoint pour recevoir et traiter les demandes d'audit de performance."""
    data = request.json
    url = data.get('url', '')
    audit_name = data.get('audit_name', None)
    
    if not url:
        return jsonify({'error': "L'URL de la page web est requise"})
    
    # Valider l'URL
    try:
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            return jsonify({'error': "URL invalide"})
    except:
        return jsonify({'error': "URL mal formée"})
    
    # Exécuter l'audit de performance
    return jsonify(run_async_task(performance_audit(url, audit_name)))

@app.route('/stress_test', methods=['POST'])
def stress_test():
    """Endpoint pour recevoir et traiter les demandes de test de charge."""
    data = request.json
    url = data.get('url', '')
    concurrent_users = int(data.get('concurrent_users', 10))
    duration_seconds = int(data.get('duration_seconds', 30))
    
    if not url:
        return jsonify({'error': "L'URL de la page web est requise"})
    
    # Valider les paramètres
    if concurrent_users <= 0 or concurrent_users > 100:
        return jsonify({'error': "Le nombre d'utilisateurs simultanés doit être entre 1 et 100"})
    
    if duration_seconds <= 0 or duration_seconds > 300:
        return jsonify({'error': "La durée du test doit être entre 1 et 300 secondes"})
    
    # Exécuter le test de charge
    return jsonify(run_async_task(run_stress_test(url, concurrent_users, duration_seconds)))

@app.route('/api/performance_audit', methods=['POST'])
def api_performance_audit():
    """API endpoint pour les demandes d'audit de performance provenant d'autres agents."""
    data = request.json
    url = data.get('url', '')
    audit_type = data.get('audit_type', 'full')  # full, basic, pagespeed
    
    if not url:
        return jsonify({'error': "L'URL de la page web est requise", 'status': 'error'})
    
    socketio.emit('log', {'type': 'info', 'message': f"Réception d'une demande d'API pour {url} (type: {audit_type})"})
    
    # Exécuter l'audit approprié en fonction du type
    if audit_type == 'full':
        results = run_async_task(performance_audit(url))
    elif audit_type == 'pagespeed':
        # Exécuter seulement l'analyse PageSpeed
        desktop_results = run_async_task(analyze_page_speed(url, 'desktop'))
        mobile_results = run_async_task(analyze_page_speed(url, 'mobile'))
        results = {
            'url': url,
            'pagespeed': {
                'desktop': desktop_results,
                'mobile': mobile_results
            }
        }
    else:  # basic
        # Initialiser le navigateur et collecter les métriques de base
        init_result = run_async_task(initialize_browser())
        if not init_result:
            return jsonify({'error': "Échec de l'initialisation du navigateur", 'status': 'error'})
        
        metrics = run_async_task(navigate_to_url(url))
        run_async_task(close_browser())
        results = {
            'url': url,
            'metrics': metrics
        }
    
    # Formatter les résultats pour les autres agents
    if 'error' in results:
        return jsonify({'error': results['error'], 'status': 'error'})
    else:
        return jsonify({
            'url': url,
            'results': results,
            'status': 'success'
        })

def start_socketio():
    """Démarre le serveur SocketIO en arrière-plan."""
    socketio.run(app, debug=True, use_reloader=False, port=5004, allow_unsafe_werkzeug=True)


@socketio.on('connect')
def handle_connect():
    """Gestionnaire d'événement de connexion client."""
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent performance"})
    
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
            log_path = os.path.join(log_dir, 'performance.log')
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