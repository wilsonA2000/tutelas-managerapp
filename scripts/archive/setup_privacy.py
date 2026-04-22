"""Setup idempotente de dependencias de privacidad (Fase B.1 v5.3).

Uso: python3 scripts/setup_privacy.py

Verifica/instala:
- presidio-analyzer, presidio-anonymizer
- modelo spaCy es_core_news_md
- PII_MASTER_KEY presente en .env (genera una si falta y lo reporta)
"""

import os
import sys
import subprocess
from pathlib import Path


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _has_spacy_model(model: str) -> bool:
    try:
        import spacy
        spacy.load(model)
        return True
    except (ImportError, OSError):
        return False


def _ensure_master_key(env_path: Path) -> None:
    from cryptography.fernet import Fernet
    if not env_path.exists():
        print(f"[warn] {env_path} no existe, saltando check PII_MASTER_KEY")
        return
    content = env_path.read_text(encoding="utf-8")
    if "PII_MASTER_KEY=" in content and "PII_MASTER_KEY=\n" not in content:
        for line in content.splitlines():
            if line.startswith("PII_MASTER_KEY=") and len(line) > len("PII_MASTER_KEY="):
                print("[ok] PII_MASTER_KEY ya presente en .env")
                return
    key = Fernet.generate_key().decode()
    print(f"[action] Genera una PII_MASTER_KEY y añádela a {env_path}:")
    print(f"         PII_MASTER_KEY={key}")
    print("[warn] No añado automáticamente al .env — cópiala manualmente para evitar sobrescribir secretos existentes.")


def main() -> int:
    ok = True
    for mod in ("presidio_analyzer", "presidio_anonymizer", "spacy", "rapidfuzz"):
        if _has_module(mod):
            print(f"[ok] {mod} instalado")
        else:
            print(f"[missing] {mod} — ejecuta: pip install -r requirements.txt")
            ok = False
    if _has_spacy_model("es_core_news_md"):
        print("[ok] spaCy es_core_news_md disponible")
    else:
        print("[action] Descargando es_core_news_md...")
        r = subprocess.run([sys.executable, "-m", "spacy", "download", "es_core_news_md"])
        ok = ok and r.returncode == 0
    _ensure_master_key(Path(__file__).resolve().parent.parent / ".env")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
