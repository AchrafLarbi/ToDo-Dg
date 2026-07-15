"""Verification quotidienne automatique des echeances (APScheduler)."""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import database

_scheduler = BackgroundScheduler(daemon=True)
_job_id = 'verification_echeances'


def start(check_callback):
    """Demarre le scheduler et programme le job selon les parametres actuels."""
    if not _scheduler.running:
        _scheduler.start()
    reschedule(check_callback)


def reschedule(check_callback):
    """Reprogramme le job quotidien selon les parametres enregistres (appele apres modification)."""
    settings = database.get_settings()
    if _scheduler.get_job(_job_id):
        _scheduler.remove_job(_job_id)
    if settings['auto_reminders_enabled']:
        _scheduler.add_job(
            check_callback,
            trigger=CronTrigger(hour=settings['daily_check_hour'], minute=0),
            id=_job_id,
            replace_existing=True,
        )


def shutdown():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
