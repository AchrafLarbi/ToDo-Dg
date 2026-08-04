"""Blueprint pour le tableau de bord."""
from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.models import database
from app.services import run_verification_echeances

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
def dashboard():
    today = date.today()
    today_str = today.isoformat()
    settings = database.get_settings()
    days_before = settings['reminder_days_before'] if settings else 2
    due_soon_days = max(7, days_before)
    due_soon_limit = (today + timedelta(days=due_soon_days)).isoformat()

    stats = database.dashboard_stats(today_str, due_soon_limit)
    par_collab = database.stats_by_collaborateur(today_str, due_soon_limit)
    overdue = database.overdue_tasks(today_str)
    due_soon = database.due_soon_tasks(today_str, due_soon_limit)
    pending_validation = database.list_pending_validation_tasks()

    return render_template(
        'dashboard/dashboard.html',
        stats=stats,
        par_collaborateur=par_collab,
        overdue=overdue,
        due_soon=due_soon,
        pending_validation=pending_validation,
        today=today_str,
    )

@dashboard_bp.route('/verifier-echeances', methods=['POST'])
def verifier_echeances():
    sent_ok, sent_ko, details = run_verification_echeances()
    if sent_ok == 0 and sent_ko == 0:
        flash("Aucune tâche en retard ou à échéance proche nécessitant une relance aujourd'hui.", "warning")
    else:
        msg = f"Relances effectuées : {sent_ok} envoyée(s) avec succès"
        if sent_ko > 0:
            msg += f", {sent_ko} échec(s)"
        flash(msg + ".", "success" if sent_ko == 0 else "warning")
    return redirect(url_for('dashboard.dashboard'))

@dashboard_bp.route('/relancer-selection', methods=['POST'])
def relancer_selection():
    task_ids = request.form.getlist('task_ids')
    channel = request.form.get('channel', 'email')
    
    if not task_ids:
        flash("Aucune tâche sélectionnée pour la relance.", "warning")
        return redirect(url_for('dashboard.dashboard'))
        
    sent_email_ok = 0
    sent_email_ko = 0
    wa_links = []
    
    from app.services.email_service import send_reminder
    from app.services import send_whatsapp_relance
    
    for tid in task_ids:
        try:
            tid_int = int(tid)
            if channel in ('email', 'all'):
                ok, msg = send_reminder(tid_int, 'echeance_proche')
                if ok:
                    sent_email_ok += 1
                else:
                    sent_email_ko += 1
            if channel in ('whatsapp', 'all'):
                ok_wa, msg_wa, wa_url = send_whatsapp_relance(tid_int)
                if ok_wa and wa_url:
                    wa_links.append(wa_url)
        except Exception:
            sent_email_ko += 1

    if channel == 'whatsapp' and wa_links:
        flash(f"Préparation de {len(wa_links)} relance(s) WhatsApp...", "success")
        return redirect(wa_links[0])
        
    msg = f"Relances effectuées : {sent_email_ok} email(s) envoyé(s) avec succès"
    if sent_email_ko > 0:
        msg += f", {sent_email_ko} échec(s)"
    flash(msg + ".", "success" if sent_email_ko == 0 else "warning")
    return redirect(url_for('dashboard.dashboard'))
