"""Logica de negocio para casos de tutela."""

from datetime import datetime
from sqlalchemy.orm import Session, subqueryload
from sqlalchemy import func, or_

from backend.database.models import Case, Document, AuditLog
from backend.services.normalizer import (
    normalize_abogado, normalize_ciudad, categorize_decision_incidente,
    get_fallo_definitivo, group_by_normalized,
)


def list_cases(
    db: Session,
    search: str = "",
    estado: str = "",
    fallo: str = "",
    abogado: str = "",
    ciudad: str = "",
    status: str = "",
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Listar casos con filtros y paginacion."""
    query = db.query(Case).filter(
        Case.folder_name.isnot(None),
        Case.folder_name != "None",
        Case.folder_name != "",
    )

    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            Case.accionante.ilike(term),
            Case.radicado_23_digitos.ilike(term),
            Case.radicado_forest.ilike(term),
            Case.folder_name.ilike(term),
            Case.observaciones.ilike(term),
            Case.accionados.ilike(term),
        ))

    if estado:
        query = query.filter(Case.estado.ilike(estado))
    if fallo:
        query = query.filter(Case.sentido_fallo_1st.ilike(f"%{fallo}%"))
    if abogado:
        query = query.filter(Case.abogado_responsable.ilike(f"%{abogado}%"))
    if ciudad:
        query = query.filter(Case.ciudad.ilike(f"%{ciudad}%"))
    if status:
        query = query.filter(Case.processing_status == status)

    total = query.count()
    cases = query.order_by(Case.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "items": [c.to_dict() for c in cases],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


def get_case(db: Session, case_id: int) -> dict | None:
    """Obtener un caso con todos sus documentos."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return None

    data = case.to_dict()
    data["documents"] = [d.to_dict() for d in case.documents]
    data["audit_log"] = [
        {
            "id": a.id,
            "field_name": a.field_name,
            "old_value": a.old_value,
            "new_value": a.new_value,
            "action": a.action,
            "source": a.source,
            "timestamp": a.timestamp.isoformat() if a.timestamp else None,
        }
        for a in sorted(case.audit_logs, key=lambda x: x.timestamp or datetime.min, reverse=True)[:50]
    ]
    return data


def update_case(db: Session, case_id: int, fields: dict) -> dict | None:
    """Actualizar campos de un caso con registro de auditoria."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return None

    for csv_col, new_value in fields.items():
        attr = Case.CSV_FIELD_MAP.get(csv_col)
        if not attr:
            continue

        old_value = getattr(case, attr) or ""
        new_value = str(new_value).strip()

        if old_value != new_value:
            setattr(case, attr, new_value)
            db.add(AuditLog(
                case_id=case.id,
                field_name=csv_col,
                old_value=old_value,
                new_value=new_value,
                action="EDICION_MANUAL",
                source="usuario",
            ))
            # Record correction for agent learning
            try:
                from backend.agent.memory import record_correction
                record_correction(db, case.id, csv_col, old_value, new_value, case.folder_name or "")
            except Exception:
                pass

    case.updated_at = datetime.utcnow()
    db.commit()
    return get_case(db, case_id)


def _real_cases_filter():
    """Filtro para excluir casos fantasma (sin carpeta real)."""
    return [Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != ""]


def get_dashboard_kpis(db: Session) -> dict:
    """Calcular KPIs para el dashboard (excluye casos fantasma, métricas inteligentes)."""
    base = db.query(Case).filter(*_real_cases_filter())
    all_cases = base.all()
    total = len(all_cases)

    activos = sum(1 for c in all_cases if (c.estado or "").upper() == "ACTIVO")
    inactivos = sum(1 for c in all_cases if (c.estado or "").upper() == "INACTIVO")

    # Favorabilidad REAL considerando 2da instancia
    fallos = {"DESFAVORABLE": 0, "FAVORABLE": 0, "IMPROCEDENTE": 0, "MODIFICADO": 0,
              "SIN FALLO": 0, "DESISTIMIENTO": 0, "OTRO": 0}
    for c in all_cases:
        fallo_def, _ = get_fallo_definitivo(c.sentido_fallo_1st, c.sentido_fallo_2nd)
        fallos[fallo_def] = fallos.get(fallo_def, 0) + 1

    # Impugnaciones: resueltas vs pendientes
    con_impugnacion = sum(1 for c in all_cases if (c.impugnacion or "").upper() == "SI")
    imp_con_fallo_2nd = sum(1 for c in all_cases
                            if (c.impugnacion or "").upper() == "SI"
                            and (c.sentido_fallo_2nd or "").strip())
    imp_pendientes = con_impugnacion - imp_con_fallo_2nd

    # Incidentes/desacatos categorizados
    con_incidente = sum(1 for c in all_cases if (c.incidente or "").upper() == "SI")
    desacatos_cat = {"SANCIONADO": 0, "EN CONSULTA": 0, "EN TRÁMITE": 0,
                     "CUMPLIDO": 0, "ARCHIVADO": 0, "PENDIENTE": 0, "OTRO": 0}
    for c in all_cases:
        if (c.incidente or "").upper() == "SI":
            cat = categorize_decision_incidente(c.decision_incidente, c.observaciones)
            desacatos_cat[cat] = desacatos_cat.get(cat, 0) + 1

    # Completitud
    n_fields = len(Case.CSV_FIELD_MAP)
    total_fields = total * n_fields
    filled_fields = 0
    gf = _real_cases_filter()
    for attr in Case.CSV_FIELD_MAP.values():
        col = getattr(Case, attr)
        filled_fields += db.query(func.count(Case.id)).filter(
            *gf, col.isnot(None), col != ""
        ).scalar()
    completitud = round(filled_fields / total_fields * 100, 1) if total_fields > 0 else 0

    # Tipo de actuación
    tutelas_unicas = sum(1 for c in all_cases if (c.tipo_actuacion or "TUTELA") == "TUTELA")
    total_incidentes = sum(1 for c in all_cases if (c.tipo_actuacion or "") == "INCIDENTE")

    # Fallo 1ra instancia (para compatibilidad)
    concede = sum(1 for c in all_cases if "CONCEDE" in (c.sentido_fallo_1st or "").upper())
    niega = sum(1 for c in all_cases if "NIEGA" in (c.sentido_fallo_1st or "").upper())
    improcedente_count = sum(1 for c in all_cases if "IMPROCEDENTE" in (c.sentido_fallo_1st or "").upper())

    return {
        "total": total,
        "total_casos": total,
        "tutelas_unicas": tutelas_unicas,
        "total_incidentes": total_incidentes,
        "activos": activos,
        "inactivos": inactivos,
        "sin_estado": total - activos - inactivos,
        # Fallo 1ra instancia (simple)
        "concede": concede,
        "niega": niega,
        "improcedente": improcedente_count,
        "sin_fallo": fallos.get("SIN FALLO", 0),
        # Favorabilidad REAL (considerando 2da instancia)
        "favorabilidad": {
            "desfavorable": fallos.get("DESFAVORABLE", 0),
            "favorable": fallos.get("FAVORABLE", 0),
            "improcedente": fallos.get("IMPROCEDENTE", 0),
            "modificado": fallos.get("MODIFICADO", 0),
            "sin_fallo": fallos.get("SIN FALLO", 0),
            "desistimiento": fallos.get("DESISTIMIENTO", 0),
            "tooltip": "Fallo definitivo: si hay 2da instancia que REVOCA, se considera favorable aunque en 1ra fue desfavorable",
        },
        # Impugnaciones detalladas
        "con_impugnacion": con_impugnacion,
        "impugnaciones_resueltas": imp_con_fallo_2nd,
        "impugnaciones_pendientes": imp_pendientes,
        # Incidentes detallados
        "con_incidente": con_incidente,
        "desacatos": desacatos_cat,
        # Procesamiento
        "pendientes_extraccion": sum(1 for c in all_cases if c.processing_status == "PENDIENTE"),
        "completos": sum(1 for c in all_cases if c.processing_status == "COMPLETO"),
        "completitud": completitud,
        "completitud_campos": completitud,
        "campos_llenos": filled_fields,
        # Calidad
        "calidad": _get_quality_metrics(db),
    }


def _get_quality_metrics(db: Session) -> dict:
    """Calcular métricas de calidad y confiabilidad de datos."""
    from backend.database.models import Document, Extraction

    gf = _real_cases_filter()

    # Documentos verificados
    total_docs = db.query(func.count(Document.id)).join(Case).filter(*gf).scalar()
    docs_ok = db.query(func.count(Document.id)).join(Case).filter(*gf, Document.verificacion == "OK").scalar()
    docs_sospechosos = db.query(func.count(Document.id)).join(Case).filter(*gf, Document.verificacion == "SOSPECHOSO").scalar()
    docs_no_verificados = db.query(func.count(Document.id)).join(Case).filter(
        *gf, or_(Document.verificacion.is_(None), Document.verificacion == "")
    ).scalar()

    # Confianza de extracciones
    ext_alta = db.query(func.count(Extraction.id)).filter(Extraction.confidence == "ALTA").scalar()
    ext_media = db.query(func.count(Extraction.id)).filter(Extraction.confidence == "MEDIA").scalar()
    ext_baja = db.query(func.count(Extraction.id)).filter(Extraction.confidence == "BAJA").scalar()
    ext_total = ext_alta + ext_media + ext_baja

    # Calcular score de confiabilidad (0-100)
    doc_score = round(docs_ok / total_docs * 100, 1) if total_docs > 0 else 0
    ext_score = round((ext_alta * 1.0 + ext_media * 0.7 + ext_baja * 0.3) / ext_total * 100, 1) if ext_total > 0 else 0

    # Campos críticos con datos
    base = db.query(Case).filter(*gf)
    total_cases = base.count()
    campos_criticos = {
        "radicado_23": base.filter(Case.radicado_23_digitos.isnot(None), Case.radicado_23_digitos != "").count(),
        "accionante": base.filter(Case.accionante.isnot(None), Case.accionante != "").count(),
        "juzgado": base.filter(Case.juzgado.isnot(None), Case.juzgado != "").count(),
        "fallo": base.filter(Case.sentido_fallo_1st.isnot(None), Case.sentido_fallo_1st != "").count(),
        "forest": base.filter(Case.radicado_forest.isnot(None), Case.radicado_forest != "").count(),
    }

    confiabilidad = round((doc_score * 0.3 + ext_score * 0.3 + (sum(campos_criticos.values()) / (total_cases * 5) * 100) * 0.4), 1) if total_cases > 0 else 0

    return {
        "confiabilidad": confiabilidad,
        "docs_total": total_docs,
        "docs_ok": docs_ok,
        "docs_sospechosos": docs_sospechosos,
        "docs_no_verificados": docs_no_verificados,
        "extracciones_alta": ext_alta,
        "extracciones_media": ext_media,
        "extracciones_baja": ext_baja,
        "campos_criticos": campos_criticos,
    }


def get_chart_data(db: Session) -> dict:
    """Datos para graficos del dashboard (queries SQL optimizadas, excluye fantasma)."""
    gf = _real_cases_filter()

    # Por ciudad — normalizar con normalize_ciudad()
    raw_cities = db.query(Case.ciudad, func.count(Case.id)).filter(
        *gf, Case.ciudad.isnot(None), Case.ciudad != ""
    ).group_by(Case.ciudad).all()
    city_rows = group_by_normalized(raw_cities, normalize_ciudad)[:10]

    # Por abogado — normalizar con normalize_abogado()
    raw_lawyers = db.query(Case.abogado_responsable, func.count(Case.id)).filter(
        *gf, Case.abogado_responsable.isnot(None), Case.abogado_responsable != ""
    ).group_by(Case.abogado_responsable).all()
    lawyer_rows = group_by_normalized(raw_lawyers, normalize_abogado)[:10]

    # Por fallo
    base = db.query(Case).filter(*gf)
    total = base.count()
    concede = base.filter(Case.sentido_fallo_1st.ilike("%concede%")).count()
    niega = base.filter(Case.sentido_fallo_1st.ilike("%niega%")).count()
    improcedente = base.filter(Case.sentido_fallo_1st.ilike("%improcedente%")).count()
    pendiente = total - concede - niega - improcedente

    # Por mes — solo este necesita Python (formato de fecha variable)
    month_rows = db.query(Case.fecha_ingreso).filter(
        *gf, Case.fecha_ingreso.isnot(None), Case.fecha_ingreso != ""
    ).all()
    months = {}
    for (fecha,) in month_rows:
        if "/" in (fecha or ""):
            parts = fecha.split("/")
            if len(parts) >= 3:
                key = f"{parts[2]}-{parts[1]}"
                months[key] = months.get(key, 0) + 1
    by_month = sorted(months.items())

    # Por derecho vulnerado — parsear campo separado por " - "
    raw_derechos = db.query(Case.derecho_vulnerado).filter(
        *gf, Case.derecho_vulnerado.isnot(None), Case.derecho_vulnerado != ""
    ).all()
    derechos_count = {}
    for (dv,) in raw_derechos:
        for d in (dv or "").split(" - "):
            d = d.strip().upper()
            if d and len(d) > 2:
                # Normalizar variaciones comunes
                if "EDUCACI" in d:
                    d = "EDUCACION"
                elif "SALUD" in d:
                    d = "SALUD"
                elif "PETICI" in d:
                    d = "PETICION"
                elif "VIDA" in d and "DIGNA" in d:
                    d = "VIDA DIGNA"
                elif "IGUALDAD" in d:
                    d = "IGUALDAD"
                elif "DEBIDO" in d and "PROCESO" in d:
                    d = "DEBIDO PROCESO"
                elif "TRABAJO" in d:
                    d = "TRABAJO"
                elif "MINIMO" in d and "VITAL" in d:
                    d = "MINIMO VITAL"
                derechos_count[d] = derechos_count.get(d, 0) + 1
    derechos_sorted = sorted(derechos_count.items(), key=lambda x: -x[1])[:10]

    # Por oficina responsable
    raw_oficinas = db.query(Case.oficina_responsable, func.count(Case.id)).filter(
        *gf, Case.oficina_responsable.isnot(None), Case.oficina_responsable != ""
    ).group_by(Case.oficina_responsable).all()
    oficinas_norm = {}
    for ofi, count in raw_oficinas:
        key = ofi.strip().title()[:40]
        oficinas_norm[key] = oficinas_norm.get(key, 0) + count
    oficinas_sorted = sorted(oficinas_norm.items(), key=lambda x: -x[1])[:10]

    # Fallos desfavorables por derecho (cruce fallo CONCEDE x derecho_vulnerado)
    raw_desfav = db.query(Case.derecho_vulnerado).filter(
        *gf, Case.sentido_fallo_1st.ilike("%concede%"),
        Case.derecho_vulnerado.isnot(None), Case.derecho_vulnerado != ""
    ).all()
    desfav_count = {}
    for (dv,) in raw_desfav:
        for d in (dv or "").split(" - "):
            d = d.strip().upper()
            if d and len(d) > 2:
                if "EDUCACI" in d: d = "EDUCACION"
                elif "SALUD" in d: d = "SALUD"
                elif "PETICI" in d: d = "PETICION"
                elif "VIDA" in d and "DIGNA" in d: d = "VIDA DIGNA"
                elif "IGUALDAD" in d: d = "IGUALDAD"
                desfav_count[d] = desfav_count.get(d, 0) + 1
    desfav_sorted = sorted(desfav_count.items(), key=lambda x: -x[1])[:10]

    # Favorabilidad REAL (considerando 2da instancia)
    all_cases = db.query(Case).filter(*gf).all()
    fav_counts = {"DESFAVORABLE": 0, "FAVORABLE": 0, "IMPROCEDENTE": 0,
                  "MODIFICADO": 0, "SIN FALLO": 0}
    for c in all_cases:
        fallo_def, _ = get_fallo_definitivo(c.sentido_fallo_1st, c.sentido_fallo_2nd)
        if fallo_def in fav_counts:
            fav_counts[fallo_def] += 1
        elif fallo_def in ("DESISTIMIENTO", "OTRO"):
            fav_counts["IMPROCEDENTE"] += 1

    # Desacatos categorizados
    desacatos_chart = {}
    for c in all_cases:
        if (c.incidente or "").upper() == "SI":
            cat = categorize_decision_incidente(c.decision_incidente, c.observaciones)
            desacatos_chart[cat] = desacatos_chart.get(cat, 0) + 1

    return {
        "by_city": [{"ciudad": c, "count": n} for c, n in city_rows],
        "by_lawyer": [{"abogado": name, "count": count} for name, count in lawyer_rows],
        "by_month": [{"month": k, "count": v} for k, v in by_month],
        "by_fallo": [
            {"fallo": "CONCEDE", "count": concede},
            {"fallo": "NIEGA", "count": niega},
            {"fallo": "IMPROCEDENTE", "count": improcedente},
            {"fallo": "PENDIENTE", "count": pendiente},
        ],
        "by_favorabilidad": [
            {"fallo": "DESFAVORABLE", "count": fav_counts["DESFAVORABLE"]},
            {"fallo": "FAVORABLE", "count": fav_counts["FAVORABLE"]},
            {"fallo": "IMPROCEDENTE", "count": fav_counts["IMPROCEDENTE"]},
            {"fallo": "MODIFICADO", "count": fav_counts["MODIFICADO"]},
            {"fallo": "SIN FALLO", "count": fav_counts["SIN FALLO"]},
        ],
        "by_desacato": [{"estado": k, "count": v} for k, v in sorted(desacatos_chart.items(), key=lambda x: -x[1])],
        "by_derecho": [{"derecho": d, "count": n} for d, n in derechos_sorted],
        "by_oficina": [{"oficina": o, "count": n} for o, n in oficinas_sorted],
        "by_desfavorable": [{"derecho": d, "count": n} for d, n in desfav_sorted],
    }


def get_filter_options(db: Session) -> dict:
    """Obtener opciones para los filtros del frontend."""
    ciudades = sorted([r[0] for r in db.query(Case.ciudad).filter(Case.ciudad.isnot(None), Case.ciudad != "").distinct().all()])
    abogados = sorted([r[0] for r in db.query(Case.abogado_responsable).filter(Case.abogado_responsable.isnot(None), Case.abogado_responsable != "").distinct().all()])
    juzgados = sorted([r[0] for r in db.query(Case.juzgado).filter(Case.juzgado.isnot(None), Case.juzgado != "").distinct().all()])

    return {
        "ciudades": ciudades,
        "abogados": abogados,
        "juzgados": juzgados,
        "estados": ["ACTIVO", "INACTIVO"],
        "fallos": ["CONCEDE", "NIEGA", "IMPROCEDENTE", "CONCEDE PARCIALMENTE"],
        "processing_status": ["PENDIENTE", "EXTRAYENDO", "REVISION", "COMPLETO"],
    }
