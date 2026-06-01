"""Tests para classify_doc_type_by_content (2A — Fase 2 plan 2026-06-01)."""
import pytest
from backend.extraction.doc_ops import classify_doc_type_by_content


@pytest.mark.parametrize("filename,text,expected", [
    # Sentencia 1ra instancia
    (
        "fallo.pdf",
        "RESUELVE: PRIMERO: Se decide la acción de tutela. SEGUNDO: administrando justicia en nombre de la República.",
        "PDF_SENTENCIA",
    ),
    # Auto admisorio
    (
        "admisorio.pdf",
        "Se admite la acción de tutela interpuesta. AVÓQUESE. NOTIFÍQUESE Y CÚMPLASE. requiérase al accionado.",
        "PDF_AUTO_ADMISORIO",
    ),
    # Respuesta SED
    (
        "respuesta.pdf",
        "AL RESPONDER CITE GOBERNACIÓN DE SANTANDER. con FOREST número. Proyectó: Wilson Arguello.",
        "RESPUESTA",
    ),
    # Demanda de tutela
    (
        "demanda.pdf",
        "ACCIONANTE: María García. acudo ante usted para instaurar acción de tutela. Señor JUEZ derechos fundamentales.",
        "DEMANDA_TUTELA",
    ),
    # Incidente de desacato
    (
        "incidente.pdf",
        "incidente de desacato artículo 27 APERTURA DEL INCIDENTE se da inicio al incidente.",
        "PDF_INCIDENTE",
    ),
    # Impugnación
    (
        "impugna.pdf",
        "recurso de impugnación interpone impugnación no compartimos el fallo de primera instancia.",
        "PDF_IMPUGNACION",
    ),
    # Sentencia 2da instancia — tipo canónico SENTENCIA_2DA (no PDF_SENTENCIA_2DA)
    (
        "segunda.pdf",
        "CONFIRMA el fallo impugnado. Tribunal Superior. Conoce el despacho de la impugnación presentada.",
        "SENTENCIA_2DA",
    ),
    # Auto concede impugnación
    (
        "concede.pdf",
        "Se concede la impugnación CONCÉDASE. Remítase al Tribunal el expediente para segunda instancia.",
        "AUTO_CONCEDE_IMPUGNACION",
    ),
    # Acta de reparto
    (
        "reparto.pdf",
        "Acta individual de reparto ACTA DE REPARTO reparto No. 2026-001.",
        "ACTA_REPARTO",
    ),
    # Auto vincula
    (
        "vincula.pdf",
        "VINCULESE a la entidad accionada. se vincula a la secretaría VINCÚLESE al proceso.",
        "AUTO_VINCULA",
    ),
    # Oficio cumplimiento
    (
        "oficio.pdf",
        "En cumplimiento del fallo del Juzgado. Dando cumplimiento a la orden impartida.",
        "OFICIO_CUMPLIMIENTO",
    ),
    # Sin señales suficientes → PDF_OTRO
    (
        "desconocido.pdf",
        "Texto genérico sin señales jurídicas específicas para clasificar.",
        "PDF_OTRO",
    ),
    # Guard: acta seguimiento no es sentencia aunque tenga RESUELVE
    (
        "acta_seguimiento_fallo.pdf",
        "RESUELVE: PRIMERO: Se decide la acción de tutela administrando justicia.",
        "PDF_OTRO",
    ),
    # Guard: email markdown
    (
        "email.md",
        "De: juzgado@correo.gov.co\nPara: tutelas@santander.gov.co\nAsunto: Fallo tutela",
        "EMAIL_MD",
    ),
    # Texto vacío → PDF_OTRO
    (
        "vacio.pdf",
        "",
        "PDF_OTRO",
    ),
])
def test_classify_doc_type_by_content(filename, text, expected):
    result = classify_doc_type_by_content(filename, text)
    assert result == expected, f"{filename!r}: expected {expected!r}, got {result!r}"
