#!/usr/bin/env python3
"""Aplica las correcciones manuales (leídas por Claude desde los PDFs) sobre los
XLSX de fallos y desacatos. NO toca la DB. Celdas modificadas se resaltan en
amarillo; filas nuevas (cases no presentes) se agregan al final con resaltado
verde claro.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
EXPORTS = ROOT / "data" / "exports"

FALLOS_XLSX = EXPORTS / "INFORME_FALLOS_2026-05-19.xlsx"
DESAC_XLSX = EXPORTS / "INFORME_DESACATOS_2026-05-19.xlsx"

# Estilos
YELLOW = PatternFill("solid", fgColor="FFF2CC")      # Celda corregida
GREEN_ROW = PatternFill("solid", fgColor="E2EFDA")    # Fila nueva agregada
THIN = Side(border_style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

# Headers exactos del XLSX original (sin tocar)
FALLOS_HEADERS = [
    "#", "RAD. CORTO", "RAD. 23 DÍGITOS", "ACCIONANTE", "ACCIONADO(S)", "CIUDAD",
    "DEPENDENCIA", "ABOGADO RESPONSABLE",
    "JUZGADO 1ª", "FECHA FALLO 1ª", "SENTIDO FALLO 1ª",
    "IMPUGNACIÓN", "QUIÉN IMPUGNÓ", "JUZGADO 2ª", "FECHA FALLO 2ª", "SENTIDO FALLO 2ª",
    "ESTADO",
]
DESAC_HEADERS = [
    "#", "RAD. CORTO", "RAD. 23 DÍGITOS", "ACCIONANTE", "DEPENDENCIA", "ABOGADO RESPONSABLE",
    "SENTIDO FALLO 1ª", "FECHA FALLO 1ª",
    "INC. 1", "FECHA APERT. 1", "RESP. DESACATO 1", "ABOG. INC. 1", "DECISIÓN INC. 1",
    "INC. 2", "FECHA APERT. 2", "RESP. DESACATO 2", "ABOG. INC. 2", "DECISIÓN INC. 2",
    "INC. 3", "FECHA APERT. 3", "RESP. DESACATO 3", "ABOG. INC. 3", "DECISIÓN INC. 3",
    "ESTADO",
]


# =========================================================================
# CORRECCIONES (resultado de lectura manual de PDFs por Claude — 2026-05-19)
# =========================================================================

# ---- Actualizaciones a filas existentes en FALLOS ----
# {case_id: {col_name: new_value}}
FALLOS_PATCH = {
    # GAP A - sentencia 2da no extraída (campos 2da + ajuste impugnación si aplica)
    20: {  # DENNIS ROCÍO MENESES — sent 2da decretó NULIDAD
        "IMPUGNACIÓN": "SI",
        "QUIÉN IMPUGNÓ": "ACCIONANTE",
        "JUZGADO 2ª": "JUZGADO SÉPTIMO PENAL DEL CIRCUITO DE CONOCIMIENTO BUCARAMANGA",
        "FECHA FALLO 2ª": "25/03/2026",
        "SENTIDO FALLO 2ª": "NULIDAD",
    },
    66: {  # DIANA GANCINO / LAURA MARCELA ALARCON
        "JUZGADO 2ª": "JUZGADO SEGUNDO PROMISCUO DE FAMILIA DE SAN GIL",
        "FECHA FALLO 2ª": "22/04/2026",
        "SENTIDO FALLO 2ª": "CONFIRMA",
    },
    73: {  # HELVIA LUCIA CAMACHO
        "JUZGADO 2ª": "JUZGADO SEGUNDO CIVIL DEL CIRCUITO SAN GIL",
        "FECHA FALLO 2ª": "18/03/2026",
        "SENTIDO FALLO 2ª": "CONFIRMA",
    },
    104: {  # PERSONERÍA BETULIA
        "JUZGADO 2ª": "JUZGADO OCTAVO CIVIL DEL CIRCUITO BUCARAMANGA",
        "FECHA FALLO 2ª": "17/04/2026",
        "SENTIDO FALLO 2ª": "CONFIRMA",
    },
    210: {  # CONSEJO DE PADRES SEDE A FALTRIQUERA
        "JUZGADO 2ª": "JUZGADO SEXTO CIVIL DEL CIRCUITO BUCARAMANGA",
        "FECHA FALLO 2ª": "29/04/2026",
        "SENTIDO FALLO 2ª": "MODIFICA",
    },
    223: {  # GLADYS GIRALDO — el accionado (Salud Total EPS) impugnó
        "IMPUGNACIÓN": "SI",
        "QUIÉN IMPUGNÓ": "ACCIONADO (Salud Total EPS)",
        "JUZGADO 2ª": "JUZGADO SEXTO CIVIL DEL CIRCUITO BUCARAMANGA",
        "FECHA FALLO 2ª": "05/05/2026",
        "SENTIDO FALLO 2ª": "MODIFICA",
    },
    380: {  # LEIDY DIANA BLANCO MÁRQUEZ
        "IMPUGNACIÓN": "SI",
        "QUIÉN IMPUGNÓ": "ACCIONANTE",
        "JUZGADO 2ª": "TRIBUNAL ADMINISTRATIVO DE SANTANDER",
        "FECHA FALLO 2ª": "09/06/2025",
        "SENTIDO FALLO 2ª": "REVOCA",
    },
    # GAP B - impugnación marcada NO pero hay doc de impugnación
    161: {"IMPUGNACIÓN": "SI", "QUIÉN IMPUGNÓ": "ACCIONANTE"},   # MARIA MONICA SUAREZ
    208: {"IMPUGNACIÓN": "SI", "QUIÉN IMPUGNÓ": "ACCIONANTE Y ACCIONADO"},  # JUAN BAUTISTA SEPULVEDA
    242: {"IMPUGNACIÓN": "SI", "QUIÉN IMPUGNÓ": "ACCIONADO (Sec. Educación Floridablanca)"},  # ALBA GONZALEZ
    302: {"IMPUGNACIÓN": "SI", "QUIÉN IMPUGNÓ": "ACCIONADO"},   # JAVIER MARTINEZ
    304: {"IMPUGNACIÓN": "SI", "QUIÉN IMPUGNÓ": "ACCIONANTE"},  # AYDE PEREZ MURILLO
    347: {"IMPUGNACIÓN": "SI", "QUIÉN IMPUGNÓ": "(revisar — FOREST)"},  # SILVIA PAOLA LUNA
}


# ---- Filas nuevas en FALLOS (GAP E — cases con sent 1ra no extraída que NO están en el informe) ----
FALLOS_NEW_ROWS = [
    # (case_id, valores por columna en orden de FALLOS_HEADERS, sin el #)
    {
        "RAD. CORTO": "2026-00083",
        "RAD. 23 DÍGITOS": "(no en DB)",
        "ACCIONANTE": "SONIA MARCELA PAEZ SUAREZ",
        "ACCIONADO(S)": "SALUD TOTAL EPS / SECRETARÍA DE EDUCACIÓN DE PIEDECUESTA",
        "CIUDAD": "PIEDECUESTA",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO TRECE CIVIL MUNICIPAL DE BUCARAMANGA",
        "FECHA FALLO 1ª": "20/02/2026",
        "SENTIDO FALLO 1ª": "NIEGA",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00012",
        "RAD. 23 DÍGITOS": "(no en DB)",
        "ACCIONANTE": "MARIA LAURA SERRANO RANGEL (en repr. menor M.I.F.S.)",
        "ACCIONADO(S)": "ITAD MOGOTES / SECRETARÍA EDUCACIÓN SANTANDER",
        "CIUDAD": "MOGOTES",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO PROMISCUO MUNICIPAL DE MOGOTES",
        "FECHA FALLO 1ª": "10/02/2026",
        "SENTIDO FALLO 1ª": "NIEGA",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00034",
        "RAD. 23 DÍGITOS": "68001400902720260003400",
        "ACCIONANTE": "ANGÉLICA MAYERLY VELASCO MÉNDEZ",
        "ACCIONADO(S)": "SECRETARÍA DE EDUCACIÓN DEL DEPARTAMENTO DE SANTANDER",
        "CIUDAD": "BUCARAMANGA",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO 27 PENAL MUNICIPAL CON FUNCION DE CONOCIMIENTO BUCARAMANGA",
        "FECHA FALLO 1ª": "06/03/2026",
        "SENTIDO FALLO 1ª": "NIEGA",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00059",
        "RAD. 23 DÍGITOS": "68001333300620260005900",
        "ACCIONANTE": "DIANA LORENA RAMOS LOZANO (en repr. menor M.V.L.R.)",
        "ACCIONADO(S)": "SECRETARÍA EDUCACIÓN DEPARTAMENTAL SANTANDER",
        "CIUDAD": "EL SOCORRO",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO SÉPTIMO PENAL MUNICIPAL DE CONOCIMIENTO DE FLORENCIA CAQUETÁ",
        "FECHA FALLO 1ª": "22/04/2026",
        "SENTIDO FALLO 1ª": "CARENCIA_OBJETO",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00078",
        "RAD. 23 DÍGITOS": "68615408900220260007800",
        "ACCIONANTE": "DIANA MARÍA MENDOZA HERNÁNDEZ (agente oficiosa 105 NNA Col. Llano de Palmas)",
        "ACCIONADO(S)": "ALCALDÍA RIONEGRO / SEC. EDUCACIÓN SANTANDER / GOBERNACIÓN",
        "CIUDAD": "RIONEGRO",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO PROMISCUO MUNICIPAL DE RIONEGRO SANTANDER",
        "FECHA FALLO 1ª": "25/03/2026",
        "SENTIDO FALLO 1ª": "CONCEDE",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00072",
        "RAD. 23 DÍGITOS": "68001408800820260007200",
        "ACCIONANTE": "EDGAR MAURICIO GALVIS VELÁSQUEZ",
        "ACCIONADO(S)": "GOBERNACIÓN SANTANDER / SECRETARÍA EDUCACIÓN DEPARTAMENTAL",
        "CIUDAD": "BUCARAMANGA",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO OCTAVO PENAL MUNICIPAL CON FUNCIONES DE CONTROL DE GARANTÍAS BUCARAMANGA",
        "FECHA FALLO 1ª": "30/04/2026",
        "SENTIDO FALLO 1ª": "IMPROCEDENTE",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00322",
        "RAD. 23 DÍGITOS": "68001400301620260032200",
        "ACCIONANTE": "SINDY NORELLY ACOSTA SÁNCHEZ",
        "ACCIONADO(S)": "GOBERNACIÓN SANTANDER / SECRETARÍA DE EDUCACIÓN",
        "CIUDAD": "BUCARAMANGA",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO DIECISÉIS CIVIL MUNICIPAL DE BUCARAMANGA",
        "FECHA FALLO 1ª": "07/05/2026",
        "SENTIDO FALLO 1ª": "IMPROCEDENTE",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00226",
        "RAD. 23 DÍGITOS": "68001311000420260022600",
        "ACCIONANTE": "MARÍA ANGÉLICA GÓMEZ RUEDA (en repr. menor M.A.L.G.)",
        "ACCIONADO(S)": "NUEVA EPS / SECRETARÍA DE EDUCACIÓN FLORIDABLANCA",
        "CIUDAD": "FLORIDABLANCA",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO CUARTO DE FAMILIA DE BUCARAMANGA",
        "FECHA FALLO 1ª": "11/05/2026",
        "SENTIDO FALLO 1ª": "CONCEDE",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00065",
        "RAD. 23 DÍGITOS": "68235408900120260006500",
        "ACCIONANTE": "LINA ROCÍO DUARTE RODRÍGUEZ",
        "ACCIONADO(S)": "SECRETARÍA DE EDUCACIÓN DEPARTAMENTAL DE SANTANDER",
        "CIUDAD": "EL CARMEN DE CHUCURÍ",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO PROMISCUO MUNICIPAL EL CARMEN DE CHUCURÍ",
        "FECHA FALLO 1ª": "12/05/2026",
        "SENTIDO FALLO 1ª": "CARENCIA_OBJETO",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00137",
        "RAD. 23 DÍGITOS": "68001310300520260013700",
        "ACCIONANTE": "SALOMÓN CONTRERAS SÁNCHEZ y YOLANDA BERMÚDEZ TUTASAURA",
        "ACCIONADO(S)": "MEN / FOMAG / FIDUPREVISORA / SECRETARÍA EDUCACIÓN SANTANDER",
        "CIUDAD": "BUCARAMANGA",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO QUINTO CIVIL DEL CIRCUITO DE BUCARAMANGA",
        "FECHA FALLO 1ª": "11/05/2026",
        "SENTIDO FALLO 1ª": "NIEGA",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00024",
        "RAD. 23 DÍGITOS": "68296408900120260002400",
        "ACCIONANTE": "PATRICIA YAMILE SOLANO VELANDIA",
        "ACCIONADO(S)": "GOBERNACIÓN SANTANDER / SECRETARÍA EDUCACIÓN SANTANDER",
        "CIUDAD": "GALÁN",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO PROMISCUO MUNICIPAL DE GALÁN",
        "FECHA FALLO 1ª": "12/05/2026",
        "SENTIDO FALLO 1ª": "CARENCIA_OBJETO",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00028",
        "RAD. 23 DÍGITOS": "68344408900120260002800",
        "ACCIONANTE": "DARÍANY MAURICIO AMOROCHO CALA",
        "ACCIONADO(S)": "SECRETARÍA DE EDUCACIÓN SANTANDER",
        "CIUDAD": "EL HATO",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO PROMISCUO MUNICIPAL HATO SANTANDER",
        "FECHA FALLO 1ª": "05/05/2026",
        "SENTIDO FALLO 1ª": "CONCEDE",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00007",
        "RAD. 23 DÍGITOS": "(no en DB)",
        "ACCIONANTE": "CAROLINA MARTÍNEZ JIMÉNEZ",
        "ACCIONADO(S)": "GOBERNACIÓN DE SANTANDER",
        "CIUDAD": "CIMITARRA",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO SEGUNDO PROMISCUO MUNICIPAL DE CIMITARRA",
        "FECHA FALLO 1ª": "29/12/2025",
        "SENTIDO FALLO 1ª": "CONCEDE",
        "IMPUGNACIÓN": "SI",
        "QUIÉN IMPUGNÓ": "ACCIONADO (Sec. Educación Santander)",
        "JUZGADO 2ª": "JUZGADO PRIMERO CIVIL DEL CIRCUITO DE CIMITARRA",
        "FECHA FALLO 2ª": "06/02/2026",
        "SENTIDO FALLO 2ª": "CONFIRMA",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2025-00046",
        "RAD. 23 DÍGITOS": "(no en DB)",
        "ACCIONANTE": "GILMA LUCIA HERNANDEZ BERNAL",
        "ACCIONADO(S)": "SECRETARÍA DE EDUCACIÓN SANTANDER / GOBERNACIÓN / MEN / FUNDAEC",
        "CIUDAD": "HATO",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "JUZGADO 1ª": "JUZGADO PROMISCUO MUNICIPAL HATO SANTANDER",
        "FECHA FALLO 1ª": "05/11/2025",
        "SENTIDO FALLO 1ª": "CONCEDE",
        "IMPUGNACIÓN": "(sin dato)", "QUIÉN IMPUGNÓ": "",
        "JUZGADO 2ª": "", "FECHA FALLO 2ª": "", "SENTIDO FALLO 2ª": "",
        "ESTADO": "ACTIVO",
    },
]


# ---- DESACATOS — actualizar filas existentes (case ya estaba en el informe pero falta marcar incidente=SI) ----
DESAC_PATCH = {
    28: {"INC. 1": "SI", "FECHA APERT. 1": "09/02/2026",
         "RESP. DESACATO 1": "YANETH KARINA ARAUJO MAESTRE (Secretaria de Educación Santander)"},
    200: {"INC. 1": "SI", "FECHA APERT. 1": "(ver pdf — abril/mayo 2026)",
          "RESP. DESACATO 1": "GOBERNACIÓN DE SANTANDER - SECRETARÍA DE EDUCACIÓN"},
    280: {"INC. 1": "SI", "FECHA APERT. 1": "(abril 2026)",
          "RESP. DESACATO 1": "SECRETARÍA DE EDUCACIÓN DE SANTANDER",
          "DECISIÓN INC. 1": "SANCIONA (auto de sanción en disco)"},
    281: {"INC. 1": "SI", "FECHA APERT. 1": "20/04/2026",
          "RESP. DESACATO 1": "YANETH KARINA ARAUJO MAESTRE (Secretaria de Educación Santander)",
          "DECISIÓN INC. 1": "SANCIONA (auto de sanción en disco)"},
    307: {"INC. 1": "SI", "FECHA APERT. 1": "06/04/2026",
          "RESP. DESACATO 1": "SECRETARÍA EDUCACIÓN DEPARTAMENTAL DE SANTANDER"},
}

# ---- DESACATOS — filas nuevas (cases NO presentes) ----
DESAC_NEW_ROWS = [
    {
        "RAD. CORTO": "2026-00015",
        "RAD. 23 DÍGITOS": "68092408900120260001500",
        "ACCIONANTE": "PERSONERÍA MUNICIPAL DE BETULIA",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "SENTIDO FALLO 1ª": "CONCEDE",
        "FECHA FALLO 1ª": "02/03/2026",
        "INC. 1": "SI",
        "FECHA APERT. 1": "08/05/2026",
        "RESP. DESACATO 1": "SECRETARÍA DE EDUCACIÓN DEPARTAMENTAL DE SANTANDER",
        "ABOG. INC. 1": "",
        "DECISIÓN INC. 1": "EN_TRAMITE",
        "ESTADO": "ACTIVO",
    },
    {
        "RAD. CORTO": "2026-00131",
        "RAD. 23 DÍGITOS": "68001400300620260013100",
        "ACCIONANTE": "LEIDY QUIROZ MEJÍA",
        "DEPENDENCIA": "",
        "ABOGADO RESPONSABLE": "",
        "SENTIDO FALLO 1ª": "IMPROCEDENTE",
        "FECHA FALLO 1ª": "05/03/2026",
        "INC. 1": "SI",
        "FECHA APERT. 1": "04/05/2026",
        "RESP. DESACATO 1": "SECRETARÍA DE EDUCACIÓN DE SANTANDER",
        "ABOG. INC. 1": "",
        "DECISIÓN INC. 1": "EN_TRAMITE",
        "ESTADO": "ACTIVO",
    },
]


# =========================================================================
# Implementación
# =========================================================================

def find_data_block(ws, headers):
    """Encuentra fila de headers y devuelve (header_row, col_index_map, first_data_row, last_data_row)."""
    for r in range(1, 8):
        for c in range(1, ws.max_column + 1):
            if ws.cell(row=r, column=c).value == headers[0]:
                hr = r
                col_idx = {}
                for cc in range(1, ws.max_column + 1):
                    v = ws.cell(row=hr, column=cc).value
                    if v in headers:
                        col_idx[v] = cc
                return hr, col_idx, hr + 1, ws.max_row
    raise RuntimeError("No se encontró fila de headers")


def load_case_id_map(con):
    """Devuelve {(rad23 or accionante normalizado): case_id} para identificar filas en el XLSX."""
    m = {}
    for r in con.execute("SELECT id, radicado_23_digitos, accionante, folder_name FROM cases"):
        rid, rad, acc, fld = r
        if rad: m[("rad", rad.strip())] = rid
        if acc: m[("acc", (acc or "").strip().upper())] = rid
        if fld: m[("fld", (fld or "").strip().upper())] = rid
    return m


def row_to_case_id(ws, col_idx, row, lookup):
    rad = ws.cell(row=row, column=col_idx.get("RAD. 23 DÍGITOS", 0)).value if "RAD. 23 DÍGITOS" in col_idx else None
    if rad and ("rad", str(rad).strip()) in lookup:
        return lookup[("rad", str(rad).strip())]
    acc = ws.cell(row=row, column=col_idx.get("ACCIONANTE", 0)).value if "ACCIONANTE" in col_idx else None
    if acc and ("acc", str(acc).strip().upper()) in lookup:
        return lookup[("acc", str(acc).strip().upper())]
    return None


def apply_patch_xlsx(xlsx_path, patch_map, new_rows, headers, sheet_name, lookup):
    wb = load_workbook(xlsx_path)
    ws = wb[sheet_name]
    hr, col_idx, dstart, dend = find_data_block(ws, headers)

    n_updated_cells = 0
    n_updated_rows = 0
    seen_case_ids = set()

    for row in range(dstart, dend + 1):
        cid = row_to_case_id(ws, col_idx, row, lookup)
        if cid is None:
            continue
        seen_case_ids.add(cid)
        if cid not in patch_map:
            continue
        for col_name, new_val in patch_map[cid].items():
            if col_name not in col_idx:
                continue
            cc = col_idx[col_name]
            cell = ws.cell(row=row, column=cc)
            cell.value = new_val
            cell.fill = YELLOW
            cell.alignment = WRAP
            cell.border = BORDER
            n_updated_cells += 1
        n_updated_rows += 1

    # Filas nuevas — agregar al final
    append_row = dend + 1
    # detectar el último # actual
    n_col = col_idx["#"]
    max_num = 0
    for row in range(dstart, dend + 1):
        v = ws.cell(row=row, column=n_col).value
        try:
            iv = int(v)
            if iv > max_num: max_num = iv
        except Exception:
            pass

    n_new = 0
    for nr in new_rows:
        max_num += 1
        # set #
        ws.cell(row=append_row, column=n_col, value=max_num)
        for col_name, val in nr.items():
            if col_name not in col_idx:
                continue
            cc = col_idx[col_name]
            ws.cell(row=append_row, column=cc, value=val)
        # styling para toda la fila
        for cc in range(1, len(headers) + 1):
            cell = ws.cell(row=append_row, column=cc)
            cell.fill = GREEN_ROW
            cell.alignment = WRAP
            cell.border = BORDER
        append_row += 1
        n_new += 1

    # Actualizar auto_filter para incluir las nuevas filas
    last_col_letter = ws.cell(row=hr, column=len(headers)).coordinate.rstrip("0123456789")
    ws.auto_filter.ref = f"A{hr}:{last_col_letter}{append_row - 1}"

    wb.save(xlsx_path)
    return n_updated_cells, n_updated_rows, n_new


def main():
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    lookup = load_case_id_map(con)

    print("== INFORME_FALLOS ==")
    nc, nr, nnew = apply_patch_xlsx(FALLOS_XLSX, FALLOS_PATCH, FALLOS_NEW_ROWS, FALLOS_HEADERS, "FALLOS", lookup)
    print(f"  celdas amarillas (correcciones): {nc} en {nr} filas")
    print(f"  filas nuevas verdes: {nnew}")

    print("== INFORME_DESACATOS ==")
    nc2, nr2, nnew2 = apply_patch_xlsx(DESAC_XLSX, DESAC_PATCH, DESAC_NEW_ROWS, DESAC_HEADERS, "DESACATOS", lookup)
    print(f"  celdas amarillas (correcciones): {nc2} en {nr2} filas")
    print(f"  filas nuevas verdes: {nnew2}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
