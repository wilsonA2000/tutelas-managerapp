#!/usr/bin/env python3
"""Ingesta de Gmail SUPERVISADA — replica el flujo de /api/emails/check con
visibilidad total (cada email, cada match, cada error, actividad de acumulación).

Flujo (idéntico a producción):
  auto_backup → check_inbox (ingesta+match) → extract_case por caso (v9, use_llm=False)

Uso:
    ./venv/bin/python3 scripts/supervised_ingest.py
"""
from __future__ import annotations

import logging
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Capturar WARNING+ de todos los módulos a stderr para verlos en vivo
logging.basicConfig(level=logging.WARNING,
                    format="    [LOG %(levelname)s %(name)s] %(message)s")

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case  # noqa: E402
from backend.email.gmail_monitor import check_inbox  # noqa: E402
from backend.v9.pipeline import extract_case  # noqa: E402


def main() -> int:
    db = SessionLocal()
    n_cases_0 = db.query(Case).count()
    print("=" * 78)
    print(f"  INGESTA SUPERVISADA — casos en DB al inicio: {n_cases_0}")
    print("=" * 78)

    # ── PASO 1+2: check_inbox (descarga + match) ──
    t0 = time.perf_counter()
    print("\n>>> PASO 1/3 — check_inbox (descarga + matching multi-criterio)…")
    try:
        results = check_inbox(db)
    except Exception as e:
        print(f"!!! check_inbox FALLÓ: {e}")
        traceback.print_exc()
        return 1
    dt = time.perf_counter() - t0
    print(f"    check_inbox terminó en {dt:.1f}s — {len(results)} resultados\n")

    errors = [r for r in results if r.get("error")]
    ok = [r for r in results if not r.get("error")]

    # Tabla por email
    print(f"{'#':>3} {'acción':<14} {'score':>5} {'caso asignado':<42} asunto")
    nuevos, ambiguos, asignados = [], [], []
    for i, r in enumerate(ok, 1):
        accion = r.get("accion") or r.get("action") or ("MATCH" if r.get("matched_case") else "?")
        mc = (r.get("matched_case") or "—")[:42]
        score = r.get("match_score") or r.get("score") or ""
        subj = (r.get("subject") or "")[:50]
        print(f"{i:>3} {str(accion):<14} {str(score):>5} {mc:<42} {subj}")
        if accion in ("CASO_NUEVO",):
            nuevos.append(r)
        elif accion in ("AMBIGUO",):
            ambiguos.append(r)
        elif r.get("matched_case"):
            asignados.append(r)

    if errors:
        print(f"\n  !!! {len(errors)} ERROR(es) en descarga/match:")
        for e in errors:
            print(f"      - {e.get('subject','?')[:50]}: {e.get('error')}")

    # ── PASO 3: extracción v9 de cada caso tocado (incluye acumulación) ──
    cases_seen, cases_to_process = set(), []
    for r in ok:
        if not r.get("matched_case"):
            continue
        c = db.query(Case).filter(Case.folder_name == r["matched_case"]).first()
        if c and c.id not in cases_seen:
            cases_seen.add(c.id)
            cases_to_process.append(c)

    print(f"\n>>> PASO 3/3 — extracción v9 de {len(cases_to_process)} casos tocados…")
    extract_errors, acum_events = [], []
    for c in cases_to_process:
        try:
            res = extract_case(db, c.id, dry_run=False, use_llm=False)
            try:
                c.processing_status = "COMPLETO"; db.commit()
            except Exception:
                db.rollback()
            acum = [w for w in res.warnings if w.startswith("acumulacion")]
            if acum:
                acum_events.append((c.id, c.folder_name, acum))
            other_warn = [w for w in res.warnings if not w.startswith("acumulacion")]
            flag = " ⚠" if other_warn else ""
            print(f"    #{c.id:<4} {((c.folder_name or '')[:46]):46} "
                  f"campos={sum(1 for v in res.fields.values.values() if v):2} "
                  f"docs={res.docs_processed}/{res.docs_processed+res.docs_failed}{flag}")
            for w in other_warn:
                print(f"         · warn: {w}")
        except Exception as e:
            extract_errors.append((c.id, str(e)))
            print(f"    #{c.id} EXCEPCIÓN: {e}")
            traceback.print_exc()

    # ── RESUMEN ──
    n_cases_1 = db.query(Case).count()
    print("\n" + "=" * 78)
    print("  RESUMEN")
    print("=" * 78)
    print(f"  Emails procesados:        {len(ok)} (errores: {len(errors)})")
    print(f"  Casos NUEVOS:             {len(nuevos)}")
    print(f"  Emails AMBIGUOS:          {len(ambiguos)}")
    print(f"  Casos extraídos:          {len(cases_to_process)} (errores: {len(extract_errors)})")
    print(f"  Casos en DB:              {n_cases_0} → {n_cases_1}  (Δ {n_cases_1 - n_cases_0})")
    if acum_events:
        print(f"\n  ⚖ ACUMULACIONES detectadas en {len(acum_events)} caso(s):")
        for cid, fn, evs in acum_events:
            print(f"      #{cid} {fn[:40]}:")
            for w in evs:
                print(f"         {w}")
    if nuevos:
        print("\n  Casos nuevos creados:")
        for r in nuevos:
            print(f"      - {r.get('matched_case','?')}")
    if ambiguos:
        print(f"\n  ⚠ Emails ambiguos (revisión manual): {len(ambiguos)}")
        for r in ambiguos:
            print(f"      - {(r.get('subject') or '?')[:55]}")
    if extract_errors:
        print(f"\n  !!! ERRORES de extracción: {len(extract_errors)}")
        for cid, e in extract_errors:
            print(f"      #{cid}: {e}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
