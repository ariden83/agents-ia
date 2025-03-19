# Agent Analytics & Monitoring

Cet agent est spécialisé dans la génération de configurations complètes d'analytics, monitoring et logging pour les projets web. Il utilise Claude via AWS Bedrock pour analyser les besoins spécifiques d'un projet et générer des configurations pour divers outils d'observabilité.

## Fonctionnalités

- Analyse des besoins en observabilité pour un projet web
- Génération de configurations pour le monitoring (Prometheus, Grafana, etc.)
- Génération de configurations pour l'analytics web (Google Analytics, Matomo, etc.)
- Génération de configurations pour la gestion des logs (ELK, Loki, Fluentd, etc.)
- Organisation claire des fichiers par type d'outil
- Documentation complète avec instructions d'installation et d'utilisation
- Interface web pour soumettre des demandes directement
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

L'agent utilise le profil AWS pour accéder à Bedrock. Assurez-vous que le profil est configuré correctement avec les permissions nécessaires pour Bedrock.

## Utilisation

### Lancement du serveur

```bash
cd python
python app.py
```

Le serveur Flask démarre sur le port 5011.

### Interface utilisateur

Accédez à l'interface web via `http://localhost:5011/` pour utiliser l'agent via l'UI.

### API

- **POST `/analytics_monitoring_request`** : Endpoint pour soumettre une demande d'analytics et monitoring directe
- **POST `/api/analytics_monitoring`** : Endpoint pour les demandes provenant d'autres agents (notamment l'agent Chef de Projet)

## Structure des projets générés

Chaque projet de configuration est organisé dans une structure de dossiers claire :

- `monitoring/` : Configurations pour les outils de monitoring (Prometheus, Grafana, etc.)
- `analytics/` : Configurations pour les outils d'analytics (Google Analytics, Matomo, etc.)
- `logging/` : Configurations pour les systèmes de gestion de logs (ELK, Loki, etc.)
- `general/` : Configurations générales ou non catégorisées
- `README.md` : Documentation complète du projet

## Communication avec l'agent Chef de Projet

L'agent Analytics & Monitoring reçoit des demandes de l'agent Chef de Projet via l'endpoint `/api/analytics_monitoring`. Il traite la demande et renvoie les résultats au format JSON.

## Exemple de demande JSON

```json
{
  "project_name": "ecommerce-app",
  "specs": "Notre application est une boutique e-commerce qui vend des produits électroniques. Nous avons besoin de surveiller les performances du site, suivre les conversions et les abandons de panier, et centraliser les logs pour le débogage.",
  "stack_info": "Frontend: React.js. Backend: Node.js avec Express. Base de données: MongoDB. Infrastructure: Kubernetes sur AWS."
}
```

## Exemple de réponse JSON

```json
{
  "project_name": "ecommerce-app",
  "project_dir": "/path/to/workspace/ecommerce-app",
  "files": [
    "/path/to/workspace/ecommerce-app/monitoring/prometheus.yaml",
    "/path/to/workspace/ecommerce-app/monitoring/grafana-dashboard.json",
    "/path/to/workspace/ecommerce-app/analytics/ga4-config.js",
    "/path/to/workspace/ecommerce-app/logging/fluent-bit.conf",
    "/path/to/workspace/ecommerce-app/README.md"
  ],
  "files_content": {
    "monitoring/prometheus.yaml": "# Configuration Prometheus...",
    "monitoring/grafana-dashboard.json": "{ ... }",
    "analytics/ga4-config.js": "// Configuration Google Analytics...",
    "logging/fluent-bit.conf": "# Configuration Fluent Bit...",
    "README.md": "# Configuration d'Analytics & Monitoring..."
  },
  "status": "success"
}
```