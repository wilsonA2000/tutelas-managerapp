"""Auditoría integral de fallos e incidentes — propuesta v8.2.

Vista unificada por etapa procesal y por abogado canónico, con cruce de:
- Fallos 1ra/2da instancia (sentido + plazos)
- Incidentes de desacato (apertura, pruebas, sanción, consulta)
- Compliance tracking (plazos del fallo)
- Bitácora de actuaciones administrativas (Excel)
- Cases en Corte Constitucional (Sprint 4)
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.database.models import Case, CaseActuacion, ComplianceTracking
from backend.alerts.early_warning import score_case, _parse_date

router = APIRouter(prefix="/api/auditoria", tags=["auditoria"])


def _case_to_audit_card(case: Case, now: datetime) -> dict:
    """Construye una tarjeta de auditoría con todas las dimensiones relevantes."""
    risk = score_case(case, now)

    # Compliance: tomar el primer registro pendiente
    compliance = None
    if hasattr(case, "compliance_records") and case.compliance_records:
        for rec in case.compliance_records:
            if (rec.estado or "").upper() not in ("CUMPLIDO",):
                limite = _parse_date(rec.fecha_limite)
                dias_restantes = (limite - now).days if limite else None
                compliance = {
                    "instancia": rec.instancia,
                    "sentido_fallo": rec.sentido_fallo,
                    "fecha_fallo": rec.fecha_fallo,
                    "fecha_limite": rec.fecha_limite,
                    "dias_restantes": dias_restantes,
                    "estado": rec.estado,
                    "impugnado": rec.impugnado,
                }
                break

    # Última actuación administrativa
    ult_actuacion = None
    if hasattr(case, "actuaciones_registradas") and case.actuaciones_registradas:
        ult = sorted(case.actuaciones_registradas,
                     key=lambda a: a.imported_at or datetime.min, reverse=True)[0]
        ult_actuacion = {
            "fecha": ult.fecha_actuacion,
            "tipo": ult.tipo_actuacion,
            "tema": ult.tema,
            "observaciones": (ult.observaciones or "")[:200],
        }

    # Etapa procesal actual
    estado_inc = (case.estado_incidente or "N/A").upper()
    sentido_2da = (case.sentido_fallo_2nd or "").upper()
    sentido_1ra = (case.sentido_fallo_1st or "").upper()
    if estado_inc == "EN_SANCION":
        etapa = "INCIDENTE_SANCION"
    elif estado_inc == "EN_CONSULTA":
        etapa = "INCIDENTE_CONSULTA"
    elif estado_inc == "ACTIVO":
        etapa = "INCIDENTE_ACTIVO"
    elif estado_inc == "CUMPLIDO":
        etapa = "INCIDENTE_CUMPLIDO"
    elif sentido_2da:
        etapa = "FALLO_2DA"
    elif sentido_1ra:
        etapa = "FALLO_1RA"
    elif case.origen == "INCIDENTE_HUERFANO":
        etapa = "INCIDENTE_HUERFANO"
    else:
        etapa = "EN_TRAMITE"

    return {
        "case_id": case.id,
        "folder_name": case.folder_name,
        "radicado": case.radicado_23_digitos,
        "accionante": case.accionante,
        "abogado_canonical": case.abogado_canonical,
        "abogado_short_display": (
            (case.abogado_canonical or "").split()[0] if case.abogado_canonical else None
        ),
        "dependencia_canonical": case.dependencia_canonical,
        "etapa": etapa,
        "origen": case.origen,
        "estado_incidente": estado_inc,
        "sentido_fallo_1st": case.sentido_fallo_1st,
        "fecha_fallo_1st": case.fecha_fallo_1st,
        "sentido_fallo_2nd": case.sentido_fallo_2nd,
        "fecha_fallo_2nd": case.fecha_fallo_2nd,
        "fecha_apertura_incidente": case.fecha_apertura_incidente,
        "compliance": compliance,
        "ultima_actuacion": ult_actuacion,
        "risk_level": risk.level,
        "risk_score": round(risk.score, 3),
        "risk_reasons": risk.reasons[:3],
    }


@router.get("/dashboard")
def auditoria_dashboard(db: Session = Depends(get_db)):
    """Dashboard agregado por etapa, abogado y dependencia."""
    cases = db.query(Case).filter(Case.processing_status == "COMPLETO").all()
    now = datetime.utcnow()

    by_etapa = Counter()
    by_abogado = defaultdict(lambda: {"total": 0, "criticos": 0, "incidentes": 0, "vencidos": 0})
    by_dependencia = defaultdict(lambda: {"total": 0, "criticos": 0, "incidentes": 0})
    rojos = 0
    amarillos = 0

    for case in cases:
        card = _case_to_audit_card(case, now)
        by_etapa[card["etapa"]] += 1

        ab = card["abogado_canonical"] or "SIN ASIGNAR"
        by_abogado[ab]["total"] += 1
        if card["risk_level"] == "ROJO":
            by_abogado[ab]["criticos"] += 1
            rojos += 1
        elif card["risk_level"] == "AMARILLO":
            amarillos += 1
        if card["estado_incidente"] in ("ACTIVO", "EN_SANCION", "EN_CONSULTA"):
            by_abogado[ab]["incidentes"] += 1
        if card.get("compliance") and card["compliance"].get("dias_restantes") is not None:
            if card["compliance"]["dias_restantes"] < 0:
                by_abogado[ab]["vencidos"] += 1

        dep = card["dependencia_canonical"] or "SIN ASIGNAR"
        by_dependencia[dep]["total"] += 1
        if card["risk_level"] == "ROJO":
            by_dependencia[dep]["criticos"] += 1
        if card["estado_incidente"] in ("ACTIVO", "EN_SANCION", "EN_CONSULTA"):
            by_dependencia[dep]["incidentes"] += 1

    return {
        "generated_at": now.isoformat(),
        "total_cases": len(cases),
        "rojos": rojos,
        "amarillos": amarillos,
        "by_etapa": dict(by_etapa),
        "by_abogado": [
            {"abogado": k, **v} for k, v in
            sorted(by_abogado.items(), key=lambda x: -x[1]["total"])
        ],
        "by_dependencia": [
            {"dependencia": k, **v} for k, v in
            sorted(by_dependencia.items(), key=lambda x: -x[1]["total"])
        ],
    }


@router.get("/cases")
def auditoria_cases(
    etapa: Optional[str] = None,
    abogado: Optional[str] = None,
    dependencia: Optional[str] = None,
    risk_level: Optional[str] = None,
    only_active: bool = True,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """Lista cases filtrada para vista de auditoría."""
    q = db.query(Case).filter(Case.processing_status == "COMPLETO")
    if abogado:
        q = q.filter(Case.abogado_canonical == abogado)
    if dependencia:
        q = q.filter(Case.dependencia_canonical == dependencia)
    cases = q.all()
    now = datetime.utcnow()
    out = []
    for case in cases:
        card = _case_to_audit_card(case, now)
        if etapa and card["etapa"] != etapa:
            continue
        if risk_level and card["risk_level"] != risk_level:
            continue
        if only_active and card["estado_incidente"] == "CUMPLIDO" and card["risk_level"] in ("VERDE", "N/A"):
            continue
        out.append(card)
    # Orden: ROJO primero, dentro orden por etapa de mayor riesgo
    risk_order = {"ROJO": 0, "AMARILLO": 1, "VERDE": 2, "N/A": 3}
    etapa_order = {
        "INCIDENTE_SANCION": 0, "INCIDENTE_CONSULTA": 1, "INCIDENTE_ACTIVO": 2,
        "INCIDENTE_HUERFANO": 3, "FALLO_2DA": 4, "FALLO_1RA": 5, "EN_TRAMITE": 6,
        "INCIDENTE_CUMPLIDO": 9,
    }
    out.sort(key=lambda c: (
        risk_order.get(c["risk_level"], 9),
        etapa_order.get(c["etapa"], 9),
        -(c["risk_score"]),
    ))
    return {"total": len(out), "items": out[:limit]}


@router.get("/abogado/{abogado_canonical}")
def auditoria_por_abogado(abogado_canonical: str, db: Session = Depends(get_db)):
    """Vista detallada para un abogado canónico: su carga, fallos, incidentes,
    plazos próximos, disensos abiertos."""
    cases = db.query(Case).filter(
        Case.processing_status == "COMPLETO",
        Case.abogado_canonical == abogado_canonical,
    ).all()
    now = datetime.utcnow()

    summary = {
        "abogado": abogado_canonical,
        "total_cases": len(cases),
        "incidentes_activos": 0,
        "en_sancion": 0,
        "en_consulta": 0,
        "fallos_concedidos_pendientes": 0,
        "plazos_vencidos": 0,
        "plazos_proximos_7d": 0,
        "criticos_rojo": 0,
        "vigilar_amarillo": 0,
    }
    cards = []
    for case in cases:
        card = _case_to_audit_card(case, now)
        cards.append(card)
        if card["estado_incidente"] == "ACTIVO":
            summary["incidentes_activos"] += 1
        elif card["estado_incidente"] == "EN_SANCION":
            summary["en_sancion"] += 1
        elif card["estado_incidente"] == "EN_CONSULTA":
            summary["en_consulta"] += 1
        if card["risk_level"] == "ROJO":
            summary["criticos_rojo"] += 1
        elif card["risk_level"] == "AMARILLO":
            summary["vigilar_amarillo"] += 1
        if (card.get("compliance") and card["compliance"].get("dias_restantes") is not None):
            d = card["compliance"]["dias_restantes"]
            if d < 0:
                summary["plazos_vencidos"] += 1
            elif d <= 7:
                summary["plazos_proximos_7d"] += 1
        s1 = (card.get("sentido_fallo_1st") or "").upper()
        if "CONCEDE" in s1 or "AMPARA" in s1:
            summary["fallos_concedidos_pendientes"] += 1

    cards.sort(key=lambda c: (
        {"ROJO": 0, "AMARILLO": 1, "VERDE": 2, "N/A": 3}.get(c["risk_level"], 9),
        -c["risk_score"],
    ))
    return {"summary": summary, "cases": cards}
