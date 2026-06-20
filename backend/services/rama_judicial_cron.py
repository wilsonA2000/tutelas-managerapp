"""Cron de sincronización periódica con la API CPNU de la Rama Judicial (Pendiente A).

Recorre los casos ACTIVOS (con incidente o fallo en curso) y, gentilmente, re-consulta
su expediente en CPNU para detectar actuaciones NUEVAS (nuevo fallo, sanción, consulta)
→ emite alertas de novedad vía `alerts.detector.emit_actuacion_novelty_alerts`.

⚠️ CPNU rate-limitea ráfagas por IP (ver memoria project_rama_judicial_cpnu): por eso
este cron es GENTIL — throttle ≥1.5s entre llamadas + cooldown entre casos, cap por
corrida, corre de noche, y ABORTA tras errores consecutivos (no martillar tras un bloqueo).

Gated por `RAMA_JUDICIAL_SYNC_CRON=true` (default OFF) → inerte hasta activarlo. Es un
flag distinto de `RAMA_JUDICIAL_ENABLED` (enrich en ingesta) para poder activar uno sin
el otro.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.core.time import utcnow

logger = logging.getLogger("tutelas.rama_judicial_cron")

# Estados que justifican vigilar el expediente (puede llegar fallo/sanción/consulta).
_ACTIVE_INCIDENTE = ("ACTIVO", "EN_CONSULTA", "EN_SANCION")
_DEFAULT_LIMIT = 25          # casos por corrida (cap)
_DEFAULT_THROTTLE = 1.6      # s entre llamadas a la API
_DEFAULT_COOLDOWN = 8.0      # s extra entre casos
_MAX_CONSEC_ERRORS = 3       # aborta si CPNU falla seguido (probable rate-limit)
_RESYNC_AFTER_DAYS = 2       # no re-consultar un caso sincronizado hace < 2 días


def cron_enabled() -> bool:
    return os.getenv("RAMA_JUDICIAL_SYNC_CRON", "false").lower() == "true"


def _watch_candidates(db: Session, limit: int) -> list:
    """Casos ACTIVOS con rad23 válido, priorizando los menos-recientemente sincronizados
    (last_synced_at NULL primero). Excluye los sincronizados hace < _RESYNC_AFTER_DAYS."""
    from backend.database.models import Case, RamaJudicialSync
    from backend.email.rad_utils import is_valid_rad23, normalize_rad23

    cutoff = utcnow() - timedelta(days=_RESYNC_AFTER_DAYS)
    rows = (
        db.query(Case)
        .filter(
            Case.processing_status != "DUPLICATE_MERGED",
            or_(Case.estado == "ACTIVO", Case.estado_incidente.in_(_ACTIVE_INCIDENTE)),
        )
        .all()
    )
    out = []
    for c in rows:
        if not is_valid_rad23(normalize_rad23(getattr(c, "radicado_23_digitos", None))):
            continue
        last = (
            db.query(RamaJudicialSync.last_synced_at)
            .filter(RamaJudicialSync.case_id == c.id)
            .order_by(RamaJudicialSync.id.desc())
            .first()
        )
        last_at = last[0] if last else None
        if last_at and last_at > cutoff:
            continue  # sincronizado hace poco → saltar
        out.append((c, last_at))
    # NULL (nunca sincronizado) primero; luego más antiguo primero
    out.sort(key=lambda t: (t[1] is not None, t[1] or utcnow()))
    return [c for c, _ in out[:limit]]


def sync_active_cases(
    db: Session,
    *,
    limit: int = _DEFAULT_LIMIT,
    throttle: float = _DEFAULT_THROTTLE,
    cooldown: float = _DEFAULT_COOLDOWN,
    client=None,
    sleep=time.sleep,
) -> dict:
    """Sincroniza gentilmente los casos activos contra CPNU y emite alertas de novedad.

    `client(rad23) -> objeto con .to_dict()` (default: rama_judicial_client.consultar_proceso),
    inyectable para tests. Returns resumen {procesados, con_novedad, alertas, errores, abortado}.
    """
    from backend.email.rad_utils import normalize_rad23
    from backend.services.rama_judicial_sync import sync_case_actuaciones
    from backend.alerts.detector import emit_actuacion_novelty_alerts

    if client is None:
        from backend.services import rama_judicial_client as rj
        client = lambda rad: rj.consultar_proceso(rad)  # noqa: E731

    cases = _watch_candidates(db, limit)
    res = {"candidatos": len(cases), "procesados": 0, "con_novedad": 0,
           "alertas": 0, "errores": 0, "abortado": False}
    consec = 0
    for i, case in enumerate(cases):
        rad = normalize_rad23(case.radicado_23_digitos)
        try:
            if i > 0:
                sleep(cooldown)
            data = client(rad).to_dict()
            sleep(throttle)
            consec = 0
        except Exception as e:  # noqa: BLE001
            res["errores"] += 1
            consec += 1
            logger.warning("CPNU cron c%s falló: %s", case.id, str(e)[:120])
            if consec >= _MAX_CONSEC_ERRORS:
                res["abortado"] = True
                logger.error("CPNU cron ABORTADO tras %d errores consecutivos (rate-limit?)", consec)
                break
            continue

        res["procesados"] += 1
        if not data or not data.get("encontrado"):
            continue
        try:
            nuevas = sync_case_actuaciones(db, case, data).get("nuevas", [])
            if nuevas:
                res["con_novedad"] += 1
                res["alertas"] += emit_actuacion_novelty_alerts(db, case, nuevas)
        except Exception as e:  # noqa: BLE001
            logger.warning("CPNU cron sync c%s falló (no-fatal): %s", case.id, str(e)[:120])

    logger.info("CPNU cron: %s", res)
    return res


def run_scheduler_thread():
    """Loop daemon: corre `sync_active_cases` una vez al día (~3:30 AM) si el flag está ON.
    Patrón espejo de los otros schedulers de main.py."""
    from backend.database.database import SessionLocal

    while True:
        now = utcnow()
        # próxima corrida: hoy 3:30 AM si aún no pasó, si no mañana
        target = now.replace(hour=3, minute=30, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        time.sleep(max(60, (target - now).total_seconds()))
        if not cron_enabled():
            continue
        try:
            db = SessionLocal()
            try:
                sync_active_cases(db)
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001
            logger.error("CPNU cron scheduler error: %s", str(e)[:160])
