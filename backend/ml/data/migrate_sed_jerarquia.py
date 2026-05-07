"""Migración v8.0: agregar columnas direccion/grupo/equipo a tabla cases.

Pobla los 213 casos existentes mapeando desde `oficina_responsable` actual.
Idempotente: si las columnas ya existen, no falla.

Uso:
    python -m backend.ml.data.migrate_sed_jerarquia
"""

from __future__ import annotations
import logging
from sqlalchemy import text

from backend.database.database import SessionLocal, engine
from backend.ml.data.normalizers import normalize_dependencia
from backend.ml.data.sed_org import get_l1, get_unit

logger = logging.getLogger("tutelas.ml.migrate_sed")


def column_exists(db, table: str, col: str) -> bool:
    rows = db.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def migrate():
    db = SessionLocal()
    try:
        # 1) Agregar columnas si faltan
        for col, ddl in [
            ("direccion", "ALTER TABLE cases ADD COLUMN direccion TEXT"),
            ("grupo",     "ALTER TABLE cases ADD COLUMN grupo TEXT"),
            ("equipo",    "ALTER TABLE cases ADD COLUMN equipo TEXT"),
        ]:
            if not column_exists(db, "cases", col):
                db.execute(text(ddl))
                logger.info("Columna %s agregada", col)
            else:
                logger.info("Columna %s ya existe", col)
        db.commit()

        # 2) Crear índices
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS ix_cases_direccion ON cases(direccion)",
            "CREATE INDEX IF NOT EXISTS ix_cases_grupo ON cases(grupo)",
        ]:
            db.execute(text(idx_sql))
        db.commit()

        # 3) Popular L1/L2/L3 desde oficina_responsable existente
        rows = db.execute(text("""
            SELECT id, oficina_responsable FROM cases
            WHERE oficina_responsable IS NOT NULL AND oficina_responsable != ''
              AND (direccion IS NULL OR grupo IS NULL)
        """)).fetchall()
        n_updated = 0
        for case_id, oficina_raw in rows:
            code = normalize_dependencia(oficina_raw)
            unit = get_unit(code)
            if not unit:
                continue
            l1_code = get_l1(code)
            if unit.level == 3:
                # equipo bajo Financiera
                grupo_code = unit.parent  # FINANCIERA
                equipo_code = unit.code
            elif unit.level == 2:
                grupo_code = unit.code
                equipo_code = None
            else:
                # L1 directo (caso genérico tipo "TALENTO HUMANO" sin grupo específico)
                grupo_code = None
                equipo_code = None

            db.execute(text("""
                UPDATE cases SET direccion=:d, grupo=:g, equipo=:e WHERE id=:id
            """), {"d": l1_code, "g": grupo_code, "e": equipo_code, "id": case_id})
            n_updated += 1
        db.commit()
        logger.info("Popular jerarquía: %d casos actualizados", n_updated)

        # 4) Reporte de cobertura
        print("\n=== COBERTURA POST-MIGRACIÓN ===")
        for col in ("direccion", "grupo", "equipo"):
            n = db.execute(text(f"SELECT COUNT(*) FROM cases WHERE {col} IS NOT NULL AND {col} != ''")).scalar()
            print(f"  {col}: {n}")
        print("\n=== Distribución direccion (L1) ===")
        for r in db.execute(text(
            "SELECT direccion, COUNT(*) n FROM cases WHERE direccion IS NOT NULL GROUP BY direccion ORDER BY n DESC"
        )).fetchall():
            print(f"  {r[1]:>4}  {r[0]}")
        print("\n=== Distribución grupo (L2) ===")
        for r in db.execute(text(
            "SELECT grupo, COUNT(*) n FROM cases WHERE grupo IS NOT NULL GROUP BY grupo ORDER BY n DESC"
        )).fetchall():
            print(f"  {r[1]:>4}  {r[0]}")

    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    migrate()
