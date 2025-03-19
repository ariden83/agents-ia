#!/usr/bin/env python3
import requests
import json
import time
import sys

def test_chef_projet_qa_workflow():
    """
    Test le flux de travail complet entre l'agent Chef de Projet et l'agent QA.
    Envoie une demande de projet à l'agent Chef de Projet qui nécessite un test QA.
    """
    
    # URL de l'agent Chef de Projet
    chef_projet_url = "http://localhost:5000/project_request"
    
    # Données de test avec une URL valide à tester
    test_data = {
        "description": "Créer un plan de test pour une application de formulaire de contact. L'application est déjà déployée sur https://example.com. Tester toutes les fonctionnalités du formulaire.",
        "app_url": "https://example.com",
        "project_name": "test_qa_workflow",
        "launch_qa": True  # Forcer l'utilisation de l'agent QA
    }
    
    print("\n----- Test du flux Chef de Projet → QA -----")
    print(f"Envoi de la demande à {chef_projet_url}...")
    print(f"Contenu: {json.dumps(test_data, indent=2)}")
    
    try:
        # Envoyer la requête à l'agent Chef de Projet
        response = requests.post(chef_projet_url, json=test_data)
        
        if response.status_code == 200:
            print(f"✅ Requête envoyée avec succès. Code: {response.status_code}")
            print(f"Réponse: {response.json()}")
            
            # Attendre quelques secondes pour que le traitement asynchrone commence
            print("\nAttente de 5 secondes pour le début du traitement asynchrone...")
            time.sleep(5)
            
            # Vérifier si l'agent QA est contacté en consultant les logs
            print("\nVérification des logs de l'agent Chef de Projet...")
            check_logs("chef_projet")
            
            print("\nVérification des logs de l'agent QA...")
            check_logs("qaclaude")
            
            print("\n⏱️ Le traitement complet peut prendre quelques minutes.")
            print("Vous pouvez consulter les interfaces web pour suivre la progression:")
            print("- Agent Chef de Projet: http://localhost:5000")
            print("- Agent QA: http://localhost:5002")
            
        else:
            print(f"❌ Erreur lors de l'envoi de la requête. Code: {response.status_code}")
            print(f"Réponse: {response.text}")
    
    except Exception as e:
        print(f"❌ Exception lors du test: {str(e)}")
        return False
    
    return True

def check_logs(agent_name):
    """Vérifie les logs d'un agent spécifique."""
    try:
        with open(f"/home/adrien.parrochia/go/src/github.com/agentsIA/logs/{agent_name}.log", "r") as f:
            logs = f.readlines()
            
            # Afficher les 10 dernières lignes de logs
            if logs:
                print(f"Dernières lignes de logs ({min(10, len(logs))}):")
                for line in logs[-10:]:
                    print(f"  {line.strip()}")
            else:
                print("Aucun log trouvé.")
    except Exception as e:
        print(f"Erreur lors de la lecture des logs: {str(e)}")

if __name__ == "__main__":
    test_chef_projet_qa_workflow()