"""Reubica archivos huerfanos de _emails_sin_clasificar/ en sus cases.

Estrategia:
  1. Filename match: extrae rad_corto del nombre (rapido, sin abrir el PDF).
  2. Si --read-pdf: para los que no tienen rad en filename, abre las
     primeras paginas del PDF y busca rad_corto/rad_23 en el texto.
  3. Si match univoco contra DB → mueve archivo + crea Document + AuditLog.
  4. Si dudoso/sin match → CSV en data/exports/ para revision manual.

Uso:
    python3 scripts/cleanup_unsorted_emails.py --dry-run
    python3 scripts/cleanup_unsorted_emails.py --dry-run --read-pdf
    python3 scripts/cleanup_unsorted_emails.py --execute --read-pdf
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.settings import settings
from backend.database.database import SessionLocal
from backend.database.models import AuditLog, Case, Document
from backend.email.rad_utils import canonical_rad_corto, derive_rad_corto_from_rad23

UNSORTED = Path(settings.BASE_DIR) / "_emails_sin_clasificar"
EXPORTS = Path(__file__).resolve().parents[1] / "data" / "exports"

_RAD_FILENAME = re.compile(r"(20\d{2})\D{0,3}(\d{4,5})")
_RAD23_TEXT = re.compile(r"\d{20,23}")
_FOREST_TEXT = re.compile(r"\b\d{6,9}\b")


def extract_rad_from_filename(name: str) -> str:
    rc = canonical_rad_corto(name)
    if rc:
        return rc
    m = _RAD_FILENAME.search(name)
    if m:
        seq = m.group(2).zfill(5)
        return f"{m.group(1)}-{seq}"
    return ""


def extract_rads_from_pdf(path: Path, max_pages: int = 3) -> list[str]:
    """Devuelve lista de rad_corto candidatos detectados en las primeras paginas."""
    try:
        import fitz
    except ImportError:
        return []
    try:
        doc = fitz.open(str(path))
    except Exception:
        return []
    rads: list[str] = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        try:
            text = page.get_text()
        except Exception:
            continue
        for m in _RAD23_TEXT.finditer(text):
            rc = derive_rad_corto_from_rad23(m.group())
            if rc:
                rads.append(rc)
        m = _RAD_FILENAME.search(text)
        if m:
            seq = m.group(2).zfill(5)
            rads.append(f"{m.group(1)}-{seq}")
    doc.close()
    return rads


def build_case_index(db) -> dict[str, list[Case]]:
    """Indexa cases por rad_corto (derivado de rad_23 y de folder_name)."""
    cases = db.query(Case).filter(Case.processing_status != "DUPLICATE_MERGED").all()
    idx: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        rc23 = derive_rad_corto_from_rad23(c.radicado_23_digitos or "")
        if rc23:
            idx[rc23].append(c)
        m = re.match(r"^(20\d{2})-(\d{4,5})", c.folder_name or "")
        if m:
            rc_folder = f"{m.group(1)}-{m.group(2).zfill(5)}"
            if c not in idx[rc_folder]:
                idx[rc_folder].append(c)
    return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--read-pdf", action="store_true",
                    help="Si no hay rad en filename, abre PDF para buscar")
    args = ap.parse_args()

    if not UNSORTED.exists():
        print(f"[ERROR] No existe {UNSORTED}")
        return 1

    files = sorted(p for p in UNSORTED.iterdir() if p.is_file())
    print(f"Archivos en {UNSORTED.name}: {len(files)}")

    db = SessionLocal()
    try:
        idx = build_case_index(db)
        print(f"Cases indexados (con rad_corto): {len(idx)}")

        movables: list[tuple[Path, Case, str]] = []  # (file, case, source)
        manual: list[dict] = []
        rad_match_counter: Counter[str] = Counter()

        for f in files:
            rc = extract_rad_from_filename(f.name)
            source = "filename"
            candidates: list[str] = [rc] if rc else []

            if not candidates and args.read_pdf and f.suffix.lower() == ".pdf":
                pdf_rads = extract_rads_from_pdf(f)
                if pdf_rads:
                    most_common = Counter(pdf_rads).most_common(1)[0][0]
                    candidates = [most_common]
                    source = "pdf_content"

            if not candidates:
                manual.append({"file": f.name, "reason": "sin rad detectable"})
                continue

            rad = candidates[0]
            cases_for_rad = idx.get(rad, [])
            if len(cases_for_rad) == 1:
                movables.append((f, cases_for_rad[0], source))
                rad_match_counter[rad] += 1
            elif len(cases_for_rad) > 1:
                manual.append({
                    "file": f.name,
                    "reason": f"rad {rad} ambiguo: {len(cases_for_rad)} cases",
                    "cases": ", ".join(str(c.id) for c in cases_for_rad),
                })
            else:
                manual.append({"file": f.name, "reason": f"rad {rad} no esta en DB"})

        print(f"\nMovibles univocos: {len(movables)}")
        print(f"Manuales (CSV): {len(manual)}")
        print("\nDistribucion de rads (top 8):")
        for rad, n in rad_match_counter.most_common(8):
            print(f"  {n:3d}  {rad}")

        EXPORTS.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if manual:
            csv_path = EXPORTS / f"unsorted_manual_{ts}.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as fp:
                w = csv.DictWriter(fp, fieldnames=["file", "reason", "cases"])
                w.writeheader()
                for row in manual:
                    w.writerow({**{k: "" for k in ("cases",)}, **row})
            print(f"\nCSV manual: {csv_path}")

        if args.dry_run:
            print("\n[DRY-RUN] no se mueve nada")
            print("Primeros 5 movibles:")
            for f, c, src in movables[:5]:
                print(f"  {f.name} -> case_id={c.id} folder={c.folder_name!r} (via {src})")
            return 0

        moved = 0
        errors = 0
        for f, case, source in movables:
            if not case.folder_path or not Path(case.folder_path).exists():
                errors += 1
                manual.append({"file": f.name, "reason": f"target folder no existe (case_id={case.id})"})
                continue
            target = Path(case.folder_path) / f.name
            counter = 1
            while target.exists():
                target = Path(case.folder_path) / f"{f.stem}_moved{counter}{f.suffix}"
                counter += 1
            try:
                shutil.move(str(f), str(target))
            except Exception as e:
                errors += 1
                manual.append({"file": f.name, "reason": f"move fallo: {e}"})
                continue

            doc = Document(
                case_id=case.id,
                filename=target.name,
                file_path=str(target),
                doc_type="OTRO",
                file_size=target.stat().st_size,
                verificacion="OK",
                verificacion_detalle=f"Reubicado desde _emails_sin_clasificar via {source}",
            )
            db.add(doc)
            db.add(AuditLog(
                case_id=case.id,
                field_name="documento",
                old_value=f"_emails_sin_clasificar/{f.name}",
                new_value=str(target),
                action="CLEANUP_RELOCATE",
                source=f"cleanup_unsorted:{source}",
            ))
            moved += 1

        db.commit()
        print(f"\n[OK] Movidos: {moved}, errores: {errors}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
