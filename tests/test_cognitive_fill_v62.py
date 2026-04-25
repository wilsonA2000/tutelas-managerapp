"""Tests FIX 6: cognitive_fill con validación + NER fallback.

Cubre la mejora del path de extracción del accionante:
- Sanitiza con clean_accionante antes de aceptar
- Rechaza si parece juzgado
- Cae a NER PERSON cuando actor_extractor falla
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.cognition.cognitive_fill import (
    _accionante_collides_with_juzgado,
    _pick_accionante_from_ner,
    _pick_accionante_from_text,
)


class TestPickAccionanteFromText:
    """FIX 6.1: regex header explícito antes de NER."""

    def test_accionante_header(self):
        text = "Fallo No. 080\nAccionante: CARMEN BELEN CAPACHO PORTILLA\nAccionado: X"
        assert _pick_accionante_from_text(text) == "CARMEN BELEN CAPACHO PORTILLA"

    def test_demandante_header(self):
        text = "JUZGADO X\nDemandante: JUAN CARLOS PEREZ MARTINEZ\nDemandado: Y"
        assert _pick_accionante_from_text(text) == "JUAN CARLOS PEREZ MARTINEZ"

    def test_tutelante_header(self):
        text = "Tutelante: MARIA FERNANDA TORRES GOMEZ\n"
        assert _pick_accionante_from_text(text) == "MARIA FERNANDA TORRES GOMEZ"

    def test_ignora_juzgado_en_header(self):
        # Si el regex pesca un juzgado por error, debe rechazarse
        text = "Accionante: JUZGADO SEGUNDO PENAL DE BUCARAMANGA\n"
        assert _pick_accionante_from_text(text) == ""

    def test_header_con_dash(self):
        text = "Accionante - LUISA MARTINEZ ROJAS\n"
        assert _pick_accionante_from_text(text) == "LUISA MARTINEZ ROJAS"


class TestAccionanteCollidesWithJuzgado:
    def test_juzgado_word_in_name(self):
        assert _accionante_collides_with_juzgado("JUZGADO 9 PENAL", "Juzgado 9 Penal Bucaramanga")

    def test_tribunal_word(self):
        assert _accionante_collides_with_juzgado("TRIBUNAL SUPERIOR", "")

    def test_corte_word(self):
        assert _accionante_collides_with_juzgado("CORTE CONSTITUCIONAL", "")

    def test_substantial_overlap(self):
        # caso 181 real: "JUZGADO SÉPTIMO CIVIL DEL CIRCUITO DE BUCARAMANGA"
        # debería rechazarse aunque solo coincida con campo juzgado
        n = "JUZGADO SÉPTIMO CIVIL DEL CIRCUITO DE BUCARAMANGA"
        j = "Juzgado Séptimo Civil del Circuito de Bucaramanga"
        assert _accionante_collides_with_juzgado(n, j)

    def test_real_name_passes(self):
        assert not _accionante_collides_with_juzgado(
            "CARMEN BELEN CAPACHO PORTILLA",
            "Juzgado 9 Civil Bucaramanga",
        )

    def test_empty_inputs(self):
        assert not _accionante_collides_with_juzgado("", "Juzgado X")
        assert not _accionante_collides_with_juzgado("ANA LOPEZ", "")


class TestPickAccionanteFromNer:
    def test_empty_text(self):
        assert _pick_accionante_from_ner("") == ""

    def test_picks_person_from_header(self):
        # Texto de tutela típica: el accionante suele aparecer en primeras líneas
        text = (
            "Bucaramanga, 1 de marzo de 2026.\n"
            "Señor Juez Constitucional.\n"
            "Yo, MARIA FERNANDA TORRES GOMEZ, mayor de edad, identificada con\n"
            "cédula 1098765432, presento acción de tutela contra la Gobernación.\n"
            "Hechos:\n1. Antecedentes...\n"
        )
        result = _pick_accionante_from_ner(text)
        # spaCy debe identificar "MARIA FERNANDA TORRES GOMEZ" o similar
        assert result, "spaCy NER no extrajo persona"
        assert "MARIA" in result.upper() or "TORRES" in result.upper()

    def test_rejects_juzgado_collision(self):
        text = (
            "JUZGADO SEGUNDO PENAL DE BUCARAMANGA\n"
            "Magistrado Ponente.\n"
        )
        # No debe devolver el juzgado como accionante
        result = _pick_accionante_from_ner(text, juzgado="Juzgado Segundo Penal de Bucaramanga")
        # spaCy puede o no identificar PERSON aquí; el filtro debe rechazar el juzgado
        assert "JUZGADO" not in result.upper() if result else True
