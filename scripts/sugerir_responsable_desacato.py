#!/usr/bin/env python3
"""Sugiere `responsable_desacato` canónico para cada caso problemático.

Pareja de `audit_responsables_canonicos.py`. Para cada caso cuyo
responsable_desacato actual es INSTITUCIONAL o PERSONA_NO_CANONICA:

1. Lee las RESPUESTAS SED de su incidente (docs tipo RESPUESTA/DOCX_RESPUESTA
   cuyo extracted_text contiene "INCIDENTE" o "DESACATO").
2. Busca el patrón "PROYECTÓ: <nombre>" en el tail del doc — ese es el
   responsable per regla c456.
3. Verifica que el nombre detectado esté entre los 17 canónicos.
4. Si hay varios docs, el proyectó canónico más frecuente gana.
5. Sugiere el cambio: actual → canónico_sugerido.

Imprime una tabla revisable + CSV `data/sugerencias_responsable_desacato_<ts>.csv`.
NO modifica la DB. Wilson aplica con `--apply` los que apruebe.

Uso:
    python3 scripts/sugerir_responsable_desacato.py            # dry-run (default)
    python3 scripts/sugerir_responsable_desacato.py --apply    # aplica todos los matches únicos canónicos
    python3 scripts/sugerir_responsable_desacato.py --case 92  # solo un caso
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "tutelas.db"
CANON_JSON = ROOT / "backend" / "data" / "abogados_canonicos.json"


def _norm(s: str) -> str:
    s = (s or "").upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def load_canon() -> tuple[dict[str, str], list[str]]:
    data = json.load(open(CANON_JSON, encoding="utf-8"))
    variants: dict[str, str] = {}
    canonicos: list[str] = []
    for entry in data:
        c = entry["canonical"]
        canonicos.append(c)
        variants[_norm(c)] = c
        for a in entry.get("aliases", []):
            variants[_norm(a)] = c
    return variants, canonicos


def find_canonical_in(text: str, variants: dict[str, str]) -> str | None:
    """Devuelve canónico si alguna variante (≥10 chars) aparece en text."""
    nt = _norm(text)
    for v, c in variants.items():
        if len(v) >= 10 and v in nt:
            return c
    return None


def suggest_for_case(db, case_id: int, variants: dict[str, str]) -> dict | None:
    """Lee respuestas SED del incidente del caso y devuelve sugerencia."""
    rows = db.execute(
        "SELECT id, filename, extracted_text FROM documents "
        "WHERE case_id = ? AND ("
        "  doc_type LIKE 'RESPUESTA%' OR doc_type LIKE 'DOCX_RESPUESTA%'"
        "  OR doc_type = 'CONTESTACION_SED'"
        ") ORDER BY id",
        (case_id,)).fetchall()

    proyecto_votes = Counter()
    reviso_votes = Counter()
    docs_examined = 0

    for r in rows:
        t = (r["extracted_text"] or "")
        nt = _norm(t)
        if "INCIDENTE" not in nt and "DESACATO" not in nt:
            continue
        docs_examined += 1
        tail = t[-2500:] if len(t) > 2500 else t
        # PROYECTÓ
        m = re.search(r"PROYECT[ÓO]\s*:?\s*([^\n]{6,80})", tail)
        if m:
            canon = find_canonical_in(m.group(1), variants)
            if canon:
                proyecto_votes[canon] += 1
        # REVISÓ / APROBÓ
        m = re.search(r"(?:REVIS[ÓO]|APROB[ÓO])\s*:?\s*([^\n]{6,80})", tail)
        if m:
            canon = find_canonical_in(m.group(1), variants)
            if canon:
                reviso_votes[canon] += 1

    if not proyecto_votes and not reviso_votes:
        return None

    # Preferir proyectó > revisó
    if proyecto_votes:
        best, votes = proyecto_votes.most_common(1)[0]
        source = "PROYECTÓ"
    else:
        best, votes = reviso_votes.most_common(1)[0]
        source = "REVISÓ"

    return {
        "case_id": case_id,
        "suggested": best,
        "source": source,
        "votes": votes,
        "docs_examined": docs_examined,
        "proyecto_all": dict(proyecto_votes),
        "reviso_all": dict(reviso_votes),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Aplica las sugerencias con un solo canónico fuerte (≥1 voto, sin ambigüedad)")
    ap.add_argument("--case", type=int, help="Solo un case_id")
    args = ap.parse_args()

    variants, canonicos = load_canon()
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Casos a procesar: los problemáticos (responsable_desacato no canónico)
    if args.case:
        cases = [args.case]
    else:
        cases = []
        for r in db.execute("SELECT id, responsable_desacato FROM cases "
                            "WHERE responsable_desacato IS NOT NULL "
                            "AND responsable_desacato != ''"):
            v = _norm(r["responsable_desacato"])
            # No canónico
            if v in variants:
                continue
            # Validar más laxo: alguna variante contenida
            if any(cv in v for cv in variants if len(cv) >= 12):
                continue
            cases.append(r["id"])

    print(f"Casos a procesar: {len(cases)}\n")

    suggestions = []
    for cid in cases:
        actual = db.execute("SELECT responsable_desacato FROM cases WHERE id=?",
                            (cid,)).fetchone()["responsable_desacato"]
        s = suggest_for_case(db, cid, variants)
        if s is None:
            suggestions.append({"case_id": cid, "actual": actual,
                                "suggested": "", "source": "—",
                                "votes": 0, "decision": "SIN_DATOS"})
            continue
        decision = "APLICAR" if (s["votes"] >= 1 and not s["proyecto_all"] or
                                  len(s["proyecto_all"]) == 1) else "REVISAR"
        suggestions.append({"case_id": cid, "actual": actual,
                            "suggested": s["suggested"], "source": s["source"],
                            "votes": s["votes"], "decision": decision,
                            "proyecto_all": s["proyecto_all"],
                            "reviso_all": s["reviso_all"]})

    # Imprime
    by_dec = Counter(s["decision"] for s in suggestions)
    print(f"Resumen: {dict(by_dec)}\n")
    for s in suggestions[:60]:
        print(f"  c{s['case_id']:>3} [{s['decision']:<10}] "
              f"actual={(s['actual'] or '')[:30]!r:<32} → {s['suggested']!r} "
              f"[{s['source']} {s.get('votes',0)} votos]")
    if len(suggestions) > 60:
        print(f"  ... +{len(suggestions)-60} más en CSV")

    # CSV
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = ROOT / "data" / f"sugerencias_responsable_desacato_{ts}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "actual", "suggested", "source",
                    "votes", "decision", "proyecto_all", "reviso_all"])
        for s in suggestions:
            w.writerow([s["case_id"], s["actual"], s["suggested"], s["source"],
                        s.get("votes", 0), s["decision"],
                        s.get("proyecto_all", {}), s.get("reviso_all", {})])
    print(f"\n📄 CSV: {out.relative_to(ROOT)}")

    if args.apply:
        to_apply = [s for s in suggestions if s["decision"] == "APLICAR"
                    and s["suggested"]]
        if not to_apply:
            print("\nNada que aplicar (todos requieren REVISAR o sin datos).")
            return 0
        # Backup
        import shutil
        bak = DB_PATH.with_suffix(f".db.bak_pre_resp_desacato_fix_{ts}")
        shutil.copy2(DB_PATH, bak)
        print(f"\nbackup: {bak.name}")
        for s in to_apply:
            db.execute("UPDATE cases SET responsable_desacato=?, "
                       "abogado_incidente=?, updated_at=? WHERE id=?",
                       (s["suggested"], s["suggested"], datetime.utcnow(),
                        s["case_id"]))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print(f"✓ Aplicados: {len(to_apply)} casos actualizados.")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
