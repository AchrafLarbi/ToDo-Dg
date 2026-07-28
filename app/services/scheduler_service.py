"""Planification et execution des relances automatiques quotidiennes."""
import logging
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from app.models import database
from .email_service import send_reminder, send_overdue_digest_to_collaborator

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def run_verification_echeances():
    today_str = date.today().isoformat()
    try:
        settings = database.get_settings()
    except Exception:
        logger.exception("Échec de la vérification des échéances")
        return 0, 0, []

    if not settings:
        return 0, 0, []

    days_before = settings['reminder_days_before'] or 2
    limit_date_str = (date.today() + timedelta(days=days_before)).isoformat()
    tasks = database.tasks_needing_reminder(today_str, limit_date_str)

    overdue_by_collab = {}
    other_tasks = []

    for task in tasks:
        due = task['due_date']
        last_rem = task['last_reminder_at']
        if last_rem and last_rem[:10] == today_str:
            continue

        if due and due < today_str and task.get('collaborator_email'):
            collab_id = task['collaborator_id']
            if collab_id not in overdue_by_collab:
                overdue_by_collab[collab_id] = []
            overdue_by_collab[collab_id].append(task)
        else:
            other_tasks.append(task)

    sent_ok = 0
    sent_ko = 0
    details = []

    # Envoi par destinataire sous forme de tableau recapitutatif pour TOUTES les taches en retard
    for collab_id, collab_tasks in overdue_by_collab.items():
        collab_email = collab_tasks[0]['collaborator_email']
        collab_name = collab_tasks[0]['collaborator_name']
        success, msg = send_overdue_digest_to_collaborator(collab_email, collab_name, collab_tasks)
        if success:
            sent_ok += len(collab_tasks)
        else:
            sent_ko += len(collab_tasks)
        details.append((f"Tableau de {len(collab_tasks)} tâche(s) en retard", collab_name, success, msg))

    # Envoi des relances d'echeance proche
    for task in other_tasks:
        success, message = send_reminder(task['id'], 'echeance_proche')
        if success:
            sent_ok += 1
        else:
            sent_ko += 1
        details.append((task['title'], task['collaborator_name'], success, message))

    return sent_ok, sent_ko, details


def start(job_function=run_verification_echeances):
    if scheduler.running:
        return
    settings = database.get_settings()
    hour = settings['daily_check_hour'] if settings else 8
    enabled = bool(settings['auto_reminders_enabled']) if settings else True

    scheduler.add_job(
        job_function,
        'cron',
        hour=hour,
        minute=0,
        id='daily_reminders',
        replace_existing=True,
    )

    if not enabled:
        scheduler.pause_job('daily_reminders')

    scheduler.start()


def reschedule(job_function=run_verification_echeances):
    settings = database.get_settings()
    if not settings or not scheduler.running:
        return
    hour = settings['daily_check_hour']
    enabled = bool(settings['auto_reminders_enabled'])

    scheduler.reschedule_job(
        'daily_reminders',
        trigger='cron',
        hour=hour,
        minute=0,
    )

    if enabled:
        scheduler.resume_job('daily_reminders')
    else:
        scheduler.pause_job('daily_reminders')
