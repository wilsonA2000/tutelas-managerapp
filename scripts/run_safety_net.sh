#!/usr/bin/env bash
# Red de seguridad anti-regresiones (Fase 1 del plan de modernización).
# Encadena: tests standalone v9 + tests sobre la DB de producción + smoke del backend + smoke del frontend (Playwright).
# Se corre al final de CADA fase. Un FAIL nuevo (no presente en la baseline) = regresión.
#
# Requiere: backend en :8000 y frontend en :5173 levantados.
# Para el smoke del frontend hace falta el navegador de Playwright (una sola vez):
#     cd frontend && npx playwright install chromium
#
# Uso:  bash scripts/run_safety_net.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PY=./venv/bin/python3
[ -x "$PY" ] || PY=python3
fail=0

echo "════════════════════════════════════════════════════════════════"
echo "  RED DE SEGURIDAD — $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════════════════════"

echo; echo ">>> [0/5] Scorecard del benchmark (Fase 0 — métricas por campo)"
if "$PY" -m pytest tests/bench/test_scorecard.py -q >/dev/null 2>&1; then echo "    OK"; else echo "    FAIL"; fail=1; fi

echo; echo ">>> [1/5] Tests standalone v9 (sin DB)"
if "$PY" scripts/v9_test_standalone.py; then echo "    OK"; else echo "    FAIL"; fail=1; fi

echo; echo ">>> [2/5] Tests sobre la DB de producción (cobertura/cotas/consistencia/no-clobber)"
if V9_DISABLE_LLM=true "$PY" scripts/v9_test_db.py; then echo "    OK"; else echo "    FAIL"; fail=1; fi

echo; echo ">>> [3/5] Escaneo de conflación cross-juzgado (carpetas mezcladas por rad corto)"
if PYTHONPATH=. "$PY" scripts/scan_conflacion.py --strict; then echo "    OK"; else echo "    FAIL"; fail=1; fi

echo; echo ">>> [4/5] Smoke del backend (endpoints que usa el frontend)"
if "$PY" scripts/smoke_backend.py; then echo "    OK"; else echo "    FAIL"; fail=1; fi

echo; echo ">>> [5/5] Smoke del frontend (Playwright — navega las rutas + endpoint del asistente)"
if [ -d "$HOME/.cache/ms-playwright" ] && ls "$HOME"/.cache/ms-playwright/chromium-* >/dev/null 2>&1; then
  if (cd frontend && node ../scripts/smoke_frontend.mjs); then echo "    OK"; else echo "    FAIL"; fail=1; fi
else
  echo "    SKIP — navegador de Playwright no instalado. Instálalo una vez con:"
  echo "           cd frontend && npx playwright install chromium"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "✅ RED DE SEGURIDAD: todo verde (salvo los FAIL de baseline documentados)."
else
  echo "❌ RED DE SEGURIDAD: hay FAILs — revisa arriba antes de avanzar de fase."
fi
exit $fail
