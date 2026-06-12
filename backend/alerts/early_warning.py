"""Early Warning — Propuesta 9.4 de la tesis (recalibrado P19, 2026-06-11).

Sistema de alertas tempranas que clasifica casos activos por nivel de riesgo
procesal. Semáforo: ROJO (intervención inmediata), AMARILLO (vigilar),
VERDE (en cumplimiento), N/A (caso archivado — no aplica).

P19: el motor evaluaba TODOS los casos (80 de 115 "rojos" eran INACTIVO,
archivados hace meses) y leía columnas del motor v6 borrado (estado_incidente,
processing_status). Ahora: compuerta por cases.estado (la autoridad curada)
+ incidentes desde incidente/decision_incidente. Sin IA, determinista.
"""

from __future__ import annotations
from backend.core.time import utcnow

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case


# ============================================================
# Configuración de umbrales (ajustables por política institucional)
# ============================================================

# Días desde apertura del incidente tras los cuales sube el riesgo
INCIDENT_DAYS_TO_YELLOW = 10
INCIDENT_DAYS_TO_RED = 20

# Días desde fallo CONCEDE sin respuesta institucional
RESPONSE_DAYS_TO_YELLOW = 5
RESPONSE_DAYS_TO_RED = 10

# Score thresholds
SCORE_RED = 0.70
SCORE_YELLOW = 0.40

# Niveles
LEVEL_RED = "ROJO"
LEVEL_YELLOW = "AMARILLO"
LEVEL_GREEN = "VERDE"
LEVEL_NA = "N/A"


# ============================================================
# Reporte
# ============================================================

@dataclass
class RiskReport:
    case_id: int
    folder_name: str
    origen: str
    estado_incidente: str
    level: str                      # ROJO / AMARILLO / VERDE / N/A
    score: float                    # 0-1
    reasons: list[str] = field(default_factory=list)
    days_since_incidente: Optional[int] = None
    days_since_fallo_1st: Optional[int] = None
    has_response: bool = True
    abogado_responsable: str = ""
    entropy_score: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "folder_name": self.folder_name,
            "origen": self.origen,
            "estado_incidente": self.estado_incidente,
            "level": self.level,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "days_since_incidente": self.days_since_incidente,
            "days_since_fallo_1st": self.days_since_fallo_1st,
            "has_response": self.has_response,
            "abogado_responsable": self.abogado_responsable,
            "entropy_score": round(self.entropy_score, 3) if self.entropy_score else None,
        }


# ============================================================
# Parsing de fechas
# ============================================================

_RE_FECHA = re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](20\d{2})")


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    m = _RE_FECHA.search(s)
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _days_ago(date_str: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    d = _parse_date(date_str)
    if not d:
        return None
    now = now or utcnow()
    return max(0, (now - d).days)


# ============================================================
# Scoring principal
# ============================================================

def score_case(case: Case, now: Optional[datetime] = None) -> RiskReport:
    """Calcula el nivel de riesgo de un caso activo.

    Reglas deterministas (sin IA), sobre campos curados:
    - Caso INACTIVO (cuadro curado) → N/A, no se evalúa
    - decision_incidente SANCIONA → ROJO directo (máxima prioridad)
    - Incidente en trámite >20 días → ROJO; 10-20 días → AMARILLO
    - Fallo CONCEDE + >10 días sin respuesta → ROJO; 5-10 días → AMARILLO
    - Plazo de cumplimiento (compliance_tracking) vencido → ROJO
    - Entropía muy alta / incidente huérfano / apercibimiento → AMARILLO
    - Todo lo demás → VERDE
    """
    now = now or utcnow()
    origen = case.origen or "AMBIGUO"
    estado = case.estado_incidente or "N/A"
    reasons: list[str] = []
    score = 0.0

    # Compuerta P19: un caso archivado (INACTIVO en el cuadro curado) no tiene
    # riesgo procesal vigente — no se evalúa. Sin esto, 80 de 115 "rojos"
    # eran casos cerrados con órdenes viejas en compliance_tracking.
    if (case.estado or "").strip().upper() == "INACTIVO":
        return RiskReport(
            case_id=case.id,
            folder_name=case.folder_name or "",
            origen=origen,
            estado_incidente=estado,
            level=LEVEL_NA,
            score=0.0,
            reasons=["Caso INACTIVO (archivado) — sin riesgo procesal vigente"],
            abogado_responsable=(case.abogado_canonical or case.abogado_responsable or ""),
            entropy_score=case.entropy_score,
        )

    # Calcular días transcurridos
    days_incid = _days_ago(case.fecha_apertura_incidente, now)
    days_fallo = _days_ago(case.fecha_fallo_1st, now)
    days_response = _days_ago(case.fecha_respuesta, now)
    has_response = bool((case.fecha_respuesta or "").strip())

    # Estado del incidente desde los campos CURADOS (decision_incidente);
    # estado_incidente del motor v6 quedó congelado y daba cifras stale.
    decisiones = {(d or "").strip().upper() for d in
                  (case.decision_incidente, case.decision_incidente_2,
                   case.decision_incidente_3)} - {""}
    dec_principal = (case.decision_incidente or "").strip().upper()
    incidente_si = (case.incidente or "").strip().upper() == "SI"

    # Regla 1: sanción vigente = ROJO automático
    if "SANCIONA" in decisiones:
        score = 1.0
        reasons.append("Incidente con SANCIÓN — intervención jurídica inmediata requerida")

    # Regla 2: incidente en trámite (abierto sin decisión terminal) con tiempo
    elif incidente_si and dec_principal in ("EN_TRAMITE", "") and days_incid is not None:
        if days_incid >= INCIDENT_DAYS_TO_RED:
            score = max(score, 0.80)
            reasons.append(f"Incidente en trámite sin resolver hace {days_incid} días (>{INCIDENT_DAYS_TO_RED})")
        elif days_incid >= INCIDENT_DAYS_TO_YELLOW:
            score = max(score, 0.50)
            reasons.append(f"Incidente en trámite hace {days_incid} días — vigilar")
        else:
            score = max(score, 0.25)
            reasons.append(f"Incidente en trámite reciente ({days_incid} días)")

    # Regla 3: EN_CONSULTA (columna legacy pero curada a mano en casos puntuales)
    elif estado == "EN_CONSULTA":
        score = max(score, 0.55)
        reasons.append("Incidente EN_CONSULTA — pendiente decisión superior")

    # Regla 4: Fallo CONCEDE/TUTELA sin respuesta institucional
    sentido = (case.sentido_fallo_1st or "").upper()
    if "CONCEDE" in sentido or "AMPARA" in sentido or "TUTELA" in sentido:
        if not has_response and days_fallo is not None:
            if days_fallo >= RESPONSE_DAYS_TO_RED:
                score = max(score, 0.75)
                reasons.append(f"Fallo CONCEDE sin respuesta hace {days_fallo} días")
            elif days_fallo >= RESPONSE_DAYS_TO_YELLOW:
                score = max(score, 0.45)
                reasons.append(f"Fallo CONCEDE con respuesta pendiente ({days_fallo} días)")

    # Regla 5: Entropía alta = datos sospechosos
    if case.entropy_score is not None and case.entropy_score >= 2.2:
        score = max(score, 0.45)
        reasons.append(f"Entropía elevada (H={case.entropy_score:.2f}) — datos requieren revisión")

    # Regla 6: INCIDENTE_HUERFANO sin consolidación
    if origen == "INCIDENTE_HUERFANO":
        score = max(score, 0.50)
        reasons.append("Incidente huérfano sin tutela madre identificada — revisar consolidación")

    # (Regla 7 eliminada en P19: leía processing_status, columna del workflow
    # de extracción legacy congelada desde la curación manual del cuadro.)

    # Regla 8 (v8.2): plazo de cumplimiento del fallo próximo a vencer.
    # Cruza con compliance_tracking — si el plazo legal del juez está por vencer,
    # antes incluso del incidente, hay que actuar.
    try:
        from backend.database.models import ComplianceTracking
        if hasattr(case, "compliance_records") and case.compliance_records:
            for rec in case.compliance_records:
                # CUMPLIDO/NO_APLICA = orden satisfecha, revocada o cerrada;
                # requiere_cumplimiento=NO = ordinal informativo sin carga.
                if (rec.estado or "").upper() in ("CUMPLIDO", "NO_APLICA"):
                    continue
                if (rec.requiere_cumplimiento or "").upper() == "NO":
                    continue
                limite = _parse_date(rec.fecha_limite)
                if not limite:
                    continue
                dias_restantes = (limite - now).days
                if dias_restantes < 0:
                    score = max(score, 0.85)
                    reasons.append(
                        f"Plazo cumplimiento fallo VENCIDO hace {abs(dias_restantes)} días "
                        f"(orden {rec.instancia or '1ra'}) — incidente probable"
                    )
                elif dias_restantes <= 2:
                    score = max(score, 0.70)
                    reasons.append(
                        f"Plazo cumplimiento fallo vence en {dias_restantes} día(s) — actuar hoy"
                    )
                elif dias_restantes <= 7:
                    score = max(score, 0.45)
                    reasons.append(
                        f"Plazo cumplimiento fallo vence en {dias_restantes} días — preparar respuesta"
                    )
    except Exception as _e:
        from backend.core.fallback_metrics import record_fallback
        record_fallback("early_warning.compliance", str(_e))  # datos sucios de compliance, ahora visible

    # Regla 9 (v8.2): detección de "previene/apercibe sanción" en sentencia.
    # Cuando el juez explícitamente advierte que ante incumplimiento decretará
    # sanción de desacato, la prevención es inmediata.
    try:
        if hasattr(case, "documents"):
            for doc in case.documents:
                doc_type = (doc.doc_type or "").upper()
                if not any(k in doc_type for k in ("SENTENCIA", "FALLO", "AUTO_ADMISORIO")):
                    continue
                text = (doc.extracted_text or "").upper()[:6000]
                # Patrones jurídicos típicos de prevención
                if any(p in text for p in (
                    "PREVENGA", "APERCIBE", "APERCIBIMIENTO", "BAJO APERCIBIMIENTO",
                    "SO PENA DE INCURRIR", "DESACATO", "POSIBLE SANCIÓN",
                    "MULTA Y/O ARRESTO",
                )):
                    score = max(score, 0.55)
                    reasons.append(
                        "Sentencia contiene prevención/apercibimiento explícito — riesgo de sanción anticipado"
                    )
                    break
    except Exception:
        pass

    # Regla 10 (v8.2): drift de asignación administrativa.
    # Si la última actuación del Excel asigna abogado distinto al canónico actual,
    # señalar para verificar quién está respondiendo realmente.
    try:
        from backend.database.models import CaseActuacion
        if hasattr(case, "actuaciones_registradas") and case.actuaciones_registradas:
            ult = sorted(
                [a for a in case.actuaciones_registradas if a.abogado_canonical],
                key=lambda a: a.imported_at or datetime.min, reverse=True,
            )
            if ult:
                ult_abog = ult[0].abogado_canonical
                if (case.abogado_canonical and ult_abog and
                        case.abogado_canonical != ult_abog):
                    score = max(score, 0.30)
                    reasons.append(
                        f"Drift de asignación: DB tiene {case.abogado_canonical[:25]} "
                        f"pero última actuación dice {ult_abog[:25]}"
                    )
    except Exception:
        pass

    # Determinar nivel
    if case.processing_status in ("DUPLICATE_MERGED",):
        level = LEVEL_NA
    elif score >= SCORE_RED:
        level = LEVEL_RED
    elif score >= SCORE_YELLOW:
        level = LEVEL_YELLOW
    elif score > 0 or estado != "N/A":
        level = LEVEL_GREEN
        if not reasons:
            reasons.append("Caso en trámite sin alertas activas")
    else:
        level = LEVEL_GREEN
        reasons.append("Sin incidentes ni alertas")

    return RiskReport(
        case_id=case.id,
        folder_name=case.folder_name or "",
        origen=origen,
        estado_incidente=estado,
        level=level,
        score=min(score, 1.0),
        reasons=reasons,
        days_since_incidente=days_incid,
        days_since_fallo_1st=days_fallo,
        has_response=has_response,
        abogado_responsable=(case.abogado_canonical or case.abogado_responsable or ""),
        entropy_score=case.entropy_score,
    )


# ============================================================
# Agregados del sistema
# ============================================================

@dataclass
class EarlyWarningSummary:
    total_cases_evaluated: int
    by_level: dict[str, int] = field(default_factory=dict)
    red_cases: list[RiskReport] = field(default_factory=list)
    yellow_cases: list[RiskReport] = field(default_factory=list)
    green_count: int = 0
    na_count: int = 0
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "total_cases_evaluated": self.total_cases_evaluated,
            "by_level": self.by_level,
            "red": [r.to_dict() for r in self.red_cases],
            "yellow": [r.to_dict() for r in self.yellow_cases],
            "green_count": self.green_count,
            "na_count": self.na_count,
            "generated_at": self.generated_at,
        }


def run_early_warning(db: Session, now: Optional[datetime] = None) -> EarlyWarningSummary:
    """Evalúa todos los casos y retorna el summary (INACTIVO sale como N/A)."""
    now = now or utcnow()
    # P19: sin filtro por processing_status (legacy congelado, además su
    # semántica SQL excluía los NULL). La compuerta por estado curado
    # vive en score_case.
    cases = db.query(Case).all()

    reports = [score_case(c, now=now) for c in cases]

    by_level: dict[str, int] = {LEVEL_RED: 0, LEVEL_YELLOW: 0, LEVEL_GREEN: 0, LEVEL_NA: 0}
    red_cases: list[RiskReport] = []
    yellow_cases: list[RiskReport] = []
    green_count = 0
    na_count = 0

    for r in reports:
        by_level[r.level] = by_level.get(r.level, 0) + 1
        if r.level == LEVEL_RED:
            red_cases.append(r)
        elif r.level == LEVEL_YELLOW:
            yellow_cases.append(r)
        elif r.level == LEVEL_NA:
            na_count += 1
        else:
            green_count += 1

    # Ordenar por score descendente
    red_cases.sort(key=lambda r: -r.score)
    yellow_cases.sort(key=lambda r: -r.score)

    return EarlyWarningSummary(
        total_cases_evaluated=len(reports),
        by_level=by_level,
        red_cases=red_cases,
        yellow_cases=yellow_cases,
        green_count=green_count,
        na_count=na_count,
        generated_at=now.isoformat(timespec="seconds"),
    )
