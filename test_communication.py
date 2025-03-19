#!/usr/bin/env python

import requests
import json
import sys

# URL de l'agent Chef de Projet pour envoyer une demande de développement Go
CHEF_PROJET_URL = "http://localhost:5000/project_request"

# Exemple de demande simple pour tester la communication
test_request = {
    "project_name": "test-communication",
    "description": "Créer une API REST simple en Go qui expose un endpoint /hello qui renvoie un message JSON.",
    "app_url": "http://localhost:8080",  # URL fictive pour l'application
    "type": "go",  # Spécifier le type de projet pour que le chef de projet choisisse l'agent Go
    "launch_dev": True  # Indiquer de lancer le développement immédiatement
}

def test_communication():
    """Teste la communication entre l'agent chef de projet et l'agent développeur Go."""
    print("Envoi d'une requête de test à l'agent Chef de Projet...")
    
    try:
        # Afficher la requête envoyée pour débogage
        print(f"Requête envoyée: {json.dumps(test_request, indent=2)}")
        
        response = requests.post(
            CHEF_PROJET_URL,
            json=test_request,
            timeout=60
        )
        
        if response.status_code == 200:
            print("Succès! Réponse reçue du Chef de Projet:")
            print(json.dumps(response.json(), indent=2))
            return True
        else:
            print(f"Erreur: Statut HTTP {response.status_code}")
            print(response.text)
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"Erreur de connexion: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_communication()
    sys.exit(0 if success else 1)