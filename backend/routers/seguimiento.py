"""Router de seguimiento de cumplimiento de fallos."""

from datetime import datetime, timedelta, timezone
from backend.core.time import utcnow
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database.database import get_db
from backend.database.models import Case, ComplianceTracking
from backend.auth.dependencies import get_current_user
from backend.auth.models import User

router = APIRouter(prefix="/api/seguimiento", tags=["seguimiento"])

COLOMBIA_TZ = timezone(timedelta(hours=-5))

# Valores que NO viven en la columna `estado` sino que los deriva
# _calcular_semaforo a partir de fecha_limite. Filtrar por estos exige
# usar el semáforo, no el estado guardado, para coincidir con las cards.
SEMAFORO_VALUES = {"VENCIDO", "URGENTE", "POR_VENCER", "EN_PLAZO"}


def _calcular_semaforo(record: ComplianceTracking) -> str:
    """Calcular el semáforo (badge de prioridad visual).

    Prioridad (decisión 2026-05-19): el ESTADO MANUAL siempre prevalece sobre
    el cálculo temporal. Solo cuando el estado es PENDIENTE (sin decisión
    humana ni IA-suggested), el semáforo refleja la urgencia temporal o el
    tipo_plazo.

    Razón: si Wilson marca IMPUGNADO o EN_PROCESO, el badge debe reflejar
    esa decisión inmediatamente. El badge "VENCIDO" se reserva para
    pendientes con fecha pasada (candidatos reales a desacato).

      1. CUMPLIDO / NO_APLICA / EN_PROCESO / IMPUGNADO / VENCIDO → estado tal cual
      2. PENDIENTE → cálculo temporal (VENCIDO/URGENTE/POR_VENCER/EN_PLAZO)
      3. Sin fecha → tipo_plazo (PERMANENTE/CONDICIONAL/SIN_PLAZO)
    """
    if record.estado == "CUMPLIDO":
        return "CUMPLIDO"
    if record.estado == "NO_APLICA":
        return "NO_APLICA"
    if record.estado == "EN_PROCESO":
        return "EN_PROCESO"
    if record.estado == "IMPUGNADO":
        # Si tiene requiere_cumplimiento=SI, igual aparece como IMPUGNADO en el badge
        # (el chip 'Imp' separado ya indica la condición)
        return "IMPUGNADO"
    if record.estado == "VENCIDO":
        return "VENCIDO"

    # PENDIENTE → cálculo temporal
    if record.fecha_limite:
        try:
            parts = record.fecha_limite.split("/")
            fecha_lim = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
            hoy = datetime.now(COLOMBIA_TZ).replace(tzinfo=None)
            dias_restantes = (fecha_lim - hoy).days
            if dias_restantes < 0:
                return "VENCIDO"
            if dias_restantes <= 3:
                return "URGENTE"
            if dias_restantes <= 7:
                return "POR_VENCER"
            return "EN_PLAZO"
        except Exception:
            pass

    # Sin fecha — el tipo_plazo describe la naturaleza
    if record.tipo_plazo == "PERMANENTE":
        return "PERMANENTE"
    if record.tipo_plazo == "CONDICIONAL":
        return "CONDICIONAL"
    return "SIN_PLAZO"


def _pipeline_stage(case: Case) -> dict:
    """v8.3: identifica en qué etapa del funnel está el case + estados booleanos.

    Returns:
        {"current": "FALLO_1ST" | "IMPUGNACION" | "FALLO_2ND" | "INCIDENTE" | "CUMPLIDO",
         "has_fallo_1st": bool, "has_impugnacion": bool, "has_fallo_2nd": bool,
         "has_incidente": bool, "is_cumplido": bool}
    """
    if not case:
        return {"current": "TUTELA", "has_fallo_1st": False, "has_impugnacion": False,
                "has_fallo_2nd": False, "has_incidente": False, "is_cumplido": False}
    norm = lambda s: (s or "").strip().upper()
    has_fallo_1st = bool(norm(case.sentido_fallo_1st)) and norm(case.sentido_fallo_1st) not in ("N/A", "PENDIENTE")
    has_impugnacion = norm(case.impugnacion).startswith("S")
    has_fallo_2nd = bool(norm(case.sentido_fallo_2nd)) and norm(case.sentido_fallo_2nd) not in ("N/A", "PENDIENTE")
    has_incidente = norm(case.incidente).startswith("S")
    is_cumplido = (case.estado_incidente or "").upper() == "CUMPLIDO"

    if is_cumplido:
        current = "CUMPLIDO"
    elif has_incidente:
        current = "INCIDENTE"
    elif has_fallo_2nd:
        current = "FALLO_2ND"
    elif has_impugnacion:
        current = "IMPUGNACION"
    elif has_fallo_1st:
        current = "FALLO_1ST"
    else:
        current = "TUTELA"
    return {
        "current": current,
        "has_fallo_1st": has_fallo_1st,
        "has_impugnacion": has_impugnacion,
        "has_fallo_2nd": has_fallo_2nd,
        "has_incidente": has_incidente,
        "is_cumplido": is_cumplido,
    }


def _extraer_radicado_corto(case: Case) -> str:
    """Extrae el radicado corto (YYYY-NNNNN) del folder_name del case.
    Es el identificador que Wilson usa para reconocer cada tutela de un vistazo.
    """
    if not case or not case.folder_name:
        return ""
    import re as _re
    m = _re.match(r"^(\d{4}-\d{4,5})", case.folder_name)
    return m.group(1) if m else ""


def _record_to_dict(r: ComplianceTracking, case: Case = None) -> dict:
    """Convertir registro a dict para API."""
    semaforo = _calcular_semaforo(r)

    # Calcular días restantes
    dias_restantes = None
    if r.fecha_limite:
        try:
            parts = r.fecha_limite.split("/")
            fecha_lim = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
            hoy = datetime.now(COLOMBIA_TZ).replace(tzinfo=None)
            dias_restantes = (fecha_lim - hoy).days
        except Exception:
            pass

    return {
        "id": r.id,
        "case_id": r.case_id,
        "folder_name": case.folder_name if case else None,
        "radicado_corto": _extraer_radicado_corto(case) if case else "",
        "accionante": case.accionante if case else None,
        "juzgado": case.juzgado if case else None,
        "instancia": r.instancia,
        "sentido_fallo": r.sentido_fallo,
        "fecha_fallo": r.fecha_fallo,
        "fecha_notificacion": r.fecha_notificacion,
        "orden_judicial": r.orden_judicial,
        "plazo_dias": r.plazo_dias,
        "fecha_limite": r.fecha_limite,
        "dias_restantes": dias_restantes,
        "responsable": r.responsable,
        "estado": r.estado,
        "semaforo": semaforo,
        "notas": r.notas,
        "fecha_cumplimiento": r.fecha_cumplimiento,
        "impugnado": r.impugnado,
        "efecto_impugnacion": r.efecto_impugnacion,
        "requiere_cumplimiento": r.requiere_cumplimiento,
        "extraido_por_ia": r.extraido_por_ia,
        "pipeline": _pipeline_stage(case),
        # v2 — campos de la orden discreta
        "ordinal_nombre": r.ordinal_nombre,
        "tipo_plazo": r.tipo_plazo,
        "destinatario_tipo": r.destinatario_tipo,
        "accion_resumida": r.accion_resumida,
        "condicion": r.condicion,
        "verbo_orden": r.verbo_orden,
        "fecha_especifica": r.fecha_especifica,
        "evidencia_doc_id": r.evidencia_doc_id,
    }


@router.get("")
def api_list_seguimiento(
    estado: str = "",
    urgencia: str = "",
    db: Session = Depends(get_db),
):
    """Listar todos los seguimientos con semáforo calculado."""
    query = db.query(ComplianceTracking)

    # Los valores temporales (VENCIDO, etc.) se filtran por semáforo en el loop;
    # solo los estados de decisión se filtran en SQL.
    if estado and estado not in SEMAFORO_VALUES:
        query = query.filter(ComplianceTracking.estado == estado)

    records = query.order_by(ComplianceTracking.created_at.desc()).all()

    # Precargar casos
    case_ids = {r.case_id for r in records}
    cases = {c.id: c for c in db.query(Case).filter(Case.id.in_(case_ids)).all()} if case_ids else {}

    items = []
    for r in records:
        item = _record_to_dict(r, cases.get(r.case_id))
        # Filtro por estado temporal (VENCIDO/URGENTE/...): vía semáforo, para
        # que coincida con las cards del resumen (que también usan semáforo).
        if estado in SEMAFORO_VALUES and item["semaforo"] != estado:
            continue
        # Filtro por urgencia. Tres tipos de filtro según semántica:
        #   - tipo_plazo (CONDICIONAL/PERMANENTE/SIN_PLAZO): atributo de la orden.
        #   - estado     (EN_PROCESO/CUMPLIDO/NO_APLICA/IMPUGNADO): dimensión cumplimiento.
        #   - semáforo   (VENCIDO/URGENTE/POR_VENCER/EN_PLAZO): dimensión temporal.
        if urgencia:
            if urgencia in ("CONDICIONAL", "PERMANENTE", "SIN_PLAZO"):
                if r.tipo_plazo != urgencia:
                    continue
            elif urgencia == "IMPUGNADO":
                if not (r.estado == "IMPUGNADO" or r.impugnado == "SI"):
                    continue
            elif urgencia in ("EN_PROCESO", "CUMPLIDO", "NO_APLICA"):
                if r.estado != urgencia:
                    continue
            else:
                if item["semaforo"] != urgencia:
                    continue
        items.append(item)

    # Ordenar: VENCIDO primero, luego URGENTE, POR_VENCER, EN_PLAZO, CUMPLIDO
    orden = {
        "VENCIDO": 0, "URGENTE": 1, "POR_VENCER": 2, "EN_PROCESO": 3,
        "EN_PLAZO": 4, "CONDICIONAL": 5, "PERMANENTE": 6, "SIN_PLAZO": 7,
        "IMPUGNADO": 8, "CUMPLIDO": 9, "NO_APLICA": 10,
    }
    items.sort(key=lambda x: orden.get(x["semaforo"], 99))

    # Resumen — usar la misma lógica que el filtro para coherencia (sin importar
    # urgencia actual). Re-iteramos sobre TODOS los records para conteo global.
    all_records = db.query(ComplianceTracking).all()
    resumen = {
        "total": len(all_records),
        "vencidos":    sum(1 for r in all_records if _calcular_semaforo(r) == "VENCIDO"),
        "urgentes":    sum(1 for r in all_records if _calcular_semaforo(r) == "URGENTE"),
        "por_vencer":  sum(1 for r in all_records if _calcular_semaforo(r) == "POR_VENCER"),
        "en_plazo":    sum(1 for r in all_records if _calcular_semaforo(r) == "EN_PLAZO"),
        "en_proceso":  sum(1 for r in all_records if r.estado == "EN_PROCESO"),
        "cumplidos":   sum(1 for r in all_records if r.estado == "CUMPLIDO"),
        "impugnados":  sum(1 for r in all_records if r.estado == "IMPUGNADO" or r.impugnado == "SI"),
        "condicional": sum(1 for r in all_records if r.tipo_plazo == "CONDICIONAL"),
        "permanente":  sum(1 for r in all_records if r.tipo_plazo == "PERMANENTE"),
        "sin_plazo":   sum(1 for r in all_records if r.tipo_plazo == "SIN_PLAZO"),
        "no_aplica":   sum(1 for r in all_records if r.estado == "NO_APLICA"),
    }

    return {"items": items, "resumen": resumen}


@router.get("/resumen")
def api_resumen_seguimiento(db: Session = Depends(get_db)):
    """Resumen rápido para mostrar en Dashboard."""
    records = db.query(ComplianceTracking).filter(
        ComplianceTracking.estado != "CUMPLIDO"
    ).all()

    case_ids = {r.case_id for r in records}
    cases = {c.id: c for c in db.query(Case).filter(Case.id.in_(case_ids)).all()} if case_ids else {}

    vencidos = 0
    urgentes = 0
    por_vencer = 0

    for r in records:
        s = _calcular_semaforo(r)
        if s == "VENCIDO":
            vencidos += 1
        elif s == "URGENTE":
            urgentes += 1
        elif s == "POR_VENCER":
            por_vencer += 1

    sin_plazo = len(records) - vencidos - urgentes - por_vencer

    return {
        "total_activos": len(records),
        "vencidos": vencidos,
        "urgentes": urgentes,
        "por_vencer": por_vencer,
        "sin_plazo": sin_plazo,
    }


@router.get("/{record_id}")
def api_get_seguimiento(record_id: int, db: Session = Depends(get_db)):
    record = db.query(ComplianceTracking).filter(ComplianceTracking.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    case = db.query(Case).filter(Case.id == record.case_id).first()
    return _record_to_dict(record, case)


@router.put("/{record_id}")
def api_update_seguimiento(record_id: int, body: dict, db: Session = Depends(get_db),
                           user: User | None = Depends(get_current_user)):
    """Actualizar un seguimiento (estado, notas, fecha cumplimiento, etc.).

    Emite eventos al audit_log para todos los cambios significativos:
    - Cambio de estado → COMPLIANCE_STATE_CHANGED
    - Nota agregada → COMPLIANCE_NOTE_ADDED (solo el delta, no la nota completa)
    - Otros campos → FIELD_MODIFIED genérico
    """
    from backend.services.audit_service import (
        audit_event, EVT_COMPLIANCE_STATE, EVT_COMPLIANCE_NOTE, EVT_FIELD_MODIFIED,
    )
    actor = user.username if user else "system"  # Fase 3: actor real del token (era "wilson" hardcodeado)

    record = db.query(ComplianceTracking).filter(ComplianceTracking.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    updatable = [
        "estado", "notas", "fecha_cumplimiento", "fecha_notificacion",
        "fecha_limite", "plazo_dias", "responsable", "orden_judicial",
        "impugnado", "efecto_impugnacion", "requiere_cumplimiento",
    ]

    # Capturar estado anterior para detectar cambios
    snapshot = {f: getattr(record, f) for f in updatable}

    for field in updatable:
        if field in body:
            setattr(record, field, body[field])

    record.updated_at = utcnow()
    db.flush()  # asegurar que record tiene los valores nuevos sin commitear aún

    # Construir contexto del evento
    ordinal = record.ordinal_nombre or ""
    instancia = record.instancia or ""
    ord_label = f"{ordinal}/{instancia}".strip("/")

    # Detectar cambio de estado (evento principal)
    if "estado" in body and snapshot["estado"] != record.estado:
        desc = f"Estado cambiado {snapshot['estado']} → {record.estado}"
        if ord_label:
            desc += f" ({ord_label})"
        audit_event(
            db,
            case_id=record.case_id,
            action=EVT_COMPLIANCE_STATE,
            actor=actor,
            entity_type="compliance",
            entity_id=record.id,
            field_name="estado",
            old_value=snapshot["estado"],
            new_value=record.estado,
            description=desc,
            meta={"ordinal_nombre": ordinal, "instancia": instancia},
            commit=False,
        )

    # Detectar nota agregada (el campo creció)
    if "notas" in body and (snapshot["notas"] or "") != (record.notas or ""):
        old_n = snapshot["notas"] or ""
        new_n = record.notas or ""
        if new_n.startswith(old_n) and len(new_n) > len(old_n):
            # Es un append: extraer solo el delta
            delta = new_n[len(old_n):].strip()
        else:
            delta = new_n
        audit_event(
            db,
            case_id=record.case_id,
            action=EVT_COMPLIANCE_NOTE,
            actor=actor,
            entity_type="compliance",
            entity_id=record.id,
            field_name="notas",
            description=f"Nota agregada{f' ({ord_label})' if ord_label else ''}",
            meta={"delta": delta[:500], "ordinal_nombre": ordinal, "instancia": instancia},
            commit=False,
        )

    # Otros campos (fecha_cumplimiento, plazo_dias, etc.) → un evento genérico
    for field in updatable:
        if field in ("estado", "notas"):
            continue  # ya manejados arriba
        if field in body and snapshot[field] != getattr(record, field):
            audit_event(
                db,
                case_id=record.case_id,
                action=EVT_FIELD_MODIFIED,
                actor=actor,
                entity_type="compliance",
                entity_id=record.id,
                field_name=field,
                old_value=snapshot[field],
                new_value=getattr(record, field),
                description=f"{field}: {snapshot[field]} → {getattr(record, field)}",
                meta={"ordinal_nombre": ordinal, "instancia": instancia},
                commit=False,
            )

    db.commit()

    case = db.query(Case).filter(Case.id == record.case_id).first()
    return _record_to_dict(record, case)


@router.post("/scan")
def api_scan_fallos(db: Session = Depends(get_db)):
    """Escanear casos con fallos desfavorables y crear registros de seguimiento."""
    # Buscar casos con fallo CONCEDE o CONCEDE PARCIALMENTE que no tengan seguimiento
    cases_con_fallo = db.query(Case).filter(
        or_(
            Case.sentido_fallo_1st.ilike("%concede%"),
        ),
        Case.sentido_fallo_1st.notilike("%niega%"),
    ).all()

    # Clave compuesta para evitar duplicados con la extracción v2 (que crea
    # múltiples filas por case, una por orden discreta). El /scan solo crea
    # un placeholder por case_id+instancia (sin ordinal_nombre); si el case
    # ya tiene CUALQUIER fila en compliance_tracking, no crear placeholder.
    existing_case_ids = {r.case_id for r in db.query(ComplianceTracking.case_id).all()}

    created = 0
    for case in cases_con_fallo:
        if case.id in existing_case_ids:
            continue

        record = ComplianceTracking(
            case_id=case.id,
            instancia="1ra" if case.sentido_fallo_1st else "2da",
            sentido_fallo=case.sentido_fallo_1st or case.sentido_fallo_2nd or "",
            fecha_fallo=case.fecha_fallo_1st or case.fecha_fallo_2nd or "",
            responsable=case.oficina_responsable or "",
            impugnado=case.impugnacion or "NO",
            estado="PENDIENTE",
        )

        # Si hay fallo de 2da instancia que CONFIRMA, es más urgente
        if case.sentido_fallo_2nd and "CONFIRMA" in (case.sentido_fallo_2nd or "").upper():
            record.instancia = "2da (CONFIRMADO)"
            record.sentido_fallo = case.sentido_fallo_2nd
            record.fecha_fallo = case.fecha_fallo_2nd or record.fecha_fallo

        # Si fue impugnado, verificar efecto
        if case.impugnacion and case.impugnacion.upper() == "SI":
            record.impugnado = "SI"
            record.estado = "IMPUGNADO"
            # Por defecto asumir que requiere cumplimiento (efecto no suspensivo)
            record.requiere_cumplimiento = "SI"

        db.add(record)
        created += 1

    db.commit()
    return {"created": created, "message": f"{created} seguimientos creados de {len(cases_con_fallo)} fallos desfavorables"}


@router.post("/{record_id}/extract-order")
def api_extract_order(record_id: int, db: Session = Depends(get_db)):
    """Extraer la orden judicial y plazo de la sentencia del caso.

    Estrategia híbrida (2026-05-19):
      1. **Regex first**: `seguimiento_extractor.extract_plazo_cumplimiento` lee head+tail
         del PDF y captura plazos estructurados (cuarenta y ocho (48) horas, 10 días,
         mes calendario, etc.). 100% accuracy validado en gold standard de 18 fallos.
         Si la 2da solo CONFIRMA, hace fallback automático a la sentencia 1ra.
      2. **LLM fallback**: si regex no extrae (plazos no estándar, redacción atípica),
         llama Qwen 3-4B local con prompt minimalista.
    """
    import os
    from pathlib import Path
    from backend.database.models import Document
    from backend.services.seguimiento_extractor import extract_plazo_cumplimiento

    record = db.query(ComplianceTracking).filter(ComplianceTracking.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    case = db.query(Case).filter(Case.id == record.case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    # Buscar documentos de sentencia (PDF en disco)
    sentencias = db.query(Document).filter(
        Document.case_id == case.id,
        or_(
            Document.doc_type.ilike("%SENTENCIA%"),
            Document.doc_type.ilike("%FALLO%"),
            Document.filename.ilike("%sentencia%"),
            Document.filename.ilike("%fallo%"),
            Document.filename.ilike("%confirma%"),
        ),
        Document.filename.ilike("%.pdf"),
    ).order_by(Document.id).all()

    pdfs_disponibles = [d.file_path for d in sentencias if d.file_path and os.path.exists(d.file_path)]

    # — Etapa 1: Regex (preferir PDF según dónde vive la ORDEN) —
    # Regla jurídica (fix 2026-05-19): la orden vive en la sentencia de 1ra
    # instancia SALVO que la 2da REVOQUE o MODIFIQUE. Una 2da que solo CONFIRMA no
    # repite la orden → leer la 1ra (antes preferíamos la 2da y se alucinaba/perdía).
    s2 = (case.sentido_fallo_2nd or "").upper()
    prefer_2da = "REVOCA" in s2 or "MODIFICA" in s2
    def score_2da(p): return ("segunda" in p.lower() or "2da" in p.lower() or "confirma" in p.lower(), "primera" not in p.lower())
    def score_1ra(p): return ("primera" in p.lower() or "primer" in p.lower() or "1ra" in p.lower(), "segunda" not in p.lower())
    pdfs_disponibles.sort(key=score_2da if prefer_2da else score_1ra, reverse=True)

    if pdfs_disponibles:
        main = pdfs_disponibles[0]
        fallback = pdfs_disponibles[1:]
        try:
            regex_result = extract_plazo_cumplimiento(
                main,
                sentido_fallo_1st=case.sentido_fallo_1st,
                sentido_fallo_2nd=case.sentido_fallo_2nd,
                fallback_paths=fallback,
            )
        except Exception:
            regex_result = None
        if regex_result:
            base_fecha = record.fecha_notificacion or record.fecha_fallo
            fecha_limite = None
            if base_fecha:
                try:
                    parts = base_fecha.split("/")
                    base = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                    fecha_limite = (base + timedelta(days=regex_result.plazo_dias)).strftime("%d/%m/%Y")
                except Exception:
                    pass
            record.plazo_dias = regex_result.plazo_dias
            record.orden_judicial = f"[{regex_result.ordinal}] {regex_result.destinatario}: {regex_result.plazo_raw}"
            if not record.responsable:
                record.responsable = regex_result.destinatario[:200]
            if fecha_limite:
                record.fecha_limite = fecha_limite
            record.extraido_por_ia = f"REGEX:{regex_result.source}"
            record.updated_at = utcnow()
            db.commit()
            return {
                "plazo_dias": regex_result.plazo_dias,
                "orden_judicial": record.orden_judicial,
                "responsable": record.responsable,
                "fecha_limite": fecha_limite,
                "source": f"regex ({regex_result.source})",
                "ordinal": regex_result.ordinal,
            }

    # — Etapa 2: LLM fallback (cuando regex no encontró nada) —
    if not sentencias:
        return {"error": "No se encontraron documentos de sentencia en este caso"}

    # Extraer texto de sentencias
    texts = []
    for doc in sentencias:
        if doc.extracted_text:
            texts.append(doc.extracted_text)
        else:
            from backend.extraction.doc_ops import extract_document_text
            text, method = extract_document_text(doc)
            if text:
                doc.extracted_text = text
                doc.extraction_method = method
                texts.append(text)

    if not texts:
        return {"error": "No se pudo extraer texto de las sentencias"}

    # Llamar a la IA local para extraer orden y plazo (versión minimalista LOCAL_ONLY)
    from backend.extraction.ai_extractor import _call_local, _LOCAL_MODEL
    provider = "local"
    model = _LOCAL_MODEL

    prompt_system = """Eres un asistente jurídico experto en acciones de tutela colombianas.
Analiza la sentencia y extrae:
1. ORDEN_JUDICIAL: Qué ordena el juez exactamente (resumen claro en 1-3 oraciones)
2. PLAZO_DIAS: Plazo en días para cumplir (número). Si dice "48 horas" = 2, "10 días" = 10. Si no especifica plazo, pon 0.
3. RESPONSABLE: A quién le ordena cumplir (ej: "Secretaría de Educación Departamental", "Gobernación de Santander")
4. EFECTO: Si menciona efecto de impugnación: SUSPENSIVO / NO_SUSPENSIVO / DEVOLUTIVO

Responde SOLO con JSON:
{"orden_judicial": "...", "plazo_dias": 0, "responsable": "...", "efecto": ""}"""

    all_text = "\n\n".join(texts)
    if len(all_text) > 30000:
        all_text = all_text[:25000] + "\n[...]\n" + all_text[-5000:]

    user_msg = f"""/no_think
CASO: {case.folder_name}

SENTENCIA:
{all_text}

Extrae la orden judicial, plazo y responsable."""

    try:
        messages = [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": user_msg},
        ]
        import json, re
        raw, inp, out = _call_local(messages, model, max_tokens=512)
        # Tolerar texto extra alrededor del JSON
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0) if m else raw)

        record.orden_judicial = data.get("orden_judicial", "")
        record.plazo_dias = int(data.get("plazo_dias", 0)) if data.get("plazo_dias") else None
        record.responsable = data.get("responsable", "") or record.responsable
        record.efecto_impugnacion = data.get("efecto", "") or record.efecto_impugnacion
        record.extraido_por_ia = "SI"

        # Calcular fecha límite si hay plazo y fecha de notificación o fallo
        if record.plazo_dias and record.plazo_dias > 0:
            base_fecha = record.fecha_notificacion or record.fecha_fallo
            if base_fecha:
                try:
                    parts = base_fecha.split("/")
                    base = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
                    limite = base + timedelta(days=record.plazo_dias)
                    record.fecha_limite = limite.strftime("%d/%m/%Y")
                except Exception:
                    pass

        record.updated_at = utcnow()
        db.commit()

        # Registrar token usage (LLM local = costo 0)
        from backend.database.models import TokenUsage
        db.add(TokenUsage(
            provider=provider, model=model,
            tokens_input=inp, tokens_output=out,
            cost_input="0.000000", cost_output="0.000000",
            cost_total="0.000000",
            case_id=case.id, fields_extracted=3,
        ))
        db.commit()

        return {
            "orden_judicial": record.orden_judicial,
            "plazo_dias": record.plazo_dias,
            "fecha_limite": record.fecha_limite,
            "responsable": record.responsable,
            "tokens_used": inp + out,
        }

    except Exception as e:
        return {"error": f"Error al extraer con IA: {str(e)}"}
