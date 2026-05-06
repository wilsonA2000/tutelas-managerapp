"""Diagnóstico global de docs SOSPECHOSO/NO_PERTENECE.

Read-only. Para cada doc problemático:
  1. Construye DocumentIR mínimo desde extracted_text + visual_signature_json (DB).
  2. Llama harvest_identifiers — identifica rad23/rad_corto/forest/cc en el doc.
  3. Cruza esos identifiers con CaseLookupCache.lookup_all → target_case_id si hit.
  4. Cruza también filename (extrae rad_corto AAAA-NNNNN visible en el nombre).
  5. Detecta carpeta mal nombrada (folder_name vs radicado_23_digitos del case actual).

Output:
  data/entropy_diagnosis.csv   — una fila por doc
  data/entropy_diagnosis_summary.json — buckets agregados

Veredictos propuestos:
  KEEP_OK              : el doc tiene identifier que coincide con case actual
  MOVE_TO              : identifier coincide con OTRO caso existente
  TRULY_ORPHAN         : no se detectaron identifiers válidos
  AMBIGUOUS            : varios casos posibles
  FOLDER_MISLABELED    : la carpeta tiene año/consecutivo distinto al rad23 del case
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, Document  # noqa: E402
from backend.email.case_lookup_cache import get_cache  # noqa: E402
from backend.email.rad_utils import normalize_rad23, derive_rad_corto_from_rad23  # noqa: E402
from backend.cognition.canonical_identifiers import harvest_identifiers  # noqa: E402
from backend.extraction.ir_models import DocumentIR, DocumentZone  # noqa: E402

OUT_CSV = ROOT / "data" / "entropy_diagnosis.csv"
OUT_JSON = ROOT / "data" / "entropy_diagnosis_summary.json"


def _norm_word(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def _build_minimal_ir(doc) -> DocumentIR:
    """Construye DocumentIR mínimo desde DB sin reabrir PDF."""
    text = doc.extracted_text or ""
    vs = {}
    if doc.visual_signature_json:
        try:
            vs = json.loads(doc.visual_signature_json)
        except Exception:
            vs = {}

    head = text[:2000]
    body = text[:150_000]
    foot = text[-4000:] if len(text) > 4000 else text

    zones = []
    if head.strip():
        zones.append(DocumentZone(zone_type="HEADER", text=head))
    if body.strip():
        zones.append(DocumentZone(zone_type="BODY", text=body))
    if foot.strip() and foot != head:
        zones.append(DocumentZone(zone_type="FOOTER_TAIL", text=foot))

    ir = DocumentIR(
        filename=doc.filename or "",
        doc_type=doc.doc_type or "OTRO",
        priority=9,
        zones=zones,
        full_text=text,
    )
    if vs:
        # No es campo del dataclass, lo seteamos como atributo dinámico
        ir.visual_signature = vs
    return ir


def _extract_rad_corto_from_filename(fn: str) -> str | None:
    """Extrae 'AAAA-NNNNN' visible en el nombre."""
    if not fn:
        return None
    # patrones: 2026-00045, 2026-0045, 2026-00045-00, 2026-00045 / 2025_00012
    m = re.search(r"\b(20\d{2})[-_ ]?0*(\d{2,5})(?:[-_ ]\d{2})?\b", fn)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(5)}"
    return None


def _extract_year_seq(s: str) -> tuple[str, str] | None:
    """Extrae (año, consecutivo padded) de un string como folder_name o rad23 normalizado."""
    if not s:
        return None
    # primero buscar 20YY+5 dígitos contiguos (rad23 normalizado)
    m = re.search(r"(20\d{2})(\d{5})", re.sub(r"\D", "", s))
    if m:
        return (m.group(1), m.group(2))
    # luego YYYY-NNNNN con separadores
    m = re.match(r"(20\d{2})[-_ ]?0*(\d{1,5})", s)
    if m:
        return (m.group(1), m.group(2).zfill(5))
    return None


def detect_folder_mislabeling(case) -> dict | None:
    """Compara folder_name vs radicado_23_digitos del case."""
    folder_yc = _extract_year_seq(case.folder_name or "")
    rad_yc = _extract_year_seq(case.radicado_23_digitos or "")
    if not folder_yc or not rad_yc:
        return None
    if folder_yc != rad_yc:
        return {
            "case_id": case.id,
            "folder_name": case.folder_name,
            "rad23": case.radicado_23_digitos,
            "folder_yc": f"{folder_yc[0]}-{folder_yc[1]}",
            "rad_yc": f"{rad_yc[0]}-{rad_yc[1]}",
        }
    return None


def diagnose_doc(doc, case, cache) -> dict:
    """Devuelve dict con el diagnóstico de un solo doc."""
    ir = _build_minimal_ir(doc)
    idset = harvest_identifiers(ir)

    # Identifiers cosechados
    rad23s = {i.value for i in idset.of_kind("rad23")}
    rad_cortos = {i.value for i in idset.of_kind("rad_corto")}
    forests = {i.value for i in idset.of_kind("forest")}
    ccs = {i.value for i in idset.of_kind("cc")}

    # También extraer rad_corto del filename (no del texto)
    fn_rad_corto = _extract_rad_corto_from_filename(doc.filename or "")
    if fn_rad_corto:
        rad_cortos.add(fn_rad_corto)

    # Caso actual: ¿alguno de los identifiers apunta a este caso?
    case_rad23 = case.radicado_23_digitos or ""
    case_rad23_norm = normalize_rad23(case_rad23)
    case_rad_corto = derive_rad_corto_from_rad23(case_rad23) or _extract_rad_corto_from_filename(case.folder_name or "")

    matches_self = False
    if case_rad23_norm and any(normalize_rad23(r)[:20] == case_rad23_norm[:20] for r in rad23s):
        matches_self = True
    if case_rad_corto and case_rad_corto in rad_cortos:
        matches_self = True

    # ¿Apuntan a OTRO caso? Cross-DB lookup
    candidates = Counter()  # {case_id: count_signals}
    candidate_evidence = defaultdict(list)
    for r in rad23s:
        hit = cache.lookup_by_rad23(r)
        if hit and hit != case.id:
            candidates[hit] += 3  # rad23 es la señal más fuerte
            candidate_evidence[hit].append(f"rad23={r[:20]}")
    for rc in rad_cortos:
        hit = cache.lookup_by_rad_corto(rc)
        if hit and hit != case.id:
            candidates[hit] += 1
            candidate_evidence[hit].append(f"rad_corto={rc}")
    for fr in forests:
        hit = cache.lookup_by_forest(fr)
        if hit and hit != case.id:
            candidates[hit] += 2
            candidate_evidence[hit].append(f"forest={fr}")
    for cc in ccs:
        hit = cache.lookup_by_cc(cc)
        if hit and hit != case.id:
            candidates[hit] += 2
            candidate_evidence[hit].append(f"cc=hash")

    target_case_id = None
    target_evidence = ""
    verdict = ""
    if matches_self and not candidates:
        verdict = "KEEP_OK"
    elif candidates:
        # más alta confianza gana
        ranked = candidates.most_common()
        if len(ranked) == 1 or ranked[0][1] >= ranked[1][1] * 2:
            target_case_id = ranked[0][0]
            target_evidence = "; ".join(candidate_evidence[target_case_id][:3])
            verdict = "MOVE_TO" if not matches_self else "MIXED_SIGNAL"
        else:
            verdict = "AMBIGUOUS"
            target_evidence = f"top: {ranked[0][0]}={ranked[0][1]}, {ranked[1][0]}={ranked[1][1]}"
    elif not rad23s and not rad_cortos and not forests:
        verdict = "TRULY_ORPHAN"
    else:
        # Tiene identifiers pero ninguno cruza con DB
        verdict = "TRULY_ORPHAN"

    return {
        "doc_id": doc.id,
        "case_id": case.id,
        "case_folder": case.folder_name,
        "filename": doc.filename,
        "current_status": doc.verificacion,
        "rad23s_found": ";".join(rad23s) if rad23s else "",
        "rad_cortos_found": ";".join(rad_cortos) if rad_cortos else "",
        "forests_found": ";".join(forests) if forests else "",
        "ccs_count": len(ccs),
        "matches_self": matches_self,
        "verdict_proposed": verdict,
        "target_case_id": target_case_id or "",
        "target_evidence": target_evidence,
        "extracted_text_len": len(doc.extracted_text or ""),
    }


def main():
    db = SessionLocal()
    print("Construyendo CaseLookupCache...")
    cache = get_cache()
    stats_cache = cache.build(db)
    print(f"  cache: {stats_cache}")

    docs = db.query(Document).filter(
        Document.verificacion.in_(["SOSPECHOSO", "NO_PERTENECE", "REVISAR"])
    ).all()
    print(f"Diagnosticando {len(docs)} docs...")

    cases_by_id = {c.id: c for c in db.query(Case).all()}

    rows = []
    for i, doc in enumerate(docs, 1):
        case = cases_by_id.get(doc.case_id)
        if not case:
            continue
        try:
            row = diagnose_doc(doc, case, get_cache())
            rows.append(row)
        except Exception as e:
            print(f"  ! doc {doc.id} falló: {e}")
        if i % 100 == 0:
            print(f"  ... {i}/{len(docs)}")

    # Detectar carpetas mal nombradas (sobre TODOS los casos COMPLETO, no solo los de docs problemáticos)
    mislabeled = []
    for c in cases_by_id.values():
        if c.processing_status == "COMPLETO":
            ml = detect_folder_mislabeling(c)
            if ml:
                mislabeled.append(ml)

    # Output CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV escrito: {OUT_CSV}")

    # Summary
    by_verdict = Counter(r["verdict_proposed"] for r in rows)
    by_status_verdict = Counter((r["current_status"], r["verdict_proposed"]) for r in rows)
    move_to_targets = Counter(r["target_case_id"] for r in rows if r["verdict_proposed"] == "MOVE_TO")

    summary = {
        "total_docs_diagnosticados": len(rows),
        "verdicts": dict(by_verdict),
        "status_x_verdict": {f"{k[0]}->{k[1]}": v for k, v in by_status_verdict.items()},
        "top_target_cases_for_move": move_to_targets.most_common(20),
        "carpetas_mal_nombradas": mislabeled,
        "cache_stats": stats_cache,
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Summary: {OUT_JSON}")
    print()
    print("=== VEREDICTOS PROPUESTOS ===")
    for v, n in sorted(by_verdict.items(), key=lambda x: -x[1]):
        print(f"  {v:20s}: {n}")
    print()
    print(f"Carpetas mal nombradas detectadas: {len(mislabeled)}")
    for ml in mislabeled[:10]:
        print(f"  case {ml['case_id']}: folder={ml['folder_yc']} vs rad23={ml['rad_yc']}")

    db.close()


if __name__ == "__main__":
    main()
