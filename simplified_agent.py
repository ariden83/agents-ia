#!/usr/bin/env python
"""
Script simplifié pour tester la communication entre agents.
Ce script implémente un serveur Flask basique qui reçoit les demandes
et les transmet directement à l'agent développeur Go.
"""

import json
import requests
import logging
from flask import Flask, request, jsonify

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
GO_BACKEND_URL = "http://localhost:5001/go_code_request"

app = Flask(__name__)

@app.route('/')
def index():
    return "Agent Chef de Projet simplifié - OK"

@app.route('/project_request', methods=['POST'])
def project_request():
    """Endpoint simplifié pour recevoir et traiter les demandes de projet"""
    logger.info("Traitement de la demande de projet")
    
    try:
        # Récupérer les données de la requête
        data = request.json
        if not data:
            logger.warning("Aucune donnée reçue dans la requête")
            return jsonify({
                "success": False,
                "error": "Aucune donnée reçue"
            })
        
        # Extraire les informations nécessaires
        project_name = data.get('project_name', 'test-project')
        project_description = data.get('description', '')
        project_type = data.get('type', '')
        
        logger.info(f"Requête reçue: project_name={project_name}, type={project_type}")
        
        # Traiter différemment selon le type de projet
        if project_type == 'go':
            logger.info("Projet Go détecté, envoi à l'agent développeur Go")
            
            # Préparer les données pour l'agent Go
            go_request = {
                "project_name": project_name,
                "specs": project_description,
                "requirements": "API REST simple en Go"
            }
            
            # Envoyer la requête à l'agent Go
            logger.info(f"Envoi à {GO_BACKEND_URL}: {json.dumps(go_request)}")
            
            response = requests.post(
                GO_BACKEND_URL,
                json=go_request,
                timeout=30
            )
            
            # Traiter la réponse
            if response.status_code == 200:
                logger.info("Réponse reçue de l'agent développeur Go")
                go_response = response.json()
                
                return jsonify({
                    "success": True,
                    "message": "Projet Go traité avec succès",
                    "response": go_response
                })
            else:
                error_msg = f"Erreur HTTP {response.status_code} de l'agent Go"
                logger.error(error_msg)
                logger.error(f"Contenu de la réponse: {response.text}")
                
                return jsonify({
                    "success": False,
                    "error": error_msg,
                    "response_text": response.text
                })
        else:
            # Type de projet non supporté par ce script simplifié
            return jsonify({
                "success": False,
                "error": f"Type de projet non supporté par l'agent simplifié: {project_type}"
            })
    
    except requests.exceptions.RequestException as e:
        error_msg = f"Erreur de connexion avec l'agent Go: {str(e)}"
        logger.error(error_msg)
        return jsonify({
            "success": False,
            "error": error_msg
        })
    except Exception as e:
        error_msg = f"Erreur lors du traitement: {str(e)}"
        logger.error(error_msg)
        return jsonify({
            "success": False,
            "error": error_msg
        })

if __name__ == '__main__':
    logger.info("Démarrage de l'agent Chef de Projet simplifié sur le port 5020")
    app.run(host='0.0.0.0', port=5020, debug=True)