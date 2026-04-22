"""Benchmark del módulo cognitivo (v5.3.1).

Sobre una muestra de casos COMPLETO de la DB, mide cuántos campos
semánticos logra llenar la cognición local sin llamar IA externa.

Métricas:
- Por caso: cuántos campos llenó cognición / cuántos esperaríamos IA.
- Agregados: % casos con cognición COMPLETA (0 campos necesitan IA).
- Per-campo: cuántas veces cada campo se llena vs queda vacío.
"""

import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import sqlite3
from collections import Counter

from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.cognition import cognitive_fill, SEMANTIC_FIELDS_COGNITIVE


def benchmark(limit: int = 20):
    db = SessionLocal()
    cases = (
        db.query(Case)
        .filter(Case.processing_status == "COMPLETO")
        .order_by(Case.id.desc())
        .limit(limit)
        .all()
    )
    print(f"Analizando {len(cases)} casos COMPLETO con cognición local...")
    print()

    stats = {
        "total_cases": len(cases),
        "full_coverage": 0,  # Casos con >=70% campos semánticos llenados
        "partial_coverage": 0,
        "zero_coverage": 0,
        "field_fill_count": Counter(),
        "case_details": [],
    }

    for case in cases:
        full_text_parts = [d.extracted_text for d in case.documents if d.extracted_text]
        full_text = "\n\n".join(full_text_parts[:15])
        if not full_text.strip():
            continue
        meta = {
            "id": case.id,
            "fecha_ingreso": case.fecha_ingreso or "",
            "radicado_23_digitos": case.radicado_23_digitos or "",
            "radicado_forest": case.radicado_forest or "",
            "abogado_responsable": case.abogado_responsable or "",
            "incidente": case.incidente or "",
        }
        docs_for_cog = [
            {"filename": d.filename, "text": d.extracted_text or "",
             "doc_type": d.doc_type or ""}
            for d in case.documents[:15] if d.extracted_text
        ]
        results = cognitive_fill(meta, full_text, existing=None, documents=docs_for_cog)
        filled = sorted(results.keys())
        coverage = len(filled) / len(SEMANTIC_FIELDS_COGNITIVE)

        for f in filled:
            stats["field_fill_count"][f] += 1

        if coverage >= 0.7:
            stats["full_coverage"] += 1
        elif coverage > 0:
            stats["partial_coverage"] += 1
        else:
            stats["zero_coverage"] += 1

        stats["case_details"].append({
            "id": case.id,
            "folder": case.folder_name[:50] if case.folder_name else "",
            "filled_count": len(filled),
            "coverage_pct": round(coverage * 100, 1),
            "filled_fields": filled,
        })

    # Print report
    print("=" * 70)
    print("RESULTADOS")
    print("=" * 70)
    print(f"Casos totales: {stats['total_cases']}")
    print(f"  Cobertura alta (>=70%): {stats['full_coverage']} ({100*stats['full_coverage']/stats['total_cases']:.1f}%)")
    print(f"  Cobertura parcial:      {stats['partial_coverage']}")
    print(f"  Sin cobertura:          {stats['zero_coverage']}")
    print()
    print("Campos llenados por cognición (frecuencia sobre 20 casos):")
    for field, count in stats["field_fill_count"].most_common():
        pct = 100 * count / stats["total_cases"]
        bar = "█" * int(pct / 5)
        print(f"  {field:25s} {count:3d}/{stats['total_cases']} ({pct:5.1f}%) {bar}")
    print()
    print("Por caso (detalle):")
    for d in stats["case_details"][:15]:
        print(f"  #{d['id']} ({d['coverage_pct']:5.1f}%): {d['filled_count']} campos — {d['folder']}")

    db.close()
    return stats


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    benchmark(limit)
