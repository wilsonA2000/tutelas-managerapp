#!/usr/bin/env python3
"""
Barrido DeepSeek general (dry_run=True).

Lee la DB de producción, corre el pipeline v9 con DeepSeek en modo
dry_run=True (sin escribir) y guarda los valores propuestos en
data/experiment/results/<case_id>.json.

El sweep es reanudable: los casos ya procesados se saltan (checkpoint).

Uso:
    # Piloto con 5 casos
    python3 scripts/deepseek_sweep/run_sweep.py --limit 5

    # Barrido completo (todos los casos activos)
    python3 scripts/deepseek_sweep/run_sweep.py

    # Reanudar tras interrupción
    python3 scripts/deepseek_sweep/run_sweep.py --resume

    # Forzar re-procesar un caso específico
    python3 scripts/deepseek_sweep/run_sweep.py --case-ids 42 117 305

Env vars requeridas (leídas de data/experiment/.env.deepseek_sweep):
    V9_ALLOW_DEEPSEEK=true
    V9_LLM_API_KEY=<key>
    LLM_LOCAL_URL=https://api.deepseek.com
    LLM_LOCAL_MODEL_ID=deepseek-v4-flash
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── cargar .env.deepseek_sweep ANTES de importar backend ──────────────────
ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = ROOT / "data" / "experiment" / ".env.deepseek_sweep"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
else:
    print(f"ADVERTENCIA: {_ENV_FILE} no encontrado; usando vars de entorno actuales.")

# ── imports backend (DESPUÉS del setenv para que lean las vars nuevas) ─────
sys.path.insert(0, str(ROOT))

import sqlalchemy  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.database.models import Case  # noqa: E402
from backend.v9.pipeline import extract_case  # noqa: E402
from backend.v9.types import EXCEL_FIELDS  # noqa: E402

# ── constantes ────────────────────────────────────────────────────────────
PROD_DB = ROOT / "data" / "tutelas.db"
RESULTS_DIR = ROOT / "data" / "experiment" / "results"
CHECKPOINT_FILE = RESULTS_DIR / "checkpoint.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(RESULTS_DIR / "sweep.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("sweep")


# ── helpers ───────────────────────────────────────────────────────────────

def _load_checkpoint() -> set[int]:
    if CHECKPOINT_FILE.exists():
        return set(json.loads(CHECKPOINT_FILE.read_text()).get("done", []))
    return set()


def _save_checkpoint(done: set[int]) -> None:
    CHECKPOINT_FILE.write_text(json.dumps({"done": sorted(done)}, indent=2))


def _current_from_case(case: Case) -> dict[str, str]:
    """Lee los 43 campos EXCEL_FIELDS del objeto Case."""
    out = {}
    for f in EXCEL_FIELDS:
        val = getattr(case, f, None)
        out[f] = str(val).strip() if val else ""
    return out


def _manual_fields(case: Case) -> set[str]:
    """Campos marcados como 'manual' en field_confidences_json."""
    raw = case.field_confidences_json or ""
    try:
        data = json.loads(raw)
        sources = data.get("v9_sources", {})
        return {k for k, v in sources.items() if v == "manual"}
    except (json.JSONDecodeError, TypeError):
        return set()


def _semaforo(val_cur: str, val_prop: str, is_manual: bool) -> str:
    if is_manual:
        return "ROJO"       # protegido — nunca pisar
    if not val_cur and not val_prop:
        return "GRIS"       # ambos vacíos
    if val_cur == val_prop:
        return "GRIS"       # sin cambio
    if not val_cur and val_prop:
        return "VERDE"      # fill vacío — candidato seguro
    if val_cur and not val_prop:
        return "GRIS"       # pipeline no encontró nada, mantener actual
    return "AMARILLO"       # conflicto — revisar


def process_case(engine, case_id: int) -> dict:
    """Procesa un caso: carga current, corre pipeline dry_run, guarda JSON."""
    result_file = RESULTS_DIR / f"{case_id}.json"
    if result_file.exists():
        return {"case_id": case_id, "status": "cached"}

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()
    try:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            return {"case_id": case_id, "status": "not_found"}

        current = _current_from_case(case)
        manual_set = _manual_fields(case)

        t0 = time.perf_counter()
        result = extract_case(
            db,
            case_id,
            dry_run=True,
            use_llm=True,
            _resolve_acum=False,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        proposed = result.fields.values
        sources = result.fields.sources_json()

        diff = []
        for campo in EXCEL_FIELDS:
            val_cur = current.get(campo, "")
            val_prop = proposed.get(campo, "")
            is_manual = campo in manual_set
            sem = _semaforo(val_cur, val_prop, is_manual)
            if sem != "GRIS":
                diff.append({
                    "campo": campo,
                    "semaforo": sem,
                    "current": val_cur,
                    "proposed": val_prop,
                    "source": sources.get(campo, ""),
                    "manual_protected": is_manual,
                })

        output = {
            "case_id": case_id,
            "folder_name": result.folder_name,
            "llm_calls": result.llm_calls,
            "elapsed_ms": elapsed_ms,
            "warnings": result.warnings[:10],  # truncar para no inflar JSON
            "current": current,
            "proposed": proposed,
            "sources": sources,
            "diff": diff,
            "diff_verde": sum(1 for d in diff if d["semaforo"] == "VERDE"),
            "diff_amarillo": sum(1 for d in diff if d["semaforo"] == "AMARILLO"),
            "diff_rojo": sum(1 for d in diff if d["semaforo"] == "ROJO"),
        }
        result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        return {
            "case_id": case_id,
            "status": "ok",
            "llm_calls": result.llm_calls,
            "elapsed_ms": elapsed_ms,
            "verde": output["diff_verde"],
            "amarillo": output["diff_amarillo"],
        }
    except Exception as exc:
        log.exception("Case %d falló: %s", case_id, exc)
        err_file = RESULTS_DIR / f"{case_id}_ERROR.json"
        err_file.write_text(json.dumps({"case_id": case_id, "error": str(exc)}, ensure_ascii=False, indent=2))
        return {"case_id": case_id, "status": "error", "error": str(exc)[:200]}
    finally:
        db.close()


# ── main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Barrido DeepSeek general (dry_run=True)")
    parser.add_argument("--limit", type=int, default=0, help="Procesar solo N casos (0 = todos)")
    parser.add_argument("--workers", type=int, default=4, help="Threads paralelos (default 4)")
    parser.add_argument("--resume", action="store_true", help="Saltar casos ya procesados")
    parser.add_argument("--case-ids", nargs="+", type=int, help="Procesar solo estos case_ids")
    args = parser.parse_args()

    # Verificar que DeepSeek está habilitado
    if os.getenv("V9_ALLOW_DEEPSEEK", "").lower() != "true":
        print("ERROR: V9_ALLOW_DEEPSEEK != true. El sweep requiere DeepSeek habilitado.")
        sys.exit(1)
    if not os.getenv("V9_LLM_API_KEY", ""):
        print("ERROR: V9_LLM_API_KEY no seteada.")
        sys.exit(1)
    llm_url = os.getenv("LLM_LOCAL_URL", "http://127.0.0.1:8765")
    if "127.0.0.1" in llm_url or "localhost" in llm_url:
        print(f"ADVERTENCIA: LLM_LOCAL_URL={llm_url} parece local, no DeepSeek cloud.")
        print("  Asegúrate de tener LLM_LOCAL_URL=https://api.deepseek.com")

    log.info("Barrido DeepSeek — prod DB: %s", PROD_DB)
    log.info("URL LLM: %s  modelo: %s", os.getenv("LLM_LOCAL_URL"), os.getenv("LLM_LOCAL_MODEL_ID"))

    engine = sqlalchemy.create_engine(
        f"sqlite:///{PROD_DB}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    # Obtener lista de case_ids
    if args.case_ids:
        case_ids = args.case_ids
    else:
        with engine.connect() as conn:
            rows = conn.execute(
                sqlalchemy.text("SELECT id FROM cases WHERE estado != 'DUPLICATE_MERGED' ORDER BY id")
            ).fetchall()
        case_ids = [r[0] for r in rows]

    done_set = _load_checkpoint() if args.resume else set()
    # El checkpoint también carga los ya guardados como JSON (reanudación automática)
    for p in RESULTS_DIR.glob("*.json"):
        if p.name == "checkpoint.json":
            continue
        try:
            cid = int(p.stem)
            done_set.add(cid)
        except ValueError:
            pass

    pending = [cid for cid in case_ids if cid not in done_set]
    if args.limit:
        pending = pending[: args.limit]

    total = len(pending)
    log.info("Cases a procesar: %d  (saltados por checkpoint: %d)", total, len(done_set))

    if total == 0:
        log.info("Nada que procesar. Usa --limit o borra data/experiment/results/ para re-correr.")
        return

    stats = {"ok": 0, "error": 0, "cached": 0, "verde": 0, "amarillo": 0, "llm_calls": 0}
    t_global = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_case, engine, cid): cid for cid in pending}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            cid = r["case_id"]
            done_set.add(cid)

            if r["status"] == "ok":
                stats["ok"] += 1
                stats["verde"] += r.get("verde", 0)
                stats["amarillo"] += r.get("amarillo", 0)
                stats["llm_calls"] += r.get("llm_calls", 0)
                log.info(
                    "[%d/%d] case %d OK — %dms, llm=%d, verde=%d, amarillo=%d",
                    i, total, cid, r.get("elapsed_ms", 0),
                    r.get("llm_calls", 0), r.get("verde", 0), r.get("amarillo", 0),
                )
            elif r["status"] == "cached":
                stats["cached"] += 1
            else:
                stats["error"] += 1
                log.warning("[%d/%d] case %d ERROR: %s", i, total, cid, r.get("error", ""))

            # Checkpoint cada 10 casos
            if i % 10 == 0:
                _save_checkpoint(done_set)

    _save_checkpoint(done_set)
    elapsed = time.perf_counter() - t_global

    log.info("═══ RESUMEN ═══")
    log.info("  OK: %d  Errores: %d  Cached: %d", stats["ok"], stats["error"], stats["cached"])
    log.info("  Diffs VERDE: %d  AMARILLO: %d", stats["verde"], stats["amarillo"])
    log.info("  LLM calls totales: %d", stats["llm_calls"])
    log.info("  Tiempo total: %.1fs (%.1fs/caso)", elapsed, elapsed / max(total, 1))
    log.info("Resultados en: %s", RESULTS_DIR)
    log.info("Siguiente paso: python3 scripts/deepseek_sweep/build_diff_report.py")


if __name__ == "__main__":
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    main()
