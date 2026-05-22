#!/usr/bin/env python3
"""Escaneo PROACTIVO de conflación cross-juzgado sobre TODA la DB.

A diferencia del gate de extracción (que corre sobre un caso puntual), este script
recorre todos los casos y reporta los que tienen documentos con radicado propio de
un juzgado distinto al del caso — la firma de las carpetas mezcladas por rad corto
compartido (c23/c129/c62, etc.).

Usa `backend.v9.folder_consistency.check_folder_consistency`, que ya cubre:
- el punto ciego de rad23 NULL (deriva identidad por juzgado mayoritario de los docs)
- la exclusión de remisiones por competencia (acta de reparto) y escalamiento a 2da.

Uso:
    python3 scripts/scan_conflacion.py            # reporte legible
    python3 scripts/scan_conflacion.py --json     # salida JSON
    python3 scripts/scan_conflacion.py --strict   # exit 1 si hay CONFLACION/RAD_AJENO
    python3 scripts/scan_conflacion.py --mark      # marca los docs ajenos verificacion=SOSPECHOSO

GATE POST-INGESTA: correr con --mark DESPUÉS de cada ingesta+extracción (junto a
reconcile_post_ingest.py). El filename en el attach del monitor solo trae el rad
corto, no el juzgado (que sale del texto extraído), así que el chequeo fiable es
aquí, cuando ya hay extracted_text. Un doc SOSPECHOSO no alimenta la extracción
silenciosamente: folder_consistency lo ve como DIRTY y el gate de extracción lo frena.
"""
from __future__ import annotations
import sys
import json

from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.v9.folder_consistency import check_folder_consistency

# Tipos que indican docs de OTRA tutela mezclados (no incluye SOSPECHOSO/PENDIENTE_OCR,
# que son estados de verificación previos, no necesariamente conflación).
_CONFLAC = {"CONFLACION", "RAD_AJENO"}


def scan() -> list[dict]:
    db = SessionLocal()
    try:
        out = []
        for (cid,) in db.query(Case.id).all():
            r = check_folder_consistency(db, cid)
            confl = [i for i in r["issues"] if i["tipo"] in _CONFLAC]
            if confl:
                c = db.query(Case).filter(Case.id == cid).first()
                out.append({
                    "case_id": cid,
                    "accionante": c.accionante,
                    "rad23": c.radicado_23_digitos,
                    "n_ajenos": len(confl),
                    "ejemplos": [i["detalle"] for i in confl[:3]],
                    "doc_ids": [i["doc_id"] for i in confl],
                })
        return out
    finally:
        db.close()


def mark_suspects(contaminados: list[dict]) -> int:
    """Marca verificacion=SOSPECHOSO en los docs ajenos detectados (gate post-ingesta).
    No pisa OK/NO_PERTENECE (decisiones previas). Devuelve nº de docs marcados."""
    db = SessionLocal()
    try:
        n = 0
        for c in contaminados:
            for did in c["doc_ids"]:
                d = db.query(Document).filter(Document.id == did).first()
                if not d or (d.verificacion or "").upper() in {"OK", "NO_PERTENECE"}:
                    continue
                d.verificacion = "SOSPECHOSO"
                d.verificacion_detalle = (
                    f"[scan_conflacion] doc de otro juzgado en c{c['case_id']} — revisar/reubicar"
                )
                n += 1
        db.commit()
        return n
    finally:
        db.close()


def main() -> int:
    contaminados = scan()
    if "--mark" in sys.argv:
        n = mark_suspects(contaminados)
        print(f"🔖 {n} docs marcados SOSPECHOSO (de {len(contaminados)} casos).")
    if "--json" in sys.argv:
        print(json.dumps(contaminados, ensure_ascii=False, indent=2))
    else:
        if not contaminados:
            print("✅ 0 casos con conflación cross-juzgado.")
        else:
            print(f"⚠️  {len(contaminados)} casos con docs de otro juzgado:")
            for c in sorted(contaminados, key=lambda x: -x["n_ajenos"]):
                print(f"  c{c['case_id']} ({c['accionante'] or '∅'}) — {c['n_ajenos']} docs ajenos")
                for ej in c["ejemplos"]:
                    print(f"      • {ej}")
    if "--strict" in sys.argv and contaminados:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
