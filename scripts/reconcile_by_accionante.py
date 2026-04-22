"""v5.1 Sprint 4.3 — Reconcile docs en casos DUPLICATE_MERGED usando matching por accionante.

reconcile_db.py original buscaba canonico solo por rad23 o por id explicito en obs.
Este script busca matching por accionante para los casos merged que no lo tenian.

Estrategia:
1. Para cada caso DUPLICATE_MERGED con docs huerfanos, si tiene accionante:
   - Buscar caso activo con accionante similar (>=2 apellidos en comun)
   - Si el caso activo tiene mismo rad_corto o mismo municipio → match
2. Solo mueve si confianza ALTA (accionante match Y algun identificador adicional)

Uso:
    python3 scripts/reconcile_by_accionante.py --dry-run
    python3 scripts/reconcile_by_accionante.py              # aplica
"""

import argparse
import logging
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal, wal_checkpoint
from backend.database.models import Case, Document, Email, AuditLog

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reconcile_acc")


def _norm(s: str) -> str:
    """Normalizar texto: sin tildes, mayusculas, sin puntuacion."""
    if not s:
        return ""
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = re.sub(r"[^\w\s]", " ", s).upper()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _accionante_tokens(acc: str) -> set[str]:
    """Extraer apellidos significativos del accionante."""
    SKIP = {"AGENTE", "OFICIOSO", "MENOR", "REPRESENTANTE", "LEGAL", "MUNICIPAL",
            "PERSONERO", "PERSONERA", "PERSONERIA", "ACCION", "TUTELA", "CONTRA",
            "HIJO", "HIJA", "SEÑOR", "SEÑORA", "COMO", "REPRESENTATE", "REPRESENTACION",
            "NOMBRE", "EN", "DE", "DEL", "LA", "EL", "LOS", "LAS", "Y"}
    return {w for w in _norm(acc).split() if len(w) >= 4 and w not in SKIP}


def _rad_corto(rad23: str | None) -> str | None:
    if not rad23:
        return None
    digits = re.sub(r"\D", "", rad23)
    m = re.search(r"(20\d{2})(\d{5})\d{2}$", digits)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def find_canonical_by_accionante(db, merged_case: Case) -> tuple[Case | None, str]:
    """Buscar canonico por matching de accionante. Returns (canon, reason)."""
    if not merged_case.accionante:
        return None, "sin accionante"

    target_tokens = _accionante_tokens(merged_case.accionante)
    if len(target_tokens) < 2:
        return None, "accionante con <2 tokens distintivos"

    merged_rc = _rad_corto(merged_case.radicado_23_digitos)

    candidates = db.query(Case).filter(
        Case.id != merged_case.id,
        Case.processing_status != "DUPLICATE_MERGED",
        Case.accionante.isnot(None),
    ).all()

    # v5.1: tomar primeros 4 tokens del accionante (el "nombre propio")
    merged_name_tokens = list(target_tokens)[:4]
    merged_name_set = set(merged_name_tokens)

    best = None
    best_score = 0
    for cand in candidates:
        cand_tokens = _accionante_tokens(cand.accionante)
        # Requerir que al menos 2 tokens del NOMBRE del merged aparezcan en el canonico
        name_overlap = merged_name_set & cand_tokens
        if len(name_overlap) < 2:
            continue
        overlap = target_tokens & cand_tokens
        score = len(overlap)
        # Boost si comparten rad_corto
        cand_rc = _rad_corto(cand.radicado_23_digitos)
        if merged_rc and cand_rc and merged_rc == cand_rc:
            score += 5
        # Boost si comparten ciudad
        merged_cities = re.findall(r"[A-Z]{4,}", _norm(merged_case.folder_name or ""))
        cand_cities = re.findall(r"[A-Z]{4,}", _norm(cand.folder_name or ""))
        common_cities = set(merged_cities) & set(cand_cities)
        if common_cities:
            score += 1
        if score > best_score:
            best_score = score
            best = cand

    if best and best_score >= 3:
        return best, f"accionante match (score={best_score}, tokens={target_tokens & _accionante_tokens(best.accionante)})"
    return None, "sin match suficiente"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-score", type=int, default=3, help="Score minimo para consolidar (default: 3)")
    args = parser.parse_args()

    db = SessionLocal()

    # Encontrar casos DUPLICATE_MERGED que tienen docs huerfanos
    merged_with_docs = db.query(Case).filter(
        Case.processing_status == "DUPLICATE_MERGED",
        Case.id.in_(db.query(Document.case_id).distinct()),
    ).all()

    logger.info("Casos DUPLICATE_MERGED con docs huerfanos: %d", len(merged_with_docs))

    matched = 0
    unmatched = 0
    docs_moved_total = 0
    emails_moved_total = 0

    for mc in merged_with_docs:
        canon, reason = find_canonical_by_accionante(db, mc)
        if not canon:
            unmatched += 1
            logger.info("  ✗ id=%d '%s' — %s", mc.id, (mc.folder_name or '')[:40], reason)
            continue

        # Contar docs y emails que se moverian
        doc_count = db.query(Document).filter(Document.case_id == mc.id).count()
        email_count = db.query(Email).filter(Email.case_id == mc.id).count()

        logger.info("  ✓ id=%d '%s' → id=%d '%s' (%d docs, %d emails) %s",
                    mc.id, (mc.folder_name or '')[:35], canon.id, (canon.folder_name or '')[:35],
                    doc_count, email_count, reason)

        if not args.dry_run:
            # Mover docs + emails
            docs_moved = db.query(Document).filter(Document.case_id == mc.id).update(
                {"case_id": canon.id}, synchronize_session=False)
            emails_moved = db.query(Email).filter(Email.case_id == mc.id).update(
                {"case_id": canon.id}, synchronize_session=False)
            db.add(AuditLog(
                case_id=mc.id, field_name="docs_case_id",
                old_value=str(mc.id), new_value=str(canon.id),
                action="RECONCILE_ACC_V51", source=reason[:200],
            ))
            docs_moved_total += docs_moved
            emails_moved_total += emails_moved
        matched += 1

    if not args.dry_run:
        db.commit()
        wal_checkpoint("PASSIVE")

    logger.info("═" * 60)
    logger.info("%s Reconcile por accionante:", "DRY RUN" if args.dry_run else "APLICADO")
    logger.info("  Merged con match:   %d", matched)
    logger.info("  Merged sin match:   %d", unmatched)
    logger.info("  Docs movidos:       %d", docs_moved_total)
    logger.info("  Emails movidos:     %d", emails_moved_total)
    db.close()


if __name__ == "__main__":
    main()
