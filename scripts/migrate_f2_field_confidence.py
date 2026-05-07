"""Migración F2: agregar columna field_confidences_json a tabla cases.

Idempotente — verifica si la columna existe antes de agregarla.
Run: python3 scripts/migrate_f2_field_confidence.py
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "tutelas.db"


def main() -> int:
    if not DB_PATH.exists():
        print(f"❌ DB no encontrada en {DB_PATH}")
        return 1

    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(cases)")
        cols = [row[1] for row in cur.fetchall()]
        if "field_confidences_json" in cols:
            print("✓ Columna field_confidences_json ya existe — no-op")
            return 0
        print("→ Agregando columna field_confidences_json a cases ...")
        cur.execute("ALTER TABLE cases ADD COLUMN field_confidences_json TEXT")
        conn.commit()
        print("✓ Migración completada")
        return 0
    except sqlite3.Error as e:
        print(f"❌ Error SQL: {e}")
        conn.rollback()
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
