"""Construye dataset JSONL ChatML para fine-tune LoRA sobre IURIS.

Extrae pares (input, output) desde los 295 casos COMPLETO.
Para cada caso + cada campo poblado, busca un contexto de ±300 chars
alrededor del valor en el texto OCR de los documentos del caso.

Output: tutelas-app/data/iuris_lora_dataset.jsonl
Formato ChatML compatible con Unsloth / HuggingFace TRL / llama.cpp tooling.

Cada línea:
{
  "messages": [
    {"role": "system", "content": "Eres un asistente jurídico..."},
    {"role": "user", "content": "Texto del documento: ...\n\nPregunta: ..."},
    {"role": "assistant", "content": "..."}
  ],
  "field": "quien_impugno",
  "case_id": 123
}

Uso:
    python3 scripts/build_lora_dataset.py [--max-per-case 10] [--limit-cases N]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "tutelas.db"
OUT_PATH = Path(__file__).parent.parent / "data" / "iuris_lora_dataset.jsonl"

SYSTEM_PROMPT = (
    "Eres un asistente jurídico especializado en derecho colombiano y procesos "
    "de tutela. Tu tarea es leer fragmentos de autos judiciales y extraer "
    "información estructurada con precisión. Responde solo lo solicitado, sin "
    "comentarios adicionales."
)

# Campos a entrenar (los que están poblados con valor extraíble del texto)
FIELDS_QUESTIONS = {
    "accionante": "¿Cuál es el nombre completo del accionante (parte que presenta la tutela)? Responde solo el nombre.",
    "juzgado": "¿Cuál es el juzgado de primera instancia que conoce la tutela? Responde solo el nombre del juzgado.",
    "ciudad": "¿Cuál es la ciudad donde se desarrollan los hechos de la tutela? Responde solo el nombre de la ciudad.",
    "sentido_fallo_1st": "¿Cuál es el sentido del fallo de primera instancia? Responde una sola palabra: CONCEDE, NIEGA o IMPROCEDENTE.",
    "fecha_fallo_1st": "¿En qué fecha se profirió el fallo de primera instancia? Responde solo la fecha.",
    "impugnacion": "¿Hubo impugnación al fallo? Responde solo SI o NO.",
    "quien_impugno": "¿Quién impugnó el fallo? Responde una sola palabra: ACCIONANTE, ACCIONADO o MINISTERIO_PUBLICO.",
    "juzgado_2nd": "¿Cuál es el juzgado de segunda instancia? Responde solo el nombre del juzgado o tribunal.",
    "sentido_fallo_2nd": "¿Cuál es el sentido del fallo de segunda instancia? Responde una palabra: CONFIRMA, REVOCA o MODIFICA.",
    "incidente": "¿Hay incidente de desacato en este caso? Responde solo SI o NO.",
    "responsable_desacato": "¿Cuál es el nombre del funcionario responsable del desacato? Responde solo el nombre.",
    "decision_incidente": "¿Cuál es la decisión sobre el incidente de desacato? Resume en una frase corta.",
    "forest_impugnacion": "¿Cuál es el número de radicado FOREST de la segunda instancia? Responde solo los dígitos.",
    "derecho_vulnerado": "¿Cuál es el derecho fundamental presuntamente vulnerado? Responde la categoría.",
    "categoria_tematica": "¿Cuál es la categoría temática de esta tutela? Responde una sola palabra.",
}

# Doc filename keywords por campo (qué docs del caso son relevantes)
FIELD_DOC_HINTS = {
    "responsable_desacato": ["incident", "desacato", "apertura", "sancion", "auto"],
    "decision_incidente": ["incident", "desacato", "apertura", "sancion", "auto"],
    "fecha_apertura_incidente": ["incident", "desacato", "apertura"],
    "juzgado_2nd": ["impugna", "segunda", "tribunal", "fallo_2"],
    "sentido_fallo_2nd": ["impugna", "segunda", "tribunal", "fallo_2"],
    "fecha_fallo_2nd": ["impugna", "segunda", "tribunal", "fallo_2"],
    "forest_impugnacion": ["impugna", "segunda", "tribunal", "fallo_2"],
    "quien_impugno": ["impugna", "segunda"],
    "sentido_fallo_1st": ["fallo", "sentencia"],
    "fecha_fallo_1st": ["fallo", "sentencia"],
}


def _find_context_window(text: str, value: str, window: int = 350) -> str | None:
    """Busca el valor en el texto y retorna ventana de ±window chars."""
    if not text or not value:
        return None
    # Match exacto primero
    pos = text.lower().find(value.lower())
    if pos < 0:
        # Match por primeras 3 palabras del value (para nombres y frases)
        first_words = " ".join(value.split()[:3])
        if len(first_words) >= 5:
            pos = text.lower().find(first_words.lower())
    if pos < 0:
        return None
    start = max(0, pos - window)
    end = min(len(text), pos + len(value) + window)
    snippet = text[start:end]
    # Limpia whitespace
    snippet = re.sub(r"\s+", " ", snippet).strip()
    if len(snippet) < 50:
        return None
    return snippet


def _select_relevant_docs(docs: list[dict], field: str) -> list[dict]:
    """Filtra docs cuyo filename matchea hints del campo."""
    hints = FIELD_DOC_HINTS.get(field, [])
    if not hints:
        return docs
    sel = []
    for d in docs:
        fn = (d.get("filename") or "").lower()
        if any(h in fn for h in hints):
            sel.append(d)
    return sel or docs


def build_examples(conn: sqlite3.Connection, max_per_case: int = 10,
                    limit_cases: int = 0) -> list[dict]:
    """Genera ejemplos LoRA recorriendo casos COMPLETO."""
    conn.row_factory = sqlite3.Row
    case_cols = [r[1] for r in conn.execute("PRAGMA table_info(cases)").fetchall()]
    cases_q = "SELECT * FROM cases WHERE processing_status = 'COMPLETO'"
    if limit_cases:
        cases_q += f" LIMIT {limit_cases}"
    cases = conn.execute(cases_q).fetchall()
    print(f"→ {len(cases)} casos COMPLETO a procesar")

    examples: list[dict] = []
    field_hits = Counter()
    field_misses = Counter()

    for c in cases:
        case_id = c["id"]
        docs = conn.execute(
            "SELECT filename, extracted_text FROM documents WHERE case_id = ?",
            (case_id,)
        ).fetchall()
        docs = [{"filename": d["filename"], "text": d["extracted_text"] or ""} for d in docs]
        if not docs:
            continue

        per_case = 0
        for field, question in FIELDS_QUESTIONS.items():
            if field not in case_cols:
                continue
            value = c[field]
            if not value or not str(value).strip():
                continue
            value = str(value).strip()
            # No tomar valores triviales
            if len(value) < 2 or value.upper() in ("N/A", "NULL", "NONE"):
                continue

            # Selecciona docs relevantes
            rel_docs = _select_relevant_docs(docs, field)

            # Busca contexto en cada doc
            ctx = None
            for d in rel_docs:
                ctx = _find_context_window(d["text"][:15000], value)
                if ctx:
                    break
            if not ctx:
                # Fallback: usa primeros 500 chars del primer doc
                first_text = docs[0]["text"][:500]
                if len(first_text.strip()) > 100:
                    ctx = re.sub(r"\s+", " ", first_text).strip()
                else:
                    field_misses[field] += 1
                    continue

            # Construye ejemplo ChatML
            user_content = f"Fragmento del expediente:\n\"{ctx[:1200]}\"\n\nPregunta: {question}"
            example = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": value[:300]},
                ],
                "field": field,
                "case_id": case_id,
            }
            examples.append(example)
            field_hits[field] += 1
            per_case += 1
            if per_case >= max_per_case:
                break

    print(f"\n→ Generados {len(examples)} ejemplos\n")
    print(f"Aciertos por campo:")
    for f in FIELDS_QUESTIONS.keys():
        h, m = field_hits.get(f, 0), field_misses.get(f, 0)
        if h or m:
            print(f"  {f:30s} hits={h:4d}  misses={m:4d}")
    return examples


def write_jsonl(examples: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"\n✓ Escrito: {path} ({path.stat().st_size/1024:.1f} KB)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-case", type=int, default=10)
    ap.add_argument("--limit-cases", type=int, default=0)
    ap.add_argument("--output", type=str, default=str(OUT_PATH))
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"❌ DB no encontrada: {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH))
    try:
        examples = build_examples(conn, args.max_per_case, args.limit_cases)
        if not examples:
            print("❌ Cero ejemplos generados", file=sys.stderr)
            return 2
        # Estratifica train/val 90/10
        import random
        random.seed(42)
        random.shuffle(examples)
        cut = int(len(examples) * 0.9)
        train = examples[:cut]
        val = examples[cut:]
        out = Path(args.output)
        write_jsonl(train, out)
        val_path = out.with_name(out.stem + "_val.jsonl")
        write_jsonl(val, val_path)
        print(f"\nResumen: {len(train)} train + {len(val)} val = {len(examples)} total")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
