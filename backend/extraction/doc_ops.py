"""Utilidades de documentos del pipeline — módulo autoritativo (Fase 7.5a).

Aquí viven los cuerpos de las funciones de documentos que el código vivo usa:
lectura de texto, clasificación de doctype por nombre, verificación de pertenencia
doc↔caso (legacy y bayesiana), dedup por hash, re-extracción.

NO incluye `process_folder` ni el resto del motor de extracción v8 — eso vive en
`pipeline.py` (sin uso desde v9, candidato a borrado) y se reemplazó por
`backend/v9/pipeline.py`. `pipeline.py` re-importa estas funciones desde aquí para
no romper a sus consumidores legacy (`unified*.py`, `ir_builder.py`, tests).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import Case, Document
from backend.extraction.pdf_extractor import extract_pdf
from backend.extraction.docx_extractor import extract_docx
from backend.extraction.doc_extractor import extract_doc

logger = logging.getLogger("tutelas.extraction.doc_ops")


__all__ = [
    "extract_document_text",
    "classify_doc_type",
    "reextract_document",
    "compute_file_hash",
    "detect_duplicate_documents",
    "verify_document_belongs",
    "verify_all_documents",
    "_verify_bayesian",
    "_verify_legacy",
]


# ── (los cuerpos de las funciones se anexan abajo desde pipeline.py — Fase 7.5a) ──


def extract_document_text(doc: Document) -> tuple[str, str]:
    """Extraer texto de un documento segun su tipo de archivo. Retorna (texto, metodo)."""
    path = Path(doc.file_path)
    ext = path.suffix.lower()

    # Normalizer mejorado para PDFs e imagenes (DOCX excluido — preserva footer regex)
    try:
        from backend.core.settings import settings
        if settings.NORMALIZER_ENABLED and ext not in (".docx", ".doc"):
            from backend.extraction.document_normalizer import normalize_document
            result = normalize_document(doc.file_path)
            if result.text.strip():
                return result.text, result.method
    except Exception:
        pass  # Fallback silencioso a extractores legacy

    if ext == ".pdf":
        result = extract_pdf(doc.file_path)
        return result.text, result.method

    elif ext == ".docx":
        result = extract_docx(doc.file_path)
        return result.text, result.method

    elif ext == ".doc":
        result = extract_doc(doc.file_path)
        return result.text, result.method

    elif ext == ".md":
        try:
            text = Path(doc.file_path).read_text(encoding="utf-8", errors="replace")
            return text, "markdown"
        except Exception:
            return "", "md_error"

    elif ext in (".png", ".jpg", ".jpeg"):
        return "", "no_ocr"

    return "", "unsupported"


def classify_doc_type(filename: str) -> str:
    """Clasificar tipo de documento por nombre de archivo.
    Fuente unica de verdad para clasificacion de documentos."""
    fn = filename.lower()
    # DOCX clasificación detallada
    if fn.endswith(".docx") or (fn.endswith(".doc") and ".doc " not in fn):
        if any(k in fn for k in ("respuesta", "contestacion", "contestación")):
            if any(k in fn for k in ("incidente", "desacato")):
                return "DOCX_DESACATO"
            if "impugnacion" in fn or "impugnación" in fn:
                return "DOCX_IMPUGNACION"
            return "DOCX_RESPUESTA"
        if "cumplimiento" in fn:
            return "DOCX_CUMPLIMIENTO"
        if any(k in fn for k in ("forest", "con forest", "con  forest")):
            return "DOCX_RESPUESTA"  # "CON FOREST" = respuesta radicada
        if any(k in fn for k in ("solicitu", "insumo")):
            return "DOCX_SOLICITUD"
        if any(k in fn for k in ("memorial", "aclaratori")):
            return "DOCX_MEMORIAL"
        if any(k in fn for k in ("carta", "oficio")):
            return "DOCX_CARTA"
        return "DOCX_OTRO"
    # PDFs y otros
    if fn.startswith("email_") and fn.endswith(".md"):
        return "EMAIL_MD"
    if fn.startswith("gmail") or fn.startswith("rv_"):
        return "PDF_GMAIL"
    if any(k in fn for k in ("auto", "admite", "avoca", "admisorio")):
        return "PDF_AUTO_ADMISORIO"
    if any(k in fn for k in ("sentencia", "fallo")):
        return "PDF_SENTENCIA"
    if any(k in fn for k in ("impugn",)):
        return "PDF_IMPUGNACION"
    if any(k in fn for k in ("incidente", "desacato")):
        return "PDF_INCIDENTE"
    # Respuesta/contestación de la SED (la rama DOCX ya la detectaba; en PDF faltaba
    # → quedaban PDF_OTRO y los extractores que filtran doc_type=="RESPUESTA" no los leían).
    if any(k in fn for k in ("respuesta", "contesta")):
        return "RESPUESTA"
    # FIX (2026-05-28): patrones descubiertos en sesión de curación masiva
    if "acta_individual_de_reparto" in fn or "acta individual de reparto" in fn \
       or "actareparto" in fn:
        return "ACTA_REPARTO"
    if fn.startswith("rt_") and re.search(r"^rt_\d{4}-\d+", fn):
        return "INSUMO_CONTESTACION"
    if "elementos_enviados" in fn or "elementos enviados" in fn:
        return "EMAIL_OUTLOOK_PDF"
    if "memorial" in fn or "memorialaccionante" in fn:
        return "MEMORIAL_ACCIONANTE"
    if "acumulaci" in fn or "autoacumula" in fn or "auto_acumula" in fn:
        return "AUTO_ACUMULACION"
    if "nulidad" in fn or "autonulidad" in fn or "decreta_nulidad" in fn:
        return "AUTO_NULIDAD"
    if "obedezca" in fn or "obedezcase" in fn or "cumplas" in fn:
        return "AUTO_OBEDEZCASE_Y_CUMPLASE"
    if "abstien" in fn or "abstenerse_abrir" in fn or "abstenerseabrir" in fn:
        return "AUTO_ABSTIENE_INCIDENTE"
    if "concede.impugn" in fn or "concedeimpugnacion" in fn:
        return "AUTO_CONCEDE_IMPUGNACION"
    if "vincula" in fn:
        return "AUTO_VINCULA"
    if "desistimiento" in fn:
        return "AUTO_DESISTIMIENTO"
    if "archiv" in fn and ("incidente" in fn or "expediente" in fn):
        return "AUTO_ARCHIVA"
    if "registro_presupuestal" in fn or fn.startswith("rp_") or fn.startswith("cdp_"):
        return "ANEXO_PRUEBA"
    if "convenio.interadministrativo" in fn or fn.startswith("minuta"):
        return "INSUMO_ADMINISTRATIVO"
    if "camscanner" in fn or fn.startswith("document_"):
        return "ANEXO_PRUEBA"
    if "estudio_tecnico" in fn or "ip-gu" in fn or "copia_controlada" in fn:
        return "INSUMO_PROCEDIMIENTO"
    # Nombre propio archivo (NOMBRE_APELLIDO.pdf) → ANEXO_PRUEBA típico
    if re.match(r"^[A-Za-zÁÉÍÓÚÑáéíóúñ]+_[A-Za-zÁÉÍÓÚÑáéíóúñ]+(?:_[A-Za-zÁÉÍÓÚÑáéíóúñ]+)?\.pdf$", filename):
        return "ANEXO_PRUEBA"
    if fn.startswith("email"):
        return "EMAIL_DB"
    # Screenshots
    if fn.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
        return "SCREENSHOT"
    return "PDF_OTRO"


def reextract_document(db: Session, doc: Document) -> tuple[str, str]:
    """Re-extraer texto de un documento especifico."""
    text, method = extract_document_text(doc)
    doc.extracted_text = text
    doc.extraction_method = method
    doc.extraction_date = datetime.utcnow()
    db.commit()
    return text, method


def compute_file_hash(file_path: str) -> str:
    """Calcular hash MD5 de un archivo."""
    import hashlib
    try:
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def detect_duplicate_documents(db) -> list[dict]:
    """Detectar documentos duplicados entre carpetas diferentes (mismo hash MD5)."""
    from collections import defaultdict

    # Calcular hashes faltantes
    docs_no_hash = db.query(Document).filter(
        Document.file_hash == "", Document.file_path.isnot(None),
    ).all()
    for doc in docs_no_hash:
        if doc.file_path and Path(doc.file_path).exists():
            doc.file_hash = compute_file_hash(doc.file_path)
    db.commit()

    # Agrupar por hash
    all_docs = db.query(Document).filter(Document.file_hash != "").all()
    hash_groups = defaultdict(list)
    for doc in all_docs:
        hash_groups[doc.file_hash].append(doc)

    # Encontrar duplicados (mismo hash en diferentes casos)
    duplicates = []
    for h, docs in hash_groups.items():
        case_ids = {d.case_id for d in docs}
        if len(case_ids) > 1:
            cases = {d.case_id: db.query(Case).filter(Case.id == d.case_id).first() for d in docs}
            duplicates.append({
                "hash": h,
                "files": [
                    {"doc_id": d.id, "filename": d.filename, "case_id": d.case_id,
                     "case_name": cases[d.case_id].folder_name if cases[d.case_id] else ""}
                    for d in docs
                ],
            })

    # Segundo paso: duplicados por contenido (texto similar, hash diferente)
    docs_with_text = db.query(Document).filter(
        Document.extracted_text.isnot(None),
        Document.extracted_text != "",
        Document.file_hash != "",
    ).all()

    # Agrupar por caso para comparar entre casos
    from itertools import combinations
    case_docs = defaultdict(list)
    for doc in docs_with_text:
        if doc.extracted_text and len(doc.extracted_text) > 200:
            case_docs[doc.case_id].append(doc)

    # Comparar docs entre diferentes casos usando trigram overlap
    seen_pairs = set()
    for (cid1, docs1), (cid2, docs2) in combinations(case_docs.items(), 2):
        if cid1 == cid2:
            continue
        for d1 in docs1[:10]:  # Limitar a 10 docs por caso
            t1 = (d1.extracted_text or "")[:5000].lower()
            if len(t1) < 200:
                continue
            trigrams1 = {t1[i:i+3] for i in range(len(t1) - 2)}
            for d2 in docs2[:10]:
                pair_key = tuple(sorted([d1.id, d2.id]))
                if pair_key in seen_pairs or d1.file_hash == d2.file_hash:
                    continue
                seen_pairs.add(pair_key)
                t2 = (d2.extracted_text or "")[:5000].lower()
                if len(t2) < 200:
                    continue
                trigrams2 = {t2[i:i+3] for i in range(len(t2) - 2)}
                overlap = len(trigrams1 & trigrams2) / max(len(trigrams1), len(trigrams2), 1)
                if overlap > 0.90:
                    c1 = db.query(Case).filter(Case.id == cid1).first()
                    c2 = db.query(Case).filter(Case.id == cid2).first()
                    duplicates.append({
                        "hash": f"content_sim_{overlap:.0%}",
                        "type": "content_similarity",
                        "files": [
                            {"doc_id": d1.id, "filename": d1.filename, "case_id": cid1,
                             "case_name": c1.folder_name if c1 else ""},
                            {"doc_id": d2.id, "filename": d2.filename, "case_id": cid2,
                             "case_name": c2.folder_name if c2 else ""},
                        ],
                    })

    return duplicates


def verify_document_belongs(case: Case, doc: Document) -> tuple[str, str]:
    """Verificar si un documento pertenece al caso.

    v6.0: delega a Bayesian assignment si `USE_COGNITIVE_PIPELINE=true`.
    Mantiene la implementación legacy (5 criterios rígidos) para compatibilidad
    cuando el feature flag está apagado.

    Returns: (status, detalle)
        status: 'OK' / 'SOSPECHOSO' / 'NO_PERTENECE' / 'REVISAR'
        detalle: explicación del resultado
    """
    # v6.0: feature flag → inferencia Bayesiana
    try:
        from backend.core.settings import settings
        if getattr(settings, "USE_COGNITIVE_PIPELINE", False):
            return _verify_bayesian(case, doc)
    except Exception:
        pass  # fallback a legacy si algo falla en el import/setting
    # Legacy (v5.5):
    return _verify_legacy(case, doc)


def _verify_bayesian(case: Case, doc: Document) -> tuple[str, str]:
    """Adapter v6.0: construye IR del doc y aplica Bayesian assignment.

    v6.0.16: Speedup — si extracted_text + visual_signature_json están persistidos
    en DB y pasan sanity check (len(text) >= 5% file_size), reciclar SIN reabrir
    el PDF. Reduce reverify de ~70min a ~30s sobre 1351 docs.
    """
    from backend.cognition.bayesian_assignment import infer_assignment
    from backend.extraction.ir_builder import _build_pdf_ir, _build_docx_ir
    from pathlib import Path as _P
    import json as _json
    path = _P(doc.file_path or "")
    ext = path.suffix.lower()

    ir = None
    # Intento de speedup: reciclar IR persistido en DB
    if doc.extracted_text and doc.visual_signature_json:
        try:
            file_size = path.stat().st_size if path.exists() else 0
            text_len = len(doc.extracted_text)
            # Sanity check: el texto persistido debe ser ≥5% del archivo, si no, reabrir
            if file_size == 0 or text_len >= file_size * 0.05 or text_len >= 1500:
                from backend.extraction.ir_models import DocumentIR, DocumentZone
                vs = _json.loads(doc.visual_signature_json or "{}")
                txt = doc.extracted_text
                head = txt[:2000]
                body = txt[:150_000]
                foot = txt[-4000:] if len(txt) > 4000 else txt
                zones = []
                if head.strip():
                    zones.append(DocumentZone(zone_type="HEADER", text=head))
                if body.strip():
                    zones.append(DocumentZone(zone_type="BODY", text=body))
                if foot.strip() and foot != head:
                    zones.append(DocumentZone(zone_type="FOOTER_TAIL", text=foot))
                ir = DocumentIR(
                    filename=doc.filename or "",
                    doc_type=doc.doc_type or "OTRO",
                    priority=9,
                    zones=zones,
                    full_text=txt,
                )
                ir.visual_signature = vs
        except Exception:
            ir = None

    # Fallback: construir IR completo desde archivo
    if ir is None:
        if ext == ".pdf" and path.exists():
            ir = _build_pdf_ir(str(path), doc.doc_type or "PDF_OTRO")
        elif ext in (".docx", ".doc") and path.exists():
            ir = _build_docx_ir(str(path), doc.doc_type or "DOCX_OTRO")
        else:
            # Sin acceso a archivo: crear IR mínimo a partir de extracted_text
            from backend.extraction.ir_models import DocumentIR, DocumentZone
            txt = doc.extracted_text or ""
            ir = DocumentIR(
                filename=doc.filename, doc_type=doc.doc_type or "OTRO", priority=9,
                zones=[DocumentZone(zone_type="BODY", text=txt)] if txt else [],
                full_text=txt,
            )

    verdict = infer_assignment(case, ir, doc=doc)
    detalle_parts = []
    if verdict.reasons_for:
        detalle_parts.append("+: " + "; ".join(verdict.reasons_for[:3]))
    if verdict.reasons_against:
        detalle_parts.append("-: " + "; ".join(verdict.reasons_against[:3]))
    if verdict.target_case_id:
        detalle_parts.append(f"→case_{verdict.target_case_id} ({verdict.target_evidence})")
    detalle_parts.append(f"post={verdict.posterior:.3f}")
    return verdict.verdict, " | ".join(detalle_parts)


def _verify_legacy(case: Case, doc: Document) -> tuple[str, str]:
    """Implementación v5.5: 5 criterios rígidos sobre primeros 10K chars."""
    import re
    import unicodedata

    filename = doc.filename or ""
    text = doc.extracted_text or ""

    # Emails .md siempre pertenecen (clasificados por Gmail)
    if filename.startswith("Email_") and filename.endswith(".md"):
        return "OK", "Email clasificado por Gmail"

    # Sin texto = verificar si es PDF encriptado
    if len(text) < 100:
        if doc.file_path and doc.file_path.lower().endswith(".pdf"):
            try:
                import fitz
                pdf = fitz.open(doc.file_path)
                if pdf.is_encrypted:
                    pdf.close()
                    return "REVISAR", "PDF encriptado - no se puede verificar pertenencia"
                pdf.close()
            except Exception:
                pass
        return "OK", "Documento sin texto suficiente"

    def _norm(s):
        return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').upper()

    # Extraer datos del caso
    folder = case.folder_name or ""
    m = re.match(r'(20\d{2})[-\s]?0*(\d+)', folder)
    if not m:
        return "OK", "Carpeta sin radicado"

    case_year = m.group(1)
    case_seq = m.group(2).lstrip('0') or '0'
    case_seq_padded = case_seq.zfill(5)

    # Radicado 23 dígitos del caso (normalizado sin separadores)
    case_rad23 = re.sub(r'[\s\-\.]', '', case.radicado_23_digitos or '')

    # Apellidos del accionante
    accionante = (case.accionante or "").upper()
    skip_words = {"AGENTE", "OFICIOSO", "MENOR", "REPRESENTANTE", "LEGAL", "MUNICIPAL",
                  "PERSONERO", "PERSONERA", "PERSONERIA", "ACCION", "TUTELA", "CONTRA",
                  "HIJO", "HIJA", "SEÑOR", "SEÑORA", "COMO", "REPRESENTATE", "REPRESENTACION",
                  "NOMBRE"}
    acc_words = [w for w in re.findall(r'[A-ZÁÉÍÓÚÑ]{4,}', _norm(accionante)) if w not in skip_words]

    text_upper = _norm(text[:10000])
    text_clean = re.sub(r'[\s\-\.]', '', text[:8000])

    # === CRITERIO 1: RADICADO 23 DIGITOS (definitivo) ===
    # Buscar TODOS los radicados 23d en el texto del documento
    rads_23_in_doc = re.findall(r'(68[\d]{17,21})', text_clean)

    if case_rad23 and len(case_rad23) >= 15 and rads_23_in_doc:
        # Verificar si el radicado 23d del caso está en el documento
        case_suffix = case_rad23[-17:]  # últimos 17 dígitos (incluye municipio + año + secuencia)
        doc_has_case_rad = any(case_suffix in r for r in rads_23_in_doc)

        # Verificar si el documento tiene un radicado 23d DIFERENTE
        other_rads_23 = [r for r in rads_23_in_doc if case_suffix not in r]

        if doc_has_case_rad:
            return "OK", "Radicado 23 dígitos del caso confirmado en documento"
        elif other_rads_23:
            # Tiene radicado 23d de OTRO caso → NO PERTENECE (alta confianza)
            return "NO_PERTENECE", f"Radicado 23d {other_rads_23[0][:20]}... NO coincide con caso {case_rad23[:20]}..."

    # === CRITERIO 2: ACCIONANTE en nombre del archivo ===
    # Archivos como "RESPUESTA FOREST B.L.A.R.docx" → las iniciales del accionante
    if acc_words and len(acc_words) >= 2:
        fn_upper = _norm(filename)
        fn_matches = sum(1 for w in acc_words[:3] if w in fn_upper)
        if fn_matches >= 1:
            return "OK", f"Accionante en nombre de archivo ({fn_matches} coincidencias)"

    # === CRITERIO 3: ACCIONANTE en el texto del documento ===
    if acc_words and len(acc_words) >= 2:
        matches = sum(1 for w in acc_words[:4] if w in text_upper)
        if matches >= 2:
            return "OK", f"Accionante mencionado en texto ({matches} apellidos)"

    # === CRITERIO 4: RADICADO CORTO en nombre de archivo ===
    if case_seq in filename or case_seq_padded in filename:
        return "OK", f"Radicado {case_seq} en nombre archivo"

    # === CRITERIO 5: RADICADO CORTO en texto ===
    rad_pattern = rf'{case_year}[-\s]?0*{case_seq}(?:\D|$)'
    if re.search(rad_pattern, text[:5000]):
        if not rads_23_in_doc:
            # Radicado corto sin confirmación 23d — ambiguo
            if case_rad23:
                return "REVISAR", f"Solo radicado corto {case_year}-{case_seq} (sin confirmacion 23d)"
            return "OK", f"Radicado {case_year}-{case_seq} en texto"

    # === Si llegamos aquí, NO encontramos referencia directa al caso ===
    # Buscar si tiene radicados cortos de OTRO caso

    otros_rads = re.findall(r'(20\d{2})[-\s]?0*(\d{2,5})\b', text[:5000])
    otros_reales = []
    for yr, sq in otros_rads:
        sq_clean = sq.lstrip('0') or '0'
        if sq_clean == case_seq and yr == case_year:
            continue
        if yr == "2012" and sq in ("35", "352", "3526"):
            continue
        if len(sq_clean) <= 2:
            continue
        yr_int = int(yr)
        if yr_int < 2019 or yr_int > 2030:
            continue
        if len(sq) > 5:
            continue
        sq_int = int(sq_clean)
        if len(sq_clean) >= 3 and sq_int > 600:
            continue
        otros_reales.append(f"{yr}-{sq}")

    if otros_reales:
        rad_encontrado = otros_reales[0]
        return "NO_PERTENECE", f"Radicado {rad_encontrado} encontrado, no coincide con {case_year}-{case_seq_padded}"

    # === CRITERIO 6: NOMBRE DE OTRO ACCIONANTE en filename ===
    # Si el archivo dice "RESPUESTA FOREST RAUL FABRA.docx" y el caso es de BELSY,
    # verificar si "RAUL FABRA" es accionante de OTRO caso en la DB
    fn_norm = _norm(filename)
    if acc_words and len(acc_words) >= 2:
        # Verificar que el accionante del caso NO está en el filename
        acc_in_fn = sum(1 for w in acc_words[:3] if w in fn_norm)
        if acc_in_fn == 0 and len(fn_norm) > 10:
            # El filename no menciona al accionante → podría ser de otro caso
            # Extraer palabras del filename que podrían ser nombres
            fn_words = set(re.findall(r'[A-Z]{4,}', fn_norm))
            fn_words -= {"RESPUESTA", "FOREST", "TUTELA", "FALLO", "AUTO", "SENTENCIA",
                         "GMAIL", "EMAIL", "OFICIO", "NOTIFICA", "URGENTE", "ADMISORIO",
                         "CONTESTACION", "IMPUGNACION", "INCIDENTE", "DESACATO",
                         "EDUCACION", "SANTANDER", "GOBERNACION", "SECRETARIA", "MERGED",
                         "ILOVEPDF", "COMPRESSED", "ANEXOS", "ESCRITO", "PRUEBA"}
            if len(fn_words) >= 2:
                return "SOSPECHOSO", f"Filename '{filename}' no menciona al accionante {accionante[:30]}"

    return "OK", "Sin radicados conflictivos"


def verify_all_documents(db: "Session") -> dict:
    """Auditoría retroactiva: verificar TODOS los documentos de todos los casos."""
    cases = db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
    ).all()

    stats = {"total": 0, "ok": 0, "sospechoso": 0, "no_pertenece": 0}

    for case in cases:
        for doc in case.documents:
            if not doc.extracted_text or len(doc.extracted_text) < 100:
                continue
            stats["total"] += 1
            status, detalle = verify_document_belongs(case, doc)
            doc.verificacion = status
            doc.verificacion_detalle = detalle
            stats[status.lower()] = stats.get(status.lower(), 0) + 1

    db.commit()
    return stats


