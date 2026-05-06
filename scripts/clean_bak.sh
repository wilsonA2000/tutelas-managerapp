#!/usr/bin/env bash
# scripts/clean_bak.sh — elimina archivos .bak de respaldos puntuales en backend/
#
# Uso:
#   bash scripts/clean_bak.sh            # lista y pide confirmación
#   bash scripts/clean_bak.sh --force    # borra sin preguntar
#
# Patrones cubiertos:
#   - *.bak
#   - *.pre_*.bak
# Sólo dentro de backend/. NO toca data/ ni docs/.
set -euo pipefail

cd "$(dirname "$0")/.."

mapfile -t FILES < <(find backend -type f \( -name "*.bak" -o -name "*.pre_*.bak" \) 2>/dev/null | sort)

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No hay archivos .bak en backend/."
  exit 0
fi

echo "Archivos .bak encontrados (${#FILES[@]}):"
printf '  %s\n' "${FILES[@]}"
echo

if [[ "${1:-}" != "--force" ]]; then
  read -r -p "¿Eliminar los ${#FILES[@]} archivos? (yes/NO): " CONF
  if [[ "$CONF" != "yes" ]]; then
    echo "Abortado."
    exit 1
  fi
fi

for f in "${FILES[@]}"; do
  rm -- "$f"
done

echo "Eliminados ${#FILES[@]} archivos."
