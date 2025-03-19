#!/usr/bin/env python3
import os
import re

# Chemin du fichier app.py de l'agent QA
qa_app_file = "/home/adrien.parrochia/go/src/github.com/agentsIA/agentQAClaude/python/app.py"

def add_explicit_logging():
    """Ajoute des instructions de logging explicites dans les fonctions principales de l'agent QA."""
    print(f"Modification du fichier {qa_app_file}...")
    
    try:
        with open(qa_app_file, 'r') as f:
            content = f.read()
        
        # Ajout de logs explicites dans la fonction qa_api_request
        if "def qa_api_request():" in content:
            print("Ajout de logs dans qa_api_request...")
            updated = content.replace(
                "def qa_api_request():",
                """def qa_api_request():
    # Log explicite ajouté ici
    with open('/home/adrien.parrochia/go/src/github.com/agentsIA/logs/qaclaude.log', 'a') as log_file:
        log_file.write("2025-03-18 [INFO] Requête QA reçue via l'API\\n")"""
            )
            
            # Vérifier si le contenu a été modifié
            if content != updated:
                content = updated
                print("✅ Logs ajoutés dans qa_api_request")
            else:
                print("⚠️ Impossible de modifier qa_api_request")
        
        # Ajout de logs explicites dans la fonction qa_claude_request
        if "async def qa_claude_request():" in content:
            print("Ajout de logs dans qa_claude_request...")
            updated = content.replace(
                "async def qa_claude_request():",
                """async def qa_claude_request():
    # Log explicite ajouté ici
    with open('/home/adrien.parrochia/go/src/github.com/agentsIA/logs/qaclaude.log', 'a') as log_file:
        log_file.write("2025-03-18 [INFO] Traitement de la requête QA en cours...\\n")
"""
            )
            
            # Vérifier si le contenu a été modifié
            if content != updated:
                content = updated
                print("✅ Logs ajoutés dans qa_claude_request")
            else:
                print("⚠️ Impossible de modifier qa_claude_request")
        
        # Écrire le contenu modifié
        with open(qa_app_file, 'w') as f:
            f.write(content)
        
        print("Modifications terminées !")
    
    except Exception as e:
        print(f"❌ Erreur lors de la modification du fichier: {str(e)}")

if __name__ == "__main__":
    add_explicit_logging()