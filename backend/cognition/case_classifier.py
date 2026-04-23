"""Case Classifier — Capa 4 del pipeline cognitivo v6.0.

Determina el `origen` del caso a partir del timeline procesal:
- TUTELA:              caso iniciado normalmente (tiene AUTO_ADMISORIO y/o SOLICITUD)
- INCIDENTE_HUERFANO:  caso con solo docs de incidente/desacato (la tutela
                        madre no está en la DB, es continuación de proceso anterior)
- AMBIGUO:             no hay piezas clave; puede ser solo emails informativos

También determina el `estado_incidente` (si aplica).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.cognition.procedural_timeline import ProcessTimeline


# ============================================================
# Enums
# ============================================================

CASE_ORIGINS = ("TUTELA", "INCIDENTE_HUERFANO", "AMBIGUO")
INCIDENT_STATES = (
    "N/A",           # no hay incidente
    "ACTIVO",        # incidente abierto, sin sanción ni archivo
    "EN_CONSULTA",   # remitido a grado de consulta
    "EN_SANCION",    # auto de sanción existente
    "ARCHIVADO",     # incidente archivado
    "CUMPLIDO",      # cumplimiento acreditado
)


@dataclass
class CaseClassification:
    origen: str                # TUTELA / INCIDENTE_HUERFANO / AMBIGUO
    estado_incidente: str      # uno de INCIDENT_STATES
    has_incidente: bool        # True si hay al menos 1 doc de incidente
    confidence: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return {
            "origen": self.origen,
            "estado_incidente": self.estado_incidente,
            "has_incidente": self.has_incidente,
            "confidence": round(self.confidence, 3),
            "reasons": self.reasons,
        }


# ============================================================
# Clasificador principal
# ============================================================

def classify_case(case, timeline: ProcessTimeline) -> CaseClassification:
    """Clasifica el caso a partir de su timeline."""
    reasons: list[str] = []
    positions = timeline.positions()

    has_auto = "AUTO_ADMISORIO" in positions
    has_sentencia = "FALLO_1ST" in positions or "FALLO_2ND" in positions
    has_solicitud = "SOLICITUD" in positions
    has_incidente = any(p in positions for p in
                        ("INCIDENTE", "AUTO_INCIDENTE", "SANCION", "CUMPLIMIENTO"))

    # Determinar origen
    if has_auto or has_solicitud:
        origen = "TUTELA"
        reasons.append("Tiene pieza inicial de tutela (auto admisorio o escrito)")
        confidence = 0.9
    elif has_sentencia and not has_incidente:
        # Ingreso tardío al sistema con solo la sentencia
        origen = "TUTELA"
        reasons.append("Solo sentencia (ingreso tardío al sistema)")
        confidence = 0.75
    elif has_incidente and not has_auto and not has_solicitud:
        # Solo docs de incidente → huérfano (tutela madre no está en DB)
        origen = "INCIDENTE_HUERFANO"
        reasons.append("Solo docs de incidente/desacato sin pieza inicial")
        confidence = 0.85
    else:
        origen = "AMBIGUO"
        reasons.append("Sin piezas procesales claras; revisar manualmente")
        confidence = 0.5

    # Determinar estado_incidente
    estado = _determine_incident_state(positions, reasons)

    return CaseClassification(
        origen=origen,
        estado_incidente=estado,
        has_incidente=has_incidente,
        confidence=confidence,
        reasons=reasons,
    )


def _determine_incident_state(positions: set[str], reasons: list[str]) -> str:
    if not any(p in positions for p in
               ("INCIDENTE", "AUTO_INCIDENTE", "SANCION", "CUMPLIMIENTO", "REMITE_CONSULTA")):
        return "N/A"
    if "SANCION" in positions:
        reasons.append("Auto de sanción detectado")
        return "EN_SANCION"
    if "REMITE_CONSULTA" in positions:
        reasons.append("Grado de consulta detectado")
        return "EN_CONSULTA"
    if "CUMPLIMIENTO" in positions and not any(p in positions for p in ("SANCION", "AUTO_INCIDENTE")):
        reasons.append("Cumplimiento comunicado")
        return "CUMPLIDO"
    if "AUTO_INCIDENTE" in positions or "INCIDENTE" in positions:
        reasons.append("Incidente abierto (sin sanción ni archivo)")
        return "ACTIVO"
    return "N/A"
