"""Configuracion central de la aplicacion.

Backward-compatible wrapper around backend.core.settings.
New code should import from backend.core.settings directly.
"""

from pathlib import Path
from backend.core.settings import settings

# Rutas (backward compatibility)
BASE_DIR = Path(settings.BASE_DIR)
APP_DIR = settings.app_dir
DB_PATH = settings.db_path
CSV_PATH = settings.csv_path
EXPORTS_DIR = settings.exports_dir

# Gmail
GMAIL_USER = settings.GMAIL_USER
GMAIL_APP_PASSWORD = settings.GMAIL_APP_PASSWORD

# Groq AI
GROQ_API_KEY = settings.GROQ_API_KEY
GROQ_MODEL = settings.GROQ_MODEL

# CSV
CSV_DELIMITER = ";"
CSV_COLUMNS = [
    "RADICADO_23_DIGITOS", "RADICADO_FOREST", "ABOGADO_RESPONSABLE",
    "ACCIONANTE", "ACCIONADOS", "VINCULADOS", "DERECHO_VULNERADO",
    "JUZGADO", "CIUDAD", "FECHA_INGRESO", "ASUNTO", "PRETENSIONES",
    "OFICINA_RESPONSABLE", "ESTADO", "FECHA_RESPUESTA",
    "SENTIDO_FALLO_1ST", "FECHA_FALLO_1ST", "IMPUGNACION",
    "QUIEN_IMPUGNO", "FOREST_IMPUGNACION", "JUZGADO_2ND",
    "SENTIDO_FALLO_2ND", "FECHA_FALLO_2ND", "INCIDENTE",
    "FECHA_APERTURA_INCIDENTE", "RESPONSABLE_DESACATO",
    "DECISION_INCIDENTE", "OBSERVACIONES",
]
