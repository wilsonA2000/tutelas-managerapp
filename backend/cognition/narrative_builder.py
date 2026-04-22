"""Narrative builder: genera ASUNTO, PRETENSIONES, OBSERVACIONES,
DERECHO_VULNERADO por plantillas determinísticas a partir de datos extraídos.

Reemplaza al ~80-90% de las llamadas a IA que hoy hacen estos campos. Solo
casos con texto narrativo muy ambiguo (escrito no-estándar, tutelas atípicas)
caen al fallback IA.
"""

from __future__ import annotations

import re
from typing import Any

from backend.cognition.cie10_to_derecho import infer_derechos_from_dx
from backend.cognition.decision_extractor import Decision
from backend.cognition.entity_extractor import ActorSet


def build_derecho_vulnerado(full_text: str, existing: str = "") -> str:
    """Genera lista 'DERECHO1 - DERECHO2 - ...' ordenada por frecuencia/peso.

    Si `existing` (de regex anterior) contiene valores, los fusiona sin duplicar.
    """
    from_text = infer_derechos_from_dx(full_text)
    existing_list = [d.strip() for d in re.split(r"\s*-\s*", existing) if d.strip()] if existing else []
    combined: list[str] = []
    seen: set[str] = set()
    for d in existing_list + from_text:
        key = d.upper()
        if key not in seen:
            seen.add(key)
            combined.append(d.upper())
    return " - ".join(combined)


def _primary_accionado(actors: ActorSet) -> str:
    if actors.accionados:
        # Preferir Secretaría de Educación si aparece (accionado principal típico)
        for a in actors.accionados:
            if "EDUCACI" in a.name.upper():
                return a.name
        return actors.accionados[0].name
    return ""


def _minor_refs(actors: ActorSet) -> str:
    if not actors.menores:
        return ""
    names = [a.name for a in actors.menores[:2]]
    return " y ".join(names)


def build_asunto(
    actors: ActorSet,
    derecho_vulnerado: str,
    full_text: str,
    max_chars: int = 180,
) -> str:
    """Construye un ASUNTO conciso: 'Solicita X por vulneración a Y'."""
    accionante = actors.accionantes[0].name if actors.accionantes else "Accionante"
    accionado = _primary_accionado(actors) or "entidad accionada"

    # Detectar el verbo/acción principal (ordenados por especificidad)
    # Expandido desde catálogo: 43× 'acción de', 39× 'solicitud de',
    # 14× 'docente solicita', 12× 'solicita traslado', 7× 'incidente de'
    action_patterns: list[tuple[re.Pattern, str]] = [
        (re.compile(r"\bincidente\s+de\s+desacato\b", re.IGNORECASE), "Incidente de desacato"),
        (re.compile(r"\btraslado\s+docente\b|traslado\s+de\s+docente", re.IGNORECASE), "Solicita traslado docente"),
        (re.compile(r"\bnombramiento\s+(?:de\s+)?docente|nombramiento\s+(?:en\s+)?propiedad", re.IGNORECASE), "Solicita nombramiento de docente"),
        (re.compile(r"\breintegr(?:o|ar)\b|reintegro\s+laboral", re.IGNORECASE), "Solicita reintegro laboral"),
        (re.compile(r"\bpae\b|programa\s+de\s+alimentaci[oó]n\s+escolar|alimentaci[oó]n\s+escolar", re.IGNORECASE), "Solicita garantía de alimentación escolar (PAE)"),
        (re.compile(r"\btransporte\s+escolar\b", re.IGNORECASE), "Solicita transporte escolar"),
        (re.compile(r"\bdocente\s+de\s+apoyo\b|profesional\s+de\s+apoyo\s+pedag[oó]gico", re.IGNORECASE), "Solicita docente de apoyo pedagógico"),
        (re.compile(r"\bmatr[íi]cula\b|\bcupo\s+escolar\b|\bcupo\s+estudiantil\b", re.IGNORECASE), "Solicita cupo o matrícula escolar"),
        (re.compile(r"\bpago\s+de\s+(?:pensi[oó]n|prestaciones|cesant[íi]as|salarios?)\b", re.IGNORECASE), "Solicita pago de prestaciones"),
        (re.compile(r"\btratamiento\s+m[eé]dico\b|\bcirug[íi]a\b|\bmedicamento\b|\bprocedimiento\s+m[eé]dico\b", re.IGNORECASE), "Solicita tratamiento/medicamento"),
        (re.compile(r"\brespuesta\s+a\s+petici[oó]n\b|\bderecho\s+de\s+petici[oó]n\b|\bpetici[oó]n\s+sin\s+resolver\b", re.IGNORECASE), "Solicita respuesta a petición"),
        (re.compile(r"\bunidad\s+familiar\b|reunificaci[oó]n\s+familiar", re.IGNORECASE), "Solicita protección a unidad familiar"),
        (re.compile(r"\bdiscapacidad\b|\binclusi[oó]n\s+educativa\b|\beducaci[oó]n\s+inclusiva\b", re.IGNORECASE), "Solicita educación inclusiva por discapacidad"),
        (re.compile(r"\basignaci[oó]n\s+de\s+(?:docente|personal)\b", re.IGNORECASE), "Solicita asignación de docente/personal"),
        (re.compile(r"\bamenazas?\b|\bseguridad\s+personal\b", re.IGNORECASE), "Traslado por amenazas/seguridad personal"),
    ]
    action = ""
    for pat, fallback in action_patterns:
        if pat.search(full_text):
            action = fallback
            break
    # Fallback v5.3.3: si patrones fallan, intentar semantic matching con spaCy
    if not action:
        try:
            from backend.cognition.semantic_matcher import classify_pretension
            match = classify_pretension(full_text, threshold=0.70)
            if match:
                label, _score = match
                action = {
                    "traslado_docente": "Solicita traslado docente",
                    "nombramiento_docente": "Solicita nombramiento de docente",
                    "docente_apoyo": "Solicita docente de apoyo pedagógico",
                    "reintegro_laboral": "Solicita reintegro laboral",
                    "pago_prestaciones": "Solicita pago de prestaciones",
                    "tratamiento_medico": "Solicita tratamiento/medicamento",
                    "transporte_escolar": "Solicita transporte escolar",
                    "alimentacion_escolar": "Solicita garantía de alimentación escolar (PAE)",
                    "cupo_matricula": "Solicita cupo o matrícula escolar",
                    "respuesta_peticion": "Solicita respuesta a petición",
                    "proteccion_menor": "Solicita protección de derechos del menor",
                    "unidad_familiar": "Solicita protección a unidad familiar",
                }.get(label, "")
        except Exception:
            pass
    if not action:
        # Fallback genérico basado en primer derecho
        primary = derecho_vulnerado.split(" - ")[0] if derecho_vulnerado else "derechos fundamentales"
        action = f"Tutela por vulneración a {primary}"

    menor_note = ""
    if actors.menores:
        menor_note = f" en favor de {_minor_refs(actors)}"

    asunto = f"{action}{menor_note}."
    if len(asunto) > max_chars:
        asunto = asunto[: max_chars - 3] + "..."
    return asunto


def build_pretensiones(
    actors: ActorSet,
    derecho_vulnerado: str,
    full_text: str,
    asunto: str = "",
) -> str:
    """Construye PRETENSIONES en 1-3 líneas desde la acción detectada."""
    accionado = _primary_accionado(actors) or "la entidad accionada"

    # Buscar el verbo "solicita/ordenar" y la oración siguiente
    m = re.search(
        r"(?:solicit[ao]\b|pido\b|pretend[eo]\b|ordenar\b|disponer\b|se\s+ordene)\s+"
        r"([^.]{20,220}[\.\,])",
        full_text,
        re.IGNORECASE,
    )
    extracted = m.group(1).strip() if m else ""

    if extracted:
        return f"Que se {extracted.rstrip(',.')}."

    # Fallback: inferir desde el asunto/derecho
    if "traslado docente" in asunto.lower():
        return "Que se ordene el traslado del docente a la institución solicitada."
    if "nombramiento" in asunto.lower():
        return f"Que se ordene al {accionado} realizar el nombramiento del docente."
    if "reintegro" in asunto.lower():
        return "Que se ordene el reintegro al cargo y el pago de salarios dejados de percibir."
    if "petici[oó]n" in asunto.lower() or "petición" in asunto.lower():
        return "Que se ordene responder de fondo el derecho de petición dentro del término legal."
    primary = derecho_vulnerado.split(" - ")[0] if derecho_vulnerado else "los derechos invocados"
    return f"Que se amparen {primary.lower()} y se ordene al {accionado} las medidas conducentes."


def build_observaciones(
    actors: ActorSet,
    derecho_vulnerado: str,
    decision: Decision | None,
    case_meta: dict[str, Any],
    events: list[dict] | None = None,
    documents: list[dict] | None = None,
    max_chars: int = 1000,
) -> str:
    """Construye OBSERVACIONES narrativas con cronología.

    Args:
        case_meta: dict con fecha_ingreso, radicado_23_digitos, radicado_forest, etc.
        events: lista opcional pre-computada de {"date", "event"}.
        documents: si se pasa, se extrae timeline automáticamente desde los docs.
    """
    # Si no se pasan events explícitos pero sí documents, construir timeline
    if not events and documents:
        try:
            from backend.cognition.timeline_builder import extract_timeline
            tl = extract_timeline(documents, max_events=5)
            events = [{"date": e.date_str, "event": e.event} for e in tl]
        except Exception:
            events = None
    accionante = actors.accionantes[0].name if actors.accionantes else "El accionante"
    accionado = _primary_accionado(actors) or "la entidad accionada"
    derechos = derecho_vulnerado or "derechos fundamentales invocados"
    minor = _minor_refs(actors)

    lines: list[str] = []

    # Encabezado narrativo
    fecha_ing = case_meta.get("fecha_ingreso", "")
    rad = case_meta.get("radicado_23_digitos", "")
    rad_suffix = f" (radicado {rad})" if rad else ""
    ing_prefix = f"El {fecha_ing}, " if fecha_ing else ""
    por_menor = f" en nombre de {minor}" if minor else ""

    lines.append(
        f"{ing_prefix}{accionante}{por_menor} interpuso acción de tutela contra {accionado}{rad_suffix}, "
        f"alegando la vulneración de {derechos.lower()}."
    )

    # FOREST si existe
    forest = case_meta.get("radicado_forest", "")
    if forest:
        abogado = case_meta.get("abogado_responsable", "")
        abg_note = f" gestionada por {abogado}" if abogado else ""
        lines.append(f"El caso recibió radicado interno FOREST {forest}{abg_note}.")

    # Decisión primera instancia
    if decision and decision.sentido:
        date = decision.fecha or "fecha no determinada"
        lines.append(f"Mediante fallo del {date}, se {decision.sentido.lower()} la tutela.")
        if decision.impugnacion == "SI":
            qi = decision.quien_impugno or "una de las partes"
            lines.append(f"Posteriormente, {qi.lower()} impugnó el fallo.")
        if decision.segunda_instancia:
            fs = decision.fecha_segunda or "fecha no determinada"
            lines.append(f"La segunda instancia ({fs}) {decision.segunda_instancia.lower()} el fallo.")

    # Eventos adicionales
    if events:
        for ev in events[:4]:
            date = ev.get("date", "")
            e = ev.get("event", "")
            if e:
                lines.append(f"{date}: {e}.".lstrip(": "))

    # Desacatos
    incidente = case_meta.get("incidente", "")
    if incidente == "SI":
        lines.append("Se promovió incidente de desacato.")

    text = " ".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 3] + "..."
    return text
