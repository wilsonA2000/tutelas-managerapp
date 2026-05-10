"""Carga el cuadro ground truth (producido por Claude) a la DB de la plataforma.

Lee /home/wilsonarguello/iuris-data/_ground_truth/<radicado>/_extraction.json
y puebla las tablas Case, Document, Email.

Idempotente: usa folder_name UNIQUE + Email.message_id UNIQUE para no duplicar.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal, init_db  # noqa: E402
from backend.database.models import Case, Document, Email  # noqa: E402

GROUND_TRUTH_ROOT = Path("/home/wilsonarguello/iuris-data/_ground_truth")
RAW_EMAILS_ROOT = Path("/home/wilsonarguello/iuris-data/_raw_emails")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("load-gt")


# Mapping CSV_FIELD_MAP key -> Case attribute (mismo que models.py)
CSV_TO_ATTR = {
    "RADICADO_23_DIGITOS": "radicado_23_digitos",
    "RADICADO_FOREST": "radicado_forest",
    "ABOGADO_RESPONSABLE": "abogado_responsable",
    "ACCIONANTE": "accionante",
    "ACCIONADOS": "accionados",
    "VINCULADOS": "vinculados",
    "DERECHO_VULNERADO": "derecho_vulnerado",
    "JUZGADO": "juzgado",
    "CIUDAD": "ciudad",
    "FECHA_INGRESO": "fecha_ingreso",
    "ASUNTO": "asunto",
    "PRETENSIONES": "pretensiones",
    "OFICINA_RESPONSABLE": "oficina_responsable",
    "ESTADO": "estado",
    "FECHA_RESPUESTA": "fecha_respuesta",
    "SENTIDO_FALLO_1ST": "sentido_fallo_1st",
    "FECHA_FALLO_1ST": "fecha_fallo_1st",
    "IMPUGNACION": "impugnacion",
    "QUIEN_IMPUGNO": "quien_impugno",
    "FOREST_IMPUGNACION": "forest_impugnacion",
    "JUZGADO_2ND": "juzgado_2nd",
    "SENTIDO_FALLO_2ND": "sentido_fallo_2nd",
    "FECHA_FALLO_2ND": "fecha_fallo_2nd",
    "INCIDENTE": "incidente",
    "FECHA_APERTURA_INCIDENTE": "fecha_apertura_incidente",
    "RESPONSABLE_DESACATO": "responsable_desacato",
    "DECISION_INCIDENTE": "decision_incidente",
    "INCIDENTE_2": "incidente_2",
    "FECHA_APERTURA_INCIDENTE_2": "fecha_apertura_incidente_2",
    "RESPONSABLE_DESACATO_2": "responsable_desacato_2",
    "DECISION_INCIDENTE_2": "decision_incidente_2",
    "INCIDENTE_3": "incidente_3",
    "FECHA_APERTURA_INCIDENTE_3": "fecha_apertura_incidente_3",
    "RESPONSABLE_DESACATO_3": "responsable_desacato_3",
    "DECISION_INCIDENTE_3": "decision_incidente_3",
    "OBSERVACIONES": "observaciones",
    "CATEGORIA_TEMATICA": "categoria_tematica",
    "DIRECCION": "direccion",
    "GRUPO": "grupo",
    "EQUIPO": "equipo",
    "ABOGADO_CANONICAL": "abogado_canonical",
    "DEPENDENCIA_CANONICAL": "dependencia_canonical",
}


def normalize_accionante(name: str) -> str:
    """Para folder_name: limpiar y truncar."""
    if not name:
        return "SIN_ACCIONANTE"
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    return s.strip()[:60].upper()


def parse_email_md(md_path: Path) -> dict:
    """Parsea email.md (header bullet list + body) — devuelve dict con keys."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    headers = {}
    for line in text.split("\n"):
        m = re.match(r"-\s+\*\*([^*]+)\*\*:\s*(.*)", line)
        if m:
            headers[m.group(1).strip().lower()] = m.group(2).strip()
        if line.startswith("---"):
            break
    body_idx = text.find("---\n")
    body = text[body_idx + 4 :].strip() if body_idx > 0 else ""
    return {
        "message_id": headers.get("message-id", md_path.parent.name),
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "date": headers.get("date", ""),
        "body_preview": body[:1000],
    }


def parse_date(s: str) -> datetime | None:
    """Parsea Date header de Gmail. Devuelve datetime o None."""
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(s)
        return d.replace(tzinfo=None) if d else None
    except Exception:
        return None


def load_case_from_extraction(extraction: dict, case_dir: Path, db):
    """Crea/actualiza Case + Documents + Emails desde extraction.json."""
    fields = extraction.get("fields", {})
    rad23 = (
        (fields.get("RADICADO_23_DIGITOS", {}) or {}).get("value")
        or extraction.get("radicado_23_digitos")
        or extraction.get("radicado_23")
    )
    if not rad23:
        # fallback final: derivar del nombre de la carpeta (formato "RAD23 - ACCIONANTE")
        first = case_dir.name.split(" - ", 1)[0].strip()
        if re.fullmatch(r"\d{5}-\d{2}-\d{2}-\d{3}-\d{4}-\d{5}-\d{2}", first):
            rad23 = first
    if not rad23:
        log.warning(f"Skipping {case_dir.name}: no radicado_23")
        return None

    accionante = (fields.get("ACCIONANTE", {}) or {}).get("value") or ""
    if not accionante:
        # Fallback: leer del _classification.json
        cls_path = case_dir / "_classification.json"
        if cls_path.exists():
            try:
                cls = json.loads(cls_path.read_text(encoding="utf-8"))
                accionante = cls.get("accionante") or ""
            except Exception:
                pass
    if not accionante:
        # Fallback final: derivar del nombre de la carpeta
        parts = case_dir.name.split(" - ", 1)
        if len(parts) == 2:
            accionante = parts[1]
    rad_corto = ""
    if rad23:
        digits = re.sub(r"\D", "", rad23)
        if len(digits) >= 11:
            rad_corto = f"{digits[-11:-7]}-{digits[-7:-2]}"

    folder_name = f"{rad_corto} {normalize_accionante(accionante)}".strip()

    # Lookup por radicado_23 + folder_name
    case = db.query(Case).filter(Case.radicado_23_digitos == rad23).first()
    if case is None:
        case = Case(
            radicado_23_digitos=rad23,
            folder_name=folder_name,
            folder_path=str(case_dir.resolve()),
            processing_status="COMPLETO",
            tipo_actuacion="TUTELA",
        )
        db.add(case)
    else:
        # Refrescar folder_name y path al valor correcto (idempotencia)
        case.folder_name = folder_name
        case.folder_path = str(case_dir.resolve())
        case.processing_status = "COMPLETO"

    # Set 42 fields
    for csv_key, attr in CSV_TO_ATTR.items():
        val = (fields.get(csv_key, {}) or {}).get("value")
        if val is not None and val != "":
            setattr(case, attr, val)
    # Asegurar accionante (puede venir del fallback)
    if accionante and not case.accionante:
        case.accionante = accionante

    # field_confidences_json
    confidences = {}
    for csv_key, payload in fields.items():
        if isinstance(payload, dict) and "confidence" in payload:
            band_map = {"alta": "OK", "media": "REVISAR", "baja": "BAJO"}
            confidences[csv_key] = {
                "score": {"alta": 0.9, "media": 0.6, "baja": 0.3}.get(payload.get("confidence", "").lower(), 0.5),
                "band": band_map.get(payload.get("confidence", "").lower(), "REVISAR"),
                "evidence": {"source_doc": payload.get("source_doc", "")},
            }
    if confidences:
        case.field_confidences_json = json.dumps(confidences, ensure_ascii=False)

    db.flush()  # to get case.id

    # Emails (un email.md por cada subdirectorio raw_emails referenciado, o el email.md en la carpeta)
    for em_md in case_dir.glob("*.email.md"):
        em = parse_email_md(em_md)
        existing = db.query(Email).filter(Email.message_id == em["message_id"]).first()
        if existing:
            existing.case_id = case.id
            existing.status = "ASIGNADO"
            continue
        db.add(Email(
            message_id=em["message_id"],
            subject=em["subject"],
            sender=em["from"],
            date_received=parse_date(em["date"]),
            body_preview=em["body_preview"],
            case_id=case.id,
            attachments=[],
            status="ASIGNADO",
        ))

    # Documents (todos los archivos no-.json no-.md en la carpeta del caso)
    doc_types_map = {d["filename"]: d.get("doc_type", "OTRO") for d in extraction.get("documents", [])}
    for fpath in case_dir.iterdir():
        if not fpath.is_file():
            continue
        if fpath.suffix.lower() in {".json", ".md"}:
            continue
        existing = db.query(Document).filter(
            Document.case_id == case.id,
            Document.filename == fpath.name,
        ).first()
        if existing:
            continue
        db.add(Document(
            case_id=case.id,
            filename=fpath.name,
            file_path=str(fpath.resolve()),
            doc_type=doc_types_map.get(fpath.name, "OTRO"),
            file_size=fpath.stat().st_size,
            extraction_date=datetime.utcnow(),
        ))

    return case


def load_special_bucket(bucket_dir: Path, status: str, db):
    """Carga emails de _NO_TUTELA o _SIN_RADICADO con status correspondiente (no crea Case)."""
    if not bucket_dir.exists():
        return 0
    count = 0
    candidates = list(bucket_dir.rglob("*.email.md")) + list(bucket_dir.rglob("email.md"))
    for em_md in candidates:
        em = parse_email_md(em_md)
        existing = db.query(Email).filter(Email.message_id == em["message_id"]).first()
        if existing:
            existing.status = status
            continue
        db.add(Email(
            message_id=em["message_id"],
            subject=em["subject"],
            sender=em["from"],
            date_received=parse_date(em["date"]),
            body_preview=em["body_preview"],
            attachments=[],
            status=status,
        ))
        count += 1
    return count


def main():
    init_db()
    db = SessionLocal()
    try:
        case_dirs = [
            d for d in GROUND_TRUTH_ROOT.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ]
        log.info(f"Found {len(case_dirs)} case directories")

        loaded = 0
        skipped = 0
        for case_dir in case_dirs:
            extraction_file = case_dir / "_extraction.json"
            if not extraction_file.exists():
                log.warning(f"No _extraction.json in {case_dir.name}, skipping")
                skipped += 1
                continue
            try:
                extraction = json.loads(extraction_file.read_text(encoding="utf-8"))
                if load_case_from_extraction(extraction, case_dir, db):
                    loaded += 1
                else:
                    skipped += 1
            except Exception as e:
                log.error(f"FAIL {case_dir.name}: {e}")
                skipped += 1
                db.rollback()

        # Special buckets
        no_tutela = load_special_bucket(GROUND_TRUTH_ROOT / "_NO_TUTELA", "IGNORADO", db)
        sin_rad = load_special_bucket(GROUND_TRUTH_ROOT / "_SIN_RADICADO", "AMBIGUO", db)

        db.commit()

        # Summary
        n_cases = db.query(Case).count()
        n_docs = db.query(Document).count()
        n_emails = db.query(Email).count()
        log.info(
            f"DONE loaded={loaded} skipped={skipped} "
            f"no_tutela_emails={no_tutela} sin_radicado_emails={sin_rad} | "
            f"DB now: cases={n_cases} documents={n_docs} emails={n_emails}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
