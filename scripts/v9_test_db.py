#!/usr/bin/env python3
"""Tests de regresión sobre la DB de producción (Fase 2 — el cuadro ya aplicado).

A diferencia de `v9_test_standalone.py` (que no toca la DB), este script lee la
DB real y verifica:
  A. COBERTURA — nº de celdas no-vacías por columna ≥ baseline documentado (2026-05-12).
  B. COTAS — invariantes cronológicas / de rango (0 violaciones permitidas):
       fecha_fallo_1st ≥ fecha_ingreso, fecha_fallo_2nd ≥ fecha_fallo_1st,
       fecha_apertura_incidente ≥ fecha_fallo_1st, fecha_respuesta ≥ fecha_ingreso,
       año(fecha_ingreso) y año(fecha_fallo_1st) ∈ año(rad23) ± 1.
  C. CONSISTENCIA — categoria_tematica == derivada(asunto); estado == derivación
       determinista; oficina_responsable ∈ L1 SED; vocabularios controlados.
  D. NO-CLOBBER — re-extraer (dry-run) un caso lleno NO cambiaría ningún campo ya
       poblado (persist solo rellena huecos).

Es read-only salvo D, que también lo es (dry_run=True). Sale 1 si algún check FALLA.

Uso:  ./venv/bin/python3 scripts/v9_test_db.py [--no-clobber-sample N]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case  # noqa: E402
from backend.v9.field_extractor import _rad_year  # noqa: E402  (mismo "año usable del rad23" que usan los extractores)


# ── baseline de cobertura (nº de cases con la celda no-vacía) — al 2026-05-12 ──
# Si re-aplicas un campo y la cobertura cae por debajo de esto, es una regresión.
COVERAGE_BASELINE: dict[str, int] = {
    "radicado_23_digitos": 381,  # 324->388->381: +re-identificados, -9 shells-dup borrados 2026-05-24
    "radicado_forest": 332,
    "accionante": 377,
    "accionados": 376,
    "vinculados": 43,
    "derecho_vulnerado": 397,
    "categoria_tematica": 397,
    "juzgado": 378,
    "ciudad": 364,
    "fecha_ingreso": 285,
    "asunto": 397,
    "pretensiones": 246,
    "oficina_responsable": 375,  # 380->375: dedup Gmail (7 casos) 2026-05-24
    "abogado_responsable": 175,  # 2026-05-18: regla cerrada — solo cuenta si resuelve a uno de los 17 oficiales
    "estado": 397,
    "fecha_respuesta": 204,
    "sentido_fallo_1st": 270,
    "fecha_fallo_1st": 216,
    "impugnacion": 397,
    "quien_impugno": 43,
    "forest_impugnacion": 32,  # 33→32: merge dup c33→c70 (misma tutela, ambos tenían FOREST impugn; el de c33 quedó como nota). 2026-05-21
    "juzgado_2nd": 78,
    "sentido_fallo_2nd": 18,
    "fecha_fallo_2nd": 28,
    "incidente": 397,
    "fecha_apertura_incidente": 63,
    "responsable_desacato": 21,  # 2026-05-18: limpieza basura (10 vaciados); pendiente extractor del auto del juez para 53 cases
    "decision_incidente": 69,  # 71->69: dedup shells 2026-05-24
}


def _parse_date(s) -> date | None:
    """DD/MM/YYYY (también DD-MM-YYYY). None si no parsea."""
    if not s:
        return None
    s = str(s).strip()
    for sep in ("/", "-"):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    dd, mm, yy = (int(p) for p in parts)
                    if yy < 100:
                        yy += 2000
                    return date(yy, mm, dd)
                except (ValueError, TypeError):
                    return None
    return None


class Report:
    def __init__(self) -> None:
        self.failed = 0
        self.passed = 0

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        mark = "✓" if ok else "✗ FAIL"
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        line = f"  {mark}  {label}"
        if detail:
            line += f"  — {detail}"
        print(line)


def _load_cases(db) -> list[Case]:
    return (
        db.query(Case)
        .filter(
            Case.folder_name.isnot(None),
            Case.folder_name != "None",
            Case.folder_name != "",
            Case.folder_name != "__SIN_RADICADO__",
            Case.processing_status != "DUPLICATE_MERGED",
        )
        .order_by(Case.id)
        .all()
    )


def check_coverage(cases: list[Case], r: Report) -> None:
    print("\n[A] COBERTURA — celdas no-vacías por columna ≥ baseline 2026-05-12")
    for attr, baseline in COVERAGE_BASELINE.items():
        n = sum(1 for c in cases if str(getattr(c, attr, "") or "").strip())
        r.check(n >= baseline, f"{attr:<28} {n:>4} (baseline {baseline})",
                "" if n >= baseline else f"cayó {baseline - n} celdas")


def check_cotas(cases: list[Case], r: Report) -> None:
    print("\n[B] COTAS — invariantes cronológicas / de rango (0 violaciones)")
    # Los cases en REVISION están incompletos a propósito (mezcla de docs de varios
    # radicados pendiente de separar a mano) → no se les exigen las cotas cronológicas.
    cases = [c for c in cases if (getattr(c, "processing_status", None) or "").upper() != "REVISION"]

    def date_pair_check(attr_a: str, attr_b: str, label: str) -> None:
        # exige: fecha(attr_a) ≥ fecha(attr_b)  para los cases con ambas
        viol = []
        for c in cases:
            da, db_ = _parse_date(getattr(c, attr_a, None)), _parse_date(getattr(c, attr_b, None))
            if da and db_ and da < db_:
                viol.append(f"#{c.id} {attr_a}={getattr(c, attr_a)} < {attr_b}={getattr(c, attr_b)}")
        r.check(not viol, label, "" if not viol else f"{len(viol)} viol: " + "; ".join(viol[:5]))

    date_pair_check("fecha_fallo_1st", "fecha_ingreso", "fecha_fallo_1st ≥ fecha_ingreso")
    date_pair_check("fecha_fallo_2nd", "fecha_fallo_1st", "fecha_fallo_2nd ≥ fecha_fallo_1st")
    date_pair_check("fecha_apertura_incidente", "fecha_fallo_1st", "fecha_apertura_incidente ≥ fecha_fallo_1st")
    date_pair_check("fecha_respuesta", "fecha_ingreso", "fecha_respuesta ≥ fecha_ingreso")

    def year_in_rad_range(attr: str, label: str) -> None:
        viol = []
        for c in cases:
            d = _parse_date(getattr(c, attr, None))
            ry = _rad_year(c)
            if d and ry is not None and abs(d.year - ry) > 1:
                viol.append(f"#{c.id} {attr}={getattr(c, attr)} (rad23 año {ry})")
        r.check(not viol, label, "" if not viol else f"{len(viol)} viol: " + "; ".join(viol[:5]))

    year_in_rad_range("fecha_ingreso", "año(fecha_ingreso) ∈ año(rad23) ± 1")
    year_in_rad_range("fecha_fallo_1st", "año(fecha_fallo_1st) ∈ año(rad23) ± 1")


def check_consistency(cases: list[Case], r: Report) -> None:
    print("\n[C] CONSISTENCIA — derivaciones deterministas + vocabularios")
    from backend.cognition.legal_schema import CATEGORIA_TEMATICA_VOCAB, categoria_tematica_de_asunto
    from backend.v9.field_extractor import (
        DERECHO_VOCAB, SENTIDO_FALLO_VOCAB, _ASUNTO_TO_L1, _area_correo_to_l1,
        extract_estado_for_case,
    )
    # Los expedientes en estado REVISION están incompletos a propósito (el usuario los
    # completa a mano: extracción escasa, valores manuales fuera de vocab). No se les
    # exigen las invariantes de vocabulario/derivación — los revisa una persona.
    cases = [c for c in cases if (getattr(c, "processing_status", None) or "").upper() != "REVISION"]

    # C1 — categoria_tematica == derivada del asunto.
    # Solo aplica cuando `asunto` es un CÓDIGO controlado (sin espacios, p.ej. TRASLADO,
    # TRANSPORTE_ESCOLAR). Tras la revisión DeepSeek 2026-05-12 muchos `asunto` pasaron a ser
    # frases descriptivas ("RECONOCIMIENTO DE PENSIÓN DE VEJEZ"); en esos casos `categoria_tematica`
    # es un campo independiente (no derivable del asunto) y no se valida la relación.
    viol = []
    for c in cases:
        a = (c.asunto or "").strip().upper()
        cat = (c.categoria_tematica or "").strip()
        if " " in a:  # asunto descriptivo (no es un código controlado) → no se valida la relación
            continue
        if not a or a in ("SIN_DETERMINAR", "OTRO"):
            if cat and cat != "SIN_DETERMINAR":
                viol.append(f"#{c.id} asunto={a or '∅'} → cat={cat} (esperaba SIN_DETERMINAR/∅)")
            continue
        expected = categoria_tematica_de_asunto(a)
        if expected is None:
            continue  # asunto no mapeable a categoría (frase descriptiva) → no se valida la relación
        if cat != expected:
            viol.append(f"#{c.id} asunto={a} → cat={cat} (esperaba {expected})")
    r.check(not viol, "categoria_tematica == derivar(asunto)",
            "" if not viol else f"{len(viol)} viol: " + "; ".join(viol[:5]))

    # C2 — estado == derivación determinista (re-derivable de los otros campos)
    viol = []
    for c in cases:
        if not (c.estado or "").strip():
            continue
        derived = extract_estado_for_case(None, c)  # solo lee atributos del Case
        if derived != c.estado:
            viol.append(f"#{c.id} estado={c.estado} (deriva → {derived})")
    r.check(not viol, "estado == derivación determinista",
            "" if not viol else f"{len(viol)} viol: " + "; ".join(viol[:5]))

    # C3 — oficina_responsable ∈ catálogo L1 SED
    l1_valid = set(_ASUNTO_TO_L1.values()) | set(_area_correo_to_l1().values())
    bad = [f"#{c.id} oficina={c.oficina_responsable}" for c in cases
           if (c.oficina_responsable or "").strip() and c.oficina_responsable not in l1_valid]
    r.check(not bad, f"oficina_responsable ∈ {{{', '.join(sorted(l1_valid))}}}",
            "" if not bad else f"{len(bad)} fuera de catálogo: " + "; ".join(bad[:5]))

    # C4 — vocabularios controlados
    def vocab_check(attr: str, vocab: set[str], label: str, split_sep: str | None = None) -> None:
        bad = []
        for c in cases:
            v = (getattr(c, attr, "") or "").strip()
            if not v:
                continue
            tags = v.split(split_sep) if split_sep else [v]
            for t in tags:
                t = t.strip()
                if t and t not in vocab:
                    bad.append(f"#{c.id} {attr}={v!r}")
                    break
        r.check(not bad, label, "" if not bad else f"{len(bad)} fuera de vocab: " + "; ".join(bad[:5]))

    vocab_check("estado", {"ACTIVO", "INACTIVO"}, "estado ∈ {ACTIVO, INACTIVO}")
    vocab_check("impugnacion", {"SI", "NO"}, "impugnacion ∈ {SI, NO}")
    for inc in ("incidente", "incidente_2", "incidente_3"):
        vocab_check(inc, {"SI", "NO"}, f"{inc} ∈ {{SI, NO}}")
    vocab_check("sentido_fallo_1st", set(SENTIDO_FALLO_VOCAB), "sentido_fallo_1st ∈ vocab")
    vocab_check("categoria_tematica", set(CATEGORIA_TEMATICA_VOCAB) | {"SIN_DETERMINAR"},
                "categoria_tematica ∈ vocab")
    vocab_check("derecho_vulnerado", set(DERECHO_VOCAB) | {"SIN_DETERMINAR"},
                "derecho_vulnerado tags ∈ vocab", split_sep=" - ")
    vocab_check("tipo_actuacion", {"TUTELA", "INCIDENTE", "IMPUGNACION", "COMUNICACION"}, "tipo_actuacion ∈ vocab")

    # C-bis — radicado_23_digitos: vacío o EXACTAMENTE 23 dígitos puros (sin separadores).
    # Un radicado judicial colombiano tiene 23 dígitos; valores truncados (21/22) o con
    # separadores o malformados (24+) indican un bug de ingesta/edición (ver fix endpoint PUT).
    import re as _re
    bad_rad = [f"#{c.id}={c.radicado_23_digitos!r}" for c in cases
               if (c.radicado_23_digitos or "").strip()
               and not _re.fullmatch(r"\d{23}", c.radicado_23_digitos.strip())]
    r.check(not bad_rad, "radicado_23_digitos vacío o 23 dígitos puros",
            "" if not bad_rad else f"{len(bad_rad)} malformados: " + "; ".join(bad_rad[:5]))


def check_no_clobber(db, cases: list[Case], r: Report, sample_n: int) -> None:
    print(f"\n[D] NO-CLOBBER — re-extraer (dry-run) {sample_n} casos llenos no cambia campos poblados")
    from backend.v9 import persist
    from backend.v9.pipeline import extract_case
    from backend.v9.persist import _CASE_FIELD_MAP

    cuadro_cols = set(_CASE_FIELD_MAP.values())
    # los más "llenos" primero
    def fill_score(c: Case) -> int:
        return sum(1 for col in cuadro_cols if str(getattr(c, col, "") or "").strip())
    chosen = sorted(cases, key=fill_score, reverse=True)[:sample_n]

    for c in chosen:
        try:
            res = extract_case(db, c.id, dry_run=True, use_llm=False)
            out = persist.persist(db, c.id, res.fields, dry_run=True)
            clobbers = [
                f"{k}: {ch.get('old')!r} -> {ch.get('new')!r}"
                for k, ch in out.get("changes", {}).items()
                if not str(k).startswith("__") and ch.get("old")
            ]
            r.check(
                not clobbers,
                f"#{c.id} {(c.folder_name or '')[:42]:<42} ({fill_score(c)} campos, {res.docs_processed} docs)",
                "" if not clobbers else f"{len(clobbers)} pisaría: " + " | ".join(clobbers[:3]),
            )
        except Exception as e:  # noqa: BLE001
            r.check(False, f"#{c.id} extract_case lanzó excepción", str(e))


def main() -> int:
    ap = argparse.ArgumentParser(description="Tests de regresión sobre la DB de producción (v9 Fase 2).")
    ap.add_argument("--no-clobber-sample", type=int, default=5,
                    help="cuántos casos llenos re-extraer en el check D (default 5)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        cases = _load_cases(db)
        print("════════════════════════════════════════════════════════════════")
        print(f"  v9_test_db — {len(cases)} cases en la DB de producción")
        print("════════════════════════════════════════════════════════════════")
        if not cases:
            print("No hay casos en la DB.", file=sys.stderr)
            return 1

        r = Report()
        check_coverage(cases, r)
        check_cotas(cases, r)
        check_consistency(cases, r)
        check_no_clobber(db, cases, r, args.no_clobber_sample)

        print("\n────────────────────────────────────────────────────────────────")
        if r.failed == 0:
            print(f"✅ {r.passed}/{r.passed} checks pasaron.")
            return 0
        print(f"❌ {r.failed} check(s) FALLARON ({r.passed} ok).")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
