# AgentsIA

Ce projet implémente un système d'agents IA spécialisés pour différents rôles dans le développement logiciel.

## Agents disponibles

- Chef de Projet
- DevOps
- Développeur Python
- Développeur Frontend
- Développeur Go Backend
- QA
- Performance
- Machine Learning
- Analytics/Monitoring
- Product Owner
- UX Designer

## Installation

### Prérequis

- Python 3.8+
- Un environnement virtuel Python

### 1. Installation des dépendances

```bash
python3 -m venv myenv
source myenv/bin/activate
pip install requests flask flask-cors flask-socketio pyautogui websocket-client
sudo apt install libnss3 libgdk-pixbuf2.0-0 libx11-xcb1 libxcomposite1 
```

## Utilisation du Makefile

Le projet inclut un Makefile qui facilite la gestion des différents agents. Voici les principales commandes disponibles:

### Gestion de l'ensemble des agents

```bash
# Démarrer tous les agents
make start

# Arrêter tous les agents
make stop

# Mettre en pause tous les agents
make pause

# Reprendre tous les agents en pause
make resume

# Afficher l'état de tous les agents
make status

# Nettoyer les fichiers PID
make clean
```

### Gestion du serveur d'administration

```bash
# Démarrer l'interface d'administration web
make start-admin

# Arrêter l'interface d'administration web
make stop-admin
```

### Gestion des agents individuels

```bash
# Démarrer un agent spécifique
make start-chef-projet          # Chef de Projet
make start-devops               # DevOps CI/CD
make start-dev-python           # Développeur Python
make start-dev-frontend         # Développeur Frontend
make start-dev-go               # Développeur Go Backend
make start-qa                   # QA
make start-perf                 # Performance
make start-ml                   # Machine Learning
make start-analytics            # Analytics/Monitoring
make start-product-owner        # Product Owner
make start-ux-designer          # UX Designer

# Arrêter un agent spécifique
make stop-chef-projet
make stop-devops
# etc...

# Mettre en pause un agent spécifique
make pause-chef-projet
make pause-devops
# etc...

# Reprendre un agent spécifique
make resume-chef-projet
make resume-devops
# etc...
```

Pour voir toutes les commandes disponibles:
```bash
make help
```

## Structure du projet

Chaque agent est implémenté dans son propre dossier avec un serveur Flask et des templates HTML pour l'interface utilisateur:

```
/agentChefProjet            # Agent Chef de Projet
/agentDevOps                # Agent DevOps CI/CD
/agentDeveloppeurPython     # Agent Développeur Python
/agentDeveloppeurFrontend   # Agent Développeur Frontend
/agentDeveloppeurGoBackend  # Agent Développeur Go Backend
/agentQAClaude              # Agent QA
/agentPerformance           # Agent Performance
/agentML                    # Agent Machine Learning
/agentAnalyticsMonitoring   # Agent Analytics/Monitoring
/agentProductOwner          # Agent Product Owner
/agentUXDesigner            # Agent UX Designer
```

## Administration

Le projet inclut un serveur d'administration pour gérer et surveiller les agents. Pour le démarrer:

```bash
make start-admin
```

L'interface web d'administration sera disponible à l'adresse: http://localhost:8080

## Contribution

Pour contribuer à ce projet, veuillez consulter la documentation spécifique à chaque agent dans leurs répertoires respectifs.