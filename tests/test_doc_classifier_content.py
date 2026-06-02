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
    # ── Anti-DEMANDA (2026-06-02): autos/informes que CITAN la tutela NO son la demanda.
    # Auto del incidente que cita ACCIONANTE + acción de tutela pero NO SANCIONA →
    # el marcador anula DEMANDA; gana AUTO_INCIDENTE por sus propias señales.
    (
        "027AutoNoSanciona.pdf",
        "JUZGADO PROMISCUO MUNICIPAL. ACCIONANTE: Personeria. Resolver el presente "
        "incidente de desacato sobre la accion de tutela por los derechos fundamentales. "
        "Por lo expuesto NO SANCIONA al accionado. ARCHIVESE.",
        "AUTO_INCIDENTE",
    ),
    # Informe de visita ocular que reporta el caso → PDF_OTRO (no DEMANDA_TUTELA).
    (
        "011_CAS-InformeVisitaOcular.pdf",
        "INFORME DE CUMPLIMIENTO - VISITA DE INSPECCION OCULAR. ACCIONANTE: Juan Perez. "
        "Me permito enviar informe de cumplimiento de la accion de tutela sobre los "
        "derechos fundamentales radicado 68001.",
        "PDF_OTRO",
    ),
    # Providencia que decide la tutela: DEMANDA se anula pero PDF_SENTENCIA gana solo.
    (
        "providencia.pdf",
        "ACCIONANTE: Maria. Decide de fondo la accion de tutela. En merito de lo "
        "expuesto, administrando justicia. RESUELVE: PRIMERO: SEGUNDO:",
        "PDF_SENTENCIA",
    ),
    # Regresión EXPLÍCITA: la demanda real (sin marcadores dispositivos) sigue DEMANDA.
    (
        "EscritoTutela_real.pdf",
        "ACCIONANTE: Maria Garcia. acudo ante usted para instaurar accion de tutela. "
        "Senor JUEZ derechos fundamentales.",
        "DEMANDA_TUTELA",
    ),
])
def test_classify_doc_type_by_content(filename, text, expected):
    result = classify_doc_type_by_content(filename, text)
    assert result == expected, f"{filename!r}: expected {expected!r}, got {result!r}"
