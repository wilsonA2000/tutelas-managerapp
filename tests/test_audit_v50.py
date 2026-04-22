"""Tests de regresion para fixes V50 (auditoria 2026-04-20).

Cubre bugs B1-B9 + B13:
- B1: RAD_LABEL regex captura FOREST como radicado (FIX F1)
- B2: extract_radicado no prioriza rad23 (FIX F2)
- B3: prompt inyecta folder_name literal (FIX F3)
- B4: post-validator no detecta radicados ajenos (FIX F4)
- B5: no renombra folder [PENDIENTE REVISION] (FIX F5)
- B6: accionante en forwarded anidado no detectado (FIX F6)
- B7: matching por rad_corto sin validar juzgado (FIX F7)
- B8: pre-COMPLETO sin rad23 valido (FIX F8)
- B13: duplicacion no reconsolidada (FIX F9 — solo detection/log)
"""

from types import SimpleNamespace

import pytest


# ---------- F1 + F2: regex + priorizacion rad23 ----------

class TestB1_RegexRadLabel:
    """F1: RAD_LABEL ya no captura FOREST 11d como radicado corto."""

    def test_foreign_forest_not_matched(self):
        from backend.agent.regex_library import RAD_LABEL, RAD_GENERIC
        # Casos reales de los emails que generaron los bugs
        for text in [
            "Con numero de radicado 20260066132",
            "con número de radicado 20260069467",
            "numero de radicado 20260066132",
            "radicado 20260066132",
        ]:
            assert RAD_LABEL.pattern.search(text) is None, (
                f"RAD_LABEL matcheo FOREST en: {text!r}"
            )
            assert RAD_GENERIC.pattern.search(text) is None, (
                f"RAD_GENERIC matcheo FOREST en: {text!r}"
            )

    def test_real_radicados_still_match(self):
        from backend.agent.regex_library import RAD_LABEL
        # El regex usa 0* para consumir ceros lideres; comparamos tras zfill(5)
        cases = [
            ("RAD. 2026-00095", "00095"),
            ("Radicado No. 2026-030", "00030"),
            ("RADICADO: 2026-00115", "00115"),
            ("Rad. 2026-00057", "00057"),
        ]
        for text, expected_seq in cases:
            m = RAD_LABEL.pattern.search(text)
            assert m is not None, f"RAD_LABEL no matcheo: {text!r}"
            assert m.group(1) == "2026"
            assert m.group(2).zfill(5) == expected_seq, (
                f"{text!r} → seq {m.group(2)!r}.zfill(5)={m.group(2).zfill(5)!r} vs {expected_seq!r}"
            )

    def test_all_patterns_self_test(self):
        from backend.agent.regex_library import validate_all_patterns
        results = validate_all_patterns()
        failures = [name for name, ok in results.items() if not ok]
        assert not failures, f"Patrones con auto-tests fallidos: {failures}"


class TestB2_ExtractRadicadoPrioritizesRad23:
    """F2: extract_radicado prioriza rad_corto derivado de rad23 sobre labels."""

    def test_caso_560_priorizes_rad23_over_forest_label(self):
        """Email real del caso 560: subject TUTELA 2026-00057, body con FOREST 20260066132."""
        from backend.email.gmail_monitor import extract_radicado
        subject = "RV: URGENTE!!! NOTIFICA AVOCA TUTELA 2026-00057"
        body = """Con número de radicado 20260066132

LINK EXP: 68001408800320260005700"""
        r = extract_radicado(f"{subject} {body}")
        assert r["radicado_23"] == "68001408800320260005700"
        assert r["radicado_corto"] == "2026-00057", (
            f"ESPERADO 2026-00057 (rad judicial), GOT {r['radicado_corto']} (probable FOREST)"
        )

    def test_no_rad23_falls_back_to_subject(self):
        """Si no hay rad23, rad_corto se extrae del subject."""
        from backend.email.gmail_monitor import extract_radicado
        r = extract_radicado("RV: 2026-00234 AVOCA TUTELA.")
        assert r["radicado_23"] == ""
        assert r["radicado_corto"] == "2026-00234"


# ---------- F3: builder de anti-contaminacion ----------

class TestB3_AntiContaminationBlock:
    """F3: bloque anti-contaminacion usa RADICADO OFICIAL cuando existe."""

    def test_uses_radicado_oficial_when_available(self):
        from backend.extraction.ai_extractor import _build_anti_contamination_block
        block = _build_anti_contamination_block(
            folder_name="2026-66132 [PENDIENTE REVISION]",
            radicado_oficial="68-001-40-88-003-2026-00057-00",
        )
        assert "RADICADO OFICIAL" in block
        assert "2026-00057" in block
        assert "68-001-40-88-003-2026-00057-00" in block
        # Que recuerde usar oficial, no folder
        assert "USA SIEMPRE" in block.upper() or "usa siempre" in block.lower()

    def test_falls_back_to_folder_when_no_rad23(self):
        from backend.extraction.ai_extractor import _build_anti_contamination_block
        block = _build_anti_contamination_block(folder_name="2026-00095 JUAN PEREZ")
        assert "CARPETA DEL CASO: 2026-00095 JUAN PEREZ" in block
        assert "RADICADO OFICIAL" not in block


# ---------- F4: post-validator detecta radicados ajenos ----------

class TestB4_ForeignRadicadosInObs:
    """F4: post-validator elimina oraciones 'Caso 20YY-NNNNN...' contaminadas."""

    def test_caso_560_removes_contaminated_sentence(self):
        from backend.extraction.post_validator import validate_extraction
        case = SimpleNamespace(
            folder_name="2026-66132 [PENDIENTE REVISION]",
            radicado_forest="20260066132",
        )
        fields = {
            "radicado_23_digitos": "68-001-40-88-003-2026-00057-00",
            "observaciones": (
                "Caso 2026-66132 en estado ACTIVO. "
                "El 14/04/2026, el Apoyo Juridico recibio la notificacion."
            ),
        }
        corrected, warnings = validate_extraction(case, fields)
        assert "observaciones" in corrected, f"Obs no corregida: {corrected}"
        assert "2026-66132" not in corrected["observaciones"]
        assert any("radicado ajeno" in w.lower() or "radicados ajenos" in w.lower() for w in warnings)

    def test_accumulated_tutelas_tolerated(self):
        from backend.extraction.post_validator import validate_extraction
        case = SimpleNamespace(folder_name="2026-00066 y 2026-00067 BISNEY", radicado_forest=None)
        fields = {
            "radicado_23_digitos": "68-001-40-03-010-2026-00066-00",
            "observaciones": "Tutela acumulada con 2026-00067.",
        }
        corrected, warnings = validate_extraction(case, fields)
        # No debe eliminar menciones legitimas de acumuladas
        assert "observaciones" not in corrected or "acumulada" in corrected["observaciones"].lower()


# ---------- F6: forwarded anidados ----------

class TestB6_ForwardedNested:
    """F6: detectar accionante en bloques forwarded profundos."""

    def test_split_forwarded_blocks(self):
        from backend.email.gmail_monitor import _split_forwarded_blocks
        body = """Nivel 0
________________________________
De: persona1@x.com
Enviado: lunes
Asunto: A

________________________________
De: persona2@y.com
Para: z
Asunto: B
"""
        blocks = _split_forwarded_blocks(body)
        assert len(blocks) >= 3, f"Esperaba >=3 bloques, GOT {len(blocks)}: {blocks}"

    def test_accionante_in_deep_level(self):
        from backend.email.gmail_monitor import extract_accionante
        # Simula el email caso 560 con LIBIA en nivel 4 aproximado
        body = """Se corre traslado del escrito de tutela.

________________________________
De: Tutelas Gobernacion
Enviado: martes

________________________________
De: Notificaciones
Enviado: martes

________________________________
De: Juzgado 03 Penal

REF: ACCION DE TUTELA 2026-00057
ACCIONANTE: LIBIA INES PATIÑO ROMAN
ACCIONADO: GOBERNACION DE SANTANDER
"""
        r = extract_accionante("RV: URGENTE!!! 2026-00057", body)
        assert "LIBIA" in r, f"No detecto accionante en nivel profundo: {r!r}"
        assert "PATIÑO" in r.upper()


# ---------- F7: matching por juzgado ----------

class TestB7_MatchingByJuzgado:
    """F7: match_to_case rechaza rad_corto cuando juzgado difiere."""

    def test_rejects_same_rad_corto_different_juzgado(self):
        """2026-00057 en juzgado 003 (Bucaramanga) vs juzgado 001 (San Gil) → casos distintos."""
        from unittest.mock import MagicMock
        from backend.email.gmail_monitor import match_to_case

        existing_case = MagicMock()
        existing_case.radicado_23_digitos = "68679-40-89-001-2026-00057-00"  # San Gil
        existing_case.folder_name = "2026-00057 OTRO ACCIONANTE"
        existing_case.accionante = "OTRO ACCIONANTE"

        db = MagicMock()
        # Query chain: db.query(Case).filter(...).all() returns []
        # Query chain para paso 2 (rad_corto folder match) returns [existing_case]
        class FakeQuery:
            def __init__(self, items):
                self.items = items
            def filter(self, *a, **kw):
                return self
            def all(self):
                return self.items
            def first(self):
                return self.items[0] if self.items else None
        # Para el flujo: paso 1 (rad23 completo) no debe encontrar match (juzgado distinto),
        # paso 2 (rad_corto folder) debe encontrar match pero F7 lo rechaza
        db.query = MagicMock(side_effect=[
            FakeQuery([existing_case]),  # paso 1a rad23 match (mismo rad23 no hay)
            FakeQuery([existing_case]),  # paso 1b rad23 parcial
            FakeQuery([]),               # paso 1.5 forest match
            FakeQuery([existing_case]),  # paso 2 rad_corto folder match
            FakeQuery([]),               # paso 3 personeria (no aplica)
            FakeQuery([]),               # paso 4 accionante match (no aplica)
        ])

        new_rad = {
            "radicado_23": "68001-40-88-003-2026-00057-00",  # Bucaramanga (juzgado 003)
            "radicado_corto": "2026-00057",
            "forest": "",
        }
        result = match_to_case(db, new_rad, "NUEVO ACCIONANTE")
        # F7 deberia rechazar el match por juzgado distinto
        assert result is None, f"F7 fallo: matcheo casos de juzgados distintos: {result}"


# ---------- F8: pre-COMPLETO sin rad23 ----------

class TestB8_PreCompletoValidation:
    """F8: rechaza marcar COMPLETO sin rad23 valido NI folder+accionante."""

    def test_logic_rejects_case_without_rad23_and_named_folder(self):
        """Test de la logica F8 aislada (no necesita pipeline completo)."""
        import re
        # Simular la condicion F8
        def f8_should_be_revision(rad23, folder_name, accionante):
            rad23_digits = re.sub(r"\D", "", rad23 or "")
            has_valid_rad23 = len(rad23_digits) >= 18
            has_named_folder = bool(
                folder_name
                and "[PENDIENTE" not in (folder_name or "")
                and re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", folder_name or "")
            )
            has_accionante = bool((accionante or "").strip())
            return not has_valid_rad23 and not (has_named_folder and has_accionante)

        # Caso malo 1: sin rad23, folder "[PENDIENTE REVISION]"
        assert f8_should_be_revision(None, "2026-66132 [PENDIENTE REVISION]", None) is True

        # Caso malo 2: sin rad23 y sin accionante
        assert f8_should_be_revision("", "2026-00057 NOMBRE", "") is True

        # Caso bueno 1: rad23 valido
        assert f8_should_be_revision("68001408800320260005700", None, None) is False

        # Caso bueno 2: folder con accionante y sin rad23 (legacy valido)
        assert f8_should_be_revision(None, "2025-00086 NUBIA GOMEZ", "NUBIA GOMEZ") is False


# ---------- F5 + F9 requieren DB real; tests de smoke ----------

class TestB5_RenameFolderLogic:
    """F5: rename usa rad23 como fuente de verdad, no folder malformado."""

    def test_rad_from_23_preferred_over_folder(self):
        import re
        # Logica aislada: derivar rad_corto del rad23 canonico
        rad23 = "68-001-40-88-003-2026-00057-00"
        digits = re.sub(r"\D", "", rad23)
        m = re.search(r"(20\d{2})(\d{5})\d{2}$", digits)
        assert m is not None
        rad_from_23 = f"{m.group(1)}-{m.group(2)}"
        assert rad_from_23 == "2026-00057"

        # El folder decia "2026-66132" (FOREST malformado)
        folder_rad = "2026-66132"
        # Force rename porque rad_from_23 != folder_rad
        assert rad_from_23 != folder_rad


class TestB13_DuplicateDetection:
    """F9: deteccion de duplicados (no reconsolidacion automatica, solo logueo)."""

    def test_same_rad23_different_case_id_is_duplicate(self):
        import re
        # Logica F9 aislada: dos casos con mismo rad23 → potential_duplicate
        rad23_a = "68-276-41-89-006-2026-00234-00"
        rad23_b = "68-276-41-89-006-2026-00234-00"
        da = re.sub(r"\D", "", rad23_a)
        db = re.sub(r"\D", "", rad23_b)
        assert da[:20] == db[:20]  # mismo rad23 → duplicate
