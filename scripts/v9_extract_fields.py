#!/usr/bin/env python3
"""Fase 2 — Extracción de campos del cuadro Excel sobre los cases ingestados.

Aplica los extractores de `backend/v9/field_extractor.py` a cada Case y
escribe los valores a la DB (con --apply) o solo reporta (--dry-run).

Campos implementados hasta ahora:
  - radicado_forest, forest_impugnacion  (extract_forest_for_case)

Uso:
    python3 scripts/v9_extract_fields.py --field forest --dry-run
    python3 scripts/v9_extract_fields.py --field forest --apply
    python3 scripts/v9_extract_fields.py --field all --apply
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case  # noqa: E402
from backend.v9.field_extractor import (  # noqa: E402
    extract_forest_for_case, extract_accionante_for_case,
    extract_accionados_for_case, extract_vinculados_for_case,
    extract_derecho_vulnerado_for_case,
    extract_juzgado_for_case, extract_juzgado_2nd_for_case,
    extract_ciudad_for_case, extract_fecha_ingreso_for_case,
    extract_asunto_for_case, extract_pretensiones_for_case,
    extract_abogado_responsable_for_case, extract_oficina_responsable_for_case,
    extract_sentido_fallo_1ra_for_case, extract_fecha_fallo_1ra_for_case,
    extract_impugnacion_cluster_for_case, extract_incidentes_cluster_for_case,
    extract_estado_for_case, extract_fecha_respuesta_for_case,
    extract_categoria_tematica_for_case, extract_observaciones_for_case,
)


def run_forest(db, apply: bool):
    """Extrae radicado_forest + forest_impugnacion para todos los cases."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para FOREST...")

    stats = Counter()
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total} ({i*100//total}%)")
        rad_forest, forest_imp = extract_forest_for_case(db, c)
        if rad_forest:
            stats["con_radicado_forest"] += 1
            if apply and c.radicado_forest != rad_forest:
                c.radicado_forest = rad_forest
        else:
            stats["sin_radicado_forest"] += 1
        if forest_imp:
            stats["con_forest_impugnacion"] += 1
            if apply and c.forest_impugnacion != forest_imp:
                c.forest_impugnacion = forest_imp
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0

    print(f"\n{'─'*60}")
    print(f"FOREST — resultados ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Cases con radicado_forest:     {stats['con_radicado_forest']:>4} / {total} ({stats['con_radicado_forest']*100//total}%)")
    print(f"  Cases SIN radicado_forest:     {stats['sin_radicado_forest']:>4} / {total} ({stats['sin_radicado_forest']*100//total}%)")
    print(f"  Cases con forest_impugnacion:  {stats['con_forest_impugnacion']:>4} / {total}")
    print(f"  Modo: {'APPLY (escrito a DB)' if apply else 'DRY-RUN'}")

    # Muestras de los que SÍ tienen
    print(f"\n  Muestras (radicado_forest):")
    n = 0
    for c in cases:
        rf, fi = extract_forest_for_case(db, c)
        if rf:
            extra = f" + impug:{fi}" if fi else ""
            print(f"    case#{c.id} {c.folder_name[:40]:<40} forest={rf}{extra}")
            n += 1
            if n >= 8:
                break

    # Muestras de los que NO
    print(f"\n  Muestras SIN forest (revisar por qué):")
    n = 0
    for c in cases:
        rf, _ = extract_forest_for_case(db, c)
        if not rf:
            n_docs = len(c.documents)
            print(f"    case#{c.id} {c.folder_name[:40]:<40} ({n_docs} docs)")
            n += 1
            if n >= 5:
                break


def run_accionante(db, apply: bool, only_empty: bool = False):
    """Extrae accionante (+ nota observaciones) para todos los cases.

    only_empty=True: solo escribe en cases cuyo `accionante` esté vacío (no pisa los ya
    extraídos) — modo seguro para rellenar los SIN_ACCIONANTE sin riesgo de regresión.
    """
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para ACCIONANTE{' (solo vacíos)' if only_empty else ''}...")

    stats = Counter()
    samples_pers, samples_agente, samples_natural, samples_sin = [], [], [], []
    written = 0
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total} ({i*100//total}%)")
        was_empty = not (c.accionante or "").strip()
        if only_empty and not was_empty:
            stats["con_accionante"] += 1  # ya lo tenía
            continue
        acc, nota = extract_accionante_for_case(db, c)
        if acc:
            stats["con_accionante"] += 1
            if "PERSONER" in acc:
                stats["personeria"] += 1
                if len(samples_pers) < 5:
                    samples_pers.append((c.id, acc, nota))
            elif nota:
                stats["agente_oficioso"] += 1
                if len(samples_agente) < 5:
                    samples_agente.append((c.id, acc, nota))
            else:
                stats["persona_natural"] += 1
                if len(samples_natural) < 5:
                    samples_natural.append((c.id, acc))
            if apply and c.accionante != acc:
                c.accionante = acc
                written += 1
            if apply and nota:
                obs = (c.observaciones or "").strip()
                if nota not in obs:
                    c.observaciones = (obs + ("\n" if obs else "") + nota).strip()
        else:
            stats["sin_accionante"] += 1
            if len(samples_sin) < 5:
                samples_sin.append((c.id, c.folder_name))
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0

    print(f"\n{'─'*60}")
    print(f"ACCIONANTE — resultados ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Con accionante:        {stats['con_accionante']:>4} / {total} ({stats['con_accionante']*100//total}%)")
    print(f"    · Personería municipal: {stats['personeria']:>4}")
    print(f"    · Agente oficioso:      {stats['agente_oficioso']:>4}")
    print(f"    · Persona natural:      {stats['persona_natural']:>4}")
    print(f"  SIN accionante:        {stats['sin_accionante']:>4} / {total}")
    print(f"  Escritos a DB:         {written}{' (solo en vacíos)' if only_empty else ''}")
    print(f"  Modo: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"\n  Muestras Personería:")
    for cid, acc, nota in samples_pers:
        print(f"    case#{cid}: {acc}" + (f"  | nota: {nota}" if nota else ""))
    print(f"\n  Muestras Agente oficioso:")
    for cid, acc, nota in samples_agente:
        print(f"    case#{cid}: {acc}  | nota: {nota}")
    print(f"\n  Muestras Persona natural:")
    for cid, acc in samples_natural:
        print(f"    case#{cid}: {acc}")
    print(f"\n  Muestras SIN accionante:")
    for cid, fn in samples_sin:
        print(f"    case#{cid}: {fn}")


def run_accionados(db, apply: bool):
    """Extrae accionados + vinculados para todos los cases."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para ACCIONADOS + VINCULADOS...")
    stats = Counter()
    samp_acc, samp_vinc = [], []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        acc = extract_accionados_for_case(db, c)
        vinc = extract_vinculados_for_case(db, c)
        if acc:
            stats["con_accionados"] += 1
            if len(samp_acc) < 6: samp_acc.append((c.id, acc))
            if apply and c.accionados != acc:
                c.accionados = acc
        else:
            stats["sin_accionados"] += 1
        if vinc:
            stats["con_vinculados"] += 1
            if len(samp_vinc) < 6: samp_vinc.append((c.id, vinc[:70]))
            if apply and c.vinculados != vinc:
                c.vinculados = vinc
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"ACCIONADOS + VINCULADOS ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Con accionados:  {stats['con_accionados']:>4} / {total} ({stats['con_accionados']*100//total}%)")
    print(f"  Con vinculados:  {stats['con_vinculados']:>4} / {total} ({stats['con_vinculados']*100//total}%)")
    print(f"  Modo: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"\n  Muestras ACCIONADOS:")
    for cid, a in samp_acc: print(f"    case#{cid}: {a}")
    print(f"\n  Muestras VINCULADOS:")
    for cid, v in samp_vinc: print(f"    case#{cid}: {v}")


def run_derecho(db, apply: bool, use_llm: bool = True):
    """Extrae derecho_vulnerado para todos los cases (regex de tags + LLM fallback)."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para DERECHO_VULNERADO (LLM fallback: {'ON' if use_llm else 'OFF'})...")

    stats = Counter()
    tag_counter = Counter()
    samples_regex, samples_llm, samples_default = [], [], []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total} ({i*100//total}%)")
        val, src = extract_derecho_vulnerado_for_case(db, c, use_llm=use_llm)
        stats[f"src_{src}"] += 1
        for tag in (val or "").split(" - "):
            if tag:
                tag_counter[tag] += 1
        if src == "regex" and len(samples_regex) < 8:
            samples_regex.append((c.id, val))
        elif src == "llm" and len(samples_llm) < 8:
            samples_llm.append((c.id, val))
        elif src == "default" and len(samples_default) < 8:
            samples_default.append((c.id, c.folder_name))
        if apply and c.derecho_vulnerado != val:
            c.derecho_vulnerado = val
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0

    print(f"\n{'─'*60}")
    print(f"DERECHO_VULNERADO — resultados ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Por regex:           {stats['src_regex']:>4} / {total} ({stats['src_regex']*100//total}%)")
    print(f"  Por LLM (fallback):  {stats['src_llm']:>4} / {total}")
    print(f"  SIN_DETERMINAR:      {stats['src_default']:>4} / {total}")
    print(f"  Modo: {'APPLY (escrito a DB)' if apply else 'DRY-RUN'}")
    print(f"\n  Distribución de tags:")
    for tag, n in tag_counter.most_common():
        print(f"    {tag:<18} {n:>4}")
    print(f"\n  Muestras (regex):")
    for cid, v in samples_regex:
        print(f"    case#{cid}: {v}")
    print(f"\n  Muestras (LLM):")
    for cid, v in samples_llm:
        print(f"    case#{cid}: {v}")
    print(f"\n  Muestras SIN_DETERMINAR (revisar):")
    for cid, fn in samples_default:
        print(f"    case#{cid}: {fn}")


def run_juzgado(db, apply: bool):
    """Extrae juzgado (1ra) + juzgado_2nd (2da, derivado si no se extrae) para todos los cases."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para JUZGADO (1ra + 2da)...")

    stats = Counter()
    samp_1, samp_2reg, samp_2der, samp_sin = [], [], [], []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        j1 = extract_juzgado_for_case(db, c)
        j2, src2 = extract_juzgado_2nd_for_case(db, c, j1)
        if j1:
            stats["con_juzgado"] += 1
            if len(samp_1) < 12:
                samp_1.append((c.id, j1))
            if apply and c.juzgado != j1:
                c.juzgado = j1
        else:
            stats["sin_juzgado"] += 1
            if len(samp_sin) < 8:
                samp_sin.append((c.id, c.folder_name))
        if j2:
            stats[f"juzgado_2nd_{src2}"] += 1
            if src2 == "regex" and len(samp_2reg) < 8:
                samp_2reg.append((c.id, j2))
            elif src2 == "derivado" and len(samp_2der) < 8:
                samp_2der.append((c.id, j2))
            if apply and c.juzgado_2nd != j2:
                c.juzgado_2nd = j2
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0

    print(f"\n{'─'*60}")
    print(f"JUZGADO — resultados ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Con juzgado 1ra:        {stats['con_juzgado']:>4} / {total} ({stats['con_juzgado']*100//total}%)")
    print(f"  SIN juzgado 1ra:        {stats['sin_juzgado']:>4} / {total}")
    print(f"  juzgado_2nd extraído:   {stats['juzgado_2nd_regex']:>4}")
    print(f"  juzgado_2nd derivado:   {stats['juzgado_2nd_derivado']:>4}  (mapa judicial canónico)")
    print(f"  Modo: {'APPLY (escrito a DB)' if apply else 'DRY-RUN'}")
    print(f"\n  Muestras juzgado 1ra:")
    for cid, j in samp_1:
        print(f"    case#{cid}: {j}")
    print(f"\n  Muestras juzgado_2nd (extraído):")
    for cid, j in samp_2reg:
        print(f"    case#{cid}: {j}")
    print(f"\n  Muestras juzgado_2nd (derivado del mapa):")
    for cid, j in samp_2der:
        print(f"    case#{cid}: {j}")
    print(f"\n  Muestras SIN juzgado 1ra (revisar):")
    for cid, fn in samp_sin:
        print(f"    case#{cid}: {fn}")


def run_ciudad(db, apply: bool):
    """Extrae ciudad (= municipio del juzgado de 1ra instancia ≈ lugar de los hechos)."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para CIUDAD...")
    stats = Counter()
    samp, samp_sin = [], []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        ciudad, src = extract_ciudad_for_case(db, c)
        if ciudad:
            stats[f"src_{src}"] += 1
            stats["con_ciudad"] += 1
            if len(samp) < 14:
                samp.append((c.id, ciudad, src, (c.juzgado or "")[:40]))
            if apply and c.ciudad != ciudad:
                c.ciudad = ciudad
        else:
            stats["sin_ciudad"] += 1
            if len(samp_sin) < 8:
                samp_sin.append((c.id, c.folder_name))
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"CIUDAD — resultados ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Con ciudad:    {stats['con_ciudad']:>4} / {total} ({stats['con_ciudad']*100//total}%)")
    print(f"    · del nombre del juzgado:  {stats['src_juzgado']:>4}")
    print(f"    · del auto admisorio:      {stats['src_auto']:>4}")
    print(f"    · del 'Señor Juez' demanda: {stats['src_demanda']:>4}")
    print(f"  SIN ciudad:    {stats['sin_ciudad']:>4} / {total}")
    print(f"  Modo: {'APPLY (escrito a DB)' if apply else 'DRY-RUN'}")
    print(f"\n  Muestras:")
    for cid, ci, src, jz in samp:
        print(f"    case#{cid}: ciudad={ci:<20} ({src})  | juz={jz}")
    print(f"\n  Muestras SIN ciudad (revisar):")
    for cid, fn in samp_sin:
        print(f"    case#{cid}: {fn}")


def run_fecha_ingreso(db, apply: bool):
    """Extrae fecha_ingreso (= fecha del auto admisorio)."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para FECHA_INGRESO...")
    stats = Counter()
    samp, samp_sin = [], []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        fecha, src = extract_fecha_ingreso_for_case(db, c)
        if fecha:
            stats[f"src_{src}"] += 1
            stats["con_fecha"] += 1
            if len(samp) < 14:
                samp.append((c.id, fecha, src))
            if apply and c.fecha_ingreso != fecha:
                c.fecha_ingreso = fecha
        else:
            stats["sin_fecha"] += 1
            if len(samp_sin) < 8:
                samp_sin.append((c.id, c.folder_name))
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"FECHA_INGRESO — resultados ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Con fecha:     {stats['con_fecha']:>4} / {total} ({stats['con_fecha']*100//total}%)")
    print(f"    · del auto admisorio:       {stats['src_auto']:>4}")
    print(f"    · del 1er email del juzgado: {stats['src_email']:>4}  (≈ fecha del auto)")
    print(f"  SIN fecha:     {stats['sin_fecha']:>4} / {total}")
    print(f"  Modo: {'APPLY (escrito a DB)' if apply else 'DRY-RUN'}")
    print(f"\n  Muestras:")
    for cid, f, src in samp:
        print(f"    case#{cid}: {f}  ({src})")
    print(f"\n  Muestras SIN fecha (revisar):")
    for cid, fn in samp_sin:
        print(f"    case#{cid}: {fn}")


def run_asunto(db, apply: bool, use_llm: bool = True):
    """Extrae asunto (vocabulario controlado SED)."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para ASUNTO (LLM fallback: {'ON' if use_llm else 'OFF'})...")
    stats = Counter(); tagc = Counter(); samp = []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        v, src = extract_asunto_for_case(db, c, use_llm=use_llm)
        stats[f"src_{src}"] += 1
        if v: tagc[v] += 1
        if len(samp) < 12: samp.append((c.id, v, src))
        if apply and c.asunto != v:
            c.asunto = v
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"ASUNTO — resultados ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Por regex (keyword SED): {stats['src_regex']:>4} / {total}")
    print(f"  Por LLM (fallback):      {stats['src_llm']:>4}")
    print(f"  SIN_DETERMINAR:          {stats['src_default']:>4}")
    print(f"  Modo: {'APPLY (escrito a DB)' if apply else 'DRY-RUN'}")
    print(f"\n  Distribución de tags:")
    for tag, n in tagc.most_common():
        print(f"    {tag:<24} {n}")
    print(f"\n  Muestras:")
    for cid, v, src in samp:
        print(f"    case#{cid}: {v}  ({src})")


def run_pretensiones(db, apply: bool, use_llm: bool = True):
    """Extrae pretensiones (transcripción literal de la demanda)."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para PRETENSIONES (LLM fallback: {'ON' if use_llm else 'OFF'})...")
    stats = Counter(); samp_r, samp_l, samp_sin = [], [], []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        v, src = extract_pretensiones_for_case(db, c, use_llm=use_llm)
        stats[f"src_{src}"] += 1
        if v:
            stats["con_pret"] += 1
            if src == "regex" and len(samp_r) < 6: samp_r.append((c.id, v))
            elif src == "llm" and len(samp_l) < 6: samp_l.append((c.id, v))
            if apply and c.pretensiones != v:
                c.pretensiones = v
        else:
            if len(samp_sin) < 6: samp_sin.append((c.id, c.folder_name))
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"PRETENSIONES — resultados ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Con pretensiones:  {stats['con_pret']:>4} / {total} ({stats['con_pret']*100//total}%)")
    print(f"    · regex (sección de la demanda): {stats['src_regex']:>4}")
    print(f"    · LLM (transcrito):              {stats['src_llm']:>4}")
    print(f"  SIN pretensiones:  {stats['src_none']:>4} / {total}")
    print(f"  Modo: {'APPLY (escrito a DB)' if apply else 'DRY-RUN'}")
    print(f"\n  Muestras (regex):")
    for cid, v in samp_r:
        print(f"    case#{cid}: {v[:140]}")
    print(f"\n  Muestras (LLM):")
    for cid, v in samp_l:
        print(f"    case#{cid}: {v[:140]}")
    print(f"\n  Muestras SIN pretensiones:")
    for cid, fn in samp_sin:
        print(f"    case#{cid}: {fn}")


def run_asignacion(db, apply: bool):
    """Extrae oficina_responsable (derivada del asunto) + abogado_responsable (footer 'Proyectó:' → roster)."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para OFICINA + ABOGADO_RESPONSABLE...")
    stats = Counter(); ofic_c = Counter(); abog_c = Counter(); samp = []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        ofic, ofic_src = extract_oficina_responsable_for_case(db, c)
        abog, abog_src = extract_abogado_responsable_for_case(db, c)
        if ofic:
            stats[f"ofic_{ofic_src}"] += 1; ofic_c[ofic] += 1
            if apply and c.oficina_responsable != ofic:
                c.oficina_responsable = ofic
        else:
            stats["ofic_none"] += 1
        if abog:
            stats[f"abog_{abog_src}"] += 1; abog_c[abog] += 1
            if apply and c.abogado_responsable != abog:
                c.abogado_responsable = abog
        else:
            stats["abog_none"] += 1
        if len(samp) < 14:
            samp.append((c.id, ofic, abog, abog_src))
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"OFICINA + ABOGADO — resultados ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Con oficina_responsable: {sum(v for k,v in stats.items() if k.startswith('ofic_') and k!='ofic_none')} / {total}  (email de asignación: {stats['ofic_email_asignacion']}, derivado del asunto: {stats['ofic_asunto']})")
    print(f"  Con abogado_responsable: {sum(v for k,v in stats.items() if k.startswith('abog_') and k!='abog_none')} / {total}")
    print(f"    · por correo (roster):  {stats['abog_roster_correo']}")
    print(f"    · por nombre (roster):  {stats['abog_roster_nombre'] + stats['abog_roster_fuzzy']}")
    print(f"    · catálogo abogados:    {stats['abog_catalogo']}")
    print(f"    · nombre crudo (footer):{stats['abog_footer']}")
    print(f"  SIN abogado: {stats['abog_none']}")
    print(f"  Modo: {'APPLY (escrito a DB)' if apply else 'DRY-RUN'}")
    print(f"\n  Distribución oficina_responsable:")
    for o, n in ofic_c.most_common():
        print(f"    {o:<30} {n}")
    print(f"\n  Top abogado_responsable:")
    for a, n in abog_c.most_common(12):
        print(f"    {a:<40} {n}")
    print(f"\n  Muestras:")
    for cid, o, a, asrc in samp:
        print(f"    case#{cid}: oficina={o}  | abogado={a} ({asrc})")


def run_fallo_1ra(db, apply: bool):
    """Extrae sentido_fallo_1st + fecha_fallo_1st de la SENTENCIA_1RA."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para SENTIDO + FECHA FALLO 1ra...")
    stats = Counter(); tagc = Counter(); samp = []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        sent, sent_src = extract_sentido_fallo_1ra_for_case(db, c)
        fec, fec_src = extract_fecha_fallo_1ra_for_case(db, c)
        if sent:
            tagc[sent] += 1; stats["con_sentido"] += 1
            if apply and c.sentido_fallo_1st != sent:
                c.sentido_fallo_1st = sent
        else:
            stats["sin_sentido"] += 1
        if fec:
            stats["con_fecha"] += 1
            if apply and c.fecha_fallo_1st != fec:
                c.fecha_fallo_1st = fec
        else:
            stats["sin_fecha"] += 1
        if len(samp) < 14:
            samp.append((c.id, sent, fec))
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"SENTIDO + FECHA FALLO 1ra — ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  Con sentido_fallo_1st: {stats['con_sentido']}/{total} ({stats['con_sentido']*100//total}%)")
    print(f"  Con fecha_fallo_1st:   {stats['con_fecha']}/{total} ({stats['con_fecha']*100//total}%)")
    print(f"  SIN sentido: {stats['sin_sentido']} | SIN fecha: {stats['sin_fecha']}")
    print(f"  Modo: {'APPLY (escrito a DB)' if apply else 'DRY-RUN'}")
    print(f"\n  Distribución sentido_fallo_1st:")
    for tag, n in tagc.most_common():
        print(f"    {tag:<24} {n}")
    print(f"\n  Muestras:")
    for cid, s, f in samp:
        print(f"    case#{cid}: sentido={s} fecha={f}")


def run_impugnacion(db, apply: bool):
    """Extrae el cluster de impugnación: impugnacion SI/NO + quien_impugno + sentido_fallo_2nd + fecha_fallo_2nd."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para CLUSTER IMPUGNACIÓN...")
    stats = Counter(); quien_c = Counter(); sent2_c = Counter(); samp = []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        flag, quien, sent2, fec2, src = extract_impugnacion_cluster_for_case(db, c)
        stats[f"flag_{flag or 'none'}"] += 1
        if quien: quien_c[quien] += 1
        if sent2: sent2_c[sent2] += 1
        if fec2: stats["con_fecha_2nd"] += 1
        if len(samp) < 14 and flag == "SI":
            samp.append((c.id, quien, sent2, fec2))
        if apply:
            if c.impugnacion != flag: c.impugnacion = flag
            if quien and c.quien_impugno != quien: c.quien_impugno = quien
            if sent2 and c.sentido_fallo_2nd != sent2: c.sentido_fallo_2nd = sent2
            if fec2 and c.fecha_fallo_2nd != fec2: c.fecha_fallo_2nd = fec2
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    n_si = stats["flag_SI"]; n_no = stats["flag_NO"]
    print(f"\n{'─'*60}")
    print(f"CLUSTER IMPUGNACIÓN — ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  impugnacion=SI: {n_si} | impugnacion=NO: {n_no}")
    print(f"  con quien_impugno:   {sum(quien_c.values())}/{n_si}")
    print(f"  con sentido_fallo_2nd: {sum(sent2_c.values())}/{n_si}")
    print(f"  con fecha_fallo_2nd:   {stats['con_fecha_2nd']}/{n_si}")
    print(f"  Modo: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"\n  quien_impugno distribución: {quien_c.most_common()}")
    print(f"  sentido_fallo_2nd distribución: {sent2_c.most_common()}")
    print(f"\n  Muestras (SI):")
    for cid, q, s, f in samp:
        print(f"    case#{cid}: quien={q} sentido_2nd={s} fecha_2nd={f}")


def run_incidentes(db, apply: bool):
    """Extrae el cluster de incidentes de desacato (slots 1/2/3 × flag+fecha+responsable+decision)."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para CLUSTER INCIDENTES DESACATO...")
    stats = Counter(); dec_c = Counter(); n_c = Counter(); samp = []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        r = extract_incidentes_cluster_for_case(db, c)
        n = r.pop("_n_incidentes", 0)
        if r["incidente"] == "SI":
            stats["con_incidente"] += 1; n_c[n] += 1
            if r["decision_incidente"]: dec_c[r["decision_incidente"]] += 1
            if r["fecha_apertura_incidente"]: stats["con_fecha"] += 1
            if r["responsable_desacato"]: stats["con_responsable"] += 1
            if r["incidente_2"] == "SI": stats["con_inc2"] += 1
            if r["incidente_3"] == "SI": stats["con_inc3"] += 1
            if len(samp) < 14:
                samp.append((c.id, r["fecha_apertura_incidente"], r["responsable_desacato"], r["decision_incidente"], r["incidente_2"], r["incidente_3"]))
        if apply:
            for k, v in r.items():
                cur = getattr(c, k, None)
                if v is not None and cur != v:
                    setattr(c, k, v)
                elif k.startswith("incidente") and v == "NO" and cur != "NO":
                    setattr(c, k, "NO")
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"INCIDENTES DESACATO — ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  cases con incidente=SI: {stats['con_incidente']}/{total}  (con 2do: {stats['con_inc2']}, con 3ro: {stats['con_inc3']})")
    print(f"  nº de incidentes por case: {dict(n_c)}")
    print(f"  con fecha_apertura: {stats['con_fecha']}/{stats['con_incidente']} | con responsable_desacato: {stats['con_responsable']}/{stats['con_incidente']}")
    print(f"  decision_incidente: {dec_c.most_common()}")
    print(f"  Modo: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"\n  Muestras (incidente=SI):")
    for cid, f, resp, dec, i2, i3 in samp:
        extra = f" +2:{i2}" + (f" +3:{i3}" if i3 == "SI" else "") if i2 == "SI" else ""
        print(f"    case#{cid}: fecha={f} resp={resp} decision={dec}{extra}")


def run_estado(db, apply: bool):
    """Extrae estado (ACTIVO/INACTIVO, derivado) + fecha_respuesta (dateline del DOCX de respuesta)."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para ESTADO + FECHA_RESPUESTA...")
    stats = Counter(); samp = []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        est = extract_estado_for_case(db, c)
        fr, fr_src = extract_fecha_respuesta_for_case(db, c)
        stats[f"estado_{est}"] += 1
        if fr:
            stats[f"fr_{fr_src}"] += 1; stats["con_fr"] += 1
        else:
            stats["sin_fr"] += 1
        if len(samp) < 14:
            samp.append((c.id, est, fr, fr_src, c.sentido_fallo_1st, c.impugnacion, c.incidente))
        if apply:
            if c.estado != est: c.estado = est
            if fr and c.fecha_respuesta != fr: c.fecha_respuesta = fr
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"ESTADO + FECHA_RESPUESTA — ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  estado: ACTIVO {stats['estado_ACTIVO']} / INACTIVO {stats['estado_INACTIVO']}")
    print(f"  fecha_respuesta: {stats['con_fr']}/{total}  (del DOCX: {stats['fr_docx_respuesta']}, del email: {stats['fr_email']})  | SIN: {stats['sin_fr']}")
    print(f"  Modo: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"\n  Muestras:")
    for cid, e, fr, src, s1, im, inc in samp:
        print(f"    case#{cid}: estado={e} fecha_resp={fr} ({src}) [fallo1={s1} impug={im} inc={inc}]")


def run_categoria(db, apply: bool):
    """Extrae categoria_tematica (derivada del asunto) + siembra banderas en observaciones."""
    cases = db.query(Case).filter(Case.folder_name != "__SIN_RADICADO__").all()
    total = len(cases)
    print(f"Procesando {total} cases para CATEGORIA_TEMATICA + OBSERVACIONES...")
    stats = Counter(); catc = Counter(); obsc = Counter(); samp = []
    t0 = time.perf_counter()
    for i, c in enumerate(cases):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total}")
        cat, cat_src = extract_categoria_tematica_for_case(db, c)
        flags = extract_observaciones_for_case(db, c)
        stats[f"cat_{cat_src}"] += 1; catc[cat] += 1
        for f in flags:
            obsc[f.split(":")[0]] += 1
        added = []
        if apply:
            if c.categoria_tematica != cat:
                c.categoria_tematica = cat
            obs = (c.observaciones or "").strip()
            for f in flags:
                if f.lower() not in obs.lower():
                    obs = (obs + ("\n" if obs else "") + f).strip()
                    added.append(f)
            if added:
                c.observaciones = obs
        if len(samp) < 16:
            samp.append((c.id, c.asunto, cat, flags))
    if apply:
        db.commit()
    elapsed = time.perf_counter() - t0
    print(f"\n{'─'*60}")
    print(f"CATEGORIA_TEMATICA + OBSERVACIONES — ({elapsed:.1f}s, {elapsed*1000/total:.0f}ms/case):")
    print(f"  categoria_tematica derivada del asunto: {stats['cat_asunto']}/{total}  | SIN_DETERMINAR: {stats['cat_default']}")
    print(f"  observaciones — banderas detectadas:")
    for k, n in obsc.most_common():
        print(f"    {k:<40} {n}")
    print(f"  Modo: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"\n  Distribución categoria_tematica:")
    for k, n in catc.most_common():
        print(f"    {k:<28} {n}")
    print(f"\n  Muestras:")
    for cid, a, cat, flags in samp:
        fx = (" | obs: " + " ; ".join(flags)) if flags else ""
        print(f"    case#{cid}: asunto={a or '∅':<22} → categoria={cat}{fx}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--field", default="forest", choices=["forest", "accionante", "accionados", "derecho", "juzgado", "ciudad", "fecha", "asunto", "pretensiones", "asignacion", "fallo", "impugnacion", "incidentes", "estado", "categoria", "all"])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="desactiva el fallback LLM (solo regex) para derecho/asunto/pretensiones")
    ap.add_argument("--only-empty", action="store_true", help="(solo --field accionante) escribe únicamente en cases con el campo vacío — no pisa los ya extraídos")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.field in ("forest", "all"):
            run_forest(db, apply=args.apply)
        if args.field in ("accionante", "all"):
            run_accionante(db, apply=args.apply, only_empty=args.only_empty)
        if args.field in ("accionados", "all"):
            run_accionados(db, apply=args.apply)
        if args.field in ("derecho", "all"):
            run_derecho(db, apply=args.apply, use_llm=not args.no_llm)
        if args.field in ("juzgado", "all"):
            run_juzgado(db, apply=args.apply)
        if args.field in ("ciudad", "all"):
            run_ciudad(db, apply=args.apply)
        if args.field in ("fecha", "all"):
            run_fecha_ingreso(db, apply=args.apply)
        if args.field in ("asunto", "all"):
            run_asunto(db, apply=args.apply, use_llm=not args.no_llm)
        if args.field in ("pretensiones", "all"):
            run_pretensiones(db, apply=args.apply, use_llm=not args.no_llm)
        if args.field in ("asignacion", "all"):
            run_asignacion(db, apply=args.apply)
        if args.field in ("fallo", "all"):
            run_fallo_1ra(db, apply=args.apply)
        if args.field in ("impugnacion", "all"):
            run_impugnacion(db, apply=args.apply)
        if args.field in ("incidentes", "all"):
            run_incidentes(db, apply=args.apply)
        if args.field in ("estado", "all"):
            run_estado(db, apply=args.apply)
        if args.field in ("categoria", "all"):
            run_categoria(db, apply=args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
