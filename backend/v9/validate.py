"""Capa de VALIDACIÓN de la re-arquitectura (re-arquitectura 2026-06-22).

Diseño SIMÉTRICO (cada capa valida a la otra donde es más fuerte):
- IDENTIFICADORES (radicado/FOREST/fechas): DeepSeek los extrae, pero un validador DETERMINISTA
  confirma que aparecen LITERALMENTE en el expediente → rechaza alucinaciones (un dígito mal =
  caso/plazo equivocado). El regex no puede alucinar → es el verificador.
- VERBATIM (pretensiones, parte_resolutiva_*): los transcribe el DETERMINISTA (copia textual),
  pero el LLM CONFIRMA que la transcripción es correcta/completa y del documento correcto
  (tiene el contexto completo). El LLM entiende → es el verificador.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("tutelas.v9.validate")

_DATE_FIELDS = ("fecha_ingreso", "fecha_respuesta", "fecha_fallo_1st", "fecha_fallo_2nd",
                "fecha_apertura_incidente", "fecha_apertura_incidente_2", "fecha_apertura_incidente_3")
_VERBATIM_FIELDS = ("pretensiones", "parte_resolutiva_1st", "parte_resolutiva_2nd",
                    "parte_resolutiva_incidente")


@dataclass
class FieldCheck:
    field: str
    status: str   # "ok" | "warn" | "reject"
    reason: str


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


# ─────────────────────────────────────────────────────────────
# 1) Validadores deterministas de IDENTIFICADORES (anti-alucinación)
# ─────────────────────────────────────────────────────────────

def validate_identifiers(out: dict, bundle: str) -> list[FieldCheck]:
    """Verifica que radicado_23/FOREST/fechas que emitió el LLM aparezcan LITERALMENTE en el
    expediente. Devuelve checks (reject = probable alucinación)."""
    checks: list[FieldCheck] = []
    bundle_digits = _digits(bundle)

    r23 = _digits(out.get("radicado_23_digitos", ""))
    if r23:
        core = r23[:20]  # núcleo del CUP (sin el recurso de 2 díg final)
        if len(core) >= 18 and core not in bundle_digits:
            checks.append(FieldCheck("radicado_23_digitos", "reject",
                                     "los dígitos no aparecen en el expediente (posible alucinación)"))

    forest = (out.get("radicado_forest", "") or "").strip()
    if forest:
        fd = _digits(forest)
        if forest not in bundle and (len(fd) < 6 or fd not in bundle_digits):
            checks.append(FieldCheck("radicado_forest", "reject",
                                     "el FOREST no aparece literal en el expediente"))

    for f in _DATE_FIELDS:
        v = (out.get(f, "") or "").strip()
        if not v:
            continue
        if not re.match(r"^\d{2}/\d{2}/\d{4}$", v):
            checks.append(FieldCheck(f, "warn", f"formato de fecha no canónico: {v!r}"))
        else:
            yr = int(v[-4:])
            if not (2018 <= yr <= 2028):
                checks.append(FieldCheck(f, "warn", f"año {yr} fuera de rango plausible"))
    return checks


def apply_identifier_guards(out: dict, bundle: str) -> tuple[dict, list[str]]:
    """Aplica los validadores: BORRA los identificadores rechazados (alucinados) y devuelve
    warnings. Mejor vacío (honesto) que un radicado/FOREST inventado."""
    r = dict(out)
    warnings: list[str] = []
    for c in validate_identifiers(r, bundle):
        if c.status == "reject":
            logger.warning("validate: %s rechazado (%s) — valor borrado: %r", c.field, c.reason, r.get(c.field))
            r[c.field] = ""
        warnings.append(f"{c.field}[{c.status}]: {c.reason}")
    return r, warnings


# ─────────────────────────────────────────────────────────────
# 2) Confirmación LLM de los VERBATIM (transcripción determinista)
# ─────────────────────────────────────────────────────────────

def confirm_verbatim(field: str, transcribed: str, doc_text: str) -> FieldCheck:
    """El LLM CONFIRMA que `transcribed` (hecho por la transcripción determinista) es una
    transcripción correcta/completa del `doc_text`. NO reescribe — solo confirma o flaggea.

    Gateado: LLM off → 'ok' (no se valida). Abstención-segura.
    """
    transcribed = (transcribed or "").strip()
    if not transcribed:
        return FieldCheck(field, "ok", "vacío (nada que confirmar)")
    from backend.email.llm_adjudicator import llm_on
    if not llm_on() or len((doc_text or "").strip()) < 100:
        return FieldCheck(field, "ok", "LLM off / sin doc")

    que = ("las PRETENSIONES del accionante" if field == "pretensiones"
           else "la PARTE RESOLUTIVA (el RESUELVE) del fallo/auto")
    prompt = (
        f"Tienes el TEXTO de un documento judicial y una TRANSCRIPCIÓN que alguien hizo de "
        f"{que}. Confirma si la transcripción es CORRECTA, COMPLETA y proviene de ESTE documento.\n\n"
        f"TRANSCRIPCIÓN A VERIFICAR:\n{transcribed[:4000]}\n\n"
        f"TEXTO DEL DOCUMENTO:\n{(doc_text or '')[:40000]}\n\n"
        "Responde SOLO JSON: {\"ok\": true|false, \"reason\": \"<breve: si falta algún numeral, "
        "si es de otro documento (ej. un auto en vez del fallo), o si está incompleta>\"}"
    )
    try:
        from backend.extraction.ai_extractor import _call_local
        raw, _, _ = _call_local(
            [{"role": "system", "content": "Verificas transcripciones jurídicas. Respondes solo JSON."},
             {"role": "user", "content": prompt}],
            max_tokens=300,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("confirm_verbatim %s falló: %s", field, e)
        return FieldCheck(field, "ok", f"LLM error: {str(e)[:60]}")
    raw = re.sub(r"```(?:json)?|```", "", raw or "").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return FieldCheck(field, "ok", "respuesta no-JSON")
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return FieldCheck(field, "ok", "JSON inválido")
    ok = bool(d.get("ok", True))
    reason = str(d.get("reason", ""))[:200]
    return FieldCheck(field, "ok" if ok else "warn", reason)
