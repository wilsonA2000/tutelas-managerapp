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
from dataclasses import asdict, dataclass, field
from typing import Optional

from backend.email.case_lookup_cache import CaseLookupCache
from backend.email.rad_utils import juzgado_code, normalize_rad23, same_juzgado

logger = logging.getLogger("tutelas.matcher")


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

    def has_any(self) -> bool:
        return bool(self.rad23 or self.rad_corto or self.forest or self.cc_accionante or self.thread_parent_case_id)


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

    if cid := hits.get("forest"):
        sender_lower = (signals.sender or "").lower()
        if _TUTELAS_SANDER_SENDER in sender_lower:
            _add_signal(cid, "forest_verified_sender", WEIGHT_FOREST_VERIFIED_SENDER)
        else:
            _add_signal(cid, "forest_generic", WEIGHT_FOREST_GENERIC)

    if cid := hits.get("cc"):
        _add_signal(cid, "cc_hash", WEIGHT_CC)

    if cid := hits.get("rad_corto"):
        # Verificar consistencia de juzgado (F7): si el email tiene rad23 y el caso
        # también, los juzgado_code deben coincidir. Si el rad_corto matchea pero
        # juzgados difieren → es otro caso con mismo year:seq (raro pero posible).
        if signals.rad23:
            case_rad23 = _get_case_rad23(db, cid)
            if case_rad23 and not same_juzgado(signals.rad23, case_rad23):
                logger.info(
                    "F7 rechazo rad_corto match: email rad23=%s case %d rad23=%s",
                    signals.rad23[:20], cid, case_rad23[:20],
                )
                # NO sumar score — es un falso match por homonimia year:seq
            else:
                _add_signal(cid, "rad_corto_juzgado", WEIGHT_RAD_CORTO_JUZGADO)
        else:
            # Sin rad23 en email, peso menor (no podemos verificar juzgado)
            _add_signal(cid, "rad_corto", WEIGHT_RAD_CORTO_SIN_JUZGADO)

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
