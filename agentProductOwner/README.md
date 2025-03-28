# Agent Product Owner

Cet agent est spécialisé dans la génération d'idées innovantes et l'analyse des tendances pour enrichir les projets. Il utilise Claude via AWS Bedrock pour identifier les tendances pertinentes et proposer des fonctionnalités à valeur ajoutée, agissant comme un Product Owner virtuel en amont du Chef de Projet.

## Fonctionnalités

- Analyse d'un projet pour en comprendre le contexte et les objectifs
- Identification des tendances technologiques, UX et business pertinentes
- Génération de suggestions de fonctionnalités innovantes et réalistes
- Évaluation de la faisabilité technique et du potentiel ROI de chaque fonctionnalité
- Hiérarchisation des suggestions par priorité
- Sauvegarde des suggestions dans un format structuré et documenté
- Interface web conviviale pour soumettre des demandes
- API pour l'intégration avec d'autres agents

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

Le serveur Flask démarre sur le port 5012.

### Interface utilisateur

Accédez à l'interface web via `http://localhost:5012/` pour utiliser l'agent via l'UI.

### API

- **POST `/po_request`** : Endpoint pour soumettre une demande de suggestions directement
- **POST `/api/po_suggestions`** : Endpoint pour les demandes provenant d'autres agents

## Structure des suggestions générées

Chaque ensemble de suggestions est organisé selon une structure claire :

1. **Analyse du projet** : Compréhension du contexte et des objectifs
2. **Tendances pertinentes** : Identification de 5 à 8 tendances applicables au projet
3. **Suggestions de fonctionnalités** : Proposition de 3 à 5 fonctionnalités inspirées des tendances avec :
   - Description détaillée
   - Alignement avec les tendances
   - Valeur ajoutée pour les utilisateurs
   - Faisabilité technique (Facile/Moyenne/Complexe)
   - Potentiel ROI (Faible/Moyen/Élevé)
4. **Recommandations prioritaires** : Hiérarchisation des suggestions

## Workflow typique

1. L'utilisateur décrit son projet, avec éventuellement des informations sur le secteur d'activité et la cible
2. L'agent PO analyse le projet et les tendances du marché
3. L'agent génère des suggestions de fonctionnalités innovantes et réalistes
4. L'utilisateur peut copier, télécharger ou transmettre ces suggestions au Chef de Projet
5. Le Chef de Projet peut alors intégrer ces suggestions dans la planification du projet

## Exemple de demande JSON

```json
{
  "project_name": "PlantCare",
  "description": "Une application mobile qui aide les utilisateurs à prendre soin de leurs plantes d'intérieur en leur fournissant des rappels d'arrosage et des conseils d'entretien personnalisés.",
  "industry": "Bien-être et jardinage",
  "target_audience": "Jeunes urbains de 25-35 ans avec peu d'expérience en jardinage",
  "additional_context": "L'application existe déjà en version beta avec les fonctionnalités de base (identification de plantes et rappels). Nous cherchons à enrichir l'expérience utilisateur pour la version 2.0."
}
```

## Exemple de réponse JSON

```json
{
  "project_name": "PlantCare",
  "suggestions_file": "/path/to/workspace/plantcare/suggestions_20240314_103045.md",
  "suggestions": "# Analyse du projet\n\nPlantCare est une application mobile...",
  "file_content": "# Suggestions pour le projet: PlantCare\n\n## Description du projet\n\nUne application mobile qui aide les utilisateurs...",
  "status": "success"
}
```