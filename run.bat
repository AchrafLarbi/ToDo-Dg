@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python n'est pas trouve dans le PATH. Installez-le depuis https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist venv (
    echo Creation de l'environnement Python...
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -q -r requirements.txt

if not exist .env (
    echo Aucun fichier .env trouve. Creez-en un a partir de .env.example
    echo avec votre DATABASE_URL, SECRET_KEY et ADMIN_PASSWORD avant de continuer.
    pause
    exit /b 1
)

echo Lancement de l'application sur http://127.0.0.1:5000 ...
start "" http://127.0.0.1:5000
python app.py

pause
