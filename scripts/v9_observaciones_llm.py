#!/usr/bin/env python3
"""Backfill del campo `observaciones` con un resumen narrativo del caso (LLM local).

`observaciones` se construye en capas, append-only:
  - banderas (las pone el pase de campos: "Agente oficioso de X", "Se solicitó medida
    provisional", "Sujeto de especial protección: ...")
  - una o varias líneas "[DD/MM/AAAA] <resumen>" — cada vez que llega una actuación nueva
    se añade una línea nueva con su fecha, SIN borrar las anteriores (contexto acumulado).

Este script añade la PRIMERA línea de resumen a los casos que aún no tienen ninguna.
La fecha que usa es la del correo más reciente del caso (proxy de "última actuación"),
o la fecha de hoy si el caso no tiene correos.

Uso:
    ./venv/bin/python3 scripts/v9_observaciones_llm.py --limit 4            # dry-run, 4 casos
    ./venv/bin/python3 scripts/v9_observaciones_llm.py --limit 4 --apply
    ./venv/bin/python3 scripts/v9_observaciones_llm.py --apply              # todos los que falten
    ./venv/bin/python3 scripts/v9_observaciones_llm.py --apply --only-vacios  # solo los de observaciones totalmente vacía
Requiere el llama-server en :8765 (NO pasar V9_DISABLE_LLM=true).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, Email  # noqa: E402
from backend.v9.field_extractor import llm_summarize_case_state, case_has_dated_observacion  # noqa: E402

SHELL_FOLDER = "__SIN_RADICADO__"


def _ultima_actuacion_fecha(db, case: Case) -> str:
    """DD/MM/AAAA del correo más reciente del caso; hoy si no tiene correos."""
    e = (db.query(Email).filter(Email.case_id == case.id, Email.date_received.isnot(None))
         .order_by(Email.date_received.desc()).first())
    dt = e.date_received if e and e.date_received else datetime.now()
    return dt.strftime("%d/%m/%Y")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="escribe a DB (sin esto: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="procesar solo los primeros N casos (0 = todos)")
    ap.add_argument("--only-vacios", action="store_true",
                    help="solo casos con observaciones totalmente vacía (no los que ya tienen banderas)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Case).filter(
            Case.folder_name.isnot(None), Case.folder_name != "", Case.folder_name != "None",
            Case.folder_name != SHELL_FOLDER, Case.processing_status != "DUPLICATE_MERGED",
        ).order_by(Case.id)
        cases = q.all()
        # filtrar: solo los que aún NO tienen una línea de resumen fechada
        pend = [c for c in cases if not case_has_dated_observacion(c)]
        if args.only_vacios:
            pend = [c for c in pend if not (c.observaciones or "").strip()]
        if args.limit:
            pend = pend[: args.limit]

        print(f"Casos sin resumen fechado: {len(pend)} (de {len(cases)} en el cuadro).")
        print(f"Modo: {'APPLY' if args.apply else 'DRY-RUN'}\n")

        n_ok = n_skip = n_fail = 0
        for i, c in enumerate(pend, 1):
            summ = llm_summarize_case_state(db, c)
            if not summ:
                n_skip += 1
                print(f"  [{i}/{len(pend)}] #{c.id} '{(c.folder_name or '')[:40]}'  → (sin resumen — datos pobres)")
                continue
            fecha = _ultima_actuacion_fecha(db, c)
            line = f"[{fecha}] {summ}"
            base = (c.observaciones or "").rstrip()
            new_obs = f"{base}\n{line}" if base else line
            n_ok += 1
            print(f"  [{i}/{len(pend)}] #{c.id} '{(c.folder_name or '')[:40]}'")
            print(f"       {line}")
            if args.apply:
                c.observaciones = new_obs
                db.commit()
        print(f"\n{'─'*64}")
        print(f"{n_ok} resúmenes {'escritos' if args.apply else 'generados (dry-run)'}; {n_skip} omitidos (datos pobres); {n_fail} errores.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
