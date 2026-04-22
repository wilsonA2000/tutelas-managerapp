"""Consolidar casos duplicados creados por el monitor Gmail (v5.4.3).

Motivo: el bug RAD_GENERIC zfill generaba casos duplicados con mismo rad23
pero distinto folder (ej. 407 `2026-10021` vs 619 `2026-1002`). Este script
consolida los duplicados vivos por (a) rad23 canónico compartido y (b) FOREST
compartido, respetando el guard F7 (si juzgados difieren en rad23, NO
consolidar — caer en suspicious_duplicates.log para revisión manual).

Política de merge:
    Canónico = caso con ID menor (más antiguo) y/o con más campos poblados.
    Perdedor = se marca processing_status='DUPLICATE_MERGED'.
    Documents y Emails del perdedor se reasignan al canónico.
    AuditLog preservado (solo crece, FK del canónico).

Uso:
    python3 scripts/consolidate_monitor_duplicates.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Añadir backend al PYTHONPATH
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend.database.database import SessionLocal
from backend.database.models import AuditLog, Case, Document, Email
from backend.email.rad_utils import juzgado_code, normalize_rad23, same_juzgado
from backend.services.backup_service import auto_backup

logger = logging.getLogger("consolidate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SUSPICIOUS_LOG = _ROOT / "logs" / "suspicious_duplicates.log"


def _score_case_richness(c: Case) -> int:
    """Puntúa qué tan poblado está un caso (más campos → mejor canónico)."""
    score = 0
    for field in (
        "radicado_23_digitos", "radicado_forest", "accionante", "juzgado",
        "ciudad", "fecha_ingreso", "asunto", "pretensiones",
        "sentido_fallo_1st", "fecha_fallo_1st", "observaciones",
    ):
        if getattr(c, field, None):
            score += 1
    return score


def _choose_canonical(cases: list[Case]) -> tuple[Case, list[Case]]:
    """Elige el canónico: primero por richness, desempate por ID menor."""
    ranked = sorted(cases, key=lambda c: (-_score_case_richness(c), c.id))
    return ranked[0], ranked[1:]


def _reassign_children(db, canonical_id: int, loser_id: int) -> dict:
    """Reasigna documents, emails y audit_log del perdedor al canónico."""
    stats = {"documents": 0, "emails": 0, "audit_log": 0}

    stats["documents"] = db.query(Document).filter(Document.case_id == loser_id).update(
        {"case_id": canonical_id}, synchronize_session=False
    )
    stats["emails"] = db.query(Email).filter(Email.case_id == loser_id).update(
        {"case_id": canonical_id}, synchronize_session=False
    )
    stats["audit_log"] = db.query(AuditLog).filter(AuditLog.case_id == loser_id).update(
        {"case_id": canonical_id}, synchronize_session=False
    )
    return stats


def _log_suspicious(reason: str, case_ids: list[int], rad23: str = "", forest: str = ""):
    """Registra duplicado sospechoso que NO se consolida automáticamente."""
    SUSPICIOUS_LOG.parent.mkdir(exist_ok=True)
    with SUSPICIOUS_LOG.open("a") as f:
        f.write(
            f"{datetime.utcnow().isoformat()} | {reason} | cases={case_ids} "
            f"rad23={rad23} forest={forest}\n"
        )


def consolidate_by_rad23(db, dry_run: bool = False) -> dict:
    """Merge casos con mismo radicado_23_digitos canónico (solo si juzgado coincide)."""
    counters = {"groups": 0, "merged": 0, "suspicious": 0, "guard_f7": 0}

    # Agrupar por rad23 normalizado (solo dígitos, primeros 20 para tolerancia)
    cases = db.query(Case).filter(
        Case.radicado_23_digitos.isnot(None),
        Case.radicado_23_digitos != "",
        Case.processing_status != "DUPLICATE_MERGED",
    ).all()

    groups: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        norm = normalize_rad23(c.radicado_23_digitos)
        if len(norm) >= 18:
            # Usar primeros 20 (depto+entidad+esp+subesp+año+seq), tolerar variación en recurso 2d
            groups[norm[:20]].append(c)

    for key, group in groups.items():
        if len(group) < 2:
            continue

        # Guard F7: todos los rad23 del grupo deben compartir juzgado_code
        juz = juzgado_code(group[0].radicado_23_digitos)
        if not all(same_juzgado(group[0].radicado_23_digitos, c.radicado_23_digitos) for c in group[1:]):
            _log_suspicious(
                "F7_JUZGADO_MISMATCH",
                [c.id for c in group],
                rad23=key,
            )
            counters["guard_f7"] += 1
            continue

        counters["groups"] += 1
        canonical, losers = _choose_canonical(group)
        logger.info(
            "[rad23] Grupo %s: canonical=%d losers=%s",
            key, canonical.id, [c.id for c in losers],
        )

        for loser in losers:
            if dry_run:
                logger.info("  DRY-RUN would merge %d → %d", loser.id, canonical.id)
                continue
            stats = _reassign_children(db, canonical.id, loser.id)
            loser.processing_status = "DUPLICATE_MERGED"
            loser.observaciones = (
                (loser.observaciones or "") + f"\n[MERGED→{canonical.id} v5.4.3]"
            ).strip()
            db.add(AuditLog(
                case_id=canonical.id,
                action="MERGE_DUPLICATE",
                source="consolidate_monitor_duplicates.py",
                new_value=f"Merged from case {loser.id}: docs={stats['documents']} emails={stats['emails']} audit={stats['audit_log']}",
            ))
            counters["merged"] += 1

    return counters


def consolidate_by_forest(db, dry_run: bool = False) -> dict:
    """Merge casos con mismo radicado_forest (solo si coincide con rad23 también)."""
    counters = {"groups": 0, "merged": 0, "suspicious": 0}

    cases = db.query(Case).filter(
        Case.radicado_forest.isnot(None),
        Case.radicado_forest != "",
        Case.processing_status != "DUPLICATE_MERGED",
    ).all()

    groups: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        groups[c.radicado_forest].append(c)

    for forest, group in groups.items():
        if len(group) < 2:
            continue

        # Si los rad23 del grupo difieren en juzgado → sospechoso, no mergear
        rad23s = [c.radicado_23_digitos for c in group if c.radicado_23_digitos]
        if len(rad23s) >= 2:
            if not all(same_juzgado(rad23s[0], r) for r in rad23s[1:]):
                _log_suspicious(
                    "FOREST_SHARED_DIFF_JUZGADO",
                    [c.id for c in group],
                    forest=forest,
                )
                counters["suspicious"] += 1
                continue

        counters["groups"] += 1
        canonical, losers = _choose_canonical(group)
        logger.info(
            "[forest] Grupo %s: canonical=%d losers=%s",
            forest, canonical.id, [c.id for c in losers],
        )

        for loser in losers:
            if dry_run:
                logger.info("  DRY-RUN would merge %d → %d", loser.id, canonical.id)
                continue
            stats = _reassign_children(db, canonical.id, loser.id)
            loser.processing_status = "DUPLICATE_MERGED"
            loser.observaciones = (
                (loser.observaciones or "") + f"\n[MERGED→{canonical.id} v5.4.3 via FOREST]"
            ).strip()
            db.add(AuditLog(
                case_id=canonical.id,
                action="MERGE_DUPLICATE_FOREST",
                source="consolidate_monitor_duplicates.py",
                new_value=f"Merged from case {loser.id} (FOREST={forest}): docs={stats['documents']} emails={stats['emails']}",
            ))
            counters["merged"] += 1

    return counters


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No escribe cambios")
    args = parser.parse_args()

    if not args.dry_run:
        logger.info("Backup pre-consolidación...")
        auto_backup("pre-consolidate-v543")

    db = SessionLocal()
    try:
        logger.info("=" * 60)
        logger.info("PASO 1: consolidar por rad23 canónico")
        logger.info("=" * 60)
        c1 = consolidate_by_rad23(db, dry_run=args.dry_run)

        logger.info("=" * 60)
        logger.info("PASO 2: consolidar por FOREST compartido")
        logger.info("=" * 60)
        c2 = consolidate_by_forest(db, dry_run=args.dry_run)

        if not args.dry_run:
            db.commit()
            logger.info("Commits aplicados.")
        else:
            logger.info("DRY-RUN — no se aplican cambios.")

        logger.info("")
        logger.info("RESUMEN:")
        logger.info("  rad23   groups=%d merged=%d guard_f7_rechazos=%d",
                    c1["groups"], c1["merged"], c1["guard_f7"])
        logger.info("  forest  groups=%d merged=%d suspicious=%d",
                    c2["groups"], c2["merged"], c2["suspicious"])
        logger.info("  Sospechosos en %s", SUSPICIOUS_LOG)

    finally:
        db.close()


if __name__ == "__main__":
    main()
