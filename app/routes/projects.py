"""Blueprint pour la gestion des projets."""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.models import database

projects_bp = Blueprint('projects', __name__)

@projects_bp.route('/projets')
def projets():
    projets_list = database.list_projets()
    return render_template('projects/projets.html', projets=projets_list, today=date.today().isoformat())

@projects_bp.route('/projets/ajouter', methods=['POST'])
def ajouter_projet():
    name = request.form['name'].strip()
    description = request.form.get('description', '').strip()
    start_date = request.form.get('start_date', '').strip()
    deadline = request.form.get('deadline', '').strip()
    status = request.form.get('status', 'En cours')
    if name:
        database.create_projet(name, description, start_date, deadline, status)
        flash('Projet créé.', 'success')
    return redirect(url_for('projects.projets'))

@projects_bp.route('/projets/<int:id>')
def detail_projet(id):
    projet = database.get_projet(id)
    if not projet:
        flash('Projet introuvable.', 'danger')
        return redirect(url_for('projects.projets'))
    tasks = database.list_taches_by_projet(id)
    return render_template('projects/projet_detail.html', projet=projet, tasks=tasks, today=date.today().isoformat())

@projects_bp.route('/projets/<int:id>/modifier', methods=['POST'])
def modifier_projet(id):
    name = request.form['name'].strip()
    description = request.form.get('description', '').strip()
    start_date = request.form.get('start_date', '').strip()
    deadline = request.form.get('deadline', '').strip()
    status = request.form.get('status', 'En cours')
    if name:
        database.update_projet(id, name, description, start_date, deadline, status)
        flash('Projet mis à jour.', 'success')
    return redirect(url_for('projects.detail_projet', id=id))

@projects_bp.route('/projets/<int:id>/supprimer', methods=['POST'])
def supprimer_projet(id):
    database.delete_projet(id)
    flash('Projet et tâches associées supprimés.', 'success')
    return redirect(url_for('projects.projets'))
