"""FIX 3 — Reextract focalizado del accionante con LLM Haiku para casos
[REVISAR_ACCIONANTE].

Estrategia:
- Carga texto extraído del doc principal (TUTELA / mayor prioridad / mayor texto).
- Prompt focalizado a Anthropic Haiku 4.5: "extrae SOLO el nombre del accionante".
- Valida la respuesta con `is_likely_real_name`.
- Update cases.accionante y dispara folder_renamer (no toda la extracción).
- Idempotente: si ya está limpio, skip.

Uso: python3 scripts/fix3_reextract_accionante.py [--dry-run] [--ids 14,20,...]
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document, AuditLog
from backend.cognition.folder_renamer import (
    clean_accionante,
    is_likely_real_name,
    needs_rename,
    rename_folder_if_needed,
)
from backend.extraction.ai_extractor import _call_anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("fix3")


DOC_PRIORITY = {
    "TUTELA_PRINCIPAL": 1,
    "PDF_TUTELA": 2,
    "AUTO_ADMISORIO": 3,
    "AUTO": 4,
    "DOCX_TUTELA": 5,
    "PDF_DEMANDA": 6,
}


PROMPT_SYSTEM = (
    "Eres un asistente especializado en extracción de datos de tutelas "
    "colombianas. Tu única tarea: identificar el nombre completo del "
    "ACCIONANTE (la persona o institución que interpone la tutela). "
    "Reglas estrictas:\n"
    "- Responde EXCLUSIVAMENTE el nombre, en mayúsculas, sin texto adicional.\n"
    "- Si es persona natural: nombre + apellidos completos.\n"
    "- Si es institución (Personería, Defensoría, etc.): el nombre oficial.\n"
    "- Si NO puedes identificar accionante con certeza, responde: DESCONOCIDO.\n"
    "- NUNCA inventes nombres ni copies fragmentos de texto descriptivo."
)


def candidate_texts(case: Case, db, limit: int = 4) -> list[tuple[str, str]]:
    """Devuelve hasta `limit` candidatos (texto, fuente) ordenados por prioridad."""
    docs = db.query(Document).filter(Document.case_id == case.id).all()
    if not docs:
        return []

    def score(d: Document) -> tuple[int, int]:
        prio = DOC_PRIORITY.get(d.doc_type or "", 99)
        size = len(d.extracted_text or "")
        return (prio, -size)

    docs_sorted = sorted(docs, key=score)
    out: list[tuple[str, str]] = []
    for d in docs_sorted:
        txt = (d.extracted_text or "").strip()
        if len(txt) >= 200:
            out.append((txt, f"{d.doc_type}/{d.filename}"))
        if len(out) >= limit:
            break
    if not out:
        for d in docs_sorted:
            txt = (d.extracted_text or "").strip()
            if txt:
                out.append((txt, f"{d.doc_type}/{d.filename}"))
                if len(out) >= limit:
                    break
    return out


def call_haiku(text: str, model: str = "claude-haiku-4-5-20251001") -> str:
    """Llama a Anthropic Haiku 4.5 con prompt focalizado. Devuelve respuesta cruda."""
    snippet = text[:8000]
    messages = [
        {"role": "system", "content": PROMPT_SYSTEM},
        {"role": "user", "content": f"Extrae el ACCIONANTE del siguiente texto:\n\n{snippet}"},
    ]
    raw, _, _ = _call_anthropic(messages, model, max_tokens=128)
    return (raw or "").strip()


def normalize_response(s: str) -> str:
    """Limpia la respuesta del LLM."""
    s = s.strip().strip('"').strip("'")
    s = re.sub(r"^(ACCIONANTE\s*:?\s*)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def llm_says_unknown(s: str) -> bool:
    """¿La respuesta indica que no pudo extraer? (sin importar si es la palabra
    sola o embebida en una explicación)."""
    if not s:
        return True
    return "DESCONOCIDO" in s.upper()


def is_too_verbose(s: str) -> bool:
    """Una respuesta con >12 palabras o frases típicas de explicación es ruido."""
    if not s:
        return False
    words = s.split()
    if len(words) > 12:
        return True
    # Frases típicas que delatan explicación, no nombre
    NOISE_PHRASES = ("EL TEXTO", "NO CONTIENE", "ES UNA RESOLUC", "ACTO ADMINIS",
                     "NO PUEDO", "NO HAY", "AUSENCIA DE", "EN ESTE CASO")
    upper = s.upper()
    return any(p in upper for p in NOISE_PHRASES)


def process_case(db, case: Case, dry_run: bool = False) -> dict:
    """Procesa un caso: extrae accionante, actualiza DB, renombra carpeta."""
    result = {
        "case_id": case.id,
        "folder_before": case.folder_name,
        "old_accionante": case.accionante,
        "new_accionante": None,
        "raw_llm": None,
        "rename": None,
        "status": "skipped",
    }

    candidates = candidate_texts(case, db)
    if not candidates:
        result["status"] = "no-text"
        return result

    candidate = None
    raw = None
    source_used = None
    attempts: list[dict] = []

    for text, source in candidates:
        try:
            raw = call_haiku(text)
        except Exception as e:
            attempts.append({"source": source, "error": str(e)[:100]})
            continue

        c = clean_accionante(normalize_response(raw))
        attempts.append({"source": source, "raw": raw, "candidate": c})

        if llm_says_unknown(raw) or is_too_verbose(c):
            continue
        if c and is_likely_real_name(c):
            candidate = c
            source_used = source
            break

    result["attempts"] = attempts
    result["raw_llm"] = raw
    result["new_accionante"] = candidate
    result["text_source"] = source_used

    if not candidate:
        result["status"] = "no-valid-name-found"
        return result

    if dry_run:
        result["status"] = "would-update"
        return result

    case.accionante = candidate
    db.add(AuditLog(
        case_id=case.id,
        action="V6_ACCIONANTE_LLM_PATCH",
        source=f"{result['old_accionante'][:80] if result['old_accionante'] else ''} → {candidate}",
    ))
    db.commit()

    if needs_rename(case.folder_name):
        rename_result = rename_folder_if_needed(db, case)
        result["rename"] = rename_result
        if rename_result.get("action") == "renamed":
            db.add(AuditLog(
                case_id=case.id,
                action="V6_FOLDER_RENAMED",
                source=f"{rename_result['old_name']} → {rename_result['new_name']} "
                       f"clean={rename_result.get('is_clean')} "
                       f"fs={rename_result.get('fs_renamed')} "
                       f"docs={rename_result.get('docs_updated')} "
                       f"src=fix3",
            ))
            db.commit()

    db.refresh(case)
    result["folder_after"] = case.folder_name
    result["status"] = "updated"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No persiste cambios")
    parser.add_argument("--ids", type=str, default="",
                        help="Lista de case_ids separados por coma. Si vacío, busca por marca.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.ids:
            ids = [int(x) for x in args.ids.split(",") if x.strip()]
            cases = db.query(Case).filter(Case.id.in_(ids)).all()
        else:
            cases = db.query(Case).filter(
                Case.folder_name.like("%[REVISAR_ACCIONANTE]%")
            ).order_by(Case.id).all()

        logger.info("Procesando %d casos (dry_run=%s)", len(cases), args.dry_run)
        results = []
        for c in cases:
            logger.info("---- case=%d folder=%s", c.id, c.folder_name[:50])
            r = process_case(db, c, dry_run=args.dry_run)
            results.append(r)
            logger.info("  status=%s new_accionante=%r", r["status"], r.get("new_accionante"))
            time.sleep(0.5)

        # Resumen
        print("\n=== RESUMEN ===")
        by_status = {}
        for r in results:
            by_status.setdefault(r["status"], []).append(r["case_id"])
        for st, ids in by_status.items():
            print(f"  {st}: {len(ids)} ({ids})")
        print()
        for r in results:
            line = (
                f"id={r['case_id']:<4} {r['status']:<22} "
                f"acc_new={r.get('new_accionante')!r:<60}"
            )
            if r.get("rename"):
                line += f" | rename={r['rename'].get('action')}"
            print(line)
    finally:
        db.close()


if __name__ == "__main__":
    main()
