"""Herramientas jurídicas del Agente: búsqueda, análisis, generación.

Cada función decorada con @register_tool queda disponible para el agente.
El agente puede invocarlas por nombre desde lenguaje natural o desde el orchestrator.
"""

import json
import re
from datetime import datetime

from sqlalchemy.orm import Session

from backend.agent.tools.registry import register_tool
from backend.database.models import Case, Document, Email, AuditLog


# ============================================================
# SEARCH TOOLS
# ============================================================

@register_tool(
    name="buscar_caso",
    description="Busca casos por radicado, accionante, juzgado o texto libre",
    category="search",
    params={
        "query": "str - texto a buscar (radicado, nombre, juzgado)",
        "limit": "int - máximo resultados (default: 10)",
    },
)
def buscar_caso(db: Session, query: str, limit: int = 10) -> list[dict]:
    q = db.query(Case).filter(
        (Case.folder_name.contains(query)) |
        (Case.accionante.contains(query)) |
        (Case.radicado_23_digitos.contains(query)) |
        (Case.juzgado.contains(query)) |
        (Case.ciudad.contains(query))
    ).limit(limit).all()

    return [
        {"id": c.id, "folder": c.folder_name, "accionante": c.accionante,
         "juzgado": c.juzgado, "ciudad": c.ciudad, "estado": c.estado,
         "fallo": c.sentido_fallo_1st}
        for c in q
    ]


@register_tool(
    name="buscar_conocimiento",
    description="Búsqueda full-text en Knowledge Base (emails, PDFs, DOCX, campos)",
    category="search",
    params={
        "query": "str - texto a buscar",
        "source_type": "str - filtro: email, pdf, docx, db_field, email_md (opcional)",
    },
)
def buscar_conocimiento(db: Session, query: str, source_type: str = None) -> list[dict]:
    from backend.knowledge.search import full_text_search
    results = full_text_search(db, query, limit=15, source_type=source_type)
    return [
        {"case_id": r.case_id, "source": r.source_name, "type": r.source_type,
         "snippet": r.snippet, "rank": r.rank}
        for r in results
    ]


@register_tool(
    name="buscar_email",
    description="Busca emails por subject, remitente o contenido",
    category="search",
    params={"query": "str - texto a buscar en subject/body"},
)
def buscar_email(db: Session, query: str) -> list[dict]:
    emails = db.query(Email).filter(
        (Email.subject.contains(query)) |
        (Email.body_preview.contains(query)) |
        (Email.sender.contains(query))
    ).limit(15).all()

    return [
        {"id": e.id, "subject": e.subject, "sender": e.sender,
         "case_id": e.case_id, "status": e.status,
         "date": e.date_received.isoformat() if e.date_received else ""}
        for e in emails
    ]


# ============================================================
# ANALYSIS TOOLS
# ============================================================

@register_tool(
    name="verificar_plazo",
    description="Verifica el plazo de cumplimiento de un caso específico",
    category="analysis",
    params={"case_id": "int - ID del caso"},
    requires_case_id=True,
)
def verificar_plazo(db: Session, case_id: int) -> dict:
    from backend.intelligence.deadlines import _parse_date
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return {"error": "Caso no encontrado"}

    result = {
        "case_id": case_id,
        "folder": case.folder_name,
        "estado": case.estado,
        "fallo_1ra": case.sentido_fallo_1st,
        "fecha_fallo": case.fecha_fallo_1st,
        "impugnacion": case.impugnacion,
        "incidente": case.incidente,
        "plazo_status": "SIN PLAZO",
    }

    if case.sentido_fallo_1st in ("CONCEDE", "CONCEDE PARCIALMENTE"):
        fecha = _parse_date(case.fecha_fallo_1st)
        if fecha:
            from datetime import timedelta
            deadline = fecha + timedelta(hours=48)
            days_left = (deadline - datetime.now()).days
            result["deadline"] = deadline.isoformat()
            result["days_left"] = days_left
            result["plazo_status"] = "VENCIDO" if days_left < 0 else "URGENTE" if days_left < 3 else "EN PLAZO"

    return result


@register_tool(
    name="predecir_resultado",
    description="Predice el resultado probable de una tutela basado en datos históricos",
    category="analysis",
    params={
        "juzgado": "str - nombre parcial del juzgado (opcional)",
        "derecho": "str - derecho vulnerado (opcional)",
        "ciudad": "str - ciudad/municipio (opcional)",
    },
)
def predecir_resultado(db: Session, juzgado: str = "", derecho: str = "", ciudad: str = "") -> dict:
    from backend.intelligence.analytics import predict_outcome
    return predict_outcome(db, juzgado=juzgado, derecho=derecho, ciudad=ciudad)


@register_tool(
    name="analizar_abogado",
    description="Muestra estadísticas de rendimiento de un abogado",
    category="analysis",
    params={"nombre": "str - nombre parcial del abogado"},
)
def analizar_abogado(db: Session, nombre: str) -> dict:
    cases = db.query(Case).filter(Case.abogado_responsable.contains(nombre)).all()
    if not cases:
        return {"error": f"No se encontraron casos para '{nombre}'"}

    total = len(cases)
    activos = sum(1 for c in cases if c.estado == "ACTIVO")
    with_fallo = [c for c in cases if c.sentido_fallo_1st]
    favorables = sum(1 for c in with_fallo if c.sentido_fallo_1st in ("NIEGA", "IMPROCEDENTE"))
    desacatos = sum(1 for c in cases if c.incidente == "SI")

    return {
        "abogado": nombre,
        "total_casos": total,
        "activos": activos,
        "con_fallo": len(with_fallo),
        "favorables": favorables,
        "tasa_favorabilidad": round(favorables / max(len(with_fallo), 1) * 100, 1),
        "desacatos": desacatos,
    }


@register_tool(
    name="obtener_contexto",
    description="Obtiene el contexto completo de un caso (todos los documentos, emails, datos)",
    category="analysis",
    params={"case_id": "int - ID del caso"},
    requires_case_id=True,
)
def obtener_contexto(db: Session, case_id: int) -> dict:
    from backend.agent.context import ContextAssembler
    from backend.core.settings import settings
    assembler = ContextAssembler(db, settings.BASE_DIR)
    ctx = assembler.assemble(case_id)
    return {
        "case_id": case_id,
        "folder": ctx.folder_name,
        "known_fields": len(ctx.known_fields),
        "documents": len(ctx.documents),
        "emails": len(ctx.emails),
        "related_cases": len(ctx.related_cases),
        "tokens_estimate": ctx.total_tokens_estimate,
        "fields": ctx.known_fields,
    }


@register_tool(
    name="ver_razonamiento",
    description="Muestra la cadena de razonamiento de la última extracción de un caso",
    category="analysis",
    params={"case_id": "int - ID del caso"},
    requires_case_id=True,
)
def ver_razonamiento(db: Session, case_id: int) -> list[dict]:
    from backend.agent.reasoning import get_reasoning
    return get_reasoning(db, case_id)


# ============================================================
# MANAGEMENT TOOLS
# ============================================================

@register_tool(
    name="listar_alertas",
    description="Lista alertas activas del sistema (plazos, anomalías, emails sin caso)",
    category="management",
    params={
        "severity": "str - filtro: CRITICAL, WARNING, INFO (opcional)",
    },
)
def listar_alertas(db: Session, severity: str = None) -> list[dict]:
    from backend.alerts.detector import get_alerts
    return get_alerts(db, status="NEW", severity=severity, limit=20)


@register_tool(
    name="escanear_alertas",
    description="Ejecuta escaneo de alertas: detecta plazos vencidos, anomalías, emails sin caso",
    category="management",
)
def escanear_alertas(db: Session) -> dict:
    from backend.alerts.detector import run_detection
    return run_detection(db)


@register_tool(
    name="estadisticas_generales",
    description="Muestra estadísticas generales del sistema con KPIs v5.0 de salud: casos por status, "
                "folders problemáticos, documentos sospechosos, pares duplicados detectados",
    category="management",
)
def estadisticas_generales(db: Session) -> dict:
    from sqlalchemy import func
    active_filter = db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
        Case.processing_status != "DUPLICATE_MERGED",
    )
    total_cases = active_filter.count()
    activos = active_filter.filter(Case.estado == "ACTIVO").count()
    total_docs = db.query(Document).count()
    total_emails = db.query(Email).count()
    emails_sin_caso = db.query(Email).filter(Email.case_id.is_(None), Email.status != "IGNORADO").count()

    with_fallo = active_filter.filter(Case.sentido_fallo_1st.isnot(None), Case.sentido_fallo_1st != "").all()
    concede = sum(1 for c in with_fallo if c.sentido_fallo_1st in ("CONCEDE", "CONCEDE PARCIALMENTE"))
    niega = sum(1 for c in with_fallo if c.sentido_fallo_1st in ("NIEGA", "IMPROCEDENTE"))

    # v5.1: KPIs de status y salud
    status_dist = {}
    for row in db.query(Case.processing_status, func.count(Case.id)).group_by(Case.processing_status).all():
        status_dist[row[0] or "NULL"] = row[1]

    # Folders [PENDIENTE REVISION] activos (v5.0 debe ser 0)
    folders_pendiente = db.query(Case).filter(
        Case.folder_name.like("%PENDIENTE%"),
        Case.processing_status != "DUPLICATE_MERGED",
    ).count()

    # COMPLETO sin rad23 (v5.0 debe ser 0)
    completo_sin_rad23 = db.query(Case).filter(
        Case.processing_status == "COMPLETO",
        (Case.radicado_23_digitos.is_(None)) | (Case.radicado_23_digitos == ""),
    ).count()

    # Docs por verificacion
    verif_dist = {}
    for row in db.query(Document.verificacion, func.count(Document.id)).group_by(Document.verificacion).all():
        verif_dist[row[0] or "NULL"] = row[1]

    from backend.knowledge.search import get_stats as kb_stats
    kb = kb_stats(db)

    return {
        "casos": {
            "total": total_cases, "activos": activos, "inactivos": total_cases - activos,
            "por_status": status_dist,
        },
        "salud_v50": {
            "folders_pendiente_revision_activos": folders_pendiente,
            "completo_sin_rad23": completo_sin_rad23,
        },
        "documentos": {"total": total_docs, "por_verificacion": verif_dist},
        "emails": {"total": total_emails, "sin_caso": emails_sin_caso},
        "fallos": {"total": len(with_fallo), "concede": concede, "niega": niega,
                   "tasa_favorabilidad": round(niega / max(len(with_fallo), 1) * 100, 1)},
        "knowledge_base": kb,
    }


# ═══════════════════════════════════════════════════════════
# v5.1: Tools de salud y cleanup
# ═══════════════════════════════════════════════════════════

@register_tool(
    name="diagnosticar_salud",
    description="Diagnóstico completo de la salud de los datos (v5.0 KPIs): folders mal formados, "
                "COMPLETO sin rad23, obs contaminadas, pares duplicados, docs sospechosos top. "
                "Devuelve summary + detalles accionables.",
    category="diagnostic",
)
def diagnosticar_salud(db: Session) -> dict:
    from backend.routers.cleanup import api_cleanup_health
    return api_cleanup_health(db)


@register_tool(
    name="detectar_duplicados",
    description="Detecta pares de casos con mismo radicado judicial (rad_corto) validando juzgado. "
                "Lista cada par con accionantes y folder_names para que el usuario decida consolidar.",
    category="diagnostic",
)
def detectar_duplicados(db: Session) -> dict:
    import re as _re
    all_cases = db.query(Case).filter(Case.processing_status != "DUPLICATE_MERGED").all()
    by_rad_corto = {}
    for c in all_cases:
        if not c.radicado_23_digitos:
            continue
        digits = _re.sub(r"\D", "", c.radicado_23_digitos)
        m = _re.search(r"(20\d{2})(\d{5})\d{2}$", digits)
        if not m:
            continue
        rc = f"{m.group(1)}-{m.group(2)}"
        juzgado = digits[5:12] if len(digits) >= 12 else ""
        key = (rc, juzgado)  # mismo rad_corto + mismo juzgado → duplicado real
        by_rad_corto.setdefault(key, []).append(c)

    duplicates = []
    for (rc, juz), cases in by_rad_corto.items():
        if len(cases) <= 1:
            continue
        duplicates.append({
            "rad_corto": rc,
            "juzgado_code": juz,
            "cases": [{
                "id": c.id, "folder_name": c.folder_name,
                "accionante": c.accionante, "status": c.processing_status,
                "updated_at": str(c.updated_at) if c.updated_at else None,
            } for c in cases],
        })
    return {"total_pares": len(duplicates), "duplicados": duplicates}


@register_tool(
    name="reconciliar_db",
    description="Reconcilia inconsistencias históricas: mueve docs/emails de casos DUPLICATE_MERGED a "
                "su canónico y sincroniza file_paths desalineados. Pasar dry_run=true primero.",
    category="cleanup",
    params={
        "dry_run": "bool - true para preview sin cambios, false para aplicar (default: true)",
    },
)
def reconciliar_db(db: Session, dry_run: bool = True) -> dict:
    from backend.services.reconcile_db import reconcile_db as _reconcile
    return _reconcile(db, dry_run=bool(dry_run))


@register_tool(
    name="verificar_rad23_integrity",
    description="Verifica integridad del radicado 23 dígitos de un caso o del universo completo. "
                "Detecta folders con rad_corto que no corresponde al rad23 oficial (bug B1).",
    category="diagnostic",
    params={
        "case_id": "int - caso específico a verificar (opcional; si se omite, audita toda la DB)",
    },
)
def verificar_rad23_integrity(db: Session, case_id: int = 0) -> dict:
    import re as _re

    def rad_corto_from_23(rad23):
        if not rad23: return None
        digits = _re.sub(r"\D", "", rad23)
        m = _re.search(r"(20\d{2})(\d{5})\d{2}$", digits)
        return f"{m.group(1)}-{m.group(2)}" if m else None

    q = db.query(Case).filter(Case.processing_status != "DUPLICATE_MERGED")
    if case_id:
        q = q.filter(Case.id == int(case_id))
    cases = q.all()

    issues = []
    for c in cases:
        if not c.folder_name:
            continue
        fm = _re.match(r"(20\d{2})-0*(\d{1,6})", c.folder_name)
        if not fm:
            continue
        rc_folder = f"{fm.group(1)}-{int(fm.group(2)):05d}"
        rc_off = rad_corto_from_23(c.radicado_23_digitos)
        if not rc_off:
            if c.processing_status == "COMPLETO":
                issues.append({
                    "case_id": c.id, "folder": c.folder_name,
                    "severity": "high", "issue": "COMPLETO sin rad23 valido",
                })
            continue
        if rc_folder != rc_off:
            forest_clean = _re.sub(r"\D", "", c.radicado_forest or "")
            seq = int(fm.group(2))
            folder_from_forest = (forest_clean and str(seq) in forest_clean) or (not forest_clean and seq >= 10000)
            severity = "high" if folder_from_forest else "medium"
            issues.append({
                "case_id": c.id, "folder": c.folder_name,
                "rad_corto_folder": rc_folder, "rad_corto_oficial": rc_off,
                "severity": severity,
                "issue": "Folder B1 (viene de FOREST)" if folder_from_forest else "Folder divergente de rad23",
            })

    return {
        "total_cases_checked": len(cases),
        "total_issues": len(issues),
        "issues": issues[:50],
    }


@register_tool(
    name="re_ocr_pending",
    description="Re-ejecuta OCR sobre documentos con verificacion=PENDIENTE_OCR (PDFs escaneados). "
                "Actualiza extracted_text y cambia a OK/REVISAR según resultado.",
    category="cleanup",
    params={
        "limit": "int - máximo de docs a procesar (default: 10, usar 0 para todos)",
    },
)
def re_ocr_pending(db: Session, limit: int = 10) -> dict:
    try:
        from backend.extraction.document_normalizer import normalize_pdf_lightweight
    except ImportError as e:
        return {"error": f"No disponible: {e}"}
    from pathlib import Path as _P
    q = db.query(Document).filter(Document.verificacion == "PENDIENTE_OCR")
    if limit:
        q = q.limit(int(limit))
    docs = q.all()

    updated_ok = 0
    updated_revisar = 0
    failed = 0
    for doc in docs:
        if not doc.file_path or not _P(doc.file_path).is_file():
            failed += 1
            continue
        try:
            result = normalize_pdf_lightweight(doc.file_path)
            text = (result.text or "").strip()
            if len(text) >= 50:
                doc.extracted_text = text
                doc.extraction_method = result.method or "ocr_reocr_v51"
                doc.verificacion = "OK"
                doc.verificacion_detalle = f"Re-OCR v5.1: {len(text)} chars"
                updated_ok += 1
            else:
                doc.verificacion = "REVISAR"
                doc.verificacion_detalle = f"Re-OCR v5.1: insuficiente ({len(text)} chars)"
                updated_revisar += 1
        except Exception:
            failed += 1
    db.commit()
    return {
        "total_processed": len(docs),
        "recovered_ok": updated_ok,
        "still_insufficient": updated_revisar,
        "failed": failed,
    }


@register_tool(
    name="resolver_sospechosos",
    description="Re-ejecuta verify_document_belongs sobre documentos SOSPECHOSO/REVISAR con los datos "
                "actualizados del caso (post v5.0). Algunos quedan OK si el caso ganó rad23 nuevo.",
    category="cleanup",
    params={
        "limit": "int - máximo de docs a procesar (default: 50, usar 0 para todos)",
        "include_revisar": "bool - si incluir también verificacion=REVISAR (default: true)",
    },
)
def resolver_sospechosos(db: Session, limit: int = 50, include_revisar: bool = True) -> dict:
    from backend.extraction.pipeline import verify_document_belongs as _verify
    statuses = ["SOSPECHOSO"] + (["REVISAR"] if include_revisar else [])
    q = db.query(Document).filter(Document.verificacion.in_(statuses))
    if limit:
        q = q.limit(int(limit))
    docs = q.all()

    transitions = {}
    for doc in docs:
        case = db.query(Case).filter(Case.id == doc.case_id).first()
        if not case:
            continue
        old = doc.verificacion
        try:
            new_status, new_detail = _verify(case, doc)
        except Exception:
            continue
        transitions[(old, new_status)] = transitions.get((old, new_status), 0) + 1
        if new_status != old:
            doc.verificacion = new_status
            doc.verificacion_detalle = f"Re-verify v5.1: {new_detail[:180]}"
    db.commit()
    return {
        "total_reviewed": len(docs),
        "transitions": {f"{o}→{n}": c for (o, n), c in transitions.items()},
    }


@register_tool(
    name="analizar_forense_carpeta",
    description="v5.2: análisis forense de una carpeta (sin IA). Extrae identificadores, entidades, "
                "tipos de documento y busca caso destino en DB. Emula el proceso cognitivo humano.",
    category="diagnostic",
    params={
        "folder_path": "str - ruta absoluta de la carpeta a analizar",
    },
)
def analizar_forense_carpeta(db, folder_path: str) -> dict:
    from backend.services.folder_correlator import correlate_folder, find_case_for_group
    result = correlate_folder(folder_path)
    if "error" in result:
        return result
    # Para cada grupo, buscar caso destino
    for idx, group in enumerate(result["groups"]):
        match = find_case_for_group(db, group)
        result.setdefault("dest_suggestions", []).append({
            "group_index": idx,
            "files": [a.filename for a in group],
            "accionantes": list({a.accionante for a in group if a.accionante}),
            "ccs": list({a.cc_accionante for a in group if a.cc_accionante}),
            "suggested_case": match,
        })
    # Serializar groups (DocumentAnalysis no es JSON)
    result["groups_summary"] = [
        [{"filename": a.filename, "type": a.primary_type,
          "accionante": a.accionante, "cc": a.cc_accionante,
          "rad23": a.rad23} for a in group]
        for group in result["groups"]
    ]
    del result["groups"]
    return result


@register_tool(
    name="analizar_forense_documento",
    description="v5.2: análisis forense de un solo documento (PDF/DOCX). Devuelve tipo, identificadores "
                "y entidades extraídas mecánicamente (sin IA).",
    category="diagnostic",
    params={
        "file_path": "str - ruta absoluta del archivo",
    },
    requires_db=False,
)
def analizar_forense_documento(file_path: str) -> dict:
    from backend.services.forensic_analyzer import analyze_document
    a = analyze_document(file_path)
    return {
        "filename": a.filename,
        "has_text": a.has_text,
        "text_length": a.text_length,
        "primary_type": a.primary_type,
        "all_types": a.doc_types,
        "accionante": a.accionante,
        "cc_accionante": a.cc_accionante,
        "rad23": a.rad23,
        "identifiers": a.identifiers,
        "entities": a.entities,
    }


@register_tool(
    name="consolidar_duplicados",
    description="Fusiona dos casos duplicados (mismo radicado): mueve docs/emails del secundario al "
                "canónico y marca el secundario como DUPLICATE_MERGED. Requiere IDs explícitos.",
    category="cleanup",
    params={
        "canonical_id": "int - ID del caso que permanece activo",
        "duplicate_id": "int - ID del caso que se marca DUPLICATE_MERGED",
    },
)
def consolidar_duplicados(db: Session, canonical_id: int, duplicate_id: int) -> dict:
    canon = db.query(Case).filter(Case.id == int(canonical_id)).first()
    dup = db.query(Case).filter(Case.id == int(duplicate_id)).first()
    if not canon or not dup:
        return {"error": "canonical_id o duplicate_id no encontrado"}
    if canon.processing_status == "DUPLICATE_MERGED":
        return {"error": "canonical es DUPLICATE_MERGED — usar otro como canónico"}

    docs_moved = db.query(Document).filter(Document.case_id == dup.id).update(
        {"case_id": canon.id}, synchronize_session=False,
    )
    emails_moved = db.query(Email).filter(Email.case_id == dup.id).update(
        {"case_id": canon.id}, synchronize_session=False,
    )
    dup.processing_status = "DUPLICATE_MERGED"
    dup.observaciones = (dup.observaciones or "") + f" | AGENT_MERGE_V51: canonical=id{canon.id}"
    db.add(AuditLog(
        case_id=duplicate_id, field_name="processing_status",
        old_value="COMPLETO", new_value="DUPLICATE_MERGED",
        action="AGENT_MERGE_V51", source=f"canonical=id{canonical_id}",
    ))
    db.commit()
    return {
        "canonical_id": canonical_id,
        "duplicate_id": duplicate_id,
        "docs_moved": docs_moved,
        "emails_moved": emails_moved,
        "status": "ok",
    }


@register_tool(
    name="consultar_cuadro",
    description="Consulta los datos del Cuadro de Tutelas (misma info que ve el usuario en pantalla). "
                "Puede filtrar por cualquier campo: accionante, juzgado, ciudad, estado, fallo, abogado, radicado, etc.",
    category="search",
    params={
        "filtro": "str - texto para buscar en cualquier campo (accionante, juzgado, ciudad, radicado, etc.)",
        "campo": "str - campo específico a filtrar: ACCIONANTE, JUZGADO, CIUDAD, ESTADO, SENTIDO_FALLO_1ST, ABOGADO_RESPONSABLE, IMPUGNACION, INCIDENTE (opcional)",
        "valor": "str - valor exacto del campo para filtrar (opcional, usa con 'campo')",
        "limit": "int - máximo resultados (default: 20)",
    },
)
def consultar_cuadro(db: Session, filtro: str = "", campo: str = "", valor: str = "", limit: int = 20) -> dict:
    """Devuelve datos del cuadro de tutelas con los mismos campos que ve el usuario."""
    cases = db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
        Case.processing_status != "DUPLICATE_MERGED",
    ).order_by(Case.id.desc()).all()

    items = []
    for c in cases:
        data = {"id": c.id, "tipo_actuacion": c.tipo_actuacion or "TUTELA"}
        filled = 0
        for csv_col, attr in Case.CSV_FIELD_MAP.items():
            val = getattr(c, attr) or ""
            data[csv_col] = val
            if val.strip():
                filled += 1
        data["completitud"] = round(filled / len(Case.CSV_FIELD_MAP) * 100)
        items.append(data)

    # Filtro por campo específico
    if campo and valor:
        campo_upper = campo.upper()
        valor_upper = valor.upper()
        items = [r for r in items if valor_upper in str(r.get(campo_upper, "")).upper()]

    # Filtro general (busca en todos los campos)
    if filtro:
        filtro_lower = filtro.lower()
        items = [r for r in items if any(filtro_lower in str(v).lower() for v in r.values())]

    total = len(items)
    items = items[:limit]

    return {
        "total_encontrados": total,
        "mostrando": len(items),
        "casos": items,
    }


@register_tool(
    name="casos_por_municipio",
    description="Lista casos agrupados por municipio/ciudad",
    category="management",
    params={"ciudad": "str - filtro por ciudad (opcional)"},
)
def casos_por_municipio(db: Session, ciudad: str = "") -> list[dict]:
    from collections import Counter
    cases = db.query(Case).filter(Case.ciudad.isnot(None), Case.ciudad != "").all()
    if ciudad:
        cases = [c for c in cases if ciudad.upper() in (c.ciudad or "").upper()]

    by_city = Counter((c.ciudad or "").strip() for c in cases)
    return [{"ciudad": c, "count": n} for c, n in by_city.most_common(30)]


# ============================================================
# EXTRACTION TOOLS
# ============================================================

@register_tool(
    name="extraer_caso",
    description="Ejecuta extracción inteligente con el Agente IA v3 para un caso",
    category="extraction",
    params={"case_id": "int - ID del caso a extraer"},
    requires_case_id=True,
)
def extraer_caso(db: Session, case_id: int) -> dict:
    from backend.agent.orchestrator import smart_extract_case
    from backend.core.settings import settings
    return smart_extract_case(db, case_id, settings.BASE_DIR)


@register_tool(
    name="consumo_tokens",
    description="Muestra consumo de tokens, costo, ahorro vs APIs de pago, y tips de optimizacion",
    category="management",
)
def consumo_tokens(db: Session) -> dict:
    from backend.agent.token_manager import get_savings_report
    return get_savings_report(db)


@register_tool(
    name="validar_forest",
    description="Valida si un número FOREST es real o alucinado",
    category="extraction",
    params={"forest": "str - número FOREST a validar"},
    requires_db=False,
)
def validar_forest(forest: str) -> dict:
    from backend.agent.forest_extractor import is_valid_forest, FOREST_BLACKLIST
    is_valid = is_valid_forest(forest)
    return {
        "forest": forest,
        "valid": is_valid,
        "in_blacklist": forest in FOREST_BLACKLIST,
        "starts_with_68": forest.startswith("68"),
        "length": len(forest),
    }


@register_tool(
    name="contar_por_categoria",
    description="Cuenta tutelas por categoría temática (INFRAESTRUCTURA, INCLUSION, NOMBRAMIENTOS, "
                "TRASLADOS, TUTOR_SOMBRA, INTERPRETES, DEBIDO_PROCESO, SALUD, COBERTURA, "
                "CARRERA_DOCENTE, NOMINA, PRESTACIONES, RESIDENCIA_ESCOLAR, DERECHO_PETICION, GENERAL). "
                "Muestra qué oficina de la Secretaría de Educación es responsable de cada tema.",
    category="search",
    params={
        "categoria": "str - categoría a consultar (opcional, sin ella muestra todas)",
    },
)
def contar_por_categoria(db: Session, categoria: str = "") -> dict:
    from collections import Counter
    from backend.extraction.thematic_classifier import suggest_oficina

    cases = db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
        Case.processing_status != "DUPLICATE_MERGED",
    ).all()

    if categoria:
        cat_upper = categoria.upper().replace(" ", "_")
        matches = [c for c in cases if (c.categoria_tematica or "").upper() == cat_upper]
        return {
            "categoria": cat_upper,
            "oficina_responsable": suggest_oficina(cat_upper),
            "total": len(matches),
            "casos": [
                {"id": c.id, "accionante": c.accionante, "juzgado": c.juzgado,
                 "ciudad": c.ciudad, "fallo": c.sentido_fallo_1st,
                 "observaciones": (c.observaciones or "")[:200]}
                for c in matches[:20]
            ],
        }

    counts = Counter((c.categoria_tematica or "GENERAL") for c in cases)
    return {
        "total_casos": len(cases),
        "por_categoria": [
            {"categoria": cat, "count": n, "oficina": suggest_oficina(cat)}
            for cat, n in counts.most_common()
        ],
    }


@register_tool(
    name="info_secretaria",
    description="Información sobre la Secretaría de Educación de Santander: organigrama, "
                "direcciones, grupos de trabajo, directores, contactos.",
    category="management",
)
def info_secretaria(db: Session) -> dict:
    from backend.agent.knowledge_sec import SEC_INFO
    return {
        "secretaria": SEC_INFO["secretaria"],
        "email": SEC_INFO["email"],
        "telefono": SEC_INFO["telefono"],
        "direcciones": {
            name: {"director": info["director"], "funcion": info["funcion"], "grupos": info["grupos"]}
            for name, info in SEC_INFO["direcciones"].items()
        },
        "grupo_juridico": SEC_INFO["grupo_juridico"],
    }
