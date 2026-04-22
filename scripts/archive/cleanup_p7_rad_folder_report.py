"""P7 — Reporte de inconsistencias rad23 vs folder_name.

NO ejecuta cambios automáticos. Genera lista para revisión humana con
sugerencia basada en cuál fuente parece más confiable:
- Si folder_name fue recientemente editado manualmente → creer al folder
- Si rad23 viene de múltiples documentos → creer al rad23

Salida: logs/rad_folder_inconsistencies_<fecha>.md
"""

import re
import sys
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from sqlalchemy import text
from backend.database.database import SessionLocal


def main():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT c.id, c.folder_name, c.radicado_23_digitos, c.accionante,
                   c.fecha_ingreso, c.updated_at,
                   (SELECT COUNT(*) FROM audit_log a WHERE a.case_id=c.id AND a.field_name='folder_name') as folder_edits,
                   (SELECT COUNT(*) FROM audit_log a WHERE a.case_id=c.id AND a.field_name='radicado_23_digitos') as rad_edits
            FROM cases c
            WHERE c.radicado_23_digitos IS NOT NULL AND c.folder_name IS NOT NULL
        """)).fetchall()

        inconsistencies = []
        for r in rows:
            cid, folder, rad, acc, fecha, updated, folder_edits, rad_edits = r
            m = re.search(r"(\d{4,5})-\d{2}$", rad)
            if not m:
                continue
            rad_cons = m.group(1).lstrip("0")
            fm = re.match(r"(20\d{2})-(\d{4,6})", folder)
            if not fm:
                continue
            folder_cons = fm.group(2).lstrip("0")
            if rad_cons == folder_cons:
                continue

            # Sugerencia
            if rad_edits > folder_edits:
                suggest = f"creer rad23 (editado {rad_edits}x vs folder {folder_edits}x)"
            elif folder_edits > rad_edits:
                suggest = f"creer folder (editado {folder_edits}x vs rad {rad_edits}x)"
            else:
                suggest = "revisión manual (ediciones iguales)"

            inconsistencies.append({
                "case_id": cid,
                "folder": folder,
                "rad23": rad,
                "rad_cons": rad_cons,
                "folder_cons": folder_cons,
                "suggest": suggest,
                "accionante": acc,
            })

        out_dir = APP / "logs"
        out_dir.mkdir(exist_ok=True)
        out = out_dir / f"rad_folder_inconsistencies_{datetime.now().strftime('%Y%m%d')}.md"

        lines = []
        lines.append(f"# Inconsistencias rad23 vs folder_name — {datetime.now():%Y-%m-%d %H:%M}")
        lines.append("")
        lines.append(f"Total: **{len(inconsistencies)}** casos")
        lines.append("")
        lines.append("| Case | Accionante | rad consecutivo | folder consecutivo | Sugerencia |")
        lines.append("|---|---|---|---|---|")
        for x in inconsistencies:
            acc = (x["accionante"] or "")[:30]
            lines.append(f"| #{x['case_id']} | {acc} | {x['rad_cons']} | {x['folder_cons']} | {x['suggest']} |")

        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"Reporte: {out}")
        print(f"Inconsistencias detectadas: {len(inconsistencies)}")
        print("\n(Requiere revisión humana caso por caso)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
