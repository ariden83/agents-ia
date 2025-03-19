#!/usr/bin/env python
"""
Script pour tester l'agent Chef de Projet simplifié.
"""

import requests
import json
import sys
import time

# URL de l'agent Chef de Projet simplifié
SIMPLIFIED_URL = "http://localhost:5020/project_request"

# Exemple de demande simple pour tester la communication
test_request = {
    "project_name": "test-simplified",
    "description": "Créer une API REST simple en Go qui expose un endpoint /hello qui renvoie un message JSON.",
    "type": "go"
}

def test_simplified_communication():
    """Teste la communication avec l'agent simplifié."""
    print("Envoi d'une requête à l'agent Chef de Projet simplifié...")
    print(f"Requête envoyée: {json.dumps(test_request, indent=2)}")
    
    try:
        response = requests.post(
            SIMPLIFIED_URL,
            json=test_request,
            timeout=60
        )
        
        if response.status_code == 200:
            print("Succès! Réponse reçue de l'agent simplifié:")
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
    success = test_simplified_communication()
    sys.exit(0 if success else 1)