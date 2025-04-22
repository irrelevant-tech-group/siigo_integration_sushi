"""
Configuraciones generales para la integración de Siigo y Google Sheets.
"""
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Google Sheets
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
SPREADSHEET_ID = "1cHrdIEDH_gNUsjFUZjwqw-wSmi04yOV_6RtXXUyDrVc"
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "creds.json")

# Siigo API
SIIGO_USERNAME = os.getenv("SIIGO_USERNAME")
SIIGO_ACCESS_KEY = os.getenv("SIIGO_ACCESS_KEY")
SIIGO_PARTNER_ID = os.getenv("SIIGO_PARTNER_ID", "IrrelevantProjectsApp")

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-3-opus-20240229"

# Database
DB_PATH = "siigo_gsheets.db"

# Cargar manualmente el archivo .env
def load_env_file():
    """Carga manualmente las variables del archivo .env"""
    env_vars = {}
    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    env_vars[key] = value
        return env_vars
    except Exception as e:
        print(f"Error al cargar el archivo .env: {e}")
        return {}

# Variables adicionales del .env
ENV_VARS = load_env_file()