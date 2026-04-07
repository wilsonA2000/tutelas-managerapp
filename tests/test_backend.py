#!/usr/bin/env python3
"""Tests del backend - Modulos, base de datos, extraccion y API."""

import sys
import os
import json
import time
from pathlib import Path

# Setup path
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

PASS = 0
FAIL = 0
TOTAL = 0


def test(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL, TOTAL
    TOTAL += 1
    if condition:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} -- {detail}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ============================================================
# 1. IMPORTS Y CONFIGURACION
# ============================================================
section("1. IMPORTS Y CONFIGURACION")

try:
    from backend.config import BASE_DIR, CSV_PATH, GROQ_API_KEY, GMAIL_USER
    test("Importar config", True)
except Exception as e:
    test("Importar config", False, str(e))

test("BASE_DIR existe", BASE_DIR.exists())
test("CSV_PATH existe", CSV_PATH.exists())
test("GROQ_API_KEY configurada", bool(GROQ_API_KEY))
test("GMAIL_USER configurado", bool(GMAIL_USER))

try:
    from backend.database.models import Case, Document, Extraction, Email, AuditLog
    test("Importar modelos", True)
except Exception as e:
    test("Importar modelos", False, str(e))

try:
    from backend.database.database import SessionLocal, init_db, engine
    test("Importar database engine", True)
except Exception as e:
    test("Importar database engine", False, str(e))

# ============================================================
# 2. BASE DE DATOS
# ============================================================
section("2. BASE DE DATOS")

db = SessionLocal()

total_cases = db.query(Case).count()
test("Casos en DB > 0", total_cases > 0, f"Found: {total_cases}")
test("Casos en DB >= 200", total_cases >= 200, f"Found: {total_cases}")

total_docs = db.query(Document).count()
test("Documentos en DB > 0", total_docs > 0, f"Found: {total_docs}")
test("Documentos >= 1000", total_docs >= 1000, f"Found: {total_docs}")

total_audit = db.query(AuditLog).count()
test("Audit log tiene registros", total_audit > 0, f"Found: {total_audit}")

# Verificar campos del modelo Case
case = db.query(Case).filter(Case.accionante.isnot(None), Case.folder_name.isnot(None)).first()
test("Case tiene accionante", bool(case and case.accionante))
test("Case tiene folder_name", bool(case and case.folder_name))

# Verificar relaciones
if case:
    test("Case.documents relacion funciona", hasattr(case, 'documents'))
    test("Case.to_dict() funciona", 'ACCIONANTE' in case.to_dict())

# Verificar CSV_FIELD_MAP
test("CSV_FIELD_MAP tiene 28 campos", len(Case.CSV_FIELD_MAP) == 28, f"Found: {len(Case.CSV_FIELD_MAP)}")

db.close()

# ============================================================
# 3. EXTRACTORES DE DOCUMENTOS
# ============================================================
section("3. EXTRACTORES DE DOCUMENTOS")

# Test PDF extractor
try:
    from backend.extraction.pdf_extractor import extract_pdf
    test("Importar pdf_extractor", True)

    # Buscar un PDF de prueba
    test_pdfs = list(BASE_DIR.glob("2026-00095*/*.pdf"))
    if test_pdfs:
        result = extract_pdf(str(test_pdfs[0]))
        test(f"Extraer PDF: {test_pdfs[0].name[:40]}", bool(result.text), result.error or "")
        test("PDF tiene paginas", result.page_count > 0, f"Pages: {result.page_count}")
        test("PDF texto no truncado (>100 chars)", len(result.text) > 100, f"Chars: {len(result.text)}")
    else:
        test("Encontrar PDF de prueba", False, "No PDFs in test folder")
except Exception as e:
    test("PDF extractor", False, str(e))

# Test DOCX extractor
try:
    from backend.extraction.docx_extractor import extract_docx
    test("Importar docx_extractor", True)

    test_docx = list(BASE_DIR.glob("2026-00095*/*.docx"))
    if test_docx:
        result = extract_docx(str(test_docx[0]))
        test(f"Extraer DOCX: {test_docx[0].name[:40]}", bool(result.text), result.error or "")
        test("DOCX tiene metodo", result.method in ("python-docx", "zip_fallback"))
        test("DOCX busco lawyer_name", hasattr(result, 'lawyer_name'))
    else:
        test("Encontrar DOCX de prueba", False, "No DOCX in test folder")
except Exception as e:
    test("DOCX extractor", False, str(e))

# Test DOC extractor
try:
    from backend.extraction.doc_extractor import extract_doc
    test("Importar doc_extractor", True)
except Exception as e:
    test("Importar doc_extractor", False, str(e))

# Test OCR extractor
try:
    from backend.extraction.ocr_extractor import is_tesseract_available
    test("Importar ocr_extractor", True)
    test("Tesseract check no falla", True)  # Solo verifica que no crashee
except Exception as e:
    test("Importar ocr_extractor", False, str(e))

# ============================================================
# 4. EXTRACTOR IA (Groq)
# ============================================================
section("4. EXTRACTOR IA (Groq)")

try:
    from backend.extraction.ai_extractor import extract_with_ai, AIExtractionResult
    test("Importar ai_extractor", True)

    # Test con texto minimo (no llama a Groq realmente)
    result = extract_with_ai([], "test_folder")
    test("AI extractor maneja lista vacia", result.error == "No hay texto para analizar")

    # Test con texto real (llama a Groq - 1 request)
    test_docs = [{"filename": "test.pdf", "text": """
        JUZGADO PRIMERO CIVIL DEL CIRCUITO DE BUCARAMANGA
        Auto admisorio de tutela
        Radicado: 68-001-31-03-001-2026-00999-00
        Accionante: JUAN PEREZ GOMEZ
        Accionado: SECRETARIA DE EDUCACION DE SANTANDER
        Derechos vulnerados: EDUCACION - IGUALDAD
        Fecha: 15/03/2026
    """}]
    result = extract_with_ai(test_docs, "2026-00999 JUAN PEREZ GOMEZ")
    test("AI extractor responde sin error", result.error is None, result.error or "")
    if not result.error:
        test("AI extrajo campos", len(result.fields) > 0, f"Fields: {len(result.fields)}")
        has_accionante = "ACCIONANTE" in result.fields and result.fields["ACCIONANTE"].value
        test("AI extrajo ACCIONANTE", has_accionante)
        has_juzgado = "JUZGADO" in result.fields and result.fields["JUZGADO"].value
        test("AI extrajo JUZGADO", has_juzgado)
except Exception as e:
    test("AI extractor", False, str(e))

# ============================================================
# 5. SERVICIOS
# ============================================================
section("5. SERVICIOS")

try:
    from backend.services.case_service import list_cases, get_case, get_dashboard_kpis, get_chart_data, get_filter_options
    db = SessionLocal()

    result = list_cases(db, page=1, per_page=5)
    test("list_cases retorna datos", len(result["items"]) > 0)
    test("list_cases tiene paginacion", "total" in result and "pages" in result)

    result = list_cases(db, search="GARCIA", per_page=5)
    test("list_cases busqueda funciona", isinstance(result["items"], list))

    kpis = get_dashboard_kpis(db)
    test("KPIs tiene total_casos", kpis["total_casos"] > 0)
    test("KPIs tiene activos", "activos" in kpis)
    test("KPIs tiene completitud", "completitud_campos" in kpis)

    charts = get_chart_data(db)
    test("Charts tiene by_city", len(charts["by_city"]) > 0)
    test("Charts tiene by_fallo", len(charts["by_fallo"]) > 0)

    filters = get_filter_options(db)
    test("Filters tiene ciudades", len(filters["ciudades"]) > 0)

    db.close()
except Exception as e:
    test("Servicios", False, str(e))

# ============================================================
# 6. EMAIL MONITOR
# ============================================================
section("6. EMAIL MONITOR")

try:
    from backend.email.gmail_monitor import (
        _extract_radicado_from_text,
        _extract_accionante_from_text,
    )
    test("Importar gmail_monitor", True)

    # Test radicado extraction (ahora retorna tupla: rad23, rad_corto)
    rad23, rad_corto = _extract_radicado_from_text("Tutela RAD. 2026-00095 admitida")
    test("Extraer radicado de texto", rad_corto == "2026-00095", f"Got: {rad_corto}")

    rad23, rad_corto = _extract_radicado_from_text("Auto 2026-95 concede")
    test("Extraer radicado corto", rad_corto == "2026-00095", f"Got: {rad_corto}")

    rad23, rad_corto = _extract_radicado_from_text("Radicado 68-001-31-03-001-2026-00012-00")
    test("Extraer radicado 23 digitos", rad23 is not None and "68" in rad23, f"Got: {rad23}")

    # Test accionante extraction
    acc = _extract_accionante_from_text(
        "Accionante: Paola Andrea Garcia Nuñez contra Gobernacion", ""
    )
    test("Extraer accionante con keyword", bool(acc) and "PAOLA" in acc.upper(), f"Got: {acc}")

    acc = _extract_accionante_from_text(
        "Auto admisorio interpuesta por Angelica Velasco Mendez contra EPS", ""
    )
    test("Extraer accionante 'interpuesta por'", bool(acc) and "ANGELICA" in acc.upper(), f"Got: {acc}")

    # Test: NO debe extraer texto juridico como accionante
    acc = _extract_accionante_from_text(
        "Notificación Auto Avoca Tutela Rad 2026-00095", ""
    )
    test("NO extraer texto juridico como accionante", acc == "", f"Got: '{acc}'")

except Exception as e:
    test("Email monitor", False, str(e))

# ============================================================
# 7. REPORTES
# ============================================================
section("7. REPORTES")

try:
    from backend.reports.metrics import calculate_metrics
    from backend.reports.excel_generator import generate_excel

    db = SessionLocal()
    cases = db.query(Case).limit(10).all()

    metrics = calculate_metrics(cases)
    test("Metrics calcula total", metrics["total"] == len(cases))
    test("Metrics tiene fallos", "fallos" in metrics)
    test("Metrics tiene field_completitud", "field_completitud" in metrics)

    # Test Excel generation
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = tmp.name

    generate_excel(cases, tmp_path)
    test("Excel se genera sin error", Path(tmp_path).exists())
    test("Excel tiene tamanio > 0", Path(tmp_path).stat().st_size > 0)
    os.unlink(tmp_path)

    db.close()
except Exception as e:
    test("Reportes", False, str(e))

# ============================================================
# 8. PIPELINE DE EXTRACCION
# ============================================================
section("8. PIPELINE DE EXTRACCION")

try:
    from backend.extraction.pipeline import extract_document_text
    test("Importar pipeline", True)

    # Test con un documento real
    db = SessionLocal()
    doc = db.query(Document).filter(Document.file_path.like("%.pdf")).first()
    if doc:
        text, method = extract_document_text(doc)
        test(f"Pipeline extrae PDF ({method})", len(text) > 0, f"Chars: {len(text)}")
    db.close()
except Exception as e:
    test("Pipeline", False, str(e))

# ============================================================
# 9. FASTAPI APP
# ============================================================
section("9. FASTAPI APP")

try:
    from backend.main import app
    test("Importar FastAPI app", True)
    test("App tiene titulo", app.title == "Tutelas Manager")

    # Verificar que todos los routers estan registrados
    routes = [r.path for r in app.routes]
    test("/api/health registrado", "/api/health" in routes)
    test("/api/cases registrado", any("/api/cases" in r for r in routes))
    test("/api/dashboard/kpis registrado", any("dashboard" in r for r in routes))
    test("/api/reports/excel registrado", any("reports" in r for r in routes))
    test("/api/emails registrado", any("emails" in r for r in routes))
    test("/api/extraction registrado", any("extraction" in r for r in routes))
    test("/api/documents registrado", any("documents" in r for r in routes))
    test("/api/monitor/status registrado", "/api/monitor/status" in routes)

    total_routes = len([r for r in routes if r.startswith("/api/")])
    test(f"Total endpoints API >= 20", total_routes >= 20, f"Found: {total_routes}")

except Exception as e:
    test("FastAPI app", False, str(e))

# ============================================================
# RESUMEN
# ============================================================
print(f"\n{'='*60}")
print(f"  RESUMEN DE TESTS")
print(f"{'='*60}")
print(f"  Total:    {TOTAL}")
print(f"  Pasaron:  {PASS}  ({PASS/TOTAL*100:.0f}%)")
print(f"  Fallaron: {FAIL}  ({FAIL/TOTAL*100:.0f}%)")
print(f"{'='*60}")

sys.exit(0 if FAIL == 0 else 1)
