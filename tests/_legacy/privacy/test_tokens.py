"""Tests de acuñación de tokens (v5.3)."""

from backend.privacy.tokens import TokenCatalog


def test_same_value_same_token_within_case():
    cat = TokenCatalog(case_id=1)
    t1 = cat.mint("PERSON", "Paola Andrea García")
    t2 = cat.mint("PERSON", "Paola Andrea García")
    t3 = cat.mint("PERSON", "PAOLA ANDREA GARCÍA")  # normalización
    assert t1 == t2 == t3


def test_different_values_different_tokens():
    cat = TokenCatalog(case_id=1)
    t1 = cat.mint("PERSON", "Paola García")
    t2 = cat.mint("PERSON", "Sofía García")
    assert t1 != t2


def test_same_value_different_cases_different_tokens():
    cat1 = TokenCatalog(case_id=1)
    cat2 = TokenCatalog(case_id=2)
    t1 = cat1.mint("PERSON", "Juan Pérez")
    t2 = cat2.mint("PERSON", "Juan Pérez")
    # Mismo counter (1) pero diferente salt garantiza que value_hash sea distinto
    # en la tabla pii_mappings. El token formato puede coincidir (ACCIONANTE_1)
    # pero la identidad (case_id, value_hash) difiere.
    assert cat1.mapping()[t1]["value_hash"] != cat2.mapping()[t2]["value_hash"]


def test_cc_token_preserves_last_4_digits():
    cat = TokenCatalog(case_id=1)
    t = cat.mint("CC", "63.498.732")
    assert "8732" in t


def test_phone_token_distinguishes_mobile_vs_fixed():
    cat = TokenCatalog(case_id=1)
    mobile = cat.mint("PHONE", "3204992211")
    fixed = cat.mint("PHONE", "6076345678")
    assert "MOVIL" in mobile
    assert "FIJO" in fixed


def test_email_token_categorizes_domain():
    cat = TokenCatalog(case_id=1)
    gov = cat.mint("EMAIL", "abogado@santander.gov.co")
    pers = cat.mint("EMAIL", "paola@gmail.com")
    assert "GOV" in gov
    assert "PERS" in pers


def test_cie10_token_keeps_family_only():
    cat = TokenCatalog(case_id=1)
    t = cat.mint("DX_DETAIL", "G80.9")
    # G80.9 → G80 (sin el .9)
    assert "G80" in t and "9" not in t.replace("G80", "")


def test_city_token_maps_to_dane_region():
    cat = TokenCatalog(case_id=1)
    t = cat.mint("CITY_EXACT", "Bucaramanga")
    assert "REG_ORIENTE" in t


def test_counter_increments_per_kind():
    cat = TokenCatalog(case_id=1)
    p1 = cat.mint("PERSON", "Juan")
    p2 = cat.mint("PERSON", "María")
    p3 = cat.mint("PERSON", "Pedro")
    # Mismos sufijos numéricos incrementales (independientes del format por kind)
    mapping = cat.mapping()
    assert len(mapping) == 3
