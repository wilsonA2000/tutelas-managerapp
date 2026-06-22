#!/usr/bin/env python3
"""Red de seguridad — smoke test del backend (Fase 1 del plan de modernización).

Hace login, golpea cada endpoint que el frontend de verdad llama, y verifica que
ninguno devuelve 5xx y que la forma de la respuesta es razonable. Para los endpoints
con efectos secundarios (POST de extracción/sync/cleanup, DELETE, etc.) NO los invoca:
solo confirma que la ruta existe en el OpenAPI (así el botón del frontend no dará 404).

Uso:
    ./venv/bin/python3 scripts/smoke_backend.py
    ./venv/bin/python3 scripts/smoke_backend.py --base http://127.0.0.1:8000 --user wilson --password tutelas2026

Exit code 0 si todo OK (salvo los FAIL "esperados/baseline"); 1 si hay algún FAIL nuevo.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

import requests

# Endpoints que el frontend llama y que HOY se sabe que fallan (baseline). Cada entrada
# es un prefijo/substring del label; se considera "FAIL esperado" si coincide. A medida
# que se vayan arreglando en las fases siguientes, se quitan de aquí.
KNOWN_FAILING: list[str] = [
    # "GET /api/dashboard/kpis",  ← arreglado en Fase 2 (AmbiguousForeignKeysError)
    # "GET /api/intelligence/similar/",  ← retirado: la búsqueda por similitud (faiss/BGE-M3) y la pestaña "Casos parecidos" se quitaron
]


def _short(v) -> str:
    s = repr(v)
    return s if len(s) <= 80 else s[:77] + "..."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--user", default="wilson")
    ap.add_argument("--password", default="tutelas2026")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()
    base = args.base.rstrip("/")

    s = requests.Session()
    s.headers["Accept"] = "application/json"

    results: list[tuple[str, str, str]] = []  # (label, status, detail)  status ∈ OK/FAIL/EXISTS/SKIP

    def record(label: str, status: str, detail: str = ""):
        results.append((label, status, detail))

    # ── login ──
    try:
        r = s.post(f"{base}/api/auth/login", json={"username": args.user, "password": args.password}, timeout=args.timeout)
        r.raise_for_status()
        token = r.json().get("access_token")
        assert token, "sin access_token"
        s.headers["Authorization"] = f"Bearer {token}"
        record("POST /api/auth/login", "OK", "token obtenido")
    except Exception as e:  # noqa: BLE001
        record("POST /api/auth/login", "FAIL", f"{type(e).__name__}: {e}")
        _print_and_exit(results)
        return 1

    # ── descubrir IDs reales para los endpoints con {id} ──
    case_id: Optional[int] = None
    email_id: Optional[int] = None
    try:
        r = s.get(f"{base}/api/cases/table", timeout=args.timeout)
        if r.ok and isinstance(r.json(), list) and r.json():
            rows = r.json()
            real = [x for x in rows if isinstance(x, dict) and x.get("id") and x.get("folder_name") != "__SIN_RADICADO__"]
            case_id = (real[0] if real else rows[0]).get("id")
    except Exception:
        pass
    try:
        r = s.get(f"{base}/api/emails", params={"limit": 1}, timeout=args.timeout)
        j = r.json() if r.ok else None
        items = j if isinstance(j, list) else (j.get("items") or j.get("emails") or j.get("data") or []) if isinstance(j, dict) else []
        if items and isinstance(items[0], dict):
            email_id = items[0].get("id")
    except Exception:
        pass

    # ── GET endpoints (read-only, seguros de invocar) ──
    # (path, assert_fn opcional sobre el json)
    def is_list(j): return isinstance(j, list)
    def has(*keys):
        return lambda j: isinstance(j, dict) and any(k in j for k in keys)

    GETS: list[tuple[str, object]] = [
        ("/api/auth/me", has("username", "user", "id")),
        ("/api/health", None),
        ("/api/cases", None),
        ("/api/cases/filters", None),
        ("/api/cases/table", is_list),
        ("/api/dashboard/kpis", has("total")),
        ("/api/dashboard/charts", None),
        ("/api/dashboard/activity", None),
        ("/api/chat/health", None),
        ("/api/chat/intents", None),
        ("/api/cleanup/diagnosis", None),
        ("/api/cleanup/health-v50", None),
        ("/api/extraction/review", None),
        ("/api/extraction/mismatched-docs", None),
        ("/api/extraction/suspicious-docs", None),
        ("/api/extraction/progress", None),
        ("/api/reports/excel/list", None),
        ("/api/reports/metrics", None),
        ("/api/emails", None),
        ("/api/emails/gmail-stats", None),
        ("/api/emails/check-status", None),
        ("/api/settings/status", None),
        ("/api/monitor/status", None),
        ("/api/sync/status", None),
        ("/api/seguimiento", None),
        ("/api/alerts", None),
        ("/api/alerts/counts", None),
        ("/api/intelligence/favorability", None),
        ("/api/intelligence/appeals", None),
        ("/api/intelligence/lawyers", None),
        ("/api/intelligence/trends", None),
        ("/api/intelligence/rights", None),
        ("/api/intelligence/calendar", None),
        ("/api/intelligence/deadlines", None),
        ("/api/v9/health", has("fields")),
        ("/api/auditoria/cases", None),
        ("/api/auditoria/dashboard", None),
        ("/api/corte/cases", None),
        ("/api/directorio-correos", None),
        ("/api/knowledge/stats", None),
        ("/api/import/control-tutelas/last-import", None),
    ]
    if case_id is not None:
        GETS += [
            (f"/api/cases/{case_id}", has("id", "radicado_23_digitos", "accionante")),
            (f"/api/cases/{case_id}/email-packages", None),
            (f"/api/v9/preview/{case_id}", has("values", "completitud")),
        ]
    if email_id is not None:
        GETS += [
            (f"/api/emails/detail/{email_id}", None),
            (f"/api/emails/{email_id}/package", None),
        ]

    for path, check in GETS:
        label = f"GET {path}"
        try:
            r = s.get(f"{base}{path}", timeout=args.timeout)
            if r.status_code >= 500:
                record(label, "FAIL", f"HTTP {r.status_code}: {_short(r.text)}")
            elif r.status_code >= 400:
                record(label, "FAIL", f"HTTP {r.status_code}")
            else:
                if check is not None:
                    try:
                        ok = check(r.json())
                    except Exception as e:  # noqa: BLE001
                        ok = False
                        record(label, "FAIL", f"HTTP {r.status_code} pero forma inesperada: {e}")
                        continue
                    record(label, "OK" if ok else "FAIL", f"HTTP {r.status_code}" + ("" if ok else " — forma inesperada"))
                else:
                    record(label, "OK", f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            record(label, "FAIL", f"{type(e).__name__}: {e}")

    # ── POSTs seguros de invocar (dry-run / sin efectos) ──
    try:
        r = s.post(f"{base}/api/chat/", json={"message": "¿cuántas tutelas hay?"}, timeout=args.timeout)
        record("POST /api/chat/", "OK" if r.ok else "FAIL", f"HTTP {r.status_code}: {_short(r.text)}")
    except Exception as e:  # noqa: BLE001
        record("POST /api/chat/", "FAIL", f"{type(e).__name__}: {e}")
    try:
        r = s.post(f"{base}/api/v9/extract-batch", json={"limit": 3, "apply": False}, timeout=max(args.timeout, 60))
        j = r.json() if r.ok else {}
        ok = r.ok and "results" in j
        record("POST /api/v9/extract-batch (dry-run)", "OK" if ok else "FAIL",
               f"HTTP {r.status_code}" + (f" count={j.get('count')} avg={j.get('summary', {}).get('avg_completitud')}" if ok else f": {_short(r.text)}"))
    except Exception as e:  # noqa: BLE001
        record("POST /api/v9/extract-batch (dry-run)", "FAIL", f"{type(e).__name__}: {e}")

    # ── endpoints con efectos secundarios: solo confirmar que la ruta existe en el OpenAPI ──
    side_effect_paths = [
        ("DELETE", "/api/cases/{id}/docs/{docId}"), ("DELETE", "/api/cases/{id}"),
        ("DELETE", "/api/extraction/mismatched-docs"), ("DELETE", "/api/extraction/mismatched-docs/{logId}"),
        ("POST", "/api/alerts/{id}/dismiss"), ("POST", "/api/alerts/mark-seen"),
        ("POST", "/api/alerts/scan"), ("POST", "/api/cases/{id}/sync"),
        ("POST", "/api/cleanup/backfill-radicados"), ("POST", "/api/cleanup/emails-md-backfill"),
        ("POST", "/api/cleanup/hash-backfill"), ("POST", "/api/cleanup/merge-forest-fragments"),
        ("POST", "/api/cleanup/merge-identity"), ("POST", "/api/cleanup/move-no-pertenece"),
        ("POST", "/api/cleanup/purge-duplicates"), ("POST", "/api/cleanup/reverify-sospechosos"),
        ("POST", "/api/emails/check"), ("POST", "/api/emails/check-cancel"),
        ("POST", "/api/extraction/audit"), ("POST", "/api/extraction/batch"),
        ("POST", "/api/extraction/docs/{docId}/mark-ok"), ("POST", "/api/extraction/docs/{docId}/move/{targetCaseId}"),
        ("POST", "/api/extraction/run-all"), ("POST", "/api/extraction/single/{caseId}"), ("POST", "/api/extraction/stop"),
        ("POST", "/api/extraction/verify-all"), ("POST", "/api/reports/excel"),
        ("POST", "/api/seguimiento/{id}/extract-order"), ("POST", "/api/seguimiento/scan"),
        ("POST", "/api/sync"), ("POST", "/api/sync/cancel"), ("POST", "/api/v9/extract/{caseId}"),
        ("PUT", "/api/cases/{id}"), ("PUT", "/api/seguimiento/{id}"),
        ("GET", "/api/extraction/docs/{docId}/suggest-target"), ("GET", "/api/intelligence/predict"),
        ("GET", "/api/documents/{id}/preview"), ("GET", "/api/cleanup/diagnosis.md"),
    ]
    try:
        spec = s.get(f"{base}/openapi.json", timeout=args.timeout).json()
        # normaliza {param} → set de (METHOD, plantilla-sin-nombres-de-param)
        import re as _re
        def norm(p: str) -> str:
            return _re.sub(r"\{[^}]+\}", "{}", p)
        registered = {(m.upper(), norm(p)) for p, methods in spec.get("paths", {}).items() for m in methods}
        for method, path in side_effect_paths:
            key = (method, norm(path))
            label = f"{method} {path}"
            record(label, "EXISTS" if key in registered else "FAIL", "en OpenAPI" if key in registered else "NO está en OpenAPI (botón roto)")
    except Exception as e:  # noqa: BLE001
        record("openapi.json", "FAIL", f"{type(e).__name__}: {e}")

    return _print_and_exit(results)


def _print_and_exit(results: list[tuple[str, str, str]]) -> int:
    width = max((len(r[0]) for r in results), default=20)
    new_fails = []
    print(f"\n{'='*70}\nSMOKE BACKEND — {len(results)} checks\n{'='*70}")
    for label, status, detail in results:
        mark = {"OK": "✓", "EXISTS": "·", "SKIP": "—"}.get(status, "✗")
        flag = ""
        if status == "FAIL":
            if any(k in label for k in KNOWN_FAILING):
                flag = "  (FAIL esperado / baseline)"
            else:
                new_fails.append(label)
        print(f"  {mark} {label:<{width}}  {status:<7} {detail}{flag}")
    print(f"{'='*70}")
    if new_fails:
        print(f"❌ {len(new_fails)} FAIL NUEVO(S) (regresión): {', '.join(new_fails)}")
        return 1
    n_ok = sum(1 for _, st, _ in results if st in ("OK", "EXISTS"))
    n_baseline = sum(1 for lbl, st, _ in results if st == "FAIL" and any(k in lbl for k in KNOWN_FAILING))
    print(f"✅ {n_ok} OK/EXISTS · {n_baseline} FAIL esperados (baseline) · 0 FAIL nuevos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
