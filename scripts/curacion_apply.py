"""Aplica curaciones de campos desde un JSON {campo: [{case_id, value, evidence}]}.
Solo escribe si el campo está vacío (no pisa curación previa). Registra audit_log.
Uso: python3 scripts/curacion_apply.py data/curacion_apply_XXX.json [--apply] [--force]
"""
import sys, json, sqlite3
from datetime import datetime, timezone

path = sys.argv[1]
APPLY = "--apply" in sys.argv
FORCE = "--force" in sys.argv  # permite pisar valor existente (úsese con cuidado)
data = json.load(open(path))
db = sqlite3.connect("data/tutelas.db")
db.row_factory = sqlite3.Row
# Formato canónico de SQLAlchemy SQLite DateTime ('YYYY-MM-DD HH:MM:SS.ffffff'), NO
# isoformat() (con 'T' y offset): así el ORM lo lee de vuelta como datetime
# (/api/dashboard/activity hace l.timestamp.replace(tzinfo=...) y necesita un datetime).
ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

changes, skipped = [], []
for field, rows in data.items():
    for r in rows:
        cid, val = r["case_id"], r["value"]
        cur = db.execute(f"SELECT {field} AS v FROM cases WHERE id=?", (cid,)).fetchone()
        if cur is None:
            skipped.append((cid, field, "NO_EXISTE")); continue
        old = (cur["v"] or "").strip()
        if old and not FORCE:
            skipped.append((cid, field, f"YA_TIENE: {old[:40]!r}")); continue
        changes.append((cid, field, old, val, r.get("evidence", "")))

print(f"{'APLICAR' if APPLY else 'DRY-RUN'}: {len(changes)} cambios, {len(skipped)} omitidos\n")
for cid, field, old, val, ev in changes:
    print(f"  c{cid}.{field}: {old[:30]!r} -> {str(val)[:70]!r}")
if skipped:
    print("\nOMITIDOS:")
    for cid, field, why in skipped:
        print(f"  c{cid}.{field}: {why}")

if APPLY:
    for cid, field, old, val, ev in changes:
        db.execute(f"UPDATE cases SET {field}=?, updated_at=? WHERE id=?", (val, ts, cid))
        db.execute(
            "INSERT INTO audit_log(case_id, field_name, old_value, new_value, action, source, timestamp, description) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cid, field, old or None, val, "CURACION_CAMPO", "curacion_apply", ts, ev[:300]),
        )
    db.commit()
    print(f"\nOK: {len(changes)} campos escritos + auditados.")
db.close()
