"""Tests para backend/email/rad_utils.py (v5.4.3)."""

import pytest

from backend.email.rad_utils import (
    canonical_rad_corto,
    consistent,
    derive_rad_corto_from_rad23,
    is_valid_rad23,
    juzgado_code,
    normalize_rad23,
    reconcile,
    same_juzgado,
)


# ─────────────────────────────────────────────────────────────
# normalize_rad23
# ─────────────────────────────────────────────────────────────

class TestNormalizeRad23:
    def test_con_guiones(self):
        out = normalize_rad23("54-001-41-05-002-2026-10021-00")
        assert out == "54001410500220261002100"
        assert len(out) == 23

    def test_con_espacios(self):
        out = normalize_rad23("68 001 4003 017 2026 00304 00")
        assert out == "68001400301720260030400"
        assert len(out) == 23

    def test_con_puntos(self):
        out = normalize_rad23("68.001.41.05.002.2026.00304.00")
        assert out == "68001410500220260030400"
        assert len(out) == 23

    def test_ya_limpio(self):
        assert normalize_rad23("68001410500220260030400") == "68001410500220260030400"

    def test_vacio(self):
        assert normalize_rad23("") == ""
        assert normalize_rad23(None) == ""


# ─────────────────────────────────────────────────────────────
# is_valid_rad23
# ─────────────────────────────────────────────────────────────

class TestIsValidRad23:
    def test_20_digitos(self):
        assert is_valid_rad23("54-001-41-05-002-2026-10021-00")

    def test_18_digitos_minimo(self):
        assert is_valid_rad23("680014003017202600304")  # 21 dígitos, válido

    def test_muy_corto(self):
        assert not is_valid_rad23("2026-00304")

    def test_vacio(self):
        assert not is_valid_rad23("")
        assert not is_valid_rad23(None)


# ─────────────────────────────────────────────────────────────
# derive_rad_corto_from_rad23 — el bug que causó 407/619
# ─────────────────────────────────────────────────────────────

class TestDeriveRadCorto:
    def test_caso_real_ronald_diaz(self):
        """Caso 619 vs 407: rad23 idéntico debe producir 2026-10021, NO 2026-01002."""
        rad23 = "54-001-41-05-002-2026-10021-00"
        assert derive_rad_corto_from_rad23(rad23) == "2026-10021"

    def test_con_separadores_mixtos(self):
        assert derive_rad_corto_from_rad23("68.001.41.05.002.2026.00304.00") == "2026-00304"

    def test_secuencia_baja(self):
        assert derive_rad_corto_from_rad23("68001400301720260000500") == "2026-00005"

    def test_muy_corto_retorna_vacio(self):
        assert derive_rad_corto_from_rad23("2026-00001") == ""

    def test_none_retorna_vacio(self):
        assert derive_rad_corto_from_rad23(None) == ""


# ─────────────────────────────────────────────────────────────
# canonical_rad_corto — fix del zfill bug
# ─────────────────────────────────────────────────────────────

class TestCanonicalRadCorto:
    def test_ya_canonico(self):
        assert canonical_rad_corto("2026-10021") == "2026-10021"

    def test_con_rad_label(self):
        assert canonical_rad_corto("RAD 2026-00053") == "2026-00053"

    def test_secuencia_5_digitos_sin_zfill(self):
        assert canonical_rad_corto("2026-10021") == "2026-10021"

    def test_secuencia_4_digitos_con_zfill(self):
        """Con min_digits=4 (default) acepta 4-dígitos y zfill-ea."""
        assert canonical_rad_corto("2026-1002") == "2026-01002"

    def test_secuencia_3_digitos_rechaza(self):
        """Con min_digits=4, rechaza secuencias de 3 dígitos."""
        assert canonical_rad_corto("2026-100") == ""

    def test_secuencia_5_digitos_estricto(self):
        """Si caller exige ≥5 dígitos, secuencias de 4 se rechazan."""
        assert canonical_rad_corto("2026-1002", min_digits=5) == ""
        assert canonical_rad_corto("2026-10021", min_digits=5) == "2026-10021"

    def test_rechaza_forest_like(self):
        """Una secuencia tipo '20260066132' NO debe producir rad_corto: es FOREST."""
        assert canonical_rad_corto("20260066132") == ""

    def test_rechaza_anio_invalido(self):
        assert canonical_rad_corto("1999-00001") == ""

    def test_vacio(self):
        assert canonical_rad_corto("") == ""
        assert canonical_rad_corto(None) == ""


# ─────────────────────────────────────────────────────────────
# consistent
# ─────────────────────────────────────────────────────────────

class TestConsistent:
    def test_ambos_coinciden(self):
        assert consistent("54-001-41-05-002-2026-10021-00", "2026-10021")

    def test_rad23_solo(self):
        """Si solo hay rad23, no hay conflicto."""
        assert consistent("54-001-41-05-002-2026-10021-00", "")
        assert consistent("54-001-41-05-002-2026-10021-00", None)

    def test_rad_corto_solo(self):
        """Si solo hay rad_corto, no hay conflicto."""
        assert consistent("", "2026-10021")

    def test_inconsistente_bug_clasico(self):
        """rad23 dice 10021 pero rad_corto dice 01002 → INCONSISTENTE."""
        assert not consistent("54-001-41-05-002-2026-10021-00", "2026-01002")

    def test_rad23_invalido_no_juzga(self):
        """Si rad23 no se puede parsear, no rechaza."""
        assert consistent("abc", "2026-00001")


# ─────────────────────────────────────────────────────────────
# reconcile
# ─────────────────────────────────────────────────────────────

class TestReconcile:
    def test_rad23_valido_prevalece(self):
        """Si rad23 es válido, el rad_corto se re-deriva (ignora el incorrecto del email)."""
        rad23, corto = reconcile(
            "54-001-41-05-002-2026-10021-00",
            "2026-01002",  # incorrecto
        )
        assert rad23 == "54-001-41-05-002-2026-10021-00"
        assert corto == "2026-10021"  # derivado, no el incorrecto

    def test_solo_rad_corto(self):
        rad23, corto = reconcile("", "2026-00005")
        assert rad23 == ""
        assert corto == "2026-00005"

    def test_ambos_vacios(self):
        assert reconcile("", "") == ("", "")
        assert reconcile(None, None) == ("", "")

    def test_rad23_invalido_usa_rad_corto(self):
        rad23, corto = reconcile("abc123", "2026-00005")
        assert corto == "2026-00005"


# ─────────────────────────────────────────────────────────────
# juzgado_code / same_juzgado (F7 multi-juzgado guard)
# ─────────────────────────────────────────────────────────────

class TestJuzgadoCode:
    def test_extrae_codigo_juzgado(self):
        # Primeros 12 dígitos: 54 + 001 + 41 + 05 + 002
        assert juzgado_code("54-001-41-05-002-2026-10021-00") == "540014105002"

    def test_rad23_corto_retorna_vacio(self):
        assert juzgado_code("2026-00001") == ""

    def test_same_juzgado_true(self):
        assert same_juzgado(
            "54-001-41-05-002-2026-10021-00",
            "54-001-41-05-002-2026-99999-00",
        )

    def test_same_juzgado_false(self):
        """Bucaramanga (68001) vs Cúcuta (54001) — distinto juzgado."""
        assert not same_juzgado(
            "68-001-41-05-002-2026-00057-00",
            "54-001-41-05-002-2026-00057-00",
        )

    def test_same_juzgado_uno_vacio(self):
        assert not same_juzgado("", "54-001-41-05-002-2026-10021-00")
