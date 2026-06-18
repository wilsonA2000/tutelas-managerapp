"""Cliente de la API pública CPNU (Consulta de Procesos Nacional Unificada) de la
Rama Judicial de Colombia.

Con SOLO el número de radicado de 23 dígitos trae datos 100% reales del juzgado:
despacho, departamento, fecha de radicación, tipo/clase de proceso, ponente, partes
(demandante/demandado) y la línea de ACTUACIONES procesales (cada evento con fecha).
A diferencia del `expediente_fetcher` (OneDrive del correo, tokens que expiran), esta
API solo necesita el radicado → fuente estable de verdad de campo.

Diseño (verificado contra la API en vivo el 2026-06-18, ver spike A0):
- API REST pública en el puerto 448, SIN autenticación; basta `User-Agent`.
- Reusa el patrón de red de `expediente_fetcher`: Session con UA, timeout, throttle,
  retry con backoff exponencial en 403/429.
- PURO: solo red + parseo/normalización. CERO acceso a la DB (lo hace el caller).
- Best-effort: si Detalle o Actuaciones fallan, el proceso igual se devuelve con lo
  que haya (no rompe).

Flujo `consultar_proceso(rad23)`:
  1. /Procesos/Consulta/NumeroRadicacion?numero=<rad23>  → idProceso + resumen
  2. /Proceso/Detalle/{idProceso}                        → tipo/clase/ponente/cod
  3. /Proceso/Actuaciones/{idProceso}?pagina=N           → timeline (paginado)
Descarga de documentos (Fase D): documentos_actuacion() + descargar_documento().
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from backend.email.rad_utils import normalize_rad23, is_valid_rad23

logger = logging.getLogger("tutelas.rama_judicial")

BASE_URL = "https://consultaprocesos.ramajudicial.gov.co:448/api/v2"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126 Safari/537.36")
_TIMEOUT = 30
_MAX_RETRIES = 4
_ACTUACIONES_MAX_PAGES = 10   # guard: no recorrer paginaciones absurdas


# ── modelos normalizados ─────────────────────────────────────────────────────

@dataclass
class Actuacion:
    fecha: Optional[str]          # DD/MM/YYYY
    actuacion: Optional[str]      # "Sentencia de Primera Instancia de Tutela"
    anotacion: Optional[str]
    con_documentos: bool = False
    id_reg_actuacion: Optional[int] = None


@dataclass
class ProcesoCPNU:
    rad23: str
    id_proceso: Optional[int] = None
    juzgado: Optional[str] = None          # despacho oficial
    departamento: Optional[str] = None
    fecha_radicacion: Optional[str] = None  # DD/MM/YYYY
    tipo: Optional[str] = None
    clase: Optional[str] = None            # "Tutelas"
    subclase: Optional[str] = None
    ponente: Optional[str] = None
    cod_despacho: Optional[str] = None
    demandante: Optional[str] = None
    demandado: Optional[str] = None
    sujetos_raw: Optional[str] = None
    es_privado: bool = False
    fecha_ultima_actuacion: Optional[str] = None
    actuaciones: list[Actuacion] = field(default_factory=list)
    encontrado: bool = False               # ¿la API devolvió un proceso?
    error: Optional[str] = None            # detalle si algo falló

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["actuaciones"] = [a.__dict__ for a in self.actuaciones]
        return d


# ── red ──────────────────────────────────────────────────────────────────────

def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept": "application/json"})
    return s


def _get(session: requests.Session, path: str, *, params: dict | None = None,
         timeout: int = _TIMEOUT, retries: int = _MAX_RETRIES) -> requests.Response:
    """GET con retry+backoff exponencial en 403/429 (rate-limit de CPNU)."""
    url = f"{BASE_URL}{path}"
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            r = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            last_exc = e
            time.sleep(2.5 * (attempt + 1))
            continue
        if r.status_code in (403, 429) and attempt < retries:
            wait = 2.5 * (attempt + 1)
            logger.warning("CPNU %s HTTP %d → backoff %.1fs (intento %d)",
                           path, r.status_code, wait, attempt + 1)
            time.sleep(wait)
            continue
        return r
    raise requests.RequestException(f"CPNU sin respuesta tras {retries} reintentos: {last_exc}")


# ── normalización ─────────────────────────────────────────────────────────────

def _iso_to_ddmmyyyy(iso: Optional[str]) -> Optional[str]:
    """'2026-03-18T00:00:00' → '18/03/2026'. El cuadro usa DD/MM/YYYY."""
    if not iso:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso))
    if not m:
        return None
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"


# Roles tolerantes para parsear `sujetosProcesales`
_RE_DEMANDANTE = re.compile(
    r"(?:Demandante|Accionante|Convocante|Ejecutante|Solicitante|Tutelante)\s*:\s*"
    r"([^|]+)", re.I)
_RE_DEMANDADO = re.compile(
    r"(?:Demandado|Accionado|Convocado|Ejecutado|Procesado|Vinculado)\s*:\s*"
    r"([^|]+)", re.I)


def _parse_sujetos(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not raw:
        return None, None

    def _first(rx) -> Optional[str]:
        m = rx.search(raw)
        if not m:
            return None
        return re.sub(r"\s+", " ", m.group(1)).strip() or None

    return _first(_RE_DEMANDANTE), _first(_RE_DEMANDADO)


# ── endpoints ────────────────────────────────────────────────────────────────

def consulta_radicado(rad23: str, session: requests.Session) -> Optional[dict]:
    """/Procesos/Consulta/NumeroRadicacion → primer proceso del radicado, o None."""
    rn = normalize_rad23(rad23)
    r = _get(session, "/Procesos/Consulta/NumeroRadicacion",
             params={"numero": rn, "SoloActivos": "false", "pagina": 1})
    r.raise_for_status()
    procs = (r.json() or {}).get("procesos") or []
    return procs[0] if procs else None


def detalle(id_proceso: int, session: requests.Session) -> dict:
    """/Proceso/Detalle/{id} → tipo/clase/ponente/cod. Best-effort ({} si falla)."""
    try:
        r = _get(session, f"/Proceso/Detalle/{id_proceso}")
        r.raise_for_status()
        return r.json() or {}
    except Exception as e:
        logger.debug("CPNU Detalle %s falló: %s", id_proceso, e)
        return {}


def actuaciones(id_proceso: int, session: requests.Session,
                max_pages: int = _ACTUACIONES_MAX_PAGES) -> list[dict]:
    """/Proceso/Actuaciones/{id} → timeline completo (pagina todas). Best-effort."""
    out: list[dict] = []
    for pagina in range(1, max_pages + 1):
        try:
            r = _get(session, f"/Proceso/Actuaciones/{id_proceso}",
                     params={"pagina": pagina})
            r.raise_for_status()
            body = r.json() or {}
        except Exception as e:
            logger.debug("CPNU Actuaciones %s p%d falló: %s", id_proceso, pagina, e)
            break
        page = body.get("actuaciones") or []
        out.extend(page)
        pag = body.get("paginacion") or {}
        if pagina >= (pag.get("cantidadPaginas") or 1):
            break
        time.sleep(0.4)
    return out


def documentos_actuacion(id_reg_actuacion: int, session: requests.Session) -> list[dict]:
    """/Proceso/DocumentosActuacion/{idReg} → [{idRegDocumento, nombre}]."""
    r = _get(session, f"/Proceso/DocumentosActuacion/{id_reg_actuacion}")
    r.raise_for_status()
    return r.json() or []


def descargar_documento(id_reg_documento: int,
                        session: requests.Session) -> tuple[bytes, Optional[str], Optional[str]]:
    """/Descarga/Documento/{idReg} → (bytes, filename, content_type)."""
    r = _get(session, f"/Descarga/Documento/{id_reg_documento}", timeout=60)
    r.raise_for_status()
    cd = r.headers.get("content-disposition", "") or ""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    filename = m.group(1).strip() if m else None
    return r.content, filename, r.headers.get("content-type")


# ── orquestación ──────────────────────────────────────────────────────────────

def consultar_proceso(rad23: str, *, session: requests.Session | None = None,
                      throttle: float = 0.4, con_actuaciones: bool = True) -> ProcesoCPNU:
    """Consulta CPNU por radicado y devuelve un `ProcesoCPNU` normalizado.

    No lanza: si el radicado es inválido / no está en CPNU / la red falla, devuelve
    un ProcesoCPNU con `encontrado=False` y `error` poblado (el caller decide)."""
    rn = normalize_rad23(rad23)
    res = ProcesoCPNU(rad23=rn)
    if not is_valid_rad23(rn):
        res.error = "rad23 inválido (<18 díg)"
        return res
    s = session or _new_session()
    try:
        proc = consulta_radicado(rn, s)
    except Exception as e:
        res.error = f"consulta: {str(e)[:150]}"
        return res
    if not proc:
        res.error = "no_encontrado"
        return res

    res.encontrado = True
    res.id_proceso = proc.get("idProceso")
    res.juzgado = (proc.get("despacho") or "").strip() or None
    res.departamento = (proc.get("departamento") or "").strip() or None
    res.fecha_radicacion = _iso_to_ddmmyyyy(proc.get("fechaProceso"))
    res.fecha_ultima_actuacion = _iso_to_ddmmyyyy(proc.get("fechaUltimaActuacion"))
    res.es_privado = bool(proc.get("esPrivado"))
    res.sujetos_raw = proc.get("sujetosProcesales")
    res.demandante, res.demandado = _parse_sujetos(res.sujetos_raw)

    if res.id_proceso:
        time.sleep(throttle)
        det = detalle(res.id_proceso, s)
        res.tipo = (det.get("tipoProceso") or "").strip() or None
        res.clase = (det.get("claseProceso") or "").strip() or None
        res.subclase = (det.get("subclaseProceso") or "").strip() or None
        res.ponente = (det.get("ponente") or "").strip() or None
        res.cod_despacho = (det.get("codDespachoCompleto") or "").strip() or None
        # el despacho de Detalle suele venir más limpio que el de Consulta
        if det.get("despacho"):
            res.juzgado = det["despacho"].strip()

        if con_actuaciones:
            time.sleep(throttle)
            for a in actuaciones(res.id_proceso, s):
                res.actuaciones.append(Actuacion(
                    fecha=_iso_to_ddmmyyyy(a.get("fechaActuacion")),
                    actuacion=(a.get("actuacion") or "").strip() or None,
                    anotacion=(a.get("anotacion") or "").strip() or None,
                    con_documentos=bool(a.get("conDocumentos")),
                    id_reg_actuacion=a.get("idRegActuacion"),
                ))
    return res
