"""Detección de similitud y comparación entre cases.

Pensado para el flujo de "reconciliación tras traslado": cuando el usuario mueve
los documentos de un case a otro y el origen queda vacío, la UI ofrece migrar
los campos exclusivos antes de eliminar el origen.

La similitud NO se usa para fusionar automáticamente — sólo para decidir si la
UI debe sugerir la reconciliación. La decisión final (qué campos migrar,
eliminar o no) la toma el usuario.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case, Email
from backend.v9.regex_pass import _rad_corto_from_23, _rad_corto_from_folder


# Campos del Case que comparamos (subset del CSV_FIELD_MAP — solo los del cuadro).
# field_name → label legible para la UI.
_COMPARED_FIELDS: tuple[tuple[str, str], ...] = (
    ("radicado_23_digitos",        "Radicado 23 dígitos"),
    ("radicado_forest",            "Radicado FOREST"),
    ("accionante",                 "Accionante"),
    ("accionados",                 "Accionados"),
    ("vinculados",                 "Vinculados"),
    ("juzgado",                    "Juzgado 1ra"),
    ("juzgado_2nd",                "Juzgado 2da"),
    ("ciudad",                     "Ciudad"),
    ("fecha_ingreso",              "Fecha ingreso"),
    ("asunto",                     "Asunto"),
    ("pretensiones",               "Pretensiones"),
    ("derecho_vulnerado",          "Derecho vulnerado"),
    ("categoria_tematica",         "Categoría temática"),
    ("oficina_responsable",        "Oficina responsable"),
    ("dependencia_canonical",      "Dependencia canónica"),
    ("direccion",                  "Dirección SED"),
    ("grupo",                      "Grupo SED"),
    ("equipo",                     "Equipo SED"),
    ("abogado_responsable",        "Abogado responsable"),
    ("abogado_canonical",          "Abogado canónico"),
    ("estado",                     "Estado"),
    ("fecha_respuesta",            "Fecha respuesta"),
    ("impugnacion",                "Impugnación"),
    ("quien_impugno",              "Quién impugnó"),
    ("forest_impugnacion",         "FOREST impugnación"),
    ("sentido_fallo_1st",          "Sentido fallo 1ra"),
    ("fecha_fallo_1st",            "Fecha fallo 1ra"),
    ("sentido_fallo_2nd",          "Sentido fallo 2da"),
    ("fecha_fallo_2nd",            "Fecha fallo 2da"),
    ("incidente",                  "Incidente"),
    ("fecha_apertura_incidente",   "Fecha apertura incidente"),
    ("responsable_desacato",       "Responsable desacato"),
    ("abogado_incidente",          "Abogado incidente"),
    ("decision_incidente",         "Decisión incidente"),
    ("observaciones",              "Observaciones"),
)

# Estos campos siempre se sugieren para fusionar (concatenar), no para reemplazar.
_MERGE_AS_TEXT: frozenset[str] = frozenset({"observaciones"})


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm_name(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", _strip_accents(s).upper()).strip()


def _rad23_root(rad23: Optional[str]) -> Optional[str]:
    """Últimos 12 dígitos del rad23 — identifican el proceso aunque varíe el juzgado."""
    if not rad23:
        return None
    digits = re.sub(r"\D", "", rad23)
    return digits[-12:] if len(digits) >= 12 else None


def detect_similarity(source: Case, target: Case) -> list[dict]:
    """Devuelve una lista de señales que indican que dos cases son el mismo proceso.

    Cada señal: {"kind": "rad_corto"|"accionante"|"rad23_root", "value": "...", "label": "..."}
    Lista vacía si los cases son procesalmente distintos.
    """
    signals: list[dict] = []

    # 1. Mismo rad_corto (derivado de rad23 o folder_name)
    src_rad = _rad_corto_from_23(source.radicado_23_digitos) or _rad_corto_from_folder(source.folder_name)
    tgt_rad = _rad_corto_from_23(target.radicado_23_digitos) or _rad_corto_from_folder(target.folder_name)
    if src_rad and tgt_rad and src_rad == tgt_rad:
        signals.append({"kind": "rad_corto", "value": src_rad, "label": f"Mismo radicado corto {src_rad}"})

    # 2. Mismo rad23_root (últimos 12 dígitos)
    src_root = _rad23_root(source.radicado_23_digitos)
    tgt_root = _rad23_root(target.radicado_23_digitos)
    if src_root and tgt_root and src_root == tgt_root:
        signals.append({"kind": "rad23_root", "value": src_root,
                        "label": f"Mismo proceso (últimos 12 dígitos del rad23 coinciden)"})

    # 3. Mismo accionante normalizado
    src_acc = _norm_name(source.accionante)
    tgt_acc = _norm_name(target.accionante)
    if src_acc and tgt_acc and src_acc == tgt_acc and len(src_acc) >= 6:
        signals.append({"kind": "accionante", "value": source.accionante or target.accionante,
                        "label": f"Mismo accionante: {source.accionante or target.accionante}"})

    # 4. Mismo FOREST
    if source.radicado_forest and target.radicado_forest and source.radicado_forest == target.radicado_forest:
        signals.append({"kind": "forest", "value": source.radicado_forest,
                        "label": f"Mismo radicado FOREST {source.radicado_forest}"})

    return signals


def compare_cases(db: Session, source_id: int, target_id: int) -> dict:
    """Comparador campo-a-campo. Devuelve estructura lista para consumir por la UI.

    Estructura:
      {
        "source": {"id", "folder_name", "n_docs"},
        "target": {"id", "folder_name", "n_docs"},
        "similarity_signals": [...],          # señales de "mismo proceso"
        "exclusive_in_source": [              # campos donde source tiene valor y target no
          {"field", "label", "value", "suggested_action": "copy"|"merge_text"}
        ],
        "differs": [                          # ambos tienen valor distinto
          {"field", "label", "source_value", "target_value"}
        ],
        "identical": [                        # ambos tienen el mismo valor
          {"field", "label", "value"}
        ],
        "both_empty_count": int,
        "source_can_be_deleted": bool,        # source quedó con 0 docs/emails
      }
    """
    source = db.query(Case).filter(Case.id == source_id).first()
    target = db.query(Case).filter(Case.id == target_id).first()
    if not source or not target:
        return {"error": f"case {source_id if not source else target_id} no existe"}

    signals = detect_similarity(source, target)

    exclusive_in_source: list[dict] = []
    differs: list[dict] = []
    identical: list[dict] = []
    both_empty = 0
    for field, label in _COMPARED_FIELDS:
        s_val = (getattr(source, field, "") or "").strip() if isinstance(getattr(source, field, ""), str) else getattr(source, field, "")
        t_val = (getattr(target, field, "") or "").strip() if isinstance(getattr(target, field, ""), str) else getattr(target, field, "")
        if not s_val and not t_val:
            both_empty += 1
            continue
        if s_val == t_val:
            identical.append({"field": field, "label": label, "value": s_val})
            continue
        if s_val and not t_val:
            exclusive_in_source.append({
                "field": field, "label": label, "value": s_val,
                "suggested_action": "merge_text" if field in _MERGE_AS_TEXT else "copy",
            })
        elif t_val and not s_val:
            # Solo en target — no necesita acción
            continue
        else:
            differs.append({
                "field": field, "label": label,
                "source_value": s_val, "target_value": t_val,
            })

    # Para observaciones: si target ya tiene valor pero distinto al de source,
    # ofrecer "merge_text" también (fusionar ambos textos en lugar de reemplazar).
    if source.observaciones and target.observaciones and source.observaciones.strip() != target.observaciones.strip():
        # Quitar del bloque "differs" y agregar como sugerencia de merge
        differs = [d for d in differs if d["field"] != "observaciones"]
        exclusive_in_source.append({
            "field": "observaciones", "label": "Observaciones",
            "value": source.observaciones,
            "suggested_action": "merge_text",
            "target_existing": target.observaciones,
        })

    n_docs_source = len(source.documents)
    n_emails_source = db.query(Email).filter(Email.case_id == source_id).count()
    can_delete = (n_docs_source == 0 and n_emails_source == 0)

    return {
        "source": {"id": source.id, "folder_name": source.folder_name, "n_docs": n_docs_source, "n_emails": n_emails_source},
        "target": {"id": target.id, "folder_name": target.folder_name, "n_docs": len(target.documents)},
        "similarity_signals": signals,
        "exclusive_in_source": exclusive_in_source,
        "differs": differs,
        "identical": identical,
        "both_empty_count": both_empty,
        "source_can_be_deleted": can_delete,
    }
