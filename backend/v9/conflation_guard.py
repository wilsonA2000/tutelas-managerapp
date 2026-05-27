"""Guard anti-conflación de DEMANDAS.

Detecta documentos `DEMANDA_TUTELA` cuyo accionante es AJENO al del caso (una
demanda de OTRA tutela misfileada en esta carpeta — conflación por rad corto
compartido entre juzgados) y la rutea a su caso correcto cuando hay un match
INEQUÍVOCO. Si no hay match único, solo flaggea (no mueve).

Por qué existe: el rad corto (p.ej. 2026-00015) lo reusan varios juzgados, así
que una carpeta puede terminar con demandas de personas distintas. Eso envenena
la extracción de derecho/asunto/accionante. El sistema debe auto-curar antes de
extraer, sin intervención manual. Caso testigo: c489 (CLAUDIA) tenía la demanda
de LUZ WENDY DOMICO (c490).

Detección robusta a OCR: NO extrae el nombre del doc (frágil — el OCR pega las
palabras: "ACCIONANTELUZWENDYDOMICO..."). En su lugar compara PRESENCIA del nombre
"despaciado" (sin espacios/acentos, mayúsculas) — el nombre del accionante de cada
caso, colapsado, como subcadena del texto del doc colapsado.

Seguridad (para NO esparcir docs):
  - Solo si el caso tiene >=2 DEMANDA_TUTELA.
  - Solo si el accionante DEL CASO aparece en alguna de sus demandas (confirma que
    la identidad del caso es real antes de mover algo).
  - Una demanda es ajena si NO contiene al accionante del caso.
  - Solo mueve si EXACTAMENTE 1 otro caso tiene su accionante (>=12 chars) presente
    en esa demanda. Si 0 ó >1 → flag, no mueve.
"""
from __future__ import annotations

import logging
import re
import unicodedata

from sqlalchemy.orm import Session

logger = logging.getLogger("tutelas.v9.conflation_guard")


def _despace(s: str | None) -> str:
    """Colapsa a solo-alfanumérico mayúsculas sin acentos: 'Peña Oviedo' → 'PENAOVIEDO'.
    Robusto al OCR que pega palabras."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


def _is_placeholder(acc: str | None) -> bool:
    if not acc:
        return True
    up = acc.upper()
    return any(p in up for p in (
        "SIN_ACCIONANTE", "SIN ACCIONANTE", "REVISAR_ACCIONANTE", "PENDIENTE",
    ))


# Nombre mínimo (despaciado) para considerarlo señal fuerte de identidad. Evita
# falsos positivos por nombres cortos/comunes que aparezcan de casualidad.
_MIN_NAME = 12


def route_foreign_demandas(db: Session, case, *, apply: bool = False) -> dict:
    """Detecta y (si apply) rutea demandas ajenas. Idempotente. No rompe la
    extracción (el caller la envuelve en try/except)."""
    from backend.database.models import Case, Document, AuditLog
    from backend.v9.field_extractor import _read_doc_text
    from backend.email.acumulacion_resolver import _move_doc_file

    summary = {"foreign": [], "moved": [], "flagged": []}
    case_acc = getattr(case, "accionante", None)
    if _is_placeholder(case_acc):
        return summary
    case_ds = _despace(case_acc)
    if len(case_ds) < _MIN_NAME:
        return summary  # accionante del caso muy corto → señal débil, no arriesgar

    demandas = db.query(Document).filter(
        Document.case_id == case.id, Document.doc_type == "DEMANDA_TUTELA"
    ).all()
    if len(demandas) < 2:
        return summary

    raw_text = {d.id: _read_doc_text(d) for d in demandas}
    doc_text_ds = {did: _despace(t) for did, t in raw_text.items()}

    # Rads del caso (solo dígitos, >=7) — si un doc cita el rad del PROPIO caso, es suyo
    # aunque mencione otro nombre (ej. un incidente nombra a la Secretaria accionada).
    from backend.v9.regex_pass import _rad_corto_from_folder
    _digits = lambda s: re.sub(r"\D", "", s or "")
    case_rads = {r for r in (
        _digits(getattr(case, "radicado_23_digitos", None)),
        _digits(_rad_corto_from_folder(getattr(case, "folder_name", None))),
    ) if r and len(r) >= 7}

    def _has_case_rad(raw: str) -> bool:
        d = _digits(raw)
        return any(r in d for r in case_rads)

    # Confirmar identidad del caso: su accionante debe aparecer en alguna demanda.
    if not any(case_ds in t for t in doc_text_ds.values()):
        return summary  # no se confirma la identidad del caso → no mover nada

    # Mapa de accionantes de OTROS casos (despaciados, >=MIN) → caso.
    others = {}
    for c in db.query(Case).filter(Case.id != case.id, Case.accionante.isnot(None)).all():
        ds = _despace(c.accionante)
        if len(ds) >= _MIN_NAME:
            others.setdefault(ds, []).append(c)

    for d in demandas:
        t = doc_text_ds[d.id]
        if case_ds in t:
            continue  # contiene al accionante del caso → es propia
        if _has_case_rad(raw_text[d.id]):
            continue  # cita el rad del PROPIO caso → es suya (aunque nombre otro accionante)
        # AJENA: ¿qué accionante de otro caso aparece en este doc?
        hits = {ds: cs for ds, cs in others.items() if ds in t}
        target_ids = {c.id for cs in hits.values() for c in cs}
        summary["foreign"].append({"doc_id": d.id, "filename": d.filename,
                                    "matches": sorted(target_ids)})
        if len(target_ids) == 1:
            tgt = next(iter(hits.values()))[0]
            if apply:
                old = d.case_id
                d.case_id = tgt.id
                try:
                    _move_doc_file(db, d, tgt.id)
                except Exception as e:  # noqa: BLE001
                    logger.warning("conflation_guard: mover archivo doc#%s falló: %s", d.id, e)
                db.add(AuditLog(
                    case_id=tgt.id, action="REASIGNAR_DOC", source="conflation_guard",
                    old_value=f"case {old}",
                    new_value=f"demanda ajena doc {d.id} '{d.filename}' → case {tgt.id}",
                ))
            summary["moved"].append({"doc_id": d.id, "filename": d.filename, "to_case": tgt.id})
        else:
            logger.info("conflation_guard: demanda ajena doc#%s sin destino único (%d) — flag",
                        d.id, len(target_ids))
            summary["flagged"].append({"doc_id": d.id, "filename": d.filename,
                                       "n_targets": len(target_ids)})
    return summary
