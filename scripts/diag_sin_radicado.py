"""Propuesta SOLO LECTURA de radicado_23_digitos para los casos sin_radicado.

Criterio fuerte (campo de INGESTA, regex estricto, dept-agnóstico):
- rad23 = 23 dígitos tras quitar separadores [-. –—], con bloque de AÑO válido
  (posición 12:16 ∈ 2018..2027). NO confundir con FOREST (11d) ni número interno
  Gobernación ("2026-00068" corto, "20260021812" 11d).
- Mayor confianza: aparece en el FILENAME o junto a etiqueta RADICADO/RAD del juzgado.
- Se valida el año contra el folder_name / radicado_forest si hay pista.
NO escribe nada. Salida: data/diag_sin_radicado.json + tabla.
"""
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.services.case_service import _get_case_completitud  # noqa

SEP = r"[-.\s–—]*"
# 23 dígitos contiguos o con separadores. GREEDY (el non-greedy cortaba los dígitos).
RE_CAND = re.compile(r"\d[\d\-.\s–—]{18,40}\d")
RE_LABEL = re.compile(r"(?i)(?:RADICAD[OA]|RAD\.?|EXPEDIENTE|PROCESO\s+No|No\.?\s*[úu]nico)")
RE_FOLDER_SHORT = re.compile(r"(20\d{2})[-.\s]?0?(\d{4,5})")


def norm(s: str) -> str:
    return re.sub(r"[-.\s–—]", "", s)


def valid_rad23(digits: str) -> bool:
    if len(digits) != 23:
        return False
    year = int(digits[12:16])
    return 2018 <= year <= 2027


def candidates(text: str):
    """Devuelve [(rad23, contexto_label_bool)] de un texto."""
    out = []
    for m in RE_CAND.finditer(text):
        d = norm(m.group(0))
        if not valid_rad23(d):
            continue
        # ¿hay etiqueta RADICADO en los 40 chars previos?
        pre = text[max(0, m.start() - 40):m.start()]
        out.append((d, bool(RE_LABEL.search(pre))))
    return out


def main():
    db = SessionLocal()
    cases = [c for c in db.query(Case).all() if not (c.radicado_23_digitos or "").strip()]
    print(f"Casos sin radicado_23_digitos: {len(cases)}\n")
    rows = []
    for c in cases:
        # rad corto del folder → (año, consecutivo 5d) para casar con el 23d
        short = None
        m = RE_FOLDER_SHORT.search(c.folder_name or "")
        if m:
            short = (m.group(1), m.group(2).zfill(5))
        fn_cands = Counter()
        txt_cands = Counter()
        label_cands = Counter()
        for d in c.documents:
            for d23, _ in candidates(d.filename or ""):
                fn_cands[d23] += 1
            for d23, lab in candidates((d.extracted_text or "")[:40000]):
                txt_cands[d23] += 1
                if lab:
                    label_cands[d23] += 1
        allc = set(fn_cands) | set(txt_cands)

        def matches_folder(r):
            return short is not None and r[12:16] == short[0] and r[16:21] == short[1]

        # ranking: coincide con folder (×1000) > filename > label > frecuencia
        best = None
        if allc:
            best = max(allc, key=lambda r: (1000 * matches_folder(r) + fn_cands[r] * 100
                                            + label_cands[r] * 10 + txt_cands[r]))
        conf = "none"
        if best:
            if matches_folder(best):
                conf = "folder_match"
            elif fn_cands[best]:
                conf = "filename"
            elif label_cands[best]:
                conf = "label"
            elif txt_cands[best] >= 2:
                conf = "texto_freq"
            else:
                conf = "texto_1"
        rows.append({
            "case_id": c.id, "accionante": c.accionante,
            "folder": c.folder_name, "forest": c.radicado_forest,
            "best": best, "conf": conf,
            "n_cands": len(allc),
            "fn": fn_cands.get(best, 0) if best else 0,
            "label": label_cands.get(best, 0) if best else 0,
            "txt": txt_cands.get(best, 0) if best else 0,
            "otros": [r for r in allc if r != best][:4],
        })

    from collections import Counter as C
    print("=== CONFIANZA ===")
    for k, v in C(r["conf"] for r in rows).most_common():
        print(f"  {k}: {v}")
    print()
    for r in sorted(rows, key=lambda x: x["conf"]):
        ot = f" otros={r['otros']}" if r["otros"] else ""
        print(f"c{r['case_id']:<4} [{r['conf']:<10}] best={r['best']} (fn={r['fn']},lbl={r['label']},txt={r['txt']}){ot}")
    json.dump(rows, open("data/diag_sin_radicado.json", "w"), ensure_ascii=False, indent=2)
    print(f"\n-> data/diag_sin_radicado.json ({len(rows)} casos)")
    db.close()


if __name__ == "__main__":
    main()
