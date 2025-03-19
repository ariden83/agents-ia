#!/usr/bin/env python3
import requests
import json
import time

def test_qa_interface_directly():
    """
    Test directement l'interface de l'agent QA pour vérifier qu'il répond correctement
    aux requêtes et génère des logs.
    """
    
    # URL de l'agent QA
    qa_url = "http://localhost:5002/qa_api_request"
    
    # Données de test simplifiées
    test_data = {
        "test_plan": "Tester un formulaire de contact simple",
        "test_cases": [
            "Vérifier que le formulaire accepte les entrées valides",
            "Vérifier les messages d'erreur pour les entrées invalides",
            "Vérifier que le formulaire envoie les données correctement"
        ],
        "app_url": "https://example.com",
        "test_mode": "simple"  # Mode de test simplifié
    }
    
    print("\n----- Test direct de l'agent QA -----")
    print(f"Envoi de la demande à {qa_url}...")
    print(f"Contenu: {json.dumps(test_data, indent=2)}")
    
    try:
        # Envoyer la requête à l'agent QA
        response = requests.post(qa_url, json=test_data)
        
        if response.status_code == 200:
            print(f"✅ Requête envoyée avec succès. Code: {response.status_code}")
            print(f"Réponse: {response.json()}")
            
            # Attendre quelques secondes pour que les logs soient générés
            print("\nAttente de 5 secondes...")
            time.sleep(5)
            
            # Vérifier les logs de l'agent QA
            print("\nVérification des logs de l'agent QA...")
            check_logs("qaclaude")
            
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
    test_qa_interface_directly()