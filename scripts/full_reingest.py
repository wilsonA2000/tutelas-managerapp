"""Re-ingesta completa de Gmail desde cero con paginación batch.

Uso:
  python3 scripts/full_reingest.py [--batch-size N] [--query Q]

Pensado para correr en background del pod tras un wipe de DB:
  nohup python3 scripts/full_reingest.py > /workspace/full_reingest.log 2>&1 &

Termina cuando Gmail deja de devolver next_cursor.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal
from backend.email.sync_batch import check_inbox_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("full_reingest")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--query", type=str, default="in:inbox")
    parser.add_argument("--max-batches", type=int, default=200,
                        help="Cap defensivo: máximo de batches a procesar")
    parser.add_argument("--read-only", action="store_true", default=True)
    args = parser.parse_args()

    cursor = None
    batch_n = 0
    total_imported = 0
    total_matched = 0
    total_ambiguo = 0
    total_pendiente = 0
    t0 = time.time()

    while batch_n < args.max_batches:
        batch_n += 1
        batch_start = time.time()
        db = SessionLocal()
        try:
            res = check_inbox_batch(
                db=db,
                batch_size=args.batch_size,
                resume_cursor=cursor,
                query=args.query,
                read_only=args.read_only,
            )
        except Exception as e:
            logger.exception("Batch %d falló: %s", batch_n, e)
            db.close()
            break
        finally:
            db.close()

        if not isinstance(res, dict):
            logger.error("Respuesta no-dict: %r", res)
            break
        if "error" in res:
            logger.error("Batch %d error: %s", batch_n, res["error"])
            break

        batch = res.get("batch", {})
        batch_new = batch.get("NEW_CASE", 0)
        batch_match = batch.get("AUTO_MATCH", 0)
        batch_quar = batch.get("QUARANTINE", 0)
        batch_dup = batch.get("DUPLICATE_GMAIL", 0)
        batch_ign = batch.get("IGNORED", 0)
        batch_err = batch.get("ERROR", 0)
        emails_in_batch = batch.get("emails_in_batch", 0)
        total_imported += (batch_new + batch_match + batch_quar)
        total_matched += batch_match
        total_ambiguo += batch_quar
        total_pendiente += batch_new
        batch_dur = time.time() - batch_start
        elapsed = time.time() - t0
        next_cursor = res.get("cursor_token")
        has_more = res.get("has_more", False)
        logger.info(
            "batch=%d in=%d new=%d match=%d quar=%d dup=%d ign=%d err=%d cum_new=%d dur=%.1fs cum_elapsed=%.1fs has_more=%s",
            batch_n, emails_in_batch, batch_new, batch_match, batch_quar,
            batch_dup, batch_ign, batch_err, total_pendiente,
            batch_dur, elapsed, has_more,
        )

        if not has_more or not next_cursor:
            logger.info("FIN: Gmail agotado (has_more=%s)", has_more)
            break
        cursor = next_cursor
        time.sleep(1)

    summary = {
        "batches": batch_n,
        "total_imported": total_imported,
        "total_matched": total_matched,
        "total_ambiguo": total_ambiguo,
        "total_pendiente": total_pendiente,
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
