"""Blueprint pour la vue Calendrier des tâches."""
from flask import Blueprint, render_template, jsonify, request
from app.models import database

calendar_bp = Blueprint('calendar', __name__)

@calendar_bp.route('/calendrier')
def calendrier():
    return render_template('calendar/calendar.html')

@calendar_bp.route('/api/calendar/events')
def calendar_events():
    hide_closed = request.args.get('hide_closed', '0') == '1'
    tasks = database.list_taches()
    events = []
    
    for t in tasks:
        due = t.get('due_date')
        if not due:
            continue
            
        status = t.get('status', 'A faire')
        if hide_closed and status in ('Terminee', 'Cloturee', 'Terminé'):
            continue
            
        priority = t.get('priority', 'Normale')
        collab = t.get('collaborator_name')
        
        # Color coding based on status & priority
        if status in ('Terminee', 'Cloturee', 'Terminé'):
            bg_color = '#10b981' # Emerald green
            border_color = '#059669'
        elif priority == 'Urgente':
            bg_color = '#f43f5e' # Rose red
            border_color = '#e11d48'
        elif priority == 'Haute':
            bg_color = '#f59e0b' # Amber orange
            border_color = '#d97706'
        elif status == 'En cours':
            bg_color = '#6366f1' # Indigo blue
            border_color = '#4f46e5'
        else:
            bg_color = '#64748b' # Slate gray
            border_color = '#475569'
            
        title_text = t['title']
        if collab:
            title_text += f" ({collab})"
            
        events.append({
            'id': str(t['id']),
            'title': title_text,
            'start': due,
            'url': f"/taches/{t['id']}",
            'backgroundColor': bg_color,
            'borderColor': border_color,
            'textColor': '#ffffff',
            'extendedProps': {
                'status': status,
                'priority': priority,
                'collaborator': collab or 'Non assigné',
                'project': t.get('project_name') or 'Sans projet',
            }
        })
        
    return jsonify(events)

@calendar_bp.route('/api/calendar/update-due-date', methods=['POST'])
def update_due_date():
    data = request.get_json() or {}
    task_id = data.get('task_id')
    due_date = data.get('due_date')
    
    if not task_id or not due_date:
        return jsonify({'success': False, 'message': 'Paramètres manquants'}), 400
        
    try:
        task_id = int(task_id)
        database.update_tache_due_date(task_id, due_date)
        
        task = database.get_tache(task_id)
        if task and task.get('collaborator_id'):
            from app.services.email_service import send_task_notification_async
            send_task_notification_async(task_id)
            
        return jsonify({'success': True, 'message': "Date d'échéance mise à jour et collaborateur notifié !"})
    except Exception as exc:
        return jsonify({'success': False, 'message': f"Erreur de mise à jour : {exc}"}), 500
