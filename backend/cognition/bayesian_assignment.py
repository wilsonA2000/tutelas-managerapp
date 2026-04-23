"""Bayesian assignment — Capa 5 del pipeline cognitivo v6.0.

Reemplaza `verify_document_belongs` rígido con inferencia probabilística.
Cada señal se modela como Likelihood Ratio (LR). El posterior se calcula vía
Bayes:

    P(pertenece | evidencia) = prior × ∏LR_i  /  (prior × ∏LR_i + (1 - prior))

La decisión final depende de umbrales DOBLES:
- posterior ≥ OK_THRESHOLD (0.92)            → OK
- posterior ≤ NEG_THRESHOLD (0.08)           → NO_PERTENECE
- en medio                                    → SOSPECHOSO con reasons_for/against explícitas

Las LRs están calibradas con muestras reales del experimento; se afinan
contra tabla de contingencia en `tests/test_bayesian_heuristics_v6.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from backend.cognition.canonical_identifiers import IdentifierSet, harvest_identifiers


# ============================================================
# Umbrales y calibración
# ============================================================

OK_THRESHOLD = 0.92
NEG_THRESHOLD = 0.08
DEFAULT_PRIOR = 0.70   # prior base: doc está en folder del caso, prior moderadamente alto


# LRs específicos (afinan por encima/debajo del lr base del identificador)
# Estos representan la fuerza adicional cuando la señal aplica "exactamente"
# al caso. Diseño: LR > 1 empuja hacia "pertenece", LR < 1 empuja a NO.
LR_RAD23_VISUAL_MATCH = 100.0              # rad23 del caso aparece en sello físico
LR_RAD23_HEADER_MATCH = 40.0
LR_RAD23_BODY_MATCH = 8.0
LR_RAD23_OTHER_CASE_IN_BODY = 0.02         # rad23 de OTRO caso en body = señal dura negativa
LR_RAD23_OTHER_CASE_IN_HEADER = 0.005       # aún más negativo si es en header
LR_RAD_CORTO_MATCH = 3.0
LR_CC_HASH_MATCH = 25.0                    # CC exacta coincide
LR_FOREST_MATCH = 15.0
LR_ABOGADO_FOOTER_MATCH = 12.0             # abogado Gobernación coincide
LR_JUZGADO_SELLO_MATCH = 10.0
LR_ACCIONANTE_NAME_MATCH_HIGH = 6.0        # fuzzy ≥ 0.85
LR_ACCIONANTE_NAME_MATCH_MEDIUM = 2.5      # fuzzy 0.65-0.85
LR_INSTITUTIONAL_HIGH = 1.8                # institutional_score > 0.5 (señal leve)
LR_THREAD_PARENT = 50.0                    # heredó case_id por email threading
LR_EMAIL_MARKDOWN = 100.0                  # email .md siempre pertenece por definición


# ============================================================
# Evidencia y veredicto
# ============================================================

@dataclass
class EvidencePoint:
    """Una señal individual con su LR aplicable."""
    name: str
    lr: float
    detail: str = ""
    pro: bool = True    # True si empuja a pertenece, False si empuja a NO_PERTENECE

    def to_dict(self) -> dict:
        return {"name": self.name, "lr": round(self.lr, 3), "pro": self.pro, "detail": self.detail}


@dataclass
class AssignmentEvidence:
    prior: float = DEFAULT_PRIOR
    signals: list[EvidencePoint] = field(default_factory=list)

    def add(self, name: str, lr: float, detail: str = "", pro: bool = True) -> None:
        self.signals.append(EvidencePoint(name=name, lr=lr, detail=detail, pro=pro))

    def posterior(self) -> float:
        """P(pertenece | evidencia) vía Bayes con LRs multiplicados."""
        p = max(min(self.prior, 0.999), 0.001)
        odds = p / (1 - p)
        for s in self.signals:
            # LRs están definidos como P(señal|pertenece) / P(señal|no_pertenece)
            # Si pro=False, el LR ya viene <1 (empuja hacia abajo); si pro=True, >1.
            lr = max(s.lr, 1e-6)
            odds *= lr
        posterior = odds / (1 + odds)
        return max(min(posterior, 1.0), 0.0)


@dataclass
class AssignmentVerdict:
    verdict: str               # OK / SOSPECHOSO / NO_PERTENECE / REVISAR
    posterior: float
    reasons_for: list[str]
    reasons_against: list[str]
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "posterior": round(self.posterior, 4),
            "reasons_for": self.reasons_for,
            "reasons_against": self.reasons_against,
            "detail": self.detail,
        }


# ============================================================
# Helpers de normalización
# ============================================================

def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def _norm_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _fuzzy_ratio(a: str, b: str) -> float:
    """Ratio muy simple de palabras compartidas, 0-1."""
    if not a or not b:
        return 0.0
    wa = set(re.findall(r"[A-ZÁÉÍÓÚÑ]{3,}", _norm_text(a)))
    wb = set(re.findall(r"[A-ZÁÉÍÓÚÑ]{3,}", _norm_text(b)))
    if not wa or not wb:
        return 0.0
    common = wa & wb
    return len(common) / max(len(wa), len(wb))


# ============================================================
# Inferencia principal
# ============================================================

def infer_assignment(case, doc_ir, doc=None) -> AssignmentVerdict:
    """Inferencia Bayesiana: ¿este doc pertenece a este caso?

    Args:
        case: SQLAlchemy Case (con radicado_23_digitos, accionante, juzgado,
              abogado_responsable, folder_name)
        doc_ir: DocumentIR del documento
        doc: SQLAlchemy Document (opcional, para heredar señales de email)
    """
    evidence = AssignmentEvidence(prior=DEFAULT_PRIOR)
    reasons_for: list[str] = []
    reasons_against: list[str] = []

    filename = (getattr(doc_ir, "filename", "") or "").strip()

    # 1) Email markdown: siempre pertenece (fue clasificado por Gmail)
    if filename.startswith("Email_") and filename.endswith(".md"):
        evidence.add("email_markdown", LR_EMAIL_MARKDOWN, detail="email .md de Gmail", pro=True)
        reasons_for.append("Email clasificado por Gmail (hilo del caso)")
        return _decide(evidence, reasons_for, reasons_against,
                       detail="Email .md siempre pertenece al caso asignado por Gmail")

    # 2) Thread parent (si el doc viene de email heredado por threading RFC 5322)
    if doc is not None and getattr(doc, "email_id", None):
        evidence.add("thread_parent", LR_THREAD_PARENT,
                     detail=f"hereda case_id por threading (email {doc.email_id})", pro=True)
        reasons_for.append("Heredó caso por threading de email RFC 5322")

    # Preparar identificadores canónicos del doc
    ids: IdentifierSet = harvest_identifiers(doc_ir)

    case_rad23 = _norm_digits(getattr(case, "radicado_23_digitos", "") or "")
    case_rad23_suffix = case_rad23[-17:] if len(case_rad23) >= 17 else ""

    # 3) RAD23 en el doc
    rads_in_doc = ids.of_kind("rad23")
    if rads_in_doc and case_rad23_suffix:
        # ¿Alguno coincide con el caso?
        matches = [r for r in rads_in_doc if case_rad23_suffix in _norm_digits(r.value)]
        others = [r for r in rads_in_doc if case_rad23_suffix not in _norm_digits(r.value)]

        for r in matches:
            if r.source_zone == "VISUAL_ROTATED":
                evidence.add("rad23_visual_match", LR_RAD23_VISUAL_MATCH,
                             detail=f"rad23 del caso en sello rotado: {r.value}")
                reasons_for.append(f"Rad23 del caso en sello físico rotado")
                break
            elif r.source_zone in ("HEADER", "RADICADO", "FOOTER_TAIL"):
                evidence.add("rad23_header_match", LR_RAD23_HEADER_MATCH,
                             detail=f"rad23 del caso en {r.source_zone}: {r.value}")
                reasons_for.append(f"Rad23 del caso en {r.source_zone}")
                break
            else:
                evidence.add("rad23_body_match", LR_RAD23_BODY_MATCH,
                             detail=f"rad23 del caso en BODY: {r.value}")
                reasons_for.append(f"Rad23 del caso mencionado en cuerpo")
                break

        # Radicado de OTRO caso en header → NO_PERTENECE fuerte
        if others:
            hard_other = [r for r in others if r.source_zone in ("HEADER", "RADICADO", "FOOTER_TAIL")]
            soft_other = [r for r in others if r.source_zone == "BODY"]
            if hard_other:
                evidence.add("rad23_other_case_header", LR_RAD23_OTHER_CASE_IN_HEADER,
                             detail=f"rad23 de otro caso en {hard_other[0].source_zone}",
                             pro=False)
                reasons_against.append(f"Rad23 de OTRO caso aparece en {hard_other[0].source_zone}")
            elif soft_other and not matches:
                # Solo penaliza si NO hay match del caso; si hay match, un rad ajeno en body es anexo
                evidence.add("rad23_other_case_body", LR_RAD23_OTHER_CASE_IN_BODY,
                             detail=f"rad23 ajeno en BODY sin match del propio",
                             pro=False)
                reasons_against.append("Rad23 de otro caso en cuerpo (sin match del propio)")

    # 4) CC del accionante del caso en el doc
    # (Necesitamos extraer las CC del caso desde case.accionante si viene con CC, o de folder)
    case_cc = _extract_cc_from_case(case)
    doc_ccs = [i.value for i in ids.of_kind("cc")]
    if case_cc and case_cc in doc_ccs:
        evidence.add("cc_match", LR_CC_HASH_MATCH, detail=f"CC {case_cc} coincide")
        reasons_for.append(f"CC del accionante ({case_cc}) coincide")

    # 5) FOREST del caso en el doc
    case_forest = _norm_digits(getattr(case, "radicado_forest", "") or "")
    if case_forest and any(_norm_digits(f.value) == case_forest for f in ids.of_kind("forest")):
        evidence.add("forest_match", LR_FOREST_MATCH, detail=f"FOREST {case_forest} coincide")
        reasons_for.append(f"FOREST del caso ({case_forest}) coincide")

    # 6) Nombre del accionante (fuzzy)
    case_accionante = getattr(case, "accionante", "") or ""
    full_text = (getattr(doc_ir, "full_text", "") or "")[:20000]
    if case_accionante and len(case_accionante) >= 8 and full_text:
        ratio = _fuzzy_ratio(case_accionante, full_text)
        if ratio >= 0.85:
            evidence.add("accionante_match_high", LR_ACCIONANTE_NAME_MATCH_HIGH,
                         detail=f"nombre accionante fuzzy={ratio:.2f}")
            reasons_for.append(f"Nombre del accionante coincide (fuzzy {ratio:.2f})")
        elif ratio >= 0.65:
            evidence.add("accionante_match_medium", LR_ACCIONANTE_NAME_MATCH_MEDIUM,
                         detail=f"nombre accionante fuzzy={ratio:.2f}")
            reasons_for.append(f"Nombre del accionante parcialmente coincide")

    # 7) Abogado del caso en FOOTER_TAIL
    case_abogado = getattr(case, "abogado_responsable", "") or ""
    if case_abogado and len(case_abogado) >= 6:
        footer_zones = [z for z in getattr(doc_ir, "zones", []) if z.zone_type in ("FOOTER", "FOOTER_TAIL")]
        footer_text = " ".join(z.text for z in footer_zones)
        if footer_text and _fuzzy_ratio(case_abogado, footer_text) >= 0.6:
            evidence.add("abogado_footer_match", LR_ABOGADO_FOOTER_MATCH,
                         detail=f"abogado {case_abogado} en footer")
            reasons_for.append(f"Abogado del caso ({case_abogado}) firma en footer")

    # 8) Sello del juzgado del caso
    case_juzgado = getattr(case, "juzgado", "") or ""
    doc_sellos_juzgado = ids.of_kind("sello_juzgado")
    if case_juzgado and doc_sellos_juzgado:
        for s in doc_sellos_juzgado:
            if _fuzzy_ratio(case_juzgado, s.value) >= 0.5:
                evidence.add("juzgado_sello_match", LR_JUZGADO_SELLO_MATCH,
                             detail=f"sello juzgado coincide en {s.source_zone}")
                reasons_for.append("Sello del juzgado coincide con el caso")
                break

    # 9) Institutional score (señal leve: doc oficial con logo y sello)
    visual_sig = getattr(doc_ir, "visual_signature", None) or {}
    inst_score = float(visual_sig.get("institutional_score") or 0.0)
    if inst_score >= 0.5 and reasons_for:
        # Solo si ya hay otras razones a favor; el score solo no decide
        evidence.add("institutional_high", LR_INSTITUTIONAL_HIGH,
                     detail=f"institutional_score={inst_score:.2f}")
        reasons_for.append(f"Doc institucional (score {inst_score:.2f})")

    return _decide(evidence, reasons_for, reasons_against)


def _extract_cc_from_case(case) -> str:
    """Extrae CC del accionante si aparece en el campo accionante o en observaciones."""
    text = " ".join([
        getattr(case, "accionante", "") or "",
        getattr(case, "observaciones", "") or "",
    ])
    from backend.agent.regex_library import CC_ACCIONANTE
    m = CC_ACCIONANTE.pattern.search(text)
    return m.group(1) if m else ""


def _decide(ev: AssignmentEvidence, reasons_for: list[str], reasons_against: list[str],
            detail: str = "") -> AssignmentVerdict:
    p = ev.posterior()
    if p >= OK_THRESHOLD:
        verdict = "OK"
    elif p <= NEG_THRESHOLD:
        verdict = "NO_PERTENECE"
    else:
        # Sin evidencia suficiente
        if not ev.signals:
            verdict = "SOSPECHOSO"
            detail = detail or "Sin señales cosechables"
        else:
            verdict = "SOSPECHOSO"
            detail = detail or f"Posterior {p:.2f} entre umbrales ({NEG_THRESHOLD}, {OK_THRESHOLD})"
    return AssignmentVerdict(
        verdict=verdict,
        posterior=p,
        reasons_for=reasons_for,
        reasons_against=reasons_against,
        detail=detail,
    )
