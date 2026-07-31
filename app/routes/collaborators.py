"""Blueprint pour la gestion des collaborateurs."""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.models import database
from app.routes.tasks import deadline_badge

collaborators_bp = Blueprint('collaborators', __name__)

@collaborators_bp.route('/collaborateurs')
def collaborateurs():
    collabs = database.list_collaborateurs()
    return render_template('collaborators/collaborateurs.html', collaborateurs=collabs)

@collaborators_bp.route('/collaborateurs/ajouter', methods=['POST'])
def ajouter_collaborateur():
    name = request.form['name'].strip()
    email = request.form['email'].strip()
    phone = request.form.get('phone', '').strip()
    if name and email:
        database.create_collaborateur(name, email, phone)
        flash('Collaborateur ajouté.', 'success')
    else:
        flash('Le nom et l\'email sont obligatoires.', 'danger')
    return redirect(url_for('collaborators.collaborateurs'))

@collaborators_bp.route('/collaborateurs/<int:id>')
def detail_collaborateur(id):
    collab = database.get_collaborateur(id)
    if not collab:
        flash('Collaborateur introuvable.', 'danger')
        return redirect(url_for('collaborators.collaborateurs'))
    tasks = database.list_taches_by_collaborateur(id)
    stats = database.get_collaborateur_stats(id)
    all_collabs = database.list_collaborateurs()
    return render_template(
        'collaborators/collaborateur_detail.html',
        collaborateur=collab,
        all_collaborateurs=all_collabs,
        tasks=tasks,
        stats=stats,
        today=date.today().isoformat(),
        deadline_badge=deadline_badge,
    )


@collaborators_bp.route('/collaborateurs/<int:id>/modifier', methods=['POST'])
def modifier_collaborateur(id):
    name = request.form['name'].strip()
    email = request.form['email'].strip()
    phone = request.form.get('phone', '').strip()
    if name and email:
        database.update_collaborateur(id, name, email, phone)
        flash('Collaborateur mis à jour.', 'success')
    return redirect(url_for('collaborators.detail_collaborateur', id=id))

@collaborators_bp.route('/collaborateurs/<int:id>/supprimer', methods=['POST'])
def supprimer_collaborateur(id):
    database.delete_collaborateur(id)
    flash('Collaborateur supprimé.', 'success')
    return redirect(url_for('collaborators.collaborateurs'))
