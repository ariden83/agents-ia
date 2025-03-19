#!/usr/bin/env python3
import os
import glob

# Ce script va appliquer une correction d'urgence très simple aux fichiers app.py
# Il va remplacer tous les appels à "logger" par des prints avant que le logger soit configuré
def emergency_fix():
    # Trouver tous les fichiers app.py des agents
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app_files = glob.glob(os.path.join(base_dir, 'agent*/python/app.py'))
    
    for app_file in app_files:
        if "agentChefProjet" not in app_file:  # Éviter de modifier l'agent Chef de Projet qui fonctionne déjà
            print(f"Correction d'urgence de {app_file}...")
            
            try:
                # Lire le fichier comme texte brut
                with open(app_file, 'r') as f:
                    lines = f.readlines()
                
                # Vérifier si le fichier a déjà été modifié
                for i in range(len(lines)):
                    # Remplacer directement toutes les utilisations problématiques de logger
                    if "aws_profile = os.getenv" in lines[i]:
                        for j in range(i, min(i+20, len(lines))):
                            if "logger.info" in lines[j]:
                                lines[j] = lines[j].replace("logger.info", "print")
                            if "logger.warning" in lines[j]:
                                lines[j] = lines[j].replace("logger.warning", "print")
                            if "logger.error" in lines[j]:
                                lines[j] = lines[j].replace("logger.error", "print")
                
                # Écrire le fichier modifié
                with open(app_file, 'w') as f:
                    f.writelines(lines)
                
                print(f"✅ Correction d'urgence appliquée à {app_file}")
            
            except Exception as e:
                print(f"❌ Erreur lors de la correction de {app_file}: {str(e)}")
    
    print("Correction d'urgence terminée.")
    print("Redémarrez tous les agents avec 'make stop' puis 'make start' pour appliquer les corrections.")

if __name__ == "__main__":
    emergency_fix()