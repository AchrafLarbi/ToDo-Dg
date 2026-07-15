"""Application Flask : gestion de projets, taches et collaborateurs."""
import os
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from markupsafe import Markup

load_dotenv()

import database
import email_utils
import scheduler
from database import PRIORITIES, SENSITIVITIES, STATUSES
from paths import RESOURCE_DIR

app = Flask(
    __name__,
    template_folder=RESOURCE_DIR,
    static_folder=RESOURCE_DIR,
    static_url_path='/static',
)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# Routes accessibles sans authentification admin (page de connexion, assets,
# et le lien securise que recoit un collaborateur par email pour sa propre tache).
PUBLIC_ENDPOINTS = {'login', 'static', 'tache_publique', 'tache_publique_soumettre'}


@app.before_request
def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if not session.get('is_admin'):
        return redirect(url_for('login', next=request.path))
    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Mot de passe incorrect.', 'danger')
    return render_template('login.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.template_filter('slugify')
def slugify(value):
    return str(value).strip().lower().replace(' ', '-')


def _due_soon_limit():
    settings = database.get_settings()
    return (date.today() + timedelta(days=settings['reminder_days_before'])).isoformat()


def _deadline_badge(task):
    """Badge visuel : orange si l'echeance approche, rouge si elle est depassee."""
    if not task['due_date'] or task['status'] in ('Terminee', 'Cloturee'):
        return Markup('')
    today_iso = date.today().isoformat()
    if task['due_date'] < today_iso:
        return Markup('<span class="badge badge-urgente">En retard</span>')
    if task['due_date'] <= _due_soon_limit():
        return Markup('<span class="badge badge-haute">Echeance proche</span>')
    return Markup('')


@app.context_processor
def inject_globals():
    return {
        'today': date.today().isoformat(),
        'PRIORITIES': PRIORITIES,
        'SENSITIVITIES': SENSITIVITIES,
        'STATUSES': STATUSES,
        'deadline_badge': _deadline_badge,
    }


def run_verification_echeances():
    """Verifie les taches en retard/proches d'echeance et envoie les relances necessaires.

    Une seule relance par jour et par tache pour eviter le spam.
    """
    today_iso = date.today().isoformat()
    limit = _due_soon_limit()
    envoyees = 0
    for task in database.tasks_needing_reminder(today_iso, limit):
        if task['last_reminder_at'] and str(task['last_reminder_at'])[:10] == today_iso:
            continue
        reminder_type = 'retard' if task['due_date'] < today_iso else 'echeance_proche'
        success, _ = email_utils.send_reminder(task['id'], reminder_type)
        if success:
            envoyees += 1
    return envoyees


# ---- Tableau de bord --------------------------------------------------------

@app.route('/')
def dashboard():
    today_iso = date.today().isoformat()
    limit = _due_soon_limit()
    stats = database.dashboard_stats(today_iso, limit)
    overdue = database.overdue_tasks(today_iso)
    due_soon = database.due_soon_tasks(today_iso, limit)
    par_collaborateur = database.stats_by_collaborateur(today_iso, limit)
    return render_template(
        'dashboard.html', stats=stats, overdue=overdue, due_soon=due_soon,
        par_collaborateur=par_collaborateur,
    )


@app.route('/verifier-echeances', methods=['POST'])
def verifier_echeances():
    envoyees = run_verification_echeances()
    flash(f"Verification effectuee : {envoyees} relance(s) envoyee(s).", 'success')
    return redirect(url_for('dashboard'))


# ---- Projets ------------------------------------------------------------------

@app.route('/projets')
def projets():
    return render_template('projets.html', projets=database.list_projets())


@app.route('/projets/ajouter', methods=['POST'])
def ajouter_projet():
    database.create_projet(
        request.form['name'].strip(),
        request.form.get('description', '').strip(),
        request.form.get('start_date', '').strip(),
        request.form.get('deadline', '').strip(),
        request.form.get('status', 'En cours'),
    )
    flash('Projet cree.', 'success')
    return redirect(url_for('projets'))


@app.route('/projets/<int:id>')
def detail_projet(id):
    projet = database.get_projet(id)
    if not projet:
        flash('Projet introuvable.', 'danger')
        return redirect(url_for('projets'))
    tasks = database.list_taches_by_projet(id)
    return render_template('projet_detail.html', projet=projet, tasks=tasks)


@app.route('/projets/<int:id>/modifier', methods=['POST'])
def modifier_projet(id):
    database.update_projet(
        id,
        request.form['name'].strip(),
        request.form.get('description', '').strip(),
        request.form.get('start_date', '').strip(),
        request.form.get('deadline', '').strip(),
        request.form.get('status', 'En cours'),
    )
    flash('Projet mis a jour.', 'success')
    return redirect(url_for('detail_projet', id=id))


@app.route('/projets/<int:id>/supprimer', methods=['POST'])
def supprimer_projet(id):
    database.delete_projet(id)
    flash('Projet supprime.', 'success')
    return redirect(url_for('projets'))


# ---- Taches ---------------------------------------------------------------------

@app.route('/taches')
def taches():
    filters = {
        'project_id': request.args.get('project_id', ''),
        'collaborator_id': request.args.get('collaborator_id', ''),
        'status': request.args.get('status', ''),
        'priority': request.args.get('priority', ''),
    }
    tasks = database.list_taches(
        project_id=filters['project_id'] or None,
        collaborator_id=filters['collaborator_id'] or None,
        status=filters['status'] or None,
        priority=filters['priority'] or None,
    )
    return render_template(
        'taches.html',
        tasks=tasks,
        filters=filters,
        projets=database.list_projets(),
        collaborateurs=database.list_collaborateurs(),
    )


@app.route('/taches/ajouter', methods=['POST'])
def ajouter_tache():
    new_id = database.create_tache(
        request.form['title'].strip(),
        request.form.get('description', '').strip(),
        request.form.get('project_id') or None,
        request.form.get('collaborator_id') or None,
        request.form.get('priority', 'Normale'),
        request.form.get('sensitivity', 'Normale'),
        request.form.get('due_date', '').strip(),
    )
    email_utils.send_task_notification(new_id)
    flash('Tache creee.', 'success')
    return redirect(url_for('taches'))


@app.route('/taches/<int:id>')
def detail_tache(id):
    task = database.get_tache(id)
    if not task:
        flash('Tache introuvable.', 'danger')
        return redirect(url_for('taches'))
    return render_template(
        'tache_detail.html',
        task=task,
        reminders=database.list_reminders(id),
        updates=database.list_task_updates(id),
        projets=database.list_projets(),
        collaborateurs=database.list_collaborateurs(),
    )


@app.route('/taches/<int:id>/modifier', methods=['POST'])
def modifier_tache(id):
    database.update_tache(
        id,
        request.form['title'].strip(),
        request.form.get('description', '').strip(),
        request.form.get('project_id') or None,
        request.form.get('collaborator_id') or None,
        request.form.get('priority', 'Normale'),
        request.form.get('sensitivity', 'Normale'),
        request.form.get('due_date', '').strip(),
    )
    flash('Tache mise a jour.', 'success')
    return redirect(url_for('detail_tache', id=id))


@app.route('/taches/<int:id>/statut', methods=['POST'])
def changer_statut(id):
    status = request.form['status']
    comment = request.form.get('closure_comment', '').strip()
    closed_at = None
    if status in ('Terminee', 'Cloturee'):
        closed_at = datetime.now().isoformat(timespec='seconds')
    database.update_statut(id, status, comment, closed_at)
    flash(f"Statut change en '{status}'.", 'success')
    return redirect(url_for('detail_tache', id=id))


@app.route('/taches/<int:id>/relancer', methods=['POST'])
def relancer_tache(id):
    success, message = email_utils.send_reminder(id, 'manuelle')
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('detail_tache', id=id))


@app.route('/taches/<int:id>/supprimer', methods=['POST'])
def supprimer_tache(id):
    database.delete_tache(id)
    flash('Tache supprimee.', 'success')
    return redirect(url_for('taches'))


# ---- Page publique pour le collaborateur (lien securise recu par email) ---------

@app.route('/t/<token>')
def tache_publique(token):
    task = database.get_tache_by_token(token)
    if not task:
        return render_template('tache_publique.html', task=None, token=token), 404
    return render_template('tache_publique.html', task=task, token=token)


@app.route('/t/<token>', methods=['POST'])
def tache_publique_soumettre(token):
    task = database.get_tache_by_token(token)
    if not task:
        return render_template('tache_publique.html', task=None), 404
    new_status = request.form.get('status', task['status'])
    new_due_date = request.form.get('due_date', '').strip()
    comment = request.form.get('comment', '').strip()
    database.collaborator_update_tache(task['id'], new_status, new_due_date, comment)
    email_utils.notify_admin_of_collaborator_update(task['id'], new_status, new_due_date, comment)
    flash('Mise a jour envoyee, merci.', 'success')
    return redirect(url_for('tache_publique', token=token))


# ---- Collaborateurs --------------------------------------------------------------

@app.route('/collaborateurs')
def collaborateurs():
    return render_template('collaborateurs.html', collaborateurs=database.list_collaborateurs())


@app.route('/collaborateurs/ajouter', methods=['POST'])
def ajouter_collaborateur():
    database.create_collaborateur(
        request.form['name'].strip(),
        request.form['email'].strip(),
        request.form.get('phone', '').strip(),
    )
    flash('Collaborateur ajoute.', 'success')
    return redirect(url_for('collaborateurs'))


@app.route('/collaborateurs/<int:id>')
def detail_collaborateur(id):
    collaborateur = database.get_collaborateur(id)
    if not collaborateur:
        flash('Collaborateur introuvable.', 'danger')
        return redirect(url_for('collaborateurs'))
    tasks = database.list_taches_by_collaborateur(id)
    return render_template('collaborateur_detail.html', collaborateur=collaborateur, tasks=tasks)


@app.route('/collaborateurs/<int:id>/modifier', methods=['POST'])
def modifier_collaborateur(id):
    database.update_collaborateur(
        id,
        request.form['name'].strip(),
        request.form['email'].strip(),
        request.form.get('phone', '').strip(),
    )
    flash('Collaborateur mis a jour.', 'success')
    return redirect(url_for('detail_collaborateur', id=id))


@app.route('/collaborateurs/<int:id>/supprimer', methods=['POST'])
def supprimer_collaborateur(id):
    database.delete_collaborateur(id)
    flash('Collaborateur supprime.', 'success')
    return redirect(url_for('collaborateurs'))


# ---- Parametres ----------------------------------------------------------------

@app.route('/parametres', methods=['GET', 'POST'])
def parametres():
    if request.method == 'POST':
        database.update_settings({
            'smtp_host': request.form['smtp_host'].strip(),
            'smtp_port': int(request.form['smtp_port']),
            'smtp_user': request.form['smtp_user'].strip(),
            'smtp_password': request.form.get('smtp_password', '').strip(),
            'sender_name': request.form['sender_name'].strip(),
            'reminder_days_before': int(request.form['reminder_days_before']),
            'daily_check_hour': int(request.form['daily_check_hour']),
            'auto_reminders_enabled': 1 if request.form.get('auto_reminders_enabled') else 0,
            'base_url': request.form.get('base_url', '').strip().rstrip('/'),
        })
        scheduler.reschedule(run_verification_echeances)
        flash('Parametres enregistres.', 'success')
        return redirect(url_for('parametres'))
    return render_template('parametres.html', settings=database.get_settings())


@app.route('/parametres/test-email', methods=['POST'])
def test_email():
    success, message = email_utils.send_test_email()
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('parametres'))


def create_app():
    database.init_db()
    scheduler.start(run_verification_echeances)
    return app


if __name__ == '__main__':
    create_app()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
