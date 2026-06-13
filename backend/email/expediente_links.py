"""Cosecha y parseo de links de expediente judicial (OneDrive/SharePoint cendoj).

Los juzgados notifican por correo con un link al expediente digital en el
OneDrive de la Rama Judicial (tenant `etbcsj-my.sharepoint.com`). Ese link es
doble oro:

1. **Señal de matching**: el PATH de la carpeta compartida contiene el radicado
   VERDADERO del proceso (la estructura de archivo del propio juzgado), aun
   cuando el subject del correo traiga el rad con typo (caso real e2038:
   subject decía 2022-00027, el path del link decía .../...0012700/... = c395).
2. **Fuente documental**: la carpeta compartida tiene el expediente completo
   con nombres curados por el juzgado (ver `services/expediente_fetcher.py`).

Este módulo es PURO (0 red, 0 DB): regex + parsing de URLs. La resolución de
links tokenizados (que requiere red) vive en `services/expediente_fetcher.py`.

OJO matching difuso: el rad del path TAMBIÉN puede traer typo del juzgado
(caso real: carpeta `69432318900120220012700` por `68432...` — dígito 2 del
DANE). Por eso `rad23_suffix_key` ancla en las posiciones [5:21] (entidad+
especialidad+despacho+año+secuencia = 16 dígitos), inmunes a typos del prefijo
de municipio y suficientemente únicas (año+secuencia+despacho).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

from backend.email.rad_utils import normalize_rad23

# ── Regex de cosecha ──────────────────────────────────────────────
# 1) Link tokenizado (el que viene en los correos; otorga cookie FedAuth anónima):
#    https://etbcsj-my.sharepoint.com/:f:/g/personal/<owner>/<token>?e=xxx
#    :f: carpeta · :b: archivo · :w:/:x: office
# 2) Vista web (lo que queda en la barra del navegador; trae el path en id=):
#    https://.../personal/<owner>/_layouts/15/onedrive.aspx?id=%2Fpersonal%2F...
# 3) guestaccess.aspx legacy.
_TOKENIZED_RE = re.compile(
    r"https://[a-z0-9\-]+\-my\.sharepoint\.com/:([fbwx]):/g/personal/[^\s\"'<>\)\]]+",
    re.IGNORECASE,
)
_ONEDRIVE_VIEW_RE = re.compile(
    r"https://[a-z0-9\-]+\-my\.sharepoint\.com/personal/[^\s\"'<>\)\]]*?onedrive\.aspx\?[^\s\"'<>\)\]]+",
    re.IGNORECASE,
)
_GUESTACCESS_RE = re.compile(
    r"https://[a-z0-9\-]+\.sharepoint\.com/[^\s\"'<>\)\]]*?guestaccess\.aspx\?[^\s\"'<>\)\]]+",
    re.IGNORECASE,
)

_RAD_IN_PATH_RE = re.compile(r"\d{19,23}")


@dataclass
class ExpedienteLinkInfo:
    """Resultado del parseo de un link de expediente (sin red)."""

    url: str
    kind: str = ""           # 'share_folder' / 'share_file' / 'onedrive_view' / 'guestaccess'
    owner: str = ""          # j01prctomalaga_cendoj_ramajudicial_gov_co
    juzgado_hint: str = ""   # j01prctomalaga (primer label del owner)
    server_path: str = ""    # /personal/<owner>/Documents/... (solo onedrive_view; los
                             # tokenizados requieren red → fetcher.resolve_share_link)
    rad23_url: str = ""      # rad de 19-23 dígitos hallado en el path
    etapa: str = ""          # último segmento si la carpeta compartida es una etapa
    instancia_hint: str = "" # segmento tipo '006AccionesTutelaPrimeraInstancia'
    archivado: bool = False  # path contiene /ARCHIVADO/
    extra: dict = field(default_factory=dict)


def harvest_expediente_links(text: str | None) -> list[str]:
    """Extrae los links de expediente del texto (dedup, orden de aparición)."""
    if not text:
        return []
    seen: list[str] = []
    for rx in (_TOKENIZED_RE, _ONEDRIVE_VIEW_RE, _GUESTACCESS_RE):
        for m in rx.finditer(text):
            url = m.group(0).rstrip(".,;").rstrip()
            if url not in seen:
                seen.append(url)
    return seen


def _owner_from_path(path: str) -> str:
    """'/personal/<owner>/...' → '<owner>'."""
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "personal":
        return parts[1]
    return ""


def _juzgado_hint(owner: str) -> str:
    """'j01prctomalaga_cendoj_ramajudicial_gov_co' → 'j01prctomalaga'."""
    return owner.split("_", 1)[0] if owner else ""


def parse_server_path(server_path: str) -> dict:
    """Extrae rad/etapa/instancia/archivado de un server-relative path decodificado.

    El rad puede venir como segmento puro (`.../68432318900120220012700/...`) o
    EMBEBIDO en el nombre de la carpeta del juzgado (caso real:
    `03) 684644089001202500107Educación`). Se prefiere el segmento puro; si no
    hay, se toma el último rad embebido (carpeta más profunda)."""
    segs = [s for s in unquote(server_path).split("/") if s]
    rad = ""
    rad_seg = ""   # segmento donde vive el rad
    etapa = ""
    instancia = ""
    archivado = False
    for s in segs:
        if s.upper() == "ARCHIVADO":
            archivado = True
        if not instancia and re.match(r"^\d{3}.*(Instancia|Tutela)", s, re.IGNORECASE):
            instancia = s
        if _RAD_IN_PATH_RE.fullmatch(s):
            rad = s
            rad_seg = s
    if not rad:
        for s in segs:
            for m in _RAD_IN_PATH_RE.finditer(s):
                rad = m.group(0)
                rad_seg = s
    if segs:
        last = segs[-1]
        # la carpeta compartida es una etapa solo si el último segmento NO es
        # (ni contiene) el rad — si lo contiene, ES la carpeta del caso.
        if last != rad_seg and not _RAD_IN_PATH_RE.search(last):
            etapa = last
    return {
        "rad23_url": rad,
        "etapa": etapa,
        "instancia_hint": instancia,
        "archivado": archivado,
    }


def parse_expediente_link(url: str) -> ExpedienteLinkInfo:
    """Parsea un link de expediente SIN red.

    Para `onedrive_view` el path (y por tanto el rad) sale del param `id=`.
    Para tokenizados (`share_folder`/`share_file`) el path NO está en la URL:
    hay que resolverlo con red (`expediente_fetcher.resolve_share_link`).
    """
    info = ExpedienteLinkInfo(url=url)
    parsed = urlparse(url)

    m = _TOKENIZED_RE.match(url)
    if m:
        info.kind = "share_folder" if m.group(1).lower() == "f" else "share_file"
        # path: /:f:/g/personal/<owner>/<token> → owner = segmento tras 'personal'
        parts = [p for p in parsed.path.split("/") if p]
        if "personal" in parts:
            idx = parts.index("personal")
            if idx + 1 < len(parts):
                info.owner = parts[idx + 1]
        info.juzgado_hint = _juzgado_hint(info.owner)
        return info

    if "onedrive.aspx" in url.lower():
        info.kind = "onedrive_view"
        qs = parse_qs(parsed.query)
        raw_id = (qs.get("id") or [""])[0]
        if raw_id:
            info.server_path = unquote(raw_id)
            info.owner = _owner_from_path(info.server_path)
            info.juzgado_hint = _juzgado_hint(info.owner)
            d = parse_server_path(info.server_path)
            info.rad23_url = d["rad23_url"]
            info.etapa = d["etapa"]
            info.instancia_hint = d["instancia_hint"]
            info.archivado = d["archivado"]
        return info

    if "guestaccess.aspx" in url.lower():
        info.kind = "guestaccess"
        return info

    return info


def es_link_judicial(url: str) -> bool:
    """True si el link es del tenant de la Rama Judicial (expediente cendoj).

    Los correos también traen links del tenant de la Gobernación
    (santandergov-my.sharepoint.com — Words internos de la SED): esos NO son
    expedientes y no entran a la cola del fetcher (hallazgo del backfill
    2026-06-12: 163/385 links eran internos)."""
    host = urlparse(url).netloc.lower()
    return "etbcsj" in host or "cendoj" in url.lower()


# ── Matching difuso del rad de URL ────────────────────────────────

def rad23_suffix_key(rad: str | None) -> str:
    """Clave difusa: posiciones [5:21] del rad normalizado (16 dígitos:
    entidad+especialidad+despacho+año+secuencia). Inmune a typos en el
    prefijo DANE de municipio (caso real 69432... por 68432...).
    Retorna '' si el rad no alcanza 21 dígitos."""
    d = normalize_rad23(rad)
    if len(d) < 21:
        return ""
    return d[5:21]
