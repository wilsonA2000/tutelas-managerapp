#!/usr/bin/env bash
# Fase 1 — Descarga de GGUF candidatos a data/lora-models/ con el nombre EXACTO
# que espera bakeoff_matrix.sh. Los 4B caben holgados; el 30B-A3B solo si hay
# >20GB libres (si no, se difiere hasta liberar espacio).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="$ROOT/data/lora-models"; mkdir -p "$DEST"
HF="$HOME/.local/bin/hf"   # huggingface-cli quedó deprecado; el CLI ahora es `hf`

dl() {  # $1=repo $2=file
  if [ -f "$DEST/$2" ]; then echo "✓ ya existe: $2"; return 0; fi
  echo ">>> descargando $2  (repo $1)"
  if "$HF" download "$1" "$2" --local-dir "$DEST"; then echo "✓ OK $2"; else echo "!! FALLÓ $1/$2"; fi
}

# --- Candidatos del carril RÁPIDO (4B, ~2.5GB c/u) ---
dl unsloth/Qwen3-4B-Instruct-2507-GGUF Qwen3-4B-Instruct-2507-Q4_K_M.gguf
dl unsloth/Qwen3.5-4B-GGUF             Qwen3.5-4B-Q4_K_M.gguf

# --- Candidato del carril PROFUNDO (30B-A3B, ~18GB) — solo si cabe ---
FREE_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "${FREE_GB:-0}" -ge 20 ]; then
  dl unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf
else
  echo "— 30B-A3B DIFERIDO: solo ${FREE_GB}GB libres (<20). Liberar espacio primero."
fi
echo "=== DESCARGAS TERMINADAS ==="
ls -lh "$DEST"/*.gguf 2>/dev/null