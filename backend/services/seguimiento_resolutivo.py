"""Extractor resolutivo focalizado para seguimiento de cumplimiento.

Premisa (validada empíricamente sobre los fallos en disco, 2026-05-19):
la parte resolutiva (RESUELVE/FALLA) vive en las ÚLTIMAS páginas del fallo
(p90 = a 6 páginas del final). En vez de leer y parsear el PDF entero, este
módulo:

  1. Lee SOLO las últimas N páginas (head+tail; aquí solo tail).
  2. Si esas páginas están escaneadas (sin capa de texto) → OCR con paddleocr.
  3. Parsea el bloque resolutivo con el regex v2 (modo lenient).
  4. Si el regex no saca órdenes pero el texto SÍ es resolutivo → LLM local
     (Qwen) como último recurso, sobre el bloque chico (barato, sin falsos
     positivos de autos porque el caller ya verificó que es una sentencia).

Reusa toda la clasificación de `seguimiento_extractor` (verbo/destinatario/plazo).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.services import seguimiento_extractor as SE
from backend.services.seguimiento_extractor import OrdenDeCumplimiento

# Umbral para considerar una página "con texto" (vs escaneada).
_MIN_CHARS_PER_PAGE = 100
_DEFAULT_TAIL_PAGES = 7


@dataclass
class ResultadoResolutivo:
    ordenes: list[OrdenDeCumplimiento]
    metodo: str            # "regex_tail" | "regex_tail_ocr" | "llm_tail" | "llm_tail_ocr" | "vacio"
    tail_text_len: int
    paginas_leidas: int
    fue_ocr: bool


def _leer_paginas(file_path: str | Path, page_indices: list[int]) -> str:
    import pymupdf
    doc = pymupdf.open(str(file_path))
    try:
        return "\n".join(doc[i].get_text() for i in page_indices if 0 <= i < doc.page_count)
    finally:
        doc.close()


def _ocr_paginas(file_path: str | Path, page_indices: list[int]) -> str:
    """OCR de páginas escaneadas con paddleocr. Best-effort: si paddleocr no está
    o falla, devuelve cadena vacía (el caller marca el caso para revisión manual)."""
    try:
        import numpy as np
        import pymupdf
        from paddleocr import PaddleOCR
    except Exception:
        return ""
    global _PADDLE
    try:
        _PADDLE
    except NameError:
        try:
            _PADDLE = PaddleOCR(use_angle_cls=True, lang="es", show_log=False)
        except Exception:
            _PADDLE = None
    if _PADDLE is None:
        return ""

    out_lines: list[str] = []
    doc = pymupdf.open(str(file_path))
    try:
        for i in page_indices:
            if not (0 <= i < doc.page_count):
                continue
            pix = doc[i].get_pixmap(matrix=pymupdf.Matrix(2, 2))  # 2x para mejor OCR
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                img = img[:, :, :3]
            try:
                res = _PADDLE.ocr(img, cls=True)
            except Exception:
                continue
            for block in (res or []):
                for line in (block or []):
                    try:
                        out_lines.append(line[1][0])
                    except Exception:
                        continue
    finally:
        doc.close()
    return "\n".join(out_lines)


def read_resolutive_tail(
    file_path: str | Path,
    n_pages: int = _DEFAULT_TAIL_PAGES,
) -> tuple[str, int, bool]:
    """Devuelve (texto_cola, paginas_leidas, fue_ocr).

    Lee las últimas n_pages. Si tienen poco texto (escaneado), las OCR-ea.
    """
    import pymupdf
    doc = pymupdf.open(str(file_path))
    pcount = doc.page_count
    doc.close()
    if pcount == 0:
        return "", 0, False
    start = max(0, pcount - n_pages)
    idxs = list(range(start, pcount))
    text = _leer_paginas(file_path, idxs)
    cpp = len(text) / max(1, len(idxs))
    if cpp >= _MIN_CHARS_PER_PAGE:
        return text, len(idxs), False
    # Escaneado → OCR
    ocr_text = _ocr_paginas(file_path, idxs)
    return ocr_text, len(idxs), True


# ── LLM fallback ──────────────────────────────────────────────────────────

_PROMPT_SYSTEM = """Eres un asistente jurídico experto en acciones de tutela colombianas.
Te doy la PARTE RESOLUTIVA de un fallo. Extrae SOLO las órdenes de cumplimiento
exigibles (ignora NOTIFICAR, REMITIR, ARCHIVAR, CONFIRMAR y la concesión del amparo).

Para cada orden devuelve:
- ordinal: PRIMERO/SEGUNDO/...
- destinatario: a quién se ordena (entidad)
- accion: qué debe hacer (1 frase corta)
- plazo_dias: número de días (48 horas = 2, 10 días = 10). 0 si no hay plazo.

Responde SOLO JSON: {"ordenes": [{"ordinal": "...", "destinatario": "...", "accion": "...", "plazo_dias": 0}]}
Si no hay ninguna orden de cumplimiento, responde {"ordenes": []}."""


def _llm_parse_resolutivo(texto: str) -> list[dict]:
    """Parsea la parte resolutiva con el LLM local. Devuelve lista de dicts."""
    try:
        from backend.extraction.ai_extractor import _call_local, _LOCAL_MODEL
    except Exception:
        return []
    bloque = texto[:8000]
    user_msg = f"/no_think\nPARTE RESOLUTIVA:\n{bloque}\n\nExtrae las órdenes de cumplimiento."
    try:
        raw, _, _ = _call_local(
            [{"role": "system", "content": _PROMPT_SYSTEM},
             {"role": "user", "content": user_msg}],
            _LOCAL_MODEL, max_tokens=700,
        )
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0) if m else raw)
        return data.get("ordenes", []) or []
    except Exception:
        return []


def _dict_to_orden(d: dict, fecha_fallo: Optional[str], texto_ordinal: str = "") -> Optional[OrdenDeCumplimiento]:
    accion = (d.get("accion") or "").strip()
    if not accion:
        return None
    plazo = d.get("plazo_dias")
    try:
        plazo = int(plazo) if plazo else None
    except Exception:
        plazo = None
    tipo_plazo = SE.TIPO_NUMERICO if plazo else SE.TIPO_SIN_PLAZO
    # Clasificar destinatario reusando el clasificador (sobre el texto que dé el LLM)
    dest_blob = f"{d.get('destinatario','')} {accion} {texto_ordinal}"
    dest_tipo, dest_texto = SE._classify_destinatario(dest_blob, sed_es_accionada_en_case=True)
    return OrdenDeCumplimiento(
        ordinal_nombre=(d.get("ordinal") or "").upper().strip() or "S/N",
        verbo_orden="(LLM)",
        verbo_tipo=SE.VERBO_IMPERATIVO,
        destinatario=d.get("destinatario", "") or dest_texto,
        destinatario_tipo=dest_tipo,
        accion_resumida=accion[:200],
        tipo_plazo=tipo_plazo,
        plazo_dias=plazo,
        plazo_raw="(LLM)",
        fecha_especifica=None,
        condicion=None,
        orden_texto=accion[:400],
        source="llm_tail",
    )


# ── Orquestador ─────────────────────────────────────────────────────────────

def extract_ordenes_focalizado(
    file_path: str | Path,
    sentido_fallo_1st: Optional[str] = None,
    sentido_fallo_2nd: Optional[str] = None,
    fecha_fallo: Optional[str] = None,
    sed_es_accionada: bool = True,
    n_tail_pages: int = _DEFAULT_TAIL_PAGES,
    use_llm: bool = True,
) -> ResultadoResolutivo:
    """Extrae órdenes leyendo solo la cola del fallo; OCR si escaneado; LLM si regex falla.

    El caller debe haber verificado que `file_path` es la sentencia del caso
    (no un auto). El filtro por sentido del fallo se aplica igual que en v2.
    """
    # Filtro por sentido (reusa la lógica v2: fallos favorables a SED → sin órdenes)
    s1 = (sentido_fallo_1st or "").upper().strip()
    s2 = (sentido_fallo_2nd or "").upper().strip()
    if s2:
        if "REVOCA" in s2 and not ("NIEGA" in s1 or "IMPROCED" in s1):
            return ResultadoResolutivo([], "vacio", 0, 0, False)
        if ("CONFIRMA" in s2 or "MODIFICA" in s2) and ("NIEGA" in s1 or "IMPROCED" in s1):
            return ResultadoResolutivo([], "vacio", 0, 0, False)

    tail, n_leidas, fue_ocr = read_resolutive_tail(file_path, n_tail_pages)
    if not tail.strip():
        return ResultadoResolutivo([], "vacio", 0, n_leidas, fue_ocr)

    # 1) Regex (lenient sobre la cola)
    ordenes = SE._extraer_ordenes_de_texto(tail, fecha_fallo, sed_es_accionada, lenient_resuelve=True)
    if ordenes:
        metodo = "regex_tail_ocr" if fue_ocr else "regex_tail"
        return ResultadoResolutivo(ordenes, metodo, len(tail), n_leidas, fue_ocr)

    # 1.5) Guard CONFIRMA (2026-05-19): si la cola es una confirmación pura de 2da
    # instancia ("PRIMERO: CONFIRMAR la sentencia..."), NO ir al LLM — alucinaría
    # órdenes desde los considerandos (medido: casos 107/152/154). La orden real
    # vive en la 1ra instancia; el caller debe pasarla (ver doc_sentencia_para_ordenes).
    _blk = SE._find_resuelve_block(tail) or SE._find_resuelve_block_lenient(tail)
    if _blk and SE._SOLO_CONFIRMA.search(_blk[:500]):
        return ResultadoResolutivo([], "vacio_confirma", len(tail), n_leidas, fue_ocr)

    # 2) LLM fallback
    if use_llm:
        try:
            from backend.services import llm_mutex
            if llm_mutex.is_up():
                dicts = _llm_parse_resolutivo(tail)
                llm_ordenes = []
                for d in dicts:
                    o = _dict_to_orden(d, fecha_fallo)
                    if o and o.destinatario_tipo != SE.DEST_EXTERNO:
                        # fecha_limite la calcula el caller; aquí solo órdenes
                        llm_ordenes.append(o)
                if llm_ordenes:
                    metodo = "llm_tail_ocr" if fue_ocr else "llm_tail"
                    return ResultadoResolutivo(llm_ordenes, metodo, len(tail), n_leidas, fue_ocr)
        except Exception:
            pass

    return ResultadoResolutivo([], "vacio", len(tail), n_leidas, fue_ocr)


def doc_sentencia_para_ordenes(docs, sentido_fallo_2nd: Optional[str] = None):
    """Elige el documento (PDF) donde vive la ORDEN de cumplimiento.

    Regla jurídica: la orden sustantiva vive en la sentencia de **1ra instancia**,
    SALVO que la 2da instancia REVOQUE o MODIFIQUE (ahí la orden nueva está en la
    2da). Una 2da que solo CONFIRMA no repite la orden → hay que leer la 1ra.

    `docs`: iterable de objetos con atributos/keys `doc_type` y `file_path`.
    Devuelve (file_path, instancia) — instancia ∈ {"1ra","2da"} — o (None, None).
    """
    def _get(d, k):
        if isinstance(d, dict):
            return d.get(k)
        try:
            return d[k]  # sqlite3.Row soporta subscript pero no getattr
        except Exception:
            return getattr(d, k, None)

    s2 = (sentido_fallo_2nd or "").upper()
    prefer_2da = "REVOCA" in s2 or "MODIFICA" in s2

    sent_1ra, sent_2da, sent_any = [], [], []
    for d in docs:
        dt = (_get(d, "doc_type") or "").upper()
        fp = _get(d, "file_path")
        if not fp or "SENTENCIA" not in dt:
            continue
        if "2DA" in dt or "2A" in dt or "SEGUNDA" in dt:
            sent_2da.append(fp)
        elif "1RA" in dt or "1A" in dt or "PRIMERA" in dt:
            sent_1ra.append(fp)
        else:
            sent_any.append(fp)

    if prefer_2da:
        orden = sent_2da or sent_1ra or sent_any
        return (orden[0], "2da") if orden else (None, None)
    # CONFIRMA o sin 2da → 1ra
    if sent_1ra:
        return sent_1ra[0], "1ra"
    if sent_any:
        return sent_any[0], "1ra"
    if sent_2da:
        return sent_2da[0], "2da"
    return None, None
