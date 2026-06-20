#!/bin/bash
# Tutelas Manager - Script de inicio
# Lanza backend (FastAPI) y frontend (React) simultaneamente

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  TUTELAS MANAGER - Gobernacion de Santander"
echo "=========================================="
echo ""

# Activar venv si existe (necesario en Linux después de migrar de Windows)
if [ -f "$DIR/venv/bin/activate" ]; then
    source "$DIR/venv/bin/activate"
    echo "venv activado: $(which python3)"
fi

# Activar SOLO los flags Rama Judicial desde .env hacia el entorno del proceso
# (el backend los lee con os.getenv; start.sh no cargaba .env, así que sin esto
# quedaban inertes). A propósito NO se exporta el resto del .env: otros flags
# os.getenv (GMAIL_READ_ONLY, USE_COGNITIVE_PIPELINE, …) corren en sus defaults
# probados y activarlos en bloque sería riesgoso. Ver project_env_flags_inertes.
if [ -f "$DIR/.env" ]; then
    export $(grep -E '^RAMA_JUDICIAL_(ENABLED|SYNC_CRON)=' "$DIR/.env" | xargs)
fi

# Matar procesos previos en los puertos
fuser -k 8000/tcp 2>/dev/null
fuser -k 5173/tcp 2>/dev/null

# Iniciar backend
echo "[1/2] Iniciando backend (FastAPI) en puerto 8000..."
cd "$DIR"
# --host 127.0.0.1: la API NO es alcanzable desde otras máquinas de la red local
# (defensa en profundidad junto al AuthMiddleware). El proxy de Vite (/api →
# localhost:8000) la alcanza igual porque corre en el mismo host.
"$DIR/venv/bin/python3" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

# Iniciar frontend
echo "[2/2] Iniciando frontend (React) en puerto 5173..."
cd "$DIR/frontend"
npm run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!

echo ""
echo "=========================================="
echo "  Aplicacion lista!"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000"
echo "  API Docs: http://localhost:8000/docs"
echo "=========================================="
echo ""
echo "Presiona Ctrl+C para detener ambos servidores"

# Esperar a que terminen
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
