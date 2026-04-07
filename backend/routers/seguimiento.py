"""Router de seguimiento de cumplimiento de fallos."""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database.database import get_db
from backend.database.models import Case, ComplianceTracking

router = APIRouter(prefix="/api/seguimiento", tags=["seguimiento"])

COLOMBIA_TZ = timezone(timedelta(hours=-5))


def _calcular_semaforo(record: ComplianceTracking) -> str:
    """Calcular estado semáforo basado en fecha límite."""
    if record.estado == "CUMPLIDO":
        return "CUMPLIDO"
    if record.estado == "IMPUGNADO" and record.requiere_cumplimiento != "SI":
        return "IMPUGNADO"

    if not record.fecha_limite:
        return "SIN_PLAZO"

    try:
        parts = record.fecha_limite.split("/")
        fecha_lim = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
        hoy = datetime.now(COLOMBIA_TZ).replace(tzinfo=None)
        dias_restantes = (fecha_lim - hoy).days

        if dias_restantes < 0:
            return "VENCIDO"
        elif dias_restantes <= 3:
            return "URGENTE"
        elif dias_restantes <= 7:
            return "POR_VENCER"
        else:
            return "EN_PLAZO"
    except Exception:
        return "SIN_PLAZO"


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
    }


@router.get("")
def api_list_seguimiento(
    estado: str = "",
    urgencia: str = "",
    db: Session = Depends(get_db),
):
    """Listar todos los seguimientos con semáforo calculado."""
    query = db.query(ComplianceTracking)

    if estado:
        query = query.filter(ComplianceTracking.estado == estado)

    records = query.order_by(ComplianceTracking.created_at.desc()).all()

    # Precargar casos
    case_ids = {r.case_id for r in records}
    cases = {c.id: c for c in db.query(Case).filter(Case.id.in_(case_ids)).all()} if case_ids else {}

    items = []
    for r in records:
        item = _record_to_dict(r, cases.get(r.case_id))
        # Filtro por urgencia (semáforo)
        if urgencia and item["semaforo"] != urgencia:
            continue
        items.append(item)

    # Ordenar: VENCIDO primero, luego URGENTE, POR_VENCER, EN_PLAZO, CUMPLIDO
    orden = {"VENCIDO": 0, "URGENTE": 1, "POR_VENCER": 2, "EN_PLAZO": 3, "SIN_PLAZO": 4, "IMPUGNADO": 5, "CUMPLIDO": 6}
    items.sort(key=lambda x: orden.get(x["semaforo"], 99))

    # Resumen
    resumen = {
        "total": len(items),
        "vencidos": sum(1 for i in items if i["semaforo"] == "VENCIDO"),
        "urgentes": sum(1 for i in items if i["semaforo"] == "URGENTE"),
        "por_vencer": sum(1 for i in items if i["semaforo"] == "POR_VENCER"),
        "en_plazo": sum(1 for i in items if i["semaforo"] == "EN_PLAZO"),
        "cumplidos": sum(1 for i in items if i["semaforo"] == "CUMPLIDO"),
        "impugnados": sum(1 for i in items if i["semaforo"] == "IMPUGNADO"),
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
def api_update_seguimiento(record_id: int, body: dict, db: Session = Depends(get_db)):
    """Actualizar un seguimiento (estado, notas, fecha cumplimiento, etc.)."""
    record = db.query(ComplianceTracking).filter(ComplianceTracking.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    updatable = [
        "estado", "notas", "fecha_cumplimiento", "fecha_notificacion",
        "fecha_limite", "plazo_dias", "responsable", "orden_judicial",
        "impugnado", "efecto_impugnacion", "requiere_cumplimiento",
    ]
    for field in updatable:
        if field in body:
            setattr(record, field, body[field])

    record.updated_at = datetime.utcnow()
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
    """Usar IA para extraer la orden judicial y plazo de la sentencia del caso."""
    record = db.query(ComplianceTracking).filter(ComplianceTracking.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Registro no encontrado")

    case = db.query(Case).filter(Case.id == record.case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    # Buscar documentos de sentencia
    from backend.database.models import Document
    sentencias = db.query(Document).filter(
        Document.case_id == case.id,
        or_(
            Document.doc_type == "SENTENCIA",
            Document.filename.ilike("%sentencia%"),
            Document.filename.ilike("%fallo%"),
        ),
    ).all()

    if not sentencias:
        return {"error": "No se encontraron documentos de sentencia en este caso"}

    # Extraer texto de sentencias
    texts = []
    for doc in sentencias:
        if doc.extracted_text:
            texts.append(doc.extracted_text)
        else:
            from backend.extraction.pipeline import extract_document_text
            text, method = extract_document_text(doc)
            if text:
                doc.extracted_text = text
                doc.extraction_method = method
                texts.append(text)

    if not texts:
        return {"error": "No se pudo extraer texto de las sentencias"}

    # Llamar a la IA para extraer orden y plazo
    from backend.extraction.ai_extractor import _call_with_retry, get_active_provider

    provider, model = get_active_provider()

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

    user_msg = f"""CASO: {case.folder_name}

SENTENCIA:
{all_text}

Extrae la orden judicial, plazo y responsable."""

    try:
        messages = [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": user_msg},
        ]
        import json
        raw, inp, out = _call_with_retry(provider, messages, model, 1024)
        data = json.loads(raw)

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

        record.updated_at = datetime.utcnow()
        db.commit()

        # Registrar token usage
        from backend.database.models import TokenUsage
        from backend.extraction.ai_extractor import PROVIDERS
        model_info = PROVIDERS.get(provider, {}).get("models", {}).get(model, {})
        cost_in = inp * model_info.get("input_price", 0) / 1_000_000
        cost_out = out * model_info.get("output_price", 0) / 1_000_000
        db.add(TokenUsage(
            provider=provider, model=model,
            tokens_input=inp, tokens_output=out,
            cost_input=f"{cost_in:.6f}", cost_output=f"{cost_out:.6f}",
            cost_total=f"{cost_in + cost_out:.6f}",
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
