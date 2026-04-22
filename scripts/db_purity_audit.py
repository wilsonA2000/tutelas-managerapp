"""Auditoría de pureza y confiabilidad de la DB (v5.3.3).

Mide 10 dimensiones de "suciedad" de datos:

1. Duplicidades de documentos (mismo file_hash en múltiples casos).
2. Duplicidades de carpetas (mismo accionante + rad23).
3. Carpetas mal nombradas (folder_name ≠ "YYYY-NNNNN ACCIONANTE").
4. Documentos huérfanos (sin case_id o sin archivo físico).
5. Documentos mal asociados (verificacion SOSPECHOSO / NO_PERTENECE).
6. Casos con campos críticos vacíos (accionante/rad23/forest).
7. Inconsistencias cross-field (rad23 vs folder_name).
8. Casos sin documentos.
9. Emails sin case asignado.
10. Integridad referencial (FK orphans).

Uso:
    python3 scripts/db_purity_audit.py [--output data/purity_report.json]
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document, Email, Extraction


# Patrón canónico de folder_name: "YYYY-NNNNN NOMBRE ACCIONANTE"
CANONICAL_FOLDER_RE = re.compile(
    r"^(20\d{2})-\d{4,6}\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+$"
)


def audit_document_duplicates(db):
    """Docs con mismo file_hash asociados a múltiples casos distintos."""
    rows = db.query(Document).filter(Document.file_hash != "").all()
    by_hash = defaultdict(list)
    for d in rows:
        by_hash[d.file_hash].append(d)
    duplicates = []
    for h, docs in by_hash.items():
        if len(docs) > 1:
            cases = {d.case_id for d in docs}
            if len(cases) > 1:
                duplicates.append({
                    "hash": h[:12],
                    "filename": docs[0].filename,
                    "cases": sorted(cases),
                    "count": len(docs),
                })
    return duplicates


def audit_case_duplicates(db):
    """Casos con mismo (accionante, rad23) — posibles duplicados."""
    cases = db.query(Case).all()
    by_key = defaultdict(list)
    for c in cases:
        if c.accionante and c.radicado_23_digitos:
            key = (c.accionante.strip().upper(), c.radicado_23_digitos.strip())
            by_key[key].append(c.id)
    duplicates = [
        {"accionante": k[0], "rad23": k[1], "case_ids": v}
        for k, v in by_key.items() if len(v) > 1
    ]
    return duplicates


def audit_folder_naming(db):
    """Carpetas que no siguen el formato canónico."""
    cases = db.query(Case).all()
    bad = []
    for c in cases:
        if not c.folder_name:
            bad.append({"case_id": c.id, "folder_name": None, "issue": "missing"})
            continue
        if not CANONICAL_FOLDER_RE.match(c.folder_name):
            bad.append({
                "case_id": c.id,
                "folder_name": c.folder_name[:60],
                "issue": "non_canonical",
            })
    return bad


def audit_orphan_documents(db):
    """Documentos sin case_id válido o sin archivo físico."""
    orphans_no_case = db.query(Document).filter(Document.case_id.is_(None)).count()
    # Archivos físicos: comprobar unos pocos para no sobrecargar
    all_docs = db.query(Document).filter(Document.case_id.isnot(None)).limit(500).all()
    missing_physical = 0
    for d in all_docs:
        if d.file_path and not Path(d.file_path).exists():
            missing_physical += 1
    return {
        "orphan_no_case": orphans_no_case,
        "missing_physical_file_sample": missing_physical,
        "sample_size": len(all_docs),
    }


def audit_document_assoc(db):
    """Documentos marcados como sospechosos o no pertenecen."""
    counts = Counter()
    for d in db.query(Document).all():
        v = d.verificacion or ""
        counts[v] += 1
    return dict(counts)


def audit_critical_fields(db):
    """Casos con campos críticos vacíos."""
    cases = db.query(Case).all()
    missing = {
        "sin_accionante": 0,
        "sin_rad23": 0,
        "sin_forest": 0,
        "sin_ciudad": 0,
        "sin_derecho": 0,
        "sin_asunto": 0,
        "sin_observaciones": 0,
    }
    for c in cases:
        if not (c.accionante or "").strip():
            missing["sin_accionante"] += 1
        if not (c.radicado_23_digitos or "").strip():
            missing["sin_rad23"] += 1
        if not (c.radicado_forest or "").strip():
            missing["sin_forest"] += 1
        if not (c.ciudad or "").strip():
            missing["sin_ciudad"] += 1
        if not (c.derecho_vulnerado or "").strip():
            missing["sin_derecho"] += 1
        if not (c.asunto or "").strip():
            missing["sin_asunto"] += 1
        if not (c.observaciones or "").strip():
            missing["sin_observaciones"] += 1
    return {"total_cases": len(cases), "missing": missing}


def audit_xfield_inconsistencies(db):
    """rad23 en DB debe coincidir con folder_name (parte del consecutivo)."""
    cases = db.query(Case).all()
    mismatches = []
    for c in cases:
        if not c.radicado_23_digitos or not c.folder_name:
            continue
        # Extraer consecutivo del rad23: último bloque "NNNNN"
        m = re.search(r"(\d{4,5})-\d{2}$", c.radicado_23_digitos)
        if not m:
            continue
        rad_cons = m.group(1).lstrip("0")
        # Extraer consecutivo del folder: "YYYY-NNNNN"
        fm = re.match(r"(20\d{2})-(\d{4,6})", c.folder_name)
        if not fm:
            continue
        folder_cons = fm.group(2).lstrip("0")
        if rad_cons != folder_cons:
            mismatches.append({
                "case_id": c.id,
                "rad23": c.radicado_23_digitos,
                "folder_name": c.folder_name[:60],
                "rad_cons": rad_cons,
                "folder_cons": folder_cons,
            })
    return mismatches


def audit_empty_cases(db):
    """Casos sin documentos."""
    cases = db.query(Case).all()
    empty = [c.id for c in cases if not c.documents]
    return empty


def audit_orphan_emails(db):
    """Emails sin case asociado."""
    return {
        "total": db.query(Email).count(),
        "without_case": db.query(Email).filter(Email.case_id.is_(None)).count(),
    }


def audit_fk_orphans(db):
    """Foreign keys rotas: Documents sin case, Extractions sin case/doc."""
    doc_no_case = db.query(Document).filter(Document.case_id.is_(None)).count()
    ext_no_case = db.query(Extraction).filter(Extraction.case_id.is_(None)).count()
    return {"document_orphans": doc_no_case, "extraction_orphans": ext_no_case}


def run_audit():
    db = SessionLocal()
    try:
        report = {}
        report["document_duplicates"] = audit_document_duplicates(db)
        report["case_duplicates"] = audit_case_duplicates(db)
        report["folder_naming_issues"] = audit_folder_naming(db)
        report["orphan_documents"] = audit_orphan_documents(db)
        report["document_verification"] = audit_document_assoc(db)
        report["critical_fields"] = audit_critical_fields(db)
        report["xfield_inconsistencies"] = audit_xfield_inconsistencies(db)
        report["empty_cases"] = audit_empty_cases(db)
        report["orphan_emails"] = audit_orphan_emails(db)
        report["fk_orphans"] = audit_fk_orphans(db)

        total_cases = report["critical_fields"]["total_cases"]
        # Score de pureza (0-100)
        issues = (
            len(report["document_duplicates"]) * 2
            + len(report["case_duplicates"]) * 5
            + len(report["folder_naming_issues"])
            + report["orphan_documents"]["orphan_no_case"] * 2
            + report["document_verification"].get("SOSPECHOSO", 0)
            + report["document_verification"].get("NO_PERTENECE", 0) * 2
            + sum(report["critical_fields"]["missing"].values())
            + len(report["xfield_inconsistencies"]) * 2
            + len(report["empty_cases"])
        )
        # Penalización relativa al total
        max_penalty = total_cases * 20  # cota superior teórica
        score = max(0, min(100, 100 - (issues / max(1, max_penalty) * 100)))
        report["purity_score"] = round(score, 2)
        report["total_issues_weighted"] = issues

        return report
    finally:
        db.close()


def render_report(report) -> str:
    lines = []
    lines.append(f"# DB Purity Audit Report")
    lines.append(f"")
    lines.append(f"**Purity score**: {report['purity_score']:.2f}/100")
    lines.append(f"**Total issues (weighted)**: {report['total_issues_weighted']}")
    lines.append(f"**Total casos**: {report['critical_fields']['total_cases']}")
    lines.append(f"")

    lines.append("## 1. Duplicidades de documentos (mismo hash, múltiples casos)")
    if report["document_duplicates"]:
        for d in report["document_duplicates"][:10]:
            lines.append(f"- Hash `{d['hash']}`: {d['filename']} en casos {d['cases']}")
    else:
        lines.append("✅ Sin duplicidades.")
    lines.append("")

    lines.append("## 2. Duplicidades de casos (mismo accionante + rad23)")
    if report["case_duplicates"]:
        for d in report["case_duplicates"][:10]:
            lines.append(f"- {d['accionante'][:40]} / rad23 {d['rad23'][:20]}: casos {d['case_ids']}")
    else:
        lines.append("✅ Sin duplicidades.")
    lines.append("")

    lines.append("## 3. Carpetas mal nombradas (no siguen `YYYY-NNNNN ACCIONANTE`)")
    fn = report["folder_naming_issues"]
    lines.append(f"Total: **{len(fn)}** carpetas con nombres no canónicos")
    for f in fn[:15]:
        lines.append(f"- Case #{f['case_id']}: `{f['folder_name']}`")
    if len(fn) > 15:
        lines.append(f"- ... y {len(fn) - 15} más")
    lines.append("")

    lines.append("## 4. Documentos huérfanos")
    od = report["orphan_documents"]
    lines.append(f"- Sin case_id: **{od['orphan_no_case']}**")
    lines.append(f"- Sin archivo físico (muestra {od['sample_size']}): **{od['missing_physical_file_sample']}**")
    lines.append("")

    lines.append("## 5. Documentos por estado de verificación")
    for status, n in report["document_verification"].items():
        lines.append(f"- `{status or 'NULL'}`: {n}")
    lines.append("")

    lines.append("## 6. Campos críticos vacíos")
    cf = report["critical_fields"]
    total = cf["total_cases"]
    for field, n in cf["missing"].items():
        pct = 100 * n / max(1, total)
        lines.append(f"- {field}: {n} ({pct:.1f}%)")
    lines.append("")

    lines.append("## 7. Inconsistencias rad23 vs folder_name")
    xi = report["xfield_inconsistencies"]
    lines.append(f"Total: **{len(xi)}** casos con rad23 no alineado con folder")
    for x in xi[:10]:
        lines.append(f"- Case #{x['case_id']}: rad={x['rad_cons']} vs folder={x['folder_cons']}")
    lines.append("")

    lines.append("## 8. Casos vacíos (sin documentos)")
    lines.append(f"- {len(report['empty_cases'])} casos: {report['empty_cases'][:20]}")
    lines.append("")

    lines.append("## 9. Emails huérfanos")
    oe = report["orphan_emails"]
    lines.append(f"- Total emails: {oe['total']}")
    lines.append(f"- Sin caso: **{oe['without_case']}**")
    lines.append("")

    lines.append("## 10. FK orphans")
    fk = report["fk_orphans"]
    lines.append(f"- Document orphans: {fk['document_orphans']}")
    lines.append(f"- Extraction orphans: {fk['extraction_orphans']}")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default=None, help="Ruta para JSON (default: stdout)")
    ap.add_argument("--md", default=None, help="Ruta para reporte Markdown")
    args = ap.parse_args()

    print("Ejecutando auditoría de pureza...")
    report = run_audit()

    # Markdown legible
    md = render_report(report)
    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
        print(f"Reporte MD: {args.md}")

    # JSON para comparación
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"Reporte JSON: {args.output}")
    else:
        print(md)


if __name__ == "__main__":
    main()
