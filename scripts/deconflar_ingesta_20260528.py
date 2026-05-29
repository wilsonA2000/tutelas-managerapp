#!/usr/bin/env python3
"""Desconflación de 3 tutelas nuevas misfileadas por el fallback F2 (cross-juzgado)
durante la ingesta del 2026-05-28.

Cada email trae una tutela NUEVA cuyo consecutivo (rad_corto) colisiona con un caso
existente de OTRO juzgado. El matcher (fix #6) las rechazó, pero el resolver F2
(_resolver_match_rad_corto) las asignó por rad_corto_unique/primer-candidato sin
verificar el juzgado del rad23.

Crea el caso correcto, mueve email + documentos (DB + disco), corrige header .md.
Idempotente-ish: si el caso destino ya existe (por rad23), reusa.

Uso:
    ./venv/bin/python3 scripts/deconflar_ingesta_20260528.py            # dry-run
    ./venv/bin/python3 scripts/deconflar_ingesta_20260528.py --apply
"""
import sys, os, re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document, Email, AuditLog

APPLY = "--apply" in sys.argv
BASE = Path("/home/wilsonarguello/Documentos/GOBERNACION DE SANTANDER/V9_PRODUCCION")

# (email_id, rad_corto, rad23_continuo, accionante, juzgado, ciudad, host_case_id)
PLAN = [
    (1767, "2026-00038", "686824089001202600038",
     "GLADYS CONSUELO CARREÑO BLANCO",
     "JUZGADO 01 PROMISCUO MUNICIPAL DE SAN JOAQUÍN (SANTANDER)", "SAN JOAQUÍN", 167),
    (1732, "2026-00093", "684644089001202600093",
     "CLAUDIA LILIANA PALOMINO ROJAS",
     "JUZGADO 01 PROMISCUO MUNICIPAL DE MOGOTES (SANTANDER)", None, 453),
    (1766, "2026-00080", "681903104001202600080",
     "LLAMISTH ORTIZ ACOSTA",
     "JUZGADO PRIMERO PENAL DEL CIRCUITO DE CIMITARRA (SANTANDER)", "CIMITARRA", 90),
]


def sanitize(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()[:80]


def main():
    db = SessionLocal()
    try:
        for email_id, rad_corto, rad23, acc, juzgado, ciudad, host_id in PLAN:
            print(f"\n{'='*70}\nEMAIL {email_id} — {rad_corto} {acc}  (host actual c{host_id})")

            # ¿ya existe un caso con este rad23?
            existing = db.query(Case).filter(
                Case.radicado_23_digitos == rad23).first()
            if existing:
                target = existing
                print(f"  → caso destino YA existe: c{target.id} {target.folder_name}")
            else:
                folder_name = sanitize(f"{rad_corto} {acc}")
                folder_path = BASE / folder_name
                print(f"  → CREAR caso nuevo: {folder_name}")
                if APPLY:
                    folder_path.mkdir(parents=True, exist_ok=True)
                    target = Case(
                        folder_name=folder_name, folder_path=str(folder_path),
                        accionante=acc, radicado_23_digitos=rad23,
                        juzgado=juzgado, ciudad=ciudad,
                        processing_status="PENDIENTE", estado="ACTIVO",
                        tipo_actuacion="TUTELA", origen="TUTELA",
                    )
                    db.add(target); db.flush()
                    db.add(AuditLog(case_id=target.id, action="CREAR", source="deconflar_F2",
                        new_value=f"Desconflación cross-juzgado: tutela nueva {rad23} separada de c{host_id}. Accionante {acc[:40]}"))
                    print(f"     creado c{target.id}  folder={folder_path}")
                else:
                    target = None

            # mover email + sus documentos
            docs = db.query(Document).filter(Document.email_id == email_id).all()
            email = db.query(Email).filter(Email.id == email_id).first()
            tgt_dir = Path(target.folder_path) if target else (BASE / "<nuevo>")
            for d in docs:
                old = Path(d.file_path) if d.file_path else None
                new = tgt_dir / old.name if old else None
                print(f"     doc {d.id} [{d.doc_type}] {old.name if old else '?'}")
                if APPLY and old and old.exists():
                    if str(old) != str(new):
                        if new.exists():
                            print(f"        (destino ya existe, no sobrescribo) {new}")
                        else:
                            shutil.move(str(old), str(new))
                    d.file_path = str(new)
                    # corregir header **Caso:** del .md
                    if new.suffix.lower() == ".md" and new.exists():
                        try:
                            txt = new.read_text(encoding="utf-8", errors="ignore")
                            txt2 = re.sub(r"(\*\*Caso:\*\*).*", rf"\1 {target.folder_name}", txt, count=1)
                            if txt2 != txt:
                                new.write_text(txt2, encoding="utf-8")
                        except Exception as e:
                            print(f"        (no pude reescribir header md: {e})")
                if APPLY:
                    d.case_id = target.id
            if APPLY and email:
                email.case_id = target.id
                email.status = "ASIGNADO"
                db.add(AuditLog(case_id=target.id, action="REASIGNAR", source="deconflar_F2",
                    new_value=f"Email {email_id} + {len(docs)} docs movidos de c{host_id} a c{target.id} (desconflación cross-juzgado)"))
            print(f"     → {len(docs)} docs + email movidos a c{target.id if target else '?'}")

        if APPLY:
            db.commit()
            print("\n✅ COMMIT hecho.")
        else:
            print("\n(DRY-RUN — usar --apply para ejecutar)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
