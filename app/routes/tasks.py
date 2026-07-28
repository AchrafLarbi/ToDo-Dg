"""Blueprint pour la gestion des taches (admin et vue publique collaborateur)."""
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from markupsafe import Markup

from app.models import database, PRIORITIES, SENSITIVITIES, STATUSES
from app.services import (
    send_task_notification_async,
    send_reminder,
    notify_admin_async,
)

tasks_bp = Blueprint('tasks', __name__)

@tasks_bp.app_template_filter('slugify')
def slugify(value):
    return str(value).strip().lower().replace(' ', '-')

def deadline_badge(task):
    due = task.get('due_date')
    status = task.get('status')
    if not due or status in ('Terminee', 'Cloturee', 'Terminé'):
        return Markup('')
    today = date.today().isoformat()
    if due < today:
        return Markup('<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-200">En retard</span>')
    settings = database.get_settings()
    days_before = settings['reminder_days_before'] if settings else 2
    from datetime import timedelta
    limit = (date.today() + timedelta(days=days_before)).isoformat()
    if due <= limit:
        return Markup('<span class="px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-200">Échéance proche</span>')
    return Markup('')

@tasks_bp.route('/taches')
def taches():
    filters = {
        'project_id': request.args.get('project_id', ''),
        'collaborator_id': request.args.get('collaborator_id', ''),
        'status': request.args.get('status', ''),
        'priority': request.args.get('priority', ''),
    }
    tasks_list = database.list_taches(
        project_id=int(filters['project_id']) if filters['project_id'] else None,
        collaborator_id=int(filters['collaborator_id']) if filters['collaborator_id'] else None,
        status=filters['status'] or None,
        priority=filters['priority'] or None,
    )
    return render_template(
        'tasks/taches.html',
        tasks=tasks_list,
        projets=database.list_projets(),
        collaborateurs=database.list_collaborateurs(),
        filters=filters,
        PRIORITIES=PRIORITIES,
        SENSITIVITIES=SENSITIVITIES,
        STATUSES=STATUSES,
        today=date.today().isoformat(),
        deadline_badge=deadline_badge,
    )

@tasks_bp.route('/taches/ajouter', methods=['POST'])
def ajouter_tache():
    title = request.form['title'].strip()
    if not title:
        flash('Le titre de la tâche est obligatoire.', 'danger')
        return redirect(url_for('tasks.taches'))
    task_id = database.create_tache(
        title=title,
        description=request.form.get('description', '').strip(),
        project_id=int(request.form['project_id']) if request.form.get('project_id') else None,
        collaborator_id=int(request.form['collaborator_id']) if request.form.get('collaborator_id') else None,
        priority=request.form.get('priority', 'Normale'),
        sensitivity=request.form.get('sensitivity', 'Normale'),
        due_date=request.form.get('due_date', '').strip(),
    )
    send_task_notification_async(task_id)
    flash('Tâche créée.', 'success')
    return redirect(url_for('tasks.taches'))

@tasks_bp.route('/taches/<int:id>')
def detail_tache(id):
    task = database.get_tache(id)
    if not task:
        flash('Tâche introuvable.', 'danger')
        return redirect(url_for('tasks.taches'))
    return render_template(
        'tasks/tache_detail.html',
        task=task,
        projets=database.list_projets(),
        collaborateurs=database.list_collaborateurs(),
        reminders=database.list_reminders(id),
        updates=database.list_task_updates(id),
        PRIORITIES=PRIORITIES,
        SENSITIVITIES=SENSITIVITIES,
        STATUSES=STATUSES,
        deadline_badge=deadline_badge,
    )

@tasks_bp.route('/taches/<int:id>/modifier', methods=['POST'])
def modifier_tache(id):
    title = request.form['title'].strip()
    if title:
        database.update_tache(
            id,
            title=title,
            description=request.form.get('description', '').strip(),
            project_id=int(request.form['project_id']) if request.form.get('project_id') else None,
            collaborator_id=int(request.form['collaborator_id']) if request.form.get('collaborator_id') else None,
            priority=request.form.get('priority', 'Normale'),
            sensitivity=request.form.get('sensitivity', 'Normale'),
            due_date=request.form.get('due_date', '').strip(),
        )
        flash('Tâche mise à jour.', 'success')
    return redirect(url_for('tasks.detail_tache', id=id))

@tasks_bp.route('/taches/<int:id>/statut', methods=['POST'])
def changer_statut(id):
    new_status = request.form.get('status')
    comment = request.form.get('closure_comment', '').strip()
    closed_at = None
    if new_status in ('Terminee', 'Cloturee', 'Terminé'):
        closed_at = datetime.now().isoformat(timespec='seconds')
    database.update_statut(id, new_status, comment, closed_at)
    flash('Statut mis à jour.', 'success')
    return redirect(url_for('tasks.detail_tache', id=id))

@tasks_bp.route('/taches/<int:id>/relancer', methods=['POST'])
def relancer_tache(id):
    success, message = send_reminder(id, 'manuelle')
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('tasks.detail_tache', id=id))

@tasks_bp.route('/taches/<int:id>/supprimer', methods=['POST'])
def supprimer_tache(id):
    database.delete_tache(id)
    flash('Tâche supprimée.', 'success')
    return redirect(url_for('tasks.taches'))

# ---- Vue publique collaborateur ---------------------------------------------

@tasks_bp.route('/t/<token>')
def tache_publique(token):
    task = database.get_tache_by_token(token)
    return render_template(
        'tasks/tache_publique.html',
        task=task,
        token=token,
        STATUSES=STATUSES,
        deadline_badge=deadline_badge,
    )

@tasks_bp.route('/t/<token>/soumettre', methods=['POST'])
def tache_publique_soumettre(token):
    task = database.get_tache_by_token(token)
    if not task:
        flash('Lien invalide ou expiré.', 'danger')
        return redirect(url_for('tasks.tache_publique', token=token))
    new_status = request.form.get('status')
    new_due_date = request.form.get('due_date', '').strip()
    comment = request.form.get('comment', '').strip()
    database.collaborator_update_tache(task['id'], new_status, new_due_date, comment)
    notify_admin_async(task['id'], new_status, new_due_date, comment)
    flash('Votre mise à jour a été enregistrée. Merci !', 'success')
    return redirect(url_for('tasks.tache_publique', token=token))
