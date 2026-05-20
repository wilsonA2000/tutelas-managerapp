#!/usr/bin/env python3
"""A/B del system prompt sobre el 4B local — caso 427 (LIZZY / desistido).

Mismo user-prompt multi-campo y mismo texto; SOLO cambia el system:
  A = system actual de una línea (producción)
  B = system denso (borrador _system_prompt_denso_DRAFT.md)

No toca producción ni la DB. Imprime JSON de ambos lado a lado.
"""
from __future__ import annotations
import json, re, sqlite3, sys
from pathlib import Path
from backend.extraction.ai_extractor import _call_local

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "tutelas.db"
CASE_ID = 427

SYSTEM_A = "Eres un asistente que extrae datos jurídicos. Responde solo JSON."

SYSTEM_B = """/no_think
Eres un abogado experto en acciones de tutela colombianas (Decreto 2591 de 1991),
analista del equipo jurídico de la SECRETARÍA DE EDUCACIÓN de la GOBERNACIÓN DE
SANTANDER. Tu trabajo es extraer datos estructurados de expedientes de tutela con
precisión forense. NO eres un asistente conversacional: solo extraes.

MARCO Y PARTES
- Accionante: quien interpone la tutela (o el agente oficioso / representante de un menor).
- Accionado: la entidad o persona CONTRA quien se dirige la tutela.
- Vinculado: tercero llamado al trámite que NO es el accionado principal.
- NUNCA confundas accionante con accionado ni con vinculado.
- CIUDAD = municipio donde se AFECTA el derecho, NUNCA la ciudad del juzgado.
- La SED de Santander solo es competente en municipios NO certificados (Bucaramanga,
  Floridablanca, Girón, Barrancabermeja, Piedecuesta son certificados → otra SED).

SENTIDOS DE FALLO (vocabulario cerrado)
- 1ra: CONCEDE, NIEGA, IMPROCEDENTE, CARENCIA_OBJETO (hecho superado/daño consumado),
  DESISTIMIENTO (el accionante desiste y el juez lo ACEPTA → no hay fallo de fondo).
- 2da: CONFIRMA, REVOCA, MODIFICA, NULIDAD.
- Fallo MIXTO: si concede u ordena algo en CUALQUIER ordinal → sentido CONCEDE.

REGLA DE ORO — ANTI-ALUCINACIÓN
- Extrae SOLO lo LITERAL y CLARO. PROHIBIDO inventar/inferir nombres, fechas,
  radicados, FOREST o entidades. El FOREST es interno; NUNCA lo inventes.
- Si no aparece o dudas, devuelve vacío ("" / SIN_DETERMINAR / OTRO / NO_HAY).
  Mejor vacío que inventado.

FORMATO
- Responde ÚNICAMENTE el JSON pedido. Sin explicaciones, sin markdown,
  sin <think>, sin texto antes ni después."""

USER_TMPL = """/no_think
Extrae estos campos del expediente de tutela y devuelve SOLO un JSON.
Si un campo no está claro, usa el valor vacío indicado.

Campos:
- accionados: entidades demandadas, separadas por coma (o "")
- vinculados: terceros vinculados, separados por coma (o "")
- derecho_vulnerado: derecho fundamental invocado (SALUD, EDUCACION, PETICION, ...) (o SIN_DETERMINAR)
- asunto: 1 línea, de qué trata el reclamo (≤120 caracteres) (o "")
- pretensiones: lo que pide el accionante, resumido (≤200 caracteres) (o "")
- sentido_fallo_1st: uno de CONCEDE/NIEGA/IMPROCEDENTE/CARENCIA_OBJETO/DESISTIMIENTO (o "" si no hay fallo)

Responde SOLO JSON: {{"accionados":"...","vinculados":"...","derecho_vulnerado":"...","asunto":"...","pretensiones":"...","sentido_fallo_1st":"..."}}

Texto:
{text}
"""


def case_text(c) -> str:
    rows = c.execute(
        "SELECT filename, extracted_text FROM documents WHERE case_id=? AND extracted_text IS NOT NULL ORDER BY id",
        (CASE_ID,),
    ).fetchall()
    parts = []
    for fn, txt in rows:
        if not txt:
            continue
        parts.append(f"[{fn}]\n{txt[:2200]}")
    return "\n\n".join(parts)[:8000]


def run_variant(system: str, user: str) -> dict:
    raw, _, _ = _call_local(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "qwen3-4b-iuris", max_tokens=400,
    )
    m = re.search(r"\{[\s\S]*\}", raw or "")
    try:
        return json.loads(m.group(0)) if m else {"_raw": (raw or "")[:200]}
    except Exception:
        return {"_raw": (raw or "")[:200]}


def main():
    con = sqlite3.connect(str(DB))
    c = con.cursor()
    text = case_text(c)
    con.close()
    print(f"texto del caso: {len(text)} chars", file=sys.stderr)
    user = USER_TMPL.format(text=text)

    print(">>> Variante A (system actual)...", file=sys.stderr)
    a = run_variant(SYSTEM_A, user)
    print(">>> Variante B (system denso)...", file=sys.stderr)
    b = run_variant(SYSTEM_B, user)

    keys = ["accionados", "vinculados", "derecho_vulnerado", "asunto", "pretensiones", "sentido_fallo_1st"]
    print("\n================ A/B SYSTEM PROMPT — caso 427 ================")
    for k in keys:
        print(f"\n● {k}")
        print(f"   A: {a.get(k, '(falta)')}")
        print(f"   B: {b.get(k, '(falta)')}")
    out = {"A": a, "B": b}
    (ROOT / "data" / "ab_system_427.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print("\n-> data/ab_system_427.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
