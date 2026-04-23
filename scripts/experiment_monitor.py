#!/usr/bin/env python3
"""Monitor v5.5 experiment: observa extracción, registra eventos, auto-relanza huérfanos."""
import json
import re
import sqlite3
import time
import urllib.request
from datetime import datetime
from pathlib import Path

DB = "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026 A/tutelas-app/data/tutelas.db"
LOG_PATH = "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app/logs/backend_experiment_9.log"
BASE_LOGS = Path("/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app/logs")
EVENTS_JSONL = BASE_LOGS / "experiment_monitor.jsonl"
REPORT_MD = BASE_LOGS / "experiment_monitor.md"
BACKEND_URL = "http://localhost:8000"

POLL_INTERVAL = 30
STUCK_MINUTES = 20
MAX_ROUNDS = 5

NOISE = re.compile(r"presidio-analyzer.*Entity MISC|GET /api/extraction/progress|Refreshing credentials|FutureWarning|UserWarning")
PATTERNS = {
    "completed_case": re.compile(r"Extracción unificada completa: caso (\d+).*\| (\d+\.?\d*)s \| status=(\w+)"),
    "error": re.compile(r"\bERROR\b|Traceback|AssertionError|TimeoutError"),
    "f9": re.compile(r"F9:"),
    "body_trunc": re.compile(r"BODY truncado"),
    "docx_fail": re.compile(r"python-docx no pudo abrir"),
    "route": re.compile(r"Route \[\w+\] → (\w+)/"),
    "fallback": re.compile(r"fallback|failover", re.I),
    "oom": re.compile(r"MemoryError|Killed|OOM", re.I),
}


def log_event(evt: dict) -> None:
    evt["ts"] = datetime.now().isoformat(timespec="seconds")
    with open(EVENTS_JSONL, "a") as f:
        f.write(json.dumps(evt, ensure_ascii=False) + "\n")


def db_state() -> dict:
    conn = sqlite3.connect(DB, timeout=10)
    try:
        state = dict(conn.execute("SELECT processing_status, COUNT(*) FROM cases GROUP BY processing_status").fetchall())
        state["__total__"] = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        return state
    finally:
        conn.close()


def tail_new(pos: int) -> tuple[list[str], int]:
    try:
        size = Path(LOG_PATH).stat().st_size
    except FileNotFoundError:
        return [], pos
    if pos > size:
        pos = 0
    with open(LOG_PATH, "rb") as f:
        f.seek(pos)
        data = f.read()
        new_pos = f.tell()
    lines = data.decode("utf-8", errors="replace").splitlines()
    return [ln for ln in lines if ln.strip() and not NOISE.search(ln)], new_pos


def http_post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BACKEND_URL}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def http_get(path: str) -> dict:
    with urllib.request.urlopen(f"{BACKEND_URL}{path}", timeout=30) as r:
        return json.loads(r.read())


def reset_stuck(ids: list[int] | None = None) -> int:
    conn = sqlite3.connect(DB, timeout=30)
    try:
        c = conn.cursor()
        if ids:
            q = f"UPDATE cases SET processing_status='PENDIENTE' WHERE id IN ({','.join('?'*len(ids))})"
            c.execute(q, ids)
        else:
            c.execute("UPDATE cases SET processing_status='PENDIENTE' WHERE processing_status='EXTRAYENDO'")
        n = c.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def write_report(started_at: str, state: dict, summary: dict, last_errors: list[str], rounds: int, round_status: str) -> None:
    elapsed_min = (datetime.now() - datetime.fromisoformat(started_at)).total_seconds() / 60
    avg_s = (summary["total_seconds"] / summary["cases_completed"]) if summary["cases_completed"] else 0
    md = [
        f"# Experiment v5.5 Monitor\n\n",
        f"- **Arrancado:** {started_at}\n",
        f"- **Actualizado:** {datetime.now().isoformat(timespec='seconds')}\n",
        f"- **Elapsed:** {elapsed_min:.1f} min\n",
        f"- **Ronda:** {rounds}/{MAX_ROUNDS} — {round_status}\n\n",
        "## Estado DB\n\n",
    ]
    for k, v in sorted(state.items()):
        md.append(f"- `{k}`: {v}\n")
    md.extend([
        "\n## Métricas acumuladas\n\n",
        f"- Casos completados esta sesión: **{summary['cases_completed']}**\n",
        f"- Tiempo total extracción: {summary['total_seconds']:.0f}s\n",
        f"- Promedio por caso: {avg_s:.1f}s\n",
        f"- Errores: {summary['errors']}\n",
        f"- Warnings F9 (rad23 duplicado): {summary['f9']}\n",
        f"- BODY truncados: {summary['body_trunc']}\n",
        f"- DOCX no legibles: {summary['docx_fail']}\n",
        f"- Fallbacks IA usados: {summary['fallbacks']}\n",
        f"- OOM/Killed: {summary['oom']}\n",
        f"- Routes: {summary['routes']}\n",
    ])
    if last_errors:
        md.append("\n## Últimos errores/warnings (max 20)\n\n```\n")
        md.extend(e + "\n" for e in last_errors[-20:])
        md.append("```\n")
    REPORT_MD.write_text("".join(md))


def main() -> None:
    started_at = datetime.now().isoformat(timespec="seconds")
    log_event({"type": "monitor_start"})
    try:
        pos = Path(LOG_PATH).stat().st_size
    except FileNotFoundError:
        pos = 0

    summary = {
        "cases_completed": 0,
        "total_seconds": 0.0,
        "errors": 0,
        "f9": 0,
        "body_trunc": 0,
        "docx_fail": 0,
        "fallbacks": 0,
        "oom": 0,
        "routes": {},
    }
    last_errors: list[str] = []
    last_progress_at = time.time()
    last_completo = db_state().get("COMPLETO", 0)
    rounds = 1
    round_status = "procesando"

    while True:
        try:
            state = db_state()
        except Exception as e:
            log_event({"type": "db_error", "msg": str(e)})
            time.sleep(POLL_INTERVAL)
            continue

        try:
            lines, pos = tail_new(pos)
        except Exception as e:
            log_event({"type": "tail_error", "msg": str(e)})
            lines = []

        for ln in lines:
            for name, pat in PATTERNS.items():
                m = pat.search(ln)
                if not m:
                    continue
                if name == "completed_case":
                    summary["cases_completed"] += 1
                    summary["total_seconds"] += float(m.group(2))
                    log_event({"type": "case_completed", "case_id": int(m.group(1)),
                               "seconds": float(m.group(2)), "status": m.group(3)})
                elif name == "error":
                    summary["errors"] += 1
                    last_errors.append(ln[:400])
                    log_event({"type": "error", "line": ln[:600]})
                elif name == "f9":
                    summary["f9"] += 1
                    log_event({"type": "f9", "line": ln[:300]})
                elif name == "body_trunc":
                    summary["body_trunc"] += 1
                elif name == "docx_fail":
                    summary["docx_fail"] += 1
                    log_event({"type": "docx_fail", "line": ln[:300]})
                elif name == "fallback":
                    summary["fallbacks"] += 1
                    log_event({"type": "fallback", "line": ln[:300]})
                elif name == "oom":
                    summary["oom"] += 1
                    last_errors.append(ln[:400])
                    log_event({"type": "oom", "line": ln[:400]})
                elif name == "route":
                    prov = m.group(1)
                    summary["routes"][prov] = summary["routes"].get(prov, 0) + 1
                break

        pendiente = state.get("PENDIENTE", 0)
        extrayendo = state.get("EXTRAYENDO", 0)
        completo = state.get("COMPLETO", 0)

        if completo > last_completo:
            last_completo = completo
            last_progress_at = time.time()

        idle_min = (time.time() - last_progress_at) / 60

        # Fin de batch: nada PENDIENTE ni EXTRAYENDO
        if pendiente == 0 and extrayendo == 0:
            round_status = "batch terminado"
            log_event({"type": "batch_done", "round": rounds, "state": state})
            write_report(started_at, state, summary, last_errors, rounds, round_status)
            if rounds >= MAX_ROUNDS:
                log_event({"type": "max_rounds_reached"})
                break
            log_event({"type": "monitor_finished_clean"})
            break

        # Detección de stuck: sin avance > STUCK_MINUTES y hay EXTRAYENDO
        if idle_min >= STUCK_MINUTES and extrayendo > 0:
            round_status = f"stuck detectado en ronda {rounds}, reseteando"
            log_event({"type": "stuck", "idle_min": idle_min, "state": state, "round": rounds})
            if rounds >= MAX_ROUNDS:
                log_event({"type": "max_rounds_reached"})
                write_report(started_at, state, summary, last_errors, rounds, round_status)
                break
            n = reset_stuck()
            log_event({"type": "reset_stuck", "count": n})
            time.sleep(3)
            try:
                r = http_post("/api/extraction/batch", {})
                log_event({"type": "relaunch", "round": rounds + 1, "response": r})
                rounds += 1
                round_status = f"ronda {rounds} lanzada"
                last_progress_at = time.time()
            except Exception as e:
                log_event({"type": "relaunch_error", "msg": str(e)})

        # Caso: PENDIENTE > 0 pero EXTRAYENDO = 0 (huérfanos sin batch activo)
        elif pendiente > 0 and extrayendo == 0:
            round_status = f"PENDIENTE sin batch, relanzando ronda {rounds + 1}"
            log_event({"type": "relaunch_pending", "pendiente": pendiente, "round": rounds + 1})
            if rounds >= MAX_ROUNDS:
                log_event({"type": "max_rounds_reached"})
                write_report(started_at, state, summary, last_errors, rounds, round_status)
                break
            try:
                r = http_post("/api/extraction/batch", {})
                log_event({"type": "relaunch", "round": rounds + 1, "response": r})
                rounds += 1
                last_progress_at = time.time()
            except Exception as e:
                log_event({"type": "relaunch_error", "msg": str(e)})

        write_report(started_at, state, summary, last_errors, rounds, round_status)
        time.sleep(POLL_INTERVAL)

    # Reporte final
    try:
        state = db_state()
    except Exception:
        state = {}
    round_status = "FIN"
    write_report(started_at, state, summary, last_errors, rounds, round_status)
    log_event({"type": "monitor_end", "final_state": state, "summary": {k: v for k, v in summary.items() if k != "routes"}})


if __name__ == "__main__":
    main()
