"""Active Learning Scheduler — cron job nocturno (v5.3.3).

Corre automáticamente a las 3:00 AM:
1. Analiza casos recientes (últimos 30 días).
2. Detecta patrones no cubiertos por cognición.
3. Registra sugerencias en AuditLog (action='ACTIVE_LEARNING').
4. NO modifica código automáticamente — solo propone para revisión humana.

Integrado al scheduler de FastAPI (backend/main.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.database import SessionLocal
from backend.database.models import Case, AuditLog

_logger = logging.getLogger("tutelas.active_learning")


def run_nightly_analysis():
    """Punto de entrada del cron nocturno."""
    from backend.cognition import cognitive_fill
    import re
    from collections import Counter

    db: Session = SessionLocal()
    try:
        # Últimos 30 días
        since = datetime.utcnow() - timedelta(days=30)
        cases = (
            db.query(Case)
            .filter(Case.processing_status == "COMPLETO")
            .filter(Case.updated_at >= since)
            .limit(50)
            .all()
        )
        if not cases:
            _logger.info("Active learning: no hay casos recientes para analizar")
            return

        _logger.info(f"Active learning: analizando {len(cases)} casos recientes")

        missed_vinculados = Counter()
        missed_accionantes = Counter()
        missed_decisions = Counter()

        for case in cases:
            full_text = "\n\n".join(
                d.extracted_text for d in case.documents if d.extracted_text
            )[:40000]
            if not full_text:
                continue

            meta = {
                "id": case.id,
                "fecha_ingreso": case.fecha_ingreso or "",
                "radicado_23_digitos": case.radicado_23_digitos or "",
                "radicado_forest": case.radicado_forest or "",
                "abogado_responsable": case.abogado_responsable or "",
                "incidente": case.incidente or "",
            }
            cog = cognitive_fill(meta, full_text, existing={})

            if case.vinculados and "vinculados" not in cog:
                for ent in re.split(r"\s*-\s*", case.vinculados):
                    ent = ent.strip().upper()
                    if ent and len(ent) >= 4:
                        missed_vinculados[ent] += 1

            if case.accionante and "accionante" not in cog:
                missed_accionantes[" ".join(case.accionante.split()[:3]).upper()] += 1

            if case.sentido_fallo_1st and "sentido_fallo_1st" not in cog:
                missed_decisions[case.sentido_fallo_1st.upper()] += 1

        # Registrar sugerencias top en AuditLog
        summary_parts = []
        for ent, n in missed_vinculados.most_common(5):
            if n >= 2:
                summary_parts.append(f"Vinculado candidato: {ent} ({n}x)")
        for fmt, n in missed_accionantes.most_common(5):
            if n >= 2:
                summary_parts.append(f"Accionante formato: {fmt} ({n}x)")
        for dec, n in missed_decisions.most_common(3):
            if n >= 2:
                summary_parts.append(f"Decisión no detectada: {dec} ({n}x)")

        if summary_parts:
            summary = " | ".join(summary_parts[:10])
            db.add(AuditLog(
                case_id=None,
                field_name="active_learning",
                old_value="",
                new_value=summary[:2000],
                action="ACTIVE_LEARNING",
                source=f"scheduler_{datetime.utcnow().strftime('%Y%m%d')}",
            ))
            db.commit()
            _logger.info("Active learning: %d sugerencias registradas", len(summary_parts))
        else:
            _logger.info("Active learning: cognición cubre todos los patrones recientes ✅")

        # También generar el reporte MD
        try:
            from scripts.active_learning import analyze_cognition_gaps, analyze_manual_corrections, render_report
            gaps = analyze_cognition_gaps(limit=100)
            corrections = analyze_manual_corrections()
            report = render_report(gaps, corrections)
            out_dir = Path(__file__).resolve().parent.parent.parent / "logs"
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / f"active_learning_{datetime.utcnow().strftime('%Y%m%d')}.md"
            out_path.write_text(report, encoding="utf-8")
            _logger.info("Reporte active learning: %s", out_path)
        except Exception as e:
            _logger.warning("No pude generar MD: %s", e)
    finally:
        db.close()


def run_scheduler_thread():
    """Thread daemon que ejecuta active learning cada día a las 3:00 AM."""
    import time as _time
    from datetime import datetime as _dt, timedelta as _td
    while True:
        now = _dt.now()
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= target:
            target = target + _td(days=1)
        wait = (target - now).total_seconds()
        _time.sleep(wait)
        try:
            run_nightly_analysis()
        except Exception as e:
            _logger.error("Error en active learning nightly: %s", e)
