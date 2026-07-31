"""Service pour la gestion des relances et notifications WhatsApp."""
import urllib.parse
import logging
from app.models import database

logger = logging.getLogger(__name__)

def generate_whatsapp_link(task):
    """Génère un lien direct WhatsApp wa.me avec un message personnalisé et pré-rempli."""
    phone = task.get('collaborator_phone')
    if not phone and task.get('collaborator_id'):
        collab = database.get_collaborateur(task['collaborator_id'])
        if collab:
            phone = collab.get('phone')

    if not phone:
        return None, "Aucun numéro de téléphone renseigné pour ce collaborateur."

    clean_phone = ''.join(c for c in str(phone) if c.isdigit())
    if not clean_phone:
        return None, "Numéro de téléphone invalide."

    base_url = "http://127.0.0.1:5000"
    try:
        settings = database.get_settings()
        if settings and settings.get('base_url'):
            base_url = settings['base_url'].rstrip('/')
    except Exception:
        pass

    task_url = f"{base_url}/t/{task['update_token']}" if task.get('update_token') else base_url

    title = task.get('title', 'Tâche')
    due = task.get('due_date') or 'Non spécifiée'
    collab_name = task.get('collaborator_name', 'Collaborateur')

    msg = (
        f"Bonjour {collab_name},\n\n"
        f"📢 Rappel concernant la tâche : *{title}*\n"
        f"📅 Échéance : {due}\n"
        f"⚡ Priorité : {task.get('priority', 'Normale')}\n\n"
        f"🔗 Merci de consulter et mettre à jour votre tâche via ce lien :\n{task_url}"
    )

    encoded_msg = urllib.parse.quote(msg)
    whatsapp_url = f"https://wa.me/{clean_phone}?text={encoded_msg}"
    return whatsapp_url, "Lien WhatsApp généré."

def send_whatsapp_relance(task_id):
    """Enregistre l'historique et génère le lien direct WhatsApp."""
    task = database.get_tache(task_id)
    if not task:
        return False, "Tâche introuvable.", None

    url, msg = generate_whatsapp_link(task)
    if not url:
        database.log_reminder(task_id, 'whatsapp', False, msg)
        return False, msg, None

    database.log_reminder(task_id, 'whatsapp', True, f"Relance WhatsApp préparée pour {task.get('collaborator_name')}")
    return True, "Relance WhatsApp prête.", url
