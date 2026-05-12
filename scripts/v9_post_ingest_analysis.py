#!/usr/bin/env python3
"""Análisis post-ingesta v9.2 — verificacion_score + cruce de referencias.

Después de una ingesta limpia (`scripts/ingest_from_gmail_v9.py`), este script:

1. ALTER TABLE documents para agregar columnas v9.2 (idempotente)
2. Calcula `verificacion_score` (0-1) para cada Document basado en:
   - rad21 match con su case: peso alto
   - método de cascada que lo asignó (rad21 > rad_corto > thread > shell > orphan)
   - sender confiable (apoyojuridicosed > otros)
   - hermanos del email también OK
3. Cruce de referencias: para cada doc SOSPECHOSO (score bajo + rad propio),
   verifica si su rad21 coincide con OTRO case existente en la DB. Si sí,
   guarda `suggested_target_case_id` + `suggested_reason`.
4. Detección de patrones colectivos: si N>=2 docs del mismo case_origen apuntan
   al mismo case_destino, lo reporta como "patrón sistémico" para revisión.

Uso:
    python3 scripts/v9_post_ingest_analysis.py
    python3 scripts/v9_post_ingest_analysis.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from backend.database.database import SessionLocal, engine  # noqa: E402
from backend.database.models import Case, Document, Email  # noqa: E402
from backend.v9.regex_pass import _extract_radicado_23  # noqa: E402


# ============================================================
# 1. Migración del schema (idempotente)
# ============================================================

def ensure_schema():
    """Agrega columnas v9.2 si no existen."""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(documents)")).fetchall()}
        added = []
        if 'verificacion_score' not in cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN verificacion_score FLOAT"))
            added.append('verificacion_score')
        if 'verificacion_breakdown' not in cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN verificacion_breakdown TEXT"))
            added.append('verificacion_breakdown')
        if 'suggested_target_case_id' not in cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN suggested_target_case_id INTEGER REFERENCES cases(id)"))
            added.append('suggested_target_case_id')
        if 'suggested_reason' not in cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN suggested_reason VARCHAR"))
            added.append('suggested_reason')
        conn.commit()
        return added


# ============================================================
# 2. Cálculo de verificacion_score
# ============================================================

# Pesos del scoring graduado (suman a ~1.0)
W_RAD_MATCH = 0.50            # rad21 del doc coincide con rad21 del case
W_DOMINANT_MATCH = 0.20       # rad coincide con dominante del email
W_SENDER_CONFIABLE = 0.10     # sender es del flujo SED conocido
W_FAMILY_OK = 0.20            # hermanos del email también OK / case tiene otros docs OK


def compute_verification_score(db, doc: Document) -> tuple[float, dict]:
    """Calcula score 0-1 + breakdown JSON-serializable."""
    breakdown = {}
    score = 0.0
    case = doc.case
    rad_in_doc = _extract_radicado_23(doc.extracted_text or '')
    case_rad = case.radicado_23_digitos if case else None

    # 1. rad21 match con case
    if rad_in_doc and case_rad:
        if rad_in_doc[:21] == case_rad[:21]:
            score += W_RAD_MATCH
            breakdown['rad21_match_case'] = W_RAD_MATCH
        else:
            breakdown['rad21_match_case'] = 0.0
    elif not rad_in_doc and case_rad:
        # Doc sin rad propio pero case tiene → asignación por contexto del email
        # Boost parcial (no es señal contraria, solo ausencia de evidencia)
        score += W_RAD_MATCH * 0.5
        breakdown['rad21_match_case_inferido'] = W_RAD_MATCH * 0.5
    elif not case_rad:
        # Case sin rad (orphan) → score neutral
        breakdown['case_sin_rad'] = 0.0

    # 2. Sender confiable
    email = db.query(Email).filter(Email.id == doc.email_id).first() if doc.email_id else None
    if email and email.sender:
        if 'santander.gov.co' in email.sender.lower() or 'ramajudicial' in email.sender.lower() or 'cendoj' in email.sender.lower():
            score += W_SENDER_CONFIABLE
            breakdown['sender_confiable'] = W_SENDER_CONFIABLE

    # 3. Familia: hermanos del email OK / case con otros docs OK
    if email:
        n_siblings_ok = db.query(Document).filter(
            Document.email_id == email.id,
            Document.id != doc.id,
            Document.verificacion == 'OK',
        ).count()
        n_case_ok = db.query(Document).filter(
            Document.case_id == case.id if case else -1,
            Document.id != doc.id,
            Document.verificacion == 'OK',
            Document.doc_type != 'EMAIL_JUDICIAL',
        ).count()
        if n_siblings_ok > 0 or n_case_ok > 0:
            score += W_FAMILY_OK
            breakdown['family_ok'] = W_FAMILY_OK
            breakdown['siblings_ok'] = n_siblings_ok
            breakdown['case_other_ok'] = n_case_ok

    # 4. Match con dominant_rad — solo evaluable si tenemos rad propio
    if rad_in_doc and case_rad and rad_in_doc[:21] == case_rad[:21]:
        score += W_DOMINANT_MATCH
        breakdown['dominant_consistent'] = W_DOMINANT_MATCH

    return min(1.0, score), breakdown


# ============================================================
# 3. Cruce de referencias — para SOSPECHOSOS, ¿el rad apunta a otro case?
# ============================================================

def find_destination_for_foreigns(db, dry_run=False):
    """Para cada doc SOSPECHOSO con rad propio, busca si existe otro case
    con rad21 coincidente. Si sí, guarda sugerencia de movimiento."""
    sospechosos = db.query(Document).filter(Document.verificacion == 'SOSPECHOSO').all()
    matched = 0
    no_target = 0

    for d in sospechosos:
        rad_in_doc = _extract_radicado_23(d.extracted_text or '')
        if not rad_in_doc:
            continue
        case_rad = d.case.radicado_23_digitos if d.case else None
        if case_rad and rad_in_doc[:21] == case_rad[:21]:
            continue  # falso positivo, no aplica sugerencia

        # Buscar OTRO case con rad21 coincidente
        target = db.query(Case).filter(
            Case.radicado_23_digitos.like(f"{rad_in_doc[:21]}%"),
            Case.id != d.case_id,
        ).first()
        if target:
            if not dry_run:
                d.suggested_target_case_id = target.id
                d.suggested_reason = f"rad21={rad_in_doc[:21]} coincide con case#{target.id} ({target.folder_name[:50]})"
            matched += 1
        else:
            no_target += 1

    if not dry_run:
        db.commit()
    return matched, no_target


# ============================================================
# 4. Patrones colectivos
# ============================================================

def detect_collective_misroutes(db) -> list[dict]:
    """Agrupa SOSPECHOSOS por (case_origen, case_destino). Reporta patrones
    con N>=2 docs cruzados (= operador con error sistémico)."""
    grouped = defaultdict(list)
    for d in db.query(Document).filter(
        Document.verificacion == 'SOSPECHOSO',
        Document.suggested_target_case_id.isnot(None),
    ).all():
        key = (d.case_id, d.suggested_target_case_id)
        grouped[key].append(d.id)

    patterns = []
    for (origen, destino), docs in grouped.items():
        if len(docs) < 2:
            continue
        case_o = db.query(Case).filter(Case.id == origen).first()
        case_d = db.query(Case).filter(Case.id == destino).first()
        patterns.append({
            'case_origen_id': origen,
            'case_origen_folder': case_o.folder_name if case_o else '?',
            'case_destino_id': destino,
            'case_destino_folder': case_d.folder_name if case_d else '?',
            'docs_count': len(docs),
            'doc_ids': docs,
        })
    return sorted(patterns, key=lambda x: -x['docs_count'])


# ============================================================
# Main
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='No escribe a DB')
    args = ap.parse_args()

    print("═" * 70)
    print("V9.2 POST-INGEST ANALYSIS — verificacion_score + cruce de referencias")
    print("═" * 70)

    print("\n[1/4] Verificando schema...")
    added = ensure_schema()
    if added:
        print(f"  Columnas agregadas: {added}")
    else:
        print(f"  Schema ya estaba al día")

    db = SessionLocal()
    try:
        n_docs = db.query(Document).count()
        print(f"\n[2/4] Calculando verificacion_score sobre {n_docs} docs...")
        if not args.dry_run:
            updated = 0
            for i, d in enumerate(db.query(Document).all()):
                if i % 500 == 0 and i > 0:
                    print(f"  {i}/{n_docs} procesados")
                score, breakdown = compute_verification_score(db, d)
                d.verificacion_score = round(score, 3)
                d.verificacion_breakdown = json.dumps(breakdown, ensure_ascii=False)
                updated += 1
            db.commit()
            print(f"  ✅ {updated} docs con score calculado")
        else:
            print(f"  (dry-run — no se escribió)")

        # Histograma de scores
        print(f"\n  Histograma de verificacion_score:")
        bins = [0.0, 0.3, 0.5, 0.7, 0.9, 1.01]
        labels = ["0.0-0.3 muy bajo", "0.3-0.5 bajo", "0.5-0.7 medio", "0.7-0.9 alto", "0.9-1.0 excelente"]
        for i in range(len(bins) - 1):
            n = db.query(Document).filter(
                Document.verificacion_score >= bins[i],
                Document.verificacion_score < bins[i+1],
            ).count()
            pct = 100 * n / max(n_docs, 1)
            print(f"    {labels[i]:<25}  {n:>5}  ({pct:.1f}%)")

        print(f"\n[3/4] Cruce de referencias para SOSPECHOSOS...")
        matched, no_target = find_destination_for_foreigns(db, dry_run=args.dry_run)
        print(f"  Sugerencias creadas: {matched}")
        print(f"  Sin destino (rad21 no existe en DB): {no_target}")

        print(f"\n[4/4] Detectando patrones colectivos (>=2 docs mismo cruce)...")
        patterns = detect_collective_misroutes(db)
        if not patterns:
            print(f"  Ninguno detectado")
        else:
            print(f"  {len(patterns)} patrones detectados:")
            for p in patterns[:10]:
                print(f"    {p['docs_count']}× docs en case#{p['case_origen_id']} ({p['case_origen_folder'][:35]})")
                print(f"        → sugerido case#{p['case_destino_id']} ({p['case_destino_folder'][:35]})")

        print(f"\n═" * 35)
        print(f"COMPLETADO")
        print(f"═" * 35)
    finally:
        db.close()


if __name__ == '__main__':
    main()
