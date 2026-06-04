#!/usr/bin/env bash
# A/B del prompt (V1 vs V2) sobre el 4B base, OCR OFF, con watchdog térmico.
# Mata todo si la temp llega al umbral. Server en :8766 (NO toca prod :8765).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
PY="venv/bin/python3"; [ -x "$PY" ] || PY=python3
SRV="$HOME/llama.cpp/build-vulkan/bin/llama-server"
MODEL="data/lora-models/Qwen3-4B-Q4_K_M.gguf"
ZONE=/sys/class/thermal/thermal_zone0/temp
MAXT=${MAXT:-87}
N=${N:-8}

temp() { echo $(( $(cat "$ZONE") / 1000 )); }

# --- watchdog térmico ---
( while true; do
    t=$(temp)
    if [ "$t" -ge "$MAXT" ]; then
      echo ">>> WATCHDOG: ${t}°C ≥ ${MAXT} — matando server+harness" >> logs/abprompt_watchdog.log
      pkill -9 -f "bakeoff_harness" 2>/dev/null
      pkill -9 -f "llama-server.*8766" 2>/dev/null
      break
    fi
    sleep 6
  done ) &
WD=$!

echo "temp inicial: $(temp)°C"
fuser -k 8766/tcp 2>/dev/null; sleep 2
nohup "$SRV" -m "$MODEL" --port 8766 --ctx-size 32768 --parallel 1 --host 127.0.0.1 --n-gpu-layers 99 > logs/abprompt_server.log 2>&1 &
for i in $(seq 1 60); do curl -s -m2 http://127.0.0.1:8766/health 2>/dev/null | grep -q ok && break; sleep 2; done
echo "server healthy · temp: $(temp)°C"

for variant in v1 v2; do
  flag=false; [ "$variant" = "v2" ] && flag=true
  echo ">>> corriendo prompt-${variant} (V9_PROMPT_V2=${flag}, OCR off, ${N} casos) · temp $(temp)°C"
  BENCH_TAG="prompt-${variant}" BENCH_MAX_CASES="$N" \
    LLM_LOCAL_URL="http://127.0.0.1:8766" LLM_LOCAL_PORT=8766 \
    V9_PROMPT_V2="$flag" V9_OCR_SCANNED=false V9_DOC_CACHE=true \
    "$PY" scripts/bench/bakeoff_harness.py >> "logs/abprompt_${variant}.log" 2>&1
  echo "    prompt-${variant} done · temp $(temp)°C"
done

fuser -k 8766/tcp 2>/dev/null
kill "$WD" 2>/dev/null
echo "=== A/B FIN · temp $(temp)°C ==="
