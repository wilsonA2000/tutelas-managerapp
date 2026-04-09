"""Intermediate Representation (IR) para documentos juridicos.

El IR es un formato estructurado entre el documento crudo y la IA.
En vez de enviar texto plano, el IR preserva estructura: zonas, fuentes,
posiciones, tablas — permitiendo extraccion mecanica de ~14 campos
y reduciendo la carga de IA a ~8 campos semanticos.
"""

from dataclasses import dataclass, field


@dataclass
class TextSpan:
    """Fragmento de texto con metadata tipografica."""
    text: str
    font_name: str = ""
    font_size: float = 0.0
    is_bold: bool = False
    is_italic: bool = False
    page: int = 0


# Tipos de zona reconocidos en documentos juridicos
ZONE_TYPES = {
    "HEADER",       # Encabezado: juzgado, ciudad, radicado (fuente grande, top pagina)
    "RADICADO",     # Numero de radicado detectado (23 digitos o formato T-)
    "PARTIES",      # Partes: accionante, accionados, vinculados
    "RIGHTS",       # Derechos vulnerados invocados
    "DATES",        # Fechas detectadas en el documento
    "BODY",         # Cuerpo del documento (texto principal)
    "RESOLUTION",   # Parte resolutiva: RESUELVE, fallo, decision
    "FOOTER",       # Pie de pagina: abogado, firma, proyeccion
    "TABLE",        # Tabla detectada
    "WATERMARK",    # Marca de agua (FOREST, sellos)
}


@dataclass
class DocumentZone:
    """Zona semantica detectada dentro de un documento."""
    zone_type: str          # Uno de ZONE_TYPES
    text: str               # Contenido textual de la zona
    spans: list[TextSpan] = field(default_factory=list)
    page: int = 0
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)  # Datos estructurados de la zona
    truncated: bool = False  # True si el texto fue recortado por limite de caracteres


@dataclass
class DocumentIR:
    """Representacion intermedia de UN documento."""
    filename: str
    doc_type: str           # PDF_AUTO_ADMISORIO, PDF_SENTENCIA, DOCX_RESPUESTA, etc.
    priority: int           # 1=auto, 2=sentencia, 3=respuesta, 4=email, 5=otro
    zones: list[DocumentZone] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)  # tabla → filas → celdas
    full_text: str = ""     # Texto plano completo (fallback)
    page_count: int = 0
    has_ocr_pages: bool = False
    extraction_method: str = ""

    def get_zones(self, zone_type: str) -> list[DocumentZone]:
        """Obtener todas las zonas de un tipo."""
        return [z for z in self.zones if z.zone_type == zone_type]

    def get_zone_text(self, zone_type: str) -> str:
        """Obtener texto concatenado de todas las zonas de un tipo."""
        return "\n".join(z.text for z in self.zones if z.zone_type == zone_type)

    def get_zone_metadata(self, zone_type: str) -> dict:
        """Obtener metadata combinada de todas las zonas de un tipo."""
        combined = {}
        for z in self.zones:
            if z.zone_type == zone_type:
                combined.update(z.metadata)
        return combined


@dataclass
class CaseIR:
    """Representacion intermedia de un CASO completo (todos sus documentos)."""
    case_id: int
    folder_name: str
    documents: list[DocumentIR] = field(default_factory=list)
    emails: list[dict] = field(default_factory=list)       # {subject, sender, date, body}
    known_fields: dict = field(default_factory=dict)        # Campos ya en DB
    corrections: list[dict] = field(default_factory=list)   # Correcciones historicas
    knowledge_snippets: list[str] = field(default_factory=list)

    def get_docs_by_type(self, doc_type: str) -> list[DocumentIR]:
        """Obtener documentos filtrados por tipo."""
        return [d for d in self.documents if d.doc_type == doc_type]

    def get_all_zones(self, zone_type: str) -> list[tuple[str, DocumentZone]]:
        """Obtener zonas de un tipo de TODOS los documentos. Retorna (filename, zone)."""
        result = []
        for doc in self.documents:
            for z in doc.zones:
                if z.zone_type == zone_type:
                    result.append((doc.filename, z))
        return result

    def to_compact_prompt(self, fields_needed: list[str]) -> str:
        """Serializar IR a prompt compacto para la IA.

        Solo incluye zonas relevantes para los campos pedidos, no texto completo.
        """
        parts = []
        parts.append(f"CASO: {self.folder_name}")

        # Campos ya conocidos (regex los lleno)
        if self.known_fields:
            parts.append("\nCAMPOS YA EXTRAIDOS (no repetir, usar como contexto):")
            for k, v in self.known_fields.items():
                if v:
                    parts.append(f"  {k}: {v}")

        # Correcciones historicas
        if self.corrections:
            parts.append("\nCORRECCIONES PREVIAS (no repetir estos errores):")
            for c in self.corrections[:5]:
                parts.append(f"  {c.get('field', '?')}: IA dijo '{c.get('ai_value', '')}' → correcto: '{c.get('corrected_value', '')}'")

        # Documentos: solo zonas relevantes (max 2 docs con BODY)
        body_count = 0
        for doc in sorted(self.documents, key=lambda d: d.priority):
            relevant_zones = []
            for z in doc.zones:
                if z.zone_type in ("HEADER", "PARTIES", "RIGHTS", "RESOLUTION", "DATES"):
                    relevant_zones.append(z)
                elif z.zone_type == "BODY" and doc.priority <= 2 and body_count < 2:
                    # Solo BODY de los 2 docs mas importantes, truncado a 3000 chars
                    body_text = z.text[:3000] if len(z.text) > 3000 else z.text
                    relevant_zones.append(DocumentZone(
                        zone_type="BODY", text=body_text, page=z.page,
                    ))
                    body_count += 1

            if relevant_zones:
                parts.append(f"\n=== {doc.filename} [{doc.doc_type}] ===")
                for z in relevant_zones:
                    parts.append(f"[{z.zone_type}] {z.text}")

        # Emails (compactos)
        for em in self.emails[:5]:
            parts.append(f"\n=== EMAIL: {em.get('subject', '')[:60]} ===")
            parts.append(f"De: {em.get('sender', '')} | Fecha: {em.get('date', '')}")
            body = em.get('body', '')[:2000]
            if body:
                parts.append(body)

        return "\n".join(parts)
