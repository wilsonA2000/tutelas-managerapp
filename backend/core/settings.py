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
_POD_ENV_FILE = Path("/workspace/tutelas-app/.env.pod")

if _ENV_FILE_OVERRIDE:
    _EFFECTIVE_ENV_FILE = str(Path(_ENV_FILE_OVERRIDE).resolve())
elif _POD_ENV_FILE.exists():
    # Auto-deteccion de pod RunPod: si /workspace/tutelas-app/.env.pod existe,
    # cargarlo sin depender de TUTELAS_ENV_FILE manual al lanzar uvicorn.
    _EFFECTIVE_ENV_FILE = str(_POD_ENV_FILE)
else:
    _EFFECTIVE_ENV_FILE = _DEFAULT_ENV_FILE


# Cargar el .env EFECTIVO a os.environ. Pydantic Settings (abajo) solo puebla el objeto
# `settings`, NO os.environ — pero gran parte del proyecto lee flags con os.getenv()
# directo (V9_LLM_*, RAMA_JUDICIAL_*, LLM_GGUF/CTX/REASONING, LLM_LOCAL_PRIMARY en
# chat.py, …). Sin esto esos flags quedaban INERTES en su default aunque el .env dijera
# otra cosa (fuente única rota). settings.py se importa tempranísimo, así que cargarlo
# aquí garantiza que os.getenv y Pydantic vean lo mismo. override=False: una var ya
# presente en el entorno gana (exports de start.sh, TUTELAS_ENV_FILE, monkeypatch en
# tests). (fix 2026-06-20 — ver project_env_flags_inertes.)
try:
    from dotenv import load_dotenv
    load_dotenv(_EFFECTIVE_ENV_FILE, override=False)
except Exception:  # pragma: no cover - dotenv siempre instalado, defensivo
    pass


class Settings(BaseSettings):
    """Configuración de la aplicación con validación."""

    model_config = SettingsConfigDict(
        env_file=_EFFECTIVE_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Rutas — default derivado del path del modulo (funciona WSL y pod RunPod).
    # En pod, .env.pod sobreescribe con BASE_DIR=/workspace/tutelas-data.
    BASE_DIR: str = str(Path(__file__).resolve().parents[3])

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
    NORMALIZER_USE_PADDLEOCR: bool = True  # Reemplaza Tesseract para español

    # (Retirado) PII Redaction (v5.3): la anonimización pre-IA-externa se quitó —
    # todo el procesamiento es local (Qwen3 en el equipo), el texto no sale del equipo.
    # Se borró backend/privacy/ y la columna Case.pii_mode del modelo.

    # v5.5 Experiment mode — probar ingesta completa desde Gmail en workspace paralelo
    EXPERIMENT_MODE: bool = False         # True = modo experimento (DB fresh, workspace vacío)
    GMAIL_READ_ONLY: bool = False         # True = NO marca emails como leído en Gmail (preserva estado)
    GMAIL_HISTORICAL_QUERY: str = ""      # Query Gmail alternativa (ej. "in:inbox") para sync histórico
    SYNC_BATCH_SIZE: int = 100            # Tamaño por defecto de batch en /api/emails/sync-batch
    EXTRACTION_MAX_WORKERS: int = 3       # Workers paralelos en /api/extraction/batch. En WSL usar 2 para no saturar.

    # Verificación bayesiana de pertenencia documento→caso (verify_document_belongs en
    # extraction/doc_ops.py). VIVO en prod (.env=true). El nombre es histórico (v6); NO es
    # el pipeline cognitivo de 7 capas (borrado): hoy solo gatea el assignment bayesiano.
    USE_COGNITIVE_PIPELINE: bool = False

    # IURIS LLM Local (2026-05-03): enrutar IA cuantizada local
    # Cuando LLM_LOCAL_URL está set y LLM_LOCAL_PRIMARY=True, smart_router
    # usa este endpoint como primary, con fallback a Anthropic/DeepSeek.
    LLM_LOCAL_URL: str = "http://127.0.0.1:8765"   # llama-server con Qwen3 4B + LoRA IURIS
    LLM_LOCAL_PRIMARY: bool = False                # True = primary; False = no usar local
    LLM_LOCAL_MODEL_ID: str = "qwen3-4b-iuris"     # identificador para token_usage
    LLM_LOCAL_SYSTEM_PROMPT_PATH: str = "docs/iuris/SYSTEM_PROMPT_COMPILER.md"

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
    # APP_DIR es FIJO (donde vive este código + DB), independiente de BASE_DIR.
    # BASE_DIR controla SOLO la raíz donde se crean carpetas de casos.
    # Esto permite cambiar BASE_DIR sin migrar la DB.
    @property
    def app_dir(self) -> Path:
        return Path(__file__).resolve().parents[2]

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
