"""Consolida un batch de clasificaciones JSON al ground truth, fusionando con
carpetas existentes cuando el radicado ya está presente.

Uso: python consolidate_batch.py /path/to/_classifications_batchN.json
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

RAW = Path("/home/wilsonarguello/iuris-data/_raw_emails")
GT = Path("/home/wilsonarguello/iuris-data/_ground_truth")


def normalize_rad23(s):
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) != 23:
        return None
    return f"{digits[0:5]}-{digits[5:7]}-{digits[7:9]}-{digits[9:12]}-{digits[12:16]}-{digits[16:21]}-{digits[21:23]}"


def safe(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "").strip()[:80]


def find_existing_case_dir(rad23):
    """Busca una carpeta en GT cuyo nombre comience con rad23."""
    if not rad23:
        return None
    for d in GT.iterdir():
        if d.is_dir() and d.name.startswith(rad23):
            return d
    # También buscar dentro de _SIN_RADICADO
    sr = GT / "_SIN_RADICADO"
    if sr.exists():
        for d in sr.iterdir():
            if d.is_dir() and d.name.startswith(rad23.split("-")[-2] if "-" in rad23 else rad23):
                return d
    return None


def main(batch_path):
    classifications = json.loads(Path(batch_path).read_text(encoding="utf-8"))

    no_tutela_emails = []
    sin_rad_emails = []
    groups = {}

    for c in classifications:
        if not c.get("is_tutela"):
            no_tutela_emails.append(c)
            continue
        rad23_norm = normalize_rad23(c.get("radicado_23"))
        rad_corto = c.get("radicado_corto") or ""
        key = rad23_norm or rad_corto
        if not key:
            sin_rad_emails.append(c)
            continue
        c["_rad23_norm"] = rad23_norm
        c["_group_key"] = key
        groups.setdefault(key, []).append(c)

    print(f"Grupos en batch: {len(groups)}")
    print(f"NO_TUTELA: {len(no_tutela_emails)}")
    print(f"SIN_RADICADO: {len(sin_rad_emails)}")

    created = 0
    merged = 0
    moved_from_sin_rad = 0

    for key, emails in groups.items():
        rad23 = emails[0].get("_rad23_norm") or ""
        accionante = ""
        for e in emails:
            if e["confianza"] == "alta" and e.get("accionante"):
                accionante = e["accionante"]
                break
        if not accionante and emails:
            accionante = emails[0].get("accionante") or "SIN_ACCIONANTE"

        # Buscar carpeta existente
        existing = find_existing_case_dir(rad23) if rad23 else None
        if not existing and not rad23:
            # buscar por radicado_corto match (formato fallback YYYY-NNNNN)
            for d in GT.iterdir():
                if d.is_dir() and key in d.name:
                    existing = d
                    break

        if existing:
            target = existing
            # Si está en _SIN_RADICADO y ahora tenemos rad23, mover a raíz
            if existing.parent.name == "_SIN_RADICADO" and rad23:
                new_target = GT / f"{rad23} - {safe(accionante)}"
                if not new_target.exists():
                    shutil.move(str(existing), str(new_target))
                    target = new_target
                    moved_from_sin_rad += 1
            merged += 1
        else:
            folder_label = rad23 if rad23 else key
            folder_name = f"{folder_label} - {safe(accionante)}"
            target = GT / folder_name
            target.mkdir(exist_ok=True)
            created += 1

        # Copiar archivos de cada email source
        all_doc_types = {}
        existing_classification = None
        cls_path = target / "_classification.json"
        if cls_path.exists():
            try:
                existing_classification = json.loads(cls_path.read_text())
                all_doc_types = {d["filename"]: d.get("doc_type", "OTRO") for d in existing_classification.get("documents", [])}
            except Exception:
                pass

        existing_source = set((existing_classification or {}).get("source_emails", []))
        for e in emails:
            src = RAW / e["message_id"]
            if not src.exists():
                continue
            existing_source.add(e["message_id"])
            em_md = src / "email.md"
            if em_md.exists():
                dst_md = target / f"{e['message_id']}.email.md"
                if not dst_md.exists():
                    shutil.copy2(em_md, dst_md)
            for f in src.iterdir():
                if f.is_file() and f.name != "email.md":
                    dst = target / f.name
                    if dst.exists():
                        # mismo nombre, distinto: sufijar
                        dst = target / f"{f.stem}_{e['message_id'][:8]}{f.suffix}"
                    if not dst.exists():
                        shutil.copy2(f, dst)
                    all_doc_types[dst.name] = e["doc_types"].get(f.name, "OTRO")

        # Actualizar/crear _classification.json
        merged_cls = {
            "radicado_corto": (existing_classification or {}).get("radicado_corto") or emails[0].get("radicado_corto") or "",
            "radicado_23_digitos": rad23 or (existing_classification or {}).get("radicado_23_digitos") or "",
            "accionante": (existing_classification or {}).get("accionante") or accionante,
            "accionados": list(dict.fromkeys(((existing_classification or {}).get("accionados") or []) + [a for e in emails for a in (e.get("accionados") or [])])),
            "source_emails": sorted(existing_source),
            "documents": [{"filename": fn, "doc_type": dt} for fn, dt in all_doc_types.items()],
            "confianza_clasificacion": max([(existing_classification or {}).get("confianza_clasificacion", "baja")] + [e.get("confianza", "baja") for e in emails], key=lambda x: {"alta": 3, "media": 2, "baja": 1}.get(x, 0)),
            "notas": " | ".join(filter(None, [(existing_classification or {}).get("notas", "")] + [e.get("notas", "") for e in emails if e.get("notas")])),
        }
        cls_path.write_text(json.dumps(merged_cls, ensure_ascii=False, indent=2), encoding="utf-8")

    # NO_TUTELA
    no_tutela_dir = GT / "_NO_TUTELA"
    no_tutela_dir.mkdir(exist_ok=True)
    report_path = no_tutela_dir / "REPORT.md"
    existing_report = report_path.read_text(encoding="utf-8") if report_path.exists() else "# Reporte de correos descartados (NO TUTELA)\n\n"
    new_lines = []
    for e in no_tutela_emails:
        em_md = (RAW / e["message_id"] / "email.md")
        if em_md.exists():
            shutil.copy2(em_md, no_tutela_dir / f"{e['message_id']}.email.md")
        new_lines.append(f"## {e['message_id']}\n- **Razón**: {e.get('discard_reason', '')}\n- **Notas**: {e.get('notas', '')}\n")
    if new_lines:
        report_path.write_text(existing_report + "\n".join(new_lines), encoding="utf-8")

    # SIN_RADICADO
    sr_dir = GT / "_SIN_RADICADO"
    sr_dir.mkdir(exist_ok=True)
    for e in sin_rad_emails:
        src = RAW / e["message_id"]
        dst = sr_dir / e["message_id"]
        if src.exists() and not dst.exists():
            shutil.copytree(src, dst)
            (dst / "_classification.json").write_text(json.dumps(e, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nResultado: created={created} merged={merged} moved_from_sin_rad={moved_from_sin_rad}")
    print(f"Total carpetas en _ground_truth: {len([d for d in GT.iterdir() if d.is_dir() and not d.name.startswith('_')])}")


if __name__ == "__main__":
    main(sys.argv[1])
