"""Configuración centralizada con Pydantic Settings.

Carga variables desde .env con validación automática.
Uso: from backend.core.settings import settings

v5.5: respeta la env var TUTELAS_ENV_FILE para seleccionar un archivo .env
alterno (ej. .env.experiment) sin tocar el .env de producción.
"""

import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


_DEFAULT_ENV_FILE = str(Path(__file__).resolve().parent.parent.parent / ".env")
_ENV_FILE_OVERRIDE = os.environ.get("TUTELAS_ENV_FILE")
_EFFECTIVE_ENV_FILE = (
    str(Path(_ENV_FILE_OVERRIDE).resolve()) if _ENV_FILE_OVERRIDE else _DEFAULT_ENV_FILE
)


class Settings(BaseSettings):
    """Configuración de la aplicación con validación."""

    model_config = SettingsConfigDict(
        env_file=_EFFECTIVE_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Rutas
    BASE_DIR: str = "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026"

    # Gmail
    GMAIL_USER: str = ""
    GMAIL_APP_PASSWORD: str = ""

    # JWT Auth
    JWT_SECRET: str = ""  # Auto-generated if empty

    # AI Providers (v5.4: solo DeepSeek + Anthropic)
    DEEPSEEK_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # Document Normalizer
    NORMALIZER_ENABLED: bool = True
    NORMALIZER_USE_MARKER: bool = False  # Requiere ~2GB de modelos ML
    NORMALIZER_USE_PADDLEOCR: bool = True  # Reemplaza Tesseract para español

    # Unified Extractor (IR-based)
    UNIFIED_EXTRACTOR_ENABLED: bool = True  # True = usar extractor unificado IR
    KB_ENHANCED_EXTRACTION: bool = True  # True = inyectar contexto KB en prompt IA

    # PII Redaction (v5.3) — anonimización antes de enviar a IA externa
    PII_REDACTION_ENABLED: bool = True
    PII_MODE_DEFAULT: str = "selective"  # "selective" | "aggressive"
    PII_GATE_STRICT: bool = False        # False (default) = solo warn. True = bloquear envío si gate detecta PII residual
    PII_PRESIDIO_MODEL: str = "es_core_news_md"
    PII_MASTER_KEY: str = ""             # Fernet key. Si vacía y PII_REDACTION_ENABLED, auto-genera en memoria con warning

    # v5.5 Experiment mode — probar ingesta completa desde Gmail en workspace paralelo
    EXPERIMENT_MODE: bool = False         # True = modo experimento (DB fresh, workspace vacío)
    GMAIL_READ_ONLY: bool = False         # True = NO marca emails como leído en Gmail (preserva estado)
    GMAIL_HISTORICAL_QUERY: str = ""      # Query Gmail alternativa (ej. "in:inbox") para sync histórico
    SYNC_BATCH_SIZE: int = 100            # Tamaño por defecto de batch en /api/emails/sync-batch
    AI_PROVIDER_PRIMARY: str = ""         # Override del router. "deepseek" o "anthropic". Vacío = respetar ROUTING_CHAINS
    EXTRACTION_MAX_WORKERS: int = 3       # Workers paralelos en /api/extraction/batch. En WSL usar 2 para no saturar.

    # CSV
    CSV_DELIMITER: str = ";"
    CSV_COLUMNS: list[str] = [
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

    # Derived paths (computed)
    @property
    def app_dir(self) -> Path:
        return Path(self.BASE_DIR) / "tutelas-app"

    @property
    def db_path(self) -> Path:
        return self.app_dir / "data" / "tutelas.db"

    @property
    def csv_path(self) -> Path:
        return Path(self.BASE_DIR) / "COMPILADO_TUTELAS_2026.csv"

    @property
    def exports_dir(self) -> Path:
        path = self.app_dir / "data" / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def has_gmail(self) -> bool:
        return bool(self.GMAIL_USER and self.GMAIL_APP_PASSWORD)

    def has_deepseek(self) -> bool:
        return bool(self.DEEPSEEK_API_KEY)

    def has_anthropic(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Singleton for backward compatibility
settings = get_settings()
