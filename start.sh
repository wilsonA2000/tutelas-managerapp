#!/bin/bash
# Tutelas Manager - Script de inicio
# Lanza backend (FastAPI) y frontend (React) simultaneamente

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  TUTELAS MANAGER - Gobernacion de Santander"
echo "=========================================="
echo ""

# Matar procesos previos en los puertos
fuser -k 8000/tcp 2>/dev/null
fuser -k 5173/tcp 2>/dev/null

# Iniciar backend
echo "[1/2] Iniciando backend (FastAPI) en puerto 8000..."
cd "$DIR"
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
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
