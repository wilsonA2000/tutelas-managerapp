#!/usr/bin/env bash
# Migración completa local → pod RunPod.
# Mueve archivos de casos + DB + backend completo + .env al pod.
# Tras esto, el backend corre IN el pod, no en local.
#
# Pre-requisitos:
#   - Pod corriendo en 213.173.107.140:38451 con clave SSH ~/.ssh/id_ed25519
#   - Backend local APAGADO (para garantizar consistencia de DB)
#   - SSH tunnel CERRADO (ya no se necesita)
#
# Uso:
#   bash scripts/migrate_to_pod.sh

set -euo pipefail

POD_HOST=${POD_HOST:-root@213.173.107.140}
POD_PORT=${POD_PORT:-27057}
POD_KEY=~/.ssh/id_ed25519
SSH_OPTS="-i $POD_KEY -p $POD_PORT -o StrictHostKeyChecking=no"
SCP_OPTS="-i $POD_KEY -P $POD_PORT -o StrictHostKeyChecking=no"
RSYNC_SSH="ssh -p $POD_PORT -i $POD_KEY -o StrictHostKeyChecking=no"

LOCAL_ROOT="/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app"
LOCAL_DATA="/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026 B"

POD_BASE="/workspace/tutelas-data"
POD_APP="/workspace/tutelas-app"

echo "=========================================="
echo "Migración local → pod RunPod"
echo "=========================================="
echo "Pod: $POD_HOST:$POD_PORT"
echo "Local data: $LOCAL_DATA"
echo "Pod data: $POD_BASE"
echo ""

# ───────────────────────────────────────────────────────────
# 1. Verificar que backend local esté apagado (sino, DB inconsistente)
# ───────────────────────────────────────────────────────────
if pgrep -f "uvicorn backend.main" > /dev/null; then
    echo "❌ Backend local está corriendo. Apágalo primero:"
    echo "   pkill -f 'uvicorn backend.main'"
    exit 1
fi
echo "[1/7] Backend local apagado ✓"

# ───────────────────────────────────────────────────────────
# 2. Force WAL checkpoint en DB local antes de copiar
# ───────────────────────────────────────────────────────────
echo "[2/7] WAL checkpoint en DB local..."
python3 -c "
import sqlite3
db = '$LOCAL_DATA/tutelas-app/data/tutelas.db'
c = sqlite3.connect(db, timeout=30)
res = c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
print(f'  WAL checkpoint: busy={res[0]} log_pages={res[1]} checkpointed={res[2]}')
c.close()
"

# ───────────────────────────────────────────────────────────
# 3. Crear estructura en pod
# ───────────────────────────────────────────────────────────
echo "[3/7] Creando estructura en pod..."
ssh $SSH_OPTS $POD_HOST "
    mkdir -p $POD_BASE
    mkdir -p $POD_APP/data
    mkdir -p $POD_APP/logs
    mkdir -p $POD_APP/data/backups
"

# ───────────────────────────────────────────────────────────
# 4. Subir backend completo (incluyendo email/, routers/, services/, etc.)
# ───────────────────────────────────────────────────────────
echo "[4/7] Subiendo backend completo..."
scp $SCP_OPTS /tmp/backend_full.tar.gz $POD_HOST:/workspace/
ssh $SSH_OPTS $POD_HOST "
    cd $POD_APP
    tar --no-same-owner --no-same-permissions -xzf /workspace/backend_full.tar.gz
    rm /workspace/backend_full.tar.gz
    # Limpiar caches
    find backend/ -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
"

# ───────────────────────────────────────────────────────────
# 5. Subir .env del pod
# ───────────────────────────────────────────────────────────
echo "[5/7] Subiendo .env.pod → .env..."
scp $SCP_OPTS "$LOCAL_ROOT/.env.pod" "$POD_HOST:$POD_APP/.env"
ssh $SSH_OPTS $POD_HOST "chmod 600 $POD_APP/.env"

# ───────────────────────────────────────────────────────────
# 6. Subir directorio de casos (rsync incremental, 3.3 GB)
# ───────────────────────────────────────────────────────────
echo "[6/7] Rsync directorio de casos (3.3 GB, ~10-15 min)..."
rsync -av --partial --progress -e "$RSYNC_SSH" \
    --exclude='tutelas-app/' \
    --exclude='.git/' \
    --exclude='node_modules/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='logs/' \
    "$LOCAL_DATA/" \
    "$POD_HOST:$POD_BASE/"

# ───────────────────────────────────────────────────────────
# 7. Subir DB final + adjuntos del experimento
# ───────────────────────────────────────────────────────────
echo "[7/7] Subiendo DB SQLite..."
scp $SCP_OPTS "$LOCAL_DATA/tutelas-app/data/tutelas.db" "$POD_HOST:$POD_APP/data/tutelas.db"

# Crear estructura simbólica esperada por el código
ssh $SSH_OPTS $POD_HOST "
    # El código espera que BASE_DIR/tutelas-app/data/tutelas.db exista
    mkdir -p $POD_BASE/tutelas-app/data
    cp $POD_APP/data/tutelas.db $POD_BASE/tutelas-app/data/tutelas.db
"

echo ""
echo "=========================================="
echo "✅ Migración completa"
echo "=========================================="
echo ""
echo "Tamaño en pod:"
ssh $SSH_OPTS $POD_HOST "du -sh $POD_BASE $POD_APP 2>/dev/null"
echo ""
echo "Siguiente paso (en el pod):"
echo "  ssh $SSH_OPTS $POD_HOST"
echo "  cd $POD_APP"
echo "  pkill -f 'uvicorn runpod.server'  # apagar extraction worker"
echo "  nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 > /workspace/backend.log 2>&1 &"
echo "  curl http://localhost:8001/api/cases?limit=1"
echo ""
echo "URL del backend desde tu local:"
echo "  https://q7xtowcydgdkxg-8001.proxy.runpod.net"
echo ""
echo "(Asegúrate de exponer el puerto 8001 en el pod desde la UI de RunPod)"
