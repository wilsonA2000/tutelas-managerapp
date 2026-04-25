"""Reescribe paths absolutos /mnt/c/... → /workspace/tutelas-data/... en una copia
de la DB SQLite, para subirla al pod.

Uso:
    python3 scripts/rewrite_paths_for_pod.py
        [--src "/path/local/tutelas.db"]
        [--dst "/tmp/tutelas_pod.db"]

Hace una COPIA antes de modificar para no tocar la DB original.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


DEFAULT_SRC = "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026 B/tutelas-app/data/tutelas.db"
DEFAULT_DST = "/tmp/tutelas_pod.db"

LOCAL_PREFIX = "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026 B"
POD_PREFIX = "/workspace/tutelas-data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--dst", default=DEFAULT_DST)
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)

    if not src.exists():
        print(f"❌ DB origen no existe: {src}")
        return 1

    print(f"Origen: {src}  ({src.stat().st_size / 1_048_576:.1f} MB)")
    print(f"Destino: {dst}")
    print(f"Reemplazo: '{LOCAL_PREFIX}' → '{POD_PREFIX}'")
    print()

    # 1. Copiar la DB
    print("[1/3] Copiando DB...")
    shutil.copy2(src, dst)
    # WAL/SHM si existen
    for ext in ("-wal", "-shm"):
        wal_src = src.with_suffix(src.suffix + ext)
        if wal_src.exists():
            shutil.copy2(wal_src, dst.with_suffix(dst.suffix + ext))

    # 2. Aplicar UPDATE en documents.file_path y cases.folder_path
    # journal_mode=DELETE escribe directo a la DB principal sin WAL separado
    # (necesario para que la DB sea autocontenida al subirla al pod).
    print("[2/3] Reescribiendo paths...")
    c = sqlite3.connect(str(dst), timeout=30)
    c.execute("PRAGMA journal_mode=DELETE")
    c.execute("PRAGMA foreign_keys=ON")

    # Documents
    cur = c.execute(
        "UPDATE documents SET file_path = REPLACE(file_path, ?, ?) WHERE file_path LIKE ?",
        (LOCAL_PREFIX, POD_PREFIX, f"{LOCAL_PREFIX}%"),
    )
    print(f"  documents.file_path actualizados: {cur.rowcount}")

    # Cases (folder_path)
    cur = c.execute(
        "UPDATE cases SET folder_path = REPLACE(folder_path, ?, ?) WHERE folder_path LIKE ?",
        (LOCAL_PREFIX, POD_PREFIX, f"{LOCAL_PREFIX}%"),
    )
    print(f"  cases.folder_path actualizados: {cur.rowcount}")

    # Por si hay paths con backslash de Windows mal-normalizados
    cur = c.execute(
        "UPDATE documents SET file_path = REPLACE(file_path, ?, ?) WHERE file_path LIKE ?",
        ("\\", "/", "%\\%"),
    )
    print(f"  documents backslash → forward: {cur.rowcount}")

    c.commit()
    c.close()
    # Borrar -wal y -shm si existen del .db destino (ya no se necesitan)
    for ext in ("-wal", "-shm"):
        wal = dst.with_suffix(dst.suffix + ext)
        if wal.exists():
            wal.unlink()

    # 3. Verificación
    print("[3/3] Verificación...")
    c = sqlite3.connect(str(dst))
    pod_count = c.execute(
        "SELECT COUNT(*) FROM documents WHERE file_path LIKE '/workspace%'"
    ).fetchone()[0]
    mnt_count = c.execute(
        "SELECT COUNT(*) FROM documents WHERE file_path LIKE '/mnt/c%'"
    ).fetchone()[0]
    total = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    print(f"  documents total: {total}")
    print(f"  documents con /workspace/: {pod_count}")
    print(f"  documents con /mnt/c/: {mnt_count}  (debe ser 0)")
    print()
    print("Sample paths nuevos:")
    for row in c.execute("SELECT file_path FROM documents LIMIT 3"):
        print(f"  {row[0][:120]}")
    c.close()

    if mnt_count > 0:
        print(f"\n⚠️  Aún quedan {mnt_count} paths con /mnt/c/. Revisa.")
        return 2

    print(f"\n✅ DB lista para subir al pod: {dst}")
    print(f"   Tamaño: {dst.stat().st_size / 1_048_576:.1f} MB")
    print(f"\nSiguiente paso:")
    print(f"  scp -P 27057 -i ~/.ssh/id_ed25519 {dst} \\")
    print(f"      root@213.173.107.140:/workspace/tutelas-app/data/tutelas.db")
    return 0


if __name__ == "__main__":
    sys.exit(main())
