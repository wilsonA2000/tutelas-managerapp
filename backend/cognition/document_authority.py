# LEGACY v8 — pipeline cognitivo sin uso desde v9; candidato a borrado en Fase 8 (ver backend/cognition/__init__.py).
"""Document Authority — jerarquía de fuerza probatoria de documentos en tutelas.

v8.1 — Codifica el conocimiento jurídico de Wilson sobre qué documentos tienen
mayor peso para diligenciar cada campo del protocolo. Un mismo dato extraído
de fuentes distintas no tiene el mismo valor: lo dicho por el juez en el fallo
prevalece sobre lo dicho por una parte en su escrito.

Niveles de autoridad (de mayor a menor):
  Nivel 1 — JUDICIAL (proviene del juzgado, tiene fuerza vinculante)
  Nivel 2 — ADMINISTRATIVO (respuestas SED, insumos institucionales)
  Nivel 3 — PARTE_ACCIONANTE (escrito de tutela, anexos)
  Nivel 4 — APELACION_INCIDENTE (segunda instancia, incidentes — fuerza propia)
  Nivel 5 — OTRO (notificaciones, gmails sin contenido procesal)
"""
from __future__ import annotations
from enum import IntEnum


class AuthorityLevel(IntEnum):
    JUDICIAL = 1
    ADMINISTRATIVO = 2
    PARTE_ACCIONANTE = 3
    APELACION_INCIDENTE = 4
    OTRO = 5


# Mapeo doc_type → nivel de autoridad para diligenciamiento
DOC_TYPE_AUTHORITY: dict[str, AuthorityLevel] = {
    # Nivel 1 — JUDICIAL
    "AUTO_ADMISORIO": AuthorityLevel.JUDICIAL,
    "PDF_AUTO_ADMISORIO": AuthorityLevel.JUDICIAL,
    "AUTO_AVOCA": AuthorityLevel.JUDICIAL,
    "AUTO_DECRETA_PRUEBAS": AuthorityLevel.JUDICIAL,
    "AUTO_REQUERIMIENTO": AuthorityLevel.JUDICIAL,
    "AUTO": AuthorityLevel.JUDICIAL,
    "SENTENCIA": AuthorityLevel.JUDICIAL,
    "PDF_SENTENCIA": AuthorityLevel.JUDICIAL,
    "FALLO": AuthorityLevel.JUDICIAL,

    # Nivel 2 — ADMINISTRATIVO (respuesta SED, pruebas institucionales)
    "RESPUESTA_DOCX": AuthorityLevel.ADMINISTRATIVO,
    "DOCX_RESPUESTA": AuthorityLevel.ADMINISTRATIVO,
    "DOCX_CONTESTACION": AuthorityLevel.ADMINISTRATIVO,
    "DOCX_CUMPLIMIENTO": AuthorityLevel.ADMINISTRATIVO,
    "RESOLUCION_SED": AuthorityLevel.ADMINISTRATIVO,
    "INFORME_TECNICO": AuthorityLevel.ADMINISTRATIVO,

    # Nivel 3 — PARTE_ACCIONANTE
    "ESCRITO_TUTELA": AuthorityLevel.PARTE_ACCIONANTE,
    "ANEXOS_TUTELA": AuthorityLevel.PARTE_ACCIONANTE,

    # Nivel 4 — APELACION/INCIDENTE
    "PDF_IMPUGNACION": AuthorityLevel.APELACION_INCIDENTE,
    "IMPUGNACION": AuthorityLevel.APELACION_INCIDENTE,
    "INCIDENTE": AuthorityLevel.APELACION_INCIDENTE,
    "AUTO_INCIDENTE": AuthorityLevel.APELACION_INCIDENTE,
    "ESCRITO_INCIDENTE": AuthorityLevel.APELACION_INCIDENTE,
    "AUTO_SANCION": AuthorityLevel.APELACION_INCIDENTE,

    # Nivel 5 — OTRO
    "EMAIL_MD": AuthorityLevel.OTRO,
    "GMAIL": AuthorityLevel.OTRO,
    "PDF_OTRO": AuthorityLevel.OTRO,
    "DOCX_OTRO": AuthorityLevel.OTRO,
    "OTRO": AuthorityLevel.OTRO,
}


# Mapeo: campo → nivel de autoridad PREFERIDO para extraer ese campo
# Si hay docs del nivel preferido, usar esos; si no, escalar al siguiente.
FIELD_AUTHORITY_PREFERENCE: dict[str, list[AuthorityLevel]] = {
    # Campos del juzgado: prevalece JUDICIAL
    "radicado_23_digitos":  [AuthorityLevel.JUDICIAL, AuthorityLevel.PARTE_ACCIONANTE],
    "juzgado":              [AuthorityLevel.JUDICIAL, AuthorityLevel.OTRO],
    "juzgado_2nd":          [AuthorityLevel.APELACION_INCIDENTE, AuthorityLevel.JUDICIAL],
    "fecha_ingreso":        [AuthorityLevel.JUDICIAL, AuthorityLevel.PARTE_ACCIONANTE],
    "fecha_fallo_1st":      [AuthorityLevel.JUDICIAL],
    "fecha_fallo_2nd":      [AuthorityLevel.APELACION_INCIDENTE],
    "sentido_fallo_1st":    [AuthorityLevel.JUDICIAL],  # SOLO desde sentencia
    "sentido_fallo_2nd":    [AuthorityLevel.APELACION_INCIDENTE],
    "fecha_apertura_incidente": [AuthorityLevel.APELACION_INCIDENTE, AuthorityLevel.JUDICIAL],
    "decision_incidente":   [AuthorityLevel.APELACION_INCIDENTE, AuthorityLevel.JUDICIAL],
    "responsable_desacato": [AuthorityLevel.APELACION_INCIDENTE, AuthorityLevel.JUDICIAL],

    # Campos de la parte: prevalece PARTE_ACCIONANTE pero el juzgado los transcribe
    "accionante":     [AuthorityLevel.PARTE_ACCIONANTE, AuthorityLevel.JUDICIAL],
    "accionados":     [AuthorityLevel.PARTE_ACCIONANTE, AuthorityLevel.JUDICIAL],
    "vinculados":     [AuthorityLevel.JUDICIAL, AuthorityLevel.APELACION_INCIDENTE],
    "derecho_vulnerado": [AuthorityLevel.PARTE_ACCIONANTE, AuthorityLevel.JUDICIAL],
    "pretensiones":   [AuthorityLevel.PARTE_ACCIONANTE, AuthorityLevel.JUDICIAL],  # transcripción
    "asunto":         [AuthorityLevel.PARTE_ACCIONANTE, AuthorityLevel.JUDICIAL],

    # Campos administrativos
    "fecha_respuesta": [AuthorityLevel.ADMINISTRATIVO],
    "abogado_responsable": [AuthorityLevel.ADMINISTRATIVO],
    "radicado_forest": [AuthorityLevel.ADMINISTRATIVO, AuthorityLevel.JUDICIAL],

    # Campos de impugnación
    "impugnacion":    [AuthorityLevel.APELACION_INCIDENTE, AuthorityLevel.JUDICIAL],
    "quien_impugno":  [AuthorityLevel.APELACION_INCIDENTE, AuthorityLevel.JUDICIAL],
    "forest_impugnacion": [AuthorityLevel.APELACION_INCIDENTE, AuthorityLevel.ADMINISTRATIVO],
}


# Campos que requieren TRANSCRIPCIÓN LITERAL (no parafrasear)
# Hallazgo Wilson 2026-05-06: pretensiones se transcriben tal cual del escrito.
LITERAL_TRANSCRIPTION_FIELDS = frozenset({
    "pretensiones",
    "derecho_vulnerado",  # también suele citarse literalmente
})


def get_authority(doc_type: str) -> AuthorityLevel:
    """Retorna el nivel de autoridad de un doc_type. Default: OTRO."""
    return DOC_TYPE_AUTHORITY.get((doc_type or "").upper(), AuthorityLevel.OTRO)


def rank_docs_for_field(docs: list, field: str) -> list:
    """Ordena docs según preferencia de autoridad para el campo dado.

    Args:
        docs: lista de objetos Document (con atributo `doc_type`)
        field: nombre del campo a extraer

    Returns:
        lista ordenada: primero los de mayor autoridad para ese campo.
    """
    preference = FIELD_AUTHORITY_PREFERENCE.get(field, [])
    if not preference:
        return docs

    def sort_key(d):
        auth = get_authority(getattr(d, "doc_type", "OTRO"))
        try:
            idx = preference.index(auth)
            return (idx, 0)
        except ValueError:
            return (len(preference) + 1, int(auth))

    return sorted(docs, key=sort_key)


def is_literal_field(field: str) -> bool:
    """True si el campo requiere transcripción literal (no parafrasear)."""
    return field in LITERAL_TRANSCRIPTION_FIELDS
