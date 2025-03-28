# Agent UX Designer

Agent UX Designer est un service basé sur Claude 3 Sonnet qui génère des conceptions UX complètes à partir de spécifications fournies par l'utilisateur.

## Fonctionnalités

- Génération de wireframes ASCII détaillés pour visualiser les interfaces
- Analyse des besoins utilisateurs
- Architecture de l'information
- Flow utilisateur
- Principes de design UI
- Recommandations d'accessibilité
- Organisation des éléments de conception dans un projet structuré

## Installation

1. Assurez-vous d'avoir Python 3.8+ installé
2. Installez les dépendances requises:

```bash
pip install -r python/requirements.txt
```

3. Configurez vos identifiants AWS pour accéder à Claude via Bedrock

## Utilisation

Pour démarrer le serveur:

```bash
cd python
python app.py
```

Accédez ensuite à l'interface web via http://localhost:5015

## Structure du Projet

- `python/app.py`: Application principale
- `python/templates/`: Templates HTML pour l'interface web
- `python/workspace/`: Dossier où les projets UX générés sont stockés

## Exemple d'Utilisation

1. Donnez un nom à votre projet
2. Décrivez les spécifications UX en détail
3. Ajoutez des contraintes optionnelles (plateforme, accessibilité, etc.)
4. Cliquez sur "Générer Conception UX"
5. Visualisez les wireframes ASCII et l'analyse complète
6. Les fichiers du projet sont sauvegardés dans le dossier workspace

## Développement

Pour contribuer au développement:

1. Clonez ce dépôt
2. Installez les dépendances de développement
3. Suivez les conventions de codage du projet

## Licence

Ce projet est sous licence MIT.