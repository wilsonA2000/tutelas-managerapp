#!/usr/bin/env python3
"""Revisión + diligenciamiento del cuadro de tutelas con Claude (API Anthropic).

Por cada expediente, envía a Claude TODO el texto de sus documentos (priorizado y
acotado) + lo que la extracción v9 tiene hoy en cada campo, y pide de vuelta un JSON:
  - resumen: 2-4 frases factuales del estado de la tutela (para el campo `observaciones`).
  - lectura: lo que Claude lee de los documentos para cada campo clave (o null si no consta).
  - discrepancias: campos donde Claude cree que la extracción quedó mal, con gravedad y nota.

QUÉ APLICA (--apply), conservador:
  - `observaciones`: añade una línea "[DD/MM/AAAA] <resumen>" (append-only; no borra lo previo).
  - Rellena SOLO los campos vacíos de tipo texto-libre/fecha que Claude sí leyó:
    pretensiones, abogado_responsable, fecha_ingreso, fecha_respuesta, fecha_fallo_1st,
    fecha_fallo_2nd, sentido_fallo_1st, sentido_fallo_2nd, impugnacion, quien_impugno,
    incidente, decision_incidente.
  - NO toca accionante/accionados/juzgado/ciudad/derecho_vulnerado/oficina_responsable/
    categoria_tematica si ya tienen valor (son de vocabulario controlado / ya curados) —
    solo se reportan las discrepancias.
SIEMPRE genera `reports/revision_claude_<ts>.md` con el detalle (resumen, vacíos llenados,
discrepancias) para revisión humana antes del informe.

Requiere ANTHROPIC_API_KEY en el entorno:
    ANTHROPIC_API_KEY='sk-ant-...' ./venv/bin/python3 scripts/v9_revision_anthropic.py --limit 3
    ANTHROPIC_API_KEY='sk-ant-...' ./venv/bin/python3 scripts/v9_revision_anthropic.py --apply --workers 4
"""
from __future__ import annotations

import argparse
import json
import os
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

SHELL_FOLDER = "__SIN_RADICADO__"
_MODEL_DEFAULT = "claude-haiku-4-5-20251001"
# Tope de texto de documentos por caso. Dos límites mandan: (1) el rate limit de la cuenta
# (tier 1 = 50K input tokens/min) — paralelizar más NO ayuda, solo causa 429s; (2) el COSTE
# (presupuesto ~$4 en Anthropic). Con ~10K chars (~3.5K tokens) + respuestas cortas → ~$2.5-3.2
# para los ~398, ~40-50 min. 10K cabe la demanda (lo clave: accionados/asunto/pretensiones) +
# el inicio de la sentencia. Subir si hay más presupuesto/tier.
_MAX_CTX_CHARS = 10_000
_MAX_TOKENS_OUT = 1400     # tope de tokens de respuesta de Claude (controla el coste de salida)
_RETRY_MAX = 5             # reintentos ante rate-limit (429) / errores transitorios

# orden de prioridad de los documentos al armar el contexto (el más informativo primero)
_DOC_PRIORITY = [
    ("ESCRITO DE TUTELA (DEMANDA)", ("DEMANDA_TUTELA", "ANEXO_DEMANDA")),
    ("AUTO ADMISORIO", ("AUTO_ADMISORIO",)),
    ("SENTENCIA 1ª INSTANCIA", ("SENTENCIA_1RA",)),
    ("IMPUGNACIÓN", ("IMPUGNACION",)),
    ("SENTENCIA 2ª INSTANCIA", ("SENTENCIA_2DA",)),
    ("ESCRITO/AUTO DE INCIDENTE DE DESACATO", ("INCIDENTE_DESACATO", "AUTO_INCIDENTE")),
    ("RESPUESTA(S) DE LA ENTIDAD ACCIONADA", ("RESPUESTA",)),
    ("CORREO JUDICIAL", ("EMAIL_JUDICIAL", "EMAIL_INTERNO")),
    ("OTROS DOCUMENTOS", ("DESCONOCIDO", "NOTIFICACION", "NOTIFICACION_FALLO", "OFICIO_CUMPLIMIENTO")),
]

# campos del cuadro que SÍ rellenamos si están vacíos (texto libre / fechas)
_FILLABLE_IF_EMPTY = [
    "pretensiones", "abogado_responsable", "fecha_ingreso", "fecha_respuesta",
    "fecha_fallo_1st", "fecha_fallo_2nd", "sentido_fallo_1st", "sentido_fallo_2nd",
    "impugnacion", "quien_impugno", "incidente", "decision_incidente",
]
# campos que pedimos a Claude que "lea" de los documentos (para comparar / reportar)
_FIELDS_FOR_CLAUDE = [
    "accionante", "accionados", "juzgado", "ciudad", "derecho_vulnerado", "asunto",
    "pretensiones", "fecha_ingreso", "sentido_fallo_1st", "fecha_fallo_1st",
    "impugnacion", "quien_impugno", "sentido_fallo_2nd", "fecha_fallo_2nd",
    "incidente", "decision_incidente", "fecha_respuesta", "abogado_responsable", "estado",
]
_SYSTEM = (
    "Eres un abogado revisor de la Secretaría de Educación del Departamento de Santander. "
    "Auditas el cuadro de control de acciones de tutela: lees los documentos del expediente y "
    "(1) resumes su estado, (2) dices qué leerías tú en cada campo, (3) marcas dónde la "
    "extracción automática se equivocó. Rigor absoluto: solo lo que consta en los documentos, "
    "sin inventar. Responde SIEMPRE y SOLO con un objeto JSON válido, sin texto antes ni después."
)


def _norm(s) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip().lower()
    return re.sub(r"[^\w\sáéíóúñ]", "", s)


def _gather_docs(db, case_id: int) -> tuple[str, int]:
    """Concatena el texto de los documentos del caso por prioridad, hasta _MAX_CTX_CHARS."""
    used_ids: set[int] = set()
    blocks: list[str] = []
    total = 0
    n_docs = 0
    for label, doctypes in _DOC_PRIORITY:
        for dt in doctypes:
            for d in db.query(Document).filter(Document.case_id == case_id, Document.doc_type == dt).all():
                if d.id in used_ids:
                    continue
                used_ids.add(d.id)
                t = _read_doc_text(d)
                if not t or len(t.strip()) < 80:
                    continue
                if total >= _MAX_CTX_CHARS:
                    return "\n\n".join(blocks), n_docs
                room = _MAX_CTX_CHARS - total
                snippet = t.strip()[:room]
                blocks.append(f"════════ {label} — «{d.filename}» ════════\n{snippet}")
                total += len(snippet)
                n_docs += 1
    return "\n\n".join(blocks), n_docs


def _current_fields(c: Case) -> dict:
    return {f: (str(getattr(c, f, "") or "")).strip() for f in _FIELDS_FOR_CLAUDE}


def _prompt(case: Case, docs_text: str, cur: dict) -> str:
    cur_lines = "\n".join(f"  {k}: {v or '(vacío)'}" for k, v in cur.items())
    fields_json = ", ".join(f'"{f}"' for f in _FIELDS_FOR_CLAUDE)
    return (
        f"EXPEDIENTE: radicado {case.radicado_23_digitos or '(s/d)'} — carpeta «{case.folder_name}».\n\n"
        "Lo que la extracción AUTOMÁTICA tiene hoy (puede tener errores u omisiones):\n"
        f"{cur_lines}\n\n"
        "════════════════ DOCUMENTOS DEL EXPEDIENTE ════════════════\n"
        f"{docs_text}\n"
        "═══════════════════════════════════════════════════════════\n\n"
        "Devuélveme SOLO este JSON (sin ```):\n"
        "{\n"
        '  "resumen": "2 a 4 frases factuales del estado de la tutela: qué pide el accionante, qué decidió cada instancia que conste (1ª, impugnación, 2ª, incidente de desacato) y fechas si aparecen, y en qué va. Máx ~90 palabras. Sin viñetas. Sin repetir el radicado.",\n'
        f'  "lectura": {{ {fields_json} }}  // para cada uno, lo que TÚ lees de los documentos; null si no consta en ellos. Fechas en formato DD/MM/AAAA. derecho_vulnerado: lista de derechos separados por " - ". sentido_fallo: una palabra (CONCEDE/NIEGA/IMPROCEDENTE/CARENCIA DE OBJETO/etc). estado: "ACTIVO" si el trámite sigue, "INACTIVO" si ya hay fallo en firme o se archivó.\n'
        '  "discrepancias": [ {"campo": "...", "valor_actual": "...", "valor_documentos": "...", "gravedad": "alta|media|baja", "nota": "por qué crees que la extracción se equivocó"} ]  // solo campos donde la extracción difiere claramente de lo que dicen los documentos; [] si todo cuadra.\n'
        "}"
    )


def _parse_json_lenient(txt: str):
    """Parsea JSON tolerando ```fences```, prefacio/posfacio y truncamiento (cierra llaves/corchetes)."""
    txt = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", txt.strip())
    i = txt.find("{")
    if i < 0:
        return None
    txt = txt[i:]
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass
    # reparar truncamiento: recortar al último elemento completo y cerrar estructuras abiertas
    fixed = txt.rstrip().rstrip(",")
    # quitar una última pareja "clave": <valor incompleto>  o  ,<valor incompleto>
    last_comma = fixed.rfind(",")
    for cut in (len(fixed), last_comma):
        if cut <= 0:
            continue
        cand = fixed[:cut].rstrip().rstrip(",")
        opens_b = cand.count("[") - cand.count("]")
        opens_c = cand.count("{") - cand.count("}")
        if opens_b < 0 or opens_c < 0:
            continue
        cand2 = cand + "]" * opens_b + "}" * opens_c
        try:
            return json.loads(cand2)
        except json.JSONDecodeError:
            continue
    return None


def _ask_claude(client, model: str, system: str, user: str) -> dict | None:
    import time as _t
    import anthropic as _ant
    txt = ""
    truncated = False
    for attempt in range(_RETRY_MAX):
        try:
            resp = client.messages.create(
                model=model, max_tokens=3500, temperature=0,
                system=system, messages=[{"role": "user", "content": user}],
            )
            txt = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            truncated = getattr(resp, "stop_reason", "") == "max_tokens"
            break
        except (_ant.RateLimitError, _ant.APIStatusError, _ant.APIConnectionError, _ant.APITimeoutError) as e:
            status = getattr(e, "status_code", None)
            if attempt == _RETRY_MAX - 1:
                return {"__error__": f"{type(e).__name__}: {str(e)[:160]}"}
            # backoff: respeta retry-after si viene, si no, espera creciente (rate-limit ≈ ventana de 1 min)
            ra = 0
            try:
                ra = int((getattr(e, "response", None).headers or {}).get("retry-after", "0"))
            except Exception:
                pass
            wait = ra if ra > 0 else (60 if status == 429 else 5 * (attempt + 1))
            _t.sleep(min(wait, 70))
        except Exception as e:  # noqa: BLE001
            return {"__error__": f"{type(e).__name__}: {str(e)[:200]}"}
    data = _parse_json_lenient(txt)
    if isinstance(data, dict):
        if truncated and isinstance(data.get("discrepancias"), list):
            data["discrepancias"] = [d for d in data["discrepancias"] if isinstance(d, dict) and d.get("campo")]
        return data
    return {"__error__": "JSON no parseable" + (" (truncado)" if truncated else ""), "__raw__": txt[:400]}


def _fecha_ultima(db, case_id: int) -> str:
    e = (db.query(Email).filter(Email.case_id == case_id, Email.date_received.isnot(None))
         .order_by(Email.date_received.desc()).first())
    return (e.date_received if e and e.date_received else datetime.now()).strftime("%d/%m/%Y")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2,
                    help="hilos concurrentes (tier 1 = 50K tokens/min → 2-3 es lo razonable; más solo causa 429)")
    ap.add_argument("--model", default=_MODEL_DEFAULT)
    args = ap.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: define ANTHROPIC_API_KEY en el entorno.", file=sys.stderr)
        return 2
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    db = SessionLocal()
    try:
        cases = db.query(Case).filter(
            Case.folder_name.isnot(None), Case.folder_name != "", Case.folder_name != "None",
            Case.folder_name != SHELL_FOLDER, Case.processing_status != "DUPLICATE_MERGED",
        ).order_by(Case.id).all()
        if args.limit:
            cases = cases[: args.limit]

        # pre-armar contextos en el hilo principal (DB no es thread-safe)
        jobs = []
        for c in cases:
            docs_text, n_docs = _gather_docs(db, c.id)
            if n_docs == 0:
                continue
            jobs.append({
                "id": c.id, "folder": c.folder_name, "rad": c.radicado_23_digitos,
                "cur": _current_fields(c), "obs_base": (c.observaciones or "").rstrip(),
                "has_obs_line": case_has_dated_observacion(c),
                "fecha": _fecha_ultima(db, c.id),
                "prompt": _prompt(c, docs_text, _current_fields(c)), "n_docs": n_docs,
            })
        print(f"Casos en el cuadro: {len(cases)} · con documentos para revisar: {len(jobs)}")
        print(f"Modelo: {args.model} · workers: {args.workers} · modo: {'APPLY' if args.apply else 'DRY-RUN'}\n")

        lock = threading.Lock()
        out: dict[int, dict] = {}

        def _work(job):
            res = _ask_claude(client, args.model, _SYSTEM, job["prompt"])
            return job, res

        n_ok = n_err = 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(_work, j) for j in jobs]
            for i, fut in enumerate(as_completed(futs), 1):
                job, res = fut.result()
                cid = job["id"]
                if not res or "__error__" in res:
                    n_err += 1
                    print(f"  [{i}/{len(jobs)}] #{cid}  ⚠ {res.get('__error__') if res else 'sin respuesta'}")
                    continue
                n_ok += 1
                with lock:
                    out[cid] = {"job": job, "res": res}
                resumen = (res.get("resumen") or "").strip()
                discr = res.get("discrepancias") or []
                print(f"  [{i}/{len(jobs)}] #{cid} '{job['folder'][:38]}'  ({job['n_docs']} docs)  discrepancias: {len(discr)}")
                if resumen:
                    print(f"        resumen: {resumen[:160]}…")
                for d in discr[:4]:
                    print(f"        ✗ {d.get('campo')}: '{d.get('valor_actual')}' → '{d.get('valor_documentos')}' [{d.get('gravedad')}] {d.get('nota','')[:80]}")

        # ── aplicar (conservador) ──
        applied_obs = applied_fills = 0
        if args.apply:
            for cid, item in out.items():
                c = db.get(Case, cid)
                if not c:
                    continue
                job, res = item["job"], item["res"]
                # 1) observaciones (append-only, solo si aún no tiene línea fechada)
                resumen = re.sub(r"\s+", " ", (res.get("resumen") or "")).strip().strip('"')
                if resumen and len(resumen) >= 20 and not case_has_dated_observacion(c):
                    line = f"[{job['fecha']}] {resumen[:900]}"
                    c.observaciones = f"{job['obs_base']}\n{line}" if job["obs_base"] else line
                    applied_obs += 1
                # 2) rellenar vacíos de campos texto-libre/fecha
                lect = res.get("lectura") or {}
                for f in _FILLABLE_IF_EMPTY:
                    cur_v = (str(getattr(c, f, "") or "")).strip()
                    new_v = lect.get(f)
                    if cur_v or not new_v:
                        continue
                    new_v = re.sub(r"\s+", " ", str(new_v)).strip()
                    if not new_v or new_v.lower() in ("null", "none", "n/a", "no consta", "(vacío)"):
                        continue
                    if f.startswith("fecha_") and not re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", new_v):
                        continue
                    setattr(c, f, new_v[:2000])
                    applied_fills += 1
            db.commit()

        # ── reporte ──
        reports_dir = ROOT / "reports"
        reports_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rpt = reports_dir / f"revision_claude_{ts}.md"
        n_discr = sum(len(v["res"].get("discrepancias") or []) for v in out.values())
        casos_con_discr = [cid for cid, v in out.items() if v["res"].get("discrepancias")]
        with open(rpt, "w", encoding="utf-8") as fh:
            fh.write(f"# Revisión del cuadro de tutelas con Claude ({args.model}) — {ts}\n\n")
            fh.write(f"- Casos revisados: **{len(out)}** (de {len(cases)} en el cuadro; {n_err} errores de API).\n")
            fh.write(f"- Discrepancias detectadas: **{n_discr}** en **{len(casos_con_discr)}** casos.\n")
            if args.apply:
                fh.write(f"- Aplicado: {applied_obs} resúmenes en `observaciones`, {applied_fills} campos vacíos rellenados.\n")
            else:
                fh.write(f"- (DRY-RUN — nada se escribió a la DB.)\n")
            fh.write("\n---\n\n## Discrepancias por caso\n\n")
            for cid in sorted(casos_con_discr):
                v = out[cid]
                fh.write(f"### #{cid} — {v['job']['folder']}\n")
                fh.write(f"_Resumen Claude:_ {v['res'].get('resumen','')}\n\n")
                fh.write("| Campo | Extracción actual | Según documentos | Gravedad | Nota |\n|---|---|---|---|---|\n")
                for d in v["res"].get("discrepancias") or []:
                    cv = lambda x: str(x or "").replace("|", "\\|").replace("\n", " ")[:200]
                    fh.write(f"| {cv(d.get('campo'))} | {cv(d.get('valor_actual'))} | {cv(d.get('valor_documentos'))} | {cv(d.get('gravedad'))} | {cv(d.get('nota'))} |\n")
                fh.write("\n")
            # apéndice: lectura completa de Claude por caso (útil para comparar)
            fh.write("\n---\n\n## Apéndice — lectura de Claude vs extracción (todos los casos revisados)\n\n")
            for cid in sorted(out):
                v = out[cid]
                fh.write(f"### #{cid} — {v['job']['folder']}\n")
                fh.write("| Campo | Extracción | Claude (de los docs) |\n|---|---|---|\n")
                lect = v["res"].get("lectura") or {}
                for f in _FIELDS_FOR_CLAUDE:
                    cv = lambda x: str(x if x not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")[:200]
                    fh.write(f"| {f} | {cv(v['job']['cur'].get(f))} | {cv(lect.get(f))} |\n")
                fh.write("\n")
        print(f"\n{'─'*64}")
        print(f"OK: {n_ok} · errores API: {n_err} · discrepancias: {n_discr} en {len(casos_con_discr)} casos.")
        if args.apply:
            print(f"Aplicado: {applied_obs} observaciones + {applied_fills} campos vacíos rellenados.")
        print(f"Reporte: {rpt}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
