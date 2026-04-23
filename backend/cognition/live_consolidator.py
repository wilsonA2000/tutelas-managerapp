"""Live Consolidator — Capa 6 del pipeline cognitivo v6.0.

Consolidación que ocurre DENTRO del pipeline (no después como reconcile_db.py).
Al cerrar la Capa 5 para un caso, evalúa si debería:

1. Fusionarse con otro caso canónico (F9 duplicados rad23 + accionante).
2. Mergerse a su tutela padre si es INCIDENTE_HUERFANO (score ≥ 0.85).
3. Reasignar docs SOSPECHOSO a otro caso donde son OK fuerte.

Acciones solo se ejecutan si el score de confianza es ≥ 0.85.
Score entre 0.5 y 0.85 queda como warning revisable en audit_log.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email, AuditLog


logger = logging.getLogger("tutelas.live_consolidator")


MERGE_AUTO_THRESHOLD = 0.85
MERGE_WARNING_THRESHOLD = 0.5


# ============================================================
# Tipos
# ============================================================

@dataclass
class ConsolidationCandidate:
    """Candidato de consolidación entre 2 casos."""
    case_id: int
    parent_case_id: int
    kind: str                           # "orphan_to_parent" / "duplicate_merge"
    score: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "parent_id": self.parent_case_id,
            "kind": self.kind,
            "score": round(self.score, 3),
            "reasons": self.reasons,
        }


@dataclass
class ConsolidationReport:
    applied: list[ConsolidationCandidate] = field(default_factory=list)
    warnings: list[ConsolidationCandidate] = field(default_factory=list)
    skipped: list[ConsolidationCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "applied": [c.to_dict() for c in self.applied],
            "warnings": [c.to_dict() for c in self.warnings],
            "skipped": [c.to_dict() for c in self.skipped],
        }


# ============================================================
# Helpers
# ============================================================

def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.strip()).upper()


def _fuzzy_name_score(a: str, b: str) -> float:
    wa = set(re.findall(r"[A-ZÁÉÍÓÚÑ]{3,}", _norm_name(a)))
    wb = set(re.findall(r"[A-ZÁÉÍÓÚÑ]{3,}", _norm_name(b)))
    if not wa or not wb:
        return 0.0
    common = wa & wb
    return len(common) / max(len(wa), len(wb))


def _norm_rad23(s: str) -> str:
    return re.sub(r"\D", "", s or "")


# ============================================================
# Detección de candidatos
# ============================================================

def find_parent_for_orphan(db: Session, orphan: Case) -> Optional[ConsolidationCandidate]:
    """Para un caso INCIDENTE_HUERFANO, busca tutela padre por múltiples criterios."""
    if (orphan.origen or "") != "INCIDENTE_HUERFANO":
        return None

    orphan_rad23 = _norm_rad23(orphan.radicado_23_digitos)
    orphan_accionante = _norm_name(orphan.accionante or "")
    reasons: list[str] = []
    score = 0.0
    best: Optional[Case] = None

    candidates = db.query(Case).filter(
        Case.id != orphan.id,
        Case.processing_status != "DUPLICATE_MERGED",
        Case.origen == "TUTELA",
    ).all()

    for cand in candidates:
        cand_score = 0.0
        cand_reasons: list[str] = []

        # 1. Rad23 canónico compartido (fuerte)
        if orphan_rad23 and len(orphan_rad23) >= 18:
            cand_rad23 = _norm_rad23(cand.radicado_23_digitos)
            if cand_rad23 and cand_rad23[-17:] == orphan_rad23[-17:]:
                cand_score += 0.55
                cand_reasons.append("rad23 canónico coincide")

        # 2. Nombre accionante coincide (fuerte si >=0.8)
        if orphan_accionante and cand.accionante:
            ratio = _fuzzy_name_score(orphan_accionante, cand.accionante)
            if ratio >= 0.85:
                cand_score += 0.40
                cand_reasons.append(f"accionante fuzzy={ratio:.2f}")
            elif ratio >= 0.6:
                cand_score += 0.20
                cand_reasons.append(f"accionante parcial={ratio:.2f}")

        # 3. Mismo juzgado
        if orphan.juzgado and cand.juzgado:
            if _fuzzy_name_score(orphan.juzgado, cand.juzgado) >= 0.6:
                cand_score += 0.15
                cand_reasons.append("juzgado coincide")

        # 4. Mismo municipio/ciudad
        if orphan.ciudad and cand.ciudad:
            if _norm_name(orphan.ciudad) == _norm_name(cand.ciudad):
                cand_score += 0.05
                cand_reasons.append("ciudad coincide")

        if cand_score > score:
            score = cand_score
            best = cand
            reasons = cand_reasons

    if best is None or score == 0:
        return None

    return ConsolidationCandidate(
        case_id=orphan.id,
        parent_case_id=best.id,
        kind="orphan_to_parent",
        score=min(score, 1.0),
        reasons=reasons,
    )


def find_duplicates_by_rad23(db: Session, case: Case) -> Optional[ConsolidationCandidate]:
    """F9: detecta si otro caso activo comparte rad23 canónico + accionante."""
    case_rad23 = _norm_rad23(case.radicado_23_digitos)
    if not case_rad23 or len(case_rad23) < 18:
        return None

    candidates = db.query(Case).filter(
        Case.id != case.id,
        Case.processing_status != "DUPLICATE_MERGED",
        Case.radicado_23_digitos.isnot(None),
    ).all()

    for cand in candidates:
        cand_rad23 = _norm_rad23(cand.radicado_23_digitos)
        if not cand_rad23 or len(cand_rad23) < 18:
            continue
        if cand_rad23[-17:] != case_rad23[-17:]:
            continue

        score = 0.55                              # rad23 match es fuerte
        reasons = ["rad23 canónico idéntico"]

        if case.accionante and cand.accionante:
            ratio = _fuzzy_name_score(case.accionante, cand.accionante)
            if ratio >= 0.8:
                score += 0.35
                reasons.append(f"accionante fuzzy={ratio:.2f}")

        # El "padre" es el caso con menor id (más antiguo)
        parent_id = min(case.id, cand.id)
        target_id = max(case.id, cand.id)
        return ConsolidationCandidate(
            case_id=target_id,
            parent_case_id=parent_id,
            kind="duplicate_merge",
            score=min(score, 1.0),
            reasons=reasons,
        )
    return None


# ============================================================
# Aplicación (fusión)
# ============================================================

def apply_consolidation(db: Session, cand: ConsolidationCandidate) -> bool:
    """Ejecuta la fusión: mueve docs+emails del case_id al parent_case_id,
    marca el caso como DUPLICATE_MERGED y registra en audit_log."""
    src = db.query(Case).filter(Case.id == cand.case_id).first()
    dst = db.query(Case).filter(Case.id == cand.parent_case_id).first()
    if src is None or dst is None:
        return False
    if src.processing_status == "DUPLICATE_MERGED":
        return False

    # Mover documentos
    docs_moved = db.query(Document).filter(Document.case_id == src.id).update(
        {Document.case_id: dst.id}, synchronize_session=False
    )
    emails_moved = db.query(Email).filter(Email.case_id == src.id).update(
        {Email.case_id: dst.id}, synchronize_session=False
    )

    # Poblar campos de desacato del padre si el huérfano los tenía y el padre no
    for f in ("incidente", "fecha_apertura_incidente", "responsable_desacato",
              "decision_incidente", "estado_incidente"):
        if getattr(src, f, None) and not getattr(dst, f, None):
            setattr(dst, f, getattr(src, f))

    # Marcar origen
    src.processing_status = "DUPLICATE_MERGED"
    src.observaciones = (
        (src.observaciones or "") + f" [v6 live_consolidate: canonical={dst.id}]"
    )

    # Audit log
    audit = AuditLog(
        case_id=src.id,
        action="V6_LIVE_CONSOLIDATE",
        source=f"canonical={dst.id} kind={cand.kind} score={cand.score:.3f} "
               f"reasons={'; '.join(cand.reasons)} docs_moved={docs_moved} emails_moved={emails_moved}",
    )
    db.add(audit)
    db.commit()
    logger.info("V6 consolidate: case %d → %d (%s, score=%.2f, docs=%d emails=%d)",
                src.id, dst.id, cand.kind, cand.score, docs_moved, emails_moved)
    return True


# ============================================================
# Entry point
# ============================================================

def consolidate_case(db: Session, case: Case) -> ConsolidationReport:
    """Evalúa y (si aplica) consolida UN caso al cerrar su procesamiento."""
    report = ConsolidationReport()

    # 1. Huérfano → padre
    cand = find_parent_for_orphan(db, case)
    if cand:
        if cand.score >= MERGE_AUTO_THRESHOLD:
            if apply_consolidation(db, cand):
                report.applied.append(cand)
            else:
                report.skipped.append(cand)
        elif cand.score >= MERGE_WARNING_THRESHOLD:
            report.warnings.append(cand)
            # Registrar warning sin mover datos
            audit = AuditLog(
                case_id=case.id,
                action="V6_CONSOLIDATE_WARNING",
                source=f"candidate_parent={cand.parent_case_id} score={cand.score:.3f} "
                       f"reasons={'; '.join(cand.reasons)}",
            )
            db.add(audit)
            db.commit()
        else:
            report.skipped.append(cand)

    # 2. F9 duplicado por rad23
    cand_dup = find_duplicates_by_rad23(db, case)
    if cand_dup:
        if cand_dup.score >= MERGE_AUTO_THRESHOLD:
            if apply_consolidation(db, cand_dup):
                report.applied.append(cand_dup)
            else:
                report.skipped.append(cand_dup)
        elif cand_dup.score >= MERGE_WARNING_THRESHOLD:
            report.warnings.append(cand_dup)
        else:
            report.skipped.append(cand_dup)

    return report
