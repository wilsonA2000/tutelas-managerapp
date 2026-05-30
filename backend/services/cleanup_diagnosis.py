"""Cleanup diagnosis v5.0: funciones puras read-only.

Agrupa TODO el desorden de disco + DB en un solo reporte JSON, usando la
regla de identidad (radicado_23d + accionante + tipo_representacion).

v5.0: detectores de fragmentos FOREST, radicados incompletos, propuesta
de limpieza de duplicados, candidatos de re-extracción.

NO toca nada. Solo lee y agrupa.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database.models import Case, Document, Email
from backend.services.provenance_service import count_linked_documents, count_orphan_documents

logger = logging.getLogger("tutelas.cleanup_diagnosis")


# ============================================================
# Identidad de caso (tupla inmutable)
# ============================================================

def normalize_accionante(name: str | None) -> str:
    """Normaliza nombre de accionante para comparacion: minusculas, sin espacios extra."""
    if not name:
        return ""
    s = name.upper().strip()
    # Quitar acentos basicos
    for a, b in [("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U"), ("Ñ", "N")]:
        s = s.replace(a, b)
    # Colapsar espacios
    s = " ".join(s.split())
    return s


def detect_tipo_representacion(folder_name: str, accionante: str) -> str:
    """Detecta tipo de representacion: DIRECTO / APODERADO / AGENTE_OFICIOSO / PERSONERO."""
    text = f"{folder_name or ''} {accionante or ''}".upper()
    if "AGENTE OFICIOSO" in text or "OFICIOSA" in text:
        return "AGENTE_OFICIOSO"
    if "APODERAD" in text or "EN REPRESENTACION" in text or "EN REPRESENTACIÓN" in text:
        return "APODERADO"
    if "PERSONERO" in text or "PERSONERIA" in text:
        return "PERSONERO"
    return "DIRECTO"


def extract_radicado_23d(case: Case) -> str | None:
    """Extrae radicado 23 digitos del caso (prioridad: DB > folder_name)."""
    if case.radicado_23_digitos:
        # Normalizar: solo digitos
        digits = re.sub(r"\D", "", case.radicado_23_digitos)
        if 17 <= len(digits) <= 25:
            return digits
    # Fallback: buscar en folder_name
    if case.folder_name:
        m = re.search(r"(\d{17,23})", re.sub(r"[\s\-\.]", "", case.folder_name))
        if m:
            return m.group(1)
    return None


def case_identity(case: Case) -> tuple[str | None, str, str]:
    """Tupla de identidad inmutable de un caso: (radicado_23d, accionante_norm, tipo_rep)."""
    return (
        extract_radicado_23d(case),
        normalize_accionante(case.accionante),
        detect_tipo_representacion(case.folder_name or "", case.accionante or ""),
    )


# ============================================================
# Detectores de problemas especificos
# ============================================================

# Palabras clave que indican que una carpeta es fragmento (no tutela real)
SUSPICIOUS_FOLDER_KEYWORDS = [
    "PENDIENTE REVISION", "PENDIENTE IDENTIFICACION", "PENDIENTE",
    "REFERENCIA", "CORREO", "CUAL CUMPLIMIENTO", "NUEVA NIEGA",
    "FRAGMENTO", "DONDE EXPONE", "EN EL MUNICIPIO", "NOTIFICACION OBEDECER",
]


def is_suspicious_folder_name(folder_name: str) -> tuple[bool, str]:
    """Detecta si un folder_name parece un fragmento mal parseado.

    Returns: (is_suspicious, reason)
    """
    if not folder_name:
        return True, "folder_name vacio"
    upper = folder_name.upper()
    for kw in SUSPICIOUS_FOLDER_KEYWORDS:
        if kw in upper:
            return True, f"contiene '{kw}'"
    if len(folder_name) > 120:
        return True, f"muy largo ({len(folder_name)} chars)"
    if not re.match(r"^\d{4}-\d{3,}", folder_name):
        return True, "no empieza con YYYY-NNNNN"
    return False, ""


def is_typo_folder(folder_name: str) -> tuple[bool, str]:
    """Detecta typos obvios en el prefijo del folder (ej: 20222-000137 vs 2022-000137)."""
    if not folder_name:
        return False, ""
    # Prefijo con 5 digitos en año (20222)
    if re.match(r"^20\d{3}-", folder_name):
        return True, "año con 5 digitos"
    return False, ""


# ============================================================
# v5.0: Detectores ampliados
# ============================================================

_RAD23_PATTERN = re.compile(r"(68\d{17,21})")
_FOREST_FOLDER_PATTERN = re.compile(r"^(\d{4})-(\d{4,})(?:\s|$)")


def _is_forest_folder(folder_name: str) -> bool:
    """Detecta si folder_name usa un número FOREST como identificador.

    Carpetas judiciales: 2026-00008 (secuencia corta, ≤3 dígitos sin ceros)
    Carpetas FOREST:     2026-62978 (número ≥10000, nunca empieza con 000)
    """
    if not folder_name:
        return False
    m = _FOREST_FOLDER_PATTERN.match(folder_name)
    if not m:
        return False
    num = int(m.group(2))
    # FOREST: números ≥10000 que no son secuencias judiciales (las judiciales son <1000 típicamente)
    # También detectar números de 5 dígitos que empiezan con 5 o 6 (FOREST del 2026)
    return num >= 10000


def detect_forest_fragments(db: Session) -> list[dict]:
    """Detecta casos cuyo folder_name usa número FOREST como identificador.

    Para cada fragmento, busca en el texto de sus documentos un radicado 23d
    que corresponda a otro caso existente (el caso padre).

    Returns:
        Lista de fragmentos con caso padre sugerido.
    """
    cases_all = db.query(Case).filter(
        (Case.processing_status != "DUPLICATE_MERGED") | (Case.processing_status.is_(None))
    ).all()

    # Índice de radicados 23d existentes → case_id
    rad23_index: dict[str, int] = {}
    case_map: dict[int, Case] = {}
    for c in cases_all:
        case_map[c.id] = c
        rad = extract_radicado_23d(c)
        if rad and len(rad) >= 18:
            rad23_index[rad] = c.id

    fragments = []
    for c in cases_all:
        if not _is_forest_folder(c.folder_name or ""):
            continue

        # Buscar radicado 23d en el texto de sus documentos
        docs = db.query(Document).filter(Document.case_id == c.id).all()
        found_rads: dict[str, int] = defaultdict(int)  # radicado → count de docs donde aparece

        for doc in docs:
            text = (doc.extracted_text or "")[:15000]
            if not text:
                continue
            matches = _RAD23_PATTERN.findall(text)
            seen_in_doc = set()
            for m in matches:
                digits = re.sub(r"\D", "", m)
                if len(digits) >= 18 and digits not in seen_in_doc:
                    seen_in_doc.add(digits)
                    found_rads[digits] += 1

        # Buscar un radicado que corresponda a otro caso
        best_match = None
        best_confidence = "BAJA"
        best_count = 0

        for rad, count in found_rads.items():
            # Buscar match en el índice con múltiples estrategias
            parent_id = None
            for existing_rad, cid in rad23_index.items():
                if cid == c.id:
                    continue
                # Estrategia 1: match exacto primeros 18 dígitos
                if rad[:18] == existing_rad[:18]:
                    parent_id = cid
                    break
                # Estrategia 2: mismo departamento + extraer número de caso
                # Formato judicial: ...2026-SSSSS-II (seq=5d, inst=2d)
                # Radicados truncados pueden tener <7 dígitos después del año
                if rad[:5] == existing_rad[:5]:
                    idx1 = rad.find("2026")
                    idx2 = existing_rad.find("2026")
                    if idx1 >= 0 and idx2 >= 0:
                        tail1 = rad[idx1 + 4:]
                        tail2 = existing_rad[idx2 + 4:]
                        # Extraer secuencia: si tiene 7+ dígitos → seq=primeros len-2, sino → todo
                        seq1 = int(tail1[:-2]) if len(tail1) >= 7 else int(tail1)
                        seq2 = int(tail2[:-2]) if len(tail2) >= 7 else int(tail2)
                        if seq1 == seq2 and seq1 > 0:
                            parent_id = cid
                            break

            if parent_id:
                # Acumular: si múltiples variantes de radicado apuntan al mismo padre, sumar
                if parent_id == best_match:
                    best_count += count
                elif count > best_count or not best_match:
                    best_match = parent_id
                    best_count = count
                best_confidence = "ALTA" if best_count >= 2 else "MEDIA"

        # También buscar por FOREST cruzado
        if not best_match and c.radicado_forest:
            for other in cases_all:
                if other.id == c.id:
                    continue
                if other.radicado_forest and other.radicado_forest == c.radicado_forest:
                    best_match = other.id
                    best_confidence = "ALTA"
                    break

        parent = case_map.get(best_match) if best_match else None
        fragments.append({
            "fragment_case_id": c.id,
            "fragment_folder": (c.folder_name or "")[:100],
            "doc_count": len(docs),
            "radicado_forest": c.radicado_forest or "",
            "detected_rad23_in_docs": list(found_rads.keys())[:3],
            "suggested_parent_case_id": best_match,
            "suggested_parent_folder": (parent.folder_name or "")[:100] if parent else None,
            "confidence": best_confidence if best_match else None,
        })

    return fragments


def detect_incomplete_radicados(db: Session) -> dict[str, Any]:
    """Detecta casos sin radicado_23_digitos o con formato incorrecto.

    Para los que no tienen, busca en extracted_text de sus documentos.

    Returns:
        dict con listas de casos sin radicado, con formato incorrecto, y sugerencias.
    """
    cases = db.query(Case).filter(
        (Case.processing_status != "DUPLICATE_MERGED") | (Case.processing_status.is_(None))
    ).all()

    missing = []       # Sin radicado
    malformed = []     # Con radicado pero formato incorrecto
    suggestions = []   # Sugerencias de radicado desde documentos

    for c in cases:
        rad = c.radicado_23_digitos
        digits = re.sub(r"\D", "", rad) if rad else ""

        if not rad or not digits:
            # Sin radicado — buscar en documentos
            entry = {
                "case_id": c.id,
                "folder_name": (c.folder_name or "")[:80],
                "current_rad23": None,
            }
            missing.append(entry)

            # Buscar sugerencia en docs
            docs = db.query(Document).filter(Document.case_id == c.id).all()
            rad_candidates: dict[str, int] = defaultdict(int)
            for doc in docs:
                text = (doc.extracted_text or "")[:15000]
                for m in _RAD23_PATTERN.findall(text):
                    d = re.sub(r"\D", "", m)
                    if 18 <= len(d) <= 25:
                        rad_candidates[d] += 1

            if rad_candidates:
                best_rad = max(rad_candidates, key=rad_candidates.get)
                best_count = rad_candidates[best_rad]
                suggestions.append({
                    "case_id": c.id,
                    "folder_name": (c.folder_name or "")[:80],
                    "suggested_rad23": best_rad,
                    "found_in_docs": best_count,
                    "confidence": "ALTA" if best_count >= 2 else "MEDIA",
                    "all_candidates": len(rad_candidates),
                })

        elif len(digits) < 18 or len(digits) > 25:
            # Formato incorrecto
            malformed.append({
                "case_id": c.id,
                "folder_name": (c.folder_name or "")[:80],
                "current_rad23": rad,
                "digit_count": len(digits),
            })

    return {
        "missing_count": len(missing),
        "malformed_count": len(malformed),
        "suggestions_count": len(suggestions),
        "missing": missing,
        "malformed": malformed,
        "suggestions": suggestions,
    }


def propose_duplicate_cleanup(db: Session) -> dict[str, Any]:
    """Propone limpieza de duplicados por hash MD5.

    Clasifica en:
    - intra_case: duplicados dentro del mismo caso (seguros de limpiar)
    - inter_case: duplicados entre casos diferentes (requiere revisión)

    Returns:
        dict con conteos, espacio estimado, y samples.
    """
    docs = db.query(Document).filter(
        Document.file_hash.isnot(None),
        Document.file_hash != "",
    ).all()

    hash_groups: dict[str, list[Document]] = defaultdict(list)
    for d in docs:
        hash_groups[d.file_hash].append(d)

    intra_groups = []
    inter_groups = []
    intra_removable = 0
    inter_reviewable = 0

    for h, group in hash_groups.items():
        if len(group) < 2:
            continue

        case_ids = {d.case_id for d in group}

        if len(case_ids) == 1:
            # Intra-caso: todos en el mismo caso
            # Conservar el que tiene email_id, o el más antiguo
            canonical = min(group, key=lambda d: (d.email_id is None, d.id))
            removable = [d for d in group if d.id != canonical.id]
            intra_removable += len(removable)
            if len(intra_groups) < 20:
                intra_groups.append({
                    "hash": h,
                    "case_id": list(case_ids)[0],
                    "total": len(group),
                    "removable": len(removable),
                    "canonical_doc_id": canonical.id,
                    "canonical_filename": canonical.filename[:60],
                })
        else:
            # Inter-caso: en diferentes casos
            inter_reviewable += len(group) - len(case_ids)
            if len(inter_groups) < 20:
                inter_groups.append({
                    "hash": h,
                    "case_ids": sorted(case_ids),
                    "total": len(group),
                    "files": [
                        {"doc_id": d.id, "filename": d.filename[:50], "case_id": d.case_id,
                         "verificacion": d.verificacion or ""}
                        for d in group[:6]
                    ],
                })

    return {
        "intra_case": {
            "groups": len([g for g in hash_groups.values() if len(g) > 1 and len({d.case_id for d in g}) == 1]),
            "removable_docs": intra_removable,
            "sample": intra_groups,
        },
        "inter_case": {
            "groups": len([g for g in hash_groups.values() if len(g) > 1 and len({d.case_id for d in g}) > 1]),
            "reviewable_docs": inter_reviewable,
            "sample": inter_groups,
        },
    }


def identify_reextraction_candidates(db: Session) -> dict[str, Any]:
    """Identifica casos que necesitan re-extracción de campos.

    Criterios:
    - accionante NULL o vacío
    - juzgado NULL o vacío
    - derecho_vulnerado NULL o vacío
    - Casos que fueron destino de una fusión reciente (tienen más docs que extracciones)

    Returns:
        dict con lista de case_ids y razones.
    """
    cases = db.query(Case).filter(
        Case.processing_status.in_(["COMPLETO", "PENDIENTE", "REVISION"])
    ).all()

    candidates = []
    for c in cases:
        reasons = []
        if not (c.accionante or "").strip():
            reasons.append("sin_accionante")
        if not (c.juzgado or "").strip():
            reasons.append("sin_juzgado")
        if not (c.derecho_vulnerado or "").strip():
            reasons.append("sin_derecho")
        if not (c.radicado_23_digitos or "").strip():
            reasons.append("sin_radicado_23d")

        if reasons:
            candidates.append({
                "case_id": c.id,
                "folder_name": (c.folder_name or "")[:80],
                "doc_count": len(c.documents),
                "reasons": reasons,
            })

    return {
        "total": len(candidates),
        "candidates": candidates,
    }


# ============================================================
# Reporte principal
# ============================================================

def diagnose(db: Session, base_dir: str | None = None) -> dict[str, Any]:
    """Diagnostico completo de la materia prima (DB + disco).

    Args:
        db: sesion SQLAlchemy
        base_dir: ruta raiz de las carpetas de casos. Si None, usa settings.BASE_DIR

    Returns:
        dict con todos los contadores y grupos de problemas detectados.
    """
    from backend.core.settings import settings
    if base_dir is None:
        base_dir = settings.BASE_DIR

    result: dict[str, Any] = {
        "timestamp": None,
        "base_dir": base_dir,
        "totals": {},
        "identity_groups": {},
        "fragments": [],
        "suspicious_folders": [],
        "typo_folders": [],
        "duplicate_radicados": [],
        "docs_without_hash": {"count": 0, "pct": 0.0},
        "docs_no_pertenece": {"count": 0, "sample": []},
        "docs_sospechoso": {"count": 0, "sample": []},
        "provenance": {},
        "emails": {},
        "disk": {},
        # v5.0
        "forest_fragments": [],
        "incomplete_radicados": {},
        "duplicate_cleanup": {},
        "reextraction_candidates": {},
    }

    from datetime import datetime
    result["timestamp"] = datetime.utcnow().isoformat()

    # --- Filtro base: solo casos activos (excluir DUPLICATE_MERGED) ---
    active_filter = [
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
        Case.processing_status != "DUPLICATE_MERGED",
    ]
    active_case_ids = {c.id for c in db.query(Case.id).filter(*active_filter).all()}

    # --- Totales basicos (solo casos activos) ---
    total_cases = len(active_case_ids)
    total_docs = db.query(Document).filter(Document.case_id.in_(active_case_ids)).count() if active_case_ids else 0
    total_emails = db.query(Email).filter(Email.status != "IGNORADO").count()

    active_cases = db.query(Case).filter(*active_filter).all()
    result["totals"] = {
        "cases": total_cases,
        "documents": total_docs,
        "emails": total_emails,
        "cases_completo": sum(1 for c in active_cases if c.processing_status == "COMPLETO"),
        "cases_pendiente": sum(1 for c in active_cases if c.processing_status == "PENDIENTE"),
        "cases_revision": sum(1 for c in active_cases if c.processing_status == "REVISION"),
        "cases_duplicate_merged": db.query(Case).filter(Case.processing_status == "DUPLICATE_MERGED").count(),
        "cases_zero_docs": sum(1 for c in active_cases if not c.documents),
        "cases_one_doc": sum(1 for c in active_cases if len(c.documents) == 1),
    }

    # --- Provenance (v4.8) ---
    linked = count_linked_documents(db)
    orphans = count_orphan_documents(db)
    result["provenance"] = {
        "docs_with_email_id": linked,
        "docs_without_email_id": orphans,
        "coverage_pct": round(linked / total_docs * 100, 2) if total_docs else 0.0,
    }

    # --- Identity groups: agrupa casos por (radicado_23d, accionante, tipo_rep) ---
    # Solo casos activos (excluye DUPLICATE_MERGED).
    identity_map: dict[tuple, list[int]] = defaultdict(list)
    cases_all = active_cases

    for c in cases_all:
        identity = case_identity(c)
        identity_map[identity].append(c.id)

    # Solo grupos con mas de 1 caso (candidatos a merge)
    groups_duplicated = []
    groups_manual_review = []
    for identity, case_ids in identity_map.items():
        if len(case_ids) > 1:
            rad23d, accionante, tipo_rep = identity
            entry = {
                "radicado_23d": rad23d,
                "accionante": accionante[:60],
                "tipo_representacion": tipo_rep,
                "case_ids": case_ids,
                "count": len(case_ids),
            }
            # Si tiene radicado 23d -> auto-mergeable
            if rad23d:
                groups_duplicated.append(entry)
            else:
                groups_manual_review.append(entry)

    result["identity_groups"] = {
        "auto_mergeable": groups_duplicated,
        "manual_review": groups_manual_review,
        "auto_count": len(groups_duplicated),
        "manual_count": len(groups_manual_review),
    }

    # --- Fragmentos (casos con <3 docs + folder_name sospechoso) ---
    for c in cases_all:
        doc_count = len(c.documents)
        if doc_count < 3:
            is_susp, reason = is_suspicious_folder_name(c.folder_name or "")
            if is_susp or doc_count == 0:
                result["fragments"].append({
                    "case_id": c.id,
                    "folder_name": (c.folder_name or "")[:80],
                    "doc_count": doc_count,
                    "reason": reason or f"solo {doc_count} doc(s)",
                    "status": c.processing_status,
                })

    # --- Suspicious folders (aunque tengan mas docs) ---
    for c in cases_all:
        is_susp, reason = is_suspicious_folder_name(c.folder_name or "")
        if is_susp and len(c.documents) >= 3:
            result["suspicious_folders"].append({
                "case_id": c.id,
                "folder_name": (c.folder_name or "")[:80],
                "doc_count": len(c.documents),
                "reason": reason,
            })

    # --- Typo folders ---
    for c in cases_all:
        is_typo, reason = is_typo_folder(c.folder_name or "")
        if is_typo:
            result["typo_folders"].append({
                "case_id": c.id,
                "folder_name": c.folder_name,
                "reason": reason,
            })

    # --- Docs sin content_hash (solo de casos activos) ---
    docs_no_hash = db.query(Document).filter(
        Document.case_id.in_(active_case_ids),
        (Document.file_hash == "") | (Document.file_hash.is_(None))
    ).count()
    result["docs_without_hash"] = {
        "count": docs_no_hash,
        "pct": round(docs_no_hash / total_docs * 100, 2) if total_docs else 0.0,
    }

    # --- Docs NO_PERTENECE y SOSPECHOSO (solo de casos activos) ---
    no_pert = db.query(Document).filter(
        Document.case_id.in_(active_case_ids),
        Document.verificacion == "NO_PERTENECE",
    ).all()
    result["docs_no_pertenece"] = {
        "count": len(no_pert),
        "sample": [
            {"doc_id": d.id, "case_id": d.case_id, "filename": d.filename[:60], "detalle": (d.verificacion_detalle or "")[:80]}
            for d in no_pert[:10]
        ],
    }

    sospechoso = db.query(Document).filter(
        Document.case_id.in_(active_case_ids),
        Document.verificacion == "SOSPECHOSO",
    ).all()
    result["docs_sospechoso"] = {
        "count": len(sospechoso),
        "sample": [
            {"doc_id": d.id, "case_id": d.case_id, "filename": d.filename[:60], "detalle": (d.verificacion_detalle or "")[:80]}
            for d in sospechoso[:5]
        ],
    }

    # --- Emails sin .md (solo emails asignados a casos activos) ---
    emails_activos = db.query(Email).filter(
        Email.case_id.in_(active_case_ids), Email.status != "IGNORADO",
    ).count()
    emails_with_md = db.query(Email).join(Document, Document.email_id == Email.id).filter(
        Document.doc_type == "EMAIL_MD", Document.case_id.in_(active_case_ids),
    ).distinct().count()
    emails_sin_caso = db.query(Email).filter(
        Email.case_id.is_(None), Email.status != "IGNORADO",
    ).count()
    result["emails"] = {
        "total": total_emails,
        "asignados": emails_activos,
        "sin_caso": emails_sin_caso,
        "with_md_generated": emails_with_md,
        "missing_md": emails_activos - emails_with_md,
    }

    # --- Disco: contar carpetas en BASE_DIR ---
    try:
        base_path = Path(base_dir)
        if base_path.exists():
            subdirs = [d for d in base_path.iterdir() if d.is_dir()]
            result["disk"] = {
                "base_dir": str(base_path),
                "total_folders": len(subdirs),
                "exists": True,
            }
        else:
            result["disk"] = {"base_dir": base_dir, "exists": False}
    except Exception as e:
        result["disk"] = {"base_dir": base_dir, "error": str(e)}

    # --- v5.0: Detectores ampliados ---
    try:
        result["forest_fragments"] = detect_forest_fragments(db)
    except Exception as e:
        logger.error("Error en detect_forest_fragments: %s", e)
        result["forest_fragments"] = []

    try:
        result["incomplete_radicados"] = detect_incomplete_radicados(db)
    except Exception as e:
        logger.error("Error en detect_incomplete_radicados: %s", e)
        result["incomplete_radicados"] = {}

    try:
        result["duplicate_cleanup"] = propose_duplicate_cleanup(db)
    except Exception as e:
        logger.error("Error en propose_duplicate_cleanup: %s", e)
        result["duplicate_cleanup"] = {}

    try:
        result["reextraction_candidates"] = identify_reextraction_candidates(db)
    except Exception as e:
        logger.error("Error en identify_reextraction_candidates: %s", e)
        result["reextraction_candidates"] = {}

    return result


def render_markdown(report: dict[str, Any]) -> str:
    """Renderiza el reporte de diagnosis como markdown."""
    lines: list[str] = []
    lines.append("# Diagnostico Cleanup v4.8")
    lines.append("")
    lines.append(f"**Timestamp:** {report.get('timestamp')}")
    lines.append(f"**BASE_DIR:** `{report.get('base_dir')}`")
    lines.append("")

    t = report.get("totals", {})
    lines.append("## Totales")
    lines.append(f"- Casos: **{t.get('cases', 0)}** (COMPLETO={t.get('cases_completo', 0)}, PENDIENTE={t.get('cases_pendiente', 0)}, REVISION={t.get('cases_revision', 0)})")
    lines.append(f"- Documents: **{t.get('documents', 0)}**")
    lines.append(f"- Emails: **{t.get('emails', 0)}**")
    lines.append(f"- Casos con 0 docs (huerfanos): **{t.get('cases_zero_docs', 0)}**")
    lines.append(f"- Casos con 1 doc (posibles fragmentos): **{t.get('cases_one_doc', 0)}**")
    lines.append("")

    p = report.get("provenance", {})
    lines.append("## v4.8 Provenance (email_id coverage)")
    lines.append(f"- Docs vinculados a email: **{p.get('docs_with_email_id', 0)}** ({p.get('coverage_pct', 0)}%)")
    lines.append(f"- Docs legacy (sin email_id): **{p.get('docs_without_email_id', 0)}**")
    lines.append("")

    ig = report.get("identity_groups", {})
    lines.append("## Grupos de identidad (radicado_23d + accionante + tipo_rep)")
    lines.append(f"- Grupos con >1 caso (auto-mergeable): **{ig.get('auto_count', 0)}**")
    lines.append(f"- Grupos con >1 caso (manual review, sin radicado_23d): **{ig.get('manual_count', 0)}**")
    if ig.get("auto_mergeable"):
        lines.append("")
        lines.append("### Top 10 grupos auto-mergeable")
        for g in ig["auto_mergeable"][:10]:
            lines.append(f"- `{g['radicado_23d']}` / {g['accionante'][:50]} / {g['tipo_representacion']} → {g['count']} casos (ids: {g['case_ids'][:5]})")
    lines.append("")

    lines.append("## Fragmentos detectados")
    lines.append(f"- Total: **{len(report.get('fragments', []))}** casos con <3 docs o folder sospechoso")
    for f in report.get("fragments", [])[:15]:
        lines.append(f"- id={f['case_id']} docs={f['doc_count']} `{f['folder_name'][:70]}` — {f['reason']}")
    lines.append("")

    sf = report.get("suspicious_folders", [])
    if sf:
        lines.append("## Carpetas sospechosas (con docs pero nombres raros)")
        lines.append(f"- Total: **{len(sf)}**")
        for f in sf[:10]:
            lines.append(f"- id={f['case_id']} docs={f['doc_count']} `{f['folder_name'][:70]}` — {f['reason']}")
        lines.append("")

    tf = report.get("typo_folders", [])
    if tf:
        lines.append("## Typos en nombre de carpeta")
        for t in tf:
            lines.append(f"- id={t['case_id']} `{t['folder_name'][:70]}` — {t['reason']}")
        lines.append("")

    dh = report.get("docs_without_hash", {})
    lines.append("## Docs sin content_hash")
    lines.append(f"- **{dh.get('count', 0)}** ({dh.get('pct', 0)}% del total)")
    lines.append("")

    np = report.get("docs_no_pertenece", {})
    lines.append("## Docs NO_PERTENECE")
    lines.append(f"- Total: **{np.get('count', 0)}**")
    for d in np.get("sample", [])[:5]:
        lines.append(f"- doc_id={d['doc_id']} case_id={d['case_id']} `{d['filename']}`")
    lines.append("")

    em = report.get("emails", {})
    lines.append("## Emails")
    lines.append(f"- Total emails: **{em.get('total', 0)}**")
    lines.append(f"- Con .md generado: **{em.get('with_md_generated', 0)}**")
    lines.append(f"- Sin .md (pendientes): **{em.get('missing_md', 0)}**")
    lines.append("")

    dk = report.get("disk", {})
    lines.append("## Disco")
    if dk.get("exists"):
        lines.append(f"- Carpetas en BASE_DIR: **{dk.get('total_folders', 0)}**")
    else:
        lines.append(f"- BASE_DIR no accesible: {dk.get('error', 'no existe')}")

    return "\n".join(lines)
