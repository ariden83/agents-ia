# Makefile pour lancer tous les agents et interfaces web
# Utilisation:
# - make start: Démarrer tous les agents
# - make stop: Arrêter tous les agents
# - make pause: Mettre en pause tous les agents (SIGSTOP)
# - make resume: Reprendre tous les agents en pause (SIGCONT)
# - make start-chef-projet: Démarrer uniquement l'agent chef de projet
# - make start-devops: Démarrer uniquement l'agent DevOps CI/CD
# - et ainsi de suite pour chaque agent individuellement
# - make pause-agent: Mettre en pause un agent spécifique
# - make resume-agent: Reprendre un agent spécifique

# Définition des chemins vers les agents
CHEF_PROJET_DIR = $(CURDIR)/agentChefProjet/python
DEVOPS_DIR = $(CURDIR)/agentDevOps/python
DEV_PYTHON_DIR = $(CURDIR)/agentDeveloppeurPython/python
DEV_FRONTEND_DIR = $(CURDIR)/agentDeveloppeurFrontend/python
DEV_GO_BACKEND_DIR = $(CURDIR)/agentDeveloppeurGoBackend/python
QA_DIR = $(CURDIR)/agentQAClaude/python
PERF_DIR = $(CURDIR)/agentPerformance/python
ML_DIR = $(CURDIR)/agentML/python
ANALYTICS_DIR = $(CURDIR)/agentAnalyticsMonitoring/python
PRODUCT_OWNER_DIR = $(CURDIR)/agentProductOwner/python
UX_DESIGNER_DIR = $(CURDIR)/agentUXDesigner/python

# Définition des ports utilisés par chaque agent
CHEF_PROJET_PORT = 5000
DEVOPS_PORT = 5005
DEV_PYTHON_PORT = 5001
DEV_FRONTEND_PORT = 5003
DEV_GO_BACKEND_PORT = 5004
QA_PORT = 5002
PERF_PORT = 5006
ML_PORT = 5007
ANALYTICS_PORT = 5008
PRODUCT_OWNER_PORT = 5009
UX_DESIGNER_PORT = 5010

# Définition des fichiers PID pour gérer les processus
PID_DIR = $(CURDIR)/pids
CHEF_PROJET_PID = $(PID_DIR)/chef_projet.pid
DEVOPS_PID = $(PID_DIR)/devops.pid
DEV_PYTHON_PID = $(PID_DIR)/dev_python.pid
DEV_FRONTEND_PID = $(PID_DIR)/dev_frontend.pid
DEV_GO_BACKEND_PID = $(PID_DIR)/dev_go_backend.pid
QA_PID = $(PID_DIR)/qa.pid
PERF_PID = $(PID_DIR)/perf.pid
ML_PID = $(PID_DIR)/ml.pid
ANALYTICS_PID = $(PID_DIR)/analytics.pid
PRODUCT_OWNER_PID = $(PID_DIR)/product_owner.pid
UX_DESIGNER_PID = $(PID_DIR)/ux_designer.pid

# Cible par défaut
.PHONY: help
help:
	@echo "Utilisation du Makefile:"
	@echo "  make init               - Crée l'environnement Python et installe les dépendances"
	@echo "  make start-admin        - Démarre l'interface d'administration web"
	@echo "  make stop-admin         - Arrête l'interface d'administration web"
	@echo "  make start              - Démarre tous les agents"
	@echo "  make stop               - Arrête tous les agents"
	@echo "  make pause              - Met en pause tous les agents"
	@echo "  make resume             - Reprend tous les agents en pause"
	@echo "  make start-chef-projet  - Démarre l'agent Chef de Projet"
	@echo "  make start-devops       - Démarre l'agent DevOps CI/CD"
	@echo "  make start-dev-python   - Démarre l'agent Développeur Python"
	@echo "  make start-dev-frontend - Démarre l'agent Développeur Frontend"
	@echo "  make start-dev-go       - Démarre l'agent Développeur Go Backend"
	@echo "  make start-qa           - Démarre l'agent QA"
	@echo "  make start-perf         - Démarre l'agent Performance"
	@echo "  make start-ml           - Démarre l'agent Machine Learning"
	@echo "  make start-analytics    - Démarre l'agent Analytics/Monitoring"
	@echo "  make start-product-owner - Démarre l'agent Product Owner"
	@echo "  make start-ux-designer  - Démarre l'agent UX Designer"
	@echo "  make pause-chef-projet  - Met en pause l'agent Chef de Projet"
	@echo "  make resume-chef-projet - Reprend l'agent Chef de Projet"
	@echo "  make pause-devops       - Met en pause l'agent DevOps CI/CD"
	@echo "  make resume-devops      - Reprend l'agent DevOps CI/CD"
	@echo "  (et ainsi de suite pour les autres agents)"
	@echo "  make status             - Affiche l'état des agents"
	@echo "  make clean              - Nettoie les fichiers PID"

# Répertoire du serveur admin
ADMIN_PORT = 8080

# Environnement Python virtuel
VENV_DIR = $(CURDIR)/venv

PYTHON = python3
PIP = $(VENV_DIR)/bin/pip

# Création du répertoire pour les PID

# Initialisation de l'environnement Python et installation des dépendances
.PHONY: init
init:
	@echo "Création de l'environnement Python virtuel..."
	@$(PYTHON) -m venv $(VENV_DIR)
	@echo "Installation des dépendances Python communes..."
	@$(PIP) install --upgrade pip
	@$(PIP) install flask flask-cors flask-socketio boto3 eventlet requests python-dotenv
	@echo "Installation des dépendances spécifiques pour l'agent ML..."
	@$(PIP) install numpy pandas scikit-learn matplotlib seaborn jupyter
	@echo "Installation de dépendances additionnelles..."
	@$(PIP) install pillow browser_use
	@echo "\nEnvironnement Python créé avec succès !"
	@echo "Pour activer l'environnement, exécutez : source $(VENV_DIR)/bin/activate"
	@echo "Toutes les dépendances ont été installées. Vous pouvez maintenant lancer les agents avec 'make start'."
$(PID_DIR):
	mkdir -p $(PID_DIR)

# Démarrage du serveur d'administration web
.PHONY: start-admin
start-admin: 
	@echo "Démarrage du serveur d'administration..."
	@$(VENV_DIR)/bin/python admin_server.py & echo $$! > $(PID_DIR)/admin.pid
	@echo "Serveur d'administration démarré sur le port $(ADMIN_PORT)"
	@echo "Interface web disponible à l'adresse: http://localhost:$(ADMIN_PORT)"

# Arrêt du serveur d'administration web
.PHONY: stop-admin
stop-admin:
	@if [ -f $(PID_DIR)/admin.pid ]; then \
		if kill -0 `cat $(PID_DIR)/admin.pid` 2>/dev/null; then \
			echo "Arrêt du serveur d'administration..."; \
			kill -15 `cat $(PID_DIR)/admin.pid`; \
			rm $(PID_DIR)/admin.pid; \
			echo "Serveur d'administration arrêté."; \
		else \
			echo "Le serveur d'administration n'est pas en cours d'exécution."; \
			rm $(PID_DIR)/admin.pid; \
		fi \
	else \
		echo "Le serveur d'administration n'est pas en cours d'exécution."; \
	fi

# Démarrage de tous les agents
.PHONY: start
start: $(PID_DIR) start-chef-projet start-devops start-dev-python start-dev-frontend start-dev-go start-qa start-perf start-ml start-analytics start-product-owner start-ux-designer
	@echo "Tous les agents ont été démarrés"
	@echo "Interfaces web disponibles aux adresses suivantes:"
	@echo "  - Agent Chef de Projet:  http://localhost:$(CHEF_PROJET_PORT)"
	@echo "  - Agent DevOps CI/CD:    http://localhost:$(DEVOPS_PORT)"
	@echo "  - Agent Développeur Python: http://localhost:$(DEV_PYTHON_PORT)"
	@echo "  - Agent Dev Frontend:    http://localhost:$(DEV_FRONTEND_PORT)"
	@echo "  - Agent Dev Go Backend:  http://localhost:$(DEV_GO_BACKEND_PORT)"
	@echo "  - Agent QA:              http://localhost:$(QA_PORT)"
	@echo "  - Agent Performance:     http://localhost:$(PERF_PORT)"
	@echo "  - Agent Machine Learning: http://localhost:$(ML_PORT)"
	@echo "  - Agent Analytics/Monitoring: http://localhost:$(ANALYTICS_PORT)"
	@echo "  - Agent Product Owner:   http://localhost:$(PRODUCT_OWNER_PORT)"
	@echo "  - Agent UX Designer:     http://localhost:$(UX_DESIGNER_PORT)"

# Arrêt de tous les agents
.PHONY: stop
stop: stop-chef-projet stop-devops stop-dev-python stop-dev-frontend stop-dev-go stop-qa stop-perf stop-ml stop-analytics stop-product-owner stop-ux-designer
	@echo "Tous les agents ont été arrêtés"
	@echo "Nettoyage des processus résiduels..."
	@./clean_processes.sh

# Démarrage de l'agent Chef de Projet
.PHONY: start-chef-projet
start-chef-projet: $(PID_DIR)
	@echo "Démarrage de l'agent Chef de Projet..."
	@if [ -f $(CHEF_PROJET_PID) ] && kill -0 `cat $(CHEF_PROJET_PID)` 2>/dev/null; then \
		echo "L'agent Chef de Projet est déjà en cours d'exécution."; \
	else \
		mkdir -p logs; \
		cd $(CHEF_PROJET_DIR) && $(VENV_DIR)/bin/python app.py > ../../logs/chef_projet.log 2>&1 & echo $$! > $(CHEF_PROJET_PID); \
		echo "Agent Chef de Projet démarré sur le port $(CHEF_PROJET_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(CHEF_PROJET_PORT)"; \
		echo "Pour voir les logs en temps réel, utilisez: make logs-chef-projet"; \
	fi

# Afficher les logs de l'agent Chef de Projet
.PHONY: logs-chef-projet
logs-chef-projet:
	@if [ -f $(CHEF_PROJET_PID) ] && kill -0 `cat $(CHEF_PROJET_PID)` 2>/dev/null; then \
		echo "Affichage des logs de l'agent Chef de Projet..."; \
		tail -f $(CURDIR)/logs/chef_projet.log 2>/dev/null || echo "Aucun fichier de log trouvé."; \
	else \
		echo "L'agent Chef de Projet n'est pas en cours d'exécution."; \
		if [ -f $(CURDIR)/logs/chef_projet.log ]; then \
			echo "Affichage des derniers logs avant l'arrêt:"; \
			tail $(CURDIR)/logs/chef_projet.log; \
		fi \
	fi

# Démarrage de l'agent DevOps CI/CD
.PHONY: start-devops
start-devops: $(PID_DIR)
	@echo "Démarrage de l'agent DevOps CI/CD..."
	@if [ -f $(DEVOPS_PID) ] && kill -0 `cat $(DEVOPS_PID)` 2>/dev/null; then \
		echo "L'agent DevOps CI/CD est déjà en cours d'exécution."; \
	else \
		cd $(DEVOPS_DIR) && $(VENV_DIR)/bin/python app.py & echo $$! > $(DEVOPS_PID); \
		echo "Agent DevOps CI/CD démarré sur le port $(DEVOPS_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(DEVOPS_PORT)"; \
	fi

# Démarrage de l'agent Développeur Python
.PHONY: start-dev-python
start-dev-python: $(PID_DIR)
	@echo "Démarrage de l'agent Développeur Python..."
	@if [ -f $(DEV_PYTHON_PID) ] && kill -0 `cat $(DEV_PYTHON_PID)` 2>/dev/null; then \
		echo "L'agent Développeur Python est déjà en cours d'exécution."; \
	else \
		cd $(DEV_PYTHON_DIR) && $(VENV_DIR)/bin/python app.py & echo $$! > $(DEV_PYTHON_PID); \
		echo "Agent Développeur Python démarré sur le port $(DEV_PYTHON_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(DEV_PYTHON_PORT)"; \
	fi

# Démarrage de l'agent Développeur Frontend
.PHONY: start-dev-frontend
start-dev-frontend: $(PID_DIR)
	@echo "Démarrage de l'agent Développeur Frontend..."
	@if [ -f $(DEV_FRONTEND_PID) ] && kill -0 `cat $(DEV_FRONTEND_PID)` 2>/dev/null; then \
		echo "L'agent Développeur Frontend est déjà en cours d'exécution."; \
	else \
		cd $(DEV_FRONTEND_DIR) && $(VENV_DIR)/bin/python app.py & echo $$! > $(DEV_FRONTEND_PID); \
		echo "Agent Développeur Frontend démarré sur le port $(DEV_FRONTEND_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(DEV_FRONTEND_PORT)"; \
	fi

# Démarrage de l'agent Développeur Go Backend
.PHONY: start-dev-go
start-dev-go: $(PID_DIR)
	@echo "Démarrage de l'agent Développeur Go Backend..."
	@if [ -f $(DEV_GO_BACKEND_PID) ] && kill -0 `cat $(DEV_GO_BACKEND_PID)` 2>/dev/null; then \
		echo "L'agent Développeur Go Backend est déjà en cours d'exécution."; \
	else \
		cd $(DEV_GO_BACKEND_DIR) && $(VENV_DIR)/bin/python app.py & echo $$! > $(DEV_GO_BACKEND_PID); \
		echo "Agent Développeur Go Backend démarré sur le port $(DEV_GO_BACKEND_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(DEV_GO_BACKEND_PORT)"; \
	fi

# Démarrage de l'agent QA
.PHONY: start-qa
start-qa: $(PID_DIR)
	@echo "Démarrage de l'agent QA..."
	@if [ -f $(QA_PID) ] && kill -0 `cat $(QA_PID)` 2>/dev/null; then \
		echo "L'agent QA est déjà en cours d'exécution."; \
	else \
		cd $(QA_DIR) && bash -c "source $(CURDIR)/myenv/bin/activate && python app.py" & echo $$! > $(QA_PID); \
		echo "Agent QA démarré sur le port $(QA_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(QA_PORT)"; \
	fi

# Démarrage de l'agent Performance
.PHONY: start-perf
start-perf: $(PID_DIR)
	@echo "Démarrage de l'agent Performance..."
	@if [ -f $(PERF_PID) ] && kill -0 `cat $(PERF_PID)` 2>/dev/null; then \
		echo "L'agent Performance est déjà en cours d'exécution."; \
	else \
		cd $(PERF_DIR) && bash -c "source $(CURDIR)/myenv/bin/activate && python app.py" & echo $$! > $(PERF_PID); \
		echo "Agent Performance démarré sur le port $(PERF_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(PERF_PORT)"; \
	fi

# Arrêt de l'agent Chef de Projet
.PHONY: stop-chef-projet
stop-chef-projet:
	@if [ -f $(CHEF_PROJET_PID) ]; then \
		if kill -0 `cat $(CHEF_PROJET_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent Chef de Projet..."; \
			kill -15 `cat $(CHEF_PROJET_PID)`; \
			rm $(CHEF_PROJET_PID); \
			echo "Agent Chef de Projet arrêté."; \
		else \
			echo "L'agent Chef de Projet n'est pas en cours d'exécution."; \
			rm $(CHEF_PROJET_PID); \
		fi \
	else \
		echo "L'agent Chef de Projet n'est pas en cours d'exécution."; \
	fi

# Arrêt de l'agent DevOps CI/CD
.PHONY: stop-devops
stop-devops:
	@if [ -f $(DEVOPS_PID) ]; then \
		if kill -0 `cat $(DEVOPS_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent DevOps CI/CD..."; \
			kill -15 `cat $(DEVOPS_PID)`; \
			rm $(DEVOPS_PID); \
			echo "Agent DevOps CI/CD arrêté."; \
		else \
			echo "L'agent DevOps CI/CD n'est pas en cours d'exécution."; \
			rm $(DEVOPS_PID); \
		fi \
	else \
		echo "L'agent DevOps CI/CD n'est pas en cours d'exécution."; \
	fi

# Arrêt de l'agent Développeur Python
.PHONY: stop-dev-python
stop-dev-python:
	@if [ -f $(DEV_PYTHON_PID) ]; then \
		if kill -0 `cat $(DEV_PYTHON_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent Développeur Python..."; \
			kill -15 `cat $(DEV_PYTHON_PID)`; \
			rm $(DEV_PYTHON_PID); \
			echo "Agent Développeur Python arrêté."; \
		else \
			echo "L'agent Développeur Python n'est pas en cours d'exécution."; \
			rm $(DEV_PYTHON_PID); \
		fi \
	else \
		echo "L'agent Développeur Python n'est pas en cours d'exécution."; \
	fi

# Arrêt de l'agent Développeur Frontend
.PHONY: stop-dev-frontend
stop-dev-frontend:
	@if [ -f $(DEV_FRONTEND_PID) ]; then \
		if kill -0 `cat $(DEV_FRONTEND_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent Développeur Frontend..."; \
			kill -15 `cat $(DEV_FRONTEND_PID)`; \
			rm $(DEV_FRONTEND_PID); \
			echo "Agent Développeur Frontend arrêté."; \
		else \
			echo "L'agent Développeur Frontend n'est pas en cours d'exécution."; \
			rm $(DEV_FRONTEND_PID); \
		fi \
	else \
		echo "L'agent Développeur Frontend n'est pas en cours d'exécution."; \
	fi

# Arrêt de l'agent Développeur Go Backend
.PHONY: stop-dev-go
stop-dev-go:
	@if [ -f $(DEV_GO_BACKEND_PID) ]; then \
		if kill -0 `cat $(DEV_GO_BACKEND_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent Développeur Go Backend..."; \
			kill -15 `cat $(DEV_GO_BACKEND_PID)`; \
			rm $(DEV_GO_BACKEND_PID); \
			echo "Agent Développeur Go Backend arrêté."; \
		else \
			echo "L'agent Développeur Go Backend n'est pas en cours d'exécution."; \
			rm $(DEV_GO_BACKEND_PID); \
		fi \
	else \
		echo "L'agent Développeur Go Backend n'est pas en cours d'exécution."; \
	fi

# Arrêt de l'agent QA
.PHONY: stop-qa
stop-qa:
	@if [ -f $(QA_PID) ]; then \
		if kill -0 `cat $(QA_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent QA..."; \
			kill -15 `cat $(QA_PID)`; \
			rm $(QA_PID); \
			echo "Agent QA arrêté."; \
		else \
			echo "L'agent QA n'est pas en cours d'exécution."; \
			rm $(QA_PID); \
		fi \
	else \
		echo "L'agent QA n'est pas en cours d'exécution."; \
	fi

# Arrêt de l'agent Performance
.PHONY: stop-perf
stop-perf:
	@if [ -f $(PERF_PID) ]; then \
		if kill -0 `cat $(PERF_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent Performance..."; \
			kill -15 `cat $(PERF_PID)`; \
			rm $(PERF_PID); \
			echo "Agent Performance arrêté."; \
		else \
			echo "L'agent Performance n'est pas en cours d'exécution."; \
			rm $(PERF_PID); \
		fi \
	else \
		echo "L'agent Performance n'est pas en cours d'exécution."; \
	fi

# Nettoyage des fichiers PID
.PHONY: clean
clean:
	@echo "Nettoyage des fichiers PID..."
	@rm -f $(PID_DIR)/*.pid
	@echo "Fichiers PID nettoyés."

# Pause de tous les agents
.PHONY: pause
pause: pause-chef-projet pause-devops pause-dev-python pause-dev-frontend pause-dev-go pause-qa pause-perf pause-ml pause-analytics pause-product-owner pause-ux-designer
	@echo "Tous les agents ont été mis en pause"

# Reprise de tous les agents
.PHONY: resume
resume: resume-chef-projet resume-devops resume-dev-python resume-dev-frontend resume-dev-go resume-qa resume-perf resume-ml resume-analytics resume-product-owner resume-ux-designer
	@echo "Tous les agents en pause ont été repris"

# Pause de l'agent Chef de Projet
.PHONY: pause-chef-projet
pause-chef-projet:
	@if [ -f $(CHEF_PROJET_PID) ] && kill -0 `cat $(CHEF_PROJET_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent Chef de Projet..."; \
		kill -STOP `cat $(CHEF_PROJET_PID)`; \
		echo "Agent Chef de Projet mis en pause."; \
	else \
		echo "L'agent Chef de Projet n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent DevOps CI/CD
.PHONY: pause-devops
pause-devops:
	@if [ -f $(DEVOPS_PID) ] && kill -0 `cat $(DEVOPS_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent DevOps CI/CD..."; \
		kill -STOP `cat $(DEVOPS_PID)`; \
		echo "Agent DevOps CI/CD mis en pause."; \
	else \
		echo "L'agent DevOps CI/CD n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent Développeur Python
.PHONY: pause-dev-python
pause-dev-python:
	@if [ -f $(DEV_PYTHON_PID) ] && kill -0 `cat $(DEV_PYTHON_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent Développeur Python..."; \
		kill -STOP `cat $(DEV_PYTHON_PID)`; \
		echo "Agent Développeur Python mis en pause."; \
	else \
		echo "L'agent Développeur Python n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent Développeur Frontend
.PHONY: pause-dev-frontend
pause-dev-frontend:
	@if [ -f $(DEV_FRONTEND_PID) ] && kill -0 `cat $(DEV_FRONTEND_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent Développeur Frontend..."; \
		kill -STOP `cat $(DEV_FRONTEND_PID)`; \
		echo "Agent Développeur Frontend mis en pause."; \
	else \
		echo "L'agent Développeur Frontend n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent Développeur Go Backend
.PHONY: pause-dev-go
pause-dev-go:
	@if [ -f $(DEV_GO_BACKEND_PID) ] && kill -0 `cat $(DEV_GO_BACKEND_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent Développeur Go Backend..."; \
		kill -STOP `cat $(DEV_GO_BACKEND_PID)`; \
		echo "Agent Développeur Go Backend mis en pause."; \
	else \
		echo "L'agent Développeur Go Backend n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent QA
.PHONY: pause-qa
pause-qa:
	@if [ -f $(QA_PID) ] && kill -0 `cat $(QA_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent QA..."; \
		kill -STOP `cat $(QA_PID)`; \
		echo "Agent QA mis en pause."; \
	else \
		echo "L'agent QA n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent Performance
.PHONY: pause-perf
pause-perf:
	@if [ -f $(PERF_PID) ] && kill -0 `cat $(PERF_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent Performance..."; \
		kill -STOP `cat $(PERF_PID)`; \
		echo "Agent Performance mis en pause."; \
	else \
		echo "L'agent Performance n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent Chef de Projet
.PHONY: resume-chef-projet
resume-chef-projet:
	@if [ -f $(CHEF_PROJET_PID) ] && kill -0 `cat $(CHEF_PROJET_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent Chef de Projet..."; \
		kill -CONT `cat $(CHEF_PROJET_PID)`; \
		echo "Agent Chef de Projet repris."; \
	else \
		echo "L'agent Chef de Projet n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent DevOps CI/CD
.PHONY: resume-devops
resume-devops:
	@if [ -f $(DEVOPS_PID) ] && kill -0 `cat $(DEVOPS_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent DevOps CI/CD..."; \
		kill -CONT `cat $(DEVOPS_PID)`; \
		echo "Agent DevOps CI/CD repris."; \
	else \
		echo "L'agent DevOps CI/CD n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent Développeur Python
.PHONY: resume-dev-python
resume-dev-python:
	@if [ -f $(DEV_PYTHON_PID) ] && kill -0 `cat $(DEV_PYTHON_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent Développeur Python..."; \
		kill -CONT `cat $(DEV_PYTHON_PID)`; \
		echo "Agent Développeur Python repris."; \
	else \
		echo "L'agent Développeur Python n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent Développeur Frontend
.PHONY: resume-dev-frontend
resume-dev-frontend:
	@if [ -f $(DEV_FRONTEND_PID) ] && kill -0 `cat $(DEV_FRONTEND_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent Développeur Frontend..."; \
		kill -CONT `cat $(DEV_FRONTEND_PID)`; \
		echo "Agent Développeur Frontend repris."; \
	else \
		echo "L'agent Développeur Frontend n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent Développeur Go Backend
.PHONY: resume-dev-go
resume-dev-go:
	@if [ -f $(DEV_GO_BACKEND_PID) ] && kill -0 `cat $(DEV_GO_BACKEND_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent Développeur Go Backend..."; \
		kill -CONT `cat $(DEV_GO_BACKEND_PID)`; \
		echo "Agent Développeur Go Backend repris."; \
	else \
		echo "L'agent Développeur Go Backend n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent QA
.PHONY: resume-qa
resume-qa:
	@if [ -f $(QA_PID) ] && kill -0 `cat $(QA_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent QA..."; \
		kill -CONT `cat $(QA_PID)`; \
		echo "Agent QA repris."; \
	else \
		echo "L'agent QA n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent Performance
.PHONY: resume-perf
resume-perf:
	@if [ -f $(PERF_PID) ] && kill -0 `cat $(PERF_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent Performance..."; \
		kill -CONT `cat $(PERF_PID)`; \
		echo "Agent Performance repris."; \
	else \
		echo "L'agent Performance n'est pas en cours d'exécution."; \
	fi

# Démarrage de l'agent Machine Learning
.PHONY: start-ml
start-ml: $(PID_DIR)
	@echo "Démarrage de l'agent Machine Learning..."
	@if [ -f $(ML_PID) ] && kill -0 `cat $(ML_PID)` 2>/dev/null; then \
		echo "L'agent Machine Learning est déjà en cours d'exécution."; \
	else \
		cd $(ML_DIR) && $(VENV_DIR)/bin/python app.py & echo $$! > $(ML_PID); \
		echo "Agent Machine Learning démarré sur le port $(ML_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(ML_PORT)"; \
	fi

# Démarrage de l'agent Analytics/Monitoring
.PHONY: start-analytics
start-analytics: $(PID_DIR)
	@echo "Démarrage de l'agent Analytics/Monitoring..."
	@if [ -f $(ANALYTICS_PID) ] && kill -0 `cat $(ANALYTICS_PID)` 2>/dev/null; then \
		echo "L'agent Analytics/Monitoring est déjà en cours d'exécution."; \
	else \
		cd $(ANALYTICS_DIR) && $(VENV_DIR)/bin/python app.py & echo $$! > $(ANALYTICS_PID); \
		echo "Agent Analytics/Monitoring démarré sur le port $(ANALYTICS_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(ANALYTICS_PORT)"; \
	fi

# Démarrage de l'agent Product Owner
.PHONY: start-product-owner
start-product-owner: $(PID_DIR)
	@echo "Démarrage de l'agent Product Owner..."
	@if [ -f $(PRODUCT_OWNER_PID) ] && kill -0 `cat $(PRODUCT_OWNER_PID)` 2>/dev/null; then \
		echo "L'agent Product Owner est déjà en cours d'exécution."; \
	else \
		cd $(PRODUCT_OWNER_DIR) && $(VENV_DIR)/bin/python app.py & echo $$! > $(PRODUCT_OWNER_PID); \
		echo "Agent Product Owner démarré sur le port $(PRODUCT_OWNER_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(PRODUCT_OWNER_PORT)"; \
	fi

# Démarrage de l'agent UX Designer
.PHONY: start-ux-designer
start-ux-designer: $(PID_DIR)
	@echo "Démarrage de l'agent UX Designer..."
	@if [ -f $(UX_DESIGNER_PID) ] && kill -0 `cat $(UX_DESIGNER_PID)` 2>/dev/null; then \
		echo "L'agent UX Designer est déjà en cours d'exécution."; \
	else \
		cd $(UX_DESIGNER_DIR) && $(VENV_DIR)/bin/python app.py & echo $$! > $(UX_DESIGNER_PID); \
		echo "Agent UX Designer démarré sur le port $(UX_DESIGNER_PORT)"; \
		echo "Interface web disponible à l'adresse: http://localhost:$(UX_DESIGNER_PORT)"; \
	fi

# Arrêt de l'agent Machine Learning
.PHONY: stop-ml
stop-ml:
	@if [ -f $(ML_PID) ]; then \
		if kill -0 `cat $(ML_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent Machine Learning..."; \
			kill -15 `cat $(ML_PID)`; \
			rm $(ML_PID); \
			echo "Agent Machine Learning arrêté."; \
		else \
			echo "L'agent Machine Learning n'est pas en cours d'exécution."; \
			rm $(ML_PID); \
		fi \
	else \
		echo "L'agent Machine Learning n'est pas en cours d'exécution."; \
	fi

# Arrêt de l'agent Analytics/Monitoring
.PHONY: stop-analytics
stop-analytics:
	@if [ -f $(ANALYTICS_PID) ]; then \
		if kill -0 `cat $(ANALYTICS_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent Analytics/Monitoring..."; \
			kill -15 `cat $(ANALYTICS_PID)`; \
			rm $(ANALYTICS_PID); \
			echo "Agent Analytics/Monitoring arrêté."; \
		else \
			echo "L'agent Analytics/Monitoring n'est pas en cours d'exécution."; \
			rm $(ANALYTICS_PID); \
		fi \
	else \
		echo "L'agent Analytics/Monitoring n'est pas en cours d'exécution."; \
	fi

# Arrêt de l'agent Product Owner
.PHONY: stop-product-owner
stop-product-owner:
	@if [ -f $(PRODUCT_OWNER_PID) ]; then \
		if kill -0 `cat $(PRODUCT_OWNER_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent Product Owner..."; \
			kill -15 `cat $(PRODUCT_OWNER_PID)`; \
			rm $(PRODUCT_OWNER_PID); \
			echo "Agent Product Owner arrêté."; \
		else \
			echo "L'agent Product Owner n'est pas en cours d'exécution."; \
			rm $(PRODUCT_OWNER_PID); \
		fi \
	else \
		echo "L'agent Product Owner n'est pas en cours d'exécution."; \
	fi

# Arrêt de l'agent UX Designer
.PHONY: stop-ux-designer
stop-ux-designer:
	@if [ -f $(UX_DESIGNER_PID) ]; then \
		if kill -0 `cat $(UX_DESIGNER_PID)` 2>/dev/null; then \
			echo "Arrêt de l'agent UX Designer..."; \
			kill -15 `cat $(UX_DESIGNER_PID)`; \
			rm $(UX_DESIGNER_PID); \
			echo "Agent UX Designer arrêté."; \
		else \
			echo "L'agent UX Designer n'est pas en cours d'exécution."; \
			rm $(UX_DESIGNER_PID); \
		fi \
	else \
		echo "L'agent UX Designer n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent Machine Learning
.PHONY: pause-ml
pause-ml:
	@if [ -f $(ML_PID) ] && kill -0 `cat $(ML_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent Machine Learning..."; \
		kill -STOP `cat $(ML_PID)`; \
		echo "Agent Machine Learning mis en pause."; \
	else \
		echo "L'agent Machine Learning n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent Analytics/Monitoring
.PHONY: pause-analytics
pause-analytics:
	@if [ -f $(ANALYTICS_PID) ] && kill -0 `cat $(ANALYTICS_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent Analytics/Monitoring..."; \
		kill -STOP `cat $(ANALYTICS_PID)`; \
		echo "Agent Analytics/Monitoring mis en pause."; \
	else \
		echo "L'agent Analytics/Monitoring n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent Product Owner
.PHONY: pause-product-owner
pause-product-owner:
	@if [ -f $(PRODUCT_OWNER_PID) ] && kill -0 `cat $(PRODUCT_OWNER_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent Product Owner..."; \
		kill -STOP `cat $(PRODUCT_OWNER_PID)`; \
		echo "Agent Product Owner mis en pause."; \
	else \
		echo "L'agent Product Owner n'est pas en cours d'exécution."; \
	fi

# Pause de l'agent UX Designer
.PHONY: pause-ux-designer
pause-ux-designer:
	@if [ -f $(UX_DESIGNER_PID) ] && kill -0 `cat $(UX_DESIGNER_PID)` 2>/dev/null; then \
		echo "Mise en pause de l'agent UX Designer..."; \
		kill -STOP `cat $(UX_DESIGNER_PID)`; \
		echo "Agent UX Designer mis en pause."; \
	else \
		echo "L'agent UX Designer n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent Machine Learning
.PHONY: resume-ml
resume-ml:
	@if [ -f $(ML_PID) ] && kill -0 `cat $(ML_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent Machine Learning..."; \
		kill -CONT `cat $(ML_PID)`; \
		echo "Agent Machine Learning repris."; \
	else \
		echo "L'agent Machine Learning n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent Analytics/Monitoring
.PHONY: resume-analytics
resume-analytics:
	@if [ -f $(ANALYTICS_PID) ] && kill -0 `cat $(ANALYTICS_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent Analytics/Monitoring..."; \
		kill -CONT `cat $(ANALYTICS_PID)`; \
		echo "Agent Analytics/Monitoring repris."; \
	else \
		echo "L'agent Analytics/Monitoring n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent Product Owner
.PHONY: resume-product-owner
resume-product-owner:
	@if [ -f $(PRODUCT_OWNER_PID) ] && kill -0 `cat $(PRODUCT_OWNER_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent Product Owner..."; \
		kill -CONT `cat $(PRODUCT_OWNER_PID)`; \
		echo "Agent Product Owner repris."; \
	else \
		echo "L'agent Product Owner n'est pas en cours d'exécution."; \
	fi

# Reprise de l'agent UX Designer
.PHONY: resume-ux-designer
resume-ux-designer:
	@if [ -f $(UX_DESIGNER_PID) ] && kill -0 `cat $(UX_DESIGNER_PID)` 2>/dev/null; then \
		echo "Reprise de l'agent UX Designer..."; \
		kill -CONT `cat $(UX_DESIGNER_PID)`; \
		echo "Agent UX Designer repris."; \
	else \
		echo "L'agent UX Designer n'est pas en cours d'exécution."; \
	fi

# Affichage de l'état des agents
.PHONY: status
status:
	@echo "État des agents:"
	@if [ -f $(CHEF_PROJET_PID) ] && kill -0 `cat $(CHEF_PROJET_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(CHEF_PROJET_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent Chef de Projet:    EN PAUSE (PID: `cat $(CHEF_PROJET_PID)`)"; \
		else \
			echo "  - Agent Chef de Projet:    EN COURS D'EXÉCUTION (PID: `cat $(CHEF_PROJET_PID)`)"; \
		fi; \
	else \
		echo "  - Agent Chef de Projet:    ARRÊTÉ"; \
	fi
	@if [ -f $(DEVOPS_PID) ] && kill -0 `cat $(DEVOPS_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(DEVOPS_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent DevOps CI/CD:      EN PAUSE (PID: `cat $(DEVOPS_PID)`)"; \
		else \
			echo "  - Agent DevOps CI/CD:      EN COURS D'EXÉCUTION (PID: `cat $(DEVOPS_PID)`)"; \
		fi; \
	else \
		echo "  - Agent DevOps CI/CD:      ARRÊTÉ"; \
	fi
	@if [ -f $(DEV_PYTHON_PID) ] && kill -0 `cat $(DEV_PYTHON_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(DEV_PYTHON_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent Développeur Python: EN PAUSE (PID: `cat $(DEV_PYTHON_PID)`)"; \
		else \
			echo "  - Agent Développeur Python: EN COURS D'EXÉCUTION (PID: `cat $(DEV_PYTHON_PID)`)"; \
		fi; \
	else \
		echo "  - Agent Développeur Python: ARRÊTÉ"; \
	fi
	@if [ -f $(DEV_FRONTEND_PID) ] && kill -0 `cat $(DEV_FRONTEND_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(DEV_FRONTEND_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent Dev Frontend:      EN PAUSE (PID: `cat $(DEV_FRONTEND_PID)`)"; \
		else \
			echo "  - Agent Dev Frontend:      EN COURS D'EXÉCUTION (PID: `cat $(DEV_FRONTEND_PID)`)"; \
		fi; \
	else \
		echo "  - Agent Dev Frontend:      ARRÊTÉ"; \
	fi
	@if [ -f $(DEV_GO_BACKEND_PID) ] && kill -0 `cat $(DEV_GO_BACKEND_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(DEV_GO_BACKEND_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent Dev Go Backend:    EN PAUSE (PID: `cat $(DEV_GO_BACKEND_PID)`)"; \
		else \
			echo "  - Agent Dev Go Backend:    EN COURS D'EXÉCUTION (PID: `cat $(DEV_GO_BACKEND_PID)`)"; \
		fi; \
	else \
		echo "  - Agent Dev Go Backend:    ARRÊTÉ"; \
	fi
	@if [ -f $(QA_PID) ] && kill -0 `cat $(QA_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(QA_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent QA:                EN PAUSE (PID: `cat $(QA_PID)`)"; \
		else \
			echo "  - Agent QA:                EN COURS D'EXÉCUTION (PID: `cat $(QA_PID)`)"; \
		fi; \
	else \
		echo "  - Agent QA:                ARRÊTÉ"; \
	fi
	@if [ -f $(PERF_PID) ] && kill -0 `cat $(PERF_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(PERF_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent Performance:       EN PAUSE (PID: `cat $(PERF_PID)`)"; \
		else \
			echo "  - Agent Performance:       EN COURS D'EXÉCUTION (PID: `cat $(PERF_PID)`)"; \
		fi; \
	else \
		echo "  - Agent Performance:       ARRÊTÉ"; \
	fi
	@if [ -f $(ML_PID) ] && kill -0 `cat $(ML_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(ML_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent Machine Learning:  EN PAUSE (PID: `cat $(ML_PID)`)"; \
		else \
			echo "  - Agent Machine Learning:  EN COURS D'EXÉCUTION (PID: `cat $(ML_PID)`)"; \
		fi; \
	else \
		echo "  - Agent Machine Learning:  ARRÊTÉ"; \
	fi
	@if [ -f $(ANALYTICS_PID) ] && kill -0 `cat $(ANALYTICS_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(ANALYTICS_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent Analytics/Monitoring: EN PAUSE (PID: `cat $(ANALYTICS_PID)`)"; \
		else \
			echo "  - Agent Analytics/Monitoring: EN COURS D'EXÉCUTION (PID: `cat $(ANALYTICS_PID)`)"; \
		fi; \
	else \
		echo "  - Agent Analytics/Monitoring: ARRÊTÉ"; \
	fi
	@if [ -f $(PRODUCT_OWNER_PID) ] && kill -0 `cat $(PRODUCT_OWNER_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(PRODUCT_OWNER_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent Product Owner:     EN PAUSE (PID: `cat $(PRODUCT_OWNER_PID)`)"; \
		else \
			echo "  - Agent Product Owner:     EN COURS D'EXÉCUTION (PID: `cat $(PRODUCT_OWNER_PID)`)"; \
		fi; \
	else \
		echo "  - Agent Product Owner:     ARRÊTÉ"; \
	fi
	@if [ -f $(UX_DESIGNER_PID) ] && kill -0 `cat $(UX_DESIGNER_PID)` 2>/dev/null; then \
		STATUS=$$(ps -o state= -p `cat $(UX_DESIGNER_PID)` 2>/dev/null | tr -d ' '); \
		if [ "$$STATUS" = "T" ]; then \
			echo "  - Agent UX Designer:       EN PAUSE (PID: `cat $(UX_DESIGNER_PID)`)"; \
		else \
			echo "  - Agent UX Designer:       EN COURS D'EXÉCUTION (PID: `cat $(UX_DESIGNER_PID)`)"; \
		fi; \
	else \
		echo "  - Agent UX Designer:       ARRÊTÉ"; \
	fi