#!/usr/bin/env python3
import json
import os
import subprocess
import re
import time
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Chemins vers les fichiers de stockage
TASKS_STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pending_tasks.json')
PROMPTS_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts_history.json')

# Définition des agents et leurs PIDs
AGENTS = {
    'chef-projet': {'name': 'Chef de Projet', 'pid_file': 'pids/chef_projet.pid'},
    'devops': {'name': 'DevOps CI/CD', 'pid_file': 'pids/devops.pid'},
    'dev-python': {'name': 'Développeur Python', 'pid_file': 'pids/dev_python.pid'},
    'dev-frontend': {'name': 'Développeur Frontend', 'pid_file': 'pids/dev_frontend.pid'},
    'dev-go': {'name': 'Développeur Go Backend', 'pid_file': 'pids/dev_go_backend.pid'},
    'dev-android': {'name': 'Développeur Android', 'pid_file': 'pids/dev_android.pid', 'exists': False},
    'dev-ios': {'name': 'Développeur iOS', 'pid_file': 'pids/dev_ios.pid', 'exists': False},
    'qa': {'name': 'QA', 'pid_file': 'pids/qa.pid'},
    'perf': {'name': 'Performance', 'pid_file': 'pids/perf.pid'},
    'analytics': {'name': 'Analytics & Monitoring', 'pid_file': 'pids/analytics.pid'},
    'communication': {'name': 'Communication & Social', 'pid_file': 'pids/communication_social.pid', 'exists': False},
    'ml': {'name': 'Machine Learning', 'pid_file': 'pids/ml.pid'},
    'product-owner': {'name': 'Product Owner', 'pid_file': 'pids/product_owner.pid'},
    'ux-designer': {'name': 'UX Designer', 'pid_file': 'pids/ux_designer.pid'}
}

@app.route('/')
def index():
    return send_from_directory('.', 'admin.html')

@app.route('/api/execute', methods=['POST'])
def execute_command():
    """Exécute une commande make"""
    data = request.json
    command = data.get('command', '')
    
    if not command:
        return jsonify({'success': False, 'message': 'Commande non spécifiée'}), 400
    
    try:
        # Exécuter la commande make
        make_cmd = f"make {command}"
        result = subprocess.run(make_cmd, shell=True, capture_output=True, text=True)
        
        # Vérifier le code de sortie
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': f'Commande exécutée avec succès: {make_cmd}',
                'stdout': result.stdout,
                'stderr': result.stderr
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erreur lors de l\'exécution de la commande: {make_cmd}',
                'stdout': result.stdout,
                'stderr': result.stderr
            })
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Exception: {str(e)}'}), 500

@app.route('/api/status')
def get_status():
    """Récupère l'état de tous les agents"""
    try:
        # Exécuter la commande make status
        result = subprocess.run("make status", shell=True, capture_output=True, text=True)
        
        # Analyser la sortie pour extraire l'état de chaque agent
        status_output = result.stdout
        agent_statuses = {}
        
        # Ajouter des logs pour le débogage
        print("Sortie de la commande 'make status':")
        print(status_output)
        
        # Parcourir les agents et extraire leur état
        for agent_id, agent_info in AGENTS.items():
            # Pattern regex pour extraire l'état de l'agent
            pattern = fr"- Agent {re.escape(agent_info['name'])}:\s+(.*?)($|\n)"
            match = re.search(pattern, status_output)
            
            # Si l'agent n'existe pas dans le système, marquer comme "inexistant"
            if agent_info.get('exists') is False:
                agent_statuses[agent_id] = "unknown"
                print(f"Agent {agent_id}: Marked as unknown (non-existent in system)")
                continue
                
            # Vérifier directement si le processus est en cours d'exécution
            pid_file_path = agent_info['pid_file']
            is_running = False
            
            if os.path.exists(pid_file_path):
                try:
                    with open(pid_file_path, 'r') as f:
                        pid = f.read().strip()
                        # Vérifier si le processus existe
                        try:
                            os.kill(int(pid), 0)  # Signal 0 pour vérifier si le processus existe
                            is_running = True
                        except (OSError, ValueError):
                            # Le processus n'existe pas ou PID invalide
                            pass
                except:
                    pass
            
            if is_running:
                # Le processus est en cours d'exécution, maintenant déterminer s'il est en pause
                if match and "EN PAUSE" in match.group(1):
                    agent_statuses[agent_id] = "paused"
                else:
                    agent_statuses[agent_id] = "running"
            else:
                agent_statuses[agent_id] = "stopped"
            
            # Ajouter un log pour le débogage
            print(f"Agent {agent_id}: Status = {agent_statuses[agent_id]}, PID file exists: {os.path.exists(pid_file_path)}")
        
        return jsonify({
            'success': True,
            'statuses': agent_statuses
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Exception: {str(e)}'}), 500

@app.route('/api/forward-request', methods=['POST'])
def forward_request():
    """Transmet une demande à l'agent Chef de Projet"""
    data = request.json
    
    try:
        import requests
        import socket
        from requests.exceptions import ConnectTimeout, ReadTimeout, ConnectionError
        
        # Vérifier si le service est accessible
        try:
            # Étape 1: Essayer de créer une connexion au socket pour vérifier si le service est disponible
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)  # Timeout court pour le test de connexion
            result = sock.connect_ex(('localhost', 5000))
            sock.close()
            
            if result != 0:
                # Le port n'est pas ouvert, le service n'est probablement pas disponible
                print(f"Chef de Projet service is not accessible on port 5000 (socket test result: {result})")
                return jsonify({
                    'success': False,
                    'message': 'L\'agent Chef de Projet n\'est pas accessible. Veuillez vérifier qu\'il est bien démarré.',
                    'details': 'Le port 5000 n\'est pas ouvert sur localhost.'
                }), 503  # Service Unavailable
                
            # Étape 2: Vérifier que le service répond correctement avec une requête de santé
            try:
                health_check_url = "http://localhost:5000/"
                health_check_response = requests.get(health_check_url, timeout=5)
                
                if health_check_response.status_code != 200:
                    print(f"Chef de Projet health check failed with status code: {health_check_response.status_code}")
                    return jsonify({
                        'success': False,
                        'message': 'L\'agent Chef de Projet est en cours d\'exécution mais ne répond pas correctement.',
                        'details': f'Le service a retourné le code d\'état {health_check_response.status_code}.'
                    }), 503
                    
                print(f"Chef de Projet health check passed with status code: {health_check_response.status_code}")
            except Exception as health_err:
                print(f"Chef de Projet health check error: {str(health_err)}")
                # Continuer malgré l'échec du health check car le socket est ouvert
                pass
                
        except Exception as sock_err:
            print(f"Error during socket test: {str(sock_err)}")
        
        # URL de l'agent Chef de Projet
        chef_projet_url = "http://localhost:5000/project_request"
        
        print(f"Sending request to Chef de Projet at {chef_projet_url}")
        print(f"Request data: {data}")
        
        # Envoyer la requête avec un délai d'attente très long (120 secondes)
        response = requests.post(chef_projet_url, json=data, timeout=120)
        
        # Vérifier la réponse
        if response.status_code == 200:
            print(f"Request to Chef de Projet succeeded with status {response.status_code}")
            return jsonify({
                'success': True,
                'message': 'Demande transmise avec succès',
                'response': response.json()
            })
        else:
            print(f"Request to Chef de Projet failed with status {response.status_code}")
            print(f"Response body: {response.text}")
            return jsonify({
                'success': False,
                'message': f'Erreur lors de la transmission de la demande: {response.status_code}',
                'details': response.text
            })
    
    except ConnectTimeout as ct:
        print(f"Connection timeout to Chef de Projet: {str(ct)}")
        return jsonify({
            'success': False, 
            'message': 'Délai de connexion à l\'agent Chef de Projet dépassé', 
            'details': 'Vérifiez que l\'agent est bien démarré et accessible.'
        }), 504  # Gateway Timeout
    
    except ReadTimeout as rt:
        print(f"Read timeout from Chef de Projet: {str(rt)}")
        return jsonify({
            'success': False, 
            'message': 'Délai de réponse de l\'agent Chef de Projet dépassé', 
            'details': 'L\'agent a pris trop de temps pour répondre ou est surchargé.'
        }), 504  # Gateway Timeout
    
    except ConnectionError as ce:
        print(f"Connection error to Chef de Projet: {str(ce)}")
        return jsonify({
            'success': False, 
            'message': 'Erreur de connexion à l\'agent Chef de Projet', 
            'details': f'Détails: {str(ce)}'
        }), 503  # Service Unavailable
    
    except Exception as e:
        print(f"Unexpected error during request to Chef de Projet: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Exception: {str(e)}',
            'details': 'Une erreur inattendue s\'est produite lors de la communication avec l\'agent Chef de Projet.'
        }), 500

# Gestion des tâches en attente
def load_pending_tasks():
    """Charge les tâches en attente depuis le fichier de stockage."""
    if os.path.exists(TASKS_STORE_FILE):
        try:
            with open(TASKS_STORE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Erreur lors du chargement des tâches en attente: {str(e)}")
    return []

def save_pending_tasks(tasks):
    """Sauvegarde les tâches en attente dans le fichier de stockage."""
    try:
        with open(TASKS_STORE_FILE, 'w') as f:
            json.dump(tasks, f, indent=2)
        return True
    except Exception as e:
        print(f"Erreur lors de la sauvegarde des tâches en attente: {str(e)}")
        return False

@app.route('/api/check-pending-tasks')
def check_pending_tasks():
    """Vérifie s'il y a des tâches en attente."""
    tasks = load_pending_tasks()
    return jsonify({
        'success': True,
        'pendingTasks': tasks
    })

@app.route('/api/resume-tasks', methods=['POST'])
def resume_tasks():
    """Reprend les tâches en attente."""
    tasks = load_pending_tasks()
    
    if not tasks:
        return jsonify({
            'success': False,
            'message': 'Aucune tâche en attente à reprendre'
        })
    
    try:
        # Envoi les tâches au Chef de Projet pour reprise
        import requests
        chef_projet_url = "http://localhost:5000/resume_tasks"
        
        # On passe toutes les tâches au Chef de Projet
        response = requests.post(chef_projet_url, json={'tasks': tasks}, timeout=30)
        
        if response.status_code == 200:
            # Ne pas effacer les tâches, elles seront mises à jour par les agents
            return jsonify({
                'success': True,
                'message': 'Tâches reprises avec succès',
                'details': response.json()
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Erreur lors de la reprise des tâches: {response.status_code}',
                'details': response.text
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Exception: {str(e)}'
        }), 500

@app.route('/api/clear-tasks', methods=['POST'])
def clear_tasks():
    """Efface les tâches en attente."""
    # Supprimer le fichier de tâches s'il existe
    if os.path.exists(TASKS_STORE_FILE):
        try:
            os.remove(TASKS_STORE_FILE)
            return jsonify({
                'success': True,
                'message': 'Tâches effacées avec succès'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Erreur lors de la suppression du fichier: {str(e)}'
            }), 500
    else:
        return jsonify({
            'success': True,
            'message': 'Aucune tâche à effacer'
        })

# Gestion de l'historique des prompts
def load_prompts_history():
    """Charge l'historique des prompts depuis le fichier de stockage."""
    if os.path.exists(PROMPTS_HISTORY_FILE):
        try:
            with open(PROMPTS_HISTORY_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Erreur lors du chargement de l'historique des prompts: {str(e)}")
    return []

def save_prompts_history(prompts):
    """Sauvegarde l'historique des prompts dans le fichier de stockage."""
    try:
        with open(PROMPTS_HISTORY_FILE, 'w') as f:
            json.dump(prompts, f, indent=2)
        return True
    except Exception as e:
        print(f"Erreur lors de la sauvegarde de l'historique des prompts: {str(e)}")
        return False

@app.route('/api/prompts-history', methods=['GET'])
def get_prompts_history():
    """Récupère l'historique des prompts."""
    prompts = load_prompts_history()
    return jsonify({
        'success': True,
        'prompts': prompts
    })

@app.route('/api/latest-prompt', methods=['GET'])
def get_latest_prompt():
    """Récupère le dernier prompt utilisé."""
    prompts = load_prompts_history()
    if prompts:
        return jsonify({
            'success': True,
            'prompt': prompts[-1]
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Aucun prompt dans l\'historique'
        })

# Modification de la route forward-request pour sauvegarder la tâche et le prompt
@app.route('/api/forward-request-with-save', methods=['POST'])
def forward_request_with_save():
    """Transmet une demande à l'agent Chef de Projet et sauvegarde la tâche et le prompt."""
    data = request.json
    
    # Sauvegarde de la tâche
    timestamp = int(time.time())
    task = {
        'id': str(timestamp),
        'description': data.get('description', 'Tâche sans description'),
        'data': data,
        'started_at': timestamp * 1000,  # Timestamp en millisecondes
        'status': 'pending'
    }
    
    tasks = load_pending_tasks()
    tasks.append(task)
    save_pending_tasks(tasks)
    
    # Sauvegarde du prompt dans l'historique
    prompt_entry = {
        'id': str(timestamp),
        'text': data.get('description', ''),
        'timestamp': timestamp * 1000,  # Timestamp en millisecondes
        'agents': [agent for agent in data.keys() if agent.startswith('launch_') and data[agent] is True],
        'project_name': data.get('project_name', ''),
        'app_url': data.get('app_url', '')
    }
    
    prompts = load_prompts_history()
    prompts.append(prompt_entry)
    # Limiter l'historique aux 50 derniers prompts
    if len(prompts) > 50:
        prompts = prompts[-50:]
    save_prompts_history(prompts)
    
    # Forward vers la méthode standard sans modification
    return forward_request()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)