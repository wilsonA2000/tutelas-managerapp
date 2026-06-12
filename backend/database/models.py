"""Modelos SQLAlchemy para la base de datos de tutelas."""

from datetime import datetime
from backend.core.time import utcnow
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index,
    LargeBinary, UniqueConstraint, Boolean, Float, func,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Case(Base):
    """Caso de tutela - 28 campos del protocolo + metadata."""
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- 28 campos del protocolo ---
    radicado_23_digitos = Column(String, index=True)
    radicado_forest = Column(String)
    abogado_responsable = Column(String)
    accionante = Column(String, index=True)
    accionados = Column(Text)
    vinculados = Column(Text)
    derecho_vulnerado = Column(String)
    juzgado = Column(String)
    ciudad = Column(String, index=True)
    fecha_ingreso = Column(String)
    asunto = Column(Text)
    pretensiones = Column(Text)
    oficina_responsable = Column(String)
    # v8.0: jerarquía SED 3 niveles (Decretos 544/2021 + 048/2022)
    direccion = Column(String, index=True)  # L1: APOYO_DIRECTO / DIRECCION_TALENTO_DOCENTE / DIRECCION_ESTRATEGICA / DIRECCION_PERMANENCIA / DIRECCION_ADMIN_FINANCIERA
    grupo = Column(String, index=True)      # L2: NOMINA / HISTORIAS_LABORALES / FINANCIERA / CALIDAD_EDUCATIVA / etc. (17 valores)
    equipo = Column(String)                 # L3: EQUIPO_TESORERIA / EQUIPO_PRESUPUESTO / EQUIPO_CONTABILIDAD / EQUIPO_FONDOS_SERVICIOS (solo bajo Financiera)
    # v8.2: campos canónicos resueltos contra abogados_sed.json + sed_org.py
    abogado_canonical = Column(String, index=True)         # Uno de los 17 abogados oficiales o NULL si firmante operativo
    abogado_canonical_confidence = Column(Float)            # 0.0 - 1.0
    dependencia_canonical = Column(String, index=True)      # código SED_ORG (DIRECCION_TALENTO_DOCENTE, etc.)
    dependencia_canonical_confidence = Column(Float)
    estado = Column(String, index=True)  # ACTIVO / INACTIVO
    fecha_respuesta = Column(String)
    sentido_fallo_1st = Column(String, index=True)  # CONCEDE / NIEGA / IMPROCEDENTE
    fecha_fallo_1st = Column(String)
    parte_resolutiva_1st = Column(Text)  # transcripción verbatim del RESUELVE (1ra instancia)
    impugnacion = Column(String, index=True)  # SI / NO
    quien_impugno = Column(String)
    forest_impugnacion = Column(String)
    juzgado_2nd = Column(String)
    sentido_fallo_2nd = Column(String)  # CONFIRMA / REVOCA / MODIFICA
    fecha_fallo_2nd = Column(String)
    parte_resolutiva_2nd = Column(Text)  # transcripción verbatim del RESUELVE (2da instancia)
    incidente = Column(String)  # SI / NO
    fecha_apertura_incidente = Column(String)
    responsable_desacato = Column(String)   # funcionario público sancionable (jurídico, Dcto 2591/91)
    abogado_incidente = Column(String)      # abogado SED que opera el incidente (= abogado_responsable)
    decision_incidente = Column(String)
    # --- Segundo incidente de desacato ---
    incidente_2 = Column(String)
    fecha_apertura_incidente_2 = Column(String)
    responsable_desacato_2 = Column(String)
    abogado_incidente_2 = Column(String)
    decision_incidente_2 = Column(String)
    # --- Tercer incidente de desacato ---
    incidente_3 = Column(String)
    fecha_apertura_incidente_3 = Column(String)
    responsable_desacato_3 = Column(String)
    abogado_incidente_3 = Column(String)
    decision_incidente_3 = Column(String)
    # Transcripción verbatim del RESUELVE del auto que SANCIONA el desacato (órdenes +
    # plazo de cumplimiento) — permite saber si se está en término. 2026-06-02.
    parte_resolutiva_incidente = Column(Text)

    observaciones = Column(Text)
    categoria_tematica = Column(String, default="", index=True)

    # --- Metadata ---
    folder_name = Column(String, unique=True, index=True)

    # v6.0: clasificación cognitiva del caso (Capa 4)
    origen = Column(String, nullable=True, index=True)           # TUTELA / INCIDENTE_HUERFANO / AMBIGUO
    estado_incidente = Column(String, nullable=True, index=True)  # N/A / ACTIVO / EN_CONSULTA / EN_SANCION / ARCHIVADO / CUMPLIDO
    entropy_score = Column(Float, nullable=True)                  # H(caso) post-extracción
    convergence_iterations = Column(Integer, nullable=True)       # cuántas iteraciones necesitó el pipeline

    # F2 (2026-05-02): confidence scoring por campo. JSON con shape
    # {field_name: {"score": 0.0-1.0, "band": "OK"|"REVISAR"|"BAJO", "evidence": {...}}}
    # Permite UI marcar extracciones débiles para revisión humana antes de exportar.
    field_confidences_json = Column(Text, nullable=True)
    folder_path = Column(String)
    processing_status = Column(String, default="PENDIENTE", index=True)  # PENDIENTE / EXTRAYENDO / REVISION / COMPLETO
    tipo_actuacion = Column(String, default="TUTELA")  # TUTELA / INCIDENTE
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Acumulación de tutelas (Decreto 2591/1991 art. 13 + CGP art. 159 supletorio).
    # Cuando un juez ordena acumular dos o más expedientes (tutela o desacato),
    # uno actúa como RECTOR (recibe los demás) y los otros como ACUMULADO
    # (mantienen su rad/folder propios pero quedan colgados del rector para
    # efectos procesales y de presentación en el cuadro).
    acumulado_a_case_id = Column(Integer, ForeignKey("cases.id"), nullable=True, index=True)
    tipo_acumulacion = Column(String, nullable=True, index=True)  # 'RECTOR' / 'ACUMULADO' / NULL
    acumulacion_auto_doc_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    acumulacion_fecha = Column(String, nullable=True)  # DD/MM/AAAA del auto que ordenó acumular
    # (Retirado) `pii_mode` — la anonimización PII no aplica en modo local-only.

    # Relaciones
    documents = relationship("Document", back_populates="case", cascade="all, delete-orphan",
                              foreign_keys="Document.case_id")
    extractions = relationship("Extraction", back_populates="case", cascade="all, delete-orphan")
    emails = relationship("Email", back_populates="case")
    audit_logs = relationship("AuditLog", back_populates="case", cascade="all, delete-orphan")

    # Mapeo CSV -> atributo del modelo
    CSV_FIELD_MAP = {
        "RADICADO_23_DIGITOS": "radicado_23_digitos",
        "RADICADO_FOREST": "radicado_forest",
        "ABOGADO_RESPONSABLE": "abogado_responsable",
        "ACCIONANTE": "accionante",
        "ACCIONADOS": "accionados",
        "VINCULADOS": "vinculados",
        "DERECHO_VULNERADO": "derecho_vulnerado",
        "JUZGADO": "juzgado",
        "CIUDAD": "ciudad",
        "FECHA_INGRESO": "fecha_ingreso",
        "ASUNTO": "asunto",
        "PRETENSIONES": "pretensiones",
        "OFICINA_RESPONSABLE": "oficina_responsable",
        "ESTADO": "estado",
        "FECHA_RESPUESTA": "fecha_respuesta",
        "SENTIDO_FALLO_1ST": "sentido_fallo_1st",
        "FECHA_FALLO_1ST": "fecha_fallo_1st",
        "PARTE_RESOLUTIVA_1ST": "parte_resolutiva_1st",
        "IMPUGNACION": "impugnacion",
        "QUIEN_IMPUGNO": "quien_impugno",
        "FOREST_IMPUGNACION": "forest_impugnacion",
        "JUZGADO_2ND": "juzgado_2nd",
        "SENTIDO_FALLO_2ND": "sentido_fallo_2nd",
        "FECHA_FALLO_2ND": "fecha_fallo_2nd",
        "PARTE_RESOLUTIVA_2ND": "parte_resolutiva_2nd",
        "INCIDENTE": "incidente",
        "FECHA_APERTURA_INCIDENTE": "fecha_apertura_incidente",
        "RESPONSABLE_DESACATO": "responsable_desacato",
        "ABOGADO_INCIDENTE": "abogado_incidente",
        "DECISION_INCIDENTE": "decision_incidente",
        "INCIDENTE_2": "incidente_2",
        "FECHA_APERTURA_INCIDENTE_2": "fecha_apertura_incidente_2",
        "RESPONSABLE_DESACATO_2": "responsable_desacato_2",
        "ABOGADO_INCIDENTE_2": "abogado_incidente_2",
        "DECISION_INCIDENTE_2": "decision_incidente_2",
        "INCIDENTE_3": "incidente_3",
        "FECHA_APERTURA_INCIDENTE_3": "fecha_apertura_incidente_3",
        "RESPONSABLE_DESACATO_3": "responsable_desacato_3",
        "ABOGADO_INCIDENTE_3": "abogado_incidente_3",
        "DECISION_INCIDENTE_3": "decision_incidente_3",
        # Transcripción verbatim del RESUELVE del auto que SANCIONA el desacato
        # (contiene órdenes + plazo de cumplimiento). 2026-06-02.
        "PARTE_RESOLUTIVA_INCIDENTE": "parte_resolutiva_incidente",
        "OBSERVACIONES": "observaciones",
        "CATEGORIA_TEMATICA": "categoria_tematica",
    }

    def to_dict(self, include_doc_count: bool = False):
        """Convertir a diccionario para API responses."""
        result = {
            "id": self.id,
            "tipo_actuacion": self.tipo_actuacion or "TUTELA",
            **{csv_col: getattr(self, attr) or "" for csv_col, attr in self.CSV_FIELD_MAP.items()},
            "folder_name": self.folder_name,
            "folder_path": self.folder_path,
            "processing_status": self.processing_status,
            # extraido: ¿corrió el pipeline v9 sobre el caso? (field_confidences_json poblado).
            # Indicador "extraído sí/no" para el frontend. Ojo: curación 100% manual sin
            # field_confidences marca extraido=False (el pipeline no corrió, aunque tenga datos).
            "extraido": bool((self.field_confidences_json or "").strip()
                             and (self.field_confidences_json or "").strip() not in ("{}", "null")),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            # Acumulación procesal (Dec 2591/91 art. 13 + Dec 1834/2015 tutelas masivas)
            "tipo_acumulacion": self.tipo_acumulacion,
            "acumulado_a_case_id": self.acumulado_a_case_id,
            "acumulacion_fecha": self.acumulacion_fecha,
            "acumulacion_auto_doc_id": self.acumulacion_auto_doc_id,
        }
        if include_doc_count:
            result["document_count"] = len(self.documents) if self.documents else 0
        return result


class Document(Base):
    """Documento dentro de una carpeta de caso."""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    doc_type = Column(String, default="OTRO")  # AUTO_ADMISORIO / GMAIL / RESPUESTA_DOCX / SENTENCIA / IMPUGNACION / INCIDENTE / SCREENSHOT / OTRO
    extracted_text = Column(Text)
    extraction_method = Column(String)  # pdfplumber / python-docx / zip_fallback / ocr / antiword
    page_count = Column(Integer)
    file_size = Column(Integer)
    extraction_date = Column(DateTime)
    # Cuándo entró la fila a la DB (ciclo de vida de extracción 2026-06-12):
    # comparar contra field_confidences_json.v9_extracted_at del case responde
    # "¿llegaron docs DESPUÉS de la última extracción?" sin estado manual.
    created_at = Column(DateTime, server_default=func.now())

    verificacion = Column(String, default="", index=True)  # '' / OK / SOSPECHOSO / NO_PERTENECE
    verificacion_detalle = Column(String, default="")
    file_hash = Column(String, default="")  # MD5 hash para detectar duplicados

    # v4.8 Provenance: vinculo inmutable al email de origen (si viene de Gmail).
    # Garantiza que hermanos (mismo email_id) viajen juntos al mover entre casos.
    # NULL = doc legacy o ingestado por sync de carpeta (no vino por Gmail).
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=True, index=True)
    email_message_id = Column(String, nullable=True, index=True)  # gmail message_id para backfill/debug

    # v6.0: percepción física del documento (Capa 0)
    institutional_score = Column(Float, nullable=True)         # 0-1, confiabilidad institucional
    visual_signature_json = Column(Text, nullable=True)         # JSON serializado del VisualSignature

    # v9: si el doc pertenece a un incidente de desacato, guardamos el rad corto
    # del incidente. El doc vive físicamente en la sub-carpeta `incidente_<rad>`
    # dentro del folder de la tutela origen. NULL si es doc directo de la tutela.
    incidente_radicado = Column(String, nullable=True, index=True)

    # v9.2: Verificación graduada (0.0 - 1.0). NULL para docs viejos.
    # Reemplaza la binaria `verificacion` por un score con desglose.
    # 1.0 = altamente confiable, 0.0 = altamente sospechoso.
    verificacion_score = Column(Float, nullable=True)
    # JSON con desglose de señales que componen el score (debug + UI)
    verificacion_breakdown = Column(Text, nullable=True)

    # v9.2: Cruce de referencias post-ingesta — si el doc tiene rad21 que apunta
    # a OTRO case existente en la DB, sugerimos el case destino para que el
    # operador decida en la UI ("¿mover este doc a case#X?").
    suggested_target_case_id = Column(Integer, ForeignKey("cases.id"), nullable=True, index=True)
    suggested_reason = Column(String, nullable=True)

    case = relationship("Case", back_populates="documents", foreign_keys=[case_id])
    email = relationship("Email", back_populates="documents")
    extractions = relationship("Extraction", back_populates="document", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "case_id": self.case_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "doc_type": self.doc_type,
            "has_text": bool(self.extracted_text),
            "text_length": len(self.extracted_text) if self.extracted_text else 0,
            "extraction_method": self.extraction_method,
            "page_count": self.page_count,
            "file_size": self.file_size,
            "extraction_date": self.extraction_date.isoformat() if self.extraction_date else None,
            "verificacion": self.verificacion or "",
            "verificacion_detalle": self.verificacion_detalle or "",
        }


class Extraction(Base):
    """Registro de extraccion de un campo especifico."""
    __tablename__ = "extractions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False, index=True)
    field_name = Column(String, nullable=False)  # Nombre del campo (ej: RADICADO_23_DIGITOS)
    extracted_value = Column(Text)
    confidence = Column(String, default="MEDIA", index=True)  # ALTA / MEDIA / BAJA
    source_page = Column(Integer)
    raw_context = Column(Text)  # Texto circundante para verificacion
    extraction_method = Column(String)  # regex / ai / manual
    created_at = Column(DateTime, default=utcnow)

    document = relationship("Document", back_populates="extractions")
    case = relationship("Case", back_populates="extractions")


class Email(Base):
    """Correo recibido via Gmail."""
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String, unique=True)
    subject = Column(String)
    sender = Column(String)
    date_received = Column(DateTime)
    body_preview = Column(Text)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True, index=True)
    attachments = Column(JSON, default=list)  # [{filename, saved_path}]
    status = Column(String, default="PENDIENTE")  # PENDIENTE / ASIGNADO / IGNORADO / AMBIGUO
    processed_at = Column(DateTime)

    # v5.4.4: threading por In-Reply-To/References + observabilidad del matcher
    in_reply_to = Column(String, index=True, nullable=True)
    references_header = Column(Text, nullable=True)
    match_score = Column(Integer, nullable=True)
    match_signals_json = Column(Text, nullable=True)
    match_confidence = Column(String, nullable=True)  # HIGH / MEDIUM / LOW

    case = relationship("Case", back_populates="emails")
    # v4.8 Provenance: reverso del vinculo inmutable. Un Email tiene N Documents hijos
    # (body.md + adjuntos) que siempre viajan juntos al reasignar a otro caso.
    documents = relationship("Document", back_populates="email")

    def to_dict(self):
        return {
            "id": self.id,
            "message_id": self.message_id,
            "subject": self.subject,
            "sender": self.sender,
            "date_received": self.date_received.isoformat() + "Z" if self.date_received else None,
            "body_preview": self.body_preview,
            "case_id": self.case_id,
            "attachments": self.attachments or [],
            "status": self.status,
        }


class AuditLog(Base):
    """Registro de auditoria de cambios — historia completa del expediente.

    Cada fila representa UN evento sobre un case (creación, modificación,
    traslado de documento, cambio de estado, etc.). Es la fuente única de
    verdad para el "Historial del expediente" (modal 🕐).
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False, index=True)
    field_name = Column(String)
    old_value = Column(Text)
    new_value = Column(Text)
    action = Column(String, index=True)  # event_type — ej. COMPLIANCE_STATE_CHANGED, DOC_ADDED, FIELD_EXTRACTED
    source = Column(String)              # actor — usuario|sistema|gmail_monitor|ai_deepseek|v9_regex
    timestamp = Column(DateTime, default=utcnow)

    # v95 — soporte para entidades específicas y UI del modal Historial
    entity_type = Column(String)         # case|document|email|compliance|field
    entity_id = Column(Integer)          # id del objeto (ej. compliance_tracking.id)
    description = Column(Text)           # frase human-readable para UI
    meta_json = Column(Text)             # contexto adicional (JSON)

    case = relationship("Case", back_populates="audit_logs")


class ComplianceTracking(Base):
    """Seguimiento de cumplimiento de fallos de tutela."""
    __tablename__ = "compliance_tracking"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False, index=True)

    # Datos del fallo
    instancia = Column(String, default="1ra")          # 1ra / 2da
    sentido_fallo = Column(String)                      # CONCEDE / CONCEDE PARCIALMENTE
    fecha_fallo = Column(String)                        # DD/MM/YYYY
    fecha_notificacion = Column(String)                 # DD/MM/YYYY — cuando se notificó

    # Orden judicial
    orden_judicial = Column(Text)                       # Qué ordenó el juez (texto extraído por IA)
    plazo_dias = Column(Integer)                        # Plazo en días para cumplir
    fecha_limite = Column(String)                       # DD/MM/YYYY — fecha calculada
    responsable = Column(String)                        # Secretaría de Educación, Salud, etc.

    # Estado de cumplimiento
    estado = Column(String, default="PENDIENTE")        # PENDIENTE / EN_PROCESO / CUMPLIDO / VENCIDO / IMPUGNADO
    notas = Column(Text)                                # Observaciones del seguimiento
    fecha_cumplimiento = Column(String)                 # DD/MM/YYYY — cuando se cumplió

    # Impugnación
    impugnado = Column(String, default="NO")            # SI / NO
    efecto_impugnacion = Column(String)                 # SUSPENSIVO / NO_SUSPENSIVO / DEVOLUTIVO
    requiere_cumplimiento = Column(String, default="SI") # SI aunque esté impugnado (efecto no suspensivo)

    # Metadata
    extraido_por_ia = Column(String, default="NO")      # SI si la IA extrajo orden/plazo
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # v2 (extractor de órdenes — 2026-05-19): una fila representa UNA orden discreta
    # del fallo, no la sentencia agregada. Cardinalidad 1:N case→orden.
    ordinal_nombre = Column(String)                     # PRIMERO/SEGUNDO/...
    tipo_plazo = Column(String)                         # NUMERICO|FECHA|INMEDIATO|PERMANENTE|CONDICIONAL|SIN_PLAZO
    destinatario_tipo = Column(String)                  # SED_DIRECTA|SED_VINCULADA|TERCERO_SED_VINCULADA|SED_OTRA
    accion_resumida = Column(Text)                      # Frase imperativa principal
    condicion = Column(Text)                            # Texto de la condición (tipo_plazo=CONDICIONAL)
    verbo_orden = Column(String)                        # ORDENAR|CONMINAR|REQUERIR|DISPONER|EXHORTAR|"(IMPLÍCITO)"
    fecha_especifica = Column(String)                   # DD/MM/YYYY cuando tipo_plazo=FECHA
    evidencia_doc_id = Column(Integer, ForeignKey("documents.id"))  # Oficio que acredita cumplimiento

    case = relationship("Case", backref="compliance_records")
    evidencia_doc = relationship("Document", foreign_keys=[evidencia_doc_id])


class CaseActuacion(Base):
    """Bitácora de actuaciones administrativas por caso (importadas del cuadro
    de control externo de la oficina jurídica).

    Cada fila es una actuación cronológica registrada por la abogada coordinadora:
    si el mismo radicado tuvo 4 actuaciones (escrito, recurso, fallo, RTA), habrá
    4 filas. Permite reconstruir cómo cambió la asignación / observaciones del
    caso en el tiempo, sin sobrescribir info del pipeline.
    """
    __tablename__ = "case_actuaciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True, index=True)
    radicado_corto = Column(String, index=True)        # "2026-00057" para matching
    radicado_forest = Column(String)
    fecha_actuacion = Column(String)                    # DD/MM/YYYY si se conoce
    tipo_actuacion = Column(String)                     # TUTELA / DESACATO / RECURSO / RTA / OTRO
    abogado_short = Column(String)                      # Como aparece en Excel: VICTOR, ANGELICA
    abogado_canonical = Column(String)                  # Resuelto contra abogados oficiales
    dependencia_raw = Column(String)                    # TALENTO HUMANO, ESTRATEGICA
    dependencia_canonical = Column(String)              # DIRECCION_TALENTO_DOCENTE etc
    tema = Column(String)                               # TRASLADO, INCLUSION, CUPO, etc
    observaciones = Column(Text)                        # Lo que la coordinadora escribió
    accionante = Column(String)                         # Como aparece en Excel
    correo_juzgado = Column(String)                     # Para validación cruzada
    source = Column(String, default="control_tutelas_xlsx")  # Trazabilidad
    source_version = Column(String)                     # Fecha de exportación del Excel
    imported_at = Column(DateTime, default=utcnow, index=True)

    case = relationship("Case", backref="actuaciones_registradas")


class CorteRevision(Base):
    """Cases en revisión de la Corte Constitucional (sentencias T-)."""
    __tablename__ = "corte_revision"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True, index=True)
    radicado_t = Column(String, nullable=False, index=True)   # 'T-9.698.713'
    radicado_corto = Column(String)                            # '2023-104'
    accionante = Column(String)
    tema = Column(String)
    correo_juzgado = Column(String)
    sentencia_hito = Column(String)                            # 'T-303 de 2024'
    observaciones = Column(Text)
    estado_revision = Column(String, default="EN_CORTE")
    fecha_seleccion = Column(String)
    fecha_fallo_corte = Column(String)
    sentido_fallo_corte = Column(String)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DirectorioCorreos(Base):
    """Directorio de contactos por dependencia/tema (importado del Excel hoja CORREOS)."""
    __tablename__ = "directorio_correos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dependencia_canonical = Column(String, nullable=False, index=True)
    tema = Column(String, nullable=False)
    correos = Column(Text, nullable=False)
    responsable = Column(String)
    notas = Column(String)
    activo = Column(Integer, default=1)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class TokenUsage(Base):
    """Registro de consumo de tokens por cada llamada a la IA."""
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utcnow, index=True)
    provider = Column(String, nullable=False)       # deepseek / anthropic (+ legacy histórico: google/openai/groq/cerebras/huggingface)
    model = Column(String, nullable=False)           # deepseek-chat / claude-haiku-4-5-20251001 / etc
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    cost_input = Column(String, default="0")         # USD como string para precision
    cost_output = Column(String, default="0")
    cost_total = Column(String, default="0")
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    fields_extracted = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)         # Tiempo de respuesta en ms
    error = Column(Text, nullable=True)
    chunk_index = Column(Integer, default=0)         # 0 si es llamada unica, 1+ si multi-chunk

# (Retirado) Los modelos PiiMapping y PrivacyStats (capa PII v5.3) se quitaron — la
# anonimización pre-IA-externa no aplica en modo local-only. Las tablas `pii_mappings` y
# `privacy_stats` quedan vestigiales en DBs ya creadas (SQLAlchemy las ignora); se dropean
# en la próxima migración limpia.
