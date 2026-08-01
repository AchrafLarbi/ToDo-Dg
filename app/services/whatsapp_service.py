"""Service pour la gestion des relances et notifications WhatsApp (Automatique & Fallback)."""
import json
import logging
import urllib.parse
import urllib.request
from app.models import database

logger = logging.getLogger(__name__)

GATEWAY_URL = "http://127.0.0.1:3001"


def get_default_country_code():
    """Récupère l'indicatif de pays par défaut depuis la base de données."""
    try:
        settings = database.get_settings()
        if settings and settings.get('whatsapp_country_code'):
            code = ''.join(c for c in str(settings['whatsapp_country_code']) if c.isdigit())
            if code:
                return code
    except Exception:
        pass
    return '213'


def format_phone_number(phone):
    """Formate un numéro de téléphone avec l'indicatif paramétré."""
    if not phone:
        return None
    clean_phone = ''.join(c for c in str(phone) if c.isdigit())
    if not clean_phone:
        return None

    country_code = get_default_country_code()
    if clean_phone.startswith('00'):
        clean_phone = clean_phone[2:]
    elif clean_phone.startswith('0') and len(clean_phone) in (9, 10):
        clean_phone = country_code + clean_phone[1:]

    return clean_phone


def send_whatsapp_auto(clean_phone, msg):
    """Tente d'envoyer le message via le service WhatsApp Gateway (port 3001)."""
    try:
        data = json.dumps({"phone": clean_phone, "message": msg}).encode('utf-8')
        req = urllib.request.Request(
            f"{GATEWAY_URL}/send",
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode('utf-8'))
                return result.get('success', False), result.get('message', 'Message envoyé.')
    except Exception as e:
        logger.warning(f"WhatsApp Gateway inaccessible ou non connecté: {e}")
    return False, "Gateway non disponible"


def build_whatsapp_message(task):
    """Construit le texte du message de relance sans icônes."""
    base_url = "http://localhost:5000"
    try:
        settings = database.get_settings()
        if settings and settings.get('base_url'):
            base_url = settings['base_url'].rstrip('/')
            if "127.0.0.1" in base_url:
                base_url = base_url.replace("127.0.0.1", "localhost")
    except Exception:
        pass

    task_url = f"{base_url}/t/{task['update_token']}" if task.get('update_token') else base_url
    title = task.get('title', 'Tâche')
    due = task.get('due_date') or 'Non spécifiée'
    collab_name = task.get('collaborator_name', 'Collaborateur')

    return (
        f"Bonjour {collab_name},\n\n"
        f"Rappel concernant la tâche : *{title}*\n"
        f"Échéance : {due}\n"
        f"Priorité : {task.get('priority', 'Normale')}\n\n"
        f"Lien de votre tâche :\n"
        f"{task_url}\n"
    )


def generate_whatsapp_link(task, custom_phone=None):
    """Génère un lien direct WhatsApp wa.me avec un message personnalisé et pré-rempli."""
    phone = custom_phone or task.get('collaborator_phone')
    if not phone and task.get('collaborator_id'):
        collab = database.get_collaborateur(task['collaborator_id'])
        if collab:
            phone = collab.get('phone')

    clean_phone = format_phone_number(phone)
    if not clean_phone:
        return None, "Aucun numéro de téléphone valide renseigné."

    msg = build_whatsapp_message(task)
    encoded_msg = urllib.parse.quote(msg.encode('utf-8'))
    whatsapp_url = f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}"
    return whatsapp_url, "Lien WhatsApp généré."


def send_whatsapp_relance(task_id, custom_phone=None):
    """Envoie automatiquement le message via la Gateway WhatsApp ou fournit le lien fallback."""
    task = database.get_tache(task_id)
    if not task:
        return False, "Tâche introuvable.", None

    phone = custom_phone or task.get('collaborator_phone')
    if not phone and task.get('collaborator_id'):
        collab = database.get_collaborateur(task['collaborator_id'])
        if collab:
            phone = collab.get('phone')

    clean_phone = format_phone_number(phone)
    if not clean_phone:
        database.log_reminder(task_id, 'whatsapp', False, "Aucun numéro de téléphone valide.")
        return False, "Aucun numéro de téléphone valide renseigné.", None

    msg = build_whatsapp_message(task)
    collab_name = task.get('collaborator_name', 'Collaborateur')

    # 1. Tente l'envoi automatique via la Gateway WhatsApp (arrière-plan sans popup)
    sent, gate_msg = send_whatsapp_auto(clean_phone, msg)
    if sent:
        database.log_reminder(task_id, 'whatsapp', True, f"Relance WhatsApp envoyée à {clean_phone} ({collab_name})")
        return True, f"Relance WhatsApp envoyée au {clean_phone} ({collab_name}) !", None

    # 2. Fallback si Gateway non connectée / non démarrée
    encoded_msg = urllib.parse.quote(msg.encode('utf-8'))
    whatsapp_url = f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}"
    database.log_reminder(task_id, 'whatsapp', True, f"Relance WhatsApp préparée pour {clean_phone}")
    return True, f"Relance WhatsApp prête pour {clean_phone}. Redirection...", whatsapp_url
