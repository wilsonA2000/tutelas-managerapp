"""Tests de fixes atómicos Anthropic v5.3 (Fase A)."""


def test_sonnet_4_6_20260320_removed_from_providers():
    from backend.extraction.ai_extractor import PROVIDERS
    models = PROVIDERS.get("anthropic", {}).get("models", {})
    assert "claude-sonnet-4-6-20260320" not in models


def test_sonnet_4_6_20260320_removed_from_pricing():
    from backend.agent.token_manager import PRICING
    assert "claude-sonnet-4-6-20260320" not in PRICING.get("anthropic", {})


def test_haiku_45_still_in_catalog():
    from backend.extraction.ai_extractor import PROVIDERS
    models = PROVIDERS.get("anthropic", {}).get("models", {})
    assert "claude-haiku-4-5-20251001" in models
    haiku = models["claude-haiku-4-5-20251001"]
    assert haiku["input_price"] == 1.00
    assert haiku["output_price"] == 5.00


def test_routing_chains_no_sonnet_reference():
    from backend.agent.smart_router import ROUTING_CHAINS
    for task, chain in ROUTING_CHAINS.items():
        for provider, model, _ in chain:
            assert model != "claude-sonnet-4-6-20260320", (
                f"Sonnet fantasma en routing chain '{task}'"
            )


def test_get_savings_report_does_not_reference_sonnet(tmp_path):
    """get_savings_report debe funcionar sin Sonnet."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.database.models import Base
    from backend.agent.token_manager import get_savings_report

    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    report = get_savings_report(db)
    assert "savings" in report
    assert "vs_claude_sonnet" not in report["savings"]
    assert "vs_claude_haiku" in report["savings"]
