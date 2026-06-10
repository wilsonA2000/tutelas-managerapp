#!/usr/bin/env python3
"""Fase 0 — Scorecard por campo (función pura, reusada por todo el benchmark).

Mide, por campo, contra el gold set:
  - FÁCTICO  (exact-match normalizado): radicados, fechas, juzgado, ciudad, enums.
  - VERBATIM (ROUGE-L recall + substring): pretensiones, parte_resolutiva_*.
  - SEMÁNTICO (solape de palabras ≥0.40): asunto, derecho, observaciones, nombres.
Y las métricas de confiabilidad de primera clase:
  - ALUCINACIÓN  = lleno cuando el oro es null (vacío VERIFICADO).
  - ABSTENCIÓN   = vacío cuando el oro es null (correcto).
  - MISS         = vacío cuando el oro tiene valor.
  - DEGENERACIÓN = reusa backend.v9.llm_gap_fill._is_garbage (lo mismo que prod rechaza).

Convención del oro (golden_v1.json):
  valor no vacío  -> presente (se puntúa el match)
  null            -> vacío VERIFICADO (se puntúa alucinación/abstención)
  ""              -> NO verificado -> se OMITE del score (status desconocido)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.v9.types import EXCEL_FIELDS  # noqa: E402
from backend.v9.llm_gap_fill import _is_garbage  # noqa: E402  (reuso exacto de prod)

# --- Clasificación de campos por tipo de scoring -------------------------------
_ENUM = {
    "tipo_actuacion", "estado", "impugnacion", "quien_impugno",
    "sentido_fallo_1st", "sentido_fallo_2nd", "incidente", "incidente_2",
    "incidente_3", "decision_incidente", "decision_incidente_2", "decision_incidente_3",
}
_EXACT = _ENUM | {
    "radicado_23_digitos", "radicado_forest", "forest_impugnacion",
    "juzgado", "juzgado_2nd", "ciudad",
    "fecha_ingreso", "fecha_respuesta", "fecha_fallo_1st", "fecha_fallo_2nd",
    "fecha_apertura_incidente", "fecha_apertura_incidente_2", "fecha_apertura_incidente_3",
}
_VERBATIM = {
    "pretensiones", "parte_resolutiva_1st", "parte_resolutiva_2nd", "parte_resolutiva_incidente",
}
# El resto (nombres, materia, asunto, observaciones, responsables) -> semántico.
_SEMANTIC = set(EXCEL_FIELDS) - _EXACT - _VERBATIM

_STOP = {"DE", "LA", "EL", "LOS", "LAS", "Y", "O", "A", "EN", "DEL", "POR", "PARA"}


def kind_of(field: str) -> str:
    if field in _EXACT:
        return "exact"
    if field in _VERBATIM:
        return "verbatim"
    return "semantic"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().upper())


def _norm_exact(field: str, s: str) -> str:
    n = _norm(s)
    if field.startswith("radicado") or field == "forest_impugnacion":
        return re.sub(r"\D", "", n)               # solo dígitos
    if field.startswith("fecha"):
        return re.sub(r"[^0-9]", "", n)           # DD MM YYYY -> dígitos
    return n


def _tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"\w+", _norm(s)) if len(w) >= 3 and w not in _STOP]


def _overlap(gold: str, pred: str) -> float:
    g = set(_tokens(gold))
    if not g:
        return 0.0
    return len(g & set(_tokens(pred))) / len(g)


def _lcs(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def _rouge_l_recall(gold: str, pred: str) -> float:
    g = _tokens(gold)
    if not g:
        return 0.0
    return _lcs(g, _tokens(pred)) / len(g)


def score_field(field: str, gold, pred: str) -> dict:
    """gold: str presente | None (vacío verificado) | "" (no verificado→omitir)."""
    pred = "" if pred is None else str(pred).strip()
    degenerate = bool(pred) and _is_garbage(pred)

    if isinstance(gold, str) and not gold.strip():
        return {"field": field, "status": "skipped_unverified", "degenerate": degenerate}

    # vacío VERIFICADO
    if gold is None:
        if not pred:
            return {"field": field, "status": "abstained", "correct": True, "degenerate": degenerate}
        return {"field": field, "status": "hallucinated", "correct": False, "degenerate": degenerate}

    # oro presente
    if not pred:
        return {"field": field, "status": "missed", "correct": False, "degenerate": degenerate}

    k = kind_of(field)
    if k == "exact":
        ok = _norm_exact(field, gold) == _norm_exact(field, pred)
        # enums: tolerar contención bidireccional (p.ej. "CONCEDE PARCIAL" ⊇ "CONCEDE")
        if not ok and field in _ENUM:
            g, p = _norm(gold), _norm(pred)
            ok = g in p or p in g
        score = 1.0 if ok else 0.0
    elif k == "verbatim":
        rec = _rouge_l_recall(gold, pred)
        contained = _norm(gold) in _norm(pred) or _norm(pred) in _norm(gold)
        ok = rec >= 0.8 or contained
        score = max(rec, 1.0 if contained else 0.0)
    else:  # semantic
        score = _overlap(gold, pred)
        ok = score >= 0.40

    return {"field": field, "status": "match" if ok else "mismatch",
            "correct": ok, "kind": k, "score": round(score, 3), "degenerate": degenerate}


def score_case(gold_case: dict, pred_values: dict) -> dict:
    """gold_case: {field: gold}. pred_values: {field: valor extraído}."""
    results = [score_field(f, gold_case.get(f, ""), pred_values.get(f, "")) for f in EXCEL_FIELDS]
    agg = {s: 0 for s in ("match", "mismatch", "missed", "hallucinated", "abstained", "skipped_unverified")}
    degen = 0
    for r in results:
        agg[r["status"]] += 1
        degen += int(r.get("degenerate", False))
    scored_present = agg["match"] + agg["mismatch"] + agg["missed"]
    return {
        "per_field": results,
        "counts": agg,
        "degenerate": degen,
        "accuracy_present": round(agg["match"] / scored_present, 3) if scored_present else None,
        "hallucination_rate": round(
            agg["hallucinated"] / (agg["hallucinated"] + agg["abstained"]), 3
        ) if (agg["hallucinated"] + agg["abstained"]) else None,
    }


if __name__ == "__main__":  # demo rápida
    g = {"radicado_23_digitos": "13001-40-03-013-2026-00556-00", "asunto": "TRASLADO DOCENTE",
         "sentido_fallo_1st": "CONCEDE", "fecha_fallo_1st": None, "pretensiones": "Solicito el traslado del docente"}
    p = {"radicado_23_digitos": "13001400301320260055600", "asunto": "TRASLADO DE DOCENTE",
         "sentido_fallo_1st": "CONCEDE PARCIALMENTE", "fecha_fallo_1st": "12/03/2026",
         "pretensiones": "Solicito el traslado del docente al colegio X"}
    import json
    print(json.dumps(score_case(g, p), ensure_ascii=False, indent=2))
