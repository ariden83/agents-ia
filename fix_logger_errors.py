#!/usr/bin/env python3
import os
import re
import glob

def fix_logger_in_file(file_path):
    """Corrige les problèmes de logger non défini dans un fichier."""
    print(f"Correction de {file_path}...")
    
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Vérifier si le logging est importé mais logger est utilisé avant d'être défini
        if "import logging" in content and "logger = logging.getLogger" not in content:
            # Ajouter la définition du logger après l'import
            content = content.replace(
                "import logging",
                "import logging\nlogger = logging.getLogger(__name__)"
            )
            
            # Vérifier si on a la configuration du logger plus tard
            logger_config_match = re.search(r'logger\s*=\s*logging\.getLogger\(__name__\)', content)
            if logger_config_match:
                # Supprimer la redéfinition du logger
                content = content.replace(logger_config_match.group(0), "# logger déjà défini plus haut")
        
        # Déplacer la déclaration du logger avant sa première utilisation si nécessaire
        aws_profile_block = re.search(r'aws_profile = os\.getenv\("AWS_PROFILE"\)[^\n]*\nif aws_profile:[^}]*?logger\.', content, re.DOTALL)
        if aws_profile_block and "logger = logging.getLogger" not in content[:aws_profile_block.start()]:
            # Extraire le bloc pour le déplacer après la configuration du logger
            aws_block = aws_profile_block.group(0)
            content = content.replace(aws_block, "")
            
            # Trouver la configuration du logger
            logger_config = re.search(r'# Configuration du logger\s*\n.*?\n.*?\n.*?\n.*?\n.*?\n.*?\n)', content, re.DOTALL)
            if logger_config:
                # Insérer le bloc après la configuration du logger
                logger_end = logger_config.end()
                content = content[:logger_end] + "\n" + aws_block + content[logger_end:]
        
        # Écrire le contenu corrigé
        with open(file_path, 'w') as f:
            f.write(content)
        
        print(f"✅ Correction terminée pour {file_path}")
        return True
    
    except Exception as e:
        print(f"❌ Erreur lors de la correction de {file_path}: {str(e)}")
        return False

def fix_config_block(file_path):
    """Réorganise le bloc de configuration AWS pour éviter les erreurs de logger."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Chercher le bloc de configuration AWS problématique
        aws_config_match = re.search(r'# Configuration AWS.*?aws_profile = os\.getenv.*?if aws_profile:.*?else:.*?logger\.info\(".*?"\)', content, re.DOTALL)
        if aws_config_match:
            # Extraire le bloc
            aws_config_block = aws_config_match.group(0)
            # Supprimer le bloc original
            content = content.replace(aws_config_block, "")
            
            # Trouver où placer le bloc après la définition du logger
            logger_def_match = re.search(r'logger = logging\.getLogger\(__name__\)', content)
            if logger_def_match:
                insert_pos = logger_def_match.end()
                # Insérer le bloc après la définition du logger
                content = content[:insert_pos] + "\n\n" + aws_config_block + content[insert_pos:]
            else:
                # Si pas de définition de logger, ajouter avant l'app = Flask
                app_flask_match = re.search(r'app = Flask\(__name__\)', content)
                if app_flask_match:
                    insert_pos = app_flask_match.start()
                    # Ajouter la définition du logger et le bloc AWS
                    logger_def = "# Définition du logger\nlogger = logging.getLogger(__name__)\n\n"
                    content = content[:insert_pos] + logger_def + aws_config_block + "\n\n" + content[insert_pos:]
        
        # Écrire le contenu corrigé
        with open(file_path, 'w') as f:
            f.write(content)
        
        print(f"✅ Bloc de configuration AWS réorganisé dans {file_path}")
        return True
    
    except Exception as e:
        print(f"❌ Erreur lors de la réorganisation du bloc AWS dans {file_path}: {str(e)}")
        return False

def main():
    """Fonction principale qui corrige tous les fichiers app.py des agents."""
    # Trouver tous les fichiers app.py des agents
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app_files = glob.glob(os.path.join(base_dir, 'agent*/python/app.py'))
    
    print(f"Trouvé {len(app_files)} fichiers app.py à corriger")
    
    # Corriger chaque fichier
    for app_file in app_files:
        if "agentChefProjet" not in app_file:  # Éviter de modifier l'agent Chef de Projet qui fonctionne déjà
            fix_logger_in_file(app_file)
            fix_config_block(app_file)
    
    print("Correction terminée pour tous les fichiers.")
    print("Redémarrez tous les agents avec 'make stop' puis 'make start' pour appliquer les corrections.")

if __name__ == "__main__":
    main()