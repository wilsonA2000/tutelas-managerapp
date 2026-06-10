#!/usr/bin/env bash
# Bake-off 30B-A3B vs 4B SOBRE EL PIPELINE REAL.
# Para cada modelo: mata el server, arranca llama-server (build-vulkan, config
# óptima medida: -ngl 99 -t 6), espera health, corre el harness, mata el server.
# Luego compara. NO toca la DB (extract_case dry-run).
#
# Uso:  bash scripts/bakeoff_30b_vs_4b.sh [case_ids...]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/venv/bin/python3"
SERVER="$HOME/llama.cpp/build-vulkan/bin/llama-server"
M4B="$ROOT/data/lora-models/Qwen3-4B-Q4_K_M.gguf"
M30B="$ROOT/data/lora-models/Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf"
LOGDIR="$ROOT/logs"; mkdir -p "$LOGDIR"
CASES="$*"
# json_object suave en ambos modelos: el strict json_schema rompe el 30B-A3B.
# Así medimos calidad de razonamiento, no el bug de constrained decoding.
export V9_LLM_SOFT_JSON="${V9_LLM_SOFT_JSON:-true}"
echo "V9_LLM_SOFT_JSON=$V9_LLM_SOFT_JSON"

kill_server() {
  pkill -9 -f llama-server 2>/dev/null || true   # bench dedicado: dueño exclusivo del server
  fuser -k 8765/tcp 2>/dev/null || true          # backstop: matar lo que tenga el puerto
  for _ in $(seq 1 20); do curl -s -m1 http://127.0.0.1:8765/health >/dev/null 2>&1 || return 0; sleep 0.5; done
}

wait_health() {  # $1 = max segundos
  local max="$1"
  for _ in $(seq 1 "$max"); do
    if curl -s -m2 http://127.0.0.1:8765/health 2>/dev/null | grep -q '"status"\|ok'; then return 0; fi
    sleep 1
  done
  return 1
}

run_model() {  # $1 = tag, $2 = ruta gguf
  local tag="$1" model="$2"
  echo ">>> [$tag] arrancando server: $(basename "$model")"
  kill_server
  local slog="$LOGDIR/bakeoff_server_${tag}.log"
  nohup "$SERVER" -m "$model" --host 127.0.0.1 --port 8765 \
    -ngl 99 -t 6 -c 4096 --no-warmup >"$slog" 2>&1 &
  echo "    log server: $slog"
  if ! wait_health 240; then echo "!!! [$tag] server no respondió health en 240s — ver $slog"; kill_server; return 1; fi
  echo ">>> [$tag] server UP — corriendo harness"
  BAKEOFF_TAG="$tag" "$PY" scripts/bakeoff_harness.py $CASES
  kill_server
  echo ">>> [$tag] hecho."
}

echo "=== BAKE-OFF 4B vs 30B · casos: ${CASES:-(default)} ==="
run_model 4B  "$M4B"
run_model 30B "$M30B"

echo
echo "=== COMPARACIÓN ==="
"$PY" scripts/bakeoff_compare.py "$ROOT/data/bakeoff_4B.json" "$ROOT/data/bakeoff_30B.json"
