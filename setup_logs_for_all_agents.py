#!/usr/bin/env python3
import os
import re
import sys
import glob

# Fonction pour obtenir le nom de l'agent à partir du chemin du répertoire
def get_agent_name(agent_dir):
    # Extraire le nom du répertoire
    dir_name = os.path.basename(agent_dir)
    # Convertir en nom plus lisible
    agent_name = re.sub(r'agent([A-Z])', r'agent_\1', dir_name).lower()
    # Supprimer le préfixe 'agent_' si présent
    agent_name = agent_name.replace('agent', '')
    return agent_name.strip('_')

# Fonction pour ajouter le code de configuration des logs
def add_logs_configuration(app_file, agent_name):
    with open(app_file, 'r') as f:
        content = f.read()
    
    # Vérifier si le code de configuration des logs est déjà présent
    if "# Configuration des logs" in content:
        print(f"Configuration des logs déjà présente dans {app_file}")
        return False
    
    # Rechercher l'import Flask
    flask_import_match = re.search(r'from flask import (.*)', content)
    if not flask_import_match:
        print(f"Impossible de trouver l'import Flask dans {app_file}")
        return False
    
    # Ajouter les imports nécessaires pour les logs
    log_imports = """import logging
import re
import time
"""
    
    # Position pour insérer les imports
    import_pos = content.find("import")
    if import_pos == -1:
        print(f"Impossible de trouver la position d'insertion des imports dans {app_file}")
        return False
    
    # Ajouter les imports
    content = content[:import_pos] + log_imports + content[import_pos:]
    
    # Configuration des logs
    logs_config = f"""
# Configuration des logs
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, '{agent_name}.log')

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
"""
    
    # Déterminer où ajouter la configuration des logs
    flask_app_def = re.search(r'app = Flask\(__name__\)', content)
    if flask_app_def:
        # Insérer avant l'initialisation de l'app Flask
        pos = flask_app_def.start()
        content = content[:pos] + logs_config + content[pos:]
    else:
        # Si on ne trouve pas l'initialisation de Flask, ajouter après les imports
        end_imports = max(content.rfind("import ") + 20, content.rfind("from ") + 20)
        content = content[:end_imports] + "\n" + logs_config + content[end_imports:]
    
    # Remplacer les print() par logger.info()
    content = re.sub(r'print\((.*?)\)', r'logger.info(\1)', content)
    
    # Ajouter la fonction safe_emit
    safe_emit_func = """
def safe_emit(event, data=None):
    \"\"\"
    Émet un événement SocketIO de manière sécurisée, en capturant les erreurs potentielles.
    
    Args:
        event (str): Nom de l'événement à émettre
        data (dict, optional): Données à envoyer avec l'événement
    \"\"\"
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
"""
    
    # Ajouter après l'initialisation de SocketIO, si elle existe
    socketio_init = re.search(r'socketio = SocketIO\(.*?\)', content)
    if socketio_init:
        pos = socketio_init.end()
        content = content[:pos] + "\n" + safe_emit_func + content[pos:]
    else:
        # Sinon, ajouter à la fin du fichier
        content += "\n" + safe_emit_func
    
    # Ajouter les gestionnaires d'événements Socket.IO
    socketio_handlers = """
@socketio.on('connect')
def handle_connect():
    \"\"\"Gestionnaire d'événement de connexion client.\"\"\"
    try:
        client_id = request.sid
        logger.info(f"Client connecté: {client_id}")
        
        # Envoyer un message de bienvenue
        safe_emit('log', {'type': 'info', 'message': f"Connexion établie avec l'agent {agent_name}"})
    
    except Exception as e:
        logger.error(f"Erreur lors de la gestion de la connexion: {str(e)}")

@socketio.on('request_logs')
def handle_request_logs():
    \"\"\"Gestionnaire d'événement pour la demande de logs\"\"\"
    try:
        logger.info("Demande de logs reçue")
        # Envoyer un accusé de réception
        safe_emit('log', {'type': 'info', 'message': "Chargement des logs en cours..."})
        
        # Lire les dernières entrées du fichier de log pour les afficher dans l'interface
        try:
            log_path = os.path.join(log_dir, '{agent_name}.log')
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
                        message_match = re.search(r'\\[(INFO|ERROR|WARNING)\\]\\s*(.*)', line)
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
"""
    
    # Remplacer les {agent_name} par le vrai nom de l'agent
    socketio_handlers = socketio_handlers.replace('{agent_name}', agent_name)
    
    # Ajouter l'import de request s'il n'existe pas
    if "from flask import" in content and "request" not in content.split("from flask import")[1].split("\n")[0]:
        content = re.sub(r'from flask import (.*)', r'from flask import \1, request', content)
    
    # Ajouter les gestionnaires d'événements à la fin du fichier, avant le bloc if __name__ == "__main__"
    main_block = re.search(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]', content)
    if main_block:
        pos = main_block.start()
        content = content[:pos] + socketio_handlers + "\n" + content[pos:]
    else:
        # Sinon, ajouter à la fin du fichier
        content += "\n" + socketio_handlers
    
    # Écrire le contenu modifié
    with open(app_file, 'w') as f:
        f.write(content)
    
    print(f"Configuration des logs ajoutée dans {app_file}")
    return True

# Fonction pour mettre à jour le template HTML
def update_html_template(template_file):
    with open(template_file, 'r') as f:
        content = f.read()
    
    # Vérifier si le code d'affichage des logs est déjà présent
    if "socket.emit('request_logs')" in content:
        print(f"Code d'affichage des logs déjà présent dans {template_file}")
        return False
    
    # Ajouter le conteneur de logs s'il n'existe pas
    if '<div id="log-container"' not in content:
        # Chercher où insérer le conteneur de logs
        body_tag = re.search(r'<body[^>]*>', content)
        if body_tag:
            # Insérer après la balise body
            pos = body_tag.end()
            log_container_html = """
    <div class="container mt-4">
        <h3>Logs:</h3>
        <div class="log-container" id="log-container" style="height: 250px; overflow-y: auto; background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 4px; padding: 10px; margin-bottom: 20px; font-family: 'Courier New', monospace;"></div>
    </div>
"""
            content = content[:pos] + log_container_html + content[pos:]
        else:
            print(f"Balise <body> non trouvée dans {template_file}")
            return False
    
    # Ajouter les styles CSS pour les logs
    head_tag = re.search(r'</head>', content)
    if head_tag:
        # Insérer avant la fin du head
        pos = head_tag.start()
        log_styles = """
    <style>
        .log-info { color: #0c5460; }
        .log-error { color: #721c24; }
        .log-success { color: #155724; }
        .log-warning { color: #856404; }
    </style>
"""
        content = content[:pos] + log_styles + content[pos:]
    else:
        print(f"Balise </head> non trouvée dans {template_file}")
    
    # Ajouter le code Socket.IO pour gérer les logs
    script_tag = re.search(r'<script[^>]*>\s*', content)
    if script_tag:
        # Chercher où insérer le code Socket.IO
        socket_io_init = re.search(r'const socket\s*=\s*io\(', content)
        if socket_io_init:
            # Chercher le gestionnaire de connexion
            connect_handler = re.search(r'socket\.on\([\'"]connect[\'"]', content)
            if connect_handler:
                # Chercher la fin du gestionnaire de connexion
                connect_end = re.search(r'}\);', content[connect_handler.start():])
                if connect_end:
                    pos = connect_handler.start() + connect_end.end()
                    log_handlers = """
    
    // Gestionnaire d'événements pour les logs
    socket.on('log', function(data) {
        console.log('Log reçu:', data.type, data.message);
        addLog(data.type, data.message);
    });
    
    // Au moment de la connexion, demander les logs précédents
    socket.on('connect', function() {
        console.log('Connexion Socket.IO établie');
        socket.emit('request_logs');
    });
    
    // Fonction pour ajouter un log
    function addLog(type, message) {
        const logContainer = document.getElementById('log-container');
        if (!logContainer) {
            console.error("Élément 'log-container' non trouvé");
            return;
        }
        const logEntry = document.createElement('div');
        logEntry.className = `log-${type}`;
        logEntry.textContent = message;
        logContainer.appendChild(logEntry);
        logContainer.scrollTop = logContainer.scrollHeight;
    }
"""
                    content = content[:pos] + log_handlers + content[pos:]
                else:
                    print(f"Fin du gestionnaire de connexion non trouvée dans {template_file}")
            else:
                # Si pas de gestionnaire de connexion, ajouter après l'initialisation de Socket.IO
                socket_io_end = re.search(r';', content[socket_io_init.end():])
                if socket_io_end:
                    pos = socket_io_init.end() + socket_io_end.end()
                    log_handlers = """
    
    // Gestionnaire d'événements pour les logs
    socket.on('log', function(data) {
        console.log('Log reçu:', data.type, data.message);
        addLog(data.type, data.message);
    });
    
    // Au moment de la connexion, demander les logs précédents
    socket.on('connect', function() {
        console.log('Connexion Socket.IO établie');
        socket.emit('request_logs');
    });
    
    // Fonction pour ajouter un log
    function addLog(type, message) {
        const logContainer = document.getElementById('log-container');
        if (!logContainer) {
            console.error("Élément 'log-container' non trouvé");
            return;
        }
        const logEntry = document.createElement('div');
        logEntry.className = `log-${type}`;
        logEntry.textContent = message;
        logContainer.appendChild(logEntry);
        logContainer.scrollTop = logContainer.scrollHeight;
    }
"""
                    content = content[:pos] + log_handlers + content[pos:]
                else:
                    print(f"Fin de l'initialisation de Socket.IO non trouvée dans {template_file}")
        else:
            # Si pas d'initialisation de Socket.IO, ajouter à la fin du script
            end_script = re.search(r'</script>', content)
            if end_script:
                pos = end_script.start()
                socket_io_code = """
    // Initialisation de Socket.IO
    const socket = io({
        transports: ['websocket', 'polling'],
        reconnection: true
    });
    
    // Gestionnaire d'événements pour les logs
    socket.on('log', function(data) {
        console.log('Log reçu:', data.type, data.message);
        addLog(data.type, data.message);
    });
    
    // Au moment de la connexion, demander les logs précédents
    socket.on('connect', function() {
        console.log('Connexion Socket.IO établie');
        socket.emit('request_logs');
    });
    
    // Fonction pour ajouter un log
    function addLog(type, message) {
        const logContainer = document.getElementById('log-container');
        if (!logContainer) {
            console.error("Élément 'log-container' non trouvé");
            return;
        }
        const logEntry = document.createElement('div');
        logEntry.className = `log-${type}`;
        logEntry.textContent = message;
        logContainer.appendChild(logEntry);
        logContainer.scrollTop = logContainer.scrollHeight;
    }
"""
                content = content[:pos] + socket_io_code + content[pos:]
            else:
                print(f"Balise </script> non trouvée dans {template_file}")
    else:
        # Si pas de balise script, en ajouter une à la fin du body
        end_body = re.search(r'</body>', content)
        if end_body:
            pos = end_body.start()
            script_code = """
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script>
        // Initialisation de Socket.IO
        const socket = io({
            transports: ['websocket', 'polling'],
            reconnection: true
        });
        
        // Gestionnaire d'événements pour les logs
        socket.on('log', function(data) {
            console.log('Log reçu:', data.type, data.message);
            addLog(data.type, data.message);
        });
        
        // Au moment de la connexion, demander les logs précédents
        socket.on('connect', function() {
            console.log('Connexion Socket.IO établie');
            socket.emit('request_logs');
        });
        
        // Fonction pour ajouter un log
        function addLog(type, message) {
            const logContainer = document.getElementById('log-container');
            if (!logContainer) {
                console.error("Élément 'log-container' non trouvé");
                return;
            }
            const logEntry = document.createElement('div');
            logEntry.className = `log-${type}`;
            logEntry.textContent = message;
            logContainer.appendChild(logEntry);
            logContainer.scrollTop = logContainer.scrollHeight;
        }
    </script>
"""
            content = content[:pos] + script_code + content[pos:]
        else:
            print(f"Balise </body> non trouvée dans {template_file}")
    
    # Écrire le contenu modifié
    with open(template_file, 'w') as f:
        f.write(content)
    
    print(f"Template HTML mis à jour dans {template_file}")
    return True

# Fonction principale
def main():
    # Créer le répertoire logs s'il n'existe pas
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # Trouver tous les répertoires d'agents
    base_dir = os.path.dirname(os.path.abspath(__file__))
    agent_dirs = [d for d in glob.glob(os.path.join(base_dir, 'agent*')) if os.path.isdir(d)]
    
    print(f"Trouvé {len(agent_dirs)} répertoires d'agents")
    
    for agent_dir in agent_dirs:
        agent_name = get_agent_name(agent_dir)
        print(f"\nTraitement de l'agent {agent_name} ({agent_dir})")
        
        # Chercher le fichier app.py
        app_file = os.path.join(agent_dir, 'python', 'app.py')
        if not os.path.exists(app_file):
            print(f"Fichier app.py non trouvé pour {agent_name}")
            continue
        
        # Ajouter la configuration des logs
        add_logs_configuration(app_file, agent_name)
        
        # Chercher le template HTML
        template_file = os.path.join(agent_dir, 'python', 'templates', 'index.html')
        if not os.path.exists(template_file):
            print(f"Template HTML non trouvé pour {agent_name}")
            continue
        
        # Mettre à jour le template HTML
        update_html_template(template_file)
    
    print("\nConfiguration des logs terminée pour tous les agents.")
    print("Redémarrez tous les agents avec 'make stop' puis 'make start' pour appliquer les modifications.")

if __name__ == "__main__":
    main()