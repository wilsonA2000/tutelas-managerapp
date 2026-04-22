"""Modelos SQLAlchemy para la base de datos de tutelas."""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index,
    LargeBinary, UniqueConstraint, Boolean,
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
    estado = Column(String, index=True)  # ACTIVO / INACTIVO
    fecha_respuesta = Column(String)
    sentido_fallo_1st = Column(String, index=True)  # CONCEDE / NIEGA / IMPROCEDENTE
    fecha_fallo_1st = Column(String)
    impugnacion = Column(String, index=True)  # SI / NO
    quien_impugno = Column(String)
    forest_impugnacion = Column(String)
    juzgado_2nd = Column(String)
    sentido_fallo_2nd = Column(String)  # CONFIRMA / REVOCA / MODIFICA
    fecha_fallo_2nd = Column(String)
    incidente = Column(String)  # SI / NO
    fecha_apertura_incidente = Column(String)
    responsable_desacato = Column(String)
    decision_incidente = Column(String)
    # --- Segundo incidente de desacato ---
    incidente_2 = Column(String)
    fecha_apertura_incidente_2 = Column(String)
    responsable_desacato_2 = Column(String)
    decision_incidente_2 = Column(String)
    # --- Tercer incidente de desacato ---
    incidente_3 = Column(String)
    fecha_apertura_incidente_3 = Column(String)
    responsable_desacato_3 = Column(String)
    decision_incidente_3 = Column(String)

    observaciones = Column(Text)
    categoria_tematica = Column(String, default="", index=True)

    # --- Metadata ---
    folder_name = Column(String, unique=True, index=True)
    folder_path = Column(String)
    processing_status = Column(String, default="PENDIENTE", index=True)  # PENDIENTE / EXTRAYENDO / REVISION / COMPLETO
    tipo_actuacion = Column(String, default="TUTELA")  # TUTELA / INCIDENTE
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # v5.3: modo de anonimización aplicado a este caso.
    # NULL = usa PII_MODE_DEFAULT global; "selective" = solo identificadores numéricos;
    # "aggressive" = también tokeniza nombres, diagnósticos, radicados
    pii_mode = Column(String, nullable=True)

    # Relaciones
    documents = relationship("Document", back_populates="case", cascade="all, delete-orphan")
    extractions = relationship("Extraction", back_populates="case", cascade="all, delete-orphan")
    emails = relationship("Email", back_populates="case")
    audit_logs = relationship("AuditLog", back_populates="case", cascade="all, delete-orphan")
    pii_mappings = relationship("PiiMapping", back_populates="case", cascade="all, delete-orphan")

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
        "IMPUGNACION": "impugnacion",
        "QUIEN_IMPUGNO": "quien_impugno",
        "FOREST_IMPUGNACION": "forest_impugnacion",
        "JUZGADO_2ND": "juzgado_2nd",
        "SENTIDO_FALLO_2ND": "sentido_fallo_2nd",
        "FECHA_FALLO_2ND": "fecha_fallo_2nd",
        "INCIDENTE": "incidente",
        "FECHA_APERTURA_INCIDENTE": "fecha_apertura_incidente",
        "RESPONSABLE_DESACATO": "responsable_desacato",
        "DECISION_INCIDENTE": "decision_incidente",
        "INCIDENTE_2": "incidente_2",
        "FECHA_APERTURA_INCIDENTE_2": "fecha_apertura_incidente_2",
        "RESPONSABLE_DESACATO_2": "responsable_desacato_2",
        "DECISION_INCIDENTE_2": "decision_incidente_2",
        "INCIDENTE_3": "incidente_3",
        "FECHA_APERTURA_INCIDENTE_3": "fecha_apertura_incidente_3",
        "RESPONSABLE_DESACATO_3": "responsable_desacato_3",
        "DECISION_INCIDENTE_3": "decision_incidente_3",
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
            "pii_mode": self.pii_mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
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

    verificacion = Column(String, default="", index=True)  # '' / OK / SOSPECHOSO / NO_PERTENECE
    verificacion_detalle = Column(String, default="")
    file_hash = Column(String, default="")  # MD5 hash para detectar duplicados

    # v4.8 Provenance: vinculo inmutable al email de origen (si viene de Gmail).
    # Garantiza que hermanos (mismo email_id) viajen juntos al mover entre casos.
    # NULL = doc legacy o ingestado por sync de carpeta (no vino por Gmail).
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=True, index=True)
    email_message_id = Column(String, nullable=True, index=True)  # gmail message_id para backfill/debug

    case = relationship("Case", back_populates="documents")
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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    status = Column(String, default="PENDIENTE")  # PENDIENTE / ASIGNADO / IGNORADO
    processed_at = Column(DateTime)

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
    """Registro de auditoria de cambios."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False, index=True)
    field_name = Column(String)
    old_value = Column(Text)
    new_value = Column(Text)
    action = Column(String, index=True)  # CREAR / ACTUALIZAR / AI_EXTRAER / EDICION_MANUAL / IMPORT_EMAIL / IMPORT_CSV
    source = Column(String)  # Quien/que hizo el cambio
    timestamp = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    case = relationship("Case", backref="compliance_records")


class TokenUsage(Base):
    """Registro de consumo de tokens por cada llamada a la IA."""
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
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


class PiiMapping(Base):
    """Mapeo token ↔ valor real para un caso (v5.3).

    Los tokens van a la IA externa; los valores se rehidratan localmente
    antes de persistir/mostrar al operador. value_encrypted usa Fernet con
    key derivada de PII_MASTER_KEY. value_hash es HMAC-SHA256 para lookup
    inverso (detección de duplicados dentro del mismo case_id) sin descifrar.
    """
    __tablename__ = "pii_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String, nullable=False)                # "[ACCIONANTE_1]"
    kind = Column(String, nullable=False, index=True)     # PERSON / CC / NUIP / ORG / ...
    value_encrypted = Column(LargeBinary, nullable=False)
    value_hash = Column(String, nullable=False, index=True)  # HMAC para lookup sin descifrar
    meta_json = Column(Text, nullable=True)               # edad/región/últimos 4, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("case_id", "token", name="uq_pii_case_token"),)

    case = relationship("Case", back_populates="pii_mappings")


class PrivacyStats(Base):
    """Telemetría agregada de la capa PII por caso y corrida."""
    __tablename__ = "privacy_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    run_at = Column(DateTime, default=datetime.utcnow, index=True)
    mode = Column(String, nullable=False)                 # selective / aggressive
    spans_detected = Column(Integer, default=0)
    tokens_minted = Column(Integer, default=0)
    violations_count = Column(Integer, default=0)
    gate_blocked = Column(Boolean, default=False)
    redactor_ms = Column(Integer, default=0)
    rehydrator_ms = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
