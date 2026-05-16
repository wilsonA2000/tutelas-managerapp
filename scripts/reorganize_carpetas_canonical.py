"""
Fase 3 — Reorganización física canónica + reset DB.

Toma audit_carpetas_report.json (de audit_carpetas_canonical.py) y reorganiza:
  - 1 carpeta = 1 rad23
  - Nombre = rad23 con guiones (R6)
  - Docs intrusos → su carpeta destino (si existe en el sistema) o _INTRUSOS_NO_PERTENECE/
  - Docs ajenos (jurisdicción no-Santander) → _AJENOS_NO_SANTANDER/
  - Docs huérfanos → _HUERFANOS_REVISAR/
  - Carpetas MIXED se dividen en N carpetas (una por rad23 detectado)

NO se ejecuta automáticamente. Modos:
  --dry-run  (default): solo imprime el plan, no toca filesystem
  --apply    : ejecuta los movimientos (REQUIERE backup previo y confirmación explícita)

NO toca DB en este script — el reset de DB se hace en script separado tras validar la nueva estructura.

Uso:
  .venv/bin/python3 scripts/reorganize_carpetas_canonical.py --dry-run
  .venv/bin/python3 scripts/reorganize_carpetas_canonical.py --apply --i-have-backup
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path("/home/wilsonarguello/iuris-data/tutelas-files")
DEST_DIR = Path("/home/wilsonarguello/iuris-data/tutelas-files-clean")

def rad23_to_canonical_name(rad23: str) -> str:
    """Devuelve el rad23 con guiones legibles. Ej: 68001-40-03-018-2026-00097-00"""
    if not rad23 or len(rad23) != 23 or not rad23.isdigit():
        return None
    # 5-2-2-3-4-5-2 = 23
    return f"{rad23[0:5]}-{rad23[5:7]}-{rad23[7:9]}-{rad23[9:12]}-{rad23[12:16]}-{rad23[16:21]}-{rad23[21:23]}"

def plan_reorganization(report: list[dict]) -> dict:
    """Devuelve plan de movimientos como dict.

    Estructura:
      plan[rad23_canonical] = {
          'target_folder': str,
          'sources': [{'src_path': str, 'src_doc': str}],
      }
      ajenos: [{src_path}]
      huerfanos: [{src_path, reason}]
      mixed_splits: [{original, splits: {rad23: [docs]}}]
    """
    plan = defaultdict(lambda: {"target_folder": None, "sources": []})
    ajenos = []
    huerfanos = []
    mixed_splits = []
    no_avoca = []

    for r in report:
        folder_name = r["folder"]
        folder_path = BASE_DIR / folder_name
        status = r["status"]

        if status == "OK":
            rad23 = r["ground_truth"]["rad23"]
            canonical = rad23_to_canonical_name(rad23)
            if not canonical:
                no_avoca.append({"folder": folder_name, "reason": "rad23 inválido"})
                continue
            plan[canonical]["target_folder"] = canonical
            for d in r.get("docs", []):
                if d.get("classification") in ("PROPIO_RAD23", "PROPIO_ACCIONANTE", "HUERFANO"):
                    plan[canonical]["sources"].append({
                        "src_path": str(folder_path / d["filename"]),
                        "src_folder": folder_name,
                    })

        elif status == "RED":
            # Carpeta tiene rad23 truth + intrusos. Truth va a su carpeta canónica.
            rad23 = r["ground_truth"]["rad23"]
            canonical = rad23_to_canonical_name(rad23)
            if canonical:
                plan[canonical]["target_folder"] = canonical
            for d in r.get("docs", []):
                cls = d.get("classification")
                src = str(folder_path / d.get("filename", ""))
                if cls in ("PROPIO_RAD23", "PROPIO_ACCIONANTE"):
                    if canonical:
                        plan[canonical]["sources"].append({"src_path": src, "src_folder": folder_name})
                elif cls in ("INTRUSO_RAD23",):
                    # Tiene rad23 distinto → mover a SU carpeta correspondiente
                    intrusos_rads = d.get("intruso_rad23") or d.get("rad23s") or []
                    for ir in intrusos_rads:
                        ic = rad23_to_canonical_name(ir)
                        if ic:
                            plan[ic]["target_folder"] = ic
                            plan[ic]["sources"].append({"src_path": src, "src_folder": folder_name})
                            break
                    else:
                        huerfanos.append({"src_path": src, "reason": "INTRUSO sin rad23 mapeable"})
                elif cls == "INTRUSO_ACCIONANTE":
                    huerfanos.append({"src_path": src, "reason": "Accionante distinto, sin rad23 verificable"})
                elif cls == "AJENO":
                    ajenos.append({"src_path": src})
                elif cls == "HUERFANO":
                    if canonical:
                        # Huérfano sin rad23: dejarlo con el caso truth (mejor estimación)
                        plan[canonical]["sources"].append({"src_path": src, "src_folder": folder_name, "huerfano": True})
                    else:
                        huerfanos.append({"src_path": src, "reason": "Huérfano sin caso truth"})

        elif status == "MIXED":
            # Carpeta tiene N Autos Avoca con N rad23s → splittear
            split_info = {"original": folder_name, "splits": defaultdict(list)}
            for d in r.get("docs", []):
                src = str(folder_path / d.get("filename", ""))
                rads = d.get("rad23s") or []
                if not rads:
                    huerfanos.append({"src_path": src, "reason": f"De carpeta MIXED {folder_name}, sin rad23"})
                    continue
                # Asignar al primer rad23 que aparezca
                for r23 in rads:
                    c = rad23_to_canonical_name(r23)
                    if c:
                        plan[c]["target_folder"] = c
                        plan[c]["sources"].append({"src_path": src, "src_folder": folder_name, "from_mixed": True})
                        split_info["splits"][c].append(d.get("filename"))
                        break
            mixed_splits.append({"original": folder_name, "splits": dict(split_info["splits"])})

        elif status in ("AJENO", "AJENO_PARCIAL"):
            for d in r.get("docs", []):
                src = str(folder_path / d.get("filename", ""))
                ajenos.append({"src_path": src, "from_folder": folder_name})

        elif status == "NO_AVOCA":
            for d in r.get("docs", []):
                src = str(folder_path / d.get("filename", ""))
                rads = d.get("rad23s") or []
                if rads:
                    c = rad23_to_canonical_name(rads[0])
                    if c:
                        plan[c]["target_folder"] = c
                        plan[c]["sources"].append({"src_path": src, "src_folder": folder_name, "no_avoca_origin": True})
                        continue
                huerfanos.append({"src_path": src, "reason": f"De {folder_name} (NO_AVOCA), sin rad23 propio"})
            no_avoca.append({"folder": folder_name})

        elif status == "REVIEW":
            # Tratar como OK si hay rad23 truth
            rad23 = r["ground_truth"]["rad23"]
            canonical = rad23_to_canonical_name(rad23)
            if canonical:
                plan[canonical]["target_folder"] = canonical
                for d in r.get("docs", []):
                    src = str(folder_path / d.get("filename", ""))
                    cls = d.get("classification")
                    if cls in ("PROPIO_RAD23", "PROPIO_ACCIONANTE", "HUERFANO"):
                        plan[canonical]["sources"].append({"src_path": src, "src_folder": folder_name})
            else:
                no_avoca.append({"folder": folder_name, "reason": "REVIEW sin rad23 truth"})

    return {
        "carpetas_canonicas": dict(plan),
        "ajenos": ajenos,
        "huerfanos": huerfanos,
        "mixed_splits": mixed_splits,
        "no_avoca_unresolved": no_avoca,
    }

def print_plan(plan: dict):
    p = plan
    print(f"\n{'='*70}")
    print(f"PLAN DE REORGANIZACIÓN")
    print(f"{'='*70}")
    print(f"  Carpetas canónicas a crear/usar: {len(p['carpetas_canonicas'])}")
    total_docs_to_move = sum(len(v['sources']) for v in p['carpetas_canonicas'].values())
    print(f"  Docs a mover a carpetas canónicas: {total_docs_to_move}")
    print(f"  Docs ajenos (otra jurisdicción): {len(p['ajenos'])}")
    print(f"  Docs huérfanos (sin rad23 / sin caso): {len(p['huerfanos'])}")
    print(f"  Carpetas MIXED a dividir: {len(p['mixed_splits'])}")
    print(f"  Carpetas sin Auto Avoca (no resueltas): {len(p['no_avoca_unresolved'])}")

    print(f"\n--- Top 20 carpetas canónicas más grandes ---")
    sorted_carpetas = sorted(p['carpetas_canonicas'].items(), key=lambda x: -len(x[1]['sources']))[:20]
    for c, info in sorted_carpetas:
        print(f"  {c}: {len(info['sources'])} docs")

    if p['mixed_splits']:
        print(f"\n--- Top 10 splits MIXED ---")
        for s in p['mixed_splits'][:10]:
            print(f"  '{s['original'][:50]}' → {len(s['splits'])} casos")

def apply_plan(plan: dict, dry_run: bool = True):
    """Ejecuta el plan."""
    if dry_run:
        print("\n[DRY RUN] No se moverá nada. Use --apply para ejecutar.")
        return

    DEST_DIR.mkdir(exist_ok=True)
    (DEST_DIR / "_AJENOS_NO_SANTANDER").mkdir(exist_ok=True)
    (DEST_DIR / "_HUERFANOS_REVISAR").mkdir(exist_ok=True)

    moved = 0
    for c, info in plan['carpetas_canonicas'].items():
        target = DEST_DIR / c
        target.mkdir(exist_ok=True)
        for src_info in info['sources']:
            src = Path(src_info['src_path'])
            if src.exists():
                dest = target / src.name
                if dest.exists():
                    # Conflicto: añadir sufijo
                    base, ext = dest.stem, dest.suffix
                    i = 1
                    while dest.exists():
                        dest = target / f"{base}_dup{i}{ext}"
                        i += 1
                shutil.copy2(src, dest)  # COPY, no move (mantener original como backup)
                moved += 1
            else:
                print(f"  ! Source no existe: {src}")

    for d in plan['ajenos']:
        src = Path(d['src_path'])
        if src.exists():
            dest = DEST_DIR / "_AJENOS_NO_SANTANDER" / src.name
            if dest.exists():
                continue  # skip dups
            shutil.copy2(src, dest)
            moved += 1

    for d in plan['huerfanos']:
        src = Path(d['src_path'])
        if src.exists():
            dest = DEST_DIR / "_HUERFANOS_REVISAR" / src.name
            if dest.exists():
                continue
            shutil.copy2(src, dest)
            moved += 1

    print(f"\n[APPLY] Total docs copiados: {moved}")
    print(f"[APPLY] Estructura limpia en: {DEST_DIR}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/tmp/audit_carpetas_report.json")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--i-have-backup", action="store_true", help="Confirma backup previo")
    ap.add_argument("--out-plan", default="/tmp/reorg_plan.json")
    args = ap.parse_args()

    if args.apply and not args.i_have_backup:
        print("ERROR: --apply requiere --i-have-backup (confirmación de respaldo)")
        sys.exit(1)

    print(f"Cargando audit report: {args.input}")
    report = json.load(open(args.input))
    print(f"  {len(report)} carpetas en report")

    plan = plan_reorganization(report)
    Path(args.out_plan).write_text(json.dumps(plan, indent=2, ensure_ascii=False, default=str))
    print(f"Plan guardado: {args.out_plan}")

    print_plan(plan)

    if args.apply:
        print(f"\n⚠ Aplicando plan. Source en {BASE_DIR}, destino {DEST_DIR}")
        apply_plan(plan, dry_run=False)
    else:
        apply_plan(plan, dry_run=True)

if __name__ == "__main__":
    main()
