#!/bin/bash

# Script pour nettoyer les processus Python bloqués sur tous les ports utilisés par les agents

# Définition des ports utilisés par les agents
PORTS="5000 5001 5002 5003 5004 5005 5006 5007 5008 5009 5010 5015"

for PORT in $PORTS; do
    # Trouver tous les processus Python écoutant sur le port
    echo "Recherche des processus Python sur le port $PORT..."
    PIDS=$(lsof -i :$PORT -sTCP:LISTEN -t)

    if [ -z "$PIDS" ]; then
        echo "Aucun processus en écoute sur le port $PORT."
    else
        echo "Processus trouvés sur le port $PORT: $PIDS"
        echo "Tentative d'arrêt propre..."
        
        for PID in $PIDS; do
            echo "Envoi de SIGTERM au processus $PID..."
            kill -15 $PID 2>/dev/null
        done
        
        # Attendre un peu pour laisser les processus s'arrêter proprement
        sleep 1
        
        # Vérifier si les processus sont toujours en cours d'exécution
        REMAINING_PIDS=$(lsof -i :$PORT -sTCP:LISTEN -t)
        if [ -n "$REMAINING_PIDS" ]; then
            echo "Certains processus n'ont pas été arrêtés proprement. Forçage de l'arrêt..."
            for PID in $REMAINING_PIDS; do
                echo "Envoi de SIGKILL au processus $PID..."
                kill -9 $PID 2>/dev/null
            done
        fi
    fi
done

# Nettoyage des fichiers PID potentiellement obsolètes
echo "Nettoyage des fichiers PID..."
find "$(dirname "$0")/pids" -name "*.pid" -type f -exec rm -v {} \;

# Vérification finale
FINAL_CHECK=$(lsof -i :5000 -sTCP:LISTEN -t)
if [ -z "$FINAL_CHECK" ]; then
    echo "Nettoyage réussi! Le port 5000 est libre."
else
    echo "ATTENTION: Des processus sont toujours en écoute sur le port 5000: $FINAL_CHECK"
    echo "Utilisez 'lsof -i :5000' pour plus de détails."
fi