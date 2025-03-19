#!/usr/bin/env python3
import os
import re

# Chemin du fichier à modifier
file_path = "/home/adrien.parrochia/go/src/github.com/agentsIA/agentChefProjet/python/app.py"

# Lire le contenu du fichier
with open(file_path, 'r') as file:
    content = file.read()

# Remplacer socketio.emit('log', ...) par safe_emit('log', ...)
modified_content = re.sub(r"socketio\.emit\('log'", r"safe_emit('log'", content)

# Remplacer socketio.emit('loading_start') par safe_emit('loading_start')
modified_content = re.sub(r"socketio\.emit\('loading_start'", r"safe_emit('loading_start'", modified_content)

# Remplacer socketio.emit('loading_end') par safe_emit('loading_end')
modified_content = re.sub(r"socketio\.emit\('loading_end'", r"safe_emit('loading_end'", modified_content)

# Remplacer socketio.emit('specifications_update', par safe_emit('specifications_update',
modified_content = re.sub(r"socketio\.emit\('specifications_update'", r"safe_emit('specifications_update'", modified_content)

# Remplacer socketio.emit('tasks_update', par safe_emit('tasks_update',
modified_content = re.sub(r"socketio\.emit\('tasks_update'", r"safe_emit('tasks_update'", modified_content)

# Remplacer socketio.emit('test_plan_update', par safe_emit('test_plan_update',
modified_content = re.sub(r"socketio\.emit\('test_plan_update'", r"safe_emit('test_plan_update'", modified_content)

# Remplacer socketio.emit('wait_for_user_action', par safe_emit('wait_for_user_action',
modified_content = re.sub(r"socketio\.emit\('wait_for_user_action'", r"safe_emit('wait_for_user_action'", modified_content)

# Remplacer socketio.emit('dev_response_update', par safe_emit('dev_response_update',
modified_content = re.sub(r"socketio\.emit\('dev_response_update'", r"safe_emit('dev_response_update'", modified_content)

# Remplacer socketio.emit('qa_response_update', par safe_emit('qa_response_update',
modified_content = re.sub(r"socketio\.emit\('qa_response_update'", r"safe_emit('qa_response_update'", modified_content)

# Remplacer socketio.emit('product_owner_response_update', par safe_emit('product_owner_response_update',
modified_content = re.sub(r"socketio\.emit\('product_owner_response_update'", r"safe_emit('product_owner_response_update'", modified_content)

# Remplacer socketio.emit('ux_designer_response_update', par safe_emit('ux_designer_response_update',
modified_content = re.sub(r"socketio\.emit\('ux_designer_response_update'", r"safe_emit('ux_designer_response_update'", modified_content)

# Remplacer socketio.emit('performance_response_update', par safe_emit('performance_response_update',
modified_content = re.sub(r"socketio\.emit\('performance_response_update'", r"safe_emit('performance_response_update'", modified_content)

# Remplacer socketio.emit('ml_response_update', par safe_emit('ml_response_update',
modified_content = re.sub(r"socketio\.emit\('ml_response_update'", r"safe_emit('ml_response_update'", modified_content)

# Remplacer socketio.emit('analytics_response_update', par safe_emit('analytics_response_update',
modified_content = re.sub(r"socketio\.emit\('analytics_response_update'", r"safe_emit('analytics_response_update'", modified_content)

# Remplacer socketio.emit('frontend_response_update', par safe_emit('frontend_response_update',
modified_content = re.sub(r"socketio\.emit\('frontend_response_update'", r"safe_emit('frontend_response_update'", modified_content)

# Remplacer socketio.emit('suggestions_update', par safe_emit('suggestions_update',
modified_content = re.sub(r"socketio\.emit\('suggestions_update'", r"safe_emit('suggestions_update'", modified_content)

# Remplacer socketio.emit('project_complete', par safe_emit('project_complete',
modified_content = re.sub(r"socketio\.emit\('project_complete'", r"safe_emit('project_complete'", modified_content)

# Vérifier si le contenu a été modifié
if content != modified_content:
    # Écrire le contenu modifié dans le fichier
    with open(file_path, 'w') as file:
        file.write(modified_content)
    print(f"✅ Tous les appels 'socketio.emit' ont été remplacés par 'safe_emit' dans {file_path}")
else:
    print("⚠️ Aucune modification n'a été effectuée dans le fichier")