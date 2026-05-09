"""
Fase D — LLM solo en campos textuales que quedaron NULL tras Fase A+B+C.

Llama directo a llama-server:8765 (no pasa por backend uvicorn).
1 LLM call por caso. Prompt enfocado solo en 4 campos:
  - asunto
  - derecho_vulnerado
  - pretensiones
  - observaciones

Uso:
  .venv/bin/python3 scripts/llm_fill_textuales.py [--limit N] [--workers 1]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
import pymupdf
from sqlalchemy.orm import Session
from backend.database.database import SessionLocal
from backend.database.models import Case, Document

LLM_URL = "http://127.0.0.1:8765/v1/chat/completions"

SYSTEM_PROMPT = """Eres un extractor de datos jurídicos. Tu única tarea es extraer 4 campos del cuadro de tutelas.

Lee los documentos y devuelve JSON con estas claves EXACTAS:

{
  "asunto": "frase corta (1 línea, max 200 chars) que describa de qué trata la tutela. Ej: 'Solicita garantía de alimentación escolar' o 'Solicita docente de apoyo'",
  "derecho_vulnerado": "lista de derechos invocados separados por ' - '. Ej: 'EDUCACION - SALUD - MINIMO VITAL'",
  "pretensiones": "qué pide el accionante (max 400 chars). Resumir si es muy largo",
  "observaciones": "datos relevantes adicionales: condición especial del accionante, fechas críticas, advertencias del juez (max 300 chars)"
}

Reglas:
- Devuelve SOLO el JSON, sin explicación.
- Si un campo no se puede determinar, usa "" (string vacío).
- NO inventes información. Si no está en el doc, usa "".
- Mayúsculas SOLO en derecho_vulnerado (ej: 'EDUCACION').
- Asunto y observaciones en frases naturales.
"""

def extract_pdf_pages(path: Path, first=5, last=3) -> str:
    try:
        doc = pymupdf.open(str(path))
        n = doc.page_count
        if n <= first + last:
            indices = range(n)
        else:
            indices = list(range(first)) + list(range(n - last, n))
        text = "\n".join(doc[i].get_text() for i in indices)
        doc.close()
        return text[:6000]
    except Exception:
        return ""

def get_case_context(case: Case, db: Session, max_chars: int = 5000) -> str:
    """Construye contexto compacto: Escrito Tutela + Auto Avoca + Sentencia 1ra."""
    docs = db.query(Document).filter(Document.case_id == case.id).all()
    parts = []
    PRIORITY = ['PDF_ESCRITO_TUTELA', 'PDF_AUTO_ADMISORIO', 'PDF_FALLO_1RA', 'PDF_AUTO_VINCULA']
    for tipo in PRIORITY:
        for d in docs:
            if d.doc_type == tipo:
                p = Path(d.file_path)
                if p.exists() and p.suffix.lower() == '.pdf':
                    txt = extract_pdf_pages(p, first=4, last=2)
                    if txt:
                        parts.append(f"--- {tipo}: {d.filename} ---\n{txt[:2500]}")
                        break  # uno por tipo
    if not parts:
        # Fallback: Email .md
        for d in docs:
            if d.doc_type == 'EMAIL_MD':
                p = Path(d.file_path)
                if p.exists():
                    try:
                        txt = p.read_text(encoding='utf-8', errors='ignore')[:2500]
                        parts.append(f"--- EMAIL: {d.filename} ---\n{txt}")
                        break
                    except: pass
    context = "\n\n".join(parts)
    return context[:max_chars]

def call_llm(context: str, current_fields: dict) -> dict | None:
    """Llama al LLM. Devuelve dict de campos extraídos."""
    user_msg = f"/no_think\n\nDocumentos del caso:\n\n{context}\n\nCampos ya extraídos (NO los repitas, solo informativo):\n{json.dumps(current_fields, ensure_ascii=False, indent=2)}\n\nDevuelve SOLO el JSON con las 4 claves."

    try:
        r = requests.post(LLM_URL,
            json={
                "model": "qwen3-4b-iuris",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 1024,
                "temperature": 0.1,
                "stream": False,
            },
            timeout=300,
        )
        if r.status_code != 200:
            return None
        body = r.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        # Extraer JSON del content
        # Eliminar <think>...</think> si aparece
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.S)
        content = content.strip()
        # Buscar primer { ... }
        m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            # Limpiar valores
            return {k: (str(v).strip() if v else None) for k, v in data.items() if k in ('asunto','derecho_vulnerado','pretensiones','observaciones')}
        except json.JSONDecodeError:
            return None
    except Exception as e:
        return {"_error": str(e)[:100]}

def process_case(case: Case, db: Session) -> dict:
    """Procesa un caso. Devuelve dict de campos extraídos por LLM."""
    # Verificar qué campos faltan
    missing = []
    for f in ('asunto','derecho_vulnerado','pretensiones','observaciones'):
        v = getattr(case, f, None)
        if not v:
            missing.append(f)

    if not missing:
        return {"_skip": "todos los campos ya llenos"}

    # Construir contexto
    context = get_case_context(case, db)
    if not context or len(context) < 200:
        return {"_skip": "sin contexto suficiente"}

    # Campos ya extraídos (Fase A+B+C) para que el LLM tenga visión global
    current = {
        "rad23": case.radicado_23_digitos,
        "accionante": case.accionante,
        "accionados": case.accionados,
        "juzgado": case.juzgado,
    }
    current = {k: v for k, v in current.items() if v}

    # LLM call
    result = call_llm(context, current)
    if not result or "_error" in (result or {}):
        return result or {"_error": "llm fail"}

    # Solo devolver campos faltantes
    return {f: v for f, v in result.items() if f in missing and v}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1, help="LLM secuencial recomendado (parallel=1)")
    args = ap.parse_args()

    db: Session = SessionLocal()
    cases = db.query(Case).filter(
        (Case.asunto.is_(None)) | (Case.asunto == '') |
        (Case.derecho_vulnerado.is_(None)) | (Case.derecho_vulnerado == '')
    ).order_by(Case.id).all()
    if args.limit:
        cases = cases[:args.limit]
    print(f"Procesando {len(cases)} casos con LLM (campos textuales)...")

    started = time.time()
    counts = {"ok": 0, "skip": 0, "error": 0, "fields_total": 0}

    for i, case in enumerate(cases, 1):
        try:
            result = process_case(case, db)
            if "_skip" in result:
                counts["skip"] += 1
            elif "_error" in result:
                counts["error"] += 1
            else:
                fields_added = 0
                for k, v in result.items():
                    if v and not getattr(case, k, None):
                        setattr(case, k, v)
                        fields_added += 1
                counts["ok"] += 1
                counts["fields_total"] += fields_added
            if i % 10 == 0:
                db.commit()
            elapsed = time.time() - started
            avg = elapsed / i
            eta = avg * (len(cases) - i)
            status = "✓" if "_skip" not in result and "_error" not in result else ("⊘" if "_skip" in result else "✗")
            print(f"  [{i:>3}/{len(cases)}] {status} case#{case.id:<4} avg={avg:.1f}s/c ETA={eta/60:.0f}m fields_total={counts['fields_total']}")

        except Exception as e:
            counts["error"] += 1
            print(f"  [{i}] EXCEPTION case#{case.id}: {e}")
            db.rollback()
            continue

    db.commit()
    elapsed = time.time() - started
    print(f"\n=== RESULTADO ===")
    print(f"  Casos procesados: {len(cases)}")
    print(f"  OK: {counts['ok']}  SKIP: {counts['skip']}  ERROR: {counts['error']}")
    print(f"  Total campos llenados: {counts['fields_total']}")
    print(f"  Tiempo total: {elapsed/60:.1f} min  ({elapsed/len(cases):.1f}s/caso)")
    db.close()

if __name__ == "__main__":
    main()
