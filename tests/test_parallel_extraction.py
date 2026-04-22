"""Tests para extraccion IA paralela (parallel_extract_with_ai v4.7).

Cubre:
- Merge Gemini + DeepSeek con cross-validation (boost a ALTA)
- Conflicto en campos criticos (demote a MEDIA → regex gana en Fase 5)
- Un provider rate-limited, el otro responde
- Ambos providers fallan
- Flag OFF: garantia de no-regression sobre flujo secuencial
- TokenUsage: 2 registros por caso cuando flag ON
"""

from unittest.mock import patch

import pytest

from backend.extraction.ai_extractor import (
    AIExtractionResult,
    AIFieldResult,
    _merge_ai_results,
    parallel_extract_with_ai,
)


# ============================================================
# Helpers
# ============================================================

def _mk_result(
    fields_dict: dict[str, tuple[str, str]] | None = None,
    error: str | None = None,
    provider: str = "google",
    model: str = "gemini-2.5-flash",
    tokens_input: int = 100,
    tokens_output: int = 200,
    duration_ms: int = 1500,
) -> AIExtractionResult:
    """Construir AIExtractionResult de prueba.

    fields_dict: {"accionante": ("Juan Perez", "ALTA"), ...}
    """
    fields: dict[str, AIFieldResult] = {}
    if fields_dict:
        for fname, (value, confidence) in fields_dict.items():
            fields[fname] = AIFieldResult(
                value=value,
                confidence=confidence,
                source=f"{provider}_source",
            )
    return AIExtractionResult(
        fields=fields,
        error=error,
        provider=provider,
        model=model,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        tokens_used=tokens_input + tokens_output,
        duration_ms=duration_ms,
        chunks_used=1,
    )


# ============================================================
# Test 1: cross-validation boost
# ============================================================

def test_merge_cross_validated_boost():
    """Si ambos providers devuelven el mismo valor, se marca cross-validated ALTA."""
    gemini = _mk_result(
        fields_dict={"accionante": ("Juan Perez", "ALTA")},
        provider="google",
        model="gemini-2.5-flash",
    )
    deepseek = _mk_result(
        fields_dict={"accionante": ("Juan Perez", "ALTA")},
        provider="deepseek",
        model="deepseek-chat",
    )

    merged = _merge_ai_results(gemini, deepseek, case_id=1)

    assert "accionante" in merged.fields
    field = merged.fields["accionante"]
    assert field.value == "Juan Perez"
    assert field.confidence == "ALTA"
    assert "_cv" in (field.source or ""), f"source debe indicar cross-validated, got {field.source}"

    # Tokens combinados
    assert merged.tokens_input == gemini.tokens_input + deepseek.tokens_input
    assert merged.tokens_output == gemini.tokens_output + deepseek.tokens_output
    assert merged.provider.startswith("parallel")


def test_merge_cross_validated_normalized_case():
    """Valores que difieren en mayusculas/espacios deben contar como coincidencia."""
    gemini = _mk_result(fields_dict={"accionante": ("JUAN   PEREZ", "ALTA")})
    deepseek = _mk_result(
        fields_dict={"accionante": ("juan perez", "MEDIA")},
        provider="deepseek",
    )

    merged = _merge_ai_results(gemini, deepseek, case_id=1)
    field = merged.fields["accionante"]
    assert field.confidence == "ALTA"  # Normalized match → boost a ALTA
    assert "_cv" in field.source


# ============================================================
# Test 2: conflicto en campo critico
# ============================================================

def test_merge_conflict_critical_field_demote():
    """Dos ALTA conflictivas en radicado → demote a MEDIA."""
    gemini = _mk_result(
        fields_dict={"radicado_23_digitos": ("68001400300120260000100", "ALTA")},
    )
    deepseek = _mk_result(
        fields_dict={"radicado_23_digitos": ("68001400300120260009999", "ALTA")},
        provider="deepseek",
    )

    merged = _merge_ai_results(gemini, deepseek, case_id=1)

    field = merged.fields["radicado_23_digitos"]
    assert field.confidence == "MEDIA", "Conflicto critico debe bajar a MEDIA"
    assert field.source == "conflict_gemini_vs_deepseek"


def test_merge_conflict_critical_field_resolve_field_regex_wins():
    """Despues del demote, resolve_field() debe preferir regex para campo critico."""
    from backend.agent.extractors.base import ExtractionResult
    from backend.agent.extractors.registry import resolve_field, REGEX_PREFERRED_FIELDS

    # Sanity: radicado_23_digitos es REGEX_PREFERRED
    assert "radicado_23_digitos" in REGEX_PREFERRED_FIELDS

    gemini = _mk_result(
        fields_dict={"radicado_23_digitos": ("AAAA-BBBB", "ALTA")},
    )
    deepseek = _mk_result(
        fields_dict={"radicado_23_digitos": ("CCCC-DDDD", "ALTA")},
        provider="deepseek",
    )
    merged = _merge_ai_results(gemini, deepseek, case_id=1)

    # Simular el wrapping que hace unified.py Fase 4
    ai_er = ExtractionResult(
        value=merged.fields["radicado_23_digitos"].value,
        confidence=70,  # MEDIA → 70
        source=merged.fields["radicado_23_digitos"].source,
        method="ia",
        reasoning="IA parallel",
    )
    regex_er = ExtractionResult(
        value="68001400300120260000100",
        confidence=95,  # regex alta confianza
        source="auto_admisorio",
        method="regex",
        reasoning="regex match",
    )

    resolved = resolve_field("radicado_23_digitos", regex_er, ai_er)
    assert resolved is not None
    assert resolved.value == "68001400300120260000100", "regex debe ganar en campo preferred"


# ============================================================
# Test 3: un provider en rate-limit
# ============================================================

def test_one_provider_rate_limited():
    """Si DeepSeek devuelve error, Gemini sigue proveyendo campos."""
    gemini = _mk_result(
        fields_dict={
            "accionante": ("Juan Perez", "ALTA"),
            "juzgado": ("Juzgado 1", "ALTA"),
            "ciudad": ("Bucaramanga", "MEDIA"),
        },
    )
    deepseek = AIExtractionResult(
        error="rate_limit",
        provider="deepseek",
        model="deepseek-chat",
        tokens_input=0,
        tokens_output=0,
    )

    merged = _merge_ai_results(gemini, deepseek, case_id=1)

    assert merged.error is None, "Un solo error NO debe propagarse como error combinado"
    assert len(merged.fields) == 3
    assert merged.fields["accionante"].value == "Juan Perez"


# ============================================================
# Test 4: ambos fallan
# ============================================================

def test_both_providers_fail():
    """Si ambos fallan, merged tiene error combinado y fields={}."""
    gemini = AIExtractionResult(
        error="timeout", provider="google", model="gemini-2.5-flash",
    )
    deepseek = AIExtractionResult(
        error="rate_limit", provider="deepseek", model="deepseek-chat",
    )

    merged = _merge_ai_results(gemini, deepseek, case_id=1)

    assert merged.error is not None
    assert "gemini" in merged.error.lower()
    assert "deepseek" in merged.error.lower()
    assert len(merged.fields) == 0


def test_both_empty_fields_synthesizes_error():
    """Si ambos devuelven fields={} sin error explicito, sintetizar error."""
    gemini = AIExtractionResult(fields={}, provider="google", model="gemini-2.5-flash")
    deepseek = AIExtractionResult(fields={}, provider="deepseek", model="deepseek-chat")

    merged = _merge_ai_results(gemini, deepseek, case_id=1)

    assert merged.error is not None
    assert "empty" in merged.error.lower()


# ============================================================
# Test 5: preferencia por campo en empate de confianza
# ============================================================

def test_merge_tie_prefers_gemini_for_visual_fields():
    """Empate MEDIA vs MEDIA en juzgado → Gemini gana (GEMINI_PREFERRED)."""
    gemini = _mk_result(
        fields_dict={"juzgado": ("Juzgado 1 Civil", "MEDIA")},
        provider="google",
    )
    deepseek = _mk_result(
        fields_dict={"juzgado": ("Juzgado Primero Civil Municipal", "MEDIA")},
        provider="deepseek",
    )

    merged = _merge_ai_results(gemini, deepseek, case_id=1)
    assert merged.fields["juzgado"].value == "Juzgado 1 Civil"


def test_merge_tie_prefers_deepseek_for_textual_fields():
    """Empate MEDIA vs MEDIA en observaciones → DeepSeek gana (DEEPSEEK_PREFERRED)."""
    gemini = _mk_result(
        fields_dict={"observaciones": ("Corto texto gemini", "MEDIA")},
        provider="google",
    )
    deepseek = _mk_result(
        fields_dict={"observaciones": ("Analisis detallado del caso", "MEDIA")},
        provider="deepseek",
    )

    merged = _merge_ai_results(gemini, deepseek, case_id=1)
    assert merged.fields["observaciones"].value == "Analisis detallado del caso"


# ============================================================
# Test 6: parallel_extract_with_ai degrada a secuencial si falta API key
# ============================================================

def test_parallel_degrades_to_sequential_when_no_api_key(monkeypatch):
    """Sin API keys, degrada a extract_with_ai y devuelve (result, [result])."""
    # Limpiar env vars para forzar degradacion
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    # Mock extract_with_ai para evitar llamadas reales
    fake_result = AIExtractionResult(
        fields={"accionante": AIFieldResult(value="Test", confidence="ALTA", source="mock")},
        provider="mocked",
        model="mock",
        tokens_input=10,
        tokens_output=20,
    )

    with patch(
        "backend.extraction.ai_extractor.extract_with_ai",
        return_value=fake_result,
    ) as mock_seq:
        merged, raw_list = parallel_extract_with_ai(
            documents=[{"filename": "x.pdf", "text": "contenido", "doc_type": "OTRO"}],
            folder_name="2026-00001 TEST",
            pdf_file_paths=None,
            case_id=1,
        )

    mock_seq.assert_called_once()
    assert len(raw_list) == 1
    assert raw_list[0] is fake_result
    assert merged.fields["accionante"].value == "Test"


# ============================================================
# Test 7: parallel_extract_with_ai corre ambos threads cuando hay keys
# ============================================================

def test_parallel_runs_both_providers(monkeypatch):
    """Con keys disponibles y sin rate limit, corre ambos via ThreadPoolExecutor."""
    # Poner API keys fake (solo para pasar el check inicial)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake_google_key_123456")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake_deepseek_key_123456")

    # Resetear cooldown
    import backend.agent.smart_router as sr
    sr._rate_limit_cooldown.clear()

    call_log = []

    def fake_run_single_provider(provider, model, documents, folder_name, pdf_file_paths):
        call_log.append(provider)
        if provider == "google":
            return _mk_result(
                fields_dict={"accionante": ("Juan Perez", "ALTA")},
                provider="google",
                model="gemini-2.5-flash",
                duration_ms=1200,
            )
        else:
            return _mk_result(
                fields_dict={
                    "accionante": ("Juan Perez", "ALTA"),
                    "observaciones": ("caso textual", "MEDIA"),
                },
                provider="deepseek",
                model="deepseek-chat",
                duration_ms=800,
            )

    with patch(
        "backend.extraction.ai_extractor._run_single_provider",
        side_effect=fake_run_single_provider,
    ):
        merged, raw_list = parallel_extract_with_ai(
            documents=[{"filename": "x.pdf", "text": "contenido", "doc_type": "OTRO"}],
            folder_name="2026-00001 TEST",
            pdf_file_paths=None,
            case_id=1,
        )

    assert len(call_log) == 2
    assert "google" in call_log and "deepseek" in call_log
    assert len(raw_list) == 2
    # accionante debe ser cross-validated
    assert "_cv" in merged.fields["accionante"].source
    # observaciones solo de deepseek
    assert "observaciones" in merged.fields
    # Token accounting: suma de ambos
    assert merged.tokens_input == 200  # 100 + 100


# ============================================================
# Test 8: flag OFF no invoca la funcion paralela
# ============================================================

def test_flag_default_is_off_in_schema():
    """El default del campo PARALLEL_AI_EXTRACTION en el schema debe ser False.

    Nota: el valor runtime puede ser True si el usuario lo activa en .env,
    pero el default del modelo garantiza que instalaciones nuevas arrancan OFF.
    """
    from backend.core.settings import Settings

    field_info = Settings.model_fields["PARALLEL_AI_EXTRACTION"]
    assert field_info.default is False, (
        "El default del schema debe ser False para no romper instalaciones nuevas"
    )


# ============================================================
# Test 9 (v4.7+): Routing post-Gemini — DeepSeek primary, Haiku 4.5 fallback
# ============================================================

def test_routing_v47_deepseek_primary_haiku_fallback(monkeypatch):
    """Sin Gemini, el router debe devolver DeepSeek como primary y
    Claude Haiku 4.5 como fallback para la tarea 'extraction'."""
    from backend.agent.smart_router import route, _rate_limit_cooldown

    # Asegurar API keys disponibles (sin tocar .env real)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake_deepseek_key_123456")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake_anthropic_key_123456")
    _rate_limit_cooldown.clear()

    decision = route("extraction")

    assert decision.provider == "deepseek", f"primary debe ser deepseek, got {decision.provider}"
    assert decision.model == "deepseek-chat"
    assert decision.fallback_provider == "anthropic", (
        f"fallback debe ser anthropic, got {decision.fallback_provider}"
    )
    assert decision.fallback_model == "claude-haiku-4-5-20251001", (
        f"fallback model debe ser haiku 4.5, got {decision.fallback_model}"
    )


def test_routing_v47_no_gemini_in_any_chain(monkeypatch):
    """v4.7: Gemini NO debe aparecer en ninguna cadena de routing."""
    from backend.agent.smart_router import ROUTING_CHAINS

    for task, chain in ROUTING_CHAINS.items():
        providers_in_chain = [p[0] for p in chain]
        assert "google" not in providers_in_chain, (
            f"Gemini ('google') no debe estar en routing chain '{task}' — "
            f"encontrado: {providers_in_chain}"
        )


def test_routing_haiku_45_is_in_provider_catalog():
    """Claude Haiku 4.5 debe estar en PROVIDERS (Haiku 3 fue retirado)."""
    from backend.extraction.ai_extractor import PROVIDERS

    anthropic_models = PROVIDERS.get("anthropic", {}).get("models", {})
    assert "claude-haiku-4-5-20251001" in anthropic_models, (
        f"claude-haiku-4-5-20251001 no encontrado. Modelos: {list(anthropic_models.keys())}"
    )
    haiku_45 = anthropic_models["claude-haiku-4-5-20251001"]
    # Verificar precios correctos (oficiales de Anthropic)
    assert haiku_45["input_price"] == 1.00
    assert haiku_45["output_price"] == 5.00
