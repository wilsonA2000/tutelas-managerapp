#!/usr/bin/env python3
"""Auditoría: detector de `abogado_responsable`, `abogado_canonical`,
`responsable_desacato`, `abogado_incidente` no-canónicos.

Lista los casos cuyos campos de personas-responsables NO están en el catálogo de
los 17 abogados oficiales (`backend/data/abogados_canonicos.json`). Clasifica
cada valor problemático en una de estas clases:

  • INSTITUCIONAL — valor es una entidad (SECRETARÍA, GOBERNACIÓN, MINISTERIO,
    ALCALDÍA, DEPARTAMENTO, INSTITUCIÓN, etc.) — siempre incorrecto.
  • CARGO        — valor es un cargo o título (Secretaria de Educación,
    Director, Coordinador, Juez, etc.) sin que la persona sea canónica.
  • PERSONA_NO_CANONICA — un nombre propio que no aparece entre los 17.

Patrón observado en la revisión por volumen 2026-05-27/28:
  - c92 Gámbita: responsable_desacato = 'GOBERNACIÓN DE SANTANDER' (institucional)
  - c198 Galán: responsable_desacato = 'YANETH KARINA ARAUJO MAESTRE' (cargo
    Secretaria — no canónica; debe ir el proyectó canónico, ANGELICA BARROSO)
  - c72 Santa Bárbara: responsable_desacato = 'JIMMI NOE GÓMEZ SEPÚLVEDA'
    (funcionario externo de Recursos Físicos/Planeación — persona no canónica)
  - c281, c280: dec_incidente=EN_TRAMITE o resp_desac=YANETH con incidente=NO

Salida: tabla en stdout + CSV `data/audit_responsables_<ts>.csv`.

Pure stdlib (sqlite3, json, csv, re). Solo lectura — no escribe en DB.

Uso:
    python3 scripts/audit_responsables_canonicos.py
    python3 scripts/audit_responsables_canonicos.py --csv-only
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "tutelas.db"
CANON_JSON = ROOT / "backend" / "data" / "abogados_canonicos.json"

# Campos a auditar
FIELDS = ("abogado_responsable", "abogado_canonical",
          "responsable_desacato", "abogado_incidente")

# Palabras clave para clasificación
INST_KEYWORDS = (
    "SECRETARIA", "SECRETARÍA", "GOBERNACION", "GOBERNACIÓN",
    "MINISTERIO", "ALCALDIA", "ALCALDÍA", "DEPARTAMENTO",
    "INSTITUCION", "INSTITUCIÓN", "PERSONERIA", "PERSONERÍA",
    "JUZGADO", "TRIBUNAL", "FOMAG", "FIDUPREVISORA",
    "DIRECCION", "DIRECCIÓN", "COORDINACION", "COORDINACIÓN",
    "OFICINA", "GRUPO", "SED ", "DPTAL", "DEPARTAMENTAL",
)
CARGO_KEYWORDS = (
    "JEFE", "DIRECTOR", "DIRECTORA", "COORDINADOR", "COORDINADORA",
    "SECRETARIO", "SECRETARIA DE EDUCACION", "JUEZ", "JUEZA",
    "PROFESIONAL UNIVERSITARIO", "RECTOR", "RECTORA",
    "GERENTE", "SUBDIRECTOR", "SUBDIRECTORA", "PROCURADOR",
)


def _normalize(s: str) -> str:
    """NFD + uppercase + sin tildes para comparación robusta."""
    s = (s or "").upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def load_canonicos() -> tuple[set[str], dict[str, str]]:
    """Devuelve (set de variantes normalizadas, mapa variante→canónico)."""
    data = json.load(open(CANON_JSON, encoding="utf-8"))
    variants: dict[str, str] = {}
    for entry in data:
        canonical = entry["canonical"]
        cn = _normalize(canonical)
        variants[cn] = canonical
        for alias in entry.get("aliases", []):
            variants[_normalize(alias)] = canonical
    return set(variants.keys()), variants


def classify(value: str, canon_variants: set[str]) -> tuple[str, str]:
    """Devuelve (clase, canonical_si_match). Clase ∈ {OK, INSTITUCIONAL, CARGO,
    PERSONA_NO_CANONICA, VACIO}."""
    if not value or not value.strip():
        return ("VACIO", "")
    norm = _normalize(value)
    # 1) Match exacto contra variante canónica
    if norm in canon_variants:
        return ("OK", norm)
    # 2) Match parcial: alguna variante canónica está contenida en norm
    for cv in canon_variants:
        if len(cv) >= 12 and cv in norm:
            return ("OK", cv)
    # 3) Institucional
    if any(k in norm for k in INST_KEYWORDS):
        return ("INSTITUCIONAL", "")
    # 4) Cargo (sin canónico)
    if any(k in norm for k in CARGO_KEYWORDS):
        return ("CARGO", "")
    # 5) Persona no canónica
    return ("PERSONA_NO_CANONICA", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-only", action="store_true",
                    help="Solo escribe CSV, no imprime tabla")
    args = ap.parse_args()

    canon_variants, _canon_map = load_canonicos()
    print(f"Catálogo: {len(canon_variants)} variantes (17 canónicos + aliases)")

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    cases = list(db.execute(
        "SELECT id, accionante, ciudad, processing_status, estado, incidente, "
        + ", ".join(FIELDS) + " FROM cases ORDER BY id"))
    print(f"Casos: {len(cases)}\n")

    findings = []  # (case_id, field, value, clase)
    counts = {f: {"OK": 0, "INSTITUCIONAL": 0, "CARGO": 0,
                  "PERSONA_NO_CANONICA": 0, "VACIO": 0} for f in FIELDS}

    for c in cases:
        for f in FIELDS:
            value = c[f]
            klass, _ = classify(value, canon_variants)
            counts[f][klass] += 1
            if klass not in ("OK", "VACIO"):
                findings.append({"case_id": c["id"], "accionante": c["accionante"],
                                 "ciudad": c["ciudad"], "incidente": c["incidente"],
                                 "field": f, "value": value, "clase": klass})

    # Resumen por campo
    print(f"{'campo':<24} {'OK':>5} {'INST':>5} {'CARGO':>6} {'PERS_NC':>8} {'VACIO':>6}")
    for f in FIELDS:
        c = counts[f]
        print(f"  {f:<22} {c['OK']:>5} {c['INSTITUCIONAL']:>5} {c['CARGO']:>6} "
              f"{c['PERSONA_NO_CANONICA']:>8} {c['VACIO']:>6}")
    print(f"\nTotal findings (a corregir): {len(findings)}")

    # Top de findings por clase
    if not args.csv_only:
        from collections import Counter
        by_class = Counter(f["clase"] for f in findings)
        print(f"\nPor clase: {dict(by_class)}")

        # Muestra hasta 20 por clase
        for klass in ("INSTITUCIONAL", "CARGO", "PERSONA_NO_CANONICA"):
            items = [f for f in findings if f["clase"] == klass]
            if not items: continue
            print(f"\n🔸 {klass} ({len(items)}):")
            for it in items[:15]:
                print(f"   c{it['case_id']:>3} {it['field']:<22} = {(it['value'] or '')[:55]!r}")
            if len(items) > 15:
                print(f"   ... +{len(items)-15} más (ver CSV)")

    # CSV
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = ROOT / "data" / f"audit_responsables_{ts}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "accionante", "ciudad", "incidente",
                    "field", "value", "clase"])
        for it in findings:
            w.writerow([it["case_id"], it["accionante"], it["ciudad"],
                        it["incidente"], it["field"], it["value"], it["clase"]])
    print(f"\n📄 CSV: {out.relative_to(ROOT)} ({len(findings)} filas)")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
