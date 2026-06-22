#!/usr/bin/env bash
# Descarga del 30B-A3B usando el CLI `hf` del SISTEMA (huggingface_hub 1.14.0).
# Razón: el hf_hub_download del venv (0.36.2) se cuelga a ~5MB; el CLI del sistema
# funciona (con él bajaron los 4B). Con HF_TOKEN (env) no hay rate-limit y reanuda.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
HF="$HOME/.local/bin/hf"
export HF_HUB_ENABLE_HF_TRANSFER=0   # plano = estable; hf_transfer se atascaba aquí
export HF_HUB_DOWNLOAD_TIMEOUT=30
[ -n "${HF_TOKEN:-}" ] && echo "HF_TOKEN presente (autenticada)" || echo "SIN token"
REPO="unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF"
FILE="Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf"
for i in $(seq 1 40); do
  echo "[intento $i] $(date '+%H:%M:%S')"
  if timeout 300 "$HF" download "$REPO" "$FILE" --local-dir data/lora-models; then
    echo "✓ 30B COMPLETO"; break
  fi
  echo "  reanudo en 5s (resume desde parcial)..."; sleep 5
done
ls -lh data/lora-models/Qwen3-30B*.gguf 2>/dev/null
echo "=== DESCARGA 30B FIN ==="