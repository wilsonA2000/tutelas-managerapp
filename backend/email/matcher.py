"""Matcher multi-criterio del monitor Gmail (v5.4.4).

Reemplaza `match_to_case()` del monitor (7 pasos secuenciales, primer match gana)
por un scoring multi-criterio que considera TODAS las señales disponibles y
devuelve confianza graduada.

Principio (análogo a `verify_document_belongs` del pipeline principal):
    Nunca decidir por una sola señal. Sumar evidencia de múltiples fuentes
    (threading de conversación, rad23, FOREST, CC, rad_corto, nombre).
    El umbral determina si el match es automático, ambiguo (quarantine) o
    debe crear caso nuevo.

Scoring (total 0-205, el threshold es relativo):
    Thread parent (In-Reply-To match a email ya procesado):  +70   (auto-match)
    rad23 canónico exacto en KB:                              +70   (auto-match; 23d = ID único nacional)
    FOREST exacto + remitente tutelas@santander.gov.co:       +50   (FOREST = ID interno de correspondencia, único)
    FOREST exacto con otro remitente:                         +20
    CC hash match en pii_mappings:                            +20
    rad_corto + juzgado_code coincidentes:                    +30   (year:seq:juzgado = casi único)
    rad_corto sin juzgado:                                    +12
    Similaridad de nombre accionante (difflib):               +10   (0-10 gradual)

Umbrales:
    ≥70   HIGH    — auto-match, escribir case_id
    40-69 MEDIUM  — ambiguo, marcar email.status='AMBIGUO' con case sugerido
    <40   LOW     — crear caso nuevo (si hay rad_corto) o quarantine

v6.0.1 (2026-04-23): rad23 y forest_verified elevados a peso auto-match.
    Justificación empírica: en 1,211 emails barridos, 244 quedaron AMBIGUO con
    rad23 exacto (score=55-65). rad23 es ID nacional único (imposible colisión).
    FOREST desde tutelas@santander.gov.co idem (ID interno único).
"""

from __future__ import annotations

import difflib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Optional

from backend.email.case_lookup_cache import CaseLookupCache
from backend.email.rad_utils import juzgado_code, normalize_rad23, same_juzgado

logger = logging.getLogger("tutelas.matcher")

# El desempate LLM de candidatos MEDIUM vive ahora en backend/email/llm_adjudicator.py
# (adjudicate_assignment). Aquí solo se invoca en el dead-end determinista.


@dataclass
class EmailSignals:
    """Señales extraídas del email por forensic_analyzer."""

    rad23: str = ""
    rad_corto: str = ""
    forest: str = ""
    cc_accionante: str = ""
    accionante_name: str = ""
    sender: str = ""
    thread_parent_case_id: Optional[int] = None  # resuelto antes del matcher
    # rad23 leído del PATH del link de expediente OneDrive del juzgado
    # (expediente_links/expediente_fetcher). Es la estructura de archivo del
    # propio despacho — corrige typos del subject (caso real e2038).
    rad23_url: str = ""

    def has_any(self) -> bool:
        return bool(self.rad23 or self.rad_corto or self.forest or self.cc_accionante
                    or self.thread_parent_case_id or self.rad23_url)


@dataclass
class MatchResult:
    case_id: Optional[int]
    score: int
    confidence: str  # HIGH / MEDIUM / LOW / NONE
    breakdown: dict = field(default_factory=dict)
    alternatives: list[tuple[int, int]] = field(default_factory=list)  # [(case_id, score)]

    def to_signals_json(self) -> str:
        return json.dumps({
            "score": self.score,
            "confidence": self.confidence,
            "breakdown": self.breakdown,
            "alternatives": self.alternatives,
        })

    @property
    def is_auto_match(self) -> bool:
        return self.case_id is not None and self.score >= 70


# ─────────────────────────────────────────────────────────────
# Pesos y umbrales
# ─────────────────────────────────────────────────────────────

WEIGHT_THREAD_PARENT = 70
WEIGHT_RAD23 = 70
# rad23 del PATH del link de expediente (OneDrive del juzgado): tan confiable
# como el rad23 del cuerpo (es el archivo del propio despacho) e inmune a
# typos del subject. El lookup difuso tolera typo en el prefijo DANE.
WEIGHT_RAD23_URL = 70
WEIGHT_FOREST_VERIFIED_SENDER = 50
WEIGHT_FOREST_GENERIC = 20
WEIGHT_CC = 20
WEIGHT_RAD_CORTO_JUZGADO = 30
WEIGHT_RAD_CORTO_SIN_JUZGADO = 12
WEIGHT_NAME_MAX = 10

THRESHOLD_HIGH = 70
THRESHOLD_MEDIUM = 40

_TUTELAS_SANDER_SENDER = "tutelas@santander.gov.co"


def _name_similarity(name_a: str, name_b: str) -> int:
    """Similaridad difflib 0-10 (mapeo de 0.0-1.0 a entero). Solo si ambos nombres son largos."""
    if not name_a or not name_b or len(name_a) < 6 or len(name_b) < 6:
        return 0
    ratio = difflib.SequenceMatcher(None, name_a.upper(), name_b.upper()).ratio()
    # Mínimo 0.7 para dar puntos (por debajo no es match)
    if ratio < 0.7:
        return 0
    return int(round((ratio - 0.7) / 0.3 * WEIGHT_NAME_MAX))


def _get_case_accionante(db, case_id: int) -> str:
    from backend.database.models import Case
    c = db.query(Case.accionante).filter(Case.id == case_id).first()
    return c[0] if c and c[0] else ""


def _get_case_rad23(db, case_id: int) -> str:
    from backend.database.models import Case
    c = db.query(Case.radicado_23_digitos).filter(Case.id == case_id).first()
    return c[0] if c and c[0] else ""


# ─────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────


def score_case_match(
    db,
    cache: CaseLookupCache,
    signals: EmailSignals,
) -> MatchResult:
    """Evalúa a qué caso pertenece un email según múltiples señales.

    Args:
        db: Session de SQLAlchemy (para lookups auxiliares como accionante del caso)
        cache: CaseLookupCache ya construido
        signals: señales extraídas del email (forensic_analyzer output)

    Returns:
        MatchResult con case_id recomendado (o None), score 0-160, breakdown.
    """
    # Candidatos: { case_id: {"score": int, "signals": dict} }
    candidates: dict[int, dict] = {}

    def _add_signal(case_id: int, signal_name: str, weight: int) -> None:
        entry = candidates.setdefault(case_id, {"score": 0, "signals": {}})
        entry["score"] += weight
        entry["signals"][signal_name] = weight

    # ── 1. Thread parent (fortísimo) ──
    if signals.thread_parent_case_id:
        _add_signal(signals.thread_parent_case_id, "thread_parent", WEIGHT_THREAD_PARENT)

    # ── 2. Lookups O(1) en cache ──
    hits = cache.lookup_all(
        rad23=signals.rad23,
        rad_corto=signals.rad_corto,
        forest=signals.forest,
        cc=signals.cc_accionante,
    )

    if cid := hits.get("rad23"):
        _add_signal(cid, "rad23", WEIGHT_RAD23)

    # ── 2b. rad23 del link de expediente (OneDrive del juzgado) ──
    if signals.rad23_url:
        cid_url = cache.lookup_by_rad23(signals.rad23_url)
        if cid_url:
            _add_signal(cid_url, "rad23_url", WEIGHT_RAD23_URL)
        else:
            # typo en el prefijo DANE del path del juzgado (caso real 69432→68432):
            # sufijo [5:21] único entre los casos = misma identidad.
            cid_url = cache.lookup_by_rad23_suffix(signals.rad23_url)
            if cid_url:
                _add_signal(cid_url, "rad23_url_suffix", WEIGHT_RAD23_URL)
                logger.info(
                    "rad23_url %s no exacto en KB pero sufijo[5:21] único → case %d "
                    "(typo de prefijo DANE en el path del juzgado)",
                    signals.rad23_url, cid_url,
                )

    if cid := hits.get("forest"):
        sender_lower = (signals.sender or "").lower()
        if _TUTELAS_SANDER_SENDER in sender_lower:
            _add_signal(cid, "forest_verified_sender", WEIGHT_FOREST_VERIFIED_SENDER)
        else:
            _add_signal(cid, "forest_generic", WEIGHT_FOREST_GENERIC)

    if cid := hits.get("cc"):
        _add_signal(cid, "cc_hash", WEIGHT_CC)

    if rc_winner := hits.get("rad_corto"):
        # El rad_corto (AAAA-NNNNN) NO es globalmente único: cada juzgado lleva su
        # propia secuencia, así que varios casos de municipios distintos pueden
        # compartirlo (p.ej. 2026-00015 en San Andrés/Oiba/Betulia). Desambiguar
        # SIEMPRE por municipio (juzgado_code) — nunca volcar al primero del bucket.
        #
        # FIX (2026-05-28): si email TRAE rad23 explícito pero NO matchea ningún
        # case en KB, NO usar rad_corto en absoluto. Razón: el rad23 indica el
        # juzgado real del proceso. Si no hay case con ese rad23, el rad_corto
        # coincidente seguro es de OTRO juzgado (conflación garantizada).
        # Esto refuerza la regla "rad23 es identidad de tutela".
        if signals.rad23 and len(signals.rad23) >= 12 and not hits.get("rad23"):
            logger.info(
                "rad_corto %s: email TRAE rad23 (%s) pero ningún case en KB lo match — "
                "NO uso rad_corto para evitar conflación cross-juzgado",
                signals.rad_corto, signals.rad23,
            )
            rc_candidates = set()  # vacío → bypasea todo el bloque
        else:
            rc_candidates = cache.rad_corto_candidates(signals.rad_corto) or {rc_winner}
        email_juzgado = juzgado_code(signals.rad23)  # "" si rad23 ausente/corto (<12d)
        if email_juzgado:
            # El caso correcto es el del MISMO juzgado que el rad23 del email.
            same = [cid for cid in rc_candidates if cache.juzgado_of(cid) == email_juzgado]
            if len(same) == 1:
                _add_signal(same[0], "rad_corto_juzgado", WEIGHT_RAD_CORTO_JUZGADO)
            elif not same:
                # Ningún caso con ese rad_corto es del juzgado del email → otro
                # municipio. NO sumar (la identidad real está en otro lado / es nuevo).
                logger.info(
                    "rad_corto %s: ningún caso es del juzgado %s del email (candidatos=%s) → no asigno",
                    signals.rad_corto, email_juzgado, sorted(rc_candidates),
                )
            # len(same) > 1: dos casos mismo juzgado + mismo rad_corto = duplicado real;
            # no forzamos — que decidan rad23 exacto / thread / revisión.
        else:
            # Email SIN rad23 usable: solo asignar por rad_corto si NO es ambiguo
            # entre municipios. Si el rad_corto lo comparten ≥2 casos (o ≥2 juzgados),
            # NO auto-asignar — esto es lo que causaba la conflación (volcar al primero).
            distinct_juzgados = {cache.juzgado_of(cid) for cid in rc_candidates if cache.juzgado_of(cid)}
            if len(rc_candidates) <= 1 and len(distinct_juzgados) <= 1:
                _add_signal(rc_winner, "rad_corto", WEIGHT_RAD_CORTO_SIN_JUZGADO)
            else:
                logger.warning(
                    "rad_corto %s AMBIGUO (%d casos, %d juzgados) y email sin rad23 → "
                    "no auto-asigno, queda para revisión: candidatos=%s",
                    signals.rad_corto, len(rc_candidates), len(distinct_juzgados), sorted(rc_candidates),
                )

    # ── 3. Similaridad de nombre del accionante (para candidatos ya identificados) ──
    if signals.accionante_name:
        for cid in list(candidates.keys()):
            case_acc = _get_case_accionante(db, cid)
            sim_score = _name_similarity(signals.accionante_name, case_acc)
            if sim_score > 0:
                _add_signal(cid, "name_similarity", sim_score)

    # ── 4. Seleccionar ganador ──
    if not candidates:
        return MatchResult(case_id=None, score=0, confidence="NONE", breakdown={})

    ranked = sorted(candidates.items(), key=lambda kv: -kv[1]["score"])
    winner_id, winner = ranked[0]
    score = winner["score"]

    if score >= THRESHOLD_HIGH:
        confidence = "HIGH"
    elif score >= THRESHOLD_MEDIUM:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # ── 4.5 Guard de conflicto de radicado (#3.4) ──
    # Si el email trae un rad EXPLÍCITO que identifica un caso DISTINTO del
    # ganador, y el ganador NO ganó por una señal autoritativa (rad23 exacto o
    # thread de conversación), NO auto-asignar: degradar a MEDIUM para revisión.
    # Previene que forest/CC/nombre de OTRO caso le ganen al rad del subject
    # (conflación silenciosa). Solo afecta auto-matches (HIGH); degradar a MEDIUM
    # es seguro (el email queda para revisión, nunca se asigna al caso equivocado).
    if confidence == "HIGH" and (signals.rad23 or signals.rad_corto):
        rad_case = hits.get("rad23") or hits.get("rad_corto")
        won_authoritative = "rad23" in winner["signals"] or "thread_parent" in winner["signals"]
        if rad_case and rad_case != winner_id and not won_authoritative:
            confidence = "MEDIUM"
            winner["signals"]["rad_conflict_downgrade"] = f"rad->{rad_case}!=ganador{winner_id}"
            logger.warning(
                "Guard conflicto rad (#3.4): el rad del email apunta al caso %s pero "
                "ganó %s por señales no-autoritativas %s → MEDIUM (revisión)",
                rad_case, winner_id, list(winner["signals"].keys()),
            )

    # ── 3C: Qwen 4B confirmación de MEDIUM ──
    # Si quedamos en MEDIUM con pocos candidatos y Qwen está activo, preguntarle SOLO
    # para CONFIRMAR al ganador determinista (nunca para cambiarlo: el scoring por
    # señales — rad23/FOREST/juzgado — manda, ese es el guard anti-conflación).
    # Si Qwen confirma al mismo ganador → promover a auto-match subiendo el score a 70
    # (is_auto_match keya en score>=70, no en confidence; si solo subiéramos confidence
    # el email caería entre las dos ramas del monitor y terminaría creando un duplicado).
    # DeepSeek (adjudicador) desempata: si CONFIRMA el ganador con alta confianza → HIGH
    # (auto-resuelve). Si elige OTRO candidato / es NUEVO / ambiguo → se queda MEDIUM
    # (revisión humana) y se loguea la recomendación razonada en match_signals_json.
    # Nunca falla el flujo (adjudicador abstención-segura) ni crea casos aquí.
    from backend.email import llm_adjudicator as _adj
    if confidence == "MEDIUM" and 1 <= len(ranked) <= 3 and _adj.llm_on():
        cand_ids = [cid for cid, _ in ranked[:3]]
        verdict = _adj.adjudicate_assignment(db, signals, cand_ids, cache=cache)
        winner["signals"]["llm_adjudication"] = verdict.as_dict()
        if verdict.is_confident and verdict.decision == winner_id:
            confidence = "HIGH"
            score = max(score, THRESHOLD_HIGH)  # garantiza is_auto_match → True
            winner["signals"]["llm_confirmed"] = 1
        elif verdict.is_confident and isinstance(verdict.decision, int) and verdict.decision in cand_ids:
            # DeepSeek confiado en OTRO candidato → NO auto-asignar aquí (anti-conflación):
            # se queda MEDIUM con la recomendación; el monitor/humano decide.
            winner["signals"]["llm_disagreed"] = verdict.decision

    alternatives = [(cid, data["score"]) for cid, data in ranked[1:4]]

    return MatchResult(
        case_id=winner_id,
        score=score,
        confidence=confidence,
        breakdown=winner["signals"],
        alternatives=alternatives,
    )


# ─────────────────────────────────────────────────────────────
# Resolver thread parent
# ─────────────────────────────────────────────────────────────


def resolve_thread_parent(db, in_reply_to: str, references: str) -> Optional[int]:
    """Busca el case_id del email padre por In-Reply-To o References header.

    Returns: case_id del email padre, o None si no hay match.
    """
    from backend.database.models import Email
    import re as _re

    raw_ids: list[str] = []
    if in_reply_to:
        raw_ids.append(in_reply_to.strip())
    if references:
        # References es una cadena de <id1> <id2> ... separados por espacio
        raw_ids.extend(_re.findall(r"<[^>]+>|[^\s]+", references))

    # Generar variantes con y sin brackets para tolerar cómo se guardó en DB
    msg_ids: list[str] = []
    for mid in raw_ids:
        stripped = mid.strip().strip("<>")
        if not stripped:
            continue
        msg_ids.append(stripped)
        msg_ids.append(f"<{stripped}>")

    if not msg_ids:
        return None

    # Buscar el email padre que tenga case_id
    parents = db.query(Email.case_id).filter(
        Email.message_id.in_(msg_ids),
        Email.case_id.isnot(None),
    ).all()

    if not parents:
        return None
    # Si hay múltiples padres en la cadena, tomar el primer case_id no-nulo
    return parents[0][0]
