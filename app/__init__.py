"""Package d'application Flask principal (Factory Pattern)."""
import os
from flask import Flask

from app.config import Config
from app.models import database
from app.services import start_scheduler
from app.routes import (
    auth_bp,
    dashboard_bp,
    projects_bp,
    tasks_bp,
    collaborators_bp,
    settings_bp,
)


def create_app(config_class=Config):
    app_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        template_folder=os.path.join(app_dir, 'templates'),
        static_folder=os.path.join(app_dir, 'static'),
        static_url_path='/static',
    )
    app.config.from_object(config_class)

    # Initialisation de la base de donnees et du planificateur
    database.init_db()
    start_scheduler()

    # Enregistrement des Blueprints (Controllers)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(collaborators_bp)
    app.register_blueprint(settings_bp)

    return app
