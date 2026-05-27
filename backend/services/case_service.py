"""Logica de negocio para casos de tutela."""

import re
import time
from datetime import datetime
from sqlalchemy.orm import Session, subqueryload
from sqlalchemy import func, or_, case as sql_case

from backend.database.database import strip_accents, ilike_unaccent
from backend.database.models import Case, Document, AuditLog
from backend.services.normalizer import (
    normalize_abogado, normalize_ciudad, categorize_decision_incidente,
    get_fallo_definitivo, group_by_normalized,
)

# Cache de KPIs (60 segundos)
_kpi_cache: dict = {"data": None, "ts": 0}
KPI_CACHE_TTL = 60


# Señales de "necesita revisión manual" por caso (para el filtro `revision` del listado).
_REVISION_OPTIONS = {
    "necesita_revision", "sin_accionante", "sin_radicado", "pocos_docs",
    "docs_sospechosos", "sin_fallo",
    "baja_completitud",      # completitud < MIN_COMPLETITUD_PERCENT
    "incidente_sin_fecha",   # incidente=SI sin fecha_apertura_incidente
    "sin_quien_impugno",     # impugnacion=SI sin quien_impugno
    "sin_extraer",           # field_confidences_json vacío → el pipeline v9 no corrió
}

# Rad corto en el folder ("2026-00083", "2025-00305", "2026-10070"…). Identifica el
# caso aunque no haya rad23 — incluye el nº interno de la Gobernación (ej. "2026-21107").
_RAD_CORTO_FOLDER = re.compile(r"20\d{2}[-\s]?\d{4,5}")

# Conteos por flag, cacheados 30s — escanea ~220 casos en Python (igual que list_cases con filtro).
_REVISION_COUNT_CACHE: dict = {"data": None, "ts": 0.0}
REVISION_COUNT_CACHE_TTL = 30


def _case_review_flags(c: Case) -> dict:
    """Calcula las señales de revisión de un caso (lazy-loads documents).

    Las carpetas COMUNICACION (oficios sin radicado) no son tutelas: ninguna de
    las señales aplica por diseño (no tienen rad/accionante).
    """
    if (c.tipo_actuacion or "") == "COMUNICACION":
        return {k: False for k in (
            "sin_accionante", "sin_radicado", "pocos_docs", "docs_sospechosos",
            "sin_fallo", "baja_completitud", "incidente_sin_fecha",
            "sin_quien_impugno", "necesita_revision", "sin_extraer",
        )} | {"_completitud": 100.0, "_n_docs": len(c.documents)}
    n_docs = len(c.documents)
    susp = any((d.verificacion or "") in ("SOSPECHOSO", "NO_PERTENECE") for d in c.documents)
    no_acc = not (c.accionante or "").strip() or "[REVISAR_ACCIONANTE]" in (c.folder_name or "")
    no_rad = not (c.radicado_23_digitos or "").strip()
    # Muchos juzgados (municipales/promiscuos) NO usan el CUP de 23 dígitos en sus
    # autos: solo el rad corto (ej. "2026-00083"). Si el folder lo trae y el caso
    # es una tutela real (>1 doc), el caso SÍ está identificado — la ausencia del
    # rad23 NO es un error accionable. Validado 2026-05-25: de 29 sin_radicado, los
    # 29 eran short-rad-only legítimos (el rad23 simplemente no existe en disco).
    tiene_rad_corto = bool(_RAD_CORTO_FOLDER.search(c.folder_name or ""))
    no_rad_accionable = no_rad and not (tiene_rad_corto and n_docs > 1)
    compl = _get_case_completitud(c)
    baja = compl < MIN_COMPLETITUD_PERCENT  # <20% del cuadro v9 — el caso casi no tiene datos
    inc_sin_fecha = (
        any((getattr(c, f) or "") == "SI" for f in ("incidente", "incidente_2", "incidente_3"))
        and not (c.fecha_apertura_incidente or "").strip()
        and not (c.fecha_apertura_incidente_2 or "").strip()
        and not (c.fecha_apertura_incidente_3 or "").strip()
    )
    sin_qi = (c.impugnacion or "") == "SI" and not (c.quien_impugno or "").strip()
    return {
        "sin_accionante": no_acc,
        "sin_radicado": no_rad,
        "pocos_docs": n_docs <= 1,
        "docs_sospechosos": susp,
        "sin_fallo": not (c.sentido_fallo_1st or "").strip(),
        "baja_completitud": baja,
        "incidente_sin_fecha": inc_sin_fecha,
        "sin_quien_impugno": sin_qi,
        # sin_extraer: ni corrió el pipeline v9 (field_confidences) NI está suficientemente
        # diligenciado a mano (completitud ≥ EXTRAIDO_MIN_COMPLETITUD). NO entra en necesita_revision.
        "sin_extraer": not _case_extraido(c, compl),
        # "necesita_revision" agrupa señales accionables (excluye sin_fallo — normal en tutelas en curso).
        # Usa no_rad_accionable (no el crudo no_rad): un caso identificado por rad corto NO es error.
        "necesita_revision": no_acc or no_rad_accionable or n_docs <= 1 or susp or baja or inc_sin_fecha or sin_qi,
        "_completitud": compl,
        "_n_docs": n_docs,
    }


def list_cases(
    db: Session,
    search: str = "",
    estado: str = "",
    fallo: str = "",
    abogado: str = "",
    ciudad: str = "",
    status: str = "",
    revision: str = "",
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Listar casos con filtros y paginacion.

    `revision` (opcional): surface casos que necesitan revisión manual antes de extraer —
    'necesita_revision' (unión: sin accionante / sin radicado / ≤1 doc / docs sospechosos /
    completitud <30% — ordenados peor-primero), o uno específico: 'sin_accionante',
    'sin_radicado', 'pocos_docs', 'docs_sospechosos', 'sin_fallo'.
    """
    query = db.query(Case).filter(
        Case.folder_name.isnot(None),
        Case.folder_name != "None",
        Case.folder_name != "",
        Case.processing_status != "DUPLICATE_MERGED",
    )

    if search:
        query = query.filter(or_(
            ilike_unaccent(Case.accionante, search),
            ilike_unaccent(Case.radicado_23_digitos, search),
            ilike_unaccent(Case.radicado_forest, search),
            ilike_unaccent(Case.folder_name, search),
            ilike_unaccent(Case.observaciones, search),
            ilike_unaccent(Case.accionados, search),
        ))

    if estado:
        query = query.filter(func.lower(func.unaccent(Case.estado)) == strip_accents(estado.strip().lower()))
    if fallo:
        query = query.filter(ilike_unaccent(Case.sentido_fallo_1st, fallo))
    if abogado:
        query = query.filter(ilike_unaccent(Case.abogado_responsable, abogado))
    if ciudad:
        query = query.filter(ilike_unaccent(Case.ciudad, ciudad))
    if status:
        query = query.filter(Case.processing_status == status)

    revision = (revision or "").strip()
    if revision not in _REVISION_OPTIONS:
        # camino rápido (sin filtro de revisión): paginar en SQL, orden id desc
        total = query.count()
        cases = query.order_by(Case.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        items = []
        for c in cases:
            d = c.to_dict()
            d["extraido"] = _case_extraido(c)  # refinado: pipeline v9 O completitud suficiente
            items.append(d)
    else:
        # filtro de revisión: requiere mirar documentos/completitud → filtrar y paginar en Python
        all_cases = query.all()
        scored = [(c, _case_review_flags(c)) for c in all_cases]
        scored = [(c, f) for c, f in scored if f.get(revision)]
        if revision == "necesita_revision":
            scored.sort(key=lambda t: (t[1]["_completitud"], -t[0].id))  # peor completitud primero
        else:
            scored.sort(key=lambda t: -t[0].id)
        total = len(scored)
        page_slice = scored[(page - 1) * per_page: page * per_page]
        items = []
        _chip_hide = {"necesita_revision"}  # redundante en la vista; no se muestra como chip
        if revision != "sin_fallo":
            _chip_hide.add("sin_fallo")      # ruido (normal en tutelas en curso) salvo si es el filtro activo
        for c, f in page_slice:
            d = c.to_dict()
            d["extraido"] = not f.get("sin_extraer", False)  # consistente con el flag
            d["_review"] = {k: v for k, v in f.items() if not k.startswith("_") and v and k not in _chip_hide}
            d["_completitud_pct"] = round(f["_completitud"])
            d["_n_docs"] = f["_n_docs"]
            items.append(d)

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 1,
    }


def _audit_ts_key(ts):
    """Clave de orden robusta para audit_logs con timestamps mixtos.

    Algunos audit_logs tienen timestamp tz-aware y otros tz-naive (datos
    históricos). Comparar ambos revienta con 'can't compare offset-naive and
    offset-aware datetimes'. Normalizamos todo a naive (descartando tzinfo) y
    usamos datetime.min (naive) como fallback → siempre comparable.
    """
    if ts is None:
        return datetime.min
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


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
        for a in sorted(case.audit_logs, key=lambda x: _audit_ts_key(x.timestamp), reverse=True)[:50]
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


MIN_COMPLETITUD_PERCENT = 20.0

# Campos del cuadro Excel que v9 efectivamente puebla — base para el % de completitud.
# Se excluyen los 5 campos heredados de v8 que v9 NO escribe (DIRECCION/GRUPO/EQUIPO del
# organigrama y los *_CANONICAL); incluirlos deprimía artificialmente la completitud.
_V8_ONLY_FIELDS = {"direccion", "grupo", "equipo", "abogado_canonical", "dependencia_canonical"}
# Transcripciones verbatim del fallo: solo existen si el caso YA tiene sentencia. Contarlas
# en la completitud penalizaría injustamente a las tutelas activas aún sin fallo → se excluyen
# del denominador (siguen en CSV_FIELD_MAP para serialización/Excel).
_TRANSCRIPTION_FIELDS = {"parte_resolutiva_1st", "parte_resolutiva_2nd"}
_CUADRO_FIELDS: tuple[str, ...] = tuple(
    attr for attr in Case.CSV_FIELD_MAP.values()
    if attr not in _V8_ONLY_FIELDS and attr not in _TRANSCRIPTION_FIELDS
)

# Etiquetas legibles para los charts del dashboard (los valores en DB son códigos en MAYÚSCULAS).
_OFICINA_LABEL = {
    "DIRECCION_TALENTO_DOCENTE": "Talento Humano",
    "DIRECCION_ESTRATEGICA": "Dirección Estratégica",
    "DIRECCION_ADMIN_FINANCIERA": "Administrativa y Financiera",
    "DIRECCION_PERMANENCIA": "Cobertura y Permanencia",
    "APOYO_DIRECTO": "Apoyo Directo / Despacho",
}
_DERECHO_LABEL = {
    "EDUCACION": "Educación", "SALUD": "Salud", "PETICION": "Petición",
    "DEBIDO_PROCESO": "Debido proceso", "VIDA": "Vida",
    "SEGURIDAD_SOCIAL": "Seguridad social", "MINIMO_VITAL": "Mínimo vital",
    "TRABAJO": "Trabajo", "IGUALDAD": "Igualdad", "INTIMIDAD": "Intimidad",
    "HABEAS_DATA": "Hábeas data", "OTRO": "Otro",
}
# tags de `derecho_vulnerado` que NO son un derecho (no van al chart)
_DERECHO_SKIP = {"SIN_DETERMINAR", "SIN DETERMINAR", "NO_DETERMINADO"}


def _label_oficina(code: str) -> str:
    c = (code or "").strip().upper()
    return _OFICINA_LABEL.get(c, c.replace("_", " ").title())


def _label_derecho(tag: str) -> str:
    t = (tag or "").strip().upper()
    return _DERECHO_LABEL.get(t, t.replace("_", " ").title())


def _count_derecho_tags(rows) -> list[tuple[str, int]]:
    """De filas [(derecho_vulnerado,), ...] cuenta cada tag (campo separado por ' - '),
    normaliza la etiqueta y descarta SIN_DETERMINAR. Devuelve [(label, count)] orden desc."""
    counts: dict[str, int] = {}
    for (dv,) in rows:
        for tag in (dv or "").split(" - "):
            tag = tag.strip().upper()
            if not tag or tag in _DERECHO_SKIP:
                continue
            label = _label_derecho(tag)
            counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


def _real_cases_filter(valid_ids: set | None = None):
    """Filtro para excluir casos fantasma (sin carpeta real) y opcionalmente por IDs validos."""
    filters = [Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
               Case.processing_status != "DUPLICATE_MERGED"]
    if valid_ids is not None:
        filters.append(Case.id.in_(valid_ids))
    return filters


def _get_case_completitud(case: Case) -> float:
    """Calcular completitud de un caso individual (sobre los campos del cuadro v9)."""
    filled = sum(1 for attr in _CUADRO_FIELDS if str(getattr(case, attr, "") or "").strip())
    return round(filled / len(_CUADRO_FIELDS) * 100, 1)


# Umbral de completitud a partir del cual un caso curado a mano (sin field_confidences)
# se considera "extraído/diligenciado" para el indicador. Ver distribución 2026-05-24:
# el grueso de los curados está en 40-60% → 50% deja como "sin extraer" solo los
# genuinamente poco poblados (~58 casos). Ajustable.
EXTRAIDO_MIN_COMPLETITUD = 50.0


def _case_extraido(case: Case, compl: float | None = None) -> bool:
    """¿El caso está extraído/diligenciado? True si corrió el pipeline v9
    (field_confidences_json poblado) O si está suficientemente completo a mano
    (completitud ≥ EXTRAIDO_MIN_COMPLETITUD). `compl` opcional para no recomputar."""
    _fc = (case.field_confidences_json or "").strip()
    if _fc and _fc not in ("{}", "null"):
        return True
    if compl is None:
        compl = _get_case_completitud(case)
    return compl >= EXTRAIDO_MIN_COMPLETITUD


def _get_valid_case_ids(db: Session, min_completitud: float = MIN_COMPLETITUD_PERCENT):
    """Obtener IDs de casos confiables para metricas del dashboard.

    Excluye: carpetas PENDIENTE REVISION/IDENTIFICACION, sin accionante+radicado,
    y casos con completitud menor al umbral.
    """
    # Comunicaciones / carpetas libres no son tutelas: excluidas de KPIs y métricas.
    base_filters = [Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
                    Case.processing_status != "DUPLICATE_MERGED",
                    Case.tipo_actuacion != "COMUNICACION"]
    all_cases = db.query(Case).filter(*base_filters).all()

    valid_ids = set()
    exclusions = {
        "pendiente_revision": 0,
        "pendiente_identificacion": 0,
        "sin_datos_basicos": 0,
        "baja_completitud": 0,
    }

    for c in all_cases:
        fname = c.folder_name or ""

        if "[PENDIENTE REVISION]" in fname:
            exclusions["pendiente_revision"] += 1
            continue
        if "[PENDIENTE IDENTIFICACION]" in fname:
            exclusions["pendiente_identificacion"] += 1
            continue

        accionante = (c.accionante or "").strip()
        radicado = (c.radicado_23_digitos or "").strip()
        if not accionante and not radicado:
            exclusions["sin_datos_basicos"] += 1
            continue

        compl = _get_case_completitud(c)
        if compl < min_completitud:
            exclusions["baja_completitud"] += 1
            continue

        valid_ids.add(c.id)

    exclusions["total_excluidos"] = sum(v for k, v in exclusions.items() if k != "total_excluidos")
    return valid_ids, exclusions


def get_dashboard_kpis(db: Session) -> dict:
    """Calcular KPIs para el dashboard con SQL aggregation + cache 60s.

    Optimizado v4.0: de ~40 queries a 3 queries + 1 iteracion.
    """
    # Cache check
    if _kpi_cache["data"] and time.time() - _kpi_cache["ts"] < KPI_CACHE_TTL:
        return _kpi_cache["data"]

    valid_ids, exclusions = _get_valid_case_ids(db)
    gf = _real_cases_filter(valid_ids)

    # QUERY 1: Aggregates principales en UNA sola query SQL
    stats = db.query(
        func.count(Case.id).label("total"),
        func.sum(sql_case((func.upper(Case.estado) == "ACTIVO", 1), else_=0)).label("activos"),
        func.sum(sql_case((func.upper(Case.estado) == "INACTIVO", 1), else_=0)).label("inactivos"),
        func.sum(sql_case((func.upper(Case.impugnacion) == "SI", 1), else_=0)).label("con_impugnacion"),
        func.sum(sql_case((func.upper(Case.incidente) == "SI", 1), else_=0)).label("con_incidente"),
        func.sum(sql_case((Case.processing_status == "PENDIENTE", 1), else_=0)).label("pendientes"),
        func.sum(sql_case((Case.processing_status == "COMPLETO", 1), else_=0)).label("completos"),
        func.sum(sql_case((Case.tipo_actuacion == "INCIDENTE", 1), else_=0)).label("total_incidentes"),
        # Fallo 1ra instancia
        func.sum(sql_case((Case.sentido_fallo_1st.contains("CONCEDE"), 1), else_=0)).label("concede"),
        func.sum(sql_case((Case.sentido_fallo_1st.contains("NIEGA"), 1), else_=0)).label("niega"),
        func.sum(sql_case((Case.sentido_fallo_1st.contains("IMPROCEDENTE"), 1), else_=0)).label("improcedente"),
        # Impugnaciones resueltas
        func.sum(sql_case(
            (func.upper(Case.impugnacion) == "SI", sql_case((Case.sentido_fallo_2nd.isnot(None), 1), else_=0)),
            else_=0,
        )).label("imp_resueltas"),
    ).filter(*gf).first()

    total = stats.total or 0

    # QUERY 2: Completitud — contar campos llenos con CASE expressions en UNA query
    field_counts = []
    for attr in _CUADRO_FIELDS:
        col = getattr(Case, attr)
        field_counts.append(func.sum(sql_case((col.isnot(None), sql_case((col != "", 1), else_=0)), else_=0)))

    completitud_row = db.query(*field_counts).filter(*gf).first()
    filled_fields = sum(v or 0 for v in completitud_row) if completitud_row else 0
    n_fields = len(_CUADRO_FIELDS)
    total_fields = total * n_fields
    completitud = round(filled_fields / total_fields * 100, 1) if total_fields > 0 else 0

    # QUERY 3: Solo para favorabilidad real + desacatos (necesita logica Python)
    # Cargar solo las columnas necesarias, no la fila completa
    fallo_data = db.query(
        Case.sentido_fallo_1st, Case.sentido_fallo_2nd,
        Case.incidente, Case.decision_incidente, Case.observaciones,
    ).filter(*gf).all()

    fallos = {"DESFAVORABLE": 0, "FAVORABLE": 0, "IMPROCEDENTE": 0, "MODIFICADO": 0,
              "SIN FALLO": 0, "DESISTIMIENTO": 0, "OTRO": 0}
    desacatos_cat = {"SANCIONADO": 0, "EN CONSULTA": 0, "EN TRÁMITE": 0,
                     "CUMPLIDO": 0, "ARCHIVADO": 0, "PENDIENTE": 0, "OTRO": 0}
    for row in fallo_data:
        fallo_def, _ = get_fallo_definitivo(row.sentido_fallo_1st, row.sentido_fallo_2nd)
        fallos[fallo_def] = fallos.get(fallo_def, 0) + 1
        if (row.incidente or "").upper() == "SI":
            cat = categorize_decision_incidente(row.decision_incidente, row.observaciones)
            desacatos_cat[cat] = desacatos_cat.get(cat, 0) + 1

    con_impugnacion = stats.con_impugnacion or 0
    imp_resueltas = stats.imp_resueltas or 0
    tutelas_unicas = total - (stats.total_incidentes or 0)
    # Total REAL de expedientes en el sistema (no-fusionados, con carpeta) — distinto
    # de `total`, que es solo los válidos para métricas (sin shells / incompletos).
    total_carpetas = db.query(func.count(Case.id)).filter(
        Case.processing_status != "DUPLICATE_MERGED",
        Case.folder_name.isnot(None), Case.folder_name != "", Case.folder_name != "None",
    ).scalar() or 0

    result = {
        "total": total,
        "total_casos": total,
        "total_carpetas": total_carpetas,
        "tutelas_unicas": tutelas_unicas,
        "total_incidentes": stats.total_incidentes or 0,
        "activos": stats.activos or 0,
        "inactivos": stats.inactivos or 0,
        "sin_estado": total - (stats.activos or 0) - (stats.inactivos or 0),
        "concede": stats.concede or 0,
        "niega": stats.niega or 0,
        "improcedente": stats.improcedente or 0,
        "sin_fallo": fallos.get("SIN FALLO", 0),
        "favorabilidad": {
            "desfavorable": fallos.get("DESFAVORABLE", 0),
            "favorable": fallos.get("FAVORABLE", 0),
            "improcedente": fallos.get("IMPROCEDENTE", 0),
            "modificado": fallos.get("MODIFICADO", 0),
            "otro": fallos.get("OTRO", 0),
            "sin_fallo": fallos.get("SIN FALLO", 0),
            "desistimiento": fallos.get("DESISTIMIENTO", 0),
            "tooltip": "Fallo definitivo: si hay 2da instancia que REVOCA, se considera favorable aunque en 1ra fue desfavorable. OTRO = carencia de objeto / hecho superado / nulidad.",
        },
        "con_impugnacion": con_impugnacion,
        "impugnaciones_resueltas": imp_resueltas,
        "impugnaciones_pendientes": con_impugnacion - imp_resueltas,
        "con_incidente": stats.con_incidente or 0,
        "desacatos": desacatos_cat,
        "pendientes_extraccion": stats.pendientes or 0,
        "completos": stats.completos or 0,
        "completitud": completitud,
        "completitud_campos": completitud,
        "campos_llenos": filled_fields,
        "calidad": _get_quality_metrics(db, valid_ids),
        "casos_excluidos": exclusions,
    }

    _kpi_cache["data"] = result
    _kpi_cache["ts"] = time.time()
    return result


def _get_quality_metrics(db: Session, valid_ids: set | None = None) -> dict:
    """Calcular métricas de calidad y confiabilidad de datos."""
    from backend.database.models import Document, Extraction

    gf = _real_cases_filter(valid_ids)

    # Documentos verificados.
    # NOTA: Document tiene dos FK hacia cases (case_id y suggested_target_case_id), así que
    # el join hay que calificarlo explícitamente o SQLAlchemy lanza AmbiguousForeignKeysError.
    _on = Document.case_id == Case.id
    total_docs = db.query(func.count(Document.id)).join(Case, _on).filter(*gf).scalar()
    docs_ok = db.query(func.count(Document.id)).join(Case, _on).filter(*gf, Document.verificacion == "OK").scalar()
    docs_sospechosos = db.query(func.count(Document.id)).join(Case, _on).filter(*gf, Document.verificacion == "SOSPECHOSO").scalar()
    docs_no_verificados = db.query(func.count(Document.id)).join(Case, _on).filter(
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

    campos_score = (sum(campos_criticos.values()) / (total_cases * 5) * 100) if total_cases > 0 else 0
    if total_cases == 0:
        confiabilidad = 0
    elif ext_total > 0:
        confiabilidad = round(doc_score * 0.3 + ext_score * 0.3 + campos_score * 0.4, 1)
    else:
        # v9 escribe a las columnas del Case y no llena la tabla Extraction:
        # se redistribuye el 30% del componente "extracciones" entre docs (3) y campos (4).
        confiabilidad = round(doc_score * (3 / 7) + campos_score * (4 / 7), 1)

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
    """Datos para graficos del dashboard (excluye fantasma, pendientes y baja completitud)."""
    valid_ids, _ = _get_valid_case_ids(db)
    gf = _real_cases_filter(valid_ids)

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

    # Por derecho vulnerado — parsear campo separado por " - " (vocab v9), normalizar etiqueta
    raw_derechos = db.query(Case.derecho_vulnerado).filter(
        *gf, Case.derecho_vulnerado.isnot(None), Case.derecho_vulnerado != ""
    ).all()
    derechos_sorted = _count_derecho_tags(raw_derechos)[:10]

    # Por oficina responsable (Dirección L1 SED) — etiqueta legible
    raw_oficinas = db.query(Case.oficina_responsable, func.count(Case.id)).filter(
        *gf, Case.oficina_responsable.isnot(None), Case.oficina_responsable != ""
    ).group_by(Case.oficina_responsable).all()
    oficinas_norm: dict[str, int] = {}
    for ofi, count in raw_oficinas:
        oficinas_norm[_label_oficina(ofi)] = oficinas_norm.get(_label_oficina(ofi), 0) + count
    oficinas_sorted = sorted(oficinas_norm.items(), key=lambda x: -x[1])[:10]

    # Fallos desfavorables por derecho (cruce fallo CONCEDE x derecho_vulnerado)
    raw_desfav = db.query(Case.derecho_vulnerado).filter(
        *gf, Case.sentido_fallo_1st.ilike("%concede%"),
        Case.derecho_vulnerado.isnot(None), Case.derecho_vulnerado != ""
    ).all()
    desfav_sorted = _count_derecho_tags(raw_desfav)[:10]

    # Favorabilidad REAL (considerando 2da instancia) — mismo desglose que el KPI:
    # CARENCIA_OBJETO/HECHO_SUPERADO/DESISTIMIENTO/NULIDAD caen en "OTRO" (no en IMPROCEDENTE).
    all_cases = db.query(Case).filter(*gf).all()
    fav_counts = {"DESFAVORABLE": 0, "FAVORABLE": 0, "IMPROCEDENTE": 0,
                  "MODIFICADO": 0, "SIN FALLO": 0, "OTRO": 0}
    for c in all_cases:
        fallo_def, _ = get_fallo_definitivo(c.sentido_fallo_1st, c.sentido_fallo_2nd)
        fav_counts[fallo_def if fallo_def in fav_counts else "OTRO"] += 1

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
            {"fallo": "OTRO", "count": fav_counts["OTRO"]},
            {"fallo": "SIN FALLO", "count": fav_counts["SIN FALLO"]},
        ],
        "by_desacato": [{"estado": k, "count": v} for k, v in sorted(desacatos_chart.items(), key=lambda x: -x[1])],
        "by_derecho": [{"derecho": d, "count": n} for d, n in derechos_sorted],
        "by_oficina": [{"oficina": o, "count": n} for o, n in oficinas_sorted],
        "by_desfavorable": [{"derecho": d, "count": n} for d, n in desfav_sorted],
    }


def get_revision_flag_counts(db: Session) -> dict:
    """Conteos de cada señal de revisión sobre los casos visibles del listado.

    Escanea ~220 casos en Python (mismo costo que list_cases con filtro de revisión).
    Cacheado 30 s — se invalida al ritmo natural de sync/extract.
    """
    if _REVISION_COUNT_CACHE["data"] and time.time() - _REVISION_COUNT_CACHE["ts"] < REVISION_COUNT_CACHE_TTL:
        return _REVISION_COUNT_CACHE["data"]

    base_cases = db.query(Case).filter(
        Case.folder_name.isnot(None),
        Case.folder_name != "None",
        Case.folder_name != "",
        Case.processing_status != "DUPLICATE_MERGED",
        # COMUNICACION no tiene rad ni accionante por diseño — los flags no aplican.
        Case.tipo_actuacion != "COMUNICACION",
    ).all()

    keys = (
        "necesita_revision", "sin_accionante", "sin_radicado", "pocos_docs",
        "docs_sospechosos", "baja_completitud", "incidente_sin_fecha",
        "sin_quien_impugno", "sin_fallo", "sin_extraer",
    )
    counts = {k: 0 for k in keys}
    for c in base_cases:
        f = _case_review_flags(c)
        for k in keys:
            if f.get(k):
                counts[k] += 1
    counts["_total"] = len(base_cases)

    _REVISION_COUNT_CACHE["data"] = counts
    _REVISION_COUNT_CACHE["ts"] = time.time()
    return counts


# Orden + severidad para que el frontend pinte la fila de chips sin reglas locales.
# severity ∈ {"critical","high","warn","procedural","info"}.
_REVISION_FLAG_META: tuple[tuple[str, str, str], ...] = (
    ("necesita_revision",   "Necesita revisión",   "high"),
    ("sin_accionante",      "Sin accionante",      "critical"),
    ("sin_radicado",        "Sin radicado",        "critical"),
    ("pocos_docs",          "≤1 documento",        "warn"),
    ("docs_sospechosos",    "Docs sospechosos",    "warn"),
    ("baja_completitud",    f"Compl. <{int(MIN_COMPLETITUD_PERCENT)}%", "warn"),
    ("incidente_sin_fecha", "Incidente s/fecha",   "procedural"),
    ("sin_quien_impugno",   "Impugna s/sujeto",    "procedural"),
    ("sin_fallo",           "Sin fallo 1ra",       "info"),
    ("sin_extraer",         "Sin extraer",         "warn"),
)


def get_filter_options(db: Session) -> dict:
    """Obtener opciones para los filtros del frontend."""
    ciudades = sorted([r[0] for r in db.query(Case.ciudad).filter(Case.ciudad.isnot(None), Case.ciudad != "").distinct().all()])
    abogados = sorted([r[0] for r in db.query(Case.abogado_responsable).filter(Case.abogado_responsable.isnot(None), Case.abogado_responsable != "").distinct().all()])
    juzgados = sorted([r[0] for r in db.query(Case.juzgado).filter(Case.juzgado.isnot(None), Case.juzgado != "").distinct().all()])
    counts = get_revision_flag_counts(db)

    return {
        "ciudades": ciudades,
        "abogados": abogados,
        "juzgados": juzgados,
        "estados": ["ACTIVO", "INACTIVO"],
        "fallos": ["CONCEDE", "NIEGA", "IMPROCEDENTE", "CARENCIA_OBJETO", "HECHO_SUPERADO",
                   "DESISTIDO", "RECHAZA", "CONCEDE PARCIALMENTE"],
        "processing_status": ["PENDIENTE", "EXTRAYENDO", "REVISION", "COMPLETO"],
        "revision_flags": [
            {"value": v, "label": label, "severity": sev, "count": counts.get(v, 0)}
            for v, label, sev in _REVISION_FLAG_META
        ],
        "revision_total": counts.get("_total", 0),
    }
