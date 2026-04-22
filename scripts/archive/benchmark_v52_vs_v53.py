"""Benchmark v5.2 (sin PII) vs v5.3 (con capa PII).

Mide sobre una muestra de casos reales:
- Presencia de PII literal en payload que va a IA (objetivo v5.3: 0)
- Tokens input/output
- Latencia de redactor/rehidrator
- Tokens acuñados por modo

Uso:
    python3 scripts/benchmark_v52_vs_v53.py --sample 10 --mode selective
    python3 scripts/benchmark_v52_vs_v53.py --sample 10 --mode aggressive

No llama IA real — ejecuta la redacción local y genera reporte markdown.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document
from backend.privacy import RedactionContext, redact_payload, assert_clean
from backend.extraction.unified import _collect_known_entities


PII_PROBES = {
    "CC_DOTS": re.compile(r"\b\d{1,3}\.\d{3}\.\d{3}\b"),
    "CC_BARE": re.compile(r"(?<!\[)\b\d{8,10}\b(?!\])"),
    "NUIP_DOTS": re.compile(r"\b\d{1,3}\.\d{3}\.\d{3}\.\d{3}\b"),
    "PHONE_MOBILE": re.compile(r"\b3[0-5]\d{8}\b"),
    "EMAIL": re.compile(r"[\w\.\-\+]+@[\w\.\-]+\.\w{2,}"),
    "ADDR": re.compile(r"\b(?:Calle|Cll|Carrera|Cra)\s*\d+[A-Z]?\s*#?\s*\d+\s*[\-–]\s*\d+\b"),
}


def _count_pii(text: str) -> dict[str, int]:
    return {k: len(p.findall(text)) for k, p in PII_PROBES.items()}


def _build_payload(case: Case) -> list[dict]:
    """Arma ia_doc_texts como lo hace unified.py (aprox) — solo texto de documentos."""
    texts = []
    for d in case.documents:
        if d.extracted_text:
            texts.append({"filename": d.filename, "text": d.extracted_text})
    # Simular contexto IR con narrativa de observaciones
    if case.observaciones:
        texts.insert(0, {"filename": "CONTEXTO_IR", "text": case.observaciones})
    return texts


def benchmark_case(db, case: Case, mode: str) -> dict:
    payload = _build_payload(case)
    if not payload:
        return {"case_id": case.id, "skip": "sin textos"}

    orig_text = " ".join(d["text"] for d in payload)
    orig_pii = _count_pii(orig_text)
    orig_len = len(orig_text)

    known = _collect_known_entities({}, case)
    t0 = time.time()
    ctx = RedactionContext(case_id=case.id, mode=mode, known_entities=known)
    red = redact_payload(payload, ctx)
    red_ms = int((time.time() - t0) * 1000)

    red_text = " ".join(d["text"] for d in red.docs)
    red_pii = _count_pii(red_text)
    red_len = len(red_text)

    v = assert_clean(red.docs, mode=mode, known_entities=known)

    return {
        "case_id": case.id,
        "folder_name": case.folder_name,
        "mode": mode,
        "orig_chars": orig_len,
        "redacted_chars": red_len,
        "char_delta_pct": round((red_len - orig_len) / orig_len * 100, 1) if orig_len else 0,
        "orig_pii": orig_pii,
        "redacted_pii": red_pii,
        "tokens_minted": red.stats.get("tokens_minted", 0),
        "spans_detected": red.stats.get("spans_detected", 0),
        "redactor_ms": red_ms,
        "violations": len(v),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=10)
    ap.add_argument("--mode", choices=["selective", "aggressive"], default="selective")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        cases = (
            db.query(Case)
            .filter(Case.processing_status == "COMPLETO")
            .order_by(Case.id.desc())
            .limit(args.sample)
            .all()
        )
        print(f"Analizando {len(cases)} casos en modo {args.mode}...")

        results = []
        for c in cases:
            r = benchmark_case(db, c, args.mode)
            results.append(r)
            print(f"  #{r['case_id']} {r.get('folder_name', '')[:40]}: "
                  f"tokens={r.get('tokens_minted', 0)} "
                  f"violations={r.get('violations', 0)} "
                  f"orig_pii={sum(r.get('orig_pii', {}).values())} → "
                  f"red_pii={sum(r.get('redacted_pii', {}).values())}")

        # Agregados
        valid = [r for r in results if "skip" not in r]
        if valid:
            total_orig = sum(sum(r["orig_pii"].values()) for r in valid)
            total_red = sum(sum(r["redacted_pii"].values()) for r in valid)
            total_viol = sum(r["violations"] for r in valid)
            avg_tokens = sum(r["tokens_minted"] for r in valid) / len(valid)
            avg_ms = sum(r["redactor_ms"] for r in valid) / len(valid)
            avg_delta_pct = sum(r["char_delta_pct"] for r in valid) / len(valid)

            print("\n" + "=" * 60)
            print(f"RESULTADOS AGREGADOS (modo={args.mode}, N={len(valid)})")
            print("=" * 60)
            print(f"  PII total ANTES:     {total_orig}")
            print(f"  PII total DESPUÉS:   {total_red}  (reducción {100*(1-total_red/total_orig) if total_orig else 0:.1f}%)")
            print(f"  Violaciones gate:    {total_viol}")
            print(f"  Tokens promedio:     {avg_tokens:.1f}")
            print(f"  Latencia promedio:   {avg_ms:.0f}ms")
            print(f"  Delta tamaño texto:  {avg_delta_pct:+.1f}% (tokens más largos que PII original)")

        out_path = Path(args.out or f"BENCHMARK_V53_{args.mode}_{time.strftime('%Y%m%d_%H%M%S')}.json")
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        print(f"\nReporte completo: {out_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
