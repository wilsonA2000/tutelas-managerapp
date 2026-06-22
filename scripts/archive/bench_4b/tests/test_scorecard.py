"""Fase 0 — self-test del scorecard (scores conocidos)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "bench"))
import scorecard as sc  # noqa: E402


def test_exact_radicado_ignores_separators():
    r = sc.score_field("radicado_23_digitos", "13001-40-03-013-2026-00556-00", "13001400301320260055600")
    assert r["status"] == "match" and r["correct"]


def test_enum_bidirectional_containment():
    assert sc.score_field("sentido_fallo_1st", "CONCEDE", "CONCEDE PARCIALMENTE")["correct"]


def test_date_normalized():
    assert sc.score_field("fecha_fallo_1st", "12/03/2026", "12-03-2026")["correct"]


def test_verbatim_substring_matches():
    r = sc.score_field("pretensiones", "Solicito el traslado del docente",
                       "Solicito el traslado del docente al colegio X")
    assert r["correct"]


def test_semantic_overlap_threshold():
    assert sc.score_field("asunto", "TRASLADO DOCENTE", "TRASLADO DE DOCENTE")["correct"]
    assert not sc.score_field("asunto", "TRASLADO DOCENTE", "REINTEGRO LABORAL")["correct"]


def test_hallucination_when_gold_null():
    r = sc.score_field("fecha_fallo_2nd", None, "12/03/2026")
    assert r["status"] == "hallucinated" and not r["correct"]


def test_abstention_when_gold_null_and_pred_empty():
    r = sc.score_field("fecha_fallo_2nd", None, "")
    assert r["status"] == "abstained" and r["correct"]


def test_missed_when_gold_present_pred_empty():
    assert sc.score_field("asunto", "TRASLADO", "")["status"] == "missed"


def test_unverified_skipped():
    assert sc.score_field("asunto", "", "lo que sea")["status"] == "skipped_unverified"


def test_degeneration_flag():
    r = sc.score_field("observaciones", None, "1 1 1 1 1 1 1 1 1")
    assert r["degenerate"]


def test_score_case_aggregates():
    gold = {"radicado_23_digitos": "13001400301320260055600", "asunto": "TRASLADO",
            "fecha_fallo_2nd": None}
    pred = {"radicado_23_digitos": "13001400301320260055600", "asunto": "TRASLADO",
            "fecha_fallo_2nd": "01/01/2026"}
    res = sc.score_case(gold, pred)
    assert res["counts"]["match"] == 2
    assert res["counts"]["hallucinated"] == 1
    assert res["hallucination_rate"] == 1.0


def test_narrative_field_not_scored():
    # M1 2026-06-11: observaciones es narrativo append-only → no entra al accuracy.
    r = sc.score_field("observaciones", "[08/05] nota curada larga", "otro resumen distinto")
    assert r["status"] == "narrative"
    case = sc.score_case({"observaciones": "nota A", "asunto": "TRASLADO"},
                         {"observaciones": "nota B", "asunto": "TRASLADO"})
    assert case["counts"]["narrative"] == 1
    assert case["accuracy_present"] == 1.0  # solo asunto cuenta y matchea
