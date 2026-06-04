#!/usr/bin/env bash
# "4B en su máximo": harness REAL (extract_case) con las palancas — reasoning off a nivel
# servidor + contexto al óptimo (~5K) + OCR off. ctx 4096 (prod). Watchdog térmico.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
PY="venv/bin/python3"; [ -x "$PY" ] || PY=python3
SRV="$HOME/llama.cpp/build-vulkan/bin/llama-server"
MODEL="data/lora-models/Qwen3-4B-Q4_K_M.gguf"
ZONE=/sys/class/thermal/thermal_zone0/temp
MAXT=${MAXT:-85}; N=${N:-5}
temp(){ echo $(( $(cat "$ZONE")/1000 )); }

( while true; do
    t=$(temp)
    if [ "$t" -ge "$MAXT" ]; then
      echo ">>> WATCHDOG ${t}°C ≥ ${MAXT} — corto" >> logs/4bmax_watchdog.log
      pkill -9 -f bakeoff_harness 2>/dev/null; pkill -9 -f "llama-server.*8766" 2>/dev/null; break
    fi; sleep 5
  done ) & WD=$!

echo "temp inicial: $(temp)°C"
fuser -k 8766/tcp 2>/dev/null; sleep 2
# Server: ctx 4096 (prod) + reasoning off a nivel servidor
nohup "$SRV" -m "$MODEL" --port 8766 --ctx-size 4096 --parallel 1 --host 127.0.0.1 \
  --n-gpu-layers 99 --jinja --reasoning off > logs/4bmax_server.log 2>&1 &
for i in $(seq 1 60); do curl -s -m2 http://127.0.0.1:8766/health 2>/dev/null | grep -q ok && break; sleep 2; done
echo "server healthy · temp $(temp)°C"

# Sanity: ¿--reasoning off devuelve CONTENT (no solo reasoning)?
san=$(curl -s -m30 http://127.0.0.1:8766/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Responde solo: OK"}],"max_tokens":10,"temperature":0}')
echo "sanity reasoning-off: $(echo "$san" | head -c 200)"

echo ">>> 4B-MAX: harness real, ${N} casos · contexto 5K · OCR off · temp $(temp)°C"
BENCH_TAG="4b-max" BENCH_MAX_CASES="$N" \
  LLM_LOCAL_URL="http://127.0.0.1:8766" LLM_LOCAL_PORT=8766 \
  V9_PROMPT_V2=false V9_OCR_SCANNED=false V9_DOC_CACHE=true \
  V9_FIELD_CONTEXT_BUDGET=5000 V9_LLM_CONTEXT_CAP=5000 \
  "$PY" scripts/bench/bakeoff_harness.py >> logs/4bmax_run.log 2>&1
echo "    done · temp $(temp)°C"

fuser -k 8766/tcp 2>/dev/null; kill "$WD" 2>/dev/null
echo "=== 4B-MAX FIN · temp $(temp)°C ==="
