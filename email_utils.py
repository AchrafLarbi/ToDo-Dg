"""Envoi d'emails via SMTP (Outlook / Office 365) et journalisation dans l'historique."""
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import database


def _send_raw(to_addr, subject, body):
    settings = database.get_settings()
    if not settings['smtp_user'] or not settings['smtp_password']:
        return False, "Parametres SMTP incomplets (adresse ou mot de passe manquant)."

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"{settings['sender_name']} <{settings['smtp_user']}>"
    msg['To'] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings['smtp_host'], settings['smtp_port'], timeout=20) as smtp:
            smtp.starttls()
            smtp.login(settings['smtp_user'], settings['smtp_password'])
            smtp.send_message(msg)
        return True, "Email envoye avec succes."
    except Exception as exc:  # smtplib / socket errors
        return False, f"Echec de l'envoi : {exc}"


def _task_link(task):
    settings = database.get_settings()
    if not settings['base_url'] or not task['update_token']:
        return None
    return f"{settings['base_url']}/t/{task['update_token']}"


def send_test_email():
    settings = database.get_settings()
    if not settings['smtp_user']:
        return False, "Aucune adresse email configuree."
    return _send_raw(
        settings['smtp_user'],
        "Test - Gestion des taches",
        "Ceci est un email de test envoye depuis l'application Gestion des taches.",
    )


def send_task_notification(task_id):
    task = database.get_tache(task_id)
    if not task or not task['collaborator_email']:
        return
    link = _task_link(task)
    subject = f"Nouvelle tache assignee : {task['title']}"
    body = (
        f"Bonjour {task['collaborator_name']},\n\n"
        f"Une nouvelle tache vous a ete assignee : {task['title']}\n"
        f"Projet : {task['project_name'] or '-'}\n"
        f"Priorite : {task['priority']}\n"
        f"Sensibilite : {task['sensitivity']}\n"
        f"Echeance : {task['due_date'] or 'non definie'}\n\n"
        f"{task['description'] or ''}\n"
    )
    if link:
        body += f"\nPour suivre ou mettre a jour cette tache : {link}\n"
    success, message = _send_raw(task['collaborator_email'], subject, body)
    database.log_reminder(task_id, 'creation', success, message)


def send_reminder(task_id, reminder_type='manuelle'):
    task = database.get_tache(task_id)
    if not task or not task['collaborator_email']:
        return False, "Aucun collaborateur avec email n'est assigne a cette tache."
    link = _task_link(task)
    urgence = "EN RETARD" if reminder_type == 'retard' else "ECHEANCE PROCHE"
    subject = f"[{urgence}] Rappel : tache {task['title']}"
    body = (
        f"Bonjour {task['collaborator_name']},\n\n"
        f"Rappel concernant la tache : {task['title']}\n"
        f"Projet : {task['project_name'] or '-'}\n"
        f"Priorite : {task['priority']}\n"
        f"Sensibilite : {task['sensitivity']}\n"
        f"Echeance : {task['due_date'] or 'non definie'}\n"
        f"Statut actuel : {task['status']}\n\n"
        f"{task['description'] or ''}\n"
    )
    if link:
        body += (
            f"\nVous pouvez mettre a jour le statut, proposer une nouvelle echeance et "
            f"expliquer la situation directement ici : {link}\n"
        )
    success, message = _send_raw(task['collaborator_email'], subject, body)
    database.log_reminder(task_id, reminder_type, success, message)
    if success:
        database.register_reminder_sent(task_id, datetime.now(timezone.utc).isoformat(timespec='seconds'))
    return success, message


def notify_admin_of_collaborator_update(task_id, new_status, new_due_date, comment):
    """Previent l'administrateur (adresse SMTP configuree) quand un collaborateur met a jour sa tache."""
    task = database.get_tache(task_id)
    settings = database.get_settings()
    if not task or not settings['smtp_user']:
        return
    subject = f"Mise a jour collaborateur : {task['title']}"
    body = (
        f"{task['collaborator_name'] or 'Un collaborateur'} a mis a jour la tache '{task['title']}'.\n\n"
        f"Nouveau statut : {new_status}\n"
        f"Nouvelle echeance : {new_due_date or '(inchangee)'}\n"
        f"Commentaire : {comment or '(aucun)'}\n"
    )
    _send_raw(settings['smtp_user'], subject, body)
