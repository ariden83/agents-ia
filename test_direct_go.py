#!/usr/bin/env python

import requests
import json
import sys

# URL de l'agent développeur Go Backend
GO_BACKEND_URL = "http://localhost:5001/go_code_request"

# Exemple de demande simple pour tester directement l'agent Go
test_request = {
    "project_name": "test-direct-go",
    "specs": "Créer une API REST simple en Go qui expose un endpoint /hello qui renvoie un message JSON.",
    "requirements": "Utiliser la bibliothèque standard Go net/http"
}

def test_direct_communication():
    """Teste la communication directe avec l'agent développeur Go."""
    print("Envoi d'une requête directe à l'agent développeur Go...")
    print(f"Requête envoyée: {json.dumps(test_request, indent=2)}")
    
    try:
        response = requests.post(
            GO_BACKEND_URL,
            json=test_request,
            timeout=60
        )
        
        if response.status_code == 200:
            print("Succès! Réponse reçue de l'agent développeur Go:")
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
    success = test_direct_communication()
    sys.exit(0 if success else 1)