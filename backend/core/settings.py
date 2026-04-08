"""Configuración centralizada con Pydantic Settings.

Carga variables desde .env con validación automática.
Uso: from backend.core.settings import settings
"""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la aplicación con validación."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
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

    # AI Providers
    GOOGLE_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    DEEPSEEK_API_KEY: str = ""
    HF_TOKEN: str = ""
    CEREBRAS_API_KEY: str = ""

    # Document Normalizer
    NORMALIZER_ENABLED: bool = True
    NORMALIZER_USE_MARKER: bool = False  # Requiere ~2GB de modelos ML
    NORMALIZER_USE_PADDLEOCR: bool = True  # Reemplaza Tesseract para español

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

    def has_google_ai(self) -> bool:
        return bool(self.GOOGLE_API_KEY)

    def has_anthropic(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)

    def has_openai(self) -> bool:
        return bool(self.OPENAI_API_KEY)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Singleton for backward compatibility
settings = get_settings()
