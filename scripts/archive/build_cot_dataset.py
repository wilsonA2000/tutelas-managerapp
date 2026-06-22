"""IURIS — Construye dataset Chain-of-Thought (CoT) desde el dataset base.

Toma `iuris_lora_dataset.jsonl` (input → output) y lo reformula a:
  input → razonamiento estructurado → output

Cada ejemplo CoT enseña al modelo a:
1. Identificar marcadores textuales del campo
2. Aplicar heurísticas del COGNITIVE_BLUEPRINT
3. Devolver respuesta normalizada

Output: data/iuris_lora_dataset_cot.jsonl
        data/iuris_lora_dataset_cot_val.jsonl

El razonamiento sigue plantillas por campo basadas en COGNITIVE_BLUEPRINT.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
INPUT_TRAIN = ROOT / "data" / "iuris_lora_dataset.jsonl"
INPUT_VAL = ROOT / "data" / "iuris_lora_dataset_val.jsonl"
OUTPUT_TRAIN = ROOT / "data" / "iuris_lora_dataset_cot.jsonl"
OUTPUT_VAL = ROOT / "data" / "iuris_lora_dataset_cot_val.jsonl"

# Plantillas de razonamiento por campo
REASONING_TEMPLATES = {
    "accionante": (
        "Busco el marcador de quien presenta la tutela. "
        "Detecto '{marker}' en el texto. "
        "Extraigo el nombre, filtro honoríficos. "
        "Verifico que sea persona natural (no entidad)."
    ),
    "juzgado": (
        "Busco el encabezado del documento. "
        "Identifico patrón 'JUZGADO X TIPO MUNICIPAL/CIRCUITO DE CIUDAD'. "
        "Confirmo que es 1ra instancia (no Tribunal Superior)."
    ),
    "juzgado_2nd": (
        "Busco mención de Tribunal o Sala superior. "
        "Confirmo que el caso fue impugnado. "
        "Format: 'TRIBUNAL [TIPO] DE [CIUDAD] - SALA [X]'."
    ),
    "ciudad": (
        "Busco la ciudad donde ocurren los hechos (no la del juzgado). "
        "Tomo la mención de domicilio o lugar del hecho vulnerador."
    ),
    "sentido_fallo_1st": (
        "Busco la sección RESUELVE/FALLA. "
        "Identifico verbo principal: TUTELAR/CONCEDER → CONCEDE; "
        "NEGAR/DENEGAR → NIEGA; IMPROCEDENTE → IMPROCEDENTE."
    ),
    "sentido_fallo_2nd": (
        "Busco RESUELVE en fallo de 2da instancia. "
        "CONFIRMAR → CONFIRMA; REVOCAR → REVOCA; MODIFICAR → MODIFICA."
    ),
    "fecha_fallo_1st": (
        "Busco fecha del fallo en pie de firma o encabezado. "
        "Devuelvo formato como aparece (DD/MM/YYYY o 'DD de MES de YYYY')."
    ),
    "fecha_fallo_2nd": (
        "Busco fecha del fallo de 2da instancia. "
        "Verifico que sea posterior al fallo de 1ra."
    ),
    "impugnacion": (
        "Busco menciones de 'impugna', 'recurre', 'interpone recurso'. "
        "También evidencia de fallo de 2da instancia. "
        "SI si hay alguna; NO si nada."
    ),
    "quien_impugno": (
        "Identifico el sujeto del verbo 'impugna'. "
        "Persona natural → ACCIONANTE; "
        "Entidad pública → ACCIONADO; "
        "Procuraduría/Personería → MINISTERIO_PUBLICO."
    ),
    "incidente": (
        "Busco 'incidente de desacato APERTURADO' (no solo requerimiento previo). "
        "SI si hay apertura formal; NO si no."
    ),
    "responsable_desacato": (
        "Busco 'REQUERIR a X', 'INCIDENTAR a X', 'SANCIONAR al señor X'. "
        "Extraigo NOMBRE de persona física (no entidad). "
        "Filtro honoríficos: 'la Dra.', 'el señor', 'doctor'."
    ),
    "decision_incidente": (
        "Busco RESUELVE en auto incidental. "
        "Capturo verbo+complemento corto: "
        "'Archivar por...', 'Sancionar con N días', 'Requerimiento previo'."
    ),
    "derecho_vulnerado": (
        "Busco mención del derecho fundamental afectado. "
        "Extraigo palabra clave: 'Educación', 'Salud', 'Petición', etc."
    ),
    "categoria_tematica": (
        "Identifico el tema principal de la tutela. "
        "Categoría única que resume el motivo."
    ),
}


def detect_marker(text: str, field: str, value: str) -> str:
    """Detecta el marcador textual aproximado donde apareció el valor."""
    if not value:
        return "(no identificado)"
    # Buscar primeras palabras del value en el texto
    val_first = " ".join(str(value).split()[:3]).lower()
    text_lower = text.lower()
    pos = text_lower.find(val_first)
    if pos < 0:
        return "(valor no encontrado en texto)"
    # Tomar contexto previo (50 chars) para detectar marcador
    pre = text[max(0, pos - 80):pos].strip()
    # Last 30 chars del prefijo = marcador probable
    marker = pre[-50:].strip()
    # Limpiar saltos de línea y espacios
    marker = re.sub(r"\s+", " ", marker)
    return marker[-40:] if len(marker) > 40 else marker


def build_cot_assistant(field: str, value: str, user_text: str) -> str:
    """Construye respuesta CoT con razonamiento estructurado."""
    template = REASONING_TEMPLATES.get(field, "Aplico reglas de extracción del campo.")

    # Detectar marker para llenar plantilla
    # User text contiene "Fragmento del expediente: \"<TEXTO>\"\n\nPregunta: ..."
    m = re.search(r'"([^"]+)"', user_text, re.DOTALL)
    text_content = m.group(1) if m else user_text
    marker = detect_marker(text_content, field, value)

    # Llenar plantilla con marker detectado
    reasoning = template.replace("{marker}", marker)

    # Format CoT: razonamiento corto + respuesta directa
    return f"<think>{reasoning}</think>\n{value}"


def transform_example(ex: dict) -> dict | None:
    """Convierte ejemplo {messages: [...]} a versión CoT."""
    msgs = ex.get("messages", [])
    if len(msgs) < 3:
        return None
    field = ex.get("field", "")
    if field not in REASONING_TEMPLATES:
        return None  # No tenemos plantilla para este campo

    system = msgs[0]["content"]
    user = msgs[1]["content"]
    original_value = msgs[2]["content"]

    new_assistant = build_cot_assistant(field, original_value, user)

    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": new_assistant},
        ],
        "field": field,
        "case_id": ex.get("case_id"),
    }


def process_file(input_path: Path, output_path: Path) -> tuple[int, int]:
    """Procesa archivo JSONL, devuelve (input_count, output_count)."""
    if not input_path.exists():
        print(f"⚠️ Input no existe: {input_path}", file=sys.stderr)
        return 0, 0
    n_in = 0
    n_out = 0
    with input_path.open("r", encoding="utf-8") as f_in, \
         output_path.open("w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            n_in += 1
            try:
                ex = json.loads(line)
            except json.JSONDecodeError:
                continue
            new_ex = transform_example(ex)
            if new_ex is None:
                continue
            f_out.write(json.dumps(new_ex, ensure_ascii=False) + "\n")
            n_out += 1
    return n_in, n_out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-train", default=str(INPUT_TRAIN))
    ap.add_argument("--input-val", default=str(INPUT_VAL))
    ap.add_argument("--output-train", default=str(OUTPUT_TRAIN))
    ap.add_argument("--output-val", default=str(OUTPUT_VAL))
    args = ap.parse_args()

    print(f"→ Procesando train...")
    n_in, n_out = process_file(Path(args.input_train), Path(args.output_train))
    print(f"  {n_in} in → {n_out} out (skip: {n_in - n_out})")

    print(f"→ Procesando val...")
    n_in_v, n_out_v = process_file(Path(args.input_val), Path(args.output_val))
    print(f"  {n_in_v} in → {n_out_v} out (skip: {n_in_v - n_out_v})")

    print()
    print(f"✓ Output train: {args.output_train}")
    print(f"✓ Output val:   {args.output_val}")
    print()
    print("Sample CoT example:")
    with Path(args.output_train).open() as f:
        for line in f:
            ex = json.loads(line)
            if ex.get("field") == "responsable_desacato":
                print(json.dumps(ex, ensure_ascii=False, indent=2)[:800])
                break

    return 0


if __name__ == "__main__":
    sys.exit(main())
