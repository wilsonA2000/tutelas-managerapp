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
LR_RAD23_OTHER_CASE_IN_HEADER = 0.02       # v8.0: ajustado a 0.02 (compromiso entre 0.005 original
                                           # y 0.05 de v6.1.1 que era demasiado lax). Sigue marcando
                                           # SOSPECHOSO casos con rad23 ajeno en header pero sin
                                           # ser tan duro como antes.
LR_RAD_CORTO_MATCH = 3.0
LR_CC_HASH_MATCH = 25.0                    # CC exacta coincide
LR_FOREST_MATCH = 15.0
LR_ABOGADO_FOOTER_MATCH = 12.0             # abogado Gobernación coincide
LR_JUZGADO_SELLO_MATCH = 10.0
LR_ACCIONANTE_NAME_MATCH_HIGH = 6.0        # fuzzy ≥ 0.85
LR_ACCIONANTE_NAME_MATCH_MEDIUM = 2.5      # fuzzy 0.65-0.85
LR_INSTITUTIONAL_HIGH = 1.8                # institutional_score > 0.5 (señal leve)
LR_THREAD_PARENT = 150.0                   # v6.1.1: subido de 50→150 — threading RFC 5322 con
                                           # In-Reply-To es señal MUY fuerte (la oficina jurídica
                                           # reenvía en hilos coherentes); evita falsos SOSPECHOSO
LR_EMAIL_MARKDOWN = 100.0                  # email .md siempre pertenece por definición

# v6.0.16 — señales cognitivas extraídas de Claude ground truth (data/claude_ground_truth.jsonl)
LR_FILENAME_HAS_CASE_RAD23 = 200.0         # filename literal contiene rad23 EXACTO del caso (override fuerte)
LR_FILENAME_HAS_CASE_RAD_CORTO = 25.0      # filename literal contiene rad_corto del caso
LR_FILENAME_HAS_ACCIONANTE = 12.0          # filename contiene ≥2 apellidos del accionante
LR_TEXT_RAD_CORTO_AND_ACCIONANTE = 30.0    # texto tiene rad_corto del caso Y accionante fuzzy ≥ 0.6
LR_TUTELA_INICIAL_PRE_RAD = 8.0            # doc_type tutela y accionante exacto sin rad23 (escrito inicial)
LR_FILENAME_HAS_OTHER_CASE_RAD23 = 0.005   # filename apunta a OTRO caso conocido en DB (señal MUY negativa)
LR_FILENAME_HAS_OTHER_CASE_RAD_CORTO = 0.10  # rad_corto en filename apunta a otro case (moderada)

# v6.0.17 — corroboración por expediente y pre-radicación incidente
LR_CASE_CORROBORATED = 4.5                 # ≥3 hermanos OK con rad23 confirmado del case
                                           # y doc actual no tiene rad ajeno → contexto valida pertenencia
LR_INCIDENTE_INICIAL_PRE_RAD = 6.0         # pre-radicación de incidente (filename con "incidente"/"desacato")


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
    # v6.0.16 — destino sugerido cuando verdict=NO_PERTENECE/SOSPECHOSO con target identificado
    target_case_id: int | None = None
    target_evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "posterior": round(self.posterior, 4),
            "reasons_for": self.reasons_for,
            "reasons_against": self.reasons_against,
            "detail": self.detail,
            "target_case_id": self.target_case_id,
            "target_evidence": self.target_evidence,
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


def _name_coverage(name: str, text: str) -> float:
    """Cobertura: qué fracción de las palabras significativas del nombre aparecen en text.
    Útil para detectar mención de accionante en textos largos donde _fuzzy_ratio falla.
    """
    if not name or not text:
        return 0.0
    name_words = _significant_name_words(name)
    if not name_words:
        return 0.0
    text_norm = _norm_text(text)
    matches = sum(1 for w in name_words if w in text_norm)
    return matches / len(name_words)


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
    # v6.0.16: comparar IGNORANDO sufijo de etapa procesal (00/01/02 = misma tutela).
    # Tomar año+consecutivo+despacho (12 dígitos antes de los últimos 2 del rad23).
    case_rad23_core = case_rad23[-14:-2] if len(case_rad23) >= 14 else ""

    def _rad_matches_case(rad_value: str) -> bool:
        rn = _norm_digits(rad_value)
        if not case_rad23_core or len(rn) < 14:
            return False
        return rn[-14:-2] == case_rad23_core

    # 3) RAD23 en el doc
    rads_in_doc = ids.of_kind("rad23")
    if rads_in_doc and case_rad23_core:
        matches = [r for r in rads_in_doc if _rad_matches_case(r.value)]
        others = [r for r in rads_in_doc if not _rad_matches_case(r.value)]

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

    # =========================================================
    # v6.0.16 — Reglas cognitivas (Claude ground truth + cache cross-DB)
    # =========================================================
    target_case_id, target_evidence = _apply_cognitive_rules(
        case, doc_ir, ids, evidence, reasons_for, reasons_against,
    )

    verdict = _decide(evidence, reasons_for, reasons_against)
    if target_case_id is not None:
        verdict.target_case_id = target_case_id
        verdict.target_evidence = target_evidence
    return verdict


def _apply_cognitive_rules(case, doc_ir, ids: IdentifierSet,
                            evidence: AssignmentEvidence,
                            reasons_for: list[str],
                            reasons_against: list[str]) -> tuple[int | None, str]:
    """v6.0.16 — Aplica las 7 reglas cognitivas extraídas del ground truth de Claude.

    Returns: (target_case_id, evidence_str) si se identificó destino claro.
    """
    filename = (getattr(doc_ir, "filename", "") or "").strip()
    full_text = (getattr(doc_ir, "full_text", "") or "")
    accionante = (getattr(case, "accionante", "") or "")
    case_rad23_norm = _norm_digits(getattr(case, "radicado_23_digitos", "") or "")
    case_folder = (getattr(case, "folder_name", "") or "")

    # Derivar rad_corto del caso (AAAA-NNNNN)
    case_rad_corto = _derive_rad_corto(case_rad23_norm) or _extract_rad_corto_from_string(case_folder)

    fn_digits = _norm_digits(filename)
    fn_norm = _norm_text(filename)

    # ---- R3: filename contiene rad23 EXACTO del caso ----
    if case_rad23_norm and len(case_rad23_norm) >= 18 and case_rad23_norm[:20] in fn_digits:
        evidence.add("filename_case_rad23", LR_FILENAME_HAS_CASE_RAD23,
                     detail=f"rad23 case en filename: {case_rad23_norm[:20]}")
        reasons_for.append("Filename contiene rad23 EXACTO del caso")

    # ---- R3b: filename contiene rad_corto EXACTO del caso ----
    if case_rad_corto:
        # Buscar AAAA-NNNNN o AAAANNNNN en filename
        cr_year, cr_seq = case_rad_corto.split("-")
        if (case_rad_corto in filename
                or case_rad_corto in fn_norm
                or f"{cr_year}{cr_seq}" in fn_digits):
            evidence.add("filename_case_rad_corto", LR_FILENAME_HAS_CASE_RAD_CORTO,
                         detail=f"rad_corto case en filename: {case_rad_corto}")
            reasons_for.append(f"Filename contiene rad_corto del caso ({case_rad_corto})")

    # ---- R1: filename contiene apellidos del accionante (≥2 palabras) ----
    if accionante:
        acc_words = _significant_name_words(accionante)
        if len(acc_words) >= 2:
            matches = sum(1 for w in acc_words[:4] if w in fn_norm)
            if matches >= 2:
                evidence.add("filename_accionante", LR_FILENAME_HAS_ACCIONANTE,
                             detail=f"{matches} apellidos del accionante en filename")
                reasons_for.append("Filename contiene apellidos del accionante")
            elif matches == 1 and len(filename) > 8:
                # 1 apellido es indicio leve, no se penaliza pero no premia tanto
                pass

    # ---- R2: texto contiene rad_corto + accionante (LR moderado) ----
    if case_rad_corto and full_text:
        text_norm = _norm_text(full_text[:20000])
        rad_corto_in_text = (case_rad_corto in text_norm
                              or case_rad_corto.replace("-", "") in _norm_digits(full_text[:20000]))
        if rad_corto_in_text:
            acc_cov = _name_coverage(accionante, full_text[:20000])
            if acc_cov >= 0.5:
                evidence.add("text_rad_corto_and_accionante", LR_TEXT_RAD_CORTO_AND_ACCIONANTE,
                             detail=f"rad_corto + accionante (cov {acc_cov:.2f}) en texto")
                reasons_for.append("Texto menciona rad_corto del caso + accionante")

    # ---- R7: tutela inicial pre-radicación con accionante exacto ----
    doc_type = (getattr(doc_ir, "doc_type", "") or "").upper()
    fn_upper = filename.upper()
    is_likely_tutela = (
        doc_type in ("TUTELA", "PDF_TUTELA", "ESCRITO_TUTELA", "DOCX_TUTELA")
        or "TUTELA" in fn_upper or "ESCRITO" in fn_upper
    )
    if is_likely_tutela and accionante and full_text:
        cov = _name_coverage(accionante, full_text[:8000])
        if cov >= 0.5 and not ids.has("rad23"):
            evidence.add("tutela_inicial_pre_rad", LR_TUTELA_INICIAL_PRE_RAD,
                         detail=f"escrito sin rad23, accionante coverage {cov:.2f}")
            reasons_for.append("Escrito de tutela con accionante del caso (pre-radicación)")

    # ---- R11: pre-radicación incidente/desacato ----
    is_likely_incidente = (
        doc_type in ("INCIDENTE", "PDF_INCIDENTE", "ESCRITO_INCIDENTE", "DESACATO")
        or "INCIDENTE" in fn_upper or "DESACATO" in fn_upper
    )
    if is_likely_incidente and accionante and full_text and not ids.has("rad23"):
        cov = _name_coverage(accionante, full_text[:8000])
        if cov >= 0.4:  # umbral más laxo: incidentes a veces solo dicen "el accionante"
            evidence.add("incidente_pre_rad", LR_INCIDENTE_INICIAL_PRE_RAD,
                         detail=f"incidente sin rad23, accionante coverage {cov:.2f}")
            reasons_for.append("Escrito de incidente/desacato con accionante (pre-radicación)")

    # ---- R5/R6: cross-DB lookup vía CaseLookupCache (target_case_id) ----
    # Refinamientos v6.0.16+:
    #  - Si el filename contiene rad23 EXACTO del case → BLOQUEAR target_case_id
    #    (rad anterior en texto es del mismo proceso, no caso ajeno).
    #  - Validar que target tenga al menos UNA señal coherente (rad23 exacto
    #    o accionante en filename) antes de proponerlo.
    target_case_id = None
    target_evidence = ""

    # Comparar rad23 completo (23 dígitos) — no truncar a 20, porque
    # el consecutivo está en posición 21+ y casos del mismo juzgado/año
    # comparten primeros 20 dígitos.
    def _same_rad23(a: str, b: str) -> bool:
        """Compara dos rad23 considerando que sólo difieren en sufijo de etapa procesal.

        rad23 colombiano termina en NN (00=1ra inst, 01=impugnación, 02+=etc).
        Dos rads del mismo proceso difieren sólo en esos 2 últimos dígitos.
        Comparamos los dígitos 11..21 (juzgado+año+consecutivo) ignorando sufijo.
        """
        a_n = _norm_digits(a)
        b_n = _norm_digits(b)
        if not a_n or not b_n or len(a_n) < 18 or len(b_n) < 18:
            return False
        # Quitar últimos 2 dígitos (sufijo etapa) y comparar 12 dígitos siguientes
        # = año(4)+consecutivo(5)+despacho(3)
        a_core = a_n[-14:-2] if len(a_n) >= 14 else a_n
        b_core = b_n[-14:-2] if len(b_n) >= 14 else b_n
        return a_core == b_core

    case_rad23_in_doc = bool(case_rad23_norm and len(case_rad23_norm) >= 18
                              and case_rad23_norm[-14:] in fn_digits)
    case_rad23_in_text = False
    for r in ids.of_kind("rad23"):
        if _same_rad23(case_rad23_norm, r.value):
            case_rad23_in_text = True
            break

    if case_rad23_in_doc or case_rad23_in_text:
        # rad23 exacto del case está en el doc → no proponer target ajeno
        return None, ""

    try:
        from backend.email.case_lookup_cache import get_cache
        cache = get_cache()
        if cache._built:
            # Helper para validar candidato target con DB
            def _validate_candidate(cand_case_id: int, source_rad: str) -> bool:
                """Verifica si el target tiene rad23 cuya forma corta == rad23 del doc.
                Si el doc tiene rad23 23-d, debe coincidir EXACTO con el del target.
                """
                if cand_case_id == getattr(case, "id", None):
                    return False
                # Si el cache lo devolvió por rad23 exacto, ya está validado
                return True

            # 1) rad23 ajeno → buscar destino
            for r in ids.of_kind("rad23"):
                rad_norm = _norm_digits(r.value)
                if not rad_norm or len(rad_norm) < 18:
                    continue
                if _same_rad23(case_rad23_norm, r.value):
                    continue
                hit = cache.lookup_by_rad23(r.value)
                if hit and _validate_candidate(hit, rad_norm):
                    target_case_id = hit
                    target_evidence = f"rad23={rad_norm[-14:]}"
                    break

            # 2) rad_corto en filename/texto (validar que target tiene rad23 que coincide)
            if not target_case_id:
                cands = _extract_rad_cortos(filename)
                for cand in cands:
                    if cand == case_rad_corto:
                        continue
                    hit = cache.lookup_by_rad_corto(cand)
                    if hit and _validate_candidate(hit, cand):
                        target_case_id = hit
                        target_evidence = f"rad_corto={cand} (filename)"
                        break

            # 3) Validación adicional: si target identificado, verificar coherencia con accionante
            if target_case_id:
                try:
                    from backend.database.database import SessionLocal
                    from backend.database.models import Case as _Case
                    _sess = SessionLocal()
                    try:
                        tgt = _sess.query(_Case).filter(_Case.id == target_case_id).first()
                        if tgt and tgt.accionante:
                            tgt_words = _significant_name_words(tgt.accionante)
                            txt_norm = _norm_text(full_text[:5000] + " " + filename)
                            if tgt_words:
                                acc_match = sum(1 for w in tgt_words[:4] if w in txt_norm)
                                if acc_match == 0 and len(tgt_words) >= 2:
                                    # Target identificado por rad pero accionante NO está en doc
                                    # → reducir confianza del target (no descarta, marca SOSPECHOSO)
                                    target_evidence += " [accionante target no en doc]"
                    finally:
                        _sess.close()
                except Exception:
                    pass

            # Si target identificado y filename apunta a otro case → señal negativa
            if target_case_id:
                for r in ids.of_kind("rad23"):
                    rad_norm = _norm_digits(r.value)
                    if (rad_norm[-14:] in fn_digits
                            and not _same_rad23(case_rad23_norm, r.value)):
                        evidence.add("filename_other_case_rad23", LR_FILENAME_HAS_OTHER_CASE_RAD23,
                                     detail=f"filename apunta a otro case: {rad_norm[-14:]}",
                                     pro=False)
                        reasons_against.append("Filename contiene rad23 de OTRO caso conocido")
                        break
    except Exception:
        pass

    # ---- R10: corroboración por expediente (v6.0.17) ----
    # Si el case tiene ≥3 docs OK con rad23 del case Y este doc no tiene rad ajeno
    # detectado → contexto del expediente valida pertenencia. LR moderado.
    # Why: docs sin identifier propio (escritos pre-rad, anexos, correos
    # renderizados) que viven en una carpeta validada heredan contexto.
    has_rad_ajeno = bool(target_case_id) or any(
        s.name in ("rad23_other_case_header", "rad23_other_case_body",
                   "filename_other_case_rad23")
        for s in evidence.signals
    )
    has_strong_signal = any(
        s.name in ("filename_case_rad23", "filename_case_rad_corto",
                   "rad23_visual_match", "rad23_header_match", "rad23_body_match",
                   "thread_parent", "email_markdown",
                   "tutela_inicial_pre_rad", "incidente_pre_rad",
                   "text_rad_corto_and_accionante")
        for s in evidence.signals
    )
    if not has_rad_ajeno and not has_strong_signal:
        try:
            from backend.database.database import SessionLocal
            from backend.database.models import Document as _Doc
            from sqlalchemy import and_
            _sess = SessionLocal()
            try:
                # Contar hermanos OK con rad23 confirmado en el case actual
                # (excluyendo el doc en evaluación si tiene id en DB)
                doc_id_self = None
                if hasattr(doc_ir, "filename") and case_rad23_norm:
                    case_id_actual = getattr(case, "id", None)
                    if case_id_actual:
                        # Heurística simple: contar docs OK del case que tienen rad23 del case
                        # mencionado en su verificacion_detalle (señal de validación previa)
                        ok_siblings = _sess.query(_Doc).filter(
                            and_(_Doc.case_id == case_id_actual,
                                 _Doc.verificacion == "OK")
                        ).count()
                        if ok_siblings >= 3:
                            evidence.add("case_corroborated", LR_CASE_CORROBORATED,
                                         detail=f"{ok_siblings} hermanos OK en case (expediente validado)")
                            reasons_for.append(
                                f"Expediente del caso tiene {ok_siblings} docs OK (corroboración por contexto)"
                            )
            finally:
                _sess.close()
        except Exception:
            pass

    return target_case_id, target_evidence


# ============================================================
# Helpers v6.0.16
# ============================================================

_NAME_SKIP = {
    "AGENTE", "OFICIOSO", "MENOR", "REPRESENTANTE", "LEGAL", "MUNICIPAL",
    "PERSONERO", "PERSONERA", "PERSONERIA", "ACCION", "TUTELA", "CONTRA",
    "HIJO", "HIJA", "SENOR", "SENORA", "COMO", "REPRESENTATE", "REPRESENTACION",
    "NOMBRE", "DOCENTE", "RECTOR", "ALCALDE", "JUEZ", "SECRETARIA",
}


def _significant_name_words(name: str) -> list[str]:
    """Extrae palabras del nombre del accionante (≥4 chars, sin stopwords)."""
    return [w for w in re.findall(r"[A-ZÁÉÍÓÚÑ]{4,}", _norm_text(name))
            if w not in _NAME_SKIP]


def _derive_rad_corto(rad23_norm: str) -> str:
    """Deriva 'AAAA-NNNNN' de un rad23 normalizado de 22-25 dígitos."""
    if not rad23_norm or len(rad23_norm) < 18:
        return ""
    m = re.search(r"(20\d{2})(\d{5})", rad23_norm)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return ""


def _extract_rad_corto_from_string(s: str) -> str:
    """Extrae 'AAAA-NNNNN' del primer match en s (folder_name, etc.)."""
    if not s:
        return ""
    m = re.search(r"(20\d{2})[-_ ]?0*(\d{1,5})", s)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(5)}"
    return ""


def _extract_rad_cortos(s: str) -> set[str]:
    """Extrae TODOS los rad_corto AAAA-NNNNN de s."""
    if not s:
        return set()
    found = set()
    for m in re.finditer(r"(20\d{2})[-_ ]?0*(\d{1,5})(?:[-_ ]?\d{2})?", s):
        yr, sq = m.group(1), m.group(2).zfill(5)
        # Sanity: año razonable, secuencial >=1
        if 2018 <= int(yr) <= 2030 and int(sq) >= 1:
            found.add(f"{yr}-{sq}")
    return found


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
