"""Point d'entree WSGI pour les serveurs de production (Gunicorn / Render)."""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run()
