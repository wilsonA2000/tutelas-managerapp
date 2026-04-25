"""Cognitive Persist — Capa 7 del pipeline cognitivo v6.0.

Persistencia atómica negentrópica. En lugar de escribir campos durante el
pipeline y corregirlos después, esta capa:

1. Calcula entropy_score(case) sobre el estado derivado del pipeline.
2. Si H ≤ umbral → persiste como COMPLETO + convergence_iterations.
3. Si H > umbral → marca REVISION_HUMANA con reporte explícito.
4. Registra en audit_log las reducciones de entropía por capa.

Idempotencia: correr el pipeline una segunda vez sobre el mismo caso debe
producir exactamente los mismos campos (atractor fijo).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case, AuditLog
from backend.cognition.entropy import entropy_of_case, CaseEntropyReport


logger = logging.getLogger("tutelas.cognitive_persist")


# Umbral por defecto (overridable via settings.COGNITIVE_ENTROPY_THRESHOLD)
DEFAULT_ENTROPY_THRESHOLD = 2.2


# ============================================================
# Reporte
# ============================================================

@dataclass
class PersistReport:
    case_id: int
    status_before: str
    status_after: str
    entropy_before: float
    entropy_after: float
    phase_reductions: dict[str, float] = field(default_factory=dict)
    convergence_iterations: int = 1
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "status_before": self.status_before,
            "status_after": self.status_after,
            "entropy_before": round(self.entropy_before, 4),
            "entropy_after": round(self.entropy_after, 4),
            "entropy_reduction": round(self.entropy_before - self.entropy_after, 4),
            "phase_reductions": {k: round(v, 4) for k, v in self.phase_reductions.items()},
            "convergence_iterations": self.convergence_iterations,
            "reason": self.reason,
        }


# ============================================================
# Entropy gate
# ============================================================

def _entropy_threshold() -> float:
    try:
        from backend.core.settings import settings
        return float(getattr(settings, "COGNITIVE_ENTROPY_THRESHOLD",
                             DEFAULT_ENTROPY_THRESHOLD))
    except Exception:
        return DEFAULT_ENTROPY_THRESHOLD


def persist_case(db: Session, case: Case,
                  phase_entropies: Optional[dict[str, float]] = None,
                  convergence_iterations: int = 1,
                  force_complete: bool = False) -> PersistReport:
    """Persiste el caso con gate de entropía.

    Args:
        db: sesión SQLAlchemy
        case: caso a persistir (ya con campos actualizados por las capas 0-6)
        phase_entropies: dict phase_name → H_después_de_esa_fase (para audit_log)
        convergence_iterations: cuántas iteraciones de feedback loop tomó
        force_complete: True para ignorar el gate (ej. en tests)
    """
    # Estado previo (como viene al entrar a esta capa)
    status_before = case.processing_status or "PENDIENTE"
    previous_entropy = case.entropy_score if case.entropy_score is not None else None

    # Calcular entropía actual
    report_entropy: CaseEntropyReport = entropy_of_case(case)
    h = report_entropy.entropy_bits

    # Actualizar metadata de entropía en el caso
    case.entropy_score = h
    case.convergence_iterations = convergence_iterations

    threshold = _entropy_threshold()

    # Decisión: las inconsistencias SIEMPRE fuerzan REVISION (aunque H sea baja)
    if force_complete:
        new_status = "COMPLETO"
        reason = f"H={h:.3f} force_complete=True"
    elif report_entropy.inconsistent_fields:
        new_status = "REVISION"
        reason = (f"H={h:.3f} con {len(report_entropy.inconsistent_fields)} campos "
                  f"inconsistentes: {', '.join(report_entropy.inconsistent_fields[:5])}")
    elif h <= threshold:
        new_status = "COMPLETO"
        reason = f"H={h:.3f} ≤ threshold={threshold}"
    else:
        new_status = "REVISION"
        reason = f"H={h:.3f} > threshold={threshold} (muchos campos esperados vacíos)"

    case.processing_status = new_status

    # Audit log con reducciones por fase
    source_parts = [
        f"status={status_before}→{new_status}",
        f"H={h:.3f}",
        f"iterations={convergence_iterations}",
        reason,
    ]
    if phase_entropies:
        phase_str = " | ".join(f"{k}={v:.3f}" for k, v in phase_entropies.items())
        source_parts.append(f"phases[{phase_str}]")

    audit = AuditLog(
        case_id=case.id,
        action="V6_COGNITIVE_PERSIST",
        source=" ".join(source_parts),
    )
    db.add(audit)
    db.commit()

    logger.info("V6 persist case=%d %s→%s H=%.3f iters=%d",
                case.id, status_before, new_status, h, convergence_iterations)

    # Capa 7+: rename automático si la carpeta sigue marcada [PENDIENTE/REVISAR]
    # Idempotente: si ya está limpia, skip. Si hay accionante real, rename con
    # nombre. Si el accionante extraído es frase/header, marca [REVISAR_ACCIONANTE].
    try:
        from backend.cognition.folder_renamer import rename_folder_if_needed, needs_rename
        if needs_rename(case.folder_name, case.accionante):
            rename_result = rename_folder_if_needed(db, case)
            if rename_result.get("action") == "renamed":
                db.add(AuditLog(
                    case_id=case.id,
                    action="V6_FOLDER_RENAMED",
                    source=f"{rename_result['old_name']} → {rename_result['new_name']} "
                           f"clean={rename_result.get('is_clean')} "
                           f"fs={rename_result.get('fs_renamed')} "
                           f"docs={rename_result.get('docs_updated')}",
                ))
                db.commit()
    except Exception as e:
        logger.warning("V6 folder rename case=%d no fatal: %s", case.id, e)

    return PersistReport(
        case_id=case.id,
        status_before=status_before,
        status_after=new_status,
        entropy_before=previous_entropy if previous_entropy is not None else h,
        entropy_after=h,
        phase_reductions=phase_entropies or {},
        convergence_iterations=convergence_iterations,
        reason=reason,
    )


# ============================================================
# Idempotencia: diff entre dos estados
# ============================================================

IDEMPOTENT_FIELDS = (
    "radicado_23_digitos", "radicado_forest", "abogado_responsable",
    "accionante", "accionados", "vinculados", "derecho_vulnerado",
    "juzgado", "ciudad", "fecha_ingreso", "asunto", "pretensiones",
    "oficina_responsable", "estado", "fecha_respuesta",
    "sentido_fallo_1st", "fecha_fallo_1st", "impugnacion", "quien_impugno",
    "forest_impugnacion", "juzgado_2nd", "sentido_fallo_2nd",
    "fecha_fallo_2nd", "incidente", "fecha_apertura_incidente",
    "responsable_desacato", "decision_incidente", "observaciones",
    "origen", "estado_incidente", "processing_status",
)


def snapshot_case(case: Case) -> dict:
    """Snapshot compacto de los campos relevantes para test de idempotencia."""
    return {f: getattr(case, f, None) for f in IDEMPOTENT_FIELDS}


def diff_snapshots(a: dict, b: dict) -> dict[str, tuple]:
    """Retorna dict con {campo: (valor_a, valor_b)} para campos que difieren."""
    diff = {}
    for k in IDEMPOTENT_FIELDS:
        va = a.get(k)
        vb = b.get(k)
        if va != vb:
            diff[k] = (va, vb)
    return diff
