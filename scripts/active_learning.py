"""Active learning loop — analiza casos donde cognición falló y propone mejoras.

Identifica 3 tipos de señal de aprendizaje:
1. Correcciones manuales del operador (AuditLog con action=MANUAL_EDIT).
2. Campos que cognición dejó vacíos pero regex/IA sí llenaron.
3. Accionantes con formato no reconocido por nuestros patrones.

Salida: `logs/active_learning_<fecha>.md` con sugerencias accionables
(nuevos patrones regex, nuevas instituciones para KNOWN_INSTITUTIONS,
palabras clave no cubiertas).
"""

import sys
import re
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document, AuditLog
from backend.cognition import cognitive_fill


def analyze_cognition_gaps(limit: int = 100):
    """Para cada caso COMPLETO, compara qué llena cognición vs qué está en DB.

    Si DB tiene un valor que cognición no produjo, el valor DB es "ground truth"
    implícito → patrón que cognición debe aprender.
    """
    db = SessionLocal()
    try:
        cases = (
            db.query(Case)
            .filter(Case.processing_status == "COMPLETO")
            .order_by(Case.id.desc())
            .limit(limit)
            .all()
        )

        accionante_formats_missed = Counter()
        accionados_missed = Counter()
        vinculados_missed = Counter()
        decisions_missed = Counter()

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

            # Accionante: DB lo tiene pero cognición no
            if case.accionante and "accionante" not in cog:
                # Extraer primera palabra en mayúsculas como "starter"
                first_words = " ".join(case.accionante.split()[:3]).upper()
                accionante_formats_missed[first_words] += 1

            # Accionados: entidades que están en DB y no detectamos
            if case.accionados and "accionados" not in cog:
                for ent in re.split(r"\s*-\s*", case.accionados):
                    ent = ent.strip().upper()
                    if ent and len(ent) >= 4:
                        accionados_missed[ent] += 1

            # Vinculados: idem
            if case.vinculados and "vinculados" not in cog:
                for ent in re.split(r"\s*-\s*", case.vinculados):
                    ent = ent.strip().upper()
                    if ent and len(ent) >= 4:
                        vinculados_missed[ent] += 1

            # Decisión: DB tiene sentido_fallo_1st y cognición no
            if case.sentido_fallo_1st and "sentido_fallo_1st" not in cog:
                decisions_missed[case.sentido_fallo_1st.upper()] += 1

        return {
            "accionante_formats": accionante_formats_missed.most_common(20),
            "accionados": accionados_missed.most_common(30),
            "vinculados": vinculados_missed.most_common(30),
            "decisions": decisions_missed.most_common(10),
            "total_cases_analyzed": len(cases),
        }
    finally:
        db.close()


def analyze_manual_corrections():
    """Revisa AuditLog por correcciones manuales del operador.

    Cada MANUAL_EDIT indica que cognición/IA erró. Los patterns más
    frecuentes son candidatos a codificar.
    """
    db = SessionLocal()
    try:
        logs = (
            db.query(AuditLog)
            .filter(AuditLog.action.like("%MANUAL%"))
            .order_by(AuditLog.id.desc())
            .limit(500)
            .all()
        )
        per_field = Counter()
        for log in logs:
            if log.field_name:
                per_field[log.field_name] += 1
        return {"total": len(logs), "per_field": per_field.most_common()}
    finally:
        db.close()


def render_report(gaps, corrections) -> str:
    lines = []
    lines.append(f"# Active Learning Report — {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(f"## Casos analizados: {gaps['total_cases_analyzed']}")
    lines.append("")

    lines.append("## 1. Formatos de ACCIONANTE no detectados por cognición")
    lines.append("Patrones frecuentes donde regex/DB tiene valor pero cognición no:")
    lines.append("")
    for fmt, n in gaps["accionante_formats"]:
        lines.append(f"- **{fmt}** ({n} casos) → considerar patrón específico")
    lines.append("")

    lines.append("## 2. Instituciones accionadas no reconocidas")
    lines.append("Candidatas a añadir a `KNOWN_INSTITUTIONS` en entity_extractor.py:")
    lines.append("")
    for inst, n in gaps["accionados"][:15]:
        lines.append(f"- `{inst}` ({n} casos)")
    lines.append("")

    lines.append("## 3. Vinculados no detectados")
    lines.append("")
    for inst, n in gaps["vinculados"][:10]:
        lines.append(f"- `{inst}` ({n} casos)")
    lines.append("")

    lines.append("## 4. Decisiones con formato inusual")
    lines.append("")
    for dec, n in gaps["decisions"]:
        lines.append(f"- `{dec}` ({n} casos)")
    lines.append("")

    lines.append("## 5. Correcciones manuales del operador")
    if corrections["total"]:
        lines.append(f"Total correcciones registradas: {corrections['total']}")
        lines.append("")
        for field, n in corrections["per_field"]:
            lines.append(f"- {field}: {n} correcciones")
    else:
        lines.append("Sin correcciones manuales registradas (normal si app es reciente).")
    lines.append("")

    lines.append("## Recomendaciones de código")
    lines.append("")
    lines.append("### Si el top 5 de accionados incluye entidades nuevas:")
    lines.append("Añadirlas a `backend/cognition/entity_extractor.py::KNOWN_INSTITUTIONS`.")
    lines.append("")
    lines.append("### Si hay un formato de accionante frecuente no cubierto:")
    lines.append("Añadir patrón regex en `accionante_patterns` (entity_extractor.py).")
    lines.append("")
    lines.append("### Si decisiones con formato inusual:")
    lines.append("Actualizar `DECISION_VERBS` en `decision_extractor.py`.")

    return "\n".join(lines)


def main():
    print("Analizando corpus para active learning...")
    gaps = analyze_cognition_gaps(limit=100)
    corrections = analyze_manual_corrections()

    report = render_report(gaps, corrections)
    out_dir = APP / "logs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"active_learning_{datetime.now().strftime('%Y%m%d')}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"Reporte guardado: {out_path}")
    print()
    print(report[:3000])


if __name__ == "__main__":
    main()
