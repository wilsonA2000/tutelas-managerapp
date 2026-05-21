"""Auditor automatizado: cruza 28 campos x 220 cases contra 12 reglas juridicas.

Salidas:
    data/exports/audit_report.json   (por caso, lista de findings)
    data/exports/audit_summary.csv   (matriz caso x campo)

Reglas (priorizando fallos y seguimiento):
    R1  impugnacion=NO -> sentido_fallo_2nd / juzgado_2nd / fecha_fallo_2nd vacios
    R2  sentido_fallo_2nd presente -> juzgado_2nd y fecha_fallo_2nd tambien
    R3  sentido_fallo_1st / sentido_fallo_2nd con enum valido
    R4  incidente=SI -> fecha_apertura_incidente y responsable_desacato presentes
    R5  radicado_23_digitos con >=18 digitos limpios
    R6  fecha_ingreso <= fecha_fallo_1st <= fecha_fallo_2nd <= fecha_apertura_incidente
    R7  tipo=TUTELA y sin radicado_23 ni radicado_forest -> SIN_ID
    R8  impugnacion=SI -> quien_impugno poblado
    R9  juzgado != juzgado_2nd
    R10 abogado_responsable resuelve a canonical (o se anota firmante operativo)
    R11 accionante no es None ni vacio
    R12 coherencia con case_actuaciones del Excel oficial

Uso:
    python3 scripts/audit_cases.py                  # corre y guarda reportes
    python3 scripts/audit_cases.py --rule R1        # solo una regla
    python3 scripts/audit_cases.py --case 25        # solo un caso
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.abogados_resolver import normalize_abogado
from backend.database.database import SessionLocal
from backend.database.models import Case, CaseActuacion, Document
from backend.email.rad_utils import normalize_rad23

EXPORTS = Path(__file__).resolve().parents[1] / "data" / "exports"

# Enum 1ra alineado con backend.v9.field_extractor.SENTIDO_FALLO_VOCAB (2026-05-20):
# CARENCIA_OBJETO/HECHO_SUPERADO (la vulneración cesó), DESISTIMIENTO (desistimiento
# aceptado, art.26 D2591/91) y CONCEDE_PARCIAL son sentidos válidos que produce v9.
# Se conservan DESISTIDO/TRAMITE/RECHAZA por tolerancia a valores legacy.
ENUM_FALLO_1ST = {"CONCEDE", "CONCEDE_PARCIAL", "NIEGA", "IMPROCEDENTE", "DESISTIMIENTO",
                  "CARENCIA_OBJETO", "HECHO_SUPERADO",
                  "DESISTIDO", "TRAMITE", "RECHAZA"}
ENUM_FALLO_2ND = {"CONFIRMA", "REVOCA", "MODIFICA", "INHIBE", "NULIDAD", "DECLARA_NULIDAD"}
DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})")


@dataclass
class Finding:
    rule: str
    field: str
    severity: str  # "ERROR" | "WARN" | "INFO"
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _is_empty(v: Optional[str]) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return not s or s.upper() in ("NONE", "N/A", "NA", "NULL")


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    m = DATE_RE.search(s)
    if not m:
        return None
    d, mth, y = m.groups()
    try:
        return datetime(int(y), int(mth), int(d))
    except ValueError:
        return None


def _enum_norm(v: Optional[str]) -> str:
    if not v:
        return ""
    s = re.sub(r"[^A-ZÁÉÍÓÚÑ_]+", " ", str(v).upper())
    return s.strip().split(" ")[0] if s.strip() else ""


# -------- 12 reglas --------

def rule_R1(case: Case) -> list[Finding]:
    if (case.impugnacion or "").upper() != "NO":
        return []
    out = []
    for f_name in ("sentido_fallo_2nd", "juzgado_2nd", "fecha_fallo_2nd"):
        v = getattr(case, f_name, None)
        if not _is_empty(v):
            out.append(Finding(
                rule="R1", field=f_name, severity="ERROR",
                message=f"impugnacion=NO pero {f_name}={v!r} esta poblado",
                evidence={"impugnacion": case.impugnacion, f_name: v},
            ))
    return out


def rule_R2(case: Case) -> list[Finding]:
    if _is_empty(case.sentido_fallo_2nd):
        return []
    out = []
    if _is_empty(case.juzgado_2nd):
        out.append(Finding("R2", "juzgado_2nd", "ERROR",
                           "sentido_fallo_2nd presente pero juzgado_2nd vacio",
                           {"sentido_fallo_2nd": case.sentido_fallo_2nd}))
    if _is_empty(case.fecha_fallo_2nd):
        out.append(Finding("R2", "fecha_fallo_2nd", "ERROR",
                           "sentido_fallo_2nd presente pero fecha_fallo_2nd vacia",
                           {"sentido_fallo_2nd": case.sentido_fallo_2nd}))
    return out


def rule_R3(case: Case) -> list[Finding]:
    out = []
    if not _is_empty(case.sentido_fallo_1st):
        norm = _enum_norm(case.sentido_fallo_1st)
        if norm not in ENUM_FALLO_1ST:
            out.append(Finding("R3", "sentido_fallo_1st", "WARN",
                               f"sentido_fallo_1st={case.sentido_fallo_1st!r} no es enum valido",
                               {"valor": case.sentido_fallo_1st, "enum": sorted(ENUM_FALLO_1ST)}))
    if not _is_empty(case.sentido_fallo_2nd):
        norm = _enum_norm(case.sentido_fallo_2nd)
        if norm not in ENUM_FALLO_2ND:
            out.append(Finding("R3", "sentido_fallo_2nd", "WARN",
                               f"sentido_fallo_2nd={case.sentido_fallo_2nd!r} no es enum valido",
                               {"valor": case.sentido_fallo_2nd, "enum": sorted(ENUM_FALLO_2ND)}))
    return out


def rule_R4(case: Case) -> list[Finding]:
    if (case.incidente or "").upper() != "SI":
        return []
    out = []
    if _is_empty(case.fecha_apertura_incidente):
        out.append(Finding("R4", "fecha_apertura_incidente", "ERROR",
                           "incidente=SI pero fecha_apertura_incidente vacia"))
    if _is_empty(case.responsable_desacato):
        out.append(Finding("R4", "responsable_desacato", "ERROR",
                           "incidente=SI pero responsable_desacato vacio"))
    return out


def rule_R5(case: Case) -> list[Finding]:
    if _is_empty(case.radicado_23_digitos):
        return []
    digits = normalize_rad23(case.radicado_23_digitos)
    if len(digits) < 18:
        return [Finding("R5", "radicado_23_digitos", "WARN",
                        f"radicado_23 truncado: {len(digits)} digitos limpios (esperado >=18)",
                        {"valor": case.radicado_23_digitos, "digitos_limpios": len(digits)})]
    return []


def rule_R6(case: Case) -> list[Finding]:
    """Orden cronologico: fecha_ingreso <= fecha_fallo_1st <= fecha_fallo_2nd <= fecha_apertura_incidente."""
    seq = [
        ("fecha_ingreso", _parse_date(case.fecha_ingreso)),
        ("fecha_fallo_1st", _parse_date(case.fecha_fallo_1st)),
        ("fecha_fallo_2nd", _parse_date(case.fecha_fallo_2nd)),
        ("fecha_apertura_incidente", _parse_date(case.fecha_apertura_incidente)),
    ]
    out = []
    prev_name, prev_date = None, None
    for name, dt in seq:
        if dt is None:
            continue
        if prev_date is not None and dt < prev_date:
            out.append(Finding("R6", name, "WARN",
                               f"{name}={dt:%Y-%m-%d} es anterior a {prev_name}={prev_date:%Y-%m-%d}",
                               {"actual": str(dt.date()), "previo": prev_name, "previo_fecha": str(prev_date.date())}))
        prev_name, prev_date = name, dt
    return out


def rule_R7(case: Case) -> list[Finding]:
    tipo = (case.tipo_actuacion or "TUTELA").upper()
    if tipo != "TUTELA":
        return []
    if _is_empty(case.radicado_23_digitos) and _is_empty(case.radicado_forest):
        return [Finding("R7", "radicado_23_digitos", "ERROR",
                        "TUTELA sin radicado_23 ni radicado_forest (SIN_ID)",
                        {"folder_name": case.folder_name})]
    return []


def rule_R8(case: Case) -> list[Finding]:
    if (case.impugnacion or "").upper() != "SI":
        return []
    if _is_empty(case.quien_impugno):
        return [Finding("R8", "quien_impugno", "ERROR",
                        "impugnacion=SI pero quien_impugno vacio")]
    return []


def rule_R9(case: Case) -> list[Finding]:
    j1 = (case.juzgado or "").strip().upper()
    j2 = (case.juzgado_2nd or "").strip().upper()
    if j1 and j2 and j1 == j2:
        return [Finding("R9", "juzgado_2nd", "WARN",
                        "juzgado y juzgado_2nd son identicos (debe ser superior jerarquico)",
                        {"juzgado": j1, "juzgado_2nd": j2})]
    return []


def rule_R10(case: Case) -> list[Finding]:
    if _is_empty(case.abogado_responsable):
        return []
    if _is_empty(case.abogado_canonical):
        canon = normalize_abogado(case.abogado_responsable)
        if canon:
            return [Finding("R10", "abogado_canonical", "WARN",
                            f"abogado_responsable={case.abogado_responsable!r} resolveria a {canon} pero abogado_canonical vacio",
                            {"sugerido": canon})]
        return [Finding("R10", "abogado_canonical", "INFO",
                        f"abogado_responsable={case.abogado_responsable!r} es firmante operativo (no oficial)")]
    return []


def rule_R11(case: Case) -> list[Finding]:
    if _is_empty(case.accionante):
        return [Finding("R11", "accionante", "ERROR",
                        "accionante esta vacio o es 'None'",
                        {"valor": case.accionante})]
    return []


def rule_R12(case: Case, db_actuaciones: list[CaseActuacion]) -> list[Finding]:
    """Coherencia con case_actuaciones del Excel oficial."""
    if not db_actuaciones:
        return []
    out = []
    excel_abogados = {a.abogado_canonical for a in db_actuaciones if a.abogado_canonical}
    if (case.abogado_canonical and excel_abogados
            and case.abogado_canonical not in excel_abogados):
        out.append(Finding("R12", "abogado_canonical", "WARN",
                           f"abogado_canonical DB={case.abogado_canonical!r} discrepa con Excel={sorted(excel_abogados)}",
                           {"db": case.abogado_canonical, "excel": sorted(excel_abogados)}))
    excel_deps = {a.dependencia_canonical for a in db_actuaciones if a.dependencia_canonical}
    if (case.dependencia_canonical and excel_deps
            and case.dependencia_canonical not in excel_deps):
        out.append(Finding("R12", "dependencia_canonical", "WARN",
                           f"dependencia_canonical DB={case.dependencia_canonical!r} discrepa con Excel={sorted(excel_deps)}"))
    return out


RULES: dict[str, Callable[..., list[Finding]]] = {
    "R1": rule_R1, "R2": rule_R2, "R3": rule_R3, "R4": rule_R4,
    "R5": rule_R5, "R6": rule_R6, "R7": rule_R7, "R8": rule_R8,
    "R9": rule_R9, "R10": rule_R10, "R11": rule_R11, "R12": rule_R12,
}


def audit_case(case: Case, actuaciones: list[CaseActuacion]) -> list[Finding]:
    findings: list[Finding] = []
    for name, fn in RULES.items():
        try:
            if name == "R12":
                findings.extend(fn(case, actuaciones))
            else:
                findings.extend(fn(case))
        except Exception as e:
            findings.append(Finding(name, "_pipeline", "ERROR",
                                    f"Excepcion en regla {name}: {e}"))
    return findings


def evidence_doc(case: Case, db, field_name: str) -> Optional[dict]:
    """Devuelve filename y offset de un doc relevante para el campo (cuando aplica)."""
    docs = db.query(Document).filter(Document.case_id == case.id).limit(20).all()
    for d in docs:
        if d.extracted_text and getattr(case, field_name, None):
            v = str(getattr(case, field_name))[:30]
            idx = d.extracted_text.find(v)
            if idx >= 0:
                return {"file_path": d.file_path, "offset": idx, "snippet": d.extracted_text[max(0, idx-40):idx+80]}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", help="Solo correr una regla (ej R1)")
    ap.add_argument("--case", type=int, help="Solo un case_id")
    ap.add_argument("--no-evidence", action="store_true", help="Skip lookup de evidencia documental")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Case).filter(Case.processing_status != "DUPLICATE_MERGED")
        if args.case:
            q = q.filter(Case.id == args.case)
        cases = q.all()
        print(f"Auditando {len(cases)} cases...")

        actuaciones_by_rad = {}
        for a in db.query(CaseActuacion).filter(CaseActuacion.radicado_corto.isnot(None)).all():
            actuaciones_by_rad.setdefault(a.radicado_corto, []).append(a)

        report: dict[str, Any] = {
            "generated_at": datetime.utcnow().isoformat(),
            "cases_audited": len(cases),
            "cases": [],
        }
        rule_counter: Counter[str] = Counter()
        severity_counter: Counter[str] = Counter()
        cases_with_findings = 0

        for c in cases:
            rad_corto = ""
            if c.folder_name:
                m = re.match(r"^(20\d{2})-(\d{4,5})", c.folder_name)
                if m:
                    rad_corto = f"{m.group(1)}-{m.group(2).zfill(5)}"
            actuaciones = actuaciones_by_rad.get(rad_corto, [])
            findings = audit_case(c, actuaciones)
            if args.rule:
                findings = [f for f in findings if f.rule == args.rule]
            if not findings:
                continue
            cases_with_findings += 1
            for f in findings:
                rule_counter[f.rule] += 1
                severity_counter[f.severity] += 1
                if not args.no_evidence and f.severity == "ERROR" and f.field not in ("_pipeline",):
                    ev = evidence_doc(c, db, f.field)
                    if ev:
                        f.evidence["doc_evidence"] = ev
            report["cases"].append({
                "case_id": c.id, "folder_name": c.folder_name,
                "rad_corto": rad_corto, "tipo": c.tipo_actuacion,
                "n_findings": len(findings),
                "findings": [asdict(f) for f in findings],
            })

        report["summary"] = {
            "cases_with_findings": cases_with_findings,
            "by_rule": dict(rule_counter),
            "by_severity": dict(severity_counter),
            "total_findings": sum(rule_counter.values()),
        }

        EXPORTS.mkdir(parents=True, exist_ok=True)
        json_path = EXPORTS / "audit_report.json"
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"\n[OK] Reporte JSON: {json_path}")

        # CSV resumen: matriz caso x regla
        csv_path = EXPORTS / "audit_summary.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fp:
            w = csv.writer(fp)
            w.writerow(["case_id", "folder_name", "tipo", "n_findings"] + sorted(RULES.keys()))
            for entry in report["cases"]:
                row_counts = Counter(f["rule"] for f in entry["findings"])
                w.writerow([entry["case_id"], entry["folder_name"], entry["tipo"], entry["n_findings"]]
                           + [row_counts.get(r, 0) for r in sorted(RULES.keys())])
        print(f"[OK] Resumen CSV: {csv_path}")

        print(f"\n=== RESUMEN ===")
        print(f"Cases con findings: {cases_with_findings}/{len(cases)}")
        print(f"Total findings: {sum(rule_counter.values())}")
        print(f"Por severidad: {dict(severity_counter)}")
        print(f"Por regla:")
        for r in sorted(rule_counter.keys()):
            print(f"  {r}: {rule_counter[r]}")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
