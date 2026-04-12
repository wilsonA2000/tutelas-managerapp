"""Context Engine: recopila TODO el contexto de un caso antes de cualquier decisión IA.

Para cada caso, el ContextAssembler reúne:
1. Documentos del folder (texto extraído)
2. Email_*.md del folder
3. Emails en DB vinculados (body completo)
4. Campos actuales en DB
5. Casos relacionados (mismo accionante, mismo radicado, mismo municipio)
6. Knowledge Base search results
7. Correcciones históricas (para few-shot learning)

Output: CaseContext serializable a prompt para IA (DeepSeek/Haiku).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

logger = logging.getLogger("tutelas.context")


@dataclass
class DocumentContext:
    filename: str
    doc_type: str  # pdf, docx, md, gmail_pdf, email_md
    content: str
    priority: int  # 1=highest (auto admisorio), 5=lowest


@dataclass
class EmailContext:
    email_id: int
    subject: str
    sender: str
    body: str
    attachments: list[str]
    date: str


@dataclass
class RelatedCase:
    case_id: int
    folder_name: str
    accionante: str
    relation: str  # same_accionante, same_radicado_prefix, same_municipio, same_juzgado


@dataclass
class CorrectionContext:
    field_name: str
    ai_value: str
    corrected_value: str
    case_folder: str


@dataclass
class CaseContext:
    """Contexto completo de un caso."""
    case_id: int
    folder_name: str
    known_fields: dict[str, str]  # Campos ya llenados en DB
    documents: list[DocumentContext]
    emails: list[EmailContext]
    related_cases: list[RelatedCase]
    corrections: list[CorrectionContext]
    knowledge_snippets: list[str]

    def to_prompt(self, max_tokens: int = 500000) -> str:
        """Serializar contexto a texto para incluir en prompt de IA."""
        parts = []

        # Known data
        if self.known_fields:
            parts.append("=== DATOS CONOCIDOS DEL CASO ===")
            parts.append(f"Carpeta: {self.folder_name}")
            for k, v in self.known_fields.items():
                if v:
                    parts.append(f"  {k}: {v}")

        # Documents (sorted by priority)
        sorted_docs = sorted(self.documents, key=lambda d: d.priority)
        parts.append(f"\n=== DOCUMENTOS DEL CASO ({len(sorted_docs)} archivos) ===")
        for doc in sorted_docs:
            parts.append(f"\n--- {doc.filename} [{doc.doc_type}] (prioridad: {doc.priority}) ---")
            parts.append(doc.content[:30000])  # Max 30K per doc

        # Emails
        if self.emails:
            parts.append(f"\n=== CORREOS VINCULADOS ({len(self.emails)}) ===")
            for em in self.emails:
                parts.append(f"\n--- Email: {em.subject} ---")
                parts.append(f"De: {em.sender} | Fecha: {em.date}")
                if em.attachments:
                    parts.append(f"Adjuntos: {', '.join(em.attachments)}")
                parts.append(em.body[:5000])

        # Related cases
        if self.related_cases:
            parts.append(f"\n=== CASOS RELACIONADOS ({len(self.related_cases)}) ===")
            for rc in self.related_cases:
                parts.append(f"  - [{rc.relation}] {rc.folder_name} | Accionante: {rc.accionante}")

        # Corrections (few-shot examples)
        if self.corrections:
            parts.append(f"\n=== CORRECCIONES HISTÓRICAS (úsalas como referencia) ===")
            for c in self.corrections:
                parts.append(f"  Campo {c.field_name}: IA dijo '{c.ai_value}' → correcto es '{c.corrected_value}' (caso: {c.case_folder})")

        full_text = "\n".join(parts)

        # Estimate tokens (~4 chars per token) and truncate if needed
        est_tokens = len(full_text) // 4
        if est_tokens > max_tokens:
            max_chars = max_tokens * 4
            full_text = full_text[:max_chars] + "\n\n[CONTEXTO TRUNCADO POR LÍMITE DE TOKENS]"

        return full_text

    @property
    def total_tokens_estimate(self) -> int:
        return len(self.to_prompt()) // 4


class ContextAssembler:
    """Ensambla el contexto completo de un caso desde múltiples fuentes."""

    # Priority mapping for document types
    DOC_PRIORITIES = {
        "auto": 1, "admite": 1, "avoca": 1,
        "sentencia": 2, "fallo": 2,
        "respuesta": 3, "forest": 3,
        "impugn": 3,
        "gmail": 4, "email": 4,
        "incidente": 3, "desacato": 3,
    }

    def __init__(self, db: Session, base_dir: str):
        self.db = db
        self.base_dir = Path(base_dir)

    def assemble(self, case_id: int) -> CaseContext:
        """Ensamblar contexto completo de un caso."""
        from backend.database.models import Case, Document, Email

        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Caso {case_id} no encontrado")

        # 1. Known fields from DB
        known_fields = self._get_known_fields(case)

        # 2. Documents from folder
        documents = self._get_documents(case)

        # 3. Emails linked to case
        emails = self._get_emails(case_id)

        # 4. Related cases
        related = self._find_related_cases(case)

        # 5. Corrections (from agent memory)
        corrections = self._get_corrections(case_id)

        # 6. Knowledge Base snippets
        snippets = self._search_knowledge(case)

        ctx = CaseContext(
            case_id=case_id,
            folder_name=case.folder_name or "",
            known_fields=known_fields,
            documents=documents,
            emails=emails,
            related_cases=related,
            corrections=corrections,
            knowledge_snippets=snippets,
        )

        logger.info(
            "Context assembled for case %d: %d docs, %d emails, %d related, ~%dK tokens",
            case_id, len(documents), len(emails), len(related),
            ctx.total_tokens_estimate // 1000,
        )
        return ctx

    def _get_known_fields(self, case) -> dict[str, str]:
        fields = {}
        # OBSERVACIONES excluido: siempre debe regenerarse con el contexto completo actual
        for col in ["radicado_23_digitos", "radicado_forest", "accionante", "accionados",
                     "vinculados", "juzgado", "ciudad", "derecho_vulnerado", "asunto",
                     "pretensiones", "abogado_responsable", "estado", "sentido_fallo_1st",
                     "fecha_fallo_1st", "impugnacion", "sentido_fallo_2nd", "incidente",
                     "oficina_responsable"]:
            val = getattr(case, col, None)
            if val and str(val).strip():
                fields[col] = str(val).strip()
        return fields

    def _get_documents(self, case) -> list[DocumentContext]:
        from backend.database.models import Document

        docs = []
        db_docs = self.db.query(Document).filter(Document.case_id == case.id).all()

        for doc in db_docs:
            content = doc.extracted_text or ""
            if not content and case.folder_name:
                # Try reading from disk
                filepath = self.base_dir / case.folder_name / doc.filename
                if filepath.exists() and filepath.suffix == ".md":
                    try:
                        content = filepath.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        pass

            # Normalizer: intentar extraer PDFs sin texto usando pdftext/PaddleOCR
            if not content and doc.file_path:
                try:
                    from backend.core.settings import settings
                    if settings.NORMALIZER_ENABLED:
                        fpath = Path(doc.file_path)
                        if fpath.exists() and fpath.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg"):
                            from backend.extraction.document_normalizer import normalize_document
                            norm = normalize_document(fpath)
                            if norm.text.strip():
                                content = norm.text
                except Exception:
                    pass

            if not content:
                continue

            # Determine type and priority
            fname_lower = doc.filename.lower()
            doc_type = "pdf"
            if fname_lower.endswith(".docx"):
                doc_type = "docx"
            elif fname_lower.endswith(".md"):
                doc_type = "email_md" if fname_lower.startswith("email_") else "md"
            elif fname_lower.startswith("gmail"):
                doc_type = "gmail_pdf"

            priority = 5  # default
            for keyword, prio in self.DOC_PRIORITIES.items():
                if keyword in fname_lower:
                    priority = min(priority, prio)
                    break

            docs.append(DocumentContext(
                filename=doc.filename,
                doc_type=doc_type,
                content=content,
                priority=priority,
            ))

        # Also read Email_*.md from disk if not in DB
        if case.folder_name:
            folder = self.base_dir / case.folder_name
            if folder.exists():
                db_filenames = {d.filename for d in docs}
                for md_file in folder.glob("Email_*.md"):
                    if md_file.name not in db_filenames:
                        try:
                            content = md_file.read_text(encoding="utf-8", errors="ignore")
                            docs.append(DocumentContext(
                                filename=md_file.name,
                                doc_type="email_md",
                                content=content,
                                priority=4,
                            ))
                        except Exception:
                            pass

        return docs

    def _get_emails(self, case_id: int) -> list[EmailContext]:
        from backend.database.models import Email
        import json

        emails = self.db.query(Email).filter(Email.case_id == case_id).all()
        result = []
        for em in emails:
            attachments = []
            if em.attachments:
                try:
                    att = json.loads(em.attachments) if isinstance(em.attachments, str) else em.attachments
                    attachments = [a.get("filename", "") if isinstance(a, dict) else str(a) for a in att]
                except Exception:
                    pass

            result.append(EmailContext(
                email_id=em.id,
                subject=em.subject or "",
                sender=em.sender or "",
                body=em.body_preview or "",
                attachments=attachments,
                date=em.date_received.isoformat() if em.date_received else "",
            ))
        return result

    def _find_related_cases(self, case) -> list[RelatedCase]:
        from backend.database.models import Case
        import re

        related = []
        # Extract short radicado from folder name
        rad_match = re.search(r"(20\d{2})-?0*(\d{2,5})", case.folder_name or "")
        rad_prefix = ""
        if rad_match:
            rad_prefix = f"{rad_match.group(1)}-{rad_match.group(2).zfill(5)}"

        # Same radicado prefix (different municipalities)
        if rad_prefix:
            others = self.db.query(Case).filter(
                Case.id != case.id,
                Case.folder_name.contains(rad_prefix[:9]),  # year + first digits
            ).limit(5).all()
            for o in others:
                related.append(RelatedCase(
                    case_id=o.id, folder_name=o.folder_name or "",
                    accionante=o.accionante or "", relation="same_radicado_prefix",
                ))

        # Same accionante (different tutelas)
        if case.accionante and len(case.accionante) > 5:
            words = case.accionante.upper().split()
            if len(words) >= 2:
                search_term = words[0]  # First apellido
                others = self.db.query(Case).filter(
                    Case.id != case.id,
                    Case.accionante.contains(search_term),
                ).limit(5).all()
                for o in others:
                    if o.id not in [r.case_id for r in related]:
                        related.append(RelatedCase(
                            case_id=o.id, folder_name=o.folder_name or "",
                            accionante=o.accionante or "", relation="same_accionante",
                        ))

        return related[:10]  # Max 10 related

    def _get_corrections(self, case_id: int) -> list[CorrectionContext]:
        """Get recent corrections from agent memory (if available)."""
        try:
            from backend.agent.memory import get_recent_corrections
            return get_recent_corrections(self.db, case_id, limit=10)
        except (ImportError, Exception):
            return []

    def _search_knowledge(self, case) -> list[str]:
        """Search Knowledge Base for relevant snippets."""
        try:
            from backend.knowledge.search import full_text_search
            snippets = []
            # Search by accionante
            if case.accionante:
                results = full_text_search(self.db, case.accionante, limit=3)
                for r in results:
                    if r.case_id != case.id:
                        snippets.append(f"[{r.source_type}] {r.snippet}")
            return snippets[:5]
        except Exception:
            return []
