"""Auditoría READ-ONLY: API CPNU (Rama Judicial) vs el cuadro curado (Fase A2).

Para cada caso con rad23 válido consulta CPNU (con cache reanudable + throttle) y
compara campo a campo contra la DB para MEDIR cuánto ayudaría la API antes de
escribir nada. NO toca la base de datos.

Mide:
  - Cobertura: cuántos rad23 existen en CPNU, cuántos esPrivado, cuántos no hallados.
  - Por campo (juzgado/fecha_ingreso/accionante/accionados/impugnacion/incidente):
    #vacíos-que-llenaría · #coinciden · #disienten.
  - CSV de disensos para revisión humana + CSV de cobertura por caso.

Uso:
    python3 scripts/audit_rama_judicial.py [--limit N] [--throttle 0.4] [--no-cache]
Salidas en data/exports/audit_cpnu_*.csv y resumen por stdout.
Cache de respuestas en data/cpnu_cache/<rad23>.json (re-correr no re-pega la API).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.email.rad_utils import normalize_rad23, is_valid_rad23, juzgado_code
from backend.services import rama_judicial_client as rj

CACHE_DIR = ROOT / "data" / "cpnu_cache"
EXPORTS = ROOT / "data" / "exports"


# ── helpers de comparación ────────────────────────────────────────────────────

def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


_NAME_NOISE = re.compile(r"\b(PERSONERIA|MUNICIPAL|DE|DEL|LA|EL|LOS|MUNICIPIO|SENOR[A]?)\b")


def _name_tokens(s: str | None) -> set[str]:
    n = _NAME_NOISE.sub(" ", _norm(s))
    return {t for t in re.split(r"[^A-Z0-9]+", n) if len(t) >= 3}


def _names_match(a: str | None, b: str | None) -> bool:
    """Match tolerante de nombres: substring o solapamiento de tokens ≥ 0.5."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    return inter / min(len(ta), len(tb)) >= 0.5


def _actuaciones_flags(p: rj.ProcesoCPNU) -> dict:
    """Deriva señales SI/NO de la línea de actuaciones (presencia, no sentido)."""
    blob = " ".join(_norm(a.actuacion) + " " + _norm(a.anotacion) for a in p.actuaciones)
    return {
        "fallo": bool(re.search(r"SENTENCIA|FALLO", blob)),
        "impugnacion": bool(re.search(r"IMPUGNAC|APELAC", blob)),
        "incidente": bool(re.search(r"INCIDENTE|DESACATO", blob)),
    }


# ── cache ─────────────────────────────────────────────────────────────────────

def _cached(rad23: str) -> dict | None:
    f = CACHE_DIR / f"{rad23}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cache(rad23: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{rad23}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--throttle", type=float, default=0.4)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    EXPORTS.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    cases = db.query(Case).filter(
        Case.processing_status != "DUPLICATE_MERGED").order_by(Case.id).all()

    # contadores
    stats = {
        "total": 0, "rad_invalido": 0, "consultados": 0, "encontrados": 0,
        "no_encontrados": 0, "es_privado": 0, "error": 0,
    }
    # por campo: {fill, agree, disagree}
    fields = ["juzgado", "fecha_ingreso", "accionante", "accionados",
              "impugnacion", "incidente"]
    fcount = {f: {"fill": 0, "agree": 0, "disagree": 0} for f in fields}
    n_actuaciones_total = 0
    disensos: list[dict] = []
    cobertura_rows: list[dict] = []
    session = rj._new_session()

    for case in cases:
        if args.limit and stats["consultados"] >= args.limit:
            break
        rad = normalize_rad23(case.radicado_23_digitos)
        stats["total"] += 1
        if not is_valid_rad23(rad):
            stats["rad_invalido"] += 1
            cobertura_rows.append({"case_id": case.id, "rad23": rad,
                                   "estado": "RAD_INVALIDO"})
            continue

        data = None if args.no_cache else _cached(rad)
        if data is None:
            p = rj.consultar_proceso(rad, session=session, throttle=args.throttle)
            data = p.to_dict()
            if not args.no_cache:
                _save_cache(rad, data)
            time.sleep(args.throttle)
        stats["consultados"] += 1

        p = rj.ProcesoCPNU(**{k: v for k, v in data.items() if k != "actuaciones"})
        p.actuaciones = [rj.Actuacion(**a) for a in data.get("actuaciones", [])]

        if not p.encontrado:
            stats["no_encontrados"] += 1
            cobertura_rows.append({"case_id": case.id, "rad23": rad,
                                   "estado": "NO_ENCONTRADO", "error": p.error})
            continue
        stats["encontrados"] += 1
        if p.es_privado:
            stats["es_privado"] += 1
        n_actuaciones_total += len(p.actuaciones)
        cobertura_rows.append({
            "case_id": case.id, "rad23": rad, "estado": "ENCONTRADO",
            "es_privado": p.es_privado, "clase": p.clase,
            "n_actuaciones": len(p.actuaciones), "juzgado_api": p.juzgado,
        })

        flags = _actuaciones_flags(p)

        def _cmp(field, db_val, api_val, match_fn):
            db_e = bool((db_val or "").strip()) if isinstance(db_val, str) else bool(db_val)
            api_e = bool(api_val)
            if api_e and not db_e:
                fcount[field]["fill"] += 1
            elif api_e and db_e:
                if match_fn(db_val, api_val):
                    fcount[field]["agree"] += 1
                else:
                    fcount[field]["disagree"] += 1
                    disensos.append({"case_id": case.id, "rad23": rad, "campo": field,
                                     "cuadro": db_val, "api": api_val})

        # juzgado: comparar por código estructural (12 díg) — exacto y robusto al formato
        _cmp("juzgado", juzgado_code(case.radicado_23_digitos),
             p.cod_despacho, lambda a, b: _norm(a) == _norm(b))
        _cmp("fecha_ingreso", case.fecha_ingreso, p.fecha_radicacion,
             lambda a, b: a == b)
        _cmp("accionante", case.accionante, p.demandante, _names_match)
        _cmp("accionados", case.accionados, p.demandado, _names_match)
        # impugnacion / incidente: SI/NO de la DB vs presencia en actuaciones
        _cmp("impugnacion", (case.impugnacion or "").upper() if case.impugnacion else "",
             "SI" if flags["impugnacion"] else "",
             lambda a, b: a == "SI")
        _cmp("incidente", (case.incidente or "").upper() if case.incidente else "",
             "SI" if flags["incidente"] else "",
             lambda a, b: a == "SI")

    # ── salida ────────────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cov_path = EXPORTS / f"audit_cpnu_cobertura_{ts}.csv"
    dis_path = EXPORTS / f"audit_cpnu_disensos_{ts}.csv"
    with cov_path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=["case_id", "rad23", "estado", "error",
                           "es_privado", "clase", "n_actuaciones", "juzgado_api"])
        w.writeheader()
        for r in cobertura_rows:
            w.writerow(r)
    with dis_path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=["case_id", "rad23", "campo", "cuadro", "api"])
        w.writeheader()
        for r in disensos:
            w.writerow(r)

    print("\n" + "=" * 64)
    print("AUDITORÍA CPNU (Rama Judicial) vs cuadro — READ-ONLY")
    print("=" * 64)
    print(f"Casos totales (no merged):      {stats['total']}")
    print(f"  rad23 inválido (no consultable): {stats['rad_invalido']}")
    print(f"  consultados a CPNU:              {stats['consultados']}")
    print(f"    ENCONTRADOS:                   {stats['encontrados']}"
          f"  ({100*stats['encontrados']/max(1,stats['consultados']):.0f}% de los consultados)")
    print(f"    no encontrados:                {stats['no_encontrados']}")
    print(f"    esPrivado (datos limitados):   {stats['es_privado']}")
    print(f"  actuaciones disponibles (total): {n_actuaciones_total}")
    print(f"\n{'campo':16} {'llenaría':>9} {'coincide':>9} {'disiente':>9}")
    print("-" * 48)
    for f in fields:
        c = fcount[f]
        print(f"{f:16} {c['fill']:>9} {c['agree']:>9} {c['disagree']:>9}")
    print(f"\nCSV cobertura: {cov_path}")
    print(f"CSV disensos:  {dis_path}  ({len(disensos)} filas)")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
