"""Acces a la base de donnees PostgreSQL (hebergee, ex. Render)."""
import os
import secrets

import psycopg2
import psycopg2.extras

PRIORITIES = ['Basse', 'Normale', 'Haute', 'Urgente']
SENSITIVITIES = ['Faible', 'Normale', 'Elevee', 'Critique']
STATUSES = ['A faire', 'En cours', 'Terminee', 'Cloturee']
RECURRENCE_TYPES = [
    'Aucune',
    'Hebdomadaire',
    'Mensuelle',
    'Chaque 1er du mois',
    'Chaque 5 du mois',
    'Chaque 10 du mois',
    'Chaque 15 du mois',
    'Chaque 20 du mois',
    'Chaque 25 du mois',
]


SCHEMA = """
CREATE TABLE IF NOT EXISTS collaborators (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    start_date TEXT,
    deadline TEXT,
    status TEXT DEFAULT 'En cours',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    collaborator_id INTEGER REFERENCES collaborators(id) ON DELETE SET NULL,
    priority TEXT DEFAULT 'Normale',
    sensitivity TEXT DEFAULT 'Normale',
    due_date TEXT,
    status TEXT DEFAULT 'A faire',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT,
    closure_comment TEXT,
    last_reminder_at TEXT,
    reminder_count INTEGER DEFAULT 0,
    update_token TEXT UNIQUE,
    recurrence_type TEXT DEFAULT 'Aucune'
);

CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    type TEXT,
    success INTEGER,
    message TEXT
);

CREATE TABLE IF NOT EXISTS task_updates (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    previous_status TEXT,
    new_status TEXT,
    previous_due_date TEXT,
    new_due_date TEXT,
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    smtp_host TEXT DEFAULT 'smtp.office365.com',
    smtp_port INTEGER DEFAULT 587,
    smtp_user TEXT,
    smtp_password TEXT,
    sender_name TEXT DEFAULT 'Gestion des taches',
    sender_email TEXT,
    reminder_days_before INTEGER DEFAULT 2,
    daily_check_hour INTEGER DEFAULT 8,
    auto_reminders_enabled INTEGER DEFAULT 1,
    base_url TEXT
);
"""


def _database_url():
    url = os.environ['DATABASE_URL']
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    return url


def get_db():
    conn = psycopg2.connect(_database_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute("ALTER TABLE settings ADD COLUMN IF NOT EXISTS sender_email TEXT")
        cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_type TEXT DEFAULT 'Aucune'")
        cur.execute("INSERT INTO settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    conn.commit()
    conn.close()


# ---- Settings -------------------------------------------------------------

def get_settings():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM settings WHERE id = 1")
        row = cur.fetchone()
    conn.close()
    return row


def update_settings(data):
    conn = get_db()
    with conn.cursor() as cur:
        if data.get('smtp_password'):
            cur.execute(
                """UPDATE settings SET smtp_host=%s, smtp_port=%s, smtp_user=%s, smtp_password=%s,
                   sender_name=%s, sender_email=%s, reminder_days_before=%s, daily_check_hour=%s,
                   auto_reminders_enabled=%s, base_url=%s WHERE id=1""",
                (data['smtp_host'], data['smtp_port'], data['smtp_user'], data['smtp_password'],
                 data['sender_name'], data.get('sender_email') or None,
                 data['reminder_days_before'], data['daily_check_hour'],
                 data['auto_reminders_enabled'], data['base_url']),
            )
        else:
            cur.execute(
                """UPDATE settings SET smtp_host=%s, smtp_port=%s, smtp_user=%s,
                   sender_name=%s, sender_email=%s, reminder_days_before=%s, daily_check_hour=%s,
                   auto_reminders_enabled=%s, base_url=%s WHERE id=1""",
                (data['smtp_host'], data['smtp_port'], data['smtp_user'],
                 data['sender_name'], data.get('sender_email') or None,
                 data['reminder_days_before'], data['daily_check_hour'],
                 data['auto_reminders_enabled'], data['base_url']),
            )
    conn.commit()
    conn.close()


# ---- Collaborateurs ---------------------------------------------------------

def list_collaborateurs():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM collaborators ORDER BY name")
        rows = cur.fetchall()
    conn.close()
    return rows


def get_collaborateur(collab_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM collaborators WHERE id = %s", (collab_id,))
        row = cur.fetchone()
    conn.close()
    return row


def create_collaborateur(name, email, phone):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO collaborators (name, email, phone) VALUES (%s, %s, %s) RETURNING id",
            (name, email, phone or None),
        )
        new_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return new_id


def update_collaborateur(collab_id, name, email, phone):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE collaborators SET name=%s, email=%s, phone=%s WHERE id=%s",
            (name, email, phone or None, collab_id),
        )
    conn.commit()
    conn.close()


def delete_collaborateur(collab_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE tasks SET collaborator_id = NULL WHERE collaborator_id = %s", (collab_id,))
        cur.execute("DELETE FROM collaborators WHERE id = %s", (collab_id,))
    conn.commit()
    conn.close()


# ---- Projets ----------------------------------------------------------------

def list_projets():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM projects ORDER BY created_at DESC")
        rows = cur.fetchall()
    conn.close()
    return rows


def get_projet(project_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
    conn.close()
    return row


def create_projet(name, description, start_date, deadline, status):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (name, description, start_date, deadline, status) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (name, description or None, start_date or None, deadline or None, status),
        )
        new_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return new_id


def update_projet(project_id, name, description, start_date, deadline, status):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE projects SET name=%s, description=%s, start_date=%s, deadline=%s, status=%s
               WHERE id=%s""",
            (name, description or None, start_date or None, deadline or None, status, project_id),
        )
    conn.commit()
    conn.close()


def delete_projet(project_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
    conn.commit()
    conn.close()


# ---- Taches -------------------------------------------------------------------

TASK_SELECT = """
    SELECT tasks.*, projects.name AS project_name,
           collaborators.name AS collaborator_name, collaborators.email AS collaborator_email
    FROM tasks
    LEFT JOIN projects ON projects.id = tasks.project_id
    LEFT JOIN collaborators ON collaborators.id = tasks.collaborator_id
"""


def list_taches(project_id=None, collaborator_id=None, status=None, priority=None):
    query = TASK_SELECT + " WHERE 1=1"
    params = []
    if project_id:
        query += " AND tasks.project_id = %s"
        params.append(project_id)
    if collaborator_id:
        query += " AND tasks.collaborator_id = %s"
        params.append(collaborator_id)
    if status:
        query += " AND tasks.status = %s"
        params.append(status)
    if priority:
        query += " AND tasks.priority = %s"
        params.append(priority)
    query += " ORDER BY (tasks.due_date IS NULL), tasks.due_date ASC, tasks.created_at DESC"
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    conn.close()
    return rows


def list_taches_by_projet(project_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            TASK_SELECT + " WHERE tasks.project_id = %s ORDER BY (tasks.due_date IS NULL), tasks.due_date ASC",
            (project_id,),
        )
        rows = cur.fetchall()
    conn.close()
    return rows


def list_taches_by_collaborateur(collaborator_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            TASK_SELECT + " WHERE tasks.collaborator_id = %s ORDER BY (tasks.due_date IS NULL), tasks.due_date ASC",
            (collaborator_id,),
        )
        rows = cur.fetchall()
    conn.close()
    return rows


def get_tache(task_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(TASK_SELECT + " WHERE tasks.id = %s", (task_id,))
        row = cur.fetchone()
    conn.close()
    return row


def get_tache_by_token(token):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(TASK_SELECT + " WHERE tasks.update_token = %s", (token,))
        row = cur.fetchone()
    conn.close()
    return row


def create_tache(title, description, project_id, collaborator_id, priority, sensitivity, due_date, recurrence_type='Aucune'):
    conn = get_db()
    token = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO tasks (title, description, project_id, collaborator_id, priority,
               sensitivity, due_date, update_token, recurrence_type)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (title, description or None, project_id or None, collaborator_id or None,
             priority, sensitivity, due_date or None, token, recurrence_type or 'Aucune'),
        )
        new_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return new_id


def update_tache(task_id, title, description, project_id, collaborator_id, priority, sensitivity, due_date, recurrence_type='Aucune'):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE tasks SET title=%s, description=%s, project_id=%s, collaborator_id=%s,
               priority=%s, sensitivity=%s, due_date=%s, recurrence_type=%s WHERE id=%s""",
            (title, description or None, project_id or None, collaborator_id or None,
             priority, sensitivity, due_date or None, recurrence_type or 'Aucune', task_id),
        )
    conn.commit()
    conn.close()


def update_statut(task_id, status, closure_comment, closed_at):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tasks SET status=%s, closure_comment=%s, closed_at=%s WHERE id=%s",
            (status, closure_comment or None, closed_at, task_id),
        )
    conn.commit()
    conn.close()
    if status in ('Terminee', 'Cloturee', 'Terminé'):
        process_task_recurrence(task_id)


def collaborator_update_tache(task_id, new_status, new_due_date, comment):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT status, due_date FROM tasks WHERE id = %s", (task_id,))
        current = cur.fetchone()
        closed_at = None
        if new_status in ('Terminee', 'Cloturee', 'Terminé'):
            import datetime as _dt
            closed_at = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute(
            "UPDATE tasks SET status=%s, due_date=%s, closed_at=%s WHERE id=%s",
            (new_status, new_due_date or current['due_date'], closed_at, task_id),
        )
        cur.execute(
            """INSERT INTO task_updates (task_id, previous_status, new_status, previous_due_date,
               new_due_date, comment) VALUES (%s, %s, %s, %s, %s, %s)""",
            (task_id, current['status'], new_status, current['due_date'],
             new_due_date or current['due_date'], comment or None),
        )
    conn.commit()
    conn.close()
    if new_status in ('Terminee', 'Cloturee', 'Terminé'):
        process_task_recurrence(task_id)


def calculate_next_due_date(base_date_str, recurrence_type):
    import datetime as _dt
    import calendar as _calendar
    import re

    if not base_date_str:
        base_date = _dt.date.today()
    else:
        try:
            base_date = _dt.datetime.strptime(base_date_str[:10], '%Y-%m-%d').date()
        except Exception:
            base_date = _dt.date.today()

    if recurrence_type == 'Hebdomadaire':
        next_date = base_date + _dt.timedelta(days=7)
    elif recurrence_type == 'Mensuelle':
        month = base_date.month % 12 + 1
        year = base_date.year + (base_date.month // 12)
        max_day = _calendar.monthrange(year, month)[1]
        day = min(base_date.day, max_day)
        next_date = _dt.date(year, month, day)
    elif recurrence_type and ('Chaque' in recurrence_type or 'du mois' in recurrence_type or 'jour' in recurrence_type):
        # Extract target day number X (e.g. "Chaque 5 du mois" -> 5)
        match = re.search(r'\d+', recurrence_type)
        target_day = int(match.group()) if match else 1
        target_day = max(1, min(31, target_day))

        month = base_date.month % 12 + 1
        year = base_date.year + (base_date.month // 12)
        max_day = _calendar.monthrange(year, month)[1]
        day = min(target_day, max_day)
        next_date = _dt.date(year, month, day)
    else:
        return base_date_str

    return next_date.isoformat()


def process_task_recurrence(task_id):
    task = get_tache(task_id)
    if not task or not task.get('recurrence_type') or task.get('recurrence_type') == 'Aucune':
        return None


    # Calculate next due date
    next_due = calculate_next_due_date(task.get('due_date'), task['recurrence_type'])

    # Remove recurrence on the completed/old task so it doesn't trigger again
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE tasks SET recurrence_type = 'Aucune' WHERE id = %s", (task_id,))
    conn.commit()
    conn.close()

    # Create new task instance for next occurrence
    new_task_id = create_tache(
        title=task['title'],
        description=task['description'],
        project_id=task['project_id'],
        collaborator_id=task['collaborator_id'],
        priority=task['priority'],
        sensitivity=task['sensitivity'],
        due_date=next_due,
        recurrence_type=task['recurrence_type'],
    )

    # Automatically send email notification to collaborator for new occurrence
    if task.get('collaborator_id'):
        from app.services import send_task_notification_async
        send_task_notification_async(new_task_id)

    return new_task_id


def delete_tache(task_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM reminders WHERE task_id = %s", (task_id,))
        cur.execute("DELETE FROM task_updates WHERE task_id = %s", (task_id,))
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()
    conn.close()


def register_reminder_sent(task_id, sent_at):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tasks SET last_reminder_at=%s, reminder_count = reminder_count + 1 WHERE id=%s",
            (sent_at, task_id),
        )
    conn.commit()
    conn.close()


# ---- Historique -------------------------------------------------------------

def log_reminder(task_id, reminder_type, success, message):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO reminders (task_id, type, success, message) VALUES (%s, %s, %s, %s)",
            (task_id, reminder_type, 1 if success else 0, message),
        )
    conn.commit()
    conn.close()


def list_reminders(task_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM reminders WHERE task_id = %s ORDER BY sent_at DESC", (task_id,))
        rows = cur.fetchall()
    conn.close()
    return rows


def list_task_updates(task_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM task_updates WHERE task_id = %s ORDER BY created_at DESC", (task_id,))
        rows = cur.fetchall()
    conn.close()
    return rows


# ---- Dashboard -------------------------------------------------------------

def dashboard_stats(today, due_soon_limit):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM tasks WHERE status NOT IN ('Terminee', 'Cloturee')")
        actives = cur.fetchone()['n']
        cur.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE due_date IS NOT NULL AND due_date < %s "
            "AND status NOT IN ('Terminee', 'Cloturee')",
            (today,),
        )
        overdue = cur.fetchone()['n']
        cur.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE due_date IS NOT NULL AND due_date >= %s AND due_date <= %s "
            "AND status NOT IN ('Terminee', 'Cloturee')",
            (today, due_soon_limit),
        )
        due_soon = cur.fetchone()['n']
        cur.execute("SELECT COUNT(*) AS n FROM tasks WHERE status IN ('Terminee', 'Cloturee')")
        closed = cur.fetchone()['n']
    conn.close()
    return {'actives': actives, 'overdue': overdue, 'due_soon': due_soon, 'closed': closed}


def stats_by_collaborateur(today, due_soon_limit):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.name,
                   COUNT(*) FILTER (WHERE t.status NOT IN ('Terminee','Cloturee')) AS actives,
                   COUNT(*) FILTER (
                       WHERE t.due_date IS NOT NULL AND t.due_date < %s
                       AND t.status NOT IN ('Terminee','Cloturee')
                   ) AS overdue,
                   COUNT(*) FILTER (
                       WHERE t.due_date IS NOT NULL AND t.due_date >= %s AND t.due_date <= %s
                       AND t.status NOT IN ('Terminee','Cloturee')
                   ) AS due_soon,
                   COUNT(*) FILTER (WHERE t.status IN ('Terminee','Cloturee')) AS closed
            FROM collaborators c
            LEFT JOIN tasks t ON t.collaborator_id = c.id
            GROUP BY c.id, c.name
            ORDER BY c.name
            """,
            (today, today, due_soon_limit),
        )
        rows = cur.fetchall()
    conn.close()
    return rows


def overdue_tasks(today):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            TASK_SELECT + " WHERE tasks.due_date IS NOT NULL AND tasks.due_date < %s "
            "AND tasks.status NOT IN ('Terminee', 'Cloturee') ORDER BY tasks.due_date ASC",
            (today,),
        )
        rows = cur.fetchall()
    conn.close()
    return rows


def due_soon_tasks(today, limit_date):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            TASK_SELECT + " WHERE tasks.due_date IS NOT NULL AND tasks.due_date >= %s AND tasks.due_date <= %s "
            "AND tasks.status NOT IN ('Terminee', 'Cloturee') ORDER BY tasks.due_date ASC",
            (today, limit_date),
        )
        rows = cur.fetchall()
    conn.close()
    return rows


def tasks_needing_reminder(today, limit_date):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            TASK_SELECT + " WHERE tasks.due_date IS NOT NULL AND tasks.due_date <= %s "
            "AND tasks.status NOT IN ('Terminee', 'Cloturee') AND collaborators.email IS NOT NULL "
            "ORDER BY tasks.due_date ASC",
            (limit_date,),
        )
        rows = cur.fetchall()
    conn.close()
    return rows


def get_collaborateur_stats(collaborator_id):
    import datetime as _dt
    today_str = _dt.date.today().isoformat()
    tasks = list_taches_by_collaborateur(collaborator_id)

    total = len(tasks)
    active = 0
    completed = 0
    overdue = 0
    completed_on_time = 0
    completed_late = 0

    status_counts = {'A faire': 0, 'En cours': 0, 'Terminee': 0, 'Cloturee': 0}
    priority_counts = {'Basse': 0, 'Normale': 0, 'Haute': 0, 'Urgente': 0}

    total_resolution_seconds = 0
    resolution_count = 0
    longest_task = None
    max_duration_seconds = -1

    for t in tasks:
        st = t.get('status')
        pr = t.get('priority', 'Normale')
        if pr in priority_counts:
            priority_counts[pr] += 1

        is_closed = st in ('Terminee', 'Cloturee', 'Terminé')
        if is_closed:
            completed += 1
            if st in status_counts:
                status_counts[st] += 1
            else:
                status_counts['Terminee'] += 1

            due = t.get('due_date')
            closed_at_str = t.get('closed_at')
            if due and closed_at_str:
                closed_date = closed_at_str[:10]
                if closed_date <= due:
                    completed_on_time += 1
                else:
                    completed_late += 1
            else:
                completed_on_time += 1

            if closed_at_str and t.get('created_at'):
                try:
                    c_dt = t['created_at'] if isinstance(t['created_at'], _dt.datetime) else _dt.datetime.strptime(str(t['created_at'])[:19], '%Y-%m-%d %H:%M:%S')
                    cl_dt = _dt.datetime.strptime(str(closed_at_str)[:19], '%Y-%m-%d %H:%M:%S')
                    diff_sec = (cl_dt - c_dt).total_seconds()
                    if diff_sec >= 0:
                        total_resolution_seconds += diff_sec
                        resolution_count += 1
                        if diff_sec > max_duration_seconds:
                            max_duration_seconds = diff_sec
                            duration_days = round(diff_sec / 86400.0, 1)
                            longest_task = {
                                'title': t['title'],
                                'duration_days': duration_days if duration_days >= 0.1 else 0.1,
                                'closed_at': closed_at_str[:10]
                            }
                except Exception:
                    pass
        else:
            active += 1
            if st in status_counts:
                status_counts[st] += 1
            due = t.get('due_date')
            if due and due < today_str:
                overdue += 1

    avg_resolution_days = round((total_resolution_seconds / resolution_count) / 86400.0, 1) if resolution_count > 0 else 0
    completion_rate = round((completed / total * 100), 1) if total > 0 else 0
    on_time_rate = round((completed_on_time / completed * 100), 1) if completed > 0 else 0

    return {
        'total': total,
        'active': active,
        'completed': completed,
        'overdue': overdue,
        'completed_on_time': completed_on_time,
        'completed_late': completed_late,
        'completion_rate': completion_rate,
        'on_time_rate': on_time_rate,
        'avg_resolution_days': avg_resolution_days,
        'longest_task': longest_task,
        'status_counts': status_counts,
        'priority_counts': priority_counts
    }

