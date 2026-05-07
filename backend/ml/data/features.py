"""Feature extraction: caso → vector listo para sklearn.

Combina:
- Features estructuradas (bool/int/categóricas) extraídas del caso
- Texto concatenado (zonas IR + observaciones) para TF-IDF

Diseño: fit_transform(historical_cases) y predict(case_features).
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class CaseFeatures:
    """Features de un caso para training/inference.

    Diseño: cada attr puede ser None si no está disponible.
    """
    # ID
    case_id: int | None = None

    # Numéricas estructuradas
    n_docs: int = 0
    n_emails: int = 0
    fecha_year: int = 2026
    fecha_month: int = 0
    accionados_count: int = 0

    # Booleans (presencia de tipos de doc)
    has_doc_admisorio: bool = False
    has_doc_sentencia: bool = False
    has_doc_impugnacion: bool = False
    has_doc_desacato: bool = False
    has_docx_respuesta: bool = False
    has_docx_contestacion: bool = False

    # Booleans (juzgado)
    juzgado_es_civil: bool = False
    juzgado_es_penal: bool = False
    juzgado_es_promiscuo: bool = False
    juzgado_es_laboral: bool = False
    juzgado_es_administrativo: bool = False

    # Booleans (accionados)
    has_min_educacion: bool = False
    has_sec_santander: bool = False
    has_eps: bool = False
    has_municipio: bool = False

    # Texto (input para TF-IDF)
    text_tema: str = ""              # del Excel histórico (tema_raw / tema_normalized)
    text_observaciones: str = ""     # del Excel + cognición V6
    text_asunto: str = ""            # extraído por cognitive_fill
    text_pretensiones: str = ""
    text_full_truncated: str = ""    # primeros 4000 chars del IR


def _detect_juzgado_kind(juzgado: str) -> dict:
    j = (juzgado or "").upper()
    return {
        "civil": "CIVIL" in j,
        "penal": "PENAL" in j,
        "promiscuo": "PROMISCUO" in j,
        "laboral": "LABORAL" in j,
        "administrativo": "ADMINIST" in j,
    }


def _detect_accionados(accionados: str) -> dict:
    a = (accionados or "").upper()
    return {
        "min_educacion": "MINISTERIO" in a and "EDUCACI" in a,
        "sec_santander": ("SECRETAR" in a and "EDUCACI" in a) or "SED" in a,
        "eps": "EPS" in a or "ENTIDAD PROMOTORA" in a,
        "municipio": "MUNICIPIO" in a or "ALCALDIA" in a or "ALCALDÍA" in a,
    }


def _parse_year_from(value) -> int:
    if not value:
        return 2026
    s = str(value)
    m = re.search(r"(20\d{2})", s)
    return int(m.group(1)) if m else 2026


def features_from_case_orm(case, n_docs: int = 0, n_emails: int = 0) -> CaseFeatures:
    """Extrae features de un objeto Case SQLAlchemy."""
    juz_kind = _detect_juzgado_kind(case.juzgado or "")
    acc_kind = _detect_accionados(case.accionados or "")

    return CaseFeatures(
        case_id=case.id,
        n_docs=n_docs,
        n_emails=n_emails,
        fecha_year=_parse_year_from(case.fecha_ingreso),
        accionados_count=len((case.accionados or "").split(" - ")) if case.accionados else 0,
        juzgado_es_civil=juz_kind["civil"],
        juzgado_es_penal=juz_kind["penal"],
        juzgado_es_promiscuo=juz_kind["promiscuo"],
        juzgado_es_laboral=juz_kind["laboral"],
        juzgado_es_administrativo=juz_kind["administrativo"],
        has_min_educacion=acc_kind["min_educacion"],
        has_sec_santander=acc_kind["sec_santander"],
        has_eps=acc_kind["eps"],
        has_municipio=acc_kind["municipio"],
        text_asunto=(case.asunto or "")[:1000],
        text_pretensiones=(case.pretensiones or "")[:1000],
        text_observaciones=(case.observaciones or "")[:2000],
    )


def features_from_historical(hc) -> CaseFeatures:
    """Extrae features de un objeto HistoricalCase (training del Excel)."""
    return CaseFeatures(
        case_id=hc.id,
        fecha_year=hc.fecha.year if hc.fecha else _parse_year_from(hc.fecha_raw),
        text_tema=(hc.tema_raw or "")[:500],
        text_observaciones=(hc.observaciones or "")[:2000],
    )


def features_to_dict(feats: CaseFeatures) -> dict:
    """Convierte CaseFeatures a dict (para sklearn ColumnTransformer)."""
    return {
        "n_docs": feats.n_docs,
        "n_emails": feats.n_emails,
        "fecha_year": feats.fecha_year,
        "fecha_month": feats.fecha_month,
        "accionados_count": feats.accionados_count,
        "has_doc_admisorio": int(feats.has_doc_admisorio),
        "has_doc_sentencia": int(feats.has_doc_sentencia),
        "has_doc_impugnacion": int(feats.has_doc_impugnacion),
        "has_doc_desacato": int(feats.has_doc_desacato),
        "has_docx_respuesta": int(feats.has_docx_respuesta),
        "has_docx_contestacion": int(feats.has_docx_contestacion),
        "juzgado_es_civil": int(feats.juzgado_es_civil),
        "juzgado_es_penal": int(feats.juzgado_es_penal),
        "juzgado_es_promiscuo": int(feats.juzgado_es_promiscuo),
        "juzgado_es_laboral": int(feats.juzgado_es_laboral),
        "juzgado_es_administrativo": int(feats.juzgado_es_administrativo),
        "has_min_educacion": int(feats.has_min_educacion),
        "has_sec_santander": int(feats.has_sec_santander),
        "has_eps": int(feats.has_eps),
        "has_municipio": int(feats.has_municipio),
        "text_tema": feats.text_tema or "",
        "text_observaciones": feats.text_observaciones or "",
        "text_asunto": feats.text_asunto or "",
        "text_pretensiones": feats.text_pretensiones or "",
        "text_full_truncated": feats.text_full_truncated or "",
    }


# Lista de columnas numéricas y de texto (para sklearn ColumnTransformer)
NUMERIC_COLS = [
    "n_docs", "n_emails", "fecha_year", "fecha_month", "accionados_count",
    "has_doc_admisorio", "has_doc_sentencia", "has_doc_impugnacion",
    "has_doc_desacato", "has_docx_respuesta", "has_docx_contestacion",
    "juzgado_es_civil", "juzgado_es_penal", "juzgado_es_promiscuo",
    "juzgado_es_laboral", "juzgado_es_administrativo",
    "has_min_educacion", "has_sec_santander", "has_eps", "has_municipio",
]

TEXT_COLS = [
    "text_tema", "text_observaciones", "text_asunto",
    "text_pretensiones", "text_full_truncated",
]
