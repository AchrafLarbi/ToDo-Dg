"""Blueprint pour la gestion des parametres et de l'email de test."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import database
from app.services import send_test_email, reschedule_scheduler

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/parametres', methods=['GET', 'POST'])
def parametres():
    if request.method == 'POST':
        database.update_settings({
            'smtp_host': request.form['smtp_host'].strip(),
            'smtp_port': int(request.form['smtp_port']),
            'smtp_user': request.form['smtp_user'].strip(),
            'smtp_password': request.form.get('smtp_password', '').strip(),
            'sender_name': request.form['sender_name'].strip(),
            'sender_email': request.form.get('sender_email', '').strip(),
            'reminder_days_before': int(request.form['reminder_days_before']),
            'daily_check_hour': int(request.form['daily_check_hour']),
            'auto_reminders_enabled': 1 if request.form.get('auto_reminders_enabled') else 0,
            'base_url': request.form.get('base_url', '').strip().rstrip('/'),
            'whatsapp_sender_phone': request.form.get('whatsapp_sender_phone', '').strip(),
            'whatsapp_country_code': request.form.get('whatsapp_country_code', '213').strip(),
        })
        reschedule_scheduler()
        flash('Paramètres enregistrés.', 'success')
        return redirect(url_for('settings.parametres'))
    return render_template('settings/parametres.html', settings=database.get_settings())

@settings_bp.route('/parametres/test-email', methods=['POST'])
def test_email():
    try:
        success, message = send_test_email()
    except Exception as exc:
        current_app.logger.exception("Erreur inattendue lors de l'envoi de l'email de test")
        success, message = False, f"Erreur inattendue : {exc}"
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('settings.parametres'))

@settings_bp.route('/parametres/reset-whatsapp', methods=['POST'])
def reset_whatsapp():
    import urllib.request
    try:
        req = urllib.request.Request('http://127.0.0.1:3001/reset', data=b'{}', headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            flash("Session WhatsApp réinitialisée. Scannez le nouveau QR Code avec votre nouveau numéro expéditeur sur http://127.0.0.1:3001/qr", "success")
    except Exception as exc:
        flash(f"Erreur lors de la réinitialisation : {exc}", "danger")
    return redirect(url_for('settings.parametres'))
