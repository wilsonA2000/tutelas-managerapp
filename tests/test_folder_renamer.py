"""Tests F2.1: folder_renamer (sanitización + needs_rename + clean_accionante).

Cubre el bug del caso 203 (accionante "SOL MILENA PEREZ DELGADO\\nACCIONADO"
que producía folder con \\n literal en disco).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.cognition.folder_renamer import (
    build_target_name,
    clean_accionante,
    is_likely_real_name,
    needs_rename,
    rename_folder_if_needed,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()


# ---------- clean_accionante ----------

class TestCleanAccionante:
    def test_strip_newline_and_role_token(self):
        # bug del caso 203
        assert clean_accionante("SOL MILENA PEREZ DELGADO\nACCIONADO") == "SOL MILENA PEREZ DELGADO"

    def test_strip_carriage_return(self):
        assert clean_accionante("JUAN PEREZ\r\nACCIONADO") == "JUAN PEREZ"

    def test_strip_tab(self):
        assert clean_accionante("MARIA LOPEZ\tDEMANDADO") == "MARIA LOPEZ"

    def test_strip_trailing_role_with_punctuation(self):
        assert clean_accionante("ANA GOMEZ\nACCIONADO,") == "ANA GOMEZ"

    def test_strip_leading_role(self):
        assert clean_accionante("ACCIONANTE: PEDRO RAMIREZ") == "PEDRO RAMIREZ"

    def test_clean_already_clean(self):
        assert clean_accionante("JUANA PEREZ MARTINEZ") == "JUANA PEREZ MARTINEZ"

    def test_empty_returns_empty(self):
        assert clean_accionante("") == ""
        assert clean_accionante(None) == ""

    def test_collapses_extra_whitespace(self):
        assert clean_accionante("  JUAN   PEREZ  ") == "JUAN PEREZ"

    # FIX 2.2: trailing cuts (frases procesales después del nombre)
    def test_cut_en_calidad_de(self):
        # caso 117 real
        assert clean_accionante("FABRIZIO ENRIQUE MANOSALVA VALLEJO en calidad de representante") \
            == "FABRIZIO ENRIQUE MANOSALVA VALLEJO"

    def test_cut_obrando_en_nombre(self):
        # caso 153 real
        assert clean_accionante("SHAIRA YURLEY HERNANDEZ CHAVEZ obrando en nombre propio") \
            == "SHAIRA YURLEY HERNANDEZ CHAVEZ"

    def test_cut_en_representacion(self):
        # caso 202 real (con tilde)
        assert clean_accionante("MIGUEL COGARIA HERRERA en representación de HCM") \
            == "MIGUEL COGARIA HERRERA"

    def test_cut_actuando_como(self):
        assert clean_accionante("ANA LOPEZ actuando como apoderada") == "ANA LOPEZ"

    def test_cut_identificado_con(self):
        assert clean_accionante("PEDRO MARTINEZ identificado con cédula 12345") == "PEDRO MARTINEZ"

    def test_cut_mayor_de_edad(self):
        assert clean_accionante("LUISA GOMEZ mayor de edad y vecina de Bucaramanga") == "LUISA GOMEZ"

    def test_cut_with_cedula(self):
        assert clean_accionante("CARLOS RUIZ con cédula 1098765432") == "CARLOS RUIZ"

    def test_cut_case_insensitive(self):
        assert clean_accionante("MARIA TORRES EN CALIDAD DE TUTORA") == "MARIA TORRES"

    # FIX 8.1 — preposición trailing (truncamiento NER)
    def test_trim_trailing_en(self):
        assert clean_accionante("YOLIMA KATHERINE QUIMBAYA SOCHA en") == "YOLIMA KATHERINE QUIMBAYA SOCHA"

    def test_trim_trailing_de(self):
        assert clean_accionante("ANA LOPEZ de") == "ANA LOPEZ"

    def test_trim_trailing_y(self):
        assert clean_accionante("PEDRO MARTINEZ y") == "PEDRO MARTINEZ"

    def test_trim_recursive_preps(self):
        # Múltiples preposiciones colgadas
        assert clean_accionante("CARLOS RUIZ en de") == "CARLOS RUIZ"

    # FIX 8.2 — frases procesales típicas de respuestas
    def test_cut_dando_cumplimiento(self):
        # casos 58, 65 reales
        assert clean_accionante("RUTH QUIJANO GARCES DANDO CUMPLIMIENTO A FALLO DE TUTELA") \
            == "RUTH QUIJANO GARCES"

    def test_cut_derecho_peticion(self):
        assert clean_accionante("JUAN PEREZ DERECHO DE PETICIÓN") == "JUAN PEREZ"

    def test_cut_dar_respuesta(self):
        assert clean_accionante("MARIA LOPEZ dar respuesta a la solicitud") == "MARIA LOPEZ"

    def test_cut_con_cc_punctuation(self):
        # caso 181 / patrón narrativo: "MARTHA con C.C. 91"
        assert clean_accionante("MARTHA ANDREA QUITIAN PINEDA con C.C. 91.154.169") \
            == "MARTHA ANDREA QUITIAN PINEDA"


# ---------- needs_rename ----------

class TestNeedsRename:
    def test_pendiente_marker(self):
        assert needs_rename("2026-00050 [PENDIENTE REVISION]")

    def test_revisar_marker(self):
        assert needs_rename("2026-00050 [REVISAR_ACCIONANTE]")

    def test_dirty_newline(self):
        # caso 203: folder con \n literal
        assert needs_rename("2026-00122 SOL MILENA PEREZ DELGADO\nACCIONADO")

    def test_dirty_tab(self):
        assert needs_rename("2026-00099 NAME\tEXTRA")

    def test_clean_folder_no_rename(self):
        assert not needs_rename("2026-00050 JUANA PEREZ MARTINEZ")

    def test_empty_no_rename(self):
        assert not needs_rename("")
        assert not needs_rename(None)


# ---------- is_likely_real_name (regresión) ----------

class TestIsLikelyRealName:
    def test_real_name_passes(self):
        assert is_likely_real_name("JUANA PEREZ MARTINEZ")

    def test_with_role_token_now_handled_upstream(self):
        # is_likely_real_name por sí sola no rechaza ACCIONADO al final
        # (el sanitize lo hace antes); no debe romper el caso ya limpio
        assert is_likely_real_name("JUANA PEREZ MARTINEZ")

    def test_phrase_rejected(self):
        assert not is_likely_real_name("PRETENDE QUE SE ORDENE")


# ---------- build_target_name ----------

class TestBuildTargetName:
    def test_dirty_accionante_produces_clean_target(self, db):
        c = Case(
            folder_name="2026-00122 SOL MILENA PEREZ DELGADO\nACCIONADO",
            folder_path="/tmp/x/2026-00122 SOL MILENA PEREZ DELGADO\nACCIONADO",
            processing_status="COMPLETO",
            accionante="SOL MILENA PEREZ DELGADO\nACCIONADO",
        )
        db.add(c)
        db.commit()
        target = build_target_name(c)
        assert target is not None
        new_name, is_clean = target
        assert is_clean is True
        assert "\n" not in new_name
        assert new_name == "2026-00122 SOL MILENA PEREZ DELGADO"

    def test_pendiente_falls_back_to_revisar(self, db):
        c = Case(
            folder_name="2026-00050 [PENDIENTE REVISION]",
            folder_path="/tmp/x/2026-00050 [PENDIENTE REVISION]",
            processing_status="COMPLETO",
            accionante="PRETENDE",
        )
        db.add(c)
        db.commit()
        new_name, is_clean = build_target_name(c)
        assert is_clean is False
        assert "[REVISAR_ACCIONANTE]" in new_name


# ---------- rename_folder_if_needed (integración DB) ----------

class TestRenameFolderIfNeeded:
    def test_rename_dirty_folder_updates_db(self, db, tmp_path):
        # Carpeta física con \n literal en el nombre — la creamos como segmentos
        # para evitar issues de filesystem (en Windows fallaría).
        old_name = "2026-00122 SOL MILENA PEREZ DELGADO_ACCIONADO_LITERAL"
        old_dir = tmp_path / old_name
        old_dir.mkdir()
        c = Case(
            folder_name="2026-00122 SOL MILENA PEREZ DELGADO\nACCIONADO",
            folder_path=str(old_dir),  # path real sin \n para que rename funcione
            processing_status="COMPLETO",
            accionante="SOL MILENA PEREZ DELGADO\nACCIONADO",
        )
        db.add(c)
        db.commit()
        result = rename_folder_if_needed(db, c, base_dir=tmp_path)
        assert result["action"] == "renamed"
        assert "\n" not in c.folder_name
        assert c.folder_name == "2026-00122 SOL MILENA PEREZ DELGADO"

    def test_idempotent(self, db, tmp_path):
        c = Case(
            folder_name="2026-00050 JUANA PEREZ MARTINEZ",
            folder_path=str(tmp_path / "2026-00050 JUANA PEREZ MARTINEZ"),
            processing_status="COMPLETO",
            accionante="JUANA PEREZ MARTINEZ",
        )
        db.add(c)
        db.commit()
        r1 = rename_folder_if_needed(db, c, base_dir=tmp_path)
        r2 = rename_folder_if_needed(db, c, base_dir=tmp_path)
        assert r1["action"] == "skipped"
        assert r2["action"] == "skipped"

    def test_revisar_accionante_no_change_when_no_better_data(self, db, tmp_path):
        old_dir = tmp_path / "2026-00050 [REVISAR_ACCIONANTE]"
        old_dir.mkdir()
        c = Case(
            folder_name="2026-00050 [REVISAR_ACCIONANTE]",
            folder_path=str(old_dir),
            processing_status="COMPLETO",
            accionante="PRETENDE",
        )
        db.add(c)
        db.commit()
        result = rename_folder_if_needed(db, c, base_dir=tmp_path)
        assert result["action"] == "skipped"
