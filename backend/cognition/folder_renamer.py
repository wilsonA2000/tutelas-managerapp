"""Renombrado automático de carpetas [PENDIENTE REVISION] post-extracción.

Esta capa se invoca al final del pipeline cognitivo (Capa 7 — cognitive_persist)
para corregir el bug histórico donde el monitor Gmail crea carpetas marcadas como
[PENDIENTE REVISION] pero la extracción posterior nunca renombra la carpeta
aunque el accionante haya sido descubierto.

Reglas:
- Solo opera sobre folder_name que contenga [PENDIENTE o [REVISAR_ACCIONANTE].
- Si el accionante extraído parece un nombre real → rename con accionante.
- Si parece frase/header (heurística) → marca como [REVISAR_ACCIONANTE].
- Idempotente: correr dos veces sobre el mismo caso no rompe nada.
- No afecta carpetas que no tengan marca (no toca casos legítimos).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case


logger = logging.getLogger("tutelas.folder_renamer")


# Caracteres no permitidos en filesystem
INVALID_FS_CHARS = re.compile(r'[<>:"/\\|?*\n\r\t]')

# Detector de control chars que ensucian un folder_name aunque no tenga marca
DIRTY_FS_CHARS = re.compile(r"[\n\r\t]")

# Palabras "trampa" que indican que el accionante es texto suelto, no un nombre
TRAP_WORDS = {
    "PRETENDE", "SEÑALA", "ANTECEDENTES", "INFORMAN", "ASUNTO", "RIESGO",
    "ACREDITO", "ACREDITÓ", "APORTO", "APORTÓ", "RELACIONADA", "IMPUGNADA",
    "JUZGADO", "ELLO", "SIGNIFICA", "REFRENCIA", "REFERENCIA", "SENTENCIA",
    "FALLO", "DOCUMENTO", "CONDICION", "CONDICIÓN", "SALUD", "MEDIANTE",
    "VINCULACION", "VINCULACIÓN", "EVENTO", "PRONUNCIARSE", "COMPETENTE",
}

# Tokens-rol procesales que aparecen pegados al accionante por extracción sucia
# (ej. "JUANA PEREZ\nACCIONADO"). Se eliminan en cabeza/cola de la línea limpia.
ROLE_TOKENS = {
    "ACCIONANTE", "ACCIONANTES", "ACCIONADO", "ACCIONADOS",
    "DEMANDANTE", "DEMANDANTES", "DEMANDADO", "DEMANDADOS",
    "VINCULADO", "VINCULADOS", "TUTELANTE", "TUTELADO",
    "CONTRA", "VS", "VS.", "Y/O",
}

# Conectores que NO deberían estar al inicio de un nombre real
START_TRAPS = {"EL", "LA", "EN", "Y", "QUE", "SI", "NO", "SE", "CON",
               "POR", "PARA", "DE", "DEL", "AL", "PRETENDE"}


def clean_accionante(s: str) -> str:
    """Sanitiza el string de accionante antes de evaluarlo como nombre.

    - Toma la primera línea no vacía (corta en \\n, \\r, \\t).
    - Elimina tokens-rol procesales en cabeza y cola
      (ej. "JUANA PEREZ\\nACCIONADO" → "JUANA PEREZ").
    - Colapsa espacios.
    """
    if not s:
        return ""
    parts = re.split(r"[\n\r\t]+", s)
    first = next((p.strip() for p in parts if p.strip()), "")
    words = first.split()

    def _strip_token(w: str) -> str:
        return w.upper().strip(",.;:()[]")

    while words and _strip_token(words[-1]) in ROLE_TOKENS:
        words.pop()
    while words and _strip_token(words[0]) in ROLE_TOKENS:
        words.pop(0)

    return re.sub(r"\s+", " ", " ".join(words)).strip()


def is_likely_real_name(s: str) -> bool:
    """Heurística: ¿el string parece un nombre/persona/institución real?

    True si parece nombre, False si parece frase/descripción.
    """
    if not s or len(s.strip()) < 3:
        return False

    s = s.strip()
    words = s.split()
    if len(words) < 2 or len(words) > 12:
        return False

    # Primera palabra empieza con mayúscula y no es trampa
    first = words[0].upper()
    if first in START_TRAPS:
        return False

    # No debe contener palabras trampa
    upper_words = {w.upper().strip(",.;:") for w in words}
    if upper_words & TRAP_WORDS:
        return False

    # Mayoría de palabras deben empezar con mayúscula (nombre propio)
    upper_count = sum(1 for w in words if w and w[0].isupper())
    if upper_count < len(words) * 0.6:
        return False

    return True


def sanitize_for_fs(s: str, max_len: int = 60) -> str:
    """Limpia string para filename."""
    if not s:
        return ""
    s = INVALID_FS_CHARS.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len]


def normalize_radicado(rad: str) -> str:
    """Normaliza YYYY-NNNNN."""
    m = re.match(r"(20\d{2})[-\s]?0*(\d+)", rad)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(5)}"
    return rad


def needs_rename(folder_name: str) -> bool:
    """¿Esta carpeta requiere atención?

    Dispara renombrado si:
    - Tiene marca [PENDIENTE...] o [REVISAR_ACCIONANTE].
    - Contiene control chars (\\n, \\r, \\t) — folder ensuciado por extracción.
    """
    if not folder_name:
        return False
    if "[PENDIENTE" in folder_name or "[REVISAR_ACCIONANTE]" in folder_name:
        return True
    if DIRTY_FS_CHARS.search(folder_name):
        return True
    return False


def build_target_name(case: Case) -> Optional[tuple[str, bool]]:
    """Calcula el nombre objetivo para la carpeta.

    Retorna (new_name, is_clean) o None si no se puede calcular.
    is_clean=True si tiene accionante real, False si va a [REVISAR_ACCIONANTE].
    """
    folder = case.folder_name or ""
    m = re.match(r"(20\d{2}[-\s]?\d+)", folder)
    if not m:
        return None

    rad = normalize_radicado(m.group(1).strip())
    accionante = clean_accionante(case.accionante or "")

    if accionante and is_likely_real_name(accionante):
        clean_acc = sanitize_for_fs(accionante)
        new_name = f"{rad} {clean_acc}"
        is_clean = True
    else:
        new_name = f"{rad} [REVISAR_ACCIONANTE]"
        is_clean = False

    new_name = INVALID_FS_CHARS.sub("", new_name).strip()[:100]
    return (new_name, is_clean)


def rename_folder_if_needed(db: Session, case: Case, base_dir: Optional[Path] = None) -> dict:
    """Renombra la carpeta del caso si tiene marca [PENDIENTE/REVISAR].

    Idempotente. Si folder_name ya está limpio, no hace nada.

    Returns:
        dict con resultado: {action: "renamed"|"skipped"|"error",
                             old_name, new_name, reason}
    """
    folder_name = case.folder_name or ""

    if not needs_rename(folder_name):
        return {"action": "skipped", "reason": "folder ya limpio",
                "old_name": folder_name, "new_name": folder_name}

    target = build_target_name(case)
    if not target:
        return {"action": "skipped", "reason": "no se pudo calcular nombre objetivo",
                "old_name": folder_name, "new_name": folder_name}

    new_name, is_clean = target

    # Si el nuevo nombre es igual al actual (ej. ya es [REVISAR_ACCIONANTE] y no hay nuevo accionante)
    if new_name == folder_name:
        return {"action": "skipped", "reason": "nombre idéntico al actual",
                "old_name": folder_name, "new_name": folder_name}

    # Resolver paths
    old_path = Path(case.folder_path) if case.folder_path else None
    if base_dir is None:
        if old_path:
            base_dir = old_path.parent
        else:
            try:
                from backend.core.settings import settings
                base_dir = Path(settings.BASE_DIR)
            except Exception:
                return {"action": "error", "reason": "no se pudo determinar BASE_DIR",
                        "old_name": folder_name, "new_name": new_name}

    new_path = base_dir / new_name

    # Resolver colisión
    if new_path.exists() and old_path != new_path:
        new_name = f"{new_name} (id{case.id})"[:100]
        new_path = base_dir / new_name

    # Rename físico (si la carpeta existe)
    fs_renamed = False
    try:
        if old_path and old_path.exists() and not new_path.exists():
            old_path.rename(new_path)
            fs_renamed = True
    except Exception as e:
        logger.warning("V6 rename_folder case=%d falló rename fs: %s", case.id, e)
        # Continuamos: aunque falle el rename físico, actualizamos DB para coherencia

    # Update DB
    old_path_str = str(old_path) if old_path else ""
    new_path_str = str(new_path)
    case.folder_name = new_name
    case.folder_path = new_path_str

    # Update file_path de cada documento
    if old_path_str:
        from backend.database.models import Document
        docs_updated = db.query(Document).filter(
            Document.case_id == case.id,
            Document.file_path.like(f"{old_path_str}%"),
        ).update(
            {Document.file_path:
                # SQLAlchemy func.replace
                __import__("sqlalchemy").func.replace(
                    Document.file_path, old_path_str, new_path_str)},
            synchronize_session=False,
        )
    else:
        docs_updated = 0

    db.commit()

    logger.info("V6 rename_folder case=%d %s → %s (clean=%s, fs_renamed=%s, docs=%d)",
                case.id, folder_name[:40], new_name[:40], is_clean, fs_renamed, docs_updated)

    return {
        "action": "renamed",
        "old_name": folder_name,
        "new_name": new_name,
        "is_clean": is_clean,
        "fs_renamed": fs_renamed,
        "docs_updated": docs_updated,
    }
