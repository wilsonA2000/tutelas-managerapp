#!/bin/bash
# Aplica: borra servicios llama-* obsoletos + reinstala el tuning GPU (freq RP0 + heartbeat 20s).
# Correr con: sudo bash scripts/apply_gpu_fix.sh   (desde tutelas-app/)
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== 1. Deshabilitar/parar servicios obsoletos ==="
systemctl disable --now llama-text.service 2>/dev/null || true
systemctl disable --now llama-vision.service 2>/dev/null || true

echo "=== 2. Borrar unit files obsoletos ==="
rm -f /etc/systemd/system/llama-text.service /etc/systemd/system/llama-vision.service

echo "=== 3. Reinstalar tuning GPU ==="
cp "$DIR/scripts/intel-gpu-maxfreq.service" /etc/systemd/system/intel-gpu-maxfreq.service

echo "=== 4. Recargar + activar ==="
systemctl daemon-reload
systemctl reset-failed
systemctl enable intel-gpu-maxfreq.service
systemctl restart intel-gpu-maxfreq.service

echo "=== APLICADO OK ==="
