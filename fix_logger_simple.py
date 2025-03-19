#!/usr/bin/env python3
import os
import glob

# Solution plus simple pour corriger le problème de logger non défini
def simple_fix_for_all_agents():
    # Trouver tous les fichiers app.py des agents
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app_files = glob.glob(os.path.join(base_dir, 'agent*/python/app.py'))
    
    for app_file in app_files:
        if "agentChefProjet" not in app_file:  # Éviter de modifier l'agent Chef de Projet qui fonctionne déjà
            print(f"Correction de {app_file}...")
            
            try:
                # Lire le fichier
                with open(app_file, 'r') as f:
                    content = f.read()
                
                # Vérifier si le fichier contient la configuration AWS mais pas de logger défini
                if "# Configuration AWS" in content and "aws_profile = os.getenv" in content:
                    # Définir une nouvelle configuration AWS qui n'utilise pas logger trop tôt
                    new_aws_config = """
# Configuration AWS - utiliser le profil spécifié dans le .env ou utiliser les identifiants par défaut si non spécifié
aws_profile = os.getenv("AWS_PROFILE")
if aws_profile:
    try:
        boto3.setup_default_session(profile_name=aws_profile)
        print(f"Session AWS initialisée avec le profil '{aws_profile}'")
    except Exception as e:
        print(f"Impossible d'utiliser le profil AWS spécifié ({aws_profile}): {str(e)}")
        print("Utilisation des identifiants AWS par défaut")
else:
    print("Aucun profil AWS spécifié dans .env, utilisation des identifiants par défaut")
"""
                    
                    # Remplacer le bloc de configuration AWS par le nouveau
                    content = content.replace("""
# Configuration AWS - utiliser le profil spécifié dans le .env ou utiliser les identifiants par défaut si non spécifié
aws_profile = os.getenv("AWS_PROFILE")
if aws_profile:
    try:
        boto3.setup_default_session(profile_name=aws_profile)
        logger.info(f"Session AWS initialisée avec le profil '{aws_profile}'")
    except Exception as e:
        logger.warning(f"Impossible d'utiliser le profil AWS spécifié ({aws_profile}): {str(e)}")
        logger.info("Utilisation des identifiants AWS par défaut")
else:
    logger.info("Aucun profil AWS spécifié dans .env, utilisation des identifiants par défaut")
""", new_aws_config)
                
                # Écrire le contenu corrigé
                with open(app_file, 'w') as f:
                    f.write(content)
                
                print(f"✅ Correction terminée pour {app_file}")
            
            except Exception as e:
                print(f"❌ Erreur lors de la correction de {app_file}: {str(e)}")
    
    print("Correction terminée pour tous les fichiers.")
    print("Redémarrez tous les agents avec 'make stop' puis 'make start' pour appliquer les corrections.")

if __name__ == "__main__":
    simple_fix_for_all_agents()