"""Generador XLSX de auditoria (v8.3) — 4 hojas.

Hoja 1: Cuadro 28 campos
Hoja 2: Confianza (band por celda con formato condicional)
Hoja 3: Findings de auditoria (caso x regla)
Hoja 4: Resumen ejecutivo (KPIs)

Uso desde router:
    from backend.reports.export_audit import generate_audit_xlsx
    generate_audit_xlsx(db, output_path)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from backend.core.time import utcnow
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from backend.database.models import Case, CaseActuacion

# Reusar reglas del auditor
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


HEADER_FILL = PatternFill("solid", fgColor="2E5C3E")
HEADER_FONT = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
THIN = Side(border_style="thin", color="BBBBBB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BAND_FILLS = {
    "OK": PatternFill("solid", fgColor="DCFCE7"),
    "REVISAR": PatternFill("solid", fgColor="FEF3C7"),
    "BAJO": PatternFill("solid", fgColor="FEE2E2"),
}


def _fields_columns() -> list[tuple[str, str]]:
    """Lista (csv_col, attr) preservando orden CSV."""
    return [(csv_col, attr) for csv_col, attr in Case.CSV_FIELD_MAP.items()]


def _safe(v) -> str:
    return str(v) if v not in (None, "") else ""


def _setup_header(ws, headers: list[str]):
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.freeze_panes = "B2"


def _generate_cuadro_sheet(wb: Workbook, cases: list[Case]):
    ws = wb.create_sheet("Cuadro")
    cols = _fields_columns()
    headers = ["case_id", "folder_name", "tipo"] + [c[0] for c in cols]
    _setup_header(ws, headers)
    for row_idx, c in enumerate(cases, 2):
        ws.cell(row=row_idx, column=1, value=c.id)
        ws.cell(row=row_idx, column=2, value=c.folder_name or "")
        ws.cell(row=row_idx, column=3, value=c.tipo_actuacion or "TUTELA")
        for col_idx, (_csv, attr) in enumerate(cols, 4):
            ws.cell(row=row_idx, column=col_idx, value=_safe(getattr(c, attr, "")))
    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 18
    ws.column_dimensions["B"].width = 35


def _generate_confidence_sheet(wb: Workbook, cases: list[Case]):
    """Hoja paralela a Cuadro pero con bandas de confianza por celda."""
    ws = wb.create_sheet("Confianza")
    cols = _fields_columns()
    headers = ["case_id", "folder_name"] + [c[0] for c in cols]
    _setup_header(ws, headers)
    for row_idx, c in enumerate(cases, 2):
        ws.cell(row=row_idx, column=1, value=c.id)
        ws.cell(row=row_idx, column=2, value=c.folder_name or "")
        confidences: dict = {}
        if c.field_confidences_json:
            try:
                confidences = json.loads(c.field_confidences_json)
            except json.JSONDecodeError:
                confidences = {}
        for col_idx, (_csv, attr) in enumerate(cols, 3):
            band = (confidences.get(attr) or {}).get("band", "")
            cell = ws.cell(row=row_idx, column=col_idx, value=band)
            if band in BAND_FILLS:
                cell.fill = BAND_FILLS[band]
                cell.alignment = Alignment(horizontal="center")
    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 12
    ws.column_dimensions["B"].width = 35


def _audit_one_case(case: Case, actuaciones_by_rad: dict) -> list[dict]:
    """Aplica las 12 reglas y devuelve lista de findings."""
    import audit_cases as ac  # type: ignore

    rad_corto = ""
    if case.folder_name:
        m = re.match(r"^(20\d{2})-(\d{4,5})", case.folder_name)
        if m:
            rad_corto = f"{m.group(1)}-{m.group(2).zfill(5)}"
    actuaciones = actuaciones_by_rad.get(rad_corto, [])
    findings = ac.audit_case(case, actuaciones)
    return [
        {"rule": f.rule, "field": f.field, "severity": f.severity, "message": f.message}
        for f in findings
    ]


def _generate_findings_sheet(wb: Workbook, cases: list[Case], actuaciones_by_rad: dict):
    ws = wb.create_sheet("Findings")
    headers = ["case_id", "folder_name", "rule", "field", "severity", "message"]
    _setup_header(ws, headers)
    severity_fills = {
        "ERROR": PatternFill("solid", fgColor="FECACA"),
        "WARN": PatternFill("solid", fgColor="FED7AA"),
        "INFO": PatternFill("solid", fgColor="E0E7FF"),
    }
    row_idx = 2
    for c in cases:
        findings = _audit_one_case(c, actuaciones_by_rad)
        for f in findings:
            ws.cell(row=row_idx, column=1, value=c.id)
            ws.cell(row=row_idx, column=2, value=c.folder_name or "")
            ws.cell(row=row_idx, column=3, value=f["rule"])
            ws.cell(row=row_idx, column=4, value=f["field"])
            sev_cell = ws.cell(row=row_idx, column=5, value=f["severity"])
            if f["severity"] in severity_fills:
                sev_cell.fill = severity_fills[f["severity"]]
            ws.cell(row=row_idx, column=6, value=f["message"])
            row_idx += 1
    for col, w in zip("ABCDEF", (10, 35, 8, 22, 10, 80)):
        ws.column_dimensions[col].width = w


def _generate_summary_sheet(wb: Workbook, cases: list[Case], db: Session):
    """Hoja resumen con KPIs ejecutivos."""
    from backend.services.executive_kpis import executive_dashboard
    ws = wb.create_sheet("Resumen")
    kpis = executive_dashboard(db)

    title = ws.cell(row=1, column=1, value="AUDITORIA INTEGRAL — TUTELAS GOBERNACION DE SANTANDER")
    title.font = Font(name="Calibri", bold=True, size=16, color="2E5C3E")
    ws.merge_cells("A1:F1")
    ws.cell(row=2, column=1, value=f"Generado: {utcnow().isoformat(timespec='seconds')}")

    rows = [
        ("Total cases activos", kpis["summary"]["total_cases"]),
        ("Compliance rate", f"{int(kpis['summary']['compliance_rate'] * 100)}%"),
        ("Casos críticos (rojos)", kpis["summary"]["casos_criticos_rojos"]),
        ("Casos en sanción", kpis["summary"]["casos_en_sancion"]),
        ("Casos con incidente activo", kpis["summary"]["casos_con_incidente_activo"]),
        ("", ""),
        ("--- PIPELINE FUNNEL ---", ""),
    ]
    for stage in kpis.get("pipeline_funnel", []):
        rows.append((stage["label"], f"{stage['count']} ({stage['pct_total']}%)"))
    rows.append(("", ""))
    rows.append(("--- FALLOS 1RA INSTANCIA ---", ""))
    for f in kpis.get("fallos_distribution", []):
        rows.append((f["sentido"], f"{f['count']} ({f['pct']}%)"))
    rows.append(("", ""))
    rows.append(("--- FALLOS 2DA INSTANCIA ---", ""))
    for f in kpis.get("fallos_2nd_distribution", []):
        rows.append((f["sentido"], f"{f['count']} ({f['pct']}%)"))
    rows.append(("", ""))
    rows.append(("--- CUMPLIMIENTO ---", ""))
    cp = kpis.get("compliance_plazos", {})
    rows.append(("Cumplidos a tiempo", cp.get("concedidas_cumplidas_a_tiempo", 0)))
    rows.append(("Pendientes de cumplimiento (>10d)", cp.get("concedidas_pendientes_cumplimiento", 0)))
    rows.append(("En sancion", cp.get("en_sancion", 0)))

    for r_idx, (k, v) in enumerate(rows, 4):
        a = ws.cell(row=r_idx, column=1, value=k)
        b = ws.cell(row=r_idx, column=2, value=v)
        if str(k).startswith("---"):
            a.font = Font(bold=True, color="2E5C3E")
        elif k:
            a.font = Font(bold=False)
            b.font = Font(bold=True)
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 22


def generate_audit_xlsx(db: Session, output_path: str) -> dict:
    """Genera el XLSX de auditoria con 4 hojas y devuelve metadata."""
    cases = (
        db.query(Case)
        .filter(Case.processing_status != "DUPLICATE_MERGED")
        .order_by(Case.id.desc())
        .all()
    )
    actuaciones_by_rad: dict[str, list[CaseActuacion]] = {}
    for a in db.query(CaseActuacion).filter(CaseActuacion.radicado_corto.isnot(None)).all():
        actuaciones_by_rad.setdefault(a.radicado_corto, []).append(a)

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    _generate_summary_sheet(wb, cases, db)
    _generate_cuadro_sheet(wb, cases)
    _generate_confidence_sheet(wb, cases)
    _generate_findings_sheet(wb, cases, actuaciones_by_rad)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return {
        "path": output_path,
        "cases": len(cases),
        "sheets": ["Resumen", "Cuadro", "Confianza", "Findings"],
    }
