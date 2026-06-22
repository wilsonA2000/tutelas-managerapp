#!/usr/bin/env bash
# Descarga del 30B-A3B con curl directo + resume (-C -), saltándose el cliente Xet
# del `hf` CLI que se atasca a ~6MB. La URL /resolve/ devuelve un 302 firmado a
# cas-bridge.xethub.hf.co que SÍ acepta Range (accept-ranges: bytes), así que el
# resume funciona aunque la URL firmada caduque (cada intento re-pide el 302 fresco).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
DEST="data/lora-models"
FILE="Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf"
URL="https://huggingface.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF/resolve/main/${FILE}"
EXPECT=18556686752                 # bytes esperados (del HEAD)
PART="${DEST}/${FILE}.part"
OUT="${DEST}/${FILE}"
mkdir -p "$DEST"

# Semilla opcional desde el .incomplete del hf CLI (si tuviera bytes útiles).
INC=$(ls -S ${DEST}/.cache/huggingface/download/*.incomplete 2>/dev/null | head -1 || true)
if [ -n "${INC:-}" ] && [ ! -f "$PART" ]; then
  isz=$(stat -c%s "$INC" 2>/dev/null || echo 0)
  if [ "$isz" -gt 1000000 ]; then echo "semilla desde .incomplete ($isz bytes)"; cp "$INC" "$PART"; fi
fi

for i in $(seq 1 200); do
  cur=$([ -f "$PART" ] && stat -c%s "$PART" || echo 0)
  echo "[intento $i] $(date '+%H:%M:%S') — parcial: $cur / $EXPECT bytes"
  if [ "$cur" -ge "$EXPECT" ]; then break; fi
  # -L sigue el 302; -C - reanuda; reintentos internos de curl ante cortes.
  curl -L -C - --retry 5 --retry-delay 5 --retry-all-errors \
       --connect-timeout 30 --max-time 1800 \
       -o "$PART" "$URL" || true
  sleep 3
done

final=$([ -f "$PART" ] && stat -c%s "$PART" || echo 0)
if [ "$final" -ge "$EXPECT" ]; then
  mv -f "$PART" "$OUT"
  echo "✓ 30B COMPLETO: $(ls -lh "$OUT" | awk '{print $5, $9}')"
else
  echo "!! incompleto: $final / $EXPECT bytes (se reanuda al re-lanzar)"
fi
echo "=== DESCARGA 30B (curl) FIN ==="
