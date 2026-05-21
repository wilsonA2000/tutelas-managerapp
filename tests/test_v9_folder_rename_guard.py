"""Guard del auto-rename de v9 (pipeline paso 9).

El hook de extract_case solo debe renombrar carpetas que sean placeholders
generados por la ingesta/monitor (SIN_ACCIONANTE, [PENDIENTE, [REVISAR_ACCIONANTE]).
NUNCA debe tocar notas humanas de revisión (ej. la nota de conflación de c400
"[REVISAR — JUZGADO 68547 CASO DINY-WILMER]"), aunque la heurística de needs_rename
las marcaría como "folder sucio".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.v9.pipeline import _folder_is_auto_placeholder
from backend.cognition.folder_renamer import needs_rename


class TestAutoPlaceholderGuard:
    def test_sin_accionante_is_placeholder(self):
        assert _folder_is_auto_placeholder("2026-00167 SIN ACCIONANTE")
        assert _folder_is_auto_placeholder("2025-00055 SIN_ACCIONANTE")

    def test_pendiente_is_placeholder(self):
        assert _folder_is_auto_placeholder("2026-00343 [PENDIENTE REVISION]")

    def test_revisar_accionante_is_placeholder(self):
        assert _folder_is_auto_placeholder("2026-00050 [REVISAR_ACCIONANTE]")

    def test_clean_folder_not_placeholder(self):
        assert not _folder_is_auto_placeholder("2026-00045 MAURICIO GIL PENA")

    def test_human_review_note_not_placeholder(self):
        # c400: nota humana de conflación — debe respetarse, NO renombrarse.
        nota = "2026-00041 [REVISAR — JUZGADO 68547 CASO DINY-WILMER]"
        assert not _folder_is_auto_placeholder(nota)

    def test_guard_protects_what_heuristic_would_flag(self):
        # Documenta POR QUÉ existe el guard: needs_rename SÍ marcaría la nota de c400
        # como renombrable (contiene "JUZGADO", trap word, y hay accionante real),
        # pero el guard del pipeline lo impide.
        nota = "2026-00041 [REVISAR — JUZGADO 68547 CASO DINY-WILMER]"
        accionante = "WILMER GALLARDO AVENDAÑO"
        assert needs_rename(nota, accionante) is True          # la heurística lo marcaría
        assert _folder_is_auto_placeholder(nota) is False      # el guard lo protege
