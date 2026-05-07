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
    NORMALIZER_USE_MARKER: bool = False  # Requiere ~2GB de modelos ML
    NORMALIZER_USE_PADDLEOCR: bool = True  # Reemplaza Tesseract para español
    # v6.1: PaddleOCR-VL 1.5 (VLM, 94.5% OmniDocBench, requiere GPU CUDA 12.6+ wheels)
    NORMALIZER_USE_PADDLEOCR_VL: bool = True
    NORMALIZER_PADDLE_DEVICE: str = "gpu:0"   # "gpu:0" | "cpu" — solo para VL native
    NORMALIZER_PADDLE_VL_MAX_PAGES: int = 30  # PDFs > N páginas caen a page-by-page
    # v6.1.1: vLLM acceleration server. Si URL definida, usa backend "vllm-server"
    # (5-10x speedup). Si vacío, usa "native" (eager mode, lento).
    NORMALIZER_VLLM_SERVER_URL: str = ""      # ej. "http://127.0.0.1:8118/v1"
    NORMALIZER_VL_MAX_CONCURRENCY: int = 16   # request paralelos al vllm-server

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

    # v6.0 Refactor cognitivo — feature flags
    USE_COGNITIVE_PIPELINE: bool = False  # True = pipeline de 7 capas cognitivas; False = v5.5 legacy
    COGNITIVE_ENTROPY_THRESHOLD: float = 2.2  # Umbral H(caso) sobre el cual marcar REVISION_HUMANA

    # F2 (2026-05-02): confidence scoring por campo (IURIS appliance vendible con SLA jurídico)
    USE_FIELD_CONFIDENCE: bool = False     # True = computa y persiste field_confidences_json post-extracción
    CONFIDENCE_OK_THRESHOLD: float = 0.85  # ≥ → banda OK
    CONFIDENCE_REVIEW_THRESHOLD: float = 0.50  # entre [REVIEW, OK) → banda REVISAR; < REVIEW → BAJO

    # IURIS LLM Local (2026-05-03): enrutar IA cuantizada local
    # Cuando LLM_LOCAL_URL está set y LLM_LOCAL_PRIMARY=True, smart_router
    # usa este endpoint como primary, con fallback a Anthropic/DeepSeek.
    LLM_LOCAL_URL: str = "http://127.0.0.1:8765"   # llama-server con Qwen3 4B + LoRA IURIS
    LLM_LOCAL_PRIMARY: bool = False                # True = primary; False = no usar local
    LLM_LOCAL_MODEL_ID: str = "qwen3-4b-iuris"     # identificador para token_usage
    LLM_LOCAL_SYSTEM_PROMPT_PATH: str = "docs/iuris/SYSTEM_PROMPT_COMPILER.md"

    # v6.1.1: modo 100% local (sin IA externa, sin PII redaction porque datos no salen)
    LOCAL_ONLY: bool = False              # True = silencia smart_router + ai_extractor + skip Presidio
    USE_AI_EXTRACTION: bool = True        # False = nunca invocar route() para extracción IA

    # v6.0.2 Remote extraction (RunPod GPU pod) — delega Capas 0-5 a un worker remoto.
    # Las capas 6-7 (consolidator cross-case + persist) siempre se ejecutan local.
    USE_REMOTE_EXTRACTION: bool = False
    REMOTE_EXTRACTION_URL: str = ""       # ej. https://<pod-id>-8000.proxy.runpod.net
    REMOTE_EXTRACTION_TOKEN: str = ""     # bearer token del pod
    REMOTE_EXTRACTION_TIMEOUT: int = 600  # segundos por caso (casos pesados ~5-8 min)
    REMOTE_EXTRACTION_STRICT: bool = False  # True = si pod falla NO hacer fallback local
                                            # (preserva RAM local; caso queda PENDIENTE para retry)

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
