"""Cleanup diagnosis v4.8: funciones puras read-only.

Agrupa TODO el desorden de disco + DB en un solo reporte JSON, usando la
regla de identidad (radicado_23d + accionante + tipo_representacion).

NO toca nada. Solo lee y agrupa.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email
from backend.services.provenance_service import count_linked_documents, count_orphan_documents


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
    }

    from datetime import datetime
    result["timestamp"] = datetime.utcnow().isoformat()

    # --- Totales basicos ---
    total_cases = db.query(Case).count()
    total_docs = db.query(Document).count()
    total_emails = db.query(Email).count()

    result["totals"] = {
        "cases": total_cases,
        "documents": total_docs,
        "emails": total_emails,
        "cases_completo": db.query(Case).filter(Case.processing_status == "COMPLETO").count(),
        "cases_pendiente": db.query(Case).filter(Case.processing_status == "PENDIENTE").count(),
        "cases_revision": db.query(Case).filter(Case.processing_status == "REVISION").count(),
        "cases_duplicate_merged": db.query(Case).filter(Case.processing_status == "DUPLICATE_MERGED").count(),
        "cases_zero_docs": db.query(Case).filter(
            ~Case.documents.any()
        ).count(),
        "cases_one_doc": sum(
            1 for c in db.query(Case).all()
            if len(c.documents) == 1
        ),
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
    # Excluye casos ya fusionados (DUPLICATE_MERGED) para no re-proponer merges.
    identity_map: dict[tuple, list[int]] = defaultdict(list)
    cases_all = db.query(Case).filter(
        (Case.processing_status != "DUPLICATE_MERGED") | (Case.processing_status.is_(None))
    ).all()

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

    # --- Docs sin content_hash ---
    docs_no_hash = db.query(Document).filter(
        (Document.file_hash == "") | (Document.file_hash.is_(None))
    ).count()
    result["docs_without_hash"] = {
        "count": docs_no_hash,
        "pct": round(docs_no_hash / total_docs * 100, 2) if total_docs else 0.0,
    }

    # --- Docs NO_PERTENECE y SOSPECHOSO ---
    no_pert = db.query(Document).filter(Document.verificacion == "NO_PERTENECE").all()
    result["docs_no_pertenece"] = {
        "count": len(no_pert),
        "sample": [
            {"doc_id": d.id, "case_id": d.case_id, "filename": d.filename[:60], "detalle": (d.verificacion_detalle or "")[:80]}
            for d in no_pert[:10]
        ],
    }

    sospechoso = db.query(Document).filter(Document.verificacion == "SOSPECHOSO").all()
    result["docs_sospechoso"] = {
        "count": len(sospechoso),
        "sample": [
            {"doc_id": d.id, "case_id": d.case_id, "filename": d.filename[:60], "detalle": (d.verificacion_detalle or "")[:80]}
            for d in sospechoso[:5]
        ],
    }

    # --- Emails sin .md ---
    emails_all = db.query(Email).count()
    emails_with_md = db.query(Email).join(Document, Document.email_id == Email.id).filter(
        Document.doc_type == "EMAIL_MD"
    ).distinct().count()
    result["emails"] = {
        "total": emails_all,
        "with_md_generated": emails_with_md,
        "missing_md": emails_all - emails_with_md,
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
