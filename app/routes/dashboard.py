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
    due_soon_limit = (today + timedelta(days=days_before)).isoformat()

    stats = database.dashboard_stats(today_str, due_soon_limit)
    par_collab = database.stats_by_collaborateur(today_str, due_soon_limit)
    overdue = database.overdue_tasks(today_str)
    due_soon = database.due_soon_tasks(today_str, due_soon_limit)

    return render_template(
        'dashboard/dashboard.html',
        stats=stats,
        par_collaborateur=par_collab,
        overdue=overdue,
        due_soon=due_soon,
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
