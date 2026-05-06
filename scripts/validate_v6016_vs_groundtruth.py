"""Valida v6.0.16 verdict (cache + reglas cognitivas) contra claude_ground_truth.jsonl."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.email.case_lookup_cache import get_cache
from backend.cognition.bayesian_assignment import infer_assignment
from backend.extraction.ir_models import DocumentIR, DocumentZone


def _build_ir(doc):
    txt = doc.extracted_text or ""
    vs = json.loads(doc.visual_signature_json) if doc.visual_signature_json else {}
    head = txt[:2000]; body = txt[:150_000]; foot = txt[-4000:] if len(txt) > 4000 else txt
    zones = []
    if head.strip(): zones.append(DocumentZone(zone_type="HEADER", text=head))
    if body.strip(): zones.append(DocumentZone(zone_type="BODY", text=body))
    if foot.strip() and foot != head: zones.append(DocumentZone(zone_type="FOOTER_TAIL", text=foot))
    ir = DocumentIR(filename=doc.filename or "", doc_type=doc.doc_type or "OTRO",
                    priority=9, zones=zones, full_text=txt)
    ir.visual_signature = vs
    return ir


def map_claude_to_v6016(claude_decision: str) -> str:
    """Mapeo de claude_decision a verdict de v6.0.16 (OK/NO_PERTENECE/SOSPECHOSO/MOVE_TO)."""
    mapping = {
        "KEEP_OK": "OK",
        "MOVE_TO": "NO_PERTENECE",  # v6.0.16 tiene target_case_id; verdict será NO_PERTENECE
        "AMBIGUOUS": "SOSPECHOSO",
        "MOVE_TO_REQUIRES_LOOKUP": "SOSPECHOSO",
        "TRULY_ORPHAN_CONFIRMED": "NO_PERTENECE",
        "SOSPECHOSO_LEGITIMATE": "SOSPECHOSO",
    }
    return mapping.get(claude_decision, "SOSPECHOSO")


def main():
    db = SessionLocal()
    cache = get_cache()
    cache.build(db)

    gt_path = ROOT / "data/claude_ground_truth.jsonl"
    truth = [json.loads(line) for line in gt_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    matches = 0
    target_matches = 0
    target_total = 0
    rows = []

    for entry in truth:
        doc_id = entry["doc_id"]
        claude_dec = entry["claude_decision"]
        claude_target = entry.get("claude_target")

        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            continue
        case = db.query(Case).filter(Case.id == doc.case_id).first()
        if not case:
            continue

        ir = _build_ir(doc)
        verdict = infer_assignment(case, ir, doc=doc)

        expected = map_claude_to_v6016(claude_dec)
        match = (verdict.verdict == expected)

        # Para MOVE_TO, además validar que target_case_id coincide
        if claude_dec == "MOVE_TO" and claude_target:
            target_total += 1
            if verdict.target_case_id == claude_target:
                target_matches += 1

        if match:
            matches += 1

        rows.append({
            "doc_id": doc_id,
            "claude_dec": claude_dec,
            "claude_target": claude_target,
            "v6016_verdict": verdict.verdict,
            "v6016_posterior": round(verdict.posterior, 3),
            "v6016_target": verdict.target_case_id,
            "v6016_target_evidence": verdict.target_evidence,
            "match": match,
            "rule": entry["rule"],
        })

    print(f"\n=== Validación v6.0.16 vs Claude ground truth ===")
    print(f"Matches verdict: {matches}/{len(truth)} = {matches/len(truth)*100:.0f}%")
    if target_total:
        print(f"Matches target_case_id: {target_matches}/{target_total} = {target_matches/target_total*100:.0f}%")
    print()
    print(f'{"doc":>5s}  {"claude":>22s}  {"v6.0.16":>14s}  {"post":>6s}  {"tgt":>5s}  {"match":>5s}  rule')
    for r in rows:
        flag = "✓" if r["match"] else "✗"
        print(f'{r["doc_id"]:5d}  {r["claude_dec"]:>22s}  {r["v6016_verdict"]:>14s}  {r["v6016_posterior"]:>6.3f}  {str(r["v6016_target"] or "-"):>5s}  {flag:>5s}  {r["rule"][:40]}')

    db.close()


if __name__ == "__main__":
    main()
