#!/usr/bin/env bash
# Red de seguridad anti-regresiones (Fase 1 del plan de modernización).
# Encadena: tests standalone v9 + smoke del backend + smoke del frontend (Playwright).
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

echo; echo ">>> [1/3] Tests standalone v9 (sin DB)"
if "$PY" scripts/v9_test_standalone.py; then echo "    OK"; else echo "    FAIL"; fail=1; fi

echo; echo ">>> [2/3] Smoke del backend (endpoints que usa el frontend)"
if "$PY" scripts/smoke_backend.py; then echo "    OK"; else echo "    FAIL"; fail=1; fi

echo; echo ">>> [3/3] Smoke del frontend (Playwright — navega las rutas + botón flotante)"
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
