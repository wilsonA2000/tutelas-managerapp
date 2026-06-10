#!/usr/bin/env python3
"""¿Qué casos necesitan LEGÍTIMAMENTE el LLM? — auditoría read-only contra el cuadro vivo.

Filosofía (ver feedback_ground_truth_cuadro_vivo, project_llm_optimizacion):
  - El LLM solo sirve para campos SEMÁNTICOS donde la cognición (regex/anclaje) falla.
  - Un campo vacío PORQUE NO EXISTE el documento fuente es VACÍO LEGÍTIMO → se excluye
    (ni el regex ni el anclaje pueden extraer lo que no está; el LLM tampoco lo vería).
  - El problema de "ambigüedad" suele ser RETRIEVAL/clasificación (doc equivocado o
    DESCONOCIDO), NO falta de inteligencia → tampoco es trabajo de LLM.

Por eso este script NO corre ningún modelo. Solo lee la DB y clasifica cada caso en:
  lleno+doc · VACÍO+doc (=cohorte LLM legítima) · vacío-sin-doc (=excluir) · lleno-sin-doc (=ambiguo/retrieval)
y vuelca los case_ids de la cohorte LLM a data/llm_cohort_<campo>.json para el bake-off posterior.

Uso:  ./venv/bin/python3 scripts/llm_need_audit.py
"""
from __future__ import annotations
import json, re, sqlite3, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"

# Documento(s) que LEGÍTIMAMENTE contienen cada campo. Si el caso no tiene ninguno,
# el vacío es legítimo y se excluye del veredicto "necesita LLM".
ADEQUATE_DOCS = {
    "pretensiones": ("DEMANDA_TUTELA", "ANEXO_DEMANDA", "AUTO_ADMISORIO",
                     "PDF_AUTO_ADMISORIO", "DOCX_SOLICITUD"),
    # observaciones es narrativa derivada del caso; "fuente" = tener algún doc sustantivo.
    "observaciones": ("DEMANDA_TUTELA", "AUTO_ADMISORIO", "SENTENCIA_1RA",
                      "RESPUESTA", "INCIDENTE_DESACATO"),
}
# Frases típicas de DOC AJENO en pretensiones (respuesta SED / fallo / auto, no la demanda).
WRONG_SRC = re.compile(r"damos respuesta|abstener|sancionar|cumplimiento al fallo|"
                       r"admisi[oó]n de la|avoca|notif[ií]|RESUELVE|por reparto|"
                       r"tener por contestada|REQUERIR a la", re.I)


def _empty(v) -> bool:
    return not v or not str(v).strip()


def audit(field: str, db: sqlite3.Connection) -> dict:
    docs: dict[int, set] = defaultdict(set)
    for r in db.execute("SELECT case_id, doc_type FROM documents"):
        docs[r[0]].add(r[1])
    has_src = {cid for cid, dt in docs.items() if dt & set(ADEQUATE_DOCS[field])}
    rows = db.execute(f"SELECT id, {field} FROM cases").fetchall()

    full_doc = full_nodoc = empty_doc = empty_nodoc = 0
    ambiguous = wrong_src = 0
    llm_cohort: list[int] = []          # vacío + doc = el regex falló teniendo la fuente
    ambiguous_cohort: list[int] = []    # lleno pero de fuente dudosa
    for cid, val in rows:
        e, hd = _empty(val), cid in has_src
        if not e and hd:
            full_doc += 1
            if WRONG_SRC.search(str(val)):
                wrong_src += 1; ambiguous_cohort.append(cid)
        elif not e and not hd:
            full_nodoc += 1; ambiguous += 1; ambiguous_cohort.append(cid)
        elif e and hd:
            empty_doc += 1; llm_cohort.append(cid)
        else:
            empty_nodoc += 1
    return {
        "field": field, "total": len(rows), "con_doc": len(has_src),
        "lleno_con_doc": full_doc, "lleno_sin_doc": full_nodoc,
        "VACIO_con_doc__cohorte_llm": empty_doc, "vacio_sin_doc__excluir": empty_nodoc,
        "lleno_frase_doc_ajeno": wrong_src, "lleno_sin_fuente_reconocida": ambiguous,
        "llm_cohort_ids": sorted(llm_cohort),
        "ambiguous_cohort_ids": sorted(ambiguous_cohort),
    }


def main() -> int:
    if not DB.exists():
        print(f"DB no encontrada: {DB}", file=sys.stderr); return 1
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for field in ("pretensiones", "observaciones"):
        r = audit(field, db)
        print(f"\n=== {field.upper()} (N={r['total']}, con doc adecuado={r['con_doc']}) ===")
        print(f"  lleno + con doc                 : {r['lleno_con_doc']:>4}"
              f"   (de frase-doc-ajeno: {r['lleno_frase_doc_ajeno']})")
        print(f"  lleno SIN doc (ambiguo/retrieval): {r['lleno_sin_doc']:>4}")
        print(f"  VACÍO + con doc  → COHORTE LLM   : {r['VACIO_con_doc__cohorte_llm']:>4}  {r['llm_cohort_ids']}")
        print(f"  vacío SIN doc    → EXCLUIR       : {r['vacio_sin_doc__excluir']:>4}")
        out = ROOT / "data" / f"llm_cohort_{field}.json"
        out.write_text(json.dumps({
            "field": field,
            "llm_cohort_ids": r["llm_cohort_ids"],
            "ambiguous_cohort_ids": r["ambiguous_cohort_ids"],
        }, ensure_ascii=False, indent=2))
        print(f"  → cohorte volcada a data/{out.name} "
              f"(LLM={len(r['llm_cohort_ids'])} · ambiguos={len(r['ambiguous_cohort_ids'])})")
    db.close()
    print("\nNota: re-correr DESPUÉS de mejorar regex para ver el gap residual real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
