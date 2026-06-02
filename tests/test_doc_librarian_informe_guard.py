"""Test del guard anti-informe en el rescate de DEMANDA de `doc_librarian.classify`
(2026-06-02).

El rescate por estructura (doc_librarian.py:495-500) recupera escritos de tutela mal
clasificados, exigiendo apertura "SEÑOR JUEZ" + estructura ACCIONANTE/HECHOS y que NO
sea providencia/respuesta/incidente. Faltaba excluir INFORMES/OFICIOS/visita ocular:
un informe de cumplimiento que cita ACCIONANTE + "fallo de tutela" caía como
DEMANDA_TUTELA (32 docs mal rotulados). `_RE_ES_INFORME` cierra ese hueco."""
from backend.v9.doc_io import DocText
from backend.v9.doc_librarian import classify, DocType


def _doc(filename, text):
    return DocText(path="x", filename=filename, text=text, method="pymupdf")


def test_informe_visita_ocular_no_es_demanda():
    # Informe con estructura de demanda (dispara el rescate) pero es un INFORME → no DEMANDA.
    txt = (
        "SENOR JUEZ PROMISCUO MUNICIPAL. INFORME DE CUMPLIMIENTO - VISITA DE INSPECCION "
        "OCULAR. ACCIONANTE: Victor Caballero. ACCIONADO: Municipio de San Andres. "
        "HECHOS: en cumplimiento del fallo de tutela me permito enviar informe de la "
        "visita ocular practicada. PRETENSION: verificar el cumplimiento."
    )
    assert classify(_doc("011_InformeVisitaOcular.pdf", txt)).doc_type != DocType.DEMANDA_TUTELA


def test_demanda_real_sigue_siendo_demanda():
    # Regresión: el escrito real del accionante sigue rescatándose como DEMANDA_TUTELA.
    txt = (
        "SENOR JUEZ CONSTITUCIONAL (REPARTO). ACCIONANTE: Maria Garcia. ACCIONADO: SED. "
        "HECHOS: En mi calidad de madre interpongo la presente accion de tutela. "
        "PRETENSIONES: tutelar el derecho fundamental."
    )
    assert classify(_doc("EscritoTutela.pdf", txt)).doc_type == DocType.DEMANDA_TUTELA
