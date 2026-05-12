#!/usr/bin/env python3
"""Validación completa del doc_librarian + RAD_23 sobre el corpus de 971 docs.

Métricas:
    1. Distribución de DocType asignados (cuántos por tipo)
    2. Confianza promedio por tipo
    3. Concordancia con Document.doc_type existente en DB
    4. Tiempo de clasificación por doc
    5. RAD_23: cobertura, fidelidad vs DB, ms por doc
    6. Reportes de integridad de expediente por caso (sample 20 cases)

Salida: tabla por consola + /tmp/v9_validation_report.json
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.v9.doc_io import DocText  # noqa: E402
from backend.v9.doc_librarian import (  # noqa: E402
    classify, audit_expediente, DocType, BelongsVerdict,
)
from backend.v9.regex_pass import _extract_radicado_23  # noqa: E402


def main():
    print("=" * 80)
    print("VALIDACIÓN doc_librarian + RAD_23 sobre 971 docs")
    print("=" * 80)

    data = json.loads(Path('/tmp/v9_corpus_1000.json').read_text())
    print(f"\nTotal docs: {len(data)}")

    # ------------------------------------------------------------
    # 1. CLASIFICACIÓN
    # ------------------------------------------------------------
    print("\n" + "=" * 80)
    print("1. CLASIFICACIÓN")
    print("=" * 80)

    classifications = []
    t0 = time.perf_counter()
    for d in data:
        doc = DocText(
            path=d['file_path'], filename=d['filename'],
            text=d['text'], method='from_corpus', pages=d.get('pages', 1),
        )
        c = classify(doc)
        classifications.append({
            'doc_id': d['doc_id'],
            'case_id': d['case_id'],
            'filename': d['filename'],
            'ext': Path(d['file_path']).suffix.lower(),
            'doc_type_db': d['doc_type_db'],
            'sample_type': d['sample_type'],
            'classified': c.doc_type.value,
            'confidence': c.confidence,
            'method': c.method,
        })
    elapsed_class = time.perf_counter() - t0
    n = len(data)
    print(f"\nTiempo total: {elapsed_class:.2f}s ({elapsed_class*1000/n:.1f} ms/doc)")

    # Distribución resultado
    type_counter = Counter(c['classified'] for c in classifications)
    print(f"\nDistribución de DocType asignados:")
    for t, n_t in type_counter.most_common():
        # Confianza promedio para este tipo
        confs = [c['confidence'] for c in classifications if c['classified'] == t]
        avg = sum(confs) / len(confs) if confs else 0
        print(f"  {t:<28} {n_t:>4}  (conf avg: {avg:.2f})")

    # Por extensión
    print(f"\nPor extensión:")
    for ext in ('.pdf', '.docx', '.doc', '.md'):
        cs = [c for c in classifications if c['ext'] == ext]
        if not cs:
            continue
        unknown = sum(1 for c in cs if c['classified'] == 'DESCONOCIDO')
        avg_conf = sum(c['confidence'] for c in cs) / len(cs)
        print(f"  {ext:6} total={len(cs):>4}  desconocidos={unknown:>3} ({unknown*100//len(cs)}%)  conf avg={avg_conf:.2f}")

    # ------------------------------------------------------------
    # 2. CONCORDANCIA CON Document.doc_type EXISTENTE
    # ------------------------------------------------------------
    print("\n" + "=" * 80)
    print("2. CONCORDANCIA con Document.doc_type existente en DB")
    print("=" * 80)

    # Mapeo entre nuestros tipos y los de la DB
    DB_TO_NEW = {
        'AUTO_ADMISORIO': {DocType.AUTO_ADMISORIO.value, DocType.AUTO_2DA.value},
        'PDF_AUTO_ADMISORIO': {DocType.AUTO_ADMISORIO.value, DocType.AUTO_2DA.value},
        'SENTENCIA': {DocType.SENTENCIA_1RA.value, DocType.SENTENCIA_2DA.value},
        'PDF_SENTENCIA': {DocType.SENTENCIA_1RA.value, DocType.SENTENCIA_2DA.value},
        'IMPUGNACION': {DocType.IMPUGNACION.value, DocType.AUTO_CONCEDE_IMPUGNACION.value},
        'PDF_IMPUGNACION': {DocType.IMPUGNACION.value, DocType.AUTO_CONCEDE_IMPUGNACION.value},
        'INCIDENTE': {DocType.INCIDENTE_DESACATO.value, DocType.AUTO_INCIDENTE.value},
        'PDF_INCIDENTE': {DocType.INCIDENTE_DESACATO.value, DocType.AUTO_INCIDENTE.value},
        'DOCX_RESPUESTA': {DocType.RESPUESTA.value},
        'EMAIL_MD': {DocType.EMAIL_JUDICIAL.value, DocType.EMAIL_INTERNO.value},
        'EMAIL_DB': {DocType.EMAIL_JUDICIAL.value, DocType.EMAIL_INTERNO.value},
        'PDF_GMAIL': {DocType.EMAIL_JUDICIAL.value, DocType.EMAIL_INTERNO.value},
    }

    matched, mismatched, no_db = 0, 0, 0
    mismatch_examples = []
    for c in classifications:
        db_type = c['doc_type_db']
        if not db_type or db_type in ('OTRO', 'DOCX_OTRO', 'PDF_OTRO'):
            no_db += 1
            continue
        expected = DB_TO_NEW.get(db_type)
        if expected and c['classified'] in expected:
            matched += 1
        else:
            mismatched += 1
            if len(mismatch_examples) < 8:
                mismatch_examples.append((c['filename'][:50], db_type, c['classified']))

    comparable = matched + mismatched
    if comparable > 0:
        print(f"\nDocs comparables (DB tiene tipo no-OTRO): {comparable}/{n}")
        print(f"  Coinciden:     {matched:>4} ({matched*100//comparable}%)")
        print(f"  Discrepan:     {mismatched:>4} ({mismatched*100//comparable}%)")
        print(f"  Sin info DB:   {no_db:>4} (DB tiene OTRO o vacío)")
        print(f"\nMuestra de discrepancias:")
        for fn, db, new in mismatch_examples[:8]:
            print(f"  {fn:50} DB={db:<22} NEW={new}")

    # ------------------------------------------------------------
    # 3. RAD_23 sobre el corpus
    # ------------------------------------------------------------
    print("\n" + "=" * 80)
    print("3. RAD_23 — cobertura y fidelidad")
    print("=" * 80)

    rad_results = []
    t0 = time.perf_counter()
    for d in data:
        rad = _extract_radicado_23(d['text'])
        rad_results.append({
            'doc_id': d['doc_id'], 'case_id': d['case_id'],
            'filename': d['filename'], 'ext': Path(d['file_path']).suffix.lower(),
            'sample_type': d['sample_type'], 'gt_rad23': d.get('gt_rad23', ''),
            'rad_extracted': rad or '',
        })
    elapsed_rad = time.perf_counter() - t0
    print(f"\nTiempo total RAD_23: {elapsed_rad:.2f}s ({elapsed_rad*1000/n:.1f} ms/doc)")

    # Cobertura por tipo
    print(f"\nCobertura por sample_type:")
    by_type = defaultdict(list)
    for r in rad_results:
        by_type[r['sample_type']].append(r)
    for t in sorted(by_type):
        rs = by_type[t]
        with_rad = sum(1 for r in rs if r['rad_extracted'])
        print(f"  {t:<18} {with_rad:>3}/{len(rs):<3}  ({with_rad*100//len(rs)}%)")

    # Fidelidad vs gt_rad23 (case.radicado_23_digitos)
    # IMPORTANTE: normalizar AMBOS quitando separadores antes de comparar
    # — la DB tiene rad con guiones, mi extractor sin guiones, son el mismo número.
    import re as _re
    def norm(s):
        return _re.sub(r"\D", "", s or "")[:23]
    def is_valid_rad23(s):
        """¿String tiene exactamente 23 dígitos válidos?"""
        n = norm(s)
        return len(n) == 23 and n.startswith("68")

    docs_with_gt = [r for r in rad_results if r['gt_rad23']]
    matched_rad = sum(1 for r in docs_with_gt if norm(r['rad_extracted']) == norm(r['gt_rad23']))
    new_rads = sum(1 for r in rad_results if r['rad_extracted'] and not r['gt_rad23'])
    contradicting = [r for r in docs_with_gt
                     if r['rad_extracted'] and norm(r['rad_extracted']) != norm(r['gt_rad23'])]

    # Sub-categorías de las discrepancias:
    # A) DB tiene rad MAL FORMADO (no 23d válidos) → DB sucia, extractor probablemente correcto
    # B) DB tiene rad válido pero el extractor sacó otro distinto → posible foreign doc
    db_dirty = [r for r in contradicting if not is_valid_rad23(r['gt_rad23'])]
    db_clean_but_diff = [r for r in contradicting if is_valid_rad23(r['gt_rad23'])]

    print(f"\nFidelidad vs case.radicado_23_digitos (DB existente):")
    print(f"  Docs con GT en DB:                    {len(docs_with_gt):>4}")
    print(f"  ✅ Extraído coincide con DB:           {matched_rad:>4} ({matched_rad*100//max(len(docs_with_gt),1)}%)")
    print(f"  🆕 Extraído nuevo (DB vacía):           {new_rads:>4} (ganancia neta)")
    print(f"  ⚠️  Discrepancias totales:              {len(contradicting):>4}")
    print(f"     ↳ 🧹 DB con rad mal formado:        {len(db_dirty):>4} (oportunidad: corregir DB con NEW)")
    print(f"     ↳ 🚨 DB válida pero NEW distinto:   {len(db_clean_but_diff):>4} (posibles FOREIGN_DOCS)")

    if db_dirty:
        print(f"\n  Muestra DB sucia (extractor probablemente acierta):")
        for r in db_dirty[:3]:
            print(f"    case#{r['case_id']} {r['filename'][:50]}")
            print(f"      DB:  {r['gt_rad23']!r:35} (len={len(norm(r['gt_rad23']))} digits, NO válido)")
            print(f"      NEW: {r['rad_extracted']!r:35} (válido)")
    if db_clean_but_diff:
        print(f"\n  Muestra DB válida pero extractor sacó OTRO:")
        for r in db_clean_but_diff[:3]:
            print(f"    case#{r['case_id']} {r['filename'][:50]}")
            print(f"      DB:  {r['gt_rad23']}")
            print(f"      NEW: {r['rad_extracted']}")

    # ------------------------------------------------------------
    # 4. INTEGRIDAD DE EXPEDIENTE — sobre 20 cases muestreados
    # ------------------------------------------------------------
    print("\n" + "=" * 80)
    print("4. INTEGRIDAD DE EXPEDIENTE — auditoría sobre 20 cases del corpus")
    print("=" * 80)

    # IMPORTANTE: para integridad necesitamos TODOS los docs del case, no solo
    # los del sample. Cargar de la DB para auditoría completa.
    print("\n  Cargando docs completos de DB para auditoría de integridad...")
    from backend.database.database import SessionLocal as _SL
    from backend.database.models import Document as _Doc, Case as _Case
    from backend.v9 import doc_io as _doc_io

    _db = _SL()
    try:
        case_ids_in_corpus = sorted({d['case_id'] for d in data})[:20]
        integrity_reports = []
        for case_id in case_ids_in_corpus:
            case = _db.query(_Case).filter(_Case.id == case_id).first()
            if not case:
                continue
            db_docs = _db.query(_Doc).filter(_Doc.case_id == case_id).all()
            doctexts = []
            for d in db_docs:
                if not d.file_path or not Path(d.file_path).exists():
                    continue
                try:
                    dt = _doc_io.read_one(d.file_path)
                    if dt.ok:
                        doctexts.append(dt)
                except Exception:
                    pass
            if not doctexts:
                continue
            report = audit_expediente(
                case_id=case_id, folder_name=case.folder_name or f"case_{case_id}",
                docs=doctexts, case_rad23=case.radicado_23_digitos,
            )
            integrity_reports.append(report)
    finally:
        _db.close()

    print(f"\n{'Case':<6} {'Docs':>5} {'Score':>6} {'Anomalías':<40}")
    print("-" * 70)
    for r in integrity_reports:
        anom_codes = ", ".join(a.code for a in r.anomalies[:3])
        if len(r.anomalies) > 3:
            anom_codes += f" (+{len(r.anomalies)-3})"
        print(f"{r.case_id:<6} {r.docs_total:>5} {r.integrity_score:>6.2f} {anom_codes[:40]}")

    # Resumen de anomalías agregado
    all_anomalies = Counter()
    for r in integrity_reports:
        for a in r.anomalies:
            all_anomalies[a.code] += 1
    print(f"\nAnomalías más comunes en los 20 cases:")
    for code, n_a in all_anomalies.most_common(10):
        print(f"  {code:<35} {n_a:>3}")

    # ------------------------------------------------------------
    # GUARDAR REPORTE
    # ------------------------------------------------------------
    out = Path('/tmp/v9_validation_report.json')
    out.write_text(json.dumps({
        'classifications': classifications,
        'rad23': rad_results,
        'integrity_reports': [
            {
                'case_id': r.case_id, 'docs_total': r.docs_total,
                'integrity_score': r.integrity_score,
                'type_counts': r.type_counts,
                'anomalies': [{'code': a.code, 'severity': a.severity, 'message': a.message}
                              for a in r.anomalies],
            } for r in integrity_reports
        ],
        'timing': {
            'classify_ms_per_doc': round(elapsed_class * 1000 / n, 1),
            'rad23_ms_per_doc': round(elapsed_rad * 1000 / n, 1),
        },
    }, ensure_ascii=False, indent=2))
    print(f"\nReporte guardado: {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == '__main__':
    main()
