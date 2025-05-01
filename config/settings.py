"""
Configuraciones generales para la integración de Siigo y Google Sheets.
Actualizado para incluir Telegram y Google Cloud Storage.
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
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1cHrdIEDH_gNUsjFUZjwqw-wSmi04yOV_6RtXXUyDrVc")
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "creds.json")

# Siigo API
# Usar funciones robustas para cargar desde .env
SIIGO_USERNAME = os.getenv("SIIGO_USERNAME")
SIIGO_ACCESS_KEY = os.getenv("SIIGO_ACCESS_KEY")
SIIGO_PARTNER_ID = os.getenv("SIIGO_PARTNER_ID", "IrrelevantProjectsApp")

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")


# Database
DB_PATH = os.getenv("DB_PATH", "siigo_gsheets.db")

# Telegram Bot
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Google Cloud Storage
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "siigo-facturacion-images")
GCS_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# Cargar manualmente el archivo .env
def load_env_file():
    """
    Carga manualmente las variables del archivo .env preservando los valores exactos
    sin alterar caracteres especiales al final como '='
    
    Returns:
        dict: Diccionario con las variables cargadas
    """
    env_vars = {}
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip('\n\r')  # Solo eliminar saltos de línea, no espacios
                
                # Ignorar líneas vacías y comentarios
                if not line or line.startswith('#'):
                    continue
                
                # Dividir en key=value pero solo en la primera aparición de =
                parts = line.split('=', 1)  # Dividir solo en el primer =
                if len(parts) != 2:
                    continue
                
                key = parts[0].strip()  # Strip espacios en la clave
                value = parts[1]  # NO hacer strip del valor para preservar caracteres como =
                
                # Guardar en el diccionario y en os.environ
                env_vars[key] = value
                os.environ[key] = value
        
        return env_vars
    except Exception as e:
        print(f"Error al cargar el archivo .env: {e}")
        return {}

# Volver a cargar con nuestra función personalizada para asegurar que no se pierda el "="
ENV_VARS = load_env_file()