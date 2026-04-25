#!/usr/bin/env bash
# Empaqueta lo mínimo necesario para subir al pod RunPod.
# Excluye: .env, data/, logs/, node_modules/, archivos de pruebas pesados.
#
# Genera: /tmp/tutelas_pod_<timestamp>.tar.gz
# Subirlo al pod con: scp /tmp/tutelas_pod_<ts>.tar.gz user@<pod-ip>:/workspace/

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TS=$(date +%Y%m%d_%H%M%S)
OUT="/tmp/tutelas_pod_${TS}.tar.gz"

echo "Empaquetando desde: $ROOT"
echo "Salida: $OUT"

tar --exclude='data/*' \
    --exclude='logs/*' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='frontend' \
    --exclude='tests' \
    --exclude='docs' \
    --exclude='scripts/archive' \
    --exclude='runpod/models' \
    --exclude='runpod/cache' \
    --exclude='runpod/tmp_cases' \
    -czf "$OUT" \
    backend/ \
    runpod/ \
    requirements.txt

echo "Hecho. Tamaño:"
ls -lh "$OUT" | awk '{print $5, $9}'
echo ""
echo "Para subir al pod RunPod:"
echo "  1. Copia el archivo al pod (web terminal, drag-and-drop, o scp)."
echo "  2. En el pod:"
echo "     cd /workspace"
echo "     mkdir -p tutelas-app && tar -xzf tutelas_pod_${TS}.tar.gz -C tutelas-app"
echo "     cd tutelas-app"
echo "     bash runpod/setup.sh"
echo "     export MODEL_SERVER_TOKEN=\$(openssl rand -hex 32)"
echo "     echo \"Token (guárdalo):\" \$MODEL_SERVER_TOKEN"
echo "     python runpod/preload_models.py"
echo "     bash runpod/start_server.sh"
