#!/usr/bin/env python3
"""Saneamiento de calidad de `pretensiones` (formato/literalidad).

Re-extrae los casos cuyo `pretensiones` almacenado NO tiene formato de petitorio
(truncado a media frase, narrativa de hechos/defensa, meta-comentario del LLM, o
resumen nominal). Solo toca esos; NO re-extrae los que ya están OK.

Fase 1 (regex, sin LLM, sin GPU): re-extrae con el código arreglado.
Fase 2 (--llm): para los que queden vacíos, LLM 1-a-1 en CPU (cero riesgo de GPU hang).

Uso:
    python3 scripts/backfill_pretensiones_quality.py             # dry-run (no escribe)
    python3 scripts/backfill_pretensiones_quality.py --apply     # fase 1 regex (backup antes)
    python3 scripts/backfill_pretensiones_quality.py --apply --llm  # + fase 2 LLM-CPU en huecos
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal       # noqa: E402
from backend.database.models import Case                 # noqa: E402
from backend.v9.field_extractor import extract_pretensiones_for_case  # noqa: E402

APPLY = "--apply" in sys.argv
WITH_LLM = "--llm" in sys.argv

# --- Detector de pretensión MAL FORMADA (mismo criterio que la auditoría) ---
_RE_GOOD = re.compile(
    r"(?i)(solicit|rueg|pido|peticion|impetr|deprec|tutel|ampar|orden|proteg|garantic|"
    r"reconozc|reintegr|nombr|declar|provee?r|asignaci|mantener|entregar|informar|"
    r"certificaci|cupo|reanud|continu|que\s+se\b|PRIMER[OA]\b|^\s*[i1][\.\)])"
)
_RE_META = re.compile(r"(?i)(extra[íi]do del resumen|no verbatim|no consta|no se especific|se infiere)")
_RE_DEFRECAP = re.compile(
    r"(?i)^(el accionante,? .{0,30}(alega|adujo|aduce|manifiesta|pretende\b)|la accionante pretende|"
    r"los? accionantes?,? actuando|la secretaría .{0,25}considera|argumentos fácticos|"
    r"frente a los hechos|en apoyo de sus pretensiones|b\) legitimaci|del ciudadano|"
    r"el grupo de talento|dado que esta situaci)"
)


# Apertura clara de petitorio (verbo dispositivo o encabezado de pretensión). Solo
# aceptamos en fase 1 los valores re-extraídos que arrancan así; lo demás (lead-in,
# fragmento, paréntesis vacíos) → hueco → LLM verbatim, más confiable.
_RE_PETITION_OPENER = re.compile(
    r"(?i)^[\s\W]*(?:ordene|tutele|ampare|disponga|proteja|garantice|reconozca|reintegre|"
    r"nombre|declare|conceda|orden\w*|tutel\w*|ampar\w*|proteg\w*|solicit\w*|rueg\w*|pido|"
    r"peticion\w*|impetr\w*|deprec\w*|que\s+se\b|primer[oa]\b|segund[oa]\b|amparar|tutelar|ordenar)"
)


def is_good(v: str) -> bool:
    """Acepta el valor re-extraído solo si arranca como petitorio CLARO (verbo/encabezado)
    y no es meta/hechos. NO usa is_bad (que marca minúsculas — un recap válido arranca con
    el verbo en minúscula 'ordene…')."""
    v = (v or "").strip()
    if len(v) < 25:
        return False
    if _RE_META.search(v[:80]) or _RE_DEFRECAP.search(v):
        return False
    return bool(_RE_PETITION_OPENER.match(v))


def is_bad(p: str) -> bool:
    p = (p or "").strip()
    if not p or p == "SIN_DETERMINAR":
        return False
    if len(p) < 25:
        return True
    if _RE_META.search(p[:80]) or _RE_DEFRECAP.search(p):
        return True
    # SELECCIÓN estricta: arranca en minúscula = sospechoso de truncamiento (lo re-extraemos;
    # el recap arreglado producirá la versión con verbo 'ordene…' si aplica).
    if re.match(r"^[\s\W]*[a-záéíóúñ]", p):
        return True
    if not _RE_GOOD.search(p[:90]):                  # sin señal de petitorio al inicio
        return True
    return False


# --- Fase 2: server LLM en CPU (cero riesgo GPU para lote desatendido) ---
def _spawn_llm_cpu() -> int:
    import subprocess
    from backend.services.llm_mutex import LLAMA_BIN, GGUF_BASE, LLM_PORT
    if not LLAMA_BIN.exists():
        raise RuntimeError(f"binario CPU no encontrado: {LLAMA_BIN}")
    log = ROOT / "logs" / f"llama_cpu_pret_{int(time.time())}.log"
    log.parent.mkdir(exist_ok=True)
    cmd = [str(LLAMA_BIN), "-m", str(GGUF_BASE), "--port", str(LLM_PORT),
           "--ctx-size", "4096", "--parallel", "1", "--host", "127.0.0.1",
           "-t", "8", "-tb", "12", "--mlock"]
    proc = subprocess.Popen(cmd, stdout=open(log, "wb"), stderr=subprocess.STDOUT, start_new_session=True)
    return proc.pid


def _llm_ready(timeout=60) -> bool:
    import urllib.request
    url = f"http://127.0.0.1:{os.getenv('LLM_LOCAL_PORT','8765')}/health"
    for _ in range(timeout // 2):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(2)
    return False


def _set_pret(c, val, db):
    c.pretensiones = val
    try:
        fc = json.loads(c.field_confidences_json or "{}")
        vs = fc.setdefault("v9_sources", {})
        if val:
            vs["pretensiones"] = "regex"
        else:
            vs.pop("pretensiones", None)
        c.field_confidences_json = json.dumps(fc)
    except Exception:
        pass


def main() -> None:
    db = SessionLocal()
    suspects = [c for c in db.query(Case).filter(Case.pretensiones.isnot(None)).all()
                if is_bad(c.pretensiones)]
    print(f"Pretensiones mal formadas: {len(suspects)} -> {sorted(c.id for c in suspects)}")

    # ── FASE 1: regex (código arreglado) ──
    fixed, gaps = 0, []
    for c in suspects:
        # Aceptar solo si arranca como petitorio claro (is_good); capturas imperfectas
        # (lead-in/fragmento/paréntesis vacíos) → hueco → LLM verbatim.
        v, _src = extract_pretensiones_for_case(db, c, use_llm=False)
        if v and is_good(v):
            if APPLY:
                _set_pret(c, v, db)
            fixed += 1
        else:
            gaps.append(c)
            if APPLY:
                _set_pret(c, None, db)   # limpiar el valor malo
    if APPLY:
        db.commit()
    print(f"FASE 1 (regex): fijó {fixed} · huecos {len(gaps)} -> {sorted(c.id for c in gaps)}")

    # ── FASE 2: LLM-CPU 1-a-1 en los huecos ──
    if WITH_LLM and APPLY and gaps:
        os.environ["V9_DISABLE_LLM"] = "false"
        print(f"FASE 2: lanzando llama-server CPU para {len(gaps)} huecos...")
        _spawn_llm_cpu()
        if not _llm_ready():
            print("  LLM no respondió — abortando fase 2 (huecos quedan vacíos)")
            return
        llm_fixed = 0
        for c in gaps:
            v, _src = extract_pretensiones_for_case(db, c, use_llm=True)
            if v and not is_bad(v):
                _set_pret(c, v, db); db.commit(); llm_fixed += 1
                print(f"  c{c.id}: LLM -> {v[:60]!r}")
            else:
                print(f"  c{c.id}: sin pretensión verbatim (queda vacío)")
        print(f"FASE 2 (LLM): fijó {llm_fixed}/{len(gaps)}")

    print("\n" + ("APLICADO ✓" if APPLY else "DRY-RUN (usa --apply; --llm para fase 2)"))


if __name__ == "__main__":
    main()
