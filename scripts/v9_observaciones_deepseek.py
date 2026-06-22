#!/usr/bin/env python3
"""Backfill del campo `observaciones` con un resumen narrativo del caso vía API DeepSeek.

A diferencia del pase local (`v9_observaciones_llm.py`), aquí le damos al modelo los
FRAGMENTOS DE LOS DOCUMENTOS (demanda, sentencias 1ª/2ª, auto/escrito de incidente,
respuesta más larga) como fuente principal — los campos ya extraídos van solo como guía,
porque el usuario quiere que el resumen se apoye en los documentos, no en la extracción.

`observaciones` se construye append-only en capas:
  - banderas (las pone el pase de campos: agente oficioso/personería, medida provisional,
    sujeto de especial protección)
  - una o varias líneas "[DD/MM/AAAA] <resumen>" — cada actuación nueva añade una línea
    nueva con su fecha SIN borrar las anteriores. Este script añade la PRIMERA línea a los
    casos que aún no tengan ninguna.

Requiere `DEEPSEEK_API_KEY` (en `.env` o variable de entorno). Es paralelo (ThreadPool).
Coste aprox.: ~$0.30-0.60 para los ~398 casos (deepseek-v4-flash ≈ $0.27/M in, $1.1/M out).

Uso:
    ./venv/bin/python3 scripts/v9_observaciones_deepseek.py --limit 4            # dry-run, 4 casos
    ./venv/bin/python3 scripts/v9_observaciones_deepseek.py --limit 4 --apply
    ./venv/bin/python3 scripts/v9_observaciones_deepseek.py --apply              # todos los que falten
    ./venv/bin/python3 scripts/v9_observaciones_deepseek.py --apply --workers 8
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, Document, Email  # noqa: E402
from backend.v9.field_extractor import _read_doc_text, case_has_dated_observacion  # noqa: E402
from backend.core.settings import settings  # noqa: E402

SHELL_FOLDER = "__SIN_RADICADO__"
_MODEL_DEFAULT = "deepseek-v4-flash"

# Qué documentos alimentar al modelo y cuánto texto de cada uno (chars).
_DOC_FEED = [
    ("escrito de tutela (demanda)", ("DEMANDA_TUTELA", "ANEXO_DEMANDA"), 4000),
    ("auto admisorio", ("AUTO_ADMISORIO",), 1800),
    ("sentencia de primera instancia", ("SENTENCIA_1RA",), 3500),
    ("impugnación", ("IMPUGNACION",), 1500),
    ("sentencia de segunda instancia", ("SENTENCIA_2DA",), 3000),
    ("escrito/auto de incidente de desacato", ("INCIDENTE_DESACATO", "AUTO_INCIDENTE"), 2500),
    ("respuesta de la entidad accionada", ("RESPUESTA",), 1800),
]

_SYSTEM = (
    "Eres un abogado de la Secretaría de Educación del Departamento de Santander que prepara "
    "el cuadro de control de tutelas. Resumes expedientes con rigor: solo lo que consta en los "
    "documentos, sin inventar ni opinar."
)

_RE_OBS_LINE = re.compile(r"^\s*\[\d{1,2}/\d{1,2}/\d{4}\]", re.M)


def _doc_head(db, case_id: int, doctypes: tuple, n: int) -> str:
    for dt in doctypes:
        best = None
        for d in db.query(Document).filter(Document.case_id == case_id, Document.doc_type == dt).all():
            t = _read_doc_text(d)
            if t and len(t) >= 200 and (best is None or len(t) > len(best)):
                best = t
        if best:
            return best[:n].strip()
    return ""


def _build_context(db, case: Case) -> tuple[str, bool]:
    """Devuelve (contexto, tiene_algun_doc)."""
    fields = []
    def _f(label, v):
        v = (str(v or "")).strip()
        if v:
            fields.append(f"- {label}: {v}")
    _f("Accionante (según extracción)", case.accionante)
    _f("Accionados (según extracción)", case.accionados)
    _f("Derechos invocados (según extracción)", (case.derecho_vulnerado or "").replace(" - ", ", "))
    _f("Asunto (según extracción)", case.asunto)
    _f("Sentido fallo 1ª instancia (según extracción)", case.sentido_fallo_1st)
    _f("Fecha fallo 1ª instancia (según extracción)", case.fecha_fallo_1st)
    _f("Impugnación (según extracción)", f"{case.impugnacion or ''} {('por '+case.quien_impugno) if case.quien_impugno else ''}".strip())
    _f("Sentido fallo 2ª instancia (según extracción)", case.sentido_fallo_2nd)
    _f("Incidente de desacato (según extracción)", case.incidente)
    _f("Decisión del incidente (según extracción)", case.decision_incidente)
    _f("Estado (según extracción)", case.estado)

    docs_blocks = []
    has_doc = False
    for label, doctypes, n in _DOC_FEED:
        txt = _doc_head(db, case.id, doctypes, n)
        if txt:
            has_doc = True
            docs_blocks.append(f"=== {label.upper()} (fragmento) ===\n{txt}")

    ctx = ""
    if fields:
        ctx += "CAMPOS YA EXTRAÍDOS (referencia — pueden tener errores; prioriza los documentos):\n" + "\n".join(fields) + "\n\n"
    if docs_blocks:
        ctx += "DOCUMENTOS DEL EXPEDIENTE:\n\n" + "\n\n".join(docs_blocks)
    return ctx[:28000], has_doc


def _summarize(client, model: str, ctx: str) -> str | None:
    prompt = (
        "Con base en lo siguiente, escribe un resumen factual del estado de esta acción de tutela, "
        "en español, de 2 a 4 frases (máximo ~80 palabras). Cubre: (1) qué solicita el accionante; "
        "(2) qué decidió cada instancia que conste (1ª instancia, impugnación, 2ª instancia, incidente "
        "de desacato) y, si aparece, la fecha; (3) en qué va el trámite. Prioriza lo que dicen los "
        "DOCUMENTOS sobre los campos extraídos. No inventes nada que no conste. No repitas el radicado. "
        "No uses viñetas ni encabezados. Si los documentos no dan información suficiente, escribe solo "
        "lo que sí consta (puede ser una sola frase). Responde ÚNICAMENTE el resumen.\n\n" + ctx
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=320, timeout=90,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        return f"__ERR__{type(e).__name__}: {str(e)[:160]}"
    raw = re.sub(r"\s+", " ", raw).strip().strip('"').strip()
    if not raw or len(raw) < 20:
        return None
    if len(raw) > 900:
        cut = raw[:900]
        last = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        raw = (cut[:last + 1] if last > 200 else cut).strip()
    return raw


def _fecha_ultima_actuacion(db, case_id: int) -> str:
    e = (db.query(Email).filter(Email.case_id == case_id, Email.date_received.isnot(None))
         .order_by(Email.date_received.desc()).first())
    dt = e.date_received if e and e.date_received else datetime.now()
    return dt.strftime("%d/%m/%Y")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--model", default=_MODEL_DEFAULT)
    ap.add_argument("--only-vacios", action="store_true",
                    help="solo casos con observaciones totalmente vacía")
    args = ap.parse_args()

    api_key = settings.DEEPSEEK_API_KEY or ""
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY no está configurada (en .env o variable de entorno).", file=sys.stderr)
        return 2
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    db = SessionLocal()
    try:
        cases = db.query(Case).filter(
            Case.folder_name.isnot(None), Case.folder_name != "", Case.folder_name != "None",
            Case.folder_name != SHELL_FOLDER, Case.processing_status != "DUPLICATE_MERGED",
        ).order_by(Case.id).all()
        pend = [c for c in cases if not case_has_dated_observacion(c)]
        if args.only_vacios:
            pend = [c for c in pend if not (c.observaciones or "").strip()]
        if args.limit:
            pend = pend[: args.limit]

        # Pre-construir contextos en el hilo principal (acceso a la DB no es thread-safe).
        jobs = []
        for c in pend:
            ctx, has_doc = _build_context(db, c)
            if not has_doc and len((ctx or "").strip()) < 60:
                continue  # nada con qué resumir
            jobs.append((c.id, c.folder_name, ctx, (c.observaciones or "").rstrip(), _fecha_ultima_actuacion(db, c.id)))

        print(f"Casos sin resumen fechado: {len(pend)} (de {len(cases)} en el cuadro); con material para resumir: {len(jobs)}.")
        print(f"Modelo: {args.model} · workers: {args.workers} · modo: {'APPLY' if args.apply else 'DRY-RUN'}\n")

        lock = threading.Lock()
        results: dict[int, str] = {}

        def _work(job):
            cid, fn, ctx, base, fecha = job
            r = _summarize(client, args.model, ctx)
            return cid, fn, base, fecha, r

        n_ok = n_skip = n_err = 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(_work, j) for j in jobs]
            for i, fut in enumerate(as_completed(futs), 1):
                cid, fn, base, fecha, r = fut.result()
                if r and r.startswith("__ERR__"):
                    n_err += 1
                    print(f"  [{i}/{len(jobs)}] #{cid} '{(fn or '')[:38]}'  ⚠ {r[7:]}")
                    continue
                if not r:
                    n_skip += 1
                    print(f"  [{i}/{len(jobs)}] #{cid} '{(fn or '')[:38]}'  → (sin resumen)")
                    continue
                line = f"[{fecha}] {r}"
                results[cid] = f"{base}\n{line}" if base else line
                n_ok += 1
                print(f"  [{i}/{len(jobs)}] #{cid} '{(fn or '')[:38]}'\n       {line}")

        if args.apply and results:
            for cid, new_obs in results.items():
                c = db.get(Case, cid)
                if c and not case_has_dated_observacion(c):  # re-check por si corrió otra vez en paralelo
                    c.observaciones = new_obs
            db.commit()
        print(f"\n{'─'*64}")
        print(f"{n_ok} resúmenes {'escritos' if args.apply else 'generados (dry-run)'}; {n_skip} sin material; {n_err} errores de API.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
