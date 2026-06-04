"""Guard: la remisión/envío del expediente a la Corte Constitucional para eventual
revisión NO es una sentencia de 2ª (ni 1ª) instancia (2026-06-04).

Bug: "09EnvioCorte.pdf" (email del juzgado remitiendo a la Corte) caía en SENTENCIA_2DA
→ cascada: impugnacion=SI falsa + fecha_fallo_2nd (la fecha del envío) + el LLM llenaba
quien_impugno. El guard en doc_librarian._disambiguate lo enruta a NOTIFICACION_FALLO,
con doble condición para NO tocar sentencias reales (que sí remiten 'para eventual
revisión' DENTRO de su RESUELVE)."""
from backend.v9.doc_io import DocText
from backend.v9.doc_librarian import classify, DocType


def _doc(filename, text):
    return DocText(path="x", filename=filename, text=text, method="pymupdf")


def test_envio_a_corte_no_es_sentencia_2da():
    # El email/oficio que solo REMITE a la Corte para eventual revisión → NO sentencia.
    txt = (
        "Envío expediente de tutela número 68572310300120260004100 a Corte Constitucional. "
        "Usted envió 4 archivos correspondientes al expediente de tutela para su eventual "
        "revisión por parte de la Corte Constitucional. Fecha Envío 16 de abril de 2026."
    )
    dt = classify(_doc("09EnvioCorte.pdf", txt)).doc_type
    assert dt != DocType.SENTENCIA_2DA, f"remisión a Corte no debe ser SENTENCIA_2DA (fue {dt})"
    assert dt != DocType.SENTENCIA_1RA


def test_sentencia_real_que_remite_a_corte_sigue_siendo_sentencia():
    # Una sentencia REAL termina remitiendo "para eventual revisión" DENTRO de su RESUELVE.
    # La doble guardia (sin dispositiva real) NO debe degradarla.
    txt = (
        "JUZGADO PRIMERO CIVIL. SENTENCIA. ACCIÓN DE TUTELA. En mérito de lo expuesto, "
        "administrando justicia, RESUELVE: PRIMERO: TUTELAR el derecho fundamental a la "
        "educación. SEGUNDO: ORDENAR a la SED el reintegro. TERCERO: Para su eventual "
        "revisión, REMÍTASE el expediente a la Corte Constitucional."
    )
    dt = classify(_doc("06SentenciaTutela.pdf", txt)).doc_type
    assert dt in (DocType.SENTENCIA_1RA, DocType.SENTENCIA_2DA), \
        f"una sentencia real con RESUELVE no debe degradarse (fue {dt})"
