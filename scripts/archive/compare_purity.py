"""Compara pureza de DB entre backup histórico y DB actual.

Usa SQL puro para funcionar con cualquier schema (backups antiguos no tienen
todas las columnas del modelo actual).

Uso:
    python3 scripts/compare_purity.py --before data/tutelas_backup_20260324.db
"""

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parent.parent

CANONICAL_FOLDER_RE = re.compile(
    r"^(20\d{2})-\d{4,6}\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+$"
)


def _table_columns(conn, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def audit_db(db_path: Path) -> dict:
    """Audit SQL puro, tolerante a schemas diferentes."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    report = {}

    doc_cols = _table_columns(conn, "documents")
    case_cols = _table_columns(conn, "cases")
    email_cols = _table_columns(conn, "emails")

    # 1. Duplicidades de documentos (si existe file_hash)
    doc_dupes = []
    if "file_hash" in doc_cols:
        rows = conn.execute(
            "SELECT file_hash, filename, case_id FROM documents "
            "WHERE file_hash IS NOT NULL AND file_hash != ''"
        ).fetchall()
        by_hash = defaultdict(list)
        for r in rows:
            by_hash[r["file_hash"]].append({"filename": r["filename"], "case_id": r["case_id"]})
        for h, docs in by_hash.items():
            cases = {d["case_id"] for d in docs}
            if len(cases) > 1:
                doc_dupes.append({
                    "hash": h[:12], "filename": docs[0]["filename"],
                    "cases": sorted(cases), "count": len(docs),
                })
    report["document_duplicates"] = doc_dupes

    # 2. Duplicidades de casos (mismo accionante + rad23)
    case_dupes = []
    if "accionante" in case_cols and "radicado_23_digitos" in case_cols:
        rows = conn.execute(
            "SELECT id, accionante, radicado_23_digitos FROM cases "
            "WHERE accionante IS NOT NULL AND accionante != '' "
            "AND radicado_23_digitos IS NOT NULL AND radicado_23_digitos != ''"
        ).fetchall()
        by_key = defaultdict(list)
        for r in rows:
            key = (r["accionante"].strip().upper()[:40], r["radicado_23_digitos"].strip()[:20])
            by_key[key].append(r["id"])
        for (acc, rad), ids in by_key.items():
            if len(ids) > 1:
                case_dupes.append({"accionante": acc, "rad23": rad, "case_ids": ids})
    report["case_duplicates"] = case_dupes

    # 3. Carpetas mal nombradas
    folder_issues = []
    rows = conn.execute("SELECT id, folder_name FROM cases").fetchall()
    for r in rows:
        fn = r["folder_name"]
        if not fn:
            folder_issues.append({"case_id": r["id"], "folder_name": None, "issue": "missing"})
        elif not CANONICAL_FOLDER_RE.match(fn):
            folder_issues.append({"case_id": r["id"], "folder_name": fn[:60], "issue": "non_canonical"})
    report["folder_naming_issues"] = folder_issues

    # 4. Documentos huérfanos
    orphan_no_case = conn.execute(
        "SELECT COUNT(*) as n FROM documents WHERE case_id IS NULL"
    ).fetchone()["n"]
    report["orphan_documents"] = {"orphan_no_case": orphan_no_case}

    # 5. Documentos por estado de verificación
    verif_counts = {}
    if "verificacion" in doc_cols:
        rows = conn.execute(
            "SELECT verificacion, COUNT(*) as n FROM documents GROUP BY verificacion"
        ).fetchall()
        verif_counts = {r["verificacion"] or "NULL": r["n"] for r in rows}
    report["document_verification"] = verif_counts

    # 6. Campos críticos vacíos
    total_cases = conn.execute("SELECT COUNT(*) as n FROM cases").fetchone()["n"]
    critical_fields = ["accionante", "radicado_23_digitos", "radicado_forest",
                       "ciudad", "derecho_vulnerado", "asunto", "observaciones"]
    missing = {}
    for field in critical_fields:
        if field in case_cols:
            n = conn.execute(
                f"SELECT COUNT(*) as n FROM cases WHERE {field} IS NULL OR TRIM({field}) = ''"
            ).fetchone()["n"]
            key = "sin_" + field.replace("radicado_23_digitos", "rad23").replace("radicado_forest", "forest").replace("derecho_vulnerado", "derecho")
            missing[key] = n
    report["critical_fields"] = {"total_cases": total_cases, "missing": missing}

    # 7. Inconsistencias rad23 vs folder_name
    xmis = []
    if "radicado_23_digitos" in case_cols and "folder_name" in case_cols:
        rows = conn.execute(
            "SELECT id, radicado_23_digitos, folder_name FROM cases "
            "WHERE radicado_23_digitos IS NOT NULL AND folder_name IS NOT NULL"
        ).fetchall()
        for r in rows:
            rad = r["radicado_23_digitos"]
            fn = r["folder_name"]
            m = re.search(r"(\d{4,5})-\d{2}$", rad)
            if not m:
                continue
            rad_cons = m.group(1).lstrip("0")
            fm = re.match(r"(20\d{2})-(\d{4,6})", fn)
            if not fm:
                continue
            folder_cons = fm.group(2).lstrip("0")
            if rad_cons != folder_cons:
                xmis.append({"case_id": r["id"], "rad_cons": rad_cons, "folder_cons": folder_cons})
    report["xfield_inconsistencies"] = xmis

    # 8. Casos vacíos (sin documentos)
    rows = conn.execute(
        "SELECT c.id FROM cases c LEFT JOIN documents d ON d.case_id = c.id "
        "GROUP BY c.id HAVING COUNT(d.id) = 0"
    ).fetchall()
    report["empty_cases"] = [r["id"] for r in rows]

    # 9. Emails
    orphan_emails = 0
    total_emails = 0
    if email_cols:
        total_emails = conn.execute("SELECT COUNT(*) as n FROM emails").fetchone()["n"]
        if "case_id" in email_cols:
            orphan_emails = conn.execute(
                "SELECT COUNT(*) as n FROM emails WHERE case_id IS NULL"
            ).fetchone()["n"]
    report["orphan_emails"] = {"total": total_emails, "without_case": orphan_emails}

    # 10. FK orphans
    ext_cols = _table_columns(conn, "extractions")
    ext_orphan = 0
    if "case_id" in ext_cols:
        ext_orphan = conn.execute(
            "SELECT COUNT(*) as n FROM extractions WHERE case_id IS NULL"
        ).fetchone()["n"]
    report["fk_orphans"] = {"document_orphans": orphan_no_case, "extraction_orphans": ext_orphan}

    # Purity score
    issues = (
        len(doc_dupes) * 2
        + len(case_dupes) * 5
        + len(folder_issues)
        + orphan_no_case * 2
        + verif_counts.get("SOSPECHOSO", 0)
        + verif_counts.get("NO_PERTENECE", 0) * 2
        + sum(missing.values())
        + len(xmis) * 2
        + len(report["empty_cases"])
    )
    max_penalty = total_cases * 20
    score = max(0, min(100, 100 - (issues / max(1, max_penalty) * 100)))
    report["purity_score"] = round(score, 2)
    report["total_issues_weighted"] = issues

    conn.close()
    return report


def compare(before: dict, after: dict, before_name: str = "ANTES", after_name: str = "DESPUÉS") -> str:
    lines = []
    lines.append("# Comparativa de pureza DB — ANTES vs DESPUÉS")
    lines.append("")
    lines.append(f"- **ANTES**: {before_name}")
    lines.append(f"- **DESPUÉS**: {after_name}")
    lines.append("")
    lines.append("## Métricas agregadas")
    lines.append("")
    lines.append(f"| Métrica | ANTES | DESPUÉS | Δ |")
    lines.append(f"|---|---|---|---|")

    bs = before["purity_score"]
    as_ = after["purity_score"]
    arrow = "🟢" if as_ > bs else ("🔴" if as_ < bs else "⚪")
    lines.append(f"| **Purity score** | {bs:.2f}/100 | **{as_:.2f}/100** | {as_-bs:+.2f} {arrow} |")

    bt = before["critical_fields"]["total_cases"]
    at = after["critical_fields"]["total_cases"]
    lines.append(f"| Total casos | {bt} | {at} | {at-bt:+d} |")

    def _cmp(label, b, a):
        a_int = int(a); b_int = int(b)
        arr = "🟢" if a_int < b_int else ("🔴" if a_int > b_int else "⚪")
        lines.append(f"| {label} | {b_int} | {a_int} | {a_int-b_int:+d} {arr} |")

    _cmp("Duplicidades docs (multi-caso)", len(before["document_duplicates"]), len(after["document_duplicates"]))
    _cmp("Duplicidades casos", len(before["case_duplicates"]), len(after["case_duplicates"]))
    _cmp("Carpetas mal nombradas", len(before["folder_naming_issues"]), len(after["folder_naming_issues"]))
    _cmp("Casos vacíos", len(before["empty_cases"]), len(after["empty_cases"]))
    _cmp("Inconsistencias rad23/folder", len(before["xfield_inconsistencies"]), len(after["xfield_inconsistencies"]))
    _cmp("Emails sin caso", before["orphan_emails"]["without_case"], after["orphan_emails"]["without_case"])
    _cmp("FK orphans documents", before["fk_orphans"]["document_orphans"], after["fk_orphans"]["document_orphans"])

    lines.append("")
    lines.append("## Campos críticos vacíos")
    lines.append("| Campo | ANTES | DESPUÉS | Δ |")
    lines.append("|---|---|---|---|")
    bm = before["critical_fields"]["missing"]
    am = after["critical_fields"]["missing"]
    for field in sorted(set(bm.keys()) | set(am.keys())):
        b = bm.get(field, 0)
        a = am.get(field, 0)
        b_pct = 100 * b / max(1, bt)
        a_pct = 100 * a / max(1, at)
        arr = "🟢" if a_pct < b_pct else ("🔴" if a_pct > b_pct else "⚪")
        lines.append(f"| {field} | {b} ({b_pct:.1f}%) | {a} ({a_pct:.1f}%) | {a_pct-b_pct:+.1f}pp {arr} |")

    lines.append("")
    lines.append("## Estado de verificación de documentos")
    if before["document_verification"] or after["document_verification"]:
        lines.append("| Estado | ANTES | DESPUÉS | Δ |")
        lines.append("|---|---|---|---|")
        bv = before["document_verification"]
        av = after["document_verification"]
        if not bv:
            lines.append(f"| (columna `verificacion` no existía en snapshot antiguo) | — | — | — |")
        for status in sorted(set(bv.keys()) | set(av.keys()), key=lambda x: str(x)):
            b = bv.get(status, 0)
            a = av.get(status, 0)
            lines.append(f"| `{status}` | {b} | {a} | {a-b:+d} |")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", default="data/tutelas.db")
    ap.add_argument("--output", default="docs/PUREZA_COMPARATIVA.md")
    args = ap.parse_args()

    before_path = APP / args.before
    after_path = APP / args.after

    print(f"Auditando BEFORE: {before_path.name}")
    before = audit_db(before_path)
    print(f"Auditando AFTER:  {after_path.name}")
    after = audit_db(after_path)

    md = compare(before, after, before_path.name, after_path.name)
    out = APP / args.output
    out.write_text(md, encoding="utf-8")

    json_dir = APP / "data"
    (json_dir / "purity_before.json").write_text(json.dumps(before, indent=2, default=str))
    (json_dir / "purity_after.json").write_text(json.dumps(after, indent=2, default=str))

    print(f"\nReporte: {out}")
    print(md)


if __name__ == "__main__":
    main()
