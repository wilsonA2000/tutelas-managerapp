#!/usr/bin/env python3
"""Aplica los resultados del preview (sem_before_after.py) a la DB.

Lee data/sem_93_preview.jsonl (formato 'DB  ->  NEW [src]'), y para cada campo
asunto/derecho_vulnerado escribe NEW si: (1) difiere del valor actual, (2) el
campo NO está curado (manual/manual_audit), (3) NEW no es None/SIN_DETERMINAR.
Actualiza field_confidences_json.v9_sources[campo] = src.

Dry-run por defecto; --apply escribe. Backup previo recomendado (ya hecho).

Uso:
    ./venv/bin/python3 scripts/sem_apply_93.py            # dry-run (plan)
    ./venv/bin/python3 scripts/sem_apply_93.py --apply
"""
from __future__ import annotations
import sqlite3, json, re, sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "tutelas.db"
PREVIEW = Path(__file__).resolve().parents[1] / "data" / "sem_93_preview.jsonl"
APPLY = "--apply" in sys.argv

# 'DB_VAL  ->  NEW_VAL [src]'  →  (new_val_or_None, src)
_PAT = re.compile(r"^(.*?)\s+->\s+(.*?)\s+\[(\w+)\]\s*$")


def parse(field_str):
    m = _PAT.match(field_str or "")
    if not m:
        return None, None, None
    db_val, new_val, src = m.group(1).strip(), m.group(2).strip(), m.group(3)
    if new_val == "None":
        new_val = None
    return db_val, new_val, src


# Derechos "seguros" de agregar (comunes, defendibles). Si el LLM agrega SOLO
# de este set respecto al valor viejo, es alta-confianza. Agregar cualquier otro
# (VIDA/SALUD/TRABAJO/MINIMO_VITAL/SEGURIDAD_SOCIAL/INTIMIDAD/HABEAS_DATA) =
# especulativo → baja confianza, no se aplica (se conserva el valor regex).
_SAFE_ADD = {"IGUALDAD", "PETICION", "DEBIDO_PROCESO"}


def _tagset(val):
    return {t.strip() for t in (val or "").split(" - ") if t.strip()}


def derecho_high_conf(old_val, new_val) -> bool:
    """True si el cambio de derecho es alta-confianza: solo quita tags, o solo
    agrega tags del set seguro."""
    old, new = _tagset(old_val), _tagset(new_val)
    if not new:
        return False
    added = new - old
    return added <= _SAFE_ADD


def is_curated(fc_json, field):
    if not fc_json:
        return False
    try:
        s = json.loads(fc_json).get("v9_sources", {}).get(field)
    except Exception:
        return False
    return isinstance(s, dict) or (isinstance(s, str) and s in ("manual", "manual_audit"))


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    planned = {"asunto": 0, "derecho_vulnerado": 0}
    skipped_curated = skipped_same = skipped_empty = 0
    skipped_lowconf = []  # cambios de derecho de baja confianza (se conservan regex)

    for line in open(PREVIEW):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        cid = d.get("case")
        if cid is None or "asunto" not in d:
            continue
        row = cur.execute(
            "SELECT asunto, derecho_vulnerado, field_confidences_json FROM cases WHERE id=?",
            (cid,)).fetchone()
        if not row:
            continue
        fc = row["field_confidences_json"]
        for field, key in (("asunto", "asunto"), ("derecho_vulnerado", "derecho")):
            db_val, new_val, src = parse(d.get(key))
            cur_val = row[field]
            if new_val is None or new_val in ("SIN_DETERMINAR", ""):
                skipped_empty += 1; continue
            if new_val == (cur_val or ""):
                skipped_same += 1; continue
            if is_curated(fc, field):
                skipped_curated += 1; continue
            # derecho: solo alta confianza (asunto se aplica siempre que cambie)
            if field == "derecho_vulnerado" and not derecho_high_conf(cur_val, new_val):
                skipped_lowconf.append((cid, cur_val, new_val))
                continue
            # asunto: NO degradar una categoría específica al catch-all genérico
            # (pérdida de info, no un fix).
            if field == "asunto" and new_val == "TUTELA_GENERICA" and \
                    cur_val and cur_val not in ("SIN_DETERMINAR", "TUTELA_GENERICA"):
                skipped_lowconf.append((cid, f"asunto {cur_val}", new_val))
                continue
            print(f"  c{cid:<4} {field:<18} {cur_val!r:>32}  ->  {new_val!r}  [{src}]")
            planned[field] += 1
            if APPLY:
                # actualizar valor
                cur.execute(f"UPDATE cases SET {field}=? WHERE id=?", (new_val, cid))
                # marcar source
                try:
                    j = json.loads(fc) if fc else {}
                except Exception:
                    j = {}
                j.setdefault("v9_sources", {})[field] = src or "llm"
                fc = json.dumps(j, ensure_ascii=False)
                cur.execute("UPDATE cases SET field_confidences_json=? WHERE id=?", (fc, cid))

    print("\n" + ("APLICADO" if APPLY else "DRY-RUN (plan, no escrito)"))
    print(f"  cambios asunto:  {planned['asunto']}")
    print(f"  cambios derecho: {planned['derecho_vulnerado']}")
    print(f"  saltados: curado={skipped_curated}, igual={skipped_same}, vacio/SIN_DET={skipped_empty}")
    print(f"  derecho BAJA confianza (NO aplicados, se conserva regex): {len(skipped_lowconf)}")
    for cid, o, n in skipped_lowconf:
        print(f"      c{cid:<4} {o!r}  ->  {n!r}")
    if APPLY:
        con.commit()
        print("  COMMIT hecho.")
    con.close()


if __name__ == "__main__":
    main()
