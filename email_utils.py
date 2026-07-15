"""Envoi d'emails via SMTP (Outlook / Office 365 ou tout autre fournisseur) et
journalisation dans l'historique.

Cette couche est volontairement defensive : quelle que soit l'erreur (parametres
manquants, base de donnees, connexion bloquee, authentification refusee), elle ne
leve JAMAIS d'exception vers l'appelant. Elle renvoie toujours un couple
(succes: bool, message: str) avec un message clair et actionnable en francais.
"""
import logging
import smtplib
import socket
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage

import database

logger = logging.getLogger(__name__)

# Delai maximal (secondes) pour chaque operation reseau SMTP. Volontairement court
# pour rester sous le timeout du worker gunicorn et ne pas bloquer l'interface.
SMTP_TIMEOUT = 15


def _friendly_error(exc):
    """Transforme une exception SMTP / reseau en message clair et actionnable."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "Authentification refusee par le serveur (erreur 535). "
            "Verifiez l'adresse email et le mot de passe. Pour Outlook / Office 365, "
            "un mot de passe de session normal ne fonctionne pas : il faut un "
            "MOT DE PASSE D'APPLICATION, et l'option « SMTP authentifie » doit "
            "etre activee pour votre boite. Si votre etablissement a desactive le SMTP "
            "de base (cas frequent), utilisez un autre fournisseur d'envoi "
            "(ex. Brevo, SendGrid, ou Gmail avec un mot de passe d'application)."
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return (
            f"Adresse expediteur refusee : {exc}. L'adresse d'envoi doit correspondre "
            "exactement au compte utilise pour se connecter."
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return f"Destinataire refuse par le serveur : {exc}."
    if isinstance(exc, (smtplib.SMTPConnectError, ConnectionError, socket.timeout,
                        TimeoutError, ssl.SSLError, OSError)):
        return (
            f"Impossible de se connecter au serveur SMTP ({exc}). "
            "Le port est peut-etre bloque par l'hebergeur, ou le serveur/port sont "
            "incorrects. Essayez le port 465 (SSL) au lieu de 587, verifiez le nom du "
            "serveur, ou utilisez un autre fournisseur d'envoi d'emails."
        )
    return f"Echec de l'envoi : {exc}"


def _open_connection(host, port, timeout):
    """Ouvre une connexion SMTP prete a l'authentification.

    Port 465 -> SSL implicite (SMTP_SSL). Sinon -> SMTP + STARTTLS (ex. 587).
    """
    context = ssl.create_default_context()
    if int(port) == 465:
        return smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    smtp = smtplib.SMTP(host, port, timeout=timeout)
    smtp.ehlo()
    smtp.starttls(context=context)
    smtp.ehlo()
    return smtp


def _send_raw(to_addr, subject, body):
    """Envoie un email. Ne leve jamais : renvoie toujours (succes, message)."""
    try:
        settings = database.get_settings()
    except Exception as exc:  # erreur de connexion / lecture base de donnees
        logger.exception("Lecture des parametres SMTP impossible")
        return False, f"Erreur de base de donnees lors de la lecture des parametres : {exc}"

    if not settings:
        return False, (
            "Parametres introuvables. Enregistrez d'abord vos parametres dans la page "
            "Parametres."
        )

    host = settings['smtp_host']
    port = settings['smtp_port'] or 587
    user = settings['smtp_user']
    password = settings['smtp_password']
    sender_name = settings['sender_name'] or 'Gestion des taches'
    # Adresse expediteur (« From ») : chez Brevo / SendGrid, le login SMTP n'est PAS
    # une adresse d'envoi valide. On utilise donc l'adresse expediteur dediee si elle
    # est renseignee, sinon on retombe sur le login (cas Outlook / Office 365).
    from_email = settings.get('sender_email') or user

    if not host:
        return False, "Serveur SMTP non configure dans les parametres."
    if not user or not password:
        return False, (
            "Parametres SMTP incomplets : le login SMTP et le mot de passe / cle SMTP "
            "sont obligatoires. Renseignez-les puis reessayez."
        )
    if not to_addr:
        return False, "Aucun destinataire pour cet email."

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"{sender_name} <{from_email}>"
    msg['To'] = to_addr
    msg.set_content(body)

    # On tente le port configure, puis un repli automatique en SSL/465 si la
    # connexion (et non l'authentification) echoue -- utile quand l'hebergeur
    # bloque le port 587.
    ports_to_try = [int(port)]
    if int(port) == 587:
        ports_to_try.append(465)

    last_exc = None
    for attempt_port in ports_to_try:
        try:
            with _open_connection(host, attempt_port, SMTP_TIMEOUT) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
            return True, "Email envoye avec succes."
        except smtplib.SMTPAuthenticationError as exc:
            # L'authentification echouera de la meme facon sur un autre port :
            # inutile de reessayer, on remonte tout de suite le diagnostic.
            logger.warning("Authentification SMTP refusee : %s", exc)
            return False, _friendly_error(exc)
        except (smtplib.SMTPConnectError, ConnectionError, socket.timeout,
                TimeoutError, ssl.SSLError, OSError) as exc:
            logger.warning("Connexion SMTP echouee sur le port %s : %s", attempt_port, exc)
            last_exc = exc
            continue  # on essaie le port de repli s'il en reste un
        except Exception as exc:  # toute autre erreur SMTP inattendue
            logger.exception("Echec inattendu de l'envoi de l'email")
            return False, _friendly_error(exc)

    return False, _friendly_error(last_exc)


def _task_link(task):
    settings = database.get_settings()
    if not settings or not settings['base_url'] or not task['update_token']:
        return None
    return f"{settings['base_url']}/t/{task['update_token']}"


def send_test_email():
    try:
        settings = database.get_settings()
    except Exception as exc:
        logger.exception("Lecture des parametres impossible")
        return False, f"Erreur de base de donnees : {exc}"
    if not settings or not settings['smtp_user']:
        return False, (
            "Aucune adresse email configuree. Renseignez vos parametres SMTP et "
            "cliquez sur « Enregistrer les parametres » avant de tester."
        )
    # On envoie le test vers l'adresse expediteur (votre vraie boite) si elle est
    # definie ; sinon vers le login SMTP (cas Outlook ou login = adresse reelle).
    destinataire = settings.get('sender_email') or settings['smtp_user']
    return _send_raw(
        destinataire,
        "Test - Gestion des taches",
        "Ceci est un email de test envoye depuis l'application Gestion des taches.\n"
        "Si vous recevez ce message, la configuration SMTP fonctionne correctement.",
    )


def send_task_notification(task_id):
    """Notifie le collaborateur d'une nouvelle tache. Ne leve jamais."""
    try:
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
    except Exception:  # ne jamais faire echouer la creation de la tache
        logger.exception("Echec de la notification de creation de tache %s", task_id)


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
    try:
        task = database.get_tache(task_id)
        settings = database.get_settings()
        if not task or not settings or not settings['smtp_user']:
            return
        destinataire = settings.get('sender_email') or settings['smtp_user']
        subject = f"Mise a jour collaborateur : {task['title']}"
        body = (
            f"{task['collaborator_name'] or 'Un collaborateur'} a mis a jour la tache '{task['title']}'.\n\n"
            f"Nouveau statut : {new_status}\n"
            f"Nouvelle echeance : {new_due_date or '(inchangee)'}\n"
            f"Commentaire : {comment or '(aucun)'}\n"
        )
        _send_raw(destinataire, subject, body)
    except Exception:
        logger.exception("Echec de la notification admin pour la tache %s", task_id)
