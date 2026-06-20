"""Etapa v9: enriquecimiento desde la API CPNU de la Rama Judicial (Fase B).

Gated por flag `RAMA_JUDICIAL_ENABLED` (default OFF) → INERTE en producción hasta
activarlo. Cuando está ON, setea AUTORITATIVAMENTE los campos ESTRUCTURALES que la
auditoría 2026-06-18 validó como fuente-de-verdad del juzgado:
  - `juzgado` (cod_despacho oficial; 87% coincidía en la auditoría)
  - `fecha_ingreso` (fecha de radicación real; corrige años mal/fechas de correo)

NO toca: accionante/accionados (CPNU parsea mal cooperativas/agentes oficiosos y choca
con la regla personería-no-personero), ni semánticos (asunto/derecho/pretensiones), ni
sentido/parte_resolutiva (probatorios). La política de sobrescritura + el guard de
coherencia de fechas viven en `persist._API_AUTHORITATIVE_FIELDS`.

Cache: `RamaJudicialSync` guarda la respuesta CPNU (TTL 7 días) para no re-pegar la API
en cada extracción. OJO operativo: con el flag ON, una extracción masiva pega CPNU por
caso → respetar el rate-limit (ver project_rama_judicial_cpnu).
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import timedelta

from sqlalchemy.orm import Session

from backend.core.time import utcnow
from backend.email.rad_utils import normalize_rad23, is_valid_rad23
from backend.v9.types import ExtractedFields, FieldSource

logger = logging.getLogger("tutelas.v9.rama_judicial_enrich")

CACHE_TTL_DAYS = 7
_AUTHORITATIVE = ("juzgado", "fecha_ingreso")

# CPNU nombra los juzgados con numeral cero-rellenado ("JUZGADO 008 ADMINISTRATIVO…").
# El cuadro curado usa la forma colombiana: 1-10 ORDINALES (PRIMERO…DÉCIMO), 11+ CARDINALES
# (ONCE, DOCE…). Sin esto, activar el enrich degradaría 433 juzgados curados al formato feo.
_JUZGADO_NUMERAL = {
    1: "PRIMERO", 2: "SEGUNDO", 3: "TERCERO", 4: "CUARTO", 5: "QUINTO",
    6: "SEXTO", 7: "SÉPTIMO", 8: "OCTAVO", 9: "NOVENO", 10: "DÉCIMO",
    11: "ONCE", 12: "DOCE", 13: "TRECE", 14: "CATORCE", 15: "QUINCE",
    16: "DIECISÉIS", 17: "DIECISIETE", 18: "DIECIOCHO", 19: "DIECINUEVE", 20: "VEINTE",
    21: "VEINTIUNO", 22: "VEINTIDÓS", 23: "VEINTITRÉS", 24: "VEINTICUATRO", 25: "VEINTICINCO",
    26: "VEINTISÉIS", 27: "VEINTISIETE", 28: "VEINTIOCHO", 29: "VEINTINUEVE", 30: "TREINTA",
    31: "TREINTA Y UNO", 32: "TREINTA Y DOS", 33: "TREINTA Y TRES", 34: "TREINTA Y CUATRO",
    35: "TREINTA Y CINCO", 36: "TREINTA Y SEIS", 37: "TREINTA Y SIETE", 38: "TREINTA Y OCHO",
    39: "TREINTA Y NUEVE", 40: "CUARENTA",
}
_JUZ_NUM_RE = re.compile(r"\bJUZGADO\s+0*(\d{1,3})\b", re.IGNORECASE)


def normalize_juzgado_cpnu(raw: str | None) -> str | None:
    """Convierte el numeral CPNU del nombre del juzgado a la forma curada
    ('JUZGADO 008 ADMINISTRATIVO  DE BUCARAMANGA' → 'JUZGADO OCTAVO ADMINISTRATIVO DE
    BUCARAMANGA'). Colapsa espacios. Fuera de rango (>40) deja el numeral intacto."""
    if not raw:
        return raw
    s = re.sub(r"\s+", " ", raw).strip()

    def _sub(m: "re.Match") -> str:
        word = _JUZGADO_NUMERAL.get(int(m.group(1)))
        return f"JUZGADO {word}" if word else m.group(0)

    return _JUZ_NUM_RE.sub(_sub, s)


def enabled() -> bool:
    return os.getenv("RAMA_JUDICIAL_ENABLED", "false").lower() == "true"


def _get_or_sync(db: Session, case, rad23: str) -> dict | None:
    """Devuelve la respuesta CPNU (cache si fresca, si no consulta y cachea)."""
    from backend.database.models import RamaJudicialSync

    row = (db.query(RamaJudicialSync)
           .filter(RamaJudicialSync.case_id == case.id)
           .order_by(RamaJudicialSync.id.desc()).first())
    if (row and row.expediente_json and row.last_synced_at
            and (utcnow() - row.last_synced_at) < timedelta(days=CACHE_TTL_DAYS)):
        try:
            return json.loads(row.expediente_json)
        except Exception:
            pass

    from backend.services import rama_judicial_client as rj
    try:
        data = rj.consultar_proceso(rad23).to_dict()
    except Exception as e:
        logger.warning("CPNU enrich c%s falló: %s", case.id, str(e)[:120])
        return None

    if row is None:
        row = RamaJudicialSync(case_id=case.id, radicado_23_digitos=rad23)
        db.add(row)
    row.radicado_23_digitos = rad23
    row.expediente_json = json.dumps(data, ensure_ascii=False)
    row.estado_sync = ("SINCRONIZADO" if data.get("encontrado")
                       else "NO_ENCONTRADO" if data.get("error") == "no_encontrado"
                       else "ERROR")
    row.last_actuaciones_count = len(data.get("actuaciones") or [])
    row.last_synced_at = utcnow()
    row.error_detail = (data.get("error") or "")[:200]
    db.commit()
    return data


def run(db: Session, case, fields: ExtractedFields) -> dict:
    """Force-setea los campos autoritativos en `fields` (la sobrescritura real la
    decide persist). Returns dict con lo aplicado/estado. No-op si el flag está OFF."""
    if not enabled():
        return {"skipped": "RAMA_JUDICIAL_ENABLED off"}
    rad = normalize_rad23(getattr(case, "radicado_23_digitos", None))
    if not is_valid_rad23(rad):
        return {"skipped": "rad23 inválido"}
    data = _get_or_sync(db, case, rad)
    if not data or not data.get("encontrado"):
        return {"found": False, "rad23": rad}

    applied = []
    if data.get("juzgado"):
        # Normaliza el numeral CPNU ("008") a la forma curada ("OCTAVO") para no
        # degradar el formato del cuadro al sobrescribir (decisión Wilson 2026-06-20).
        fields.values["juzgado"] = normalize_juzgado_cpnu(data["juzgado"])
        fields.sources["juzgado"] = FieldSource.API_RAMA_JUDICIAL
        applied.append("juzgado")
    if data.get("fecha_radicacion"):
        fields.values["fecha_ingreso"] = data["fecha_radicacion"]
        fields.sources["fecha_ingreso"] = FieldSource.API_RAMA_JUDICIAL
        applied.append("fecha_ingreso")

    # Fase C: vuelca la línea de actuaciones reales a case_actuaciones y detecta novedades.
    nuevas = []
    alertas = 0
    try:
        from backend.services.rama_judicial_sync import sync_case_actuaciones
        nuevas = sync_case_actuaciones(db, case, data).get("nuevas", [])
        # Hook de novedad: emite Alert por cada actuación nueva significativa
        # (fallo/sentencia/sanción/desacato). Cierra la Fase C.
        if nuevas:
            from backend.alerts.detector import emit_actuacion_novelty_alerts
            alertas = emit_actuacion_novelty_alerts(db, case, nuevas)
    except Exception as e:
        logger.warning("sync actuaciones c%s falló (no-fatal): %s", case.id, str(e)[:120])

    logger.info("CPNU enrich c%s: aplicó %s, +%d actuaciones nuevas, %d alertas",
                case.id, applied, len(nuevas), alertas)
    return {"found": True, "rad23": rad, "applied": applied,
            "actuaciones_nuevas": nuevas, "alertas_novedad": alertas}
