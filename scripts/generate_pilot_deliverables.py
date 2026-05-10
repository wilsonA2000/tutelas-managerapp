"""Genera los entregables del piloto:
- cuadro_ground_truth_piloto_<fecha>.xlsx (3 hojas, formato espejo de excel_generator)
- cuadro_ground_truth_piloto.json (un caso por entrada)
- diff_piloto.md (vs DB archivada)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case  # noqa: E402
from backend.reports.excel_generator import generate_excel  # noqa: E402

OUT = Path("/home/wilsonarguello/iuris-data/_ground_truth")
TODAY = date.today().isoformat()

ARCHIVED_DB = Path("/home/wilsonarguello/iuris-data/_archive_2026-05-09/data_corrupt/tutelas.db")


def main():
    db = SessionLocal()
    try:
        cases = db.query(Case).order_by(Case.radicado_23_digitos).all()
        print(f"Loaded {len(cases)} cases from DB")

        # Excel
        xlsx_path = OUT / f"cuadro_ground_truth_piloto_{TODAY}.xlsx"
        generate_excel(cases, str(xlsx_path))
        print(f"Excel: {xlsx_path}")

        # JSON consolidado
        consolidated = []
        for c in cases:
            consolidated.append(c.to_dict(include_doc_count=True))
        json_path = OUT / "cuadro_ground_truth_piloto.json"
        json_path.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {json_path}")

        # Diff vs DB archivada
        diff_lines = ["# Diff piloto vs plataforma anterior\n"]
        diff_lines.append(f"DB archivada: `{ARCHIVED_DB}`\n")
        diff_lines.append(f"Casos en ground truth piloto: **{len(cases)}**\n")

        if ARCHIVED_DB.exists():
            arc = sqlite3.connect(f"file:{ARCHIVED_DB}?mode=ro", uri=True)
            arc.row_factory = sqlite3.Row
            cur = arc.cursor()

            matched = 0
            new_in_gt = []
            for c in cases:
                rad23 = c.radicado_23_digitos
                # buscar por radicado_23 limpio
                rad23_clean = rad23.replace("-", "")
                cur.execute(
                    "SELECT id, folder_name, accionante, sentido_fallo_1st, ciudad, "
                    "fecha_fallo_1st, impugnacion, incidente "
                    "FROM cases WHERE replace(radicado_23_digitos,'-','') = ?",
                    (rad23_clean,),
                )
                row = cur.fetchone()
                if row:
                    matched += 1
                    diff_lines.append(f"\n## {rad23} — {c.accionante or 'SIN_ACCIONANTE'}")
                    diff_lines.append("\n| Campo | Ground truth (Claude) | Plataforma (DB anterior) |")
                    diff_lines.append("|---|---|---|")
                    for fld, gt_val, db_val in [
                        ("ACCIONANTE", c.accionante, row["accionante"]),
                        ("CIUDAD", c.ciudad, row["ciudad"]),
                        ("SENTIDO_FALLO_1ST", c.sentido_fallo_1st, row["sentido_fallo_1st"]),
                        ("FECHA_FALLO_1ST", c.fecha_fallo_1st, row["fecha_fallo_1st"]),
                        ("IMPUGNACION", c.impugnacion, row["impugnacion"]),
                        ("INCIDENTE", c.incidente, row["incidente"]),
                    ]:
                        gt_str = (gt_val or "").strip() or "_(vacío)_"
                        db_str = (db_val or "").strip() or "_(vacío)_"
                        veredicto = "✅" if gt_str == db_str else "⚠️"
                        diff_lines.append(f"| {fld} | {gt_str} | {db_str} | {veredicto}")
                else:
                    new_in_gt.append(rad23)

            diff_lines.append(f"\n---\n\n## Resumen\n")
            diff_lines.append(f"- **Coincidencias por radicado_23**: {matched}/{len(cases)}")
            diff_lines.append(f"- **Nuevos en ground truth (no estaban en plataforma)**: {len(new_in_gt)}")
            if new_in_gt:
                diff_lines.append("\nRadicados nuevos:\n")
                for r in new_in_gt:
                    diff_lines.append(f"- `{r}`")

            arc.close()
        else:
            diff_lines.append("\n_(DB archivada no encontrada, diff omitido)_\n")

        diff_path = OUT / "diff_piloto.md"
        diff_path.write_text("\n".join(diff_lines), encoding="utf-8")
        print(f"Diff: {diff_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
