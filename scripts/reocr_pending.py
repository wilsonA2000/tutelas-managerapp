"""v5.1 Sprint 2 — Re-OCR de documentos PENDIENTE_OCR.

Aplica normalize_pdf_lightweight (PaddleOCR) a cada doc con verificacion='PENDIENTE_OCR'
y actualiza extracted_text + verificacion.

Uso:
    python3 scripts/reocr_pending.py              # aplica a todos
    python3 scripts/reocr_pending.py --limit 10   # solo primeros 10 (prueba)
    python3 scripts/reocr_pending.py --dry-run    # solo lista
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal, wal_checkpoint
from backend.database.models import Document, AuditLog

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reocr")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Limite de docs a procesar (0=todos)")
    parser.add_argument("--dry-run", action="store_true", help="Solo listar, no procesar")
    args = parser.parse_args()

    db = SessionLocal()
    q = db.query(Document).filter(Document.verificacion == "PENDIENTE_OCR")
    if args.limit:
        q = q.limit(args.limit)
    docs = q.all()

    logger.info("Docs PENDIENTE_OCR encontrados: %d", len(docs))

    if args.dry_run:
        for d in docs[:20]:
            logger.info("  [%d] %s (case=%d)", d.id, d.filename, d.case_id or 0)
        if len(docs) > 20:
            logger.info("  ... y %d mas", len(docs) - 20)
        db.close()
        return

    # Import lazy (PaddleOCR es pesado)
    try:
        from backend.extraction.document_normalizer import normalize_pdf_lightweight
    except ImportError as e:
        logger.error("No se pudo importar normalizer: %s", e)
        db.close()
        return

    updated_ok = 0
    updated_still_empty = 0
    failed = 0
    total_time = 0

    for i, doc in enumerate(docs, 1):
        if not doc.file_path or not Path(doc.file_path).is_file():
            logger.warning("[%d/%d] %s — archivo no existe, skip", i, len(docs), doc.filename)
            failed += 1
            continue

        start = time.time()
        try:
            result = normalize_pdf_lightweight(doc.file_path)
            elapsed = time.time() - start
            total_time += elapsed
            text = (result.text or "").strip()
            if len(text) >= 50:
                doc.extracted_text = text
                doc.extraction_method = result.method or "ocr_reocr_v51"
                doc.verificacion = "OK"
                doc.verificacion_detalle = f"Re-OCR v5.1: {len(text)} chars extraidos"
                db.add(AuditLog(
                    case_id=doc.case_id or 0, field_name="verificacion",
                    old_value="PENDIENTE_OCR", new_value="OK",
                    action="REOCR_V51", source=f"doc_id={doc.id}",
                ))
                updated_ok += 1
                logger.info("[%d/%d] ✅ %s — %d chars (%.1fs)", i, len(docs), doc.filename, len(text), elapsed)
            else:
                doc.verificacion = "REVISAR"
                doc.verificacion_detalle = f"Re-OCR v5.1: texto insuficiente ({len(text)} chars)"
                updated_still_empty += 1
                logger.info("[%d/%d] ⚠️  %s — solo %d chars (%.1fs)", i, len(docs), doc.filename, len(text), elapsed)
        except Exception as e:
            logger.warning("[%d/%d] ❌ %s — %s", i, len(docs), doc.filename, str(e)[:80])
            failed += 1

        if i % 10 == 0:
            db.commit()
            logger.info("Commit parcial tras %d docs", i)

    db.commit()
    wal_checkpoint("PASSIVE")
    db.close()

    logger.info("═" * 60)
    logger.info("Re-OCR completado:")
    logger.info("  ✅ Recuperados (→OK):     %d", updated_ok)
    logger.info("  ⚠️  Texto insuficiente:   %d (→ REVISAR)", updated_still_empty)
    logger.info("  ❌ Fallidos:              %d", failed)
    logger.info("  ⏱  Tiempo total:         %.1fs", total_time)
    logger.info("  ⏱  Promedio por doc:     %.1fs", total_time / max(len(docs), 1))


if __name__ == "__main__":
    main()
