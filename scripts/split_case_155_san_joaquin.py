#!/usr/bin/env python3
"""Separa la tutela de San Joaquín que la ingesta de Gmail metió dentro del expediente #155.

El #155 ("2026-00030 LAURA VIVIANA CHACON ARCE", Juzgado 01 Promiscuo de Vélez,
rad 688614089001-2026-00030) contiene además el paquete del email#1366 (06/05/2026,
"RESPUESTA ACCIÓN DE TUTELA 2026-0030") que en realidad pertenece a OTRA tutela:
rad 686824089001-2026-00030, Juzgado Promiscuo Municipal de San Joaquín, accionante
BEATRIZ HELENA MARTÍNEZ DÍAZ (Personera Municipal de San Joaquín, agente oficiosa),
accionados Secretaría de Educación Departamental. Se conflataron por el radicado corto
"2026-00030" aunque son juzgados distintos (Vélez 68861 vs San Joaquín 68682).

Este script:
  1. crea un Case nuevo ("2026-00030 [PENDIENTE SAN JOAQUIN]", rad 68682408900120260003000),
  2. mueve el paquete del email#1366 (doc 4307 .md + adjuntos 4308..4312) al Case nuevo
     vía sibling_mover (hermanos viajan juntos, mueve archivos físicos + AuditLog),
  3. corre el pipeline v9 sobre el Case nuevo para diligenciar sus campos,
  4. renombra la carpeta del Case nuevo a "<rad corto> <ACCIONANTE>".
NO toca el #155 (su identidad Laura Chacón/Vélez ya era correcta; solo sobraban docs).

Uso:
    ./venv/bin/python3 scripts/split_case_155_san_joaquin.py            # dry-run
    ./venv/bin/python3 scripts/split_case_155_san_joaquin.py --apply    # ejecuta
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, Document, Email  # noqa: E402
from backend.services.sibling_mover import move_document_or_package  # noqa: E402

SOURCE_CASE_ID = 155
ANCHOR_EMAIL_ID = 1366            # "RESPUESTA ACCIÓN DE TUTELA 2026-0030" (06/05/2026) — San Joaquín
ANCHOR_DOC_ID = 4307              # el EMAIL_JUDICIAL .md de ese email
NEW_RAD23 = "68682408900120260003000"   # 686824089001 (San Joaquín) + 2026 + 00030 + 00
TEMP_FOLDER = "2026-00030 [PENDIENTE SAN JOAQUIN]"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="ejecuta (sin esto: dry-run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        src = db.get(Case, SOURCE_CASE_ID)
        if not src:
            print(f"No existe el caso #{SOURCE_CASE_ID}", file=sys.stderr)
            return 1
        anchor_doc = db.get(Document, ANCHOR_DOC_ID)
        anchor_email = db.get(Email, ANCHOR_EMAIL_ID)
        if not anchor_doc or anchor_doc.case_id != SOURCE_CASE_ID:
            print(f"doc#{ANCHOR_DOC_ID} no está en el caso #{SOURCE_CASE_ID}", file=sys.stderr)
            return 1
        pkg = db.query(Document).filter(Document.email_id == ANCHOR_EMAIL_ID, Document.case_id == SOURCE_CASE_ID).all()
        prod_root = Path(src.folder_path).parent  # .../V9_PRODUCCION
        new_path = prod_root / TEMP_FOLDER

        print(f"Origen: #{src.id} '{src.folder_name}'  ({len(src.documents)} docs)")
        print(f"Paquete a mover: email#{ANCHOR_EMAIL_ID} «{(anchor_email.subject or '')[:60]}» — {len(pkg)} doc(s):")
        for d in pkg:
            print(f"    doc#{d.id:5d} {d.doc_type:16s} {d.filename}")
        print(f"Caso nuevo: '{TEMP_FOLDER}'  rad={NEW_RAD23}  path={new_path}")
        print(f"Modo: {'APPLY' if args.apply else 'DRY-RUN'}\n")

        if not args.apply:
            print("(dry-run — nada se modificó)")
            return 0

        # 1) crear el Case nuevo + su carpeta en disco
        new_path.mkdir(parents=True, exist_ok=True)
        new_case = Case(
            folder_name=TEMP_FOLDER,
            folder_path=str(new_path),
            radicado_23_digitos=NEW_RAD23,
            tipo_actuacion="TUTELA",
            processing_status="REVISION",
        )
        db.add(new_case)
        db.commit()
        db.refresh(new_case)
        print(f"  ✓ creado Case #{new_case.id}")

        # 2) mover el paquete del email (sibling_mover mueve doc 4307 + sus hermanos)
        r = move_document_or_package(db, ANCHOR_DOC_ID, new_case.id, reason="split_case_155_san_joaquin")
        if r.get("errors"):
            print(f"  ⚠ errores moviendo: {r['errors']}")
            db.rollback()
            return 1
        anchor_email.case_id = new_case.id
        anchor_email.status = "ASIGNADO"
        db.commit()
        print(f"  ✓ movidos {len(r.get('moved_ids', []))} docs + email#{ANCHOR_EMAIL_ID} → Case #{new_case.id}")

        # 3) pipeline v9 sobre el Case nuevo (sin LLM) → diligencia accionante/juzgado/etc.
        from backend.v9.pipeline import extract_case
        res = extract_case(db, new_case.id, dry_run=False, use_llm=False)
        db.commit()
        nc = db.get(Case, new_case.id)
        print(f"  ✓ v9 extract: accionante={nc.accionante!r} juzgado={nc.juzgado!r} ciudad={nc.ciudad!r} estado={nc.estado!r}")
        if getattr(res, "warnings", None):
            print(f"    warnings: {res.warnings}")

        # 4) renombrar la carpeta a "<rad corto> <ACCIONANTE>"
        from backend.cognition.folder_renamer import rename_folder_if_needed
        ren = rename_folder_if_needed(db, nc)
        db.commit()
        nc = db.get(Case, new_case.id)
        print(f"  ✓ folder_renamer: {ren}  → folder_name={nc.folder_name!r}")

        print(f"\nListo. Caso nuevo #{new_case.id}. El #{SOURCE_CASE_ID} quedó con {len(db.get(Case, SOURCE_CASE_ID).documents)} docs.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
