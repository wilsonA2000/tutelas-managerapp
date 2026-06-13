"""Fetcher de expedientes judiciales desde OneDrive/SharePoint del juzgado.

PoC validado 2026-06-12 (ver memoria project_expedientes_sharepoint_poc):

1. GET al link tokenizado del correo (`/:f:/g/personal/...?e=...`) con cookie
   jar → SharePoint entrega cookie **FedAuth de invitado anónimo** (sin login,
   sin cuenta Microsoft) y redirige a `onedrive.aspx?id=<server_path>`.
2. Con esa cookie, la API REST clásica enumera y descarga:
     GET /personal/<owner>/_api/web/GetFolderByServerRelativeUrl('<path>')/Files
     GET .../GetFolderByServerRelativeUrl('<path>')/Folders   (recursión)
     GET .../GetFileByServerRelativeUrl('<path>/<name>')/$value (bytes)
3. Límite: el token solo abre la carpeta compartida (subir al padre → 403).

Diseño anti-sorpresas:
- Throttle entre requests (es el OneDrive de la Rama Judicial — cortesía).
- Dedupe por sha256 contra los docs YA archivados del caso (los adjuntos de
  correo no se duplican): se descarga, se hashea, y el byte-idéntico se descarta.
- Archivado PLANO en la carpeta del caso con prefijo `EXPJ_<etapa>_` (nada de
  zips ni subcarpetas en la raíz).
- Registro vía `sync_service.sync_case_folder` (la misma maquinaria del
  self-healing: clasifica, extrae texto y verifica pertenencia) + provenance
  `email_id` del correo que trajo el link.
- Estados por link: RESUELTO / DESCARGADO / SIN_NOVEDAD / REQUIERE_ACCESO /
  EXPIRADO / ERROR — un link caído jamás rompe nada, queda en cola de reporte.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from backend.core.time import utcnow
from backend.email.expediente_links import (
    ExpedienteLinkInfo,
    parse_expediente_link,
    parse_server_path,
)

logger = logging.getLogger("tutelas.expediente_fetcher")

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126 Safari/537.36")
_TIMEOUT = 30
MAX_FILE_MB = 80          # guard: no bajar archivos gigantes sin revisión
MAX_FILES_PER_LINK = 300  # guard: no recorrer carpetas absurdas
VALID_EXT = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".xlsx", ".md"}


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = _UA
    return s


def resolve_share_link(url: str, timeout: int = _TIMEOUT,
                       session: requests.Session | None = None) -> dict:
    """Resuelve un link de expediente: cookie FedAuth + server_path + rad/etapa.

    Retorna dict con `estado` ∈ {RESUELTO, REQUIERE_ACCESO, EXPIRADO, ERROR} y,
    si RESUELTO: session (autenticada), host, owner, server_path, rad23_url,
    etapa, instancia_hint, archivado.
    """
    info: ExpedienteLinkInfo = parse_expediente_link(url)
    s = session or _new_session()
    try:
        r = s.get(url, allow_redirects=True, timeout=timeout)
    except requests.RequestException as e:
        return {"estado": "ERROR", "error_detail": f"red: {str(e)[:120]}"}

    final = r.url or ""
    if "login.microsoftonline" in final or "login.live.com" in final:
        return {"estado": "REQUIERE_ACCESO",
                "error_detail": "el link exige autenticación (no es de invitado anónimo)"}
    if r.status_code in (403, 404, 410) or "Este vínculo ya no funciona" in (r.text or "")[:5000]:
        return {"estado": "EXPIRADO", "error_detail": f"HTTP {r.status_code}"}
    if r.status_code != 200:
        return {"estado": "ERROR", "error_detail": f"HTTP {r.status_code}"}

    parsed = urlparse(final)
    host = parsed.netloc
    # path desde id= del onedrive.aspx final (o del propio link si era vista web)
    final_info = parse_expediente_link(final)
    server_path = final_info.server_path or info.server_path
    if not server_path:
        return {"estado": "ERROR", "error_detail": "no pude derivar server_path del redirect"}

    d = parse_server_path(server_path)
    return {
        "estado": "RESUELTO",
        "session": s,
        "host": host,
        "owner": final_info.owner or info.owner,
        "server_path": server_path,
        "rad23_url": d["rad23_url"],
        "etapa": d["etapa"],
        "instancia_hint": d["instancia_hint"],
        "archivado": d["archivado"],
    }


def _api_base(host: str, server_path: str) -> str:
    """https://<host>/personal/<owner> — raíz del sitio personal para la API."""
    parts = [p for p in server_path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "personal":
        return f"https://{host}/personal/{parts[1]}"
    return f"https://{host}"


def list_folder(session: requests.Session, host: str, server_path: str,
                recursive: bool = True, throttle: float = 0.5,
                _depth: int = 0) -> list[dict]:
    """Enumera archivos de la carpeta compartida (Name/Length/Modified/ServerPath).

    Recursa subcarpetas DENTRO del scope compartido (máx 3 niveles, salta 'Forms').
    """
    if _depth > 3:
        return []
    base = _api_base(host, server_path)
    qpath = quote(server_path, safe="/")
    out: list[dict] = []

    r = session.get(
        f"{base}/_api/web/GetFolderByServerRelativeUrl('{qpath}')/Files"
        "?$select=Name,Length,TimeLastModified",
        headers={"Accept": "application/json;odata=nometadata"},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    for f in r.json().get("value", []):
        out.append({
            "name": f.get("Name", ""),
            "size": int(f.get("Length") or 0),
            "modified": f.get("TimeLastModified", ""),
            "server_path": f"{server_path}/{f.get('Name', '')}",
            "subfolder": "" if _depth == 0 else server_path.rsplit("/", 1)[-1],
        })

    if recursive:
        time.sleep(throttle)
        rf = session.get(
            f"{base}/_api/web/GetFolderByServerRelativeUrl('{qpath}')/Folders?$select=Name",
            headers={"Accept": "application/json;odata=nometadata"},
            timeout=_TIMEOUT,
        )
        if rf.status_code == 200:
            for sub in rf.json().get("value", []):
                name = sub.get("Name", "")
                if not name or name.lower() == "forms":
                    continue
                if len(out) >= MAX_FILES_PER_LINK:
                    break
                time.sleep(throttle)
                try:
                    out.extend(list_folder(session, host, f"{server_path}/{name}",
                                           recursive=True, throttle=throttle,
                                           _depth=_depth + 1))
                except requests.RequestException as e:
                    logger.warning("subcarpeta %s ilegible: %s", name, str(e)[:80])
    return out[:MAX_FILES_PER_LINK]


def download_file(session: requests.Session, host: str, file_server_path: str,
                  dest: Path, retries: int = 3) -> str:
    """Descarga un archivo al destino. Retorna sha256 hex. Lanza si agota retries."""
    base = _api_base(host, file_server_path)
    qpath = quote(file_server_path, safe="/")
    url = f"{base}/_api/web/GetFileByServerRelativeUrl('{qpath}')/$value"
    last: Exception | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(1.5 * (2 ** attempt))
        try:
            with session.get(url, stream=True, timeout=_TIMEOUT * 4) as r:
                r.raise_for_status()
                h = hashlib.sha256()
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        fh.write(chunk)
                        h.update(chunk)
                return h.hexdigest()
        except requests.RequestException as e:
            last = e
            dest.unlink(missing_ok=True)
    raise RuntimeError(f"descarga falló x{retries}: {str(last)[:120]}")


def _safe_filename(etapa: str, name: str) -> str:
    """`EXPJ_<etapa>_<name>` saneado (el prefijo EXPJ_ es el marcador de origen)."""
    et = re.sub(r"[^A-Za-z0-9]+", "", etapa or "")[:40]
    nm = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    return f"EXPJ_{et}_{nm}" if et else f"EXPJ_{nm}"


def _case_hashes(db, case_id: int) -> set[str]:
    """sha256 de los docs existentes del caso (file_hash o calculado del disco)."""
    from backend.database.models import Document
    hashes: set[str] = set()
    for doc in db.query(Document).filter(Document.case_id == case_id).all():
        if doc.file_hash and len(doc.file_hash) == 64:
            hashes.add(doc.file_hash)
        elif doc.file_path and os.path.exists(doc.file_path):
            try:
                with open(doc.file_path, "rb") as fh:
                    hashes.add(hashlib.sha256(fh.read()).hexdigest())
            except OSError:
                pass
    return hashes


def fetch_link(db, link, *, dry_run: bool = True, throttle: float = 1.0) -> dict:
    """Procesa UN ExpedienteLink: resolver → manifest → dedupe → descargar → registrar.

    Con dry_run=True solo resuelve y lista (actualiza rad/etapa/n_files del link,
    NO descarga). Retorna reporte dict. Nunca lanza: el error queda en el link.
    """
    from backend.database.models import Case, Document

    report = {"link_id": link.id, "case_id": link.case_id, "url": link.url,
              "estado": "", "manifest": [], "nuevos": [], "duplicados": 0,
              "omitidos": [], "error": ""}
    link.last_checked = utcnow()

    res = resolve_share_link(link.url)
    if res["estado"] != "RESUELTO":
        link.estado = res["estado"]
        link.error_detail = res.get("error_detail", "")[:300]
        report["estado"] = res["estado"]
        report["error"] = link.error_detail
        return report

    link.server_path = res["server_path"]
    link.rad23_url = res["rad23_url"] or link.rad23_url
    link.etapa = res["etapa"] or link.etapa
    link.instancia_hint = res["instancia_hint"] or link.instancia_hint
    link.archivado = bool(res["archivado"])
    link.owner = res["owner"] or link.owner

    session, host = res["session"], res["host"]
    try:
        manifest = list_folder(session, host, res["server_path"], throttle=throttle * 0.5)
    except requests.RequestException as e:
        link.estado = "ERROR"
        link.error_detail = f"manifest: {str(e)[:200]}"
        report["estado"] = "ERROR"
        report["error"] = link.error_detail
        return report

    link.n_files = len(manifest)
    link.estado = "RESUELTO"
    report["manifest"] = manifest
    report["estado"] = "RESUELTO"

    if dry_run or not link.case_id:
        return report

    case = db.query(Case).filter(Case.id == link.case_id).first()
    if not case or not case.folder_path or not Path(case.folder_path).is_dir():
        link.estado = "ERROR"
        link.error_detail = "caso sin carpeta en disco"
        report["estado"] = "ERROR"
        report["error"] = link.error_detail
        return report

    folder = Path(case.folder_path)
    known = _case_hashes(db, case.id)
    nuevos: list[str] = []
    for item in manifest:
        name = item["name"]
        ext = Path(name).suffix.lower()
        if ext not in VALID_EXT:
            report["omitidos"].append(f"{name} (extensión)")
            continue
        if item["size"] > MAX_FILE_MB * 1024 * 1024:
            report["omitidos"].append(f"{name} ({item['size'] >> 20}MB > {MAX_FILE_MB}MB)")
            continue
        etapa_eff = item.get("subfolder") or link.etapa
        dest = folder / _safe_filename(etapa_eff, name)
        if dest.exists():
            report["omitidos"].append(f"{name} (ya existe en carpeta)")
            continue
        time.sleep(throttle)
        try:
            sha = download_file(session, host, item["server_path"], dest)
        except RuntimeError as e:
            report["omitidos"].append(f"{name} ({e})")
            continue
        if sha in known:
            dest.unlink(missing_ok=True)   # byte-idéntico a un doc ya archivado
            report["duplicados"] += 1
            continue
        known.add(sha)
        nuevos.append(dest.name)

    report["nuevos"] = nuevos
    if nuevos:
        # registro con la maquinaria del self-healing (clasifica + texto + verifica)
        from backend.services.sync_service import sync_case_folder
        sync_case_folder(db, case, source="expediente_juzgado")
        # provenance: el correo que trajo el link + hash sha256
        for fname in nuevos:
            doc = db.query(Document).filter(
                Document.case_id == case.id, Document.filename == fname,
            ).first()
            if doc:
                if link.email_id and not doc.email_id:
                    doc.email_id = link.email_id
                fpath = folder / fname
                if not doc.file_hash and fpath.exists():
                    with open(fpath, "rb") as fh:
                        doc.file_hash = hashlib.sha256(fh.read()).hexdigest()
        link.n_descargados = (link.n_descargados or 0) + len(nuevos)
        link.estado = "DESCARGADO"
    else:
        link.estado = "SIN_NOVEDAD"
    report["estado"] = link.estado
    db.commit()
    return report


def fetch_case(db, case_id: int, *, dry_run: bool = True, throttle: float = 1.0) -> list[dict]:
    """Procesa todos los links pendientes/resueltos de un caso."""
    from backend.database.models import ExpedienteLink
    links = db.query(ExpedienteLink).filter(
        ExpedienteLink.case_id == case_id,
        ExpedienteLink.estado.in_(["PENDIENTE", "RESUELTO", "ERROR", "SIN_NOVEDAD", "DESCARGADO"]),
    ).all()
    reports = []
    for link in links:
        reports.append(fetch_link(db, link, dry_run=dry_run, throttle=throttle))
        db.commit()
    return reports
