#!/usr/bin/env python3
"""Re-extrae los casos del experimento v5.5 con las mejoras deterministas.

Pasos:
1. WAL checkpoint + backup DB (pre_reextract_v55)
2. Snapshot JSON de campos actuales para diff posterior
3. Reset COMPLETO/REVISION → PENDIENTE
4. POST /api/extraction/batch
5. Lanza experiment_monitor para auto-retomar huérfanos

Uso:
    python3 scripts/reextract_v55.py           # interactivo, pide confirmación
    python3 scripts/reextract_v55.py --yes     # sin prompt
    python3 scripts/reextract_v55.py --only-revision  # solo REVISION
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DB_EXPERIMENT = "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026 A/tutelas-app/data/tutelas.db"
APP_DIR = Path("/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app")
BACKEND_URL = "http://localhost:8000"

SNAPSHOT_FIELDS = [
    "id", "radicado_23_digitos", "radicado_forest", "accionante", "accionados",
    "vinculados", "derecho_vulnerado", "juzgado", "ciudad", "fecha_ingreso",
    "asunto", "pretensiones", "oficina_responsable", "sentido_fallo_1st",
    "fecha_fallo_1st", "impugnacion", "quien_impugno", "sentido_fallo_2nd",
    "fecha_fallo_2nd", "responsable_desacato", "decision_incidente",
    "observaciones", "processing_status",
]


def snapshot(db_path: str, out_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cols = ", ".join(SNAPSHOT_FIELDS)
        rows = cur.execute(f"SELECT {cols} FROM cases").fetchall()
        data = [dict(zip(SNAPSHOT_FIELDS, r)) for r in rows]
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return len(data)
    finally:
        conn.close()


def reset_to_pendiente(db_path: str, only_revision: bool) -> int:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        cur = conn.cursor()
        if only_revision:
            cur.execute("UPDATE cases SET processing_status='PENDIENTE' WHERE processing_status='REVISION'")
        else:
            cur.execute("UPDATE cases SET processing_status='PENDIENTE' "
                        "WHERE processing_status IN ('COMPLETO', 'REVISION', 'EXTRAYENDO')")
        n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def http_post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BACKEND_URL}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def http_get(path: str) -> dict:
    with urllib.request.urlopen(f"{BACKEND_URL}{path}", timeout=10) as r:
        return json.loads(r.read())


def backend_alive() -> bool:
    try:
        http_get("/api/settings/status")
        return True
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-extracción v5.5 sobre DB experimental")
    parser.add_argument("--yes", action="store_true", help="No pedir confirmación")
    parser.add_argument("--only-revision", action="store_true", help="Solo casos en REVISION")
    parser.add_argument("--db", default=DB_EXPERIMENT, help="Ruta DB a usar")
    parser.add_argument("--skip-monitor", action="store_true", help="No lanzar monitor")
    args = parser.parse_args()

    db = args.db
    if not Path(db).exists():
        print(f"ERROR: DB no existe: {db}")
        return 1

    if not backend_alive():
        print(f"ERROR: backend no responde en {BACKEND_URL}. Arráncalo primero.")
        return 1

    # Paso 1: WAL checkpoint + backup
    stamp = time.strftime("%Y%m%d_%H%M%S")
    conn = sqlite3.connect(db, timeout=30)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    bak = f"{db}.pre_reextract_v55_{stamp}.bak"
    shutil.copy2(db, bak)
    print(f"[1/5] Backup: {bak}")

    # Paso 2: snapshot pre
    snap_pre = APP_DIR / "logs" / f"snapshot_pre_reextract_v55_{stamp}.json"
    n = snapshot(db, snap_pre)
    print(f"[2/5] Snapshot pre: {snap_pre} ({n} casos)")

    # Estado actual
    conn = sqlite3.connect(db)
    state = dict(conn.execute("SELECT processing_status, COUNT(*) FROM cases GROUP BY processing_status").fetchall())
    conn.close()
    print(f"      Estado actual: {state}")

    # Paso 3: confirmación
    if not args.yes:
        scope = "REVISION" if args.only_revision else "COMPLETO + REVISION + EXTRAYENDO"
        print(f"\n⚠️  Voy a resetear {scope} → PENDIENTE y disparar re-extracción.")
        ans = input("¿Proceder? [y/N]: ").strip().lower()
        if ans != "y":
            print("Cancelado.")
            return 0

    # Paso 4: reset
    n_reset = reset_to_pendiente(db, args.only_revision)
    print(f"[3/5] Reset: {n_reset} casos → PENDIENTE")

    # Paso 5: disparar batch
    try:
        r = http_post("/api/extraction/batch", {})
        print(f"[4/5] Batch disparado: {r}")
    except Exception as e:
        print(f"ERROR disparando batch: {e}")
        return 1

    # Paso 6: monitor
    if args.skip_monitor:
        print("[5/5] Monitor saltado (--skip-monitor)")
    else:
        monitor_log = APP_DIR / "logs" / f"reextract_monitor_stdout_{stamp}.log"
        p = subprocess.Popen(
            ["python3", "scripts/experiment_monitor.py"],
            cwd=str(APP_DIR),
            stdout=open(monitor_log, "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        print(f"[5/5] Monitor lanzado: PID {p.pid} (log: {monitor_log})")

    print(f"\nTodo listo. Dashboard: {APP_DIR}/logs/experiment_monitor.md")
    print(f"Snapshot pre: {snap_pre}")
    print(f"Cuando termine, corre: python3 scripts/compare_extraction_v55.py {snap_pre}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
