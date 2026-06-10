#!/usr/bin/env python3
"""
Aplica los cambios aceptados del barrido DeepSeek a la DB.

SIEMPRE aplica primero a la DB de EXPERIMENTO. Solo tras confirmación
explícita aplica a producción.

Modos:
  --mode fill-empty   Aplica SOLO diffs VERDE (current="" → proposed!="")
  --mode all-non-manual  Aplica VERDE + AMARILLO (excluye ROJO/manual)
  --from-csv FILE     Aplica filas de un CSV personalizado (col semaforo != ROJO)

Targets:
  --target experiment   Escribe en data/experiment/tutelas_experiment.db (default)
  --target prod         Escribe en data/tutelas.db (hace backup automático antes)

Uso típico:
    # 1. Revisar qué se aplicaría
    python3 scripts/deepseek_sweep/apply_accepted.py --mode fill-empty --dry-run

    # 2. Aplicar a experimento y verificar en la app
    python3 scripts/deepseek_sweep/apply_accepted.py --mode fill-empty --target experiment

    # 3. Cuando OK, aplicar a prod
    python3 scripts/deepseek_sweep/apply_accepted.py --mode fill-empty --target prod

Reglas innegociables:
  - Campos ROJO (manual) NUNCA se tocan, en ningún modo ni target.
  - En prod, siempre backup automático antes de escribir.
  - El script actualiza field_confidences_json.v9_sources con source "llm" o "regex".
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import sqlalchemy  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from backend.database.models import Case  # noqa: E402

RESULTS_DIR = ROOT / "data" / "experiment" / "results"
EXPERIMENT_DB = ROOT / "data" / "experiment" / "tutelas_experiment.db"
PROD_DB = ROOT / "data" / "tutelas.db"


def load_diffs(mode: str, from_csv: str | None) -> list[dict]:
    """Carga los diffs a aplicar según el modo."""
    rows = []

    if from_csv:
        with open(from_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("semaforo", "") != "ROJO":
                    rows.append(row)
        return rows

    for p in sorted(RESULTS_DIR.glob("*.json")):
        if p.name in ("checkpoint.json",) or "ERROR" in p.name:
            continue
        try:
            res = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        for d in res.get("diff", []):
            sem = d.get("semaforo", "")
            if sem == "ROJO":
                continue
            if mode == "fill-empty" and sem != "VERDE":
                continue
            # mode == "all-non-manual" acepta VERDE + AMARILLO
            rows.append({
                "case_id": res["case_id"],
                "folder_name": res.get("folder_name", ""),
                "campo": d["campo"],
                "semaforo": sem,
                "current": d["current"],
                "proposed": d["proposed"],
                "source": d.get("source", ""),
            })
    return rows


def update_sources_json(existing_json: str | None, campo: str, source: str) -> str:
    """Actualiza field_confidences_json.v9_sources para el campo dado."""
    try:
        data = json.loads(existing_json or "{}")
    except (json.JSONDecodeError, TypeError):
        data = {}
    sources = data.get("v9_sources", {})
    sources[campo] = source
    data["v9_sources"] = sources
    return json.dumps(data, ensure_ascii=False)


def apply_rows(db_path: Path, rows: list[dict], dry_run: bool) -> dict:
    engine = sqlalchemy.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    # Agrupar por case_id para una sola transacción por caso
    by_case: dict[int, list[dict]] = {}
    for r in rows:
        cid = int(r["case_id"])
        by_case.setdefault(cid, []).append(r)

    stats = {"updated": 0, "skipped_manual": 0, "case_errors": 0, "field_updates": 0}

    db = Session()
    try:
        for case_id, changes in by_case.items():
            case = db.query(Case).filter(Case.id == case_id).first()
            if not case:
                stats["case_errors"] += 1
                continue

            # Verificar protección manual fresh desde la DB
            try:
                raw = case.field_confidences_json or ""
                manual_set = {k for k, v in json.loads(raw).get("v9_sources", {}).items() if v == "manual"}
            except (json.JSONDecodeError, TypeError):
                manual_set = set()

            applied_fields = []
            for ch in changes:
                campo = ch["campo"]
                if campo in manual_set:
                    stats["skipped_manual"] += 1
                    continue
                proposed = ch["proposed"]
                if not proposed:
                    continue
                # fill-only: no pisar valores existentes (respeta la jerarquía fill-only)
                # Para VERDE esto siempre aplica (current es vacío)
                # Para AMARILLO: el operador eligió explícitamente este modo, se aplica
                if not dry_run:
                    setattr(case, campo, proposed)
                    case.field_confidences_json = update_sources_json(
                        case.field_confidences_json, campo, ch.get("source", "llm")
                    )
                applied_fields.append(campo)
                stats["field_updates"] += 1

            if applied_fields:
                stats["updated"] += 1
                if dry_run:
                    print(f"  [DRY] case {case_id}: {applied_fields}")

        if not dry_run:
            db.commit()
    except Exception as exc:
        db.rollback()
        print(f"ERROR en transacción: {exc}")
        raise
    finally:
        db.close()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Aplicar diffs aceptados del barrido DeepSeek")
    parser.add_argument(
        "--mode", choices=["fill-empty", "all-non-manual"], default="fill-empty",
        help="fill-empty=solo VERDE; all-non-manual=VERDE+AMARILLO",
    )
    parser.add_argument("--from-csv", help="CSV de diffs a aplicar (override de --mode)")
    parser.add_argument(
        "--target", choices=["experiment", "prod"], default="experiment",
        help="DB destino (default: experiment — NUNCA prod sin revisión previa)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Solo imprimir, no escribir")
    args = parser.parse_args()

    rows = load_diffs(args.mode, args.from_csv)
    if not rows:
        print("Sin diffs a aplicar. Corre primero run_sweep.py y build_diff_report.py.")
        sys.exit(0)

    n_verde = sum(1 for r in rows if r["semaforo"] == "VERDE")
    n_amarillo = sum(1 for r in rows if r["semaforo"] == "AMARILLO")
    print(f"Diffs cargados: {len(rows)} ({n_verde} VERDE, {n_amarillo} AMARILLO)")

    if args.target == "prod":
        db_path = PROD_DB
        if not args.dry_run:
            # Backup automático obligatorio
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bak = PROD_DB.with_name(f"tutelas.db.bak_pre_deepseek_apply_{ts}")
            shutil.copy2(PROD_DB, bak)
            print(f"Backup creado: {bak}")
            confirm = input(
                f"\n⚠ CONFIRMAR escritura a PRODUCCIÓN ({len(rows)} cambios).\n"
                "Escribe 'SI APLICAR' para continuar: "
            ).strip()
            if confirm != "SI APLICAR":
                print("Abortado.")
                sys.exit(0)
    else:
        db_path = EXPERIMENT_DB
        if not db_path.exists():
            print(f"ERROR: {db_path} no existe. Corre primero el setup.")
            print("  cp data/tutelas.db data/experiment/tutelas_experiment.db")
            sys.exit(1)
        print(f"Target: EXPERIMENTO ({db_path})")

    if args.dry_run:
        print("\n[DRY-RUN] No se escribe nada. Cambios que se aplicarían:")

    t0 = time.perf_counter()
    stats = apply_rows(db_path, rows, dry_run=args.dry_run)
    elapsed = time.perf_counter() - t0

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}RESULTADO:")
    print(f"  Cases actualizados: {stats['updated']}")
    print(f"  Campos actualizados: {stats['field_updates']}")
    print(f"  Saltados (manual protegido): {stats['skipped_manual']}")
    print(f"  Errores de case: {stats['case_errors']}")
    print(f"  Tiempo: {elapsed:.1f}s")

    if not args.dry_run and args.target == "experiment":
        print(f"\nExperimento aplicado. Verifica en la app (cambia DB_PATH o usa la copia).")
        print("Cuando OK:")
        print("  python3 scripts/deepseek_sweep/apply_accepted.py --mode fill-empty --target prod")


if __name__ == "__main__":
    main()
