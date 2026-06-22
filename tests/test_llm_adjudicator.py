"""Tests del adjudicador DeepSeek de la ingesta (backend/email/llm_adjudicator.py).

Mockean `_call_local` (la llamada a DeepSeek) para ser deterministas — igual que
test_monitor_matcher mockea el desempate. Verifican el contrato:
- gateado off → AMBIGUOUS (fallback determinista),
- confiado → aplica,
- baja confianza → no aplica,
- decisión fuera de candidatos → rechazada (AMBIGUOUS),
- basura/no-JSON → AMBIGUOUS.
"""

import backend.email.llm_adjudicator as adj
from backend.email.llm_adjudicator import Verdict, _adjudicate


def _mock_llm(monkeypatch, raw: str):
    """Fuerza llm_on=True y hace que _call_local devuelva `raw`."""
    monkeypatch.setattr(adj, "llm_on", lambda: True)
    import backend.extraction.ai_extractor as ai
    monkeypatch.setattr(ai, "_call_local", lambda *a, **k: (raw, 0, 0))


VALID = {"100", "200", "NEW", "AMBIGUOUS"}
CANDS = [100, 200]


def test_gated_off_abstiene(monkeypatch):
    monkeypatch.setattr(adj, "llm_on", lambda: False)
    v = _adjudicate("sys", "prompt", valid=VALID, candidates=CANDS)
    assert v.decision == "AMBIGUOUS" and v.confidence == 0.0 and not v.is_confident


def test_confiado_aplica(monkeypatch):
    _mock_llm(monkeypatch, '{"decision": 100, "confidence": 0.95, "reason": "accionante y juzgado coinciden"}')
    v = _adjudicate("sys", "prompt", valid=VALID, candidates=CANDS)
    assert v.decision == 100 and v.confidence == 0.95 and v.is_confident
    assert "accionante" in v.reason


def test_baja_confianza_no_aplica(monkeypatch):
    _mock_llm(monkeypatch, '{"decision": 200, "confidence": 0.50, "reason": "dudoso"}')
    v = _adjudicate("sys", "prompt", valid=VALID, candidates=CANDS)
    assert v.decision == 200 and not v.is_confident  # decidió pero NO auto-resuelve


def test_decision_fuera_de_candidatos_rechazada(monkeypatch):
    _mock_llm(monkeypatch, '{"decision": 999, "confidence": 0.99, "reason": "alucinó un id"}')
    v = _adjudicate("sys", "prompt", valid=VALID, candidates=CANDS)
    assert v.decision == "AMBIGUOUS" and not v.is_confident


def test_new_es_valido(monkeypatch):
    _mock_llm(monkeypatch, '{"decision": "NEW", "confidence": 0.9, "reason": "otro proceso"}')
    v = _adjudicate("sys", "prompt", valid=VALID, candidates=CANDS)
    assert v.decision == "NEW" and v.is_confident


def test_basura_abstiene(monkeypatch):
    _mock_llm(monkeypatch, "######## $$$$ %%%% no es json")
    v = _adjudicate("sys", "prompt", valid=VALID, candidates=CANDS)
    assert v.decision == "AMBIGUOUS"


def test_json_con_fences_y_prosa(monkeypatch):
    _mock_llm(monkeypatch, 'Claro:\n```json\n{"decision": 200, "confidence": 0.91, "reason": "ok"}\n```')
    v = _adjudicate("sys", "prompt", valid=VALID, candidates=CANDS)
    assert v.decision == 200 and v.is_confident


def test_confidence_fuera_de_rango_se_clampa(monkeypatch):
    _mock_llm(monkeypatch, '{"decision": 100, "confidence": 5, "reason": "x"}')
    v = _adjudicate("sys", "prompt", valid=VALID, candidates=CANDS)
    assert v.confidence == 1.0  # clamp a [0,1]


def test_adjudicate_assignment_sin_candidatos():
    v = adj.adjudicate_assignment(None, None, [])
    assert v.decision == "AMBIGUOUS"


def test_verdict_as_dict_serializable():
    v = Verdict(100, 0.9, "razón", [100, 200])
    d = v.as_dict()
    assert d["decision"] == 100 and d["confidence"] == 0.9 and d["candidates"] == [100, 200]


# ── classify_doc_by_content ──────────────────────────────────
_DOC_TEXT = "ACCION DE TUTELA. Yo, JUAN PEREZ, interpongo accion de tutela contra la Secretaria " * 6


def test_doc_content_clasifica_demanda(monkeypatch):
    _mock_llm(monkeypatch, '{"decision": "DEMANDA_TUTELA", "confidence": 0.93, "reason": "escrito del accionante"}')
    v = adj.classify_doc_by_content(_DOC_TEXT, "adjunto1.pdf")
    assert v.decision == "DEMANDA_TUTELA" and v.is_confident


def test_doc_content_otro_no_se_aplica(monkeypatch):
    _mock_llm(monkeypatch, '{"decision": "OTRO", "confidence": 0.9, "reason": "no encaja"}')
    v = adj.classify_doc_by_content(_DOC_TEXT, "x.pdf")
    assert v.decision == "OTRO"  # is_confident True, pero el caller NO aplica OTRO


def test_doc_content_tipo_invalido_abstiene(monkeypatch):
    _mock_llm(monkeypatch, '{"decision": "FACTURA", "confidence": 0.99, "reason": "alucinó"}')
    v = adj.classify_doc_by_content(_DOC_TEXT, "x.pdf")
    assert v.decision == "AMBIGUOUS"


def test_doc_content_texto_corto_abstiene(monkeypatch):
    monkeypatch.setattr(adj, "llm_on", lambda: True)
    v = adj.classify_doc_by_content("muy corto", "x.pdf")
    assert v.decision == "AMBIGUOUS" and "insuficiente" in v.reason


def test_doc_content_gated_off(monkeypatch):
    monkeypatch.setattr(adj, "llm_on", lambda: False)
    v = adj.classify_doc_by_content(_DOC_TEXT, "x.pdf")
    assert v.decision == "AMBIGUOUS"
