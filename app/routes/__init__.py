"""Package Routes contenant les Blueprints de l'application."""
from .auth import auth_bp
from .dashboard import dashboard_bp
from .projects import projects_bp
from .tasks import tasks_bp
from .collaborators import collaborators_bp
from .settings import settings_bp
from .calendar import calendar_bp

__all__ = [
    'auth_bp',
    'dashboard_bp',
    'projects_bp',
    'tasks_bp',
    'collaborators_bp',
    'settings_bp',
    'calendar_bp',
]
