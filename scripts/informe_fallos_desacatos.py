#!/usr/bin/env python3
"""Genera dos informes ejecutivos XLSX directo desde la DB (sin pasar por la UI).

  scripts/informe_fallos_desacatos.py
    -> data/exports/INFORME_FALLOS_<YYYY-MM-DD>.xlsx
    -> data/exports/INFORME_DESACATOS_<YYYY-MM-DD>.xlsx

Para entregar hoy mismo sin depender del frontend/backend.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
EXPORTS = ROOT / "data" / "exports"
EXPORTS.mkdir(parents=True, exist_ok=True)

TODAY = date.today().isoformat()

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
TITLE_FONT = Font(bold=True, size=14, color="1F4E78")
THIN = Side(border_style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
ZEBRA = PatternFill("solid", fgColor="F2F2F2")

RAD_CORTO_RE = re.compile(r"\b(20\d{2}-\d{4,5})\b")


def rad_corto(folder_name: str | None, rad23: str | None) -> str:
    """Deriva el radicado corto YYYY-NNNNN desde folder_name o rad23."""
    for src in (folder_name, rad23):
        if not src:
            continue
        m = RAD_CORTO_RE.search(str(src))
        if m:
            return m.group(1)
    # último intento: tomar año + 5 dígitos del medio del rad23 (formato Rama Judicial)
    if rad23:
        digits = re.sub(r"\D", "", rad23)
        if len(digits) >= 23:
            # rad23 colombiano: posiciones 12-15 año, 16-19 consecutivo
            year = digits[12:16]
            cons = digits[16:21]
            if year.startswith("20") and cons:
                return f"{year}-{cons.zfill(5)}"
    return ""


def fetchall(con: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    return list(con.execute(sql))


def set_header(ws, headers, row_idx=1):
    for i, h in enumerate(headers, start=1):
        cell = ws.cell(row=row_idx, column=i, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        cell.border = BORDER
    ws.row_dimensions[row_idx].height = 32


def autosize(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def write_row(ws, row_idx, values, zebra=False):
    for j, v in enumerate(values, start=1):
        cell = ws.cell(row=row_idx, column=j, value=v)
        cell.border = BORDER
        cell.alignment = WRAP
        if zebra:
            cell.fill = ZEBRA


def title_block(ws, title: str, subtitle: str, n_cols: int) -> int:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
    ws.cell(row=1, column=1, value=title).font = TITLE_FONT
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n_cols)
    sc = ws.cell(row=2, column=1, value=subtitle)
    sc.font = Font(italic=True, color="595959")
    sc.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 16
    return 3  # next row index


# ---------- INFORME DE FALLOS ----------

FALLOS_HEADERS = [
    "#", "RAD. CORTO", "RAD. 23 DÍGITOS", "ACCIONANTE", "ACCIONADO(S)", "CIUDAD",
    "DEPENDENCIA", "ABOGADO RESPONSABLE",
    "JUZGADO 1ª", "FECHA FALLO 1ª", "SENTIDO FALLO 1ª",
    "IMPUGNACIÓN", "QUIÉN IMPUGNÓ", "JUZGADO 2ª", "FECHA FALLO 2ª", "SENTIDO FALLO 2ª",
    "ESTADO",
]
FALLOS_WIDTHS = [5, 14, 28, 32, 28, 14, 26, 26, 28, 14, 18, 14, 16, 28, 14, 18, 14]


def build_informe_fallos(con: sqlite3.Connection) -> Path:
    sql = """
    SELECT
        radicado_23_digitos, radicado_forest, folder_name,
        accionante, accionados, ciudad,
        COALESCE(NULLIF(TRIM(dependencia_canonical),''), oficina_responsable) AS dep,
        abogado_responsable, juzgado,
        fecha_fallo_1st, sentido_fallo_1st,
        impugnacion, quien_impugno, juzgado_2nd, fecha_fallo_2nd, sentido_fallo_2nd,
        estado
    FROM cases
    WHERE sentido_fallo_1st IS NOT NULL AND TRIM(sentido_fallo_1st) <> ''
      AND processing_status != 'DUPLICATE_MERGED'
    ORDER BY
        CASE WHEN fecha_fallo_1st IS NULL OR fecha_fallo_1st='' THEN 1 ELSE 0 END,
        fecha_fallo_1st DESC,
        accionante
    """
    rows = fetchall(con, sql)

    wb = Workbook()
    ws = wb.active
    ws.title = "FALLOS"
    next_row = title_block(
        ws,
        f"INFORME DE FALLOS DE TUTELA — Corte {TODAY}",
        f"Gobernación de Santander · Secretaría de Educación · Total: {len(rows)} casos con fallo de 1ª instancia",
        len(FALLOS_HEADERS),
    )
    set_header(ws, FALLOS_HEADERS, row_idx=next_row)
    autosize(ws, FALLOS_WIDTHS)
    ws.freeze_panes = ws.cell(row=next_row + 1, column=4)

    data_start = next_row + 1
    for i, r in enumerate(rows, start=1):
        zebra = (i % 2 == 0)
        rc = rad_corto(r["folder_name"], r["radicado_23_digitos"])
        write_row(ws, data_start + i - 1, [
            i, rc, r["radicado_23_digitos"] or "",
            r["accionante"] or "", r["accionados"] or "", r["ciudad"] or "",
            r["dep"] or "", r["abogado_responsable"] or "",
            r["juzgado"] or "", r["fecha_fallo_1st"] or "", r["sentido_fallo_1st"] or "",
            r["impugnacion"] or "", r["quien_impugno"] or "",
            r["juzgado_2nd"] or "", r["fecha_fallo_2nd"] or "", r["sentido_fallo_2nd"] or "",
            r["estado"] or "",
        ], zebra=zebra)

    last_row = data_start + len(rows) - 1
    ws.auto_filter.ref = f"A{data_start - 1}:{get_column_letter(len(FALLOS_HEADERS))}{max(last_row, data_start)}"

    # Hoja RESUMEN
    ws2 = wb.create_sheet("RESUMEN")
    ws2.column_dimensions["A"].width = 32
    ws2.column_dimensions["B"].width = 12
    ws2["A1"] = "INFORME DE FALLOS · RESUMEN"
    ws2["A1"].font = TITLE_FONT
    ws2["A3"] = "Sentido fallo 1ª"; ws2["B3"] = "Casos"
    for c in (ws2["A3"], ws2["B3"]):
        c.fill = HEADER_FILL; c.font = HEADER_FONT; c.alignment = CENTER
    row = 4
    for s, n in con.execute(
        "SELECT sentido_fallo_1st, COUNT(*) FROM cases "
        "WHERE sentido_fallo_1st IS NOT NULL AND processing_status != 'DUPLICATE_MERGED' "
        "GROUP BY sentido_fallo_1st ORDER BY 2 DESC"
    ):
        ws2.cell(row=row, column=1, value=s).border = BORDER
        ws2.cell(row=row, column=2, value=n).border = BORDER
        row += 1

    row += 2
    ws2.cell(row=row, column=1, value="Impugnación").fill = HEADER_FILL
    ws2.cell(row=row, column=1).font = HEADER_FONT
    ws2.cell(row=row, column=2, value="Casos").fill = HEADER_FILL
    ws2.cell(row=row, column=2).font = HEADER_FONT
    row += 1
    for s, n in con.execute(
        "SELECT impugnacion, COUNT(*) FROM cases "
        "WHERE sentido_fallo_1st IS NOT NULL AND processing_status != 'DUPLICATE_MERGED' "
        "GROUP BY impugnacion ORDER BY 2 DESC"
    ):
        ws2.cell(row=row, column=1, value=s or "(sin dato)").border = BORDER
        ws2.cell(row=row, column=2, value=n).border = BORDER
        row += 1

    out = EXPORTS / f"INFORME_FALLOS_{TODAY}.xlsx"
    wb.save(out)
    return out


# ---------- INFORME DE DESACATOS ----------

DESAC_HEADERS = [
    "#", "RAD. CORTO", "RAD. 23 DÍGITOS", "ACCIONANTE", "DEPENDENCIA", "ABOGADO RESPONSABLE",
    "SENTIDO FALLO 1ª", "FECHA FALLO 1ª",
    "INC. 1", "FECHA APERT. 1", "RESP. DESACATO 1", "ABOG. INC. 1", "DECISIÓN INC. 1",
    "INC. 2", "FECHA APERT. 2", "RESP. DESACATO 2", "ABOG. INC. 2", "DECISIÓN INC. 2",
    "INC. 3", "FECHA APERT. 3", "RESP. DESACATO 3", "ABOG. INC. 3", "DECISIÓN INC. 3",
    "ESTADO",
]
DESAC_WIDTHS = [5, 14, 28, 32, 26, 26, 18, 14,
                8, 14, 26, 26, 24,
                8, 14, 26, 26, 24,
                8, 14, 26, 26, 24,
                14]


def build_informe_desacatos(con: sqlite3.Connection) -> Path:
    sql = """
    SELECT
        radicado_23_digitos, folder_name,
        accionante,
        COALESCE(NULLIF(TRIM(dependencia_canonical),''), oficina_responsable) AS dep,
        abogado_responsable,
        sentido_fallo_1st, fecha_fallo_1st,
        incidente, fecha_apertura_incidente, responsable_desacato, abogado_incidente, decision_incidente,
        incidente_2, fecha_apertura_incidente_2, responsable_desacato_2, abogado_incidente_2, decision_incidente_2,
        incidente_3, fecha_apertura_incidente_3, responsable_desacato_3, abogado_incidente_3, decision_incidente_3,
        estado
    FROM cases
    WHERE processing_status != 'DUPLICATE_MERGED'
      AND (
            (UPPER(COALESCE(incidente,''))='SI')
         OR (fecha_apertura_incidente IS NOT NULL AND TRIM(fecha_apertura_incidente)<>'')
         OR (decision_incidente IS NOT NULL AND TRIM(decision_incidente)<>'')
         OR (responsable_desacato IS NOT NULL AND TRIM(responsable_desacato)<>'')
         OR (UPPER(COALESCE(incidente_2,''))='SI')
         OR (fecha_apertura_incidente_2 IS NOT NULL AND TRIM(fecha_apertura_incidente_2)<>'')
         OR (decision_incidente_2 IS NOT NULL AND TRIM(decision_incidente_2)<>'')
         OR (UPPER(COALESCE(incidente_3,''))='SI')
         OR (fecha_apertura_incidente_3 IS NOT NULL AND TRIM(fecha_apertura_incidente_3)<>'')
         OR (decision_incidente_3 IS NOT NULL AND TRIM(decision_incidente_3)<>'')
      )
    ORDER BY
        CASE WHEN fecha_apertura_incidente IS NULL OR fecha_apertura_incidente='' THEN 1 ELSE 0 END,
        fecha_apertura_incidente DESC,
        accionante
    """
    rows = fetchall(con, sql)

    wb = Workbook()
    ws = wb.active
    ws.title = "DESACATOS"
    next_row = title_block(
        ws,
        f"INFORME DE INCIDENTES DE DESACATO — Corte {TODAY}",
        f"Gobernación de Santander · Secretaría de Educación · Total: {len(rows)} casos con actividad de incidente",
        len(DESAC_HEADERS),
    )
    set_header(ws, DESAC_HEADERS, row_idx=next_row)
    autosize(ws, DESAC_WIDTHS)
    ws.freeze_panes = ws.cell(row=next_row + 1, column=4)

    data_start = next_row + 1
    for i, r in enumerate(rows, start=1):
        zebra = (i % 2 == 0)
        rc = rad_corto(r["folder_name"], r["radicado_23_digitos"])
        write_row(ws, data_start + i - 1, [
            i, rc, r["radicado_23_digitos"] or "",
            r["accionante"] or "", r["dep"] or "", r["abogado_responsable"] or "",
            r["sentido_fallo_1st"] or "", r["fecha_fallo_1st"] or "",
            r["incidente"] or "", r["fecha_apertura_incidente"] or "",
            r["responsable_desacato"] or "", r["abogado_incidente"] or "", r["decision_incidente"] or "",
            r["incidente_2"] or "", r["fecha_apertura_incidente_2"] or "",
            r["responsable_desacato_2"] or "", r["abogado_incidente_2"] or "", r["decision_incidente_2"] or "",
            r["incidente_3"] or "", r["fecha_apertura_incidente_3"] or "",
            r["responsable_desacato_3"] or "", r["abogado_incidente_3"] or "", r["decision_incidente_3"] or "",
            r["estado"] or "",
        ], zebra=zebra)

    last_row = data_start + len(rows) - 1
    ws.auto_filter.ref = f"A{data_start - 1}:{get_column_letter(len(DESAC_HEADERS))}{max(last_row, data_start)}"

    # Hoja RESUMEN
    ws2 = wb.create_sheet("RESUMEN")
    ws2.column_dimensions["A"].width = 40
    ws2.column_dimensions["B"].width = 12
    ws2["A1"] = "INFORME DE DESACATOS · RESUMEN"
    ws2["A1"].font = TITLE_FONT
    ws2["A3"] = "Decisión incidente (nivel 1)"; ws2["B3"] = "Casos"
    for c in (ws2["A3"], ws2["B3"]):
        c.fill = HEADER_FILL; c.font = HEADER_FONT; c.alignment = CENTER
    row = 4
    for s, n in con.execute(
        "SELECT decision_incidente, COUNT(*) FROM cases "
        "WHERE processing_status != 'DUPLICATE_MERGED' AND decision_incidente IS NOT NULL "
        "GROUP BY decision_incidente ORDER BY 2 DESC"
    ):
        ws2.cell(row=row, column=1, value=s).border = BORDER
        ws2.cell(row=row, column=2, value=n).border = BORDER
        row += 1
    out = EXPORTS / f"INFORME_DESACATOS_{TODAY}.xlsx"
    wb.save(out)
    return out


def main() -> int:
    if not DB.exists():
        print(f"DB no encontrada: {DB}", file=sys.stderr)
        return 1
    con = sqlite3.connect(str(DB))
    try:
        a = build_informe_fallos(con)
        b = build_informe_desacatos(con)
    finally:
        con.close()
    print(f"OK fallos   -> {a}")
    print(f"OK desacatos-> {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
