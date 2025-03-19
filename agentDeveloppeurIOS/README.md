# Agent Développeur iOS

Cet agent est spécialisé dans le développement d'applications iOS en Swift. Il utilise Claude via AWS Bedrock pour analyser les spécifications et générer des solutions iOS complètes et robustes.

## Fonctionnalités

- Analyse des spécifications de projets iOS
- Génération de code Swift structuré et bien organisé
- Création de fichiers de projet prêts à l'emploi
- Support des frameworks UIKit et SwiftUI
- Interface web pour interagir avec l'agent

## Installation

1. Clonez ce dépôt
2. Installez les dépendances Python requises :
   ```
   cd python
   pip install -r requirements.txt
   ```
3. Assurez-vous que les informations d'identification AWS sont configurées correctement

## Utilisation

1. Démarrez le serveur :
   ```
   cd python
   python app.py
   ```
2. Accédez à l'interface web à l'adresse http://localhost:5013
3. Saisissez les spécifications de votre projet iOS
4. Cliquez sur "Générer Projet iOS"

## API

L'agent expose également une API REST pour l'intégration avec d'autres agents :

### Endpoint : `/code_request`

**Méthode** : POST

**Corps de la requête** :
```json
{
  "project_name": "MonProjetIOS",
  "specs": "Description détaillée du projet...",
  "requirements": "Exigences techniques spécifiques (optionnel)"
}
```

**Réponse** :
```json
{
  "project_name": "MonProjetIOS",
  "project_dir": "/chemin/vers/le/projet",
  "files": ["liste des fichiers générés"],
  "files_content": {
    "nom_fichier.swift": "contenu du fichier"
  },
  "main_file": "/chemin/vers/fichier/principal",
  "status": "success"
}
```