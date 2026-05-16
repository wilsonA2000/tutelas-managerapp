#!/usr/bin/env python3
"""Triaje de la bandeja `__SIN_RADICADO__`.

La ingesta de Gmail deposita en este caso-shell los correos que no pudo cruzar con
ningún expediente. Muchos SÍ traen el radicado de la tutela en el ASUNTO (la cascada
no lo capturó porque venía solo ahí). Este script:
  1. parsea el asunto + el cuerpo (.md) de cada correo de la bandeja,
  2. extrae el radicado de tutela (23 dígitos o corto "AAAA-NNNNN"),
  3. busca el expediente por radicado,
  4. mueve el correo + sus adjuntos al expediente correcto (sibling_mover, regla
     "hermanos viajan juntos").
Los correos sin radicado de tutela (correspondencia interna, procesos no-SED, spam)
quedan en la bandeja para revisión manual.

Uso:
    ./venv/bin/python3 scripts/triage_sin_radicado.py            # dry-run (solo reporta)
    ./venv/bin/python3 scripts/triage_sin_radicado.py --apply    # mueve de verdad
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, Document, Email  # noqa: E402
from backend.email.rad_utils import normalize_rad23, derive_rad_corto_from_rad23  # noqa: E402
from backend.services.sibling_mover import move_document_or_package  # noqa: E402

SHELL_FOLDER = "__SIN_RADICADO__"

# bloque de dígitos/guiones largo (radicado de 21-23 dígitos, con o sin separadores)
_RE_RAD_LONG = re.compile(r"(?<![\d-])(\d{2}[\d.\- ]{16,30}\d)(?![\d-])")
# radicado corto "AAAA-NNNNN" anclado a una palabra de tutela (para no agarrar fechas)
_RE_RAD_CORTO = re.compile(
    r"(?i)(?:tutela|incidente|desacato|rad(?:icad[oa])?\.?|acci[oó]n\s+de\s+tutela|fallo)\s*"
    r"(?:n[o°.º]*)?\s*[:#\-–]?\s*(20\d{2})\s*[-\s]?\s*0*(\d{1,5})\b"
)
_EMAIL_DOCTYPES = ("EMAIL_JUDICIAL", "EMAIL_INTERNO")


def _short_from_long(digits: str) -> str | None:
    """De un bloque de ≥21 dígitos saca el radicado corto 'AAAA-NNNNN' (año chars 12-15,
    consecutivo chars 16-20). NO se usa el truncado a 20 dígitos: conflataría consecutivos
    contiguos (p.ej. 2026-00011 vs 2026-00012 comparten los primeros 20)."""
    if len(digits) < 21:
        return None
    rc = derive_rad_corto_from_rad23(digits[:23] if len(digits) >= 23 else digits + "00")
    return rc or None


def _build_lookup(db) -> dict:
    """by_corto['AAAA-NNNNN'] → case_id  (del radicado_23_digitos y del folder_name)."""
    by_corto: dict[str, int] = {}
    for c in db.query(Case).filter(Case.processing_status != "DUPLICATE_MERGED").all():
        r23 = normalize_rad23(c.radicado_23_digitos)
        if len(r23) >= 21:
            rc = derive_rad_corto_from_rad23(c.radicado_23_digitos)
            if rc:
                by_corto.setdefault(rc, c.id)
        m = re.match(r"(20\d{2})[-\s]?0*(\d{1,6})", (c.folder_name or "").strip())
        if m:
            by_corto.setdefault(f"{m.group(1)}-{int(m.group(2)):05d}", c.id)
    return by_corto


def _find_target(subject: str, body: str, by_corto: dict, exclude_id: int):
    """Devuelve (case_id, motivo) o (None, None)."""
    txt = f"{subject or ''}\n{(body or '')[:1500]}"
    # 1) radicado largo (≥21 dígitos) → derivar el corto (sin truncar a 20)
    for m in _RE_RAD_LONG.finditer(txt):
        digits = re.sub(r"\D", "", m.group(1))
        if 21 <= len(digits) <= 24:
            rc = _short_from_long(digits)
            if rc and (cid := by_corto.get(rc)) and cid != exclude_id:
                return cid, f"radicado {m.group(1).strip()} → {rc}"
    # 2) radicado corto anclado a "tutela/rad/acción de tutela"
    for m in _RE_RAD_CORTO.finditer(txt):
        rc = f"{m.group(1)}-{int(m.group(2)):05d}"
        cid = by_corto.get(rc)
        if cid and cid != exclude_id:
            return cid, f"radicado corto {rc}"
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Triaje de la bandeja __SIN_RADICADO__.")
    ap.add_argument("--apply", action="store_true", help="mueve los correos de verdad (sin esto: dry-run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        shell = db.query(Case).filter(Case.folder_name == SHELL_FOLDER).first()
        if not shell:
            print(f"No existe el caso shell {SHELL_FOLDER!r}.", file=sys.stderr)
            return 1
        by_corto = _build_lookup(db)
        emails = db.query(Email).filter(Email.case_id == shell.id).order_by(Email.id).all()
        print(f"Bandeja {SHELL_FOLDER} (case#{shell.id}): {len(emails)} correos vinculados.")
        print(f"Modo: {'APPLY' if args.apply else 'DRY-RUN'}\n")

        moved_emails = moved_docs = skipped = errs = 0
        for e in emails:
            pkg = db.query(Document).filter(Document.case_id == shell.id, Document.email_id == e.id).all()
            md = next((d for d in pkg if d.doc_type in _EMAIL_DOCTYPES), None)
            body = (md.extracted_text if md and md.extracted_text else "") or (e.body_preview or "")
            tid, why = _find_target(e.subject, body, by_corto, shell.id)
            subj = (e.subject or "(sin asunto)").strip()
            if tid:
                target = db.query(Case).filter(Case.id == tid).first()
                print(f"  ✓ correo#{e.id}  «{subj[:58]}»  →  case#{tid} '{(target.folder_name or '')[:36]}'  ({why}; {len(pkg)} doc(s))")
                if args.apply:
                    anchor = md or (pkg[0] if pkg else None)
                    if anchor is None:
                        # correo sin documentos asociados: solo re-vincular el correo
                        e.case_id = tid
                        e.status = "ASIGNADO"
                        db.commit()
                        moved_emails += 1
                        continue
                    r = move_document_or_package(db, anchor.id, tid, reason="triage_sin_radicado")
                    if r.get("errors"):
                        print(f"      ⚠ error moviendo: {r['errors']}")
                        db.rollback()
                        errs += 1
                        continue
                    e.case_id = tid
                    e.status = "ASIGNADO"
                    db.commit()
                    moved_emails += 1
                    moved_docs += len(r["moved_ids"])
            else:
                skipped += 1

        print(f"\n{'─' * 64}")
        print(f"{moved_emails} correos + {moved_docs} documentos {'movidos' if args.apply else 'a mover (dry-run)'}; "
              f"{skipped} sin radicado de tutela en el asunto (quedan en la bandeja); {errs} errores.")
        rem_e = db.query(Email).filter(Email.case_id == shell.id).count()
        rem_d = db.query(Document).filter(Document.case_id == shell.id).count()
        print(f"En {SHELL_FOLDER} {'quedan' if args.apply else 'hay'}: {rem_e} correos, {rem_d} documentos.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
