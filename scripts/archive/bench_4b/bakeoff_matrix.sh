#!/usr/bin/env bash
# Fase 1 — Matriz modelo × config × caché sobre el pipeline de PRODUCCIÓN.
#
# SEGURIDAD (clave): el server del bench corre en BENCH_PORT (8766), y el pipeline
# le habla vía LLM_LOCAL_URL. NUNCA mata ni toca tu :8765 de producción. Solo mata
# procesos en BENCH_PORT (su propio server). dry-run → no escribe la DB.
#
# Reusa el patrón probado de scripts/bakeoff_30b_vs_4b.sh (kill/health/spawn).
#
# Uso:
#   bash scripts/bench/bakeoff_matrix.sh                 # todas las celdas disponibles
#   bash scripts/bench/bakeoff_matrix.sh baseline        # solo el preset baseline
#   BENCH_CONFIRM=1 bash scripts/bench/bakeoff_matrix.sh # confirma correr aunque :8765 esté ocupado
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/venv/bin/python3"; [ -x "$PY" ] || PY=python3
SERVER="$HOME/llama.cpp/build-vulkan/bin/llama-server"
LOGDIR="$ROOT/logs"; mkdir -p "$LOGDIR" "$ROOT/data/bench"

BENCH_PORT="${BENCH_PORT:-8766}"          # NUNCA 8765
BENCH_URL="http://127.0.0.1:${BENCH_PORT}"
ONLY_PRESET="${1:-}"

# --- Modelos candidatos (se saltan los que no existan localmente) ----------
declare -A MODELS=(
  [current]="$ROOT/data/lora-models/Qwen3-4B-Q4_K_M.gguf"
  [4b2507]="$ROOT/data/lora-models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
  [qwen35-4b]="$ROOT/data/lora-models/Qwen3.5-4B-Q4_K_M.gguf"
  [30b-a3b]="$ROOT/data/lora-models/Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf"
)
# Orden de evaluación (baseline primero)
MODEL_ORDER=(current 4b2507 qwen35-4b 30b-a3b)
# Override opcional: BENCH_MODELS="current 4b2507 qwen35-4b" limita el carril.
[ -n "${BENCH_MODELS:-}" ] && MODEL_ORDER=(${BENCH_MODELS})

# --- Presets de config (flags del llama-server) ----------------------------
# NOTA: KV q8_0 REQUIERE -fa (dependencia dura de llama.cpp).
declare -A PRESET_FLAGS=(
  [baseline]="-c 4096 -ngl 99 -t 6 --no-warmup"
  [fa_kv16k]="-c 16384 -ngl 99 -t 6 -fa on --cache-type-k q8_0 --cache-type-v q8_0 --no-warmup"
  [fa_kv32k]="-c 32768 -ngl 99 -t 6 -fa on --cache-type-k q8_0 --cache-type-v q8_0 -ub 512 --no-warmup"
)
PRESET_ORDER=(baseline fa_kv16k fa_kv32k)

# --- Guard: no reventar al operador ---------------------------------------
if curl -s -m2 "http://127.0.0.1:8765/health" >/dev/null 2>&1; then
  if [ "${BENCH_CONFIRM:-0}" != "1" ]; then
    echo "⚠ Tu :8765 (producción) está ARRIBA. El bench corre en :$BENCH_PORT y NO lo tocará,"
    echo "  pero cargar un 2º modelo en la misma iGPU puede contender memoria (riesgo OOM)."
    echo "  Si NO hay extracción activa, relanza con:  BENCH_CONFIRM=1 bash $0 ${ONLY_PRESET}"
    exit 2
  fi
  echo "ℹ :8765 arriba pero BENCH_CONFIRM=1 → procedo en :$BENCH_PORT (sin tocar 8765)."
fi
[ -x "$SERVER" ] || { echo "!! no existe build-vulkan/llama-server: $SERVER"; exit 1; }

kill_bench() {                              # SOLO mata el server del bench (BENCH_PORT)
  fuser -k "${BENCH_PORT}/tcp" 2>/dev/null || true
  for _ in $(seq 1 20); do curl -s -m1 "${BENCH_URL}/health" >/dev/null 2>&1 || return 0; sleep 0.5; done
}
wait_health() { local max="$1"; for _ in $(seq 1 "$max"); do
  curl -s -m2 "${BENCH_URL}/health" 2>/dev/null | grep -q '"status"\|ok' && return 0; sleep 1; done; return 1; }

run_cell() {  # $1=model_key $2=preset $3=doc_cache(true|false)
  local mk="$1" preset="$2" dcache="$3"
  local model="${MODELS[$mk]}" flags="${PRESET_FLAGS[$preset]}"
  local soft="false"; [ "$mk" = "30b-a3b" ] && soft="true"
  local tag="${mk}__${preset}__cache-${dcache}"
  local slog="$LOGDIR/bench_server_${tag}.log"
  echo ">>> celda [$tag]  ($(basename "$model"))"
  kill_bench
  nohup "$SERVER" -m "$model" --host 127.0.0.1 --port "$BENCH_PORT" --parallel 1 $flags >"$slog" 2>&1 &
  local spid=$!
  if ! wait_health 300; then echo "    !! server no respondió (ver $slog) — celda saltada"; kill_bench; return 1; fi
  BENCH_TAG="$tag" BENCH_CONFIG="$preset; $flags" BENCH_SERVER_LOG="$slog" BENCH_SERVER_PID="$spid" \
    LLM_LOCAL_URL="$BENCH_URL" LLM_LOCAL_PORT="$BENCH_PORT" \
    V9_DOC_CACHE="$dcache" V9_LLM_SOFT_JSON="$soft" \
    "$PY" scripts/bench/bakeoff_harness.py
  kill_bench
}

echo "═══ MATRIZ DE BENCHMARK · bench en :$BENCH_PORT (prod :8765 intacto) ═══"
for mk in "${MODEL_ORDER[@]}"; do
  [ -f "${MODELS[$mk]}" ] || { echo "— saltado [$mk]: GGUF no encontrado (${MODELS[$mk]##*/})"; continue; }
  for preset in "${PRESET_ORDER[@]}"; do
    [ -n "$ONLY_PRESET" ] && [ "$preset" != "$ONLY_PRESET" ] && continue
    for dcache in ${BENCH_CACHES:-true false}; do
      run_cell "$mk" "$preset" "$dcache" || true
    done
  done
done

echo; echo "═══ REPORTE ═══"
"$PY" scripts/bench/bakeoff_report.py || true
