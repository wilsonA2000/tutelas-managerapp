# LEGACY v8 — pipeline cognitivo sin uso desde v9; candidato a borrado en Fase 8 (ver backend/cognition/__init__.py).
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
    """Genera lista 'DERECHO1 - DERECHO2 - ...' por relevancia (top-3).

    v6.1.1 fix regresión: el algoritmo anterior unía TODOS los derechos
    matched, produciendo el mismo string en cada caso (porque casi todas
    las tutelas mencionan docente+EPS+transporte). Ahora cuenta cuántas
    KEYWORD_DERECHOS patterns matchean en el texto y devuelve top-3.
    """
    from collections import Counter
    from backend.cognition.cie10_to_derecho import (
        KEYWORD_DERECHOS, CIE10_FAMILY_DERECHOS, _extract_cie10_codes,
        _normalize_derecho,
    )

    counts: Counter[str] = Counter()

    # Peso 3: CIE-10 codes explícitos (señal médica fuerte)
    for code in _extract_cie10_codes(full_text.upper()):
        if code in CIE10_FAMILY_DERECHOS:
            for d in CIE10_FAMILY_DERECHOS[code]:
                counts[_normalize_derecho(d)] += 3

    # Peso 1: por cada match de keyword pattern, sumar 1 a cada derecho asociado
    for pat, derechos in KEYWORD_DERECHOS:
        n_matches = len(pat.findall(full_text))
        if n_matches:
            for d in derechos:
                counts[_normalize_derecho(d)] += n_matches

    top = [d for d, _ in counts.most_common(3)]

    existing_list = [
        d.strip().upper() for d in re.split(r"\s*-\s*", existing) if d and d.strip()
    ] if existing else []
    combined: list[str] = []
    seen: set[str] = set()
    for d in existing_list + top:
        if d not in seen:
            seen.add(d)
            combined.append(d)
        if len(combined) >= 5:
            break
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


PRETENSIONES_HEADER_PATTERN = re.compile(
    r"\b(?:PRETENSIONES|PETICIONES|SOLICITUDES|II?\s*[\.\)]\s*PRETENSIONES|"
    r"EN\s+CONSECUENCIA(?:\s+SOLICITO)?)\b\s*[:.\-]?",
    re.IGNORECASE,
)

# Headers que típicamente cierran la sección de pretensiones
PRETENSIONES_END_PATTERN = re.compile(
    r"\b(?:HECHOS|ANTECEDENTES|FUNDAMENTOS\s+DE\s+DERECHO|FUNDAMENTOS\s+JUR[IÍ]DICOS|"
    r"PRUEBAS|JURAMENTO|NOTIFICACIONES|ANEXOS|COMPETENCIA|MEDIDA\s+PROVISIONAL|"
    r"DERECHO[S]?\s+VULNERAD|MARCO\s+CONSTITUCIONAL|VI?\s*[\.\)]\s*HECHOS)\b",
    re.IGNORECASE,
)

# v9.4.3: cortar el full_text antes de la sección de RESPUESTA/CONTESTACIÓN
# del accionado para evitar capturar SUS pretensiones (que son defensa,
# no las del accionante). Caso real bug #1: caso #1 capturó "Que se declare
# la improcedencia de las pretensiones" — eso era la respuesta SED.
RESPUESTA_ACCIONADO_PATTERN = re.compile(
    r"\b(?:RESPUESTA\s+A\s+LA\s+ACCI[OÓ]N|CONTESTACI[OÓ]N\s+A\s+LA\s+TUTELA|"
    r"OPOSICI[OÓ]N\s+A\s+LA\s+TUTELA|EN\s+RESPUESTA\s+A\s+LA\s+ACCI[OÓ]N|"
    r"DEFENSA\s+DE\s+LA\s+ACCIONADA|"
    r"improcedencia\s+de\s+las\s+pretensiones|"
    r"se\s+rechac[ee]n?\s+las\s+pretensiones|"
    r"se\s+nieguen?\s+las\s+pretensiones|"
    r"sea\s+desestimada\s+la\s+acci[oó]n)\b",
    re.IGNORECASE,
)

PRETENSIONES_MAX_CHARS = 4000


def _strip_respuesta_accionado(full_text: str) -> str:
    """v9.4.3: trunca el texto en el primer header de RESPUESTA del accionado.

    Esto evita que build_pretensiones capture la sección PRETENSIONES de la
    contestación del accionado (donde el accionado pide 'declarar improcedentes'
    las pretensiones del accionante).
    """
    if not full_text:
        return full_text
    m = RESPUESTA_ACCIONADO_PATTERN.search(full_text)
    if m:
        return full_text[:m.start()]
    return full_text


def build_pretensiones(
    actors: ActorSet,
    derecho_vulnerado: str,
    full_text: str,
    asunto: str = "",
) -> str:
    """Construye PRETENSIONES en modo VERBATIM (v9.4).

    Wilson explícitamente requirió: "las pretensiones deben ser transcritas tal
    cual, no resumidas, no parafraseadas". Por eso esta función YA NO genera
    paráfrasis ni plantillas. Solo localiza la sección 'PRETENSIONES' del
    escrito de tutela y la copia literal hasta el siguiente header.

    Si no se encuentra la sección de pretensiones, retorna cadena vacía
    (no inventa). El campo se rellenará después por la capa Qwen
    (target=pretensiones_verbatim) o queda en blanco para revisión humana.

    Args:
      actors: ActorSet (no usado en VERBATIM, mantenido por compat de firma)
      derecho_vulnerado: ídem
      full_text: texto completo del expediente (escrito tutela + otros)
      asunto: ídem

    Returns:
      str con las pretensiones literales (máx 4000 chars) o "" si no se halla.
    """
    if not full_text:
        return ""

    # v9.4.3: cortar antes de la sección de respuesta del accionado para no
    # capturar SUS pretensiones de defensa.
    text = _strip_respuesta_accionado(full_text)

    # Localizar primer header "PRETENSIONES" o equivalente en el escrito de tutela
    m_start = PRETENSIONES_HEADER_PATTERN.search(text)
    if not m_start:
        return ""  # honestidad: sin sección clara, mejor vacío que inventar
    full_text = text  # reasignar para el resto de la función

    start_idx = m_start.end()
    tail = full_text[start_idx:]

    # Localizar el siguiente header que cierre la sección
    m_end = PRETENSIONES_END_PATTERN.search(tail)
    end_idx_tail = m_end.start() if m_end else min(len(tail), PRETENSIONES_MAX_CHARS)

    bloque = tail[:end_idx_tail].strip()

    # Limpieza mínima: quitar saltos múltiples consecutivos pero preservar
    # los saltos que separan numeración (1., 2., 3., PRIMERA, SEGUNDA…).
    bloque = re.sub(r"\n{3,}", "\n\n", bloque)
    bloque = re.sub(r"[ \t]+", " ", bloque)
    bloque = bloque.strip(" .:;-\n")

    # Si el bloque es demasiado corto (<30 chars) probablemente la captura falló
    if len(bloque) < 30:
        return ""

    # Truncar a max sin cortar palabra
    if len(bloque) > PRETENSIONES_MAX_CHARS:
        cut = bloque[:PRETENSIONES_MAX_CHARS]
        last_space = cut.rfind(" ")
        if last_space > PRETENSIONES_MAX_CHARS - 200:
            cut = cut[:last_space]
        bloque = cut.rstrip(" .,;:") + "…"

    return bloque


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
