#!/usr/bin/env python3
"""Tests E2E - Verifica el flujo completo contra el servidor corriendo."""

import sys
import json
import time
import requests

BASE_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:5173"

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
# 0. VERIFICAR QUE LOS SERVIDORES ESTAN CORRIENDO
# ============================================================
section("0. SERVIDORES")

try:
    r = requests.get(f"{BASE_URL}/api/health", timeout=5)
    test("Backend responde", r.status_code == 200)
    data = r.json()
    test("Backend es Tutelas Manager", data.get("app") == "Tutelas Manager v1.0")
except requests.ConnectionError:
    print("  [FATAL] Backend no esta corriendo en puerto 8000")
    print("  Ejecute: cd tutelas-app && python3 -m uvicorn backend.main:app --port 8000")
    sys.exit(1)

try:
    r = requests.get(FRONTEND_URL, timeout=5)
    test("Frontend responde", r.status_code == 200)
    test("Frontend sirve HTML", "<!doctype html>" in r.text.lower() or "<html" in r.text.lower())
except requests.ConnectionError:
    test("Frontend responde", False, "No esta corriendo en puerto 5173")

# ============================================================
# 1. DASHBOARD
# ============================================================
section("1. DASHBOARD KPIs Y GRAFICOS")

r = requests.get(f"{BASE_URL}/api/dashboard/kpis")
test("GET /dashboard/kpis -> 200", r.status_code == 200)
kpis = r.json()
test("KPIs tiene total_casos > 0", kpis.get("total_casos", 0) > 0, f"Total: {kpis.get('total_casos')}")
test("KPIs tiene activos", "activos" in kpis)
test("KPIs tiene completitud_campos", "completitud_campos" in kpis)

r = requests.get(f"{BASE_URL}/api/dashboard/charts")
test("GET /dashboard/charts -> 200", r.status_code == 200)
charts = r.json()
test("Charts tiene by_city", len(charts.get("by_city", [])) > 0)
test("Charts tiene by_fallo", len(charts.get("by_fallo", [])) > 0)
test("Charts tiene by_month", isinstance(charts.get("by_month"), list))
test("Charts tiene by_lawyer", isinstance(charts.get("by_lawyer"), list))

r = requests.get(f"{BASE_URL}/api/dashboard/activity")
test("GET /dashboard/activity -> 200", r.status_code == 200)
test("Activity es lista", isinstance(r.json(), list))

# ============================================================
# 2. CASOS - CRUD
# ============================================================
section("2. CASOS CRUD")

# Listar
r = requests.get(f"{BASE_URL}/api/cases", params={"per_page": 5})
test("GET /cases -> 200", r.status_code == 200)
data = r.json()
test("Cases tiene paginacion", "total" in data and "pages" in data)
test("Cases retorna datos", len(data.get("items", [])) > 0)
first_case_id = data["items"][0]["id"] if data.get("items") else None

# Busqueda
r = requests.get(f"{BASE_URL}/api/cases", params={"search": "GARCIA", "per_page": 5})
test("Busqueda por nombre funciona", r.status_code == 200)

# Filtros
r = requests.get(f"{BASE_URL}/api/cases", params={"estado": "ACTIVO", "per_page": 5})
test("Filtro por estado funciona", r.status_code == 200)

r = requests.get(f"{BASE_URL}/api/cases/filters")
test("GET /cases/filters -> 200", r.status_code == 200)
filters = r.json()
test("Filters tiene ciudades", len(filters.get("ciudades", [])) > 0)
test("Filters tiene abogados", isinstance(filters.get("abogados"), list))

# Detalle de un caso
if first_case_id:
    r = requests.get(f"{BASE_URL}/api/cases/{first_case_id}")
    test(f"GET /cases/{first_case_id} -> 200", r.status_code == 200)
    case = r.json()
    test("Case tiene 28 campos", "RADICADO_23_DIGITOS" in case and "OBSERVACIONES" in case)
    test("Case tiene documents", "documents" in case)
    test("Case tiene audit_log", "audit_log" in case)

# Caso inexistente
r = requests.get(f"{BASE_URL}/api/cases/99999")
test("GET /cases/99999 -> 404", r.status_code == 404)

# Actualizar caso
if first_case_id:
    r = requests.put(
        f"{BASE_URL}/api/cases/{first_case_id}",
        json={"OBSERVACIONES": "Test E2E - actualizado automaticamente"}
    )
    test("PUT /cases update -> 200", r.status_code == 200)
    updated = r.json()
    test("Campo actualizado correctamente", updated.get("OBSERVACIONES", "").startswith("Test E2E"))

    # Revertir
    requests.put(
        f"{BASE_URL}/api/cases/{first_case_id}",
        json={"OBSERVACIONES": ""}
    )

# ============================================================
# 3. DOCUMENTOS
# ============================================================
section("3. DOCUMENTOS")

if first_case_id:
    r = requests.get(f"{BASE_URL}/api/cases/{first_case_id}")
    case = r.json()
    docs = case.get("documents", [])

    if docs:
        doc_id = docs[0]["id"]
        r = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        test(f"GET /documents/{doc_id} -> 200", r.status_code == 200)
        doc = r.json()
        test("Document tiene filename", bool(doc.get("filename")))
        test("Document tiene doc_type", bool(doc.get("doc_type")))

        # Preview (solo si es PDF)
        if doc.get("filename", "").endswith(".pdf"):
            r = requests.get(f"{BASE_URL}/api/documents/{doc_id}/preview")
            test("GET /documents/preview -> 200", r.status_code == 200)
            test("Preview content-type es PDF", "pdf" in r.headers.get("content-type", ""))
    else:
        test("Caso tiene documentos", False, "No documents found")

# ============================================================
# 4. EXTRACCION
# ============================================================
section("4. EXTRACCION")

r = requests.get(f"{BASE_URL}/api/extraction/review")
test("GET /extraction/review -> 200", r.status_code == 200)
test("Review queue es lista", isinstance(r.json(), list))

# ============================================================
# 5. REPORTES
# ============================================================
section("5. REPORTES")

r = requests.post(f"{BASE_URL}/api/reports/excel")
test("POST /reports/excel -> 200", r.status_code == 200)
excel_data = r.json()
test("Excel generado tiene filename", bool(excel_data.get("filename")))
test("Excel tiene cases_count > 0", excel_data.get("cases_count", 0) > 0)

if excel_data.get("filename"):
    filename = excel_data["filename"]
    r = requests.get(f"{BASE_URL}/api/reports/excel/download/{filename}")
    test("Descargar Excel -> 200", r.status_code == 200)
    test("Excel es archivo valido (>1KB)", len(r.content) > 1024, f"Size: {len(r.content)}")

r = requests.get(f"{BASE_URL}/api/reports/excel/list")
test("GET /reports/excel/list -> 200", r.status_code == 200)
test("Lista tiene archivos", len(r.json()) > 0)

r = requests.get(f"{BASE_URL}/api/reports/metrics")
test("GET /reports/metrics -> 200", r.status_code == 200)
metrics = r.json()
test("Metrics tiene total", metrics.get("total", 0) > 0)

# ============================================================
# 6. EMAILS
# ============================================================
section("6. EMAILS")

r = requests.get(f"{BASE_URL}/api/emails")
test("GET /emails -> 200", r.status_code == 200)
email_data = r.json()
test("Emails tiene paginacion", "total" in email_data)

# ============================================================
# 7. CONFIGURACION Y MONITOR
# ============================================================
section("7. CONFIGURACION Y MONITOR")

r = requests.get(f"{BASE_URL}/api/settings/status")
test("GET /settings/status -> 200", r.status_code == 200)
settings = r.json()
test("Gmail configurado", settings.get("gmail_configured") == True)
test("Groq configurado", settings.get("groq_configured") == True)

r = requests.get(f"{BASE_URL}/api/monitor/status")
test("GET /monitor/status -> 200", r.status_code == 200)
monitor = r.json()
test("Monitor tiene enabled", "enabled" in monitor)
test("Monitor tiene interval", monitor.get("interval_minutes") == 20)
test("Monitor tiene log", isinstance(monitor.get("log"), list))

# ============================================================
# 8. SWAGGER/DOCS
# ============================================================
section("8. DOCUMENTACION API")

r = requests.get(f"{BASE_URL}/docs")
test("GET /docs (Swagger) -> 200", r.status_code == 200)

r = requests.get(f"{BASE_URL}/openapi.json")
test("GET /openapi.json -> 200", r.status_code == 200)
openapi = r.json()
test("OpenAPI tiene paths", len(openapi.get("paths", {})) > 10)

# ============================================================
# 9. FRONTEND PROXY
# ============================================================
section("9. FRONTEND -> BACKEND PROXY")

try:
    r = requests.get(f"{FRONTEND_URL}/api/health", timeout=5)
    test("Frontend proxies /api/health", r.status_code == 200 and r.json().get("status") == "ok")
except Exception:
    test("Frontend proxies /api/health", False, "Proxy not working or frontend not running")

# ============================================================
# RESUMEN
# ============================================================
print(f"\n{'='*60}")
print(f"  RESUMEN DE TESTS E2E")
print(f"{'='*60}")
print(f"  Total:    {TOTAL}")
print(f"  Pasaron:  {PASS}  ({PASS/TOTAL*100:.0f}%)")
print(f"  Fallaron: {FAIL}  ({FAIL/TOTAL*100:.0f}%)")
print(f"{'='*60}")

sys.exit(0 if FAIL == 0 else 1)
