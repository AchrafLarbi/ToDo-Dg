"""Service d'envoi d'emails (Outlook / Office 365, Brevo, SendGrid, etc.)

Supports direct Brevo REST API over HTTPS (Port 443) to completely bypass Cloud/Render firewall blocks on SMTP ports.
"""
import json
import logging
import smtplib
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage

from app.models import database

logger = logging.getLogger(__name__)

# Timeout court de 5s par tentative
SMTP_TIMEOUT = 5
MAX_ADDRESSES_PER_HOST = 1
MAX_ATTEMPTS = 1


def _create_ipv4_connection(host, port, timeout, source_address=None):
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        ip = host

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if timeout is not None:
        sock.settimeout(timeout)
    if source_address:
        sock.bind(source_address)
    sock.connect((ip, port))
    return sock


class _IPv4SMTP(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        return _create_ipv4_connection(host, port, timeout, self.source_address)


class _IPv4SMTP_SSL(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        raw_socket = _create_ipv4_connection(host, port, timeout, self.source_address)
        return self.context.wrap_socket(raw_socket, server_hostname=self._host)


def _friendly_error(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "Authentification refusée par le serveur (erreur 535). "
            "Vérifiez l'adresse email et le mot de passe / clé SMTP."
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return f"Adresse expéditeur refusée : {exc}."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return f"Destinataire refusé par le serveur : {exc}."
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return f"Connexion au serveur SMTP expirée ({exc}). Réessayez ultérieurement."
    if isinstance(exc, (smtplib.SMTPConnectError, ConnectionError, ssl.SSLError, OSError)):
        return f"Impossible de se connecter au serveur SMTP ({exc}). Les ports 465/587 sont peut-être bloqués par l'hébergeur."
    return f"Échec de l'envoi : {exc}"


_TRANSIENT_NETWORK_ERRORS = (smtplib.SMTPConnectError, ConnectionError, socket.timeout,
                              TimeoutError, ssl.SSLError, OSError)


def _open_connection(host, port, timeout):
    context = ssl.create_default_context()
    if int(port) == 465:
        return _IPv4SMTP_SSL(host, port, timeout=timeout, context=context)
    smtp = _IPv4SMTP(host, port, timeout=timeout)
    smtp.ehlo()
    smtp.starttls(context=context)
    smtp.ehlo()
    return smtp


def _send_brevo_api(to_addr, subject, body, html_body, sender_name, from_email, api_key):
    """Envoi ultra-rapide via l'API REST HTTP Brevo (Port 443 HTTPS).
    
    Bypasse a 100% les blocages de pare-feu Cloud (Render, AWS, DigitalOcean) sur les ports SMTP.
    Rend la reponse en ~150 millisecondes.
    """
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": sender_name, "email": from_email},
        "to": [{"email": to_addr}],
        "subject": subject,
        "textContent": body,
    }
    if html_body:
        payload["htmlContent"] = html_body

    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
        "user-agent": "ToDo-Dg/1.0",
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status in (200, 201, 202):
                return True, "Email envoyé avec succès."
            return False, f"Brevo API status: {resp.status}"
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode('utf-8', errors='ignore')
        logger.warning("Brevo API HTTPError %s: %s", exc.code, err_body)
        if exc.code == 401:
            return False, "Authentification Brevo refusée (Clé SMTP / API invalide)."
        return False, f"Erreur Brevo API ({exc.code}) : {err_body}"
    except Exception as exc:
        logger.warning("Brevo API error: %s", exc)
        return False, str(exc)


def _send_raw(to_addr, subject, body, html_body=None):
    try:
        settings = database.get_settings()
    except Exception as exc:
        logger.exception("Lecture des paramètres SMTP impossible")
        return False, f"Erreur de base de données : {exc}"

    if not settings:
        return False, "Paramètres introuvables. Enregistrez d'abord vos paramètres."

    host = settings['smtp_host'] or ''
    port = settings['smtp_port'] or 587
    user = settings['smtp_user']
    password = settings['smtp_password']
    sender_name = settings['sender_name'] or 'Gestion des taches'
    from_email = settings.get('sender_email') or user

    if not host:
        return False, "Serveur SMTP non configuré dans les paramètres."
    if not user or not password:
        return False, "Paramètres SMTP incomplets : le login SMTP et la clé SMTP sont obligatoires."
    if not to_addr:
        return False, "Aucun destinataire pour cet email."

    # Si la clé est une clé API Brevo REST (xkeysib-), on utilise l'API REST HTTPS
    if password.startswith('xkeysib-'):
        ok, msg_api = _send_brevo_api(to_addr, subject, body, html_body, sender_name, from_email, password)
        if ok:
            return True, msg_api

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"{sender_name} <{from_email}>"
    msg['To'] = to_addr
    msg.set_content(body)

    if html_body:
        msg.add_alternative(html_body, subtype='html')

    # Priorité au port configuré, puis 587, 465, 2525
    ports_to_try = [int(port), 587, 465, 2525]
    unique_ports = []
    for p in ports_to_try:
        if p not in unique_ports:
            unique_ports.append(p)

    last_exc = None
    for attempt_port in unique_ports:
        try:
            with _open_connection(host, attempt_port, SMTP_TIMEOUT) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
            return True, "Email envoyé avec succès."
        except smtplib.SMTPAuthenticationError as exc:
            logger.warning("Authentification SMTP refusée : %s", exc)
            return False, _friendly_error(exc)
        except _TRANSIENT_NETWORK_ERRORS as exc:
            logger.warning("Connexion SMTP échouée sur le port %s : %s", attempt_port, exc)
            last_exc = exc
            continue
        except Exception as exc:
            logger.exception("Échec inattendu de l'envoi de l'email")
            return False, _friendly_error(exc)

    return False, _friendly_error(last_exc)


def _task_link(task):
    settings = database.get_settings()
    if not settings or not settings['base_url'] or not task['update_token']:
        return None
    return f"{settings['base_url']}/t/{task['update_token']}"


def send_test_email(recipient=None):
    try:
        settings = database.get_settings()
    except Exception as exc:
        logger.exception("Lecture des paramètres impossible")
        return False, f"Erreur de base de données : {exc}"
    if not settings or not settings['smtp_user']:
        return False, "Aucune adresse email configurée. Renseignez vos paramètres SMTP."
    destinataire = (recipient or '').strip() or settings.get('sender_email') or settings['smtp_user']
    
    body = (
        "Bonjour,\n\n"
        "Ceci est un email de test envoyé depuis l'application Gestion des tâches.\n"
        "Si vous recevez ce message, la configuration SMTP fonctionne correctement."
    )
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 12px; background-color: #ffffff;">
      <h2 style="color: #4f46e5; margin-top: 0;">Test d'envoi d'email</h2>
      <p style="color: #334155; font-size: 14px; line-height: 1.5;">
        Ceci est un email de test envoyé à <strong>{destinataire}</strong> depuis l'application <strong>Gestion des tâches</strong>.
      </p>
      <div style="background-color: #f0fdf4; border-left: 4px solid #22c55e; padding: 12px; margin: 16px 0; font-size: 13px; color: #15803d;">
        ✓ La configuration SMTP est fonctionnelle et prête à envoyer des notifications.
      </div>
    </div>
    """
    return _send_raw(destinataire, "Test - Gestion des tâches", body, html_body)


def send_task_notification(task_id):
    try:
        task = database.get_tache(task_id)
        if not task or not task['collaborator_email']:
            return
        link = _task_link(task)
        collab_name = task['collaborator_name'] or "Collaborateur"
        
        subject = f"Une tâche vous a été affectée : {task['title']}"
        
        rec_type = task.get('recurrence_type', 'Aucune')
        body = (
            f"Bonjour {collab_name},\n\n"
            f"Une tâche vous a été affectée.\n\n"
            f"• Titre : {task['title']}\n"
            f"• Projet : {task['project_name'] or '-'}\n"
            f"• Échéance : {task['due_date'] or 'Non définie'}\n"
            f"• Priorité : {task['priority']}\n"
            f"• Sensibilité : {task['sensitivity']}\n"
            f"• Récurrence : {rec_type}\n\n"
            f"Description :\n{task['description'] or 'Aucune'}\n\n"
        )
        if link:
            body += f"Mettre à jour la tâche : {link}\n"

        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background-color: #ffffff;">
          <h2 style="color: #1e293b; margin-top: 0; font-size: 20px;">Bonjour {collab_name},</h2>
          <p style="color: #475569; font-size: 15px; font-weight: 500; margin-bottom: 20px;">
            Une tâche vous a été affectée.
          </p>

          <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px;">
            <thead>
              <tr style="background-color: #f8fafc; border-bottom: 2px solid #e2e8f0; text-align: left;">
                <th style="padding: 10px; color: #475569;">Champ</th>
                <th style="padding: 10px; color: #475569;">Détail</th>
              </tr>
            </thead>
            <tbody>
              <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 10px; font-weight: bold; color: #334155;">Titre de la tâche</td>
                <td style="padding: 10px; color: #0f172a; font-weight: bold;">{task['title']}</td>
              </tr>
              <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 10px; font-weight: bold; color: #334155;">Projet</td>
                <td style="padding: 10px; color: #334155;">{task['project_name'] or '-'}</td>
              </tr>
              <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 10px; font-weight: bold; color: #334155;">Échéance</td>
                <td style="padding: 10px; color: #dc2626; font-weight: bold;">{task['due_date'] or 'Non définie'}</td>
              </tr>
              <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 10px; font-weight: bold; color: #334155;">Priorité</td>
                <td style="padding: 10px; color: #334155;">{task['priority']}</td>
              </tr>
              <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 10px; font-weight: bold; color: #334155;">Sensibilité</td>
                <td style="padding: 10px; color: #334155;">{task['sensitivity']}</td>
              </tr>
              <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 10px; font-weight: bold; color: #334155;">Type de récurrence</td>
                <td style="padding: 10px; color: #334155;">{rec_type}</td>
              </tr>
              {'<tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 10px; font-weight: bold; color: #334155;">Description</td><td style="padding: 10px; color: #334155;">' + str(task['description']) + '</td></tr>' if task['description'] else ''}
            </tbody>
          </table>

          {f'<div style="text-align: center; margin-top: 24px;"><a href="{link}" style="display: inline-block; background-color: #4f46e5; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; font-size: 14px;">Mettre à jour cette tâche</a></div>' if link else ''}
        </div>
        """
        success, message = _send_raw(task['collaborator_email'], subject, body, html_body)
        database.log_reminder(task_id, 'creation', success, message)
    except Exception:
        logger.exception("Échec de la notification de création de tâche %s", task_id)


def send_task_notification_async(task_id):
    thread = threading.Thread(target=send_task_notification, args=(task_id,), daemon=True)
    thread.start()


def send_reminder(task_id, reminder_type='manuelle'):
    task = database.get_tache(task_id)
    if not task or not task['collaborator_email']:
        return False, "Aucun collaborateur avec email n'est assigné à cette tâche."
    link = _task_link(task)
    collab_name = task['collaborator_name'] or "Collaborateur"
    is_overdue = reminder_type == 'retard' or (task['due_date'] and task['due_date'] < datetime.now().strftime('%Y-%m-%d'))
    urgence = "EN RETARD" if is_overdue else "ÉCHÉANCE PROCHE"
    
    subject = f"[{urgence}] Rappel de tâche : {task['title']}"
    
    body = (
        f"Bonjour {collab_name},\n\n"
        f"Alerte : la tâche suivante est {urgence.lower()}.\n\n"
        f"• Titre : {task['title']}\n"
        f"• Projet : {task['project_name'] or '-'}\n"
        f"• Échéance : {task['due_date'] or 'Non définie'}\n"
        f"• Statut : {task['status']}\n"
        f"• Priorité : {task['priority']}\n\n"
    )
    if link:
        body += f"Mettre à jour directement : {link}\n"

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background-color: #ffffff;">
      <h2 style="color: {'#dc2626' if is_overdue else '#d97706'}; margin-top: 0; font-size: 18px;">
        [{urgence}] Rappel de tâche
      </h2>
      <p style="color: #334155; font-size: 14px;">Bonjour {collab_name},</p>
      <p style="color: #475569; font-size: 14px; margin-bottom: 20px;">
        Voici le récapitulatif de la tâche qui requiert votre attention :
      </p>

      <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px;">
        <thead>
          <tr style="background-color: #f8fafc; border-bottom: 2px solid #e2e8f0; text-align: left;">
            <th style="padding: 10px; color: #475569;">Titre</th>
            <th style="padding: 10px; color: #475569;">Projet</th>
            <th style="padding: 10px; color: #475569;">Échéance</th>
            <th style="padding: 10px; color: #475569;">Statut</th>
          </tr>
        </thead>
        <tbody>
          <tr style="border-bottom: 1px solid #f1f5f9;">
            <td style="padding: 10px; font-weight: bold; color: #0f172a;">{task['title']}</td>
            <td style="padding: 10px; color: #334155;">{task['project_name'] or '-'}</td>
            <td style="padding: 10px; color: {'#dc2626' if is_overdue else '#d97706'}; font-weight: bold;">{task['due_date'] or '-'}</td>
            <td style="padding: 10px; color: #334155;">{task['status']}</td>
          </tr>
        </tbody>
      </table>

      {f'<div style="text-align: center; margin-top: 24px;"><a href="{link}" style="display: inline-block; background-color: #4f46e5; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; font-size: 14px;">Mettre à jour la situation</a></div>' if link else ''}
    </div>
    """
    success, message = _send_raw(task['collaborator_email'], subject, body, html_body)
    database.log_reminder(task_id, reminder_type, success, message)
    if success:
        database.register_reminder_sent(task_id, datetime.now(timezone.utc).isoformat(timespec='seconds'))
    return success, message


def send_overdue_digest_to_collaborator(collaborator_email, collaborator_name, overdue_tasks):
    if not overdue_tasks or not collaborator_email:
        return False, "Aucune tâche ou adresse email manquante."

    subject = f"[Alerte Retard] Récapitulatif de vos tâches en retard ({len(overdue_tasks)})"

    text_lines = [
        f"Bonjour {collaborator_name},\n",
        f"Voici le tableau de vos tâches actuellement en retard ({len(overdue_tasks)}) :\n",
    ]
    
    rows_html = ""
    for t in overdue_tasks:
        link = _task_link(t)
        text_lines.append(f"- {t['title']} | Projet: {t['project_name'] or '-'} | Échéance: {t['due_date']}")
        if link:
            text_lines.append(f"  Mise à jour : {link}")

        rows_html += f"""
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 12px; font-weight: bold; color: #0f172a;">{t['title']}</td>
          <td style="padding: 12px; color: #475569;">{t['project_name'] or '-'}</td>
          <td style="padding: 12px; color: #dc2626; font-weight: bold;">{t['due_date'] or '-'}</td>
          <td style="padding: 12px; color: #475569;">{t['priority']}</td>
          <td style="padding: 12px; text-align: center;">
            {f'<a href="{link}" style="background-color: #4f46e5; color: #ffffff; text-decoration: none; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;">Accéder</a>' if link else '-'}
          </td>
        </tr>
        """

    body = "\n".join(text_lines)

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background-color: #ffffff;">
      <h2 style="color: #dc2626; margin-top: 0; font-size: 20px;">Rappel : Tâches affectées en retard</h2>
      <p style="color: #334155; font-size: 14px;">Bonjour {collaborator_name},</p>
      <p style="color: #475569; font-size: 14px; margin-bottom: 20px;">
        Veuillez trouver ci-dessous le tableau récapitulatif des tâches qui vous sont affectées et dont l'échéance est dépassée :
      </p>

      <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 13px;">
        <thead>
          <tr style="background-color: #f8fafc; border-bottom: 2px solid #cbd5e1; text-align: left;">
            <th style="padding: 10px; color: #334155;">Titre de la tâche</th>
            <th style="padding: 10px; color: #334155;">Projet</th>
            <th style="padding: 10px; color: #334155;">Échéance</th>
            <th style="padding: 10px; color: #334155;">Priorité</th>
            <th style="padding: 10px; color: #334155; text-align: center;">Action</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>

      <p style="color: #64748b; font-size: 12px; margin-top: 20px;">
        Merci de mettre à jour le statut ou de proposer une nouvelle date d'échéance via les liens ci-dessus.
      </p>
    </div>
    """

    success, message = _send_raw(collaborator_email, subject, body, html_body)
    if success:
        for t in overdue_tasks:
            database.register_reminder_sent(t['id'], datetime.now(timezone.utc).isoformat(timespec='seconds'))
            database.log_reminder(t['id'], 'retard_tableau', True, message)
    return success, message


def notify_admin_of_collaborator_update(task_id, new_status, new_due_date, comment):
    try:
        task = database.get_tache(task_id)
        settings = database.get_settings()
        if not task or not settings or not settings['smtp_user']:
            return
        destinataire = settings.get('sender_email') or settings['smtp_user']
        subject = f"Mise à jour collaborateur : {task['title']}"
        body = (
            f"{task['collaborator_name'] or 'Un collaborateur'} a mis à jour la tâche '{task['title']}'.\n\n"
            f"Nouveau statut : {new_status}\n"
            f"Nouvelle échéance : {new_due_date or '(inchangée)'}\n"
            f"Commentaire : {comment or '(aucun)'}\n"
        )
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background-color: #ffffff;">
          <h3 style="color: #1e293b; margin-top: 0;">Mise à jour de tâche par un collaborateur</h3>
          <p style="color: #475569; font-size: 14px;"><strong>{task['collaborator_name'] or 'Un collaborateur'}</strong> a apporté des modifications à sa tâche :</p>
          <table style="width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px;">
            <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px; font-weight: bold;">Tâche</td><td style="padding: 8px;">{task['title']}</td></tr>
            <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px; font-weight: bold;">Nouveau Statut</td><td style="padding: 8px; color: #4f46e5; font-weight: bold;">{new_status}</td></tr>
            <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px; font-weight: bold;">Nouvelle Échéance</td><td style="padding: 8px;">{new_due_date or '(inchangée)'}</td></tr>
            <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px; font-weight: bold;">Commentaire</td><td style="padding: 8px; color: #334155;">{comment or '(aucun)'}</td></tr>
          </table>
        </div>
        """
        _send_raw(destinataire, subject, body, html_body)
    except Exception:
        logger.exception("Échec de la notification admin pour la tâche %s", task_id)


def notify_admin_async(task_id, new_status, new_due_date, comment):
    thread = threading.Thread(target=notify_admin_of_collaborator_update, args=(task_id, new_status, new_due_date, comment), daemon=True)
    thread.start()


def send_rejection_notification(task_id, rejection_comment=None):
    try:
        task = database.get_tache(task_id)
        if not task or not task['collaborator_email']:
            return False, "Aucun collaborateur ou email associé à cette tâche."
        
        collab_name = task['collaborator_name'] or "Collaborateur"
        link = _task_link(task)
        motif = rejection_comment.strip() if rejection_comment and rejection_comment.strip() else "Complément d'information ou révision demandée."
        
        subject = f"[Révision demandée] Statut non validé : {task['title']}"
        
        body = (
            f"Bonjour {collab_name},\n\n"
            f"DEMANDE DE RÉVISION DE TÂCHE\n\n"
            f"La demande de clôture pour la tâche '{task['title']}' n'a pas été validée.\n"
            f"La tâche a été renvoyée au statut 'En cours'.\n\n"
            f"MOTIF & INSTRUCTIONS DE RÉVISION :\n"
            f"{motif}\n\n"
            f"Merci de procéder aux révisions nécessaires et de mettre à jour votre tâche.\n\n"
        )
        if link:
            body += f"Accéder à votre tâche : {link}\n"
            
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 650px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background-color: #ffffff;">
          <div style="background-color: #0f172a; color: #ffffff; padding: 16px 20px; border-radius: 8px; margin-bottom: 20px; text-align: center;">
            <h2 style="margin: 0; font-size: 18px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">Demande de révision de tâche</h2>
          </div>

          <h3 style="color: #0f172a; margin-top: 0; font-size: 17px;">Bonjour {collab_name},</h3>
          <p style="color: #334155; font-size: 14px; line-height: 1.5;">
            La demande de clôture pour la tâche <strong>"{task['title']}"</strong> n'a pas été validée. La tâche repasse au statut <strong>En cours</strong>.
          </p>

          <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-left: 4px solid #4f46e5; border-radius: 8px; padding: 18px; margin: 20px 0;">
            <h4 style="color: #0f172a; margin: 0 0 10px 0; font-size: 13px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">Motif & instructions de révision :</h4>
            <p style="color: #1e293b; margin: 0; font-size: 14px; font-weight: 500; line-height: 1.6; white-space: pre-wrap;">{motif}</p>
          </div>

          <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 14px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;">
            <tr style="border-bottom: 1px solid #f1f5f9; background-color: #f8fafc;">
              <td style="padding: 10px 14px; font-weight: bold; color: #475569; width: 35%;">Tâche concernée</td>
              <td style="padding: 10px 14px; color: #0f172a; font-weight: bold;">{task['title']}</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
              <td style="padding: 10px 14px; font-weight: bold; color: #475569;">Projet</td>
              <td style="padding: 10px 14px; color: #334155;">{task['project_name'] or '-'}</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
              <td style="padding: 10px 14px; font-weight: bold; color: #475569;">Nouveau statut</td>
              <td style="padding: 10px 14px; color: #4f46e5; font-weight: bold;">En cours (Révision demandée)</td>
            </tr>
          </table>

          {f'<div style="text-align: center; margin-top: 24px;"><a href="{link}" style="display: inline-block; background-color: #4f46e5; color: #ffffff; text-decoration: none; padding: 12px 28px; border-radius: 8px; font-weight: bold; font-size: 14px;">Accéder à votre tâche pour la mettre à jour</a></div>' if link else ''}
        </div>
        """
        success, message = _send_raw(task['collaborator_email'], subject, body, html_body)
        database.log_reminder(task_id, 'refus_dg', success, message)
        return success, message
    except Exception as exc:
        logger.exception("Échec de la notification de refus pour la tâche %s", task_id)
        return False, str(exc)


def send_rejection_notification_async(task_id, rejection_comment=None):
    thread = threading.Thread(target=send_rejection_notification, args=(task_id, rejection_comment), daemon=True)
    thread.start()
