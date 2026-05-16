#!/usr/bin/env python3
"""Importa el expediente de DILSA ACEVEDO PARADA al v9.

Caso encontrado 2026-05-15: la carpeta `/TUTELAS 2026/2026-429 DILSA ACEVEDO PARADA/`
es del workspace pre-modernización (v8). v9 nunca la ingestó porque el SED solo
recibió por Gmail el .md de la notificación de la Corte Suprema (rad
11001020300020260042900) — el cuerpo del expediente lo recopilaste a mano en esa
carpeta vieja. El email#16 (doc#42, .md) quedó en el case-shell #1 __SIN_RADICADO__.

Este script:
  1. Crea un Case nuevo en la DB con rad/accionante de DILSA.
  2. Crea la carpeta del case dentro de BASE_DIR (/V9_PRODUCCION/).
  3. COPIA los archivos físicos de la carpeta vieja a la nueva (no mueve,
     la vieja queda intacta como referente).
  4. Registra cada archivo como Document en la DB.
  5. Mueve el email#16 + su .md (doc#42) del case #1 al case nuevo.
  6. Corre v9 pipeline para diligenciar campos.

Dry-run por defecto.

Uso:
    ./venv/bin/python3 scripts/import_dilsa.py            # dry-run
    ./venv/bin/python3 scripts/import_dilsa.py --apply    # ejecuta
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.settings import settings  # noqa: E402
from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import AuditLog, Case, Document, Email  # noqa: E402


OLD_FOLDER = Path("/home/wilsonarguello/Documentos/GOBERNACION DE SANTANDER/TUTELAS 2026/2026-429 DILSA ACEVEDO PARADA")
NEW_FOLDER_NAME = "2026-00429 DILSA ACEVEDO PARADA"
RAD_23 = "11001020300020260042900"
ACCIONANTE = "DILSA ACEVEDO PARADA"
JUZGADO_PRIMERA = "JUZGADO TERCERO PROMISCUO DE FAMILIA DE BARRANCABERMEJA"
ACCIONADOS = "SALA CIVIL FAMILIA DEL TRIBUNAL SUPERIOR DE BUCARAMANGA — JUZGADO TERCERO PROMISCUO DE FAMILIA DE BARRANCABERMEJA"
ANCHOR_EMAIL_ID = 16
ANCHOR_DOC_MD_ID = 42


def detect_doctype(filename: str, subdir: str = "") -> str:
    """Detecta doc_type básico por filename + subcarpeta. v9 lo afinará al re-extraer."""
    fn = filename.lower()
    sub = (subdir or "").lower()
    # Por path: si vive en RESPUESTA/, default RESPUESTA salvo que sea claramente otra cosa
    if "respuesta" in sub:
        if "forest" in fn:
            return "RESPUESTA"
        if "envio" in fn or "soporte" in fn:
            return "DESCONOCIDO"
        return "RESPUESTA"
    # Por filename — orden importa
    if "fallo" in fn and ("tutela" in fn or "sentencia" in fn):
        return "SENTENCIA_1RA"
    if "sentencia" in fn:
        return "SENTENCIA_1RA"
    if "demanda" in fn or fn.startswith("tutela") or fn.startswith("tutela_"):
        return "DEMANDA_TUTELA"
    if "auto" in fn and ("admis" in fn or "0006auto" in fn):
        return "AUTO_ADMISORIO"
    if "auto" in fn:
        return "AUTO_ADMISORIO"
    if "respuesta" in fn or "rta" in fn or "forest" in fn:
        return "RESPUESTA"
    if "pruebas" in fn or fn.endswith(".zip"):
        return "ANEXO_DEMANDA"
    if "acta" in fn and "reparto" in fn:
        return "DESCONOCIDO"
    return "DESCONOCIDO"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not OLD_FOLDER.exists():
        print(f"ERROR: carpeta vieja no existe: {OLD_FOLDER}", file=sys.stderr)
        return 1

    base_dir = Path(settings.BASE_DIR)
    new_folder = base_dir / NEW_FOLDER_NAME

    db = SessionLocal()
    try:
        # ¿Ya existe el case?
        existing = db.query(Case).filter(Case.radicado_23_digitos == RAD_23).first()
        if existing:
            print(f"NO-OP: ya existe case #{existing.id} con rad {RAD_23}")
            return 0

        # Inventario de archivos a copiar
        files_to_copy = []  # (src_path, rel_subdir)
        for p in sorted(OLD_FOLDER.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                rel = p.relative_to(OLD_FOLDER)
                files_to_copy.append((p, str(rel.parent) if rel.parent != Path(".") else ""))

        print(f"Carpeta origen: {OLD_FOLDER}")
        print(f"Carpeta destino (BASE_DIR v9): {new_folder}")
        print(f"\nCase a crear:")
        print(f"  rad_23: {RAD_23}")
        print(f"  accionante: {ACCIONANTE}")
        print(f"  folder_name: {NEW_FOLDER_NAME}")
        print(f"\nArchivos a copiar: {len(files_to_copy)}")
        for src, sub in files_to_copy:
            dt = detect_doctype(src.name, sub)
            print(f"  [{dt:<18}] {sub + '/' if sub else ''}{src.name}  ({src.stat().st_size:>10} bytes)")

        print(f"\nEmail huérfano a mover del #1: email#{ANCHOR_EMAIL_ID} + doc#{ANCHOR_DOC_MD_ID} (.md)")
        print(f"\nModo: {'APPLY' if args.apply else 'DRY-RUN'}")

        if not args.apply:
            print("\n(dry-run — nada se modificó)")
            return 0

        # 1) crear el case
        new_folder.mkdir(parents=True, exist_ok=True)
        new_case = Case(
            folder_name=NEW_FOLDER_NAME,
            folder_path=str(new_folder),
            radicado_23_digitos=RAD_23,
            accionante=ACCIONANTE,
            accionados=ACCIONADOS,
            juzgado=JUZGADO_PRIMERA,
            ciudad="BARRANCABERMEJA",
            tipo_actuacion="TUTELA",
            processing_status="REVISION",
            observaciones=(
                "Expediente importado 2026-05-15 desde carpeta legacy "
                f"({OLD_FOLDER.name}) que vivía fuera del BASE_DIR v9. "
                "Tutela contra providencia judicial; el SED de Santander figura como vinculado/interesado. "
                "Fallo 1ra Corte Suprema STC884-2026 (04/02/2026) Magistrada Hilda González Neira. "
                "PDFs copiados (no movidos), la carpeta legacy se mantiene como referente."
            ),
        )
        db.add(new_case)
        db.commit()
        db.refresh(new_case)
        print(f"\n  ✓ Case #{new_case.id} creado en DB")

        # 2-3) copiar archivos físicos + registrar en DB
        copied = 0
        for src, sub in files_to_copy:
            dest_dir = new_folder / sub if sub else new_folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            i = 1
            while dest.exists():
                dest = dest_dir / f"{dest.stem}_dup{i}{dest.suffix}"
                i += 1
            shutil.copy2(src, dest)

            doc = Document(
                case_id=new_case.id,
                filename=src.name,
                file_path=str(dest),
                doc_type=detect_doctype(src.name, sub),
                file_size=src.stat().st_size,
                verificacion="OK",
                verificacion_detalle=f"Importado de carpeta legacy {OLD_FOLDER.name} (copia, original intacto)",
                extraction_date=datetime.utcnow(),
            )
            db.add(doc)
            copied += 1
        db.commit()
        print(f"  ✓ {copied} archivos copiados a {new_folder}")

        # 4) mover email#16 + su doc#42 del case #1 al nuevo
        from backend.services.sibling_mover import move_document_or_package
        anchor_doc = db.get(Document, ANCHOR_DOC_MD_ID)
        if anchor_doc and anchor_doc.case_id == 1:
            r = move_document_or_package(db, ANCHOR_DOC_MD_ID, new_case.id, reason="import_dilsa")
            email = db.get(Email, ANCHOR_EMAIL_ID)
            if email:
                email.case_id = new_case.id
                email.status = "ASIGNADO"
            db.commit()
            print(f"  ✓ email#{ANCHOR_EMAIL_ID} + doc#{ANCHOR_DOC_MD_ID} reasignados a Case #{new_case.id}")
        else:
            print(f"  ⚠ doc#{ANCHOR_DOC_MD_ID} no estaba en case #1 — skip move email")

        # 5) re-extracción/análisis de los docs por v9 (no es estrictamente necesario para el case si la
        #    info crítica ya está, pero v9 puede mejorar doc_type y extraer texto)
        try:
            from backend.extraction.doc_ops import reextract_document
            for d in db.query(Document).filter(Document.case_id == new_case.id, Document.extracted_text.is_(None)).all():
                try:
                    reextract_document(db, d.id)
                except Exception as e:
                    print(f"  ⚠ reextract doc#{d.id}: {e}")
            db.commit()
            print(f"  ✓ reextract de docs (text extraction) completado")
        except Exception as e:
            print(f"  ⚠ no se pudo reextract: {e}")

        # 6) correr v9 pipeline
        try:
            from backend.v9.pipeline import extract_case
            res = extract_case(db, new_case.id, dry_run=False, use_llm=False)
            db.commit()
            print(f"  ✓ v9 pipeline: {res.summary()}")
        except Exception as e:
            print(f"  ⚠ v9 pipeline error: {e}")

        nc = db.get(Case, new_case.id)
        print(f"\n=== Estado final Case #{nc.id} ===")
        print(f"  folder_name: {nc.folder_name}")
        print(f"  accionante: {nc.accionante}")
        print(f"  juzgado: {nc.juzgado}")
        print(f"  fecha_fallo_1st: {nc.fecha_fallo_1st}")
        print(f"  sentido_fallo_1st: {nc.sentido_fallo_1st}")
        print(f"  estado: {nc.estado}")
        print(f"  Total docs: {db.query(Document).filter(Document.case_id == nc.id).count()}")
        print(f"  Total emails: {db.query(Email).filter(Email.case_id == nc.id).count()}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
