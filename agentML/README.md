# Agent Machine Learning

Cet agent est spécialisé dans la génération de solutions Machine Learning complètes et prêtes à l'emploi. Il utilise Claude via AWS Bedrock pour analyser les problèmes ML et générer des scripts Python, notebooks Jupyter, et fichiers de configuration adaptés.

## Fonctionnalités

- Analyse de problèmes ML à partir de descriptions textuelles
- Génération de notebooks Jupyter avec code et visualisations
- Création de scripts Python exécutables
- Génération de fichiers requirements.txt avec les dépendances nécessaires
- Stockage organisé des projets dans un workspace dédié
- Interface via API pour l'intégration avec d'autres agents

## Installation

1. Créer un environnement virtuel (recommandé)
```bash
python3 -m venv venv
source venv/bin/activate  # Sur Linux/macOS
```

2. Installer les dépendances
```bash
pip install -r python/requirements.txt
```

## Configuration AWS

L'agent utilise le profil AWS 'lbc-genai-dev-datauser' pour accéder à Bedrock. Assurez-vous que le profil est configuré correctement avec les permissions nécessaires pour Bedrock.

## Utilisation

### Lancement du serveur

```bash
cd python
python app.py
```

Le serveur Flask démarre sur le port 5007.

### Interface utilisateur

Accédez à l'interface web via `http://localhost:5007/` pour utiliser l'agent via l'UI.

### API

- **POST `/ml_request`** : Endpoint pour soumettre une demande ML directe
- **POST `/api/ml_analysis`** : Endpoint pour les demandes provenant d'autres agents (notamment l'agent Chef de Projet)

## Structure des projets générés

Chaque projet ML est stocké dans un dossier dédié dans `workspace/` et contient :

- Un notebook Jupyter (`.ipynb`) avec l'analyse complète
- Un script Python (`.py`) avec le code du modèle
- Un fichier `requirements.txt` avec les dépendances
- Un fichier `README.md` avec la documentation du projet

## Communication avec l'agent Chef de Projet

L'agent ML reçoit les demandes de l'agent Chef de Projet via l'endpoint `/api/ml_analysis`. Il traite la demande et renvoie les résultats au format JSON.

## Exemple de demande JSON

```json
{
  "project_name": "classification_clients",
  "specs": "Créer un modèle de classification pour prédire si un client va changer de fournisseur (churn) en utilisant les données démographiques et d'utilisation. Les données contiennent l'âge, le genre, la durée d'abonnement, le montant des factures mensuelles, etc."
}
```

## Exemple de réponse JSON

```json
{
  "project_name": "classification_clients",
  "project_dir": "/home/user/workspace/classification_clients",
  "files": [
    "/home/user/workspace/classification_clients/classification_clients_analysis.ipynb",
    "/home/user/workspace/classification_clients/classification_clients_model.py",
    "/home/user/workspace/classification_clients/requirements.txt",
    "/home/user/workspace/classification_clients/README.md"
  ],
  "status": "success"
}
```