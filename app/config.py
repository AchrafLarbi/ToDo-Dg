"""Configuration de l'application Flask et variables d'environnement."""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    DATABASE_URL = os.environ.get('DATABASE_URL')
    TEMPLATES_AUTO_RELOAD = True
    PORT = int(os.environ.get('PORT', 5000))
