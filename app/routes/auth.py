"""Blueprint pour l'authentification administrateur."""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app

auth_bp = Blueprint('auth', __name__)

PUBLIC_ENDPOINTS = {'auth.login', 'static', 'tasks.tache_publique', 'tasks.tache_publique_soumettre'}

@auth_bp.before_app_request
def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if not session.get('is_admin'):
        return redirect(url_for('auth.login', next=request.path))
    return None

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == current_app.config['ADMIN_PASSWORD']:
            session['is_admin'] = True
            return redirect(request.args.get('next') or url_for('dashboard.dashboard'))
        flash('Mot de passe incorrect.', 'danger')
    return render_template('auth/login.html')

@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
