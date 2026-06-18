"""Descarga de documentos del expediente desde la API CPNU de la Rama Judicial,
por número de radicado (Fase D).

A diferencia de `expediente_fetcher` (OneDrive del correo, tokens FedAuth que expiran
a 7 días / piden OTP), aquí basta el rad23: la API CPNU expone los documentos de cada
actuación y se descargan directo. Resuelve la deuda de links EXPIRADO/REQUIERE_ACCESO
y los casos sin demanda archivada.

Reusa la maquinaria probada:
- `rama_judicial_client` para los endpoints CPNU (DocumentosActuacion + Descarga).
- `expediente_fetcher._case_hashes` para dedup sha256 contra los docs ya archivados.
- `sync_service.sync_case_folder` para registrar+extraer+verificar lo descargado.

Archivado PLANO con prefijo `RJ_<fecha>_` (marcador de origen Rama Judicial).
Best-effort: una actuación/documento caído no rompe el resto. dry_run por defecto.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import Case
from backend.email.rad_utils import normalize_rad23, is_valid_rad23
from backend.services import rama_judicial_client as rj
from backend.services.expediente_fetcher import _case_hashes

logger = logging.getLogger("tutelas.rama_judicial_fetcher")

MAX_DOCS_PER_CASE = 200      # guard anti-expedientes absurdos
MAX_FILE_MB = 80


def _safe_name(fecha: str | None, nombre: str) -> str:
    f = re.sub(r"[^0-9]", "", (fecha or ""))[:8]
    nm = re.sub(r'[\\/:*?"<>|]', "_", nombre or "doc").strip()
    if not nm.lower().endswith((".pdf", ".docx", ".doc", ".xlsx")):
        nm += ".pdf"
    return f"RJ_{f}_{nm}" if f else f"RJ_{nm}"


def fetch_case_documents(db: Session, case_id: int, *, dry_run: bool = True,
                         throttle: float = 0.4, session=None) -> dict:
    """Descarga al folder del caso los documentos de las actuaciones CPNU del rad23.

    Returns dict: {estado, rad23, found, n_actuaciones_con_doc, descargados,
                   dedup, errors, archivos:[...]}.
    """
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return {"estado": "ERROR", "error": f"case {case_id} no existe"}
    rad = normalize_rad23(case.radicado_23_digitos)
    if not is_valid_rad23(rad):
        return {"estado": "RAD_INVALIDO", "rad23": rad}
    if not case.folder_path or not Path(case.folder_path).exists():
        return {"estado": "ERROR", "error": "folder del caso no existe", "rad23": rad}

    s = session or rj._new_session()
    proc = rj.consultar_proceso(rad, session=s, throttle=throttle)
    if not proc.encontrado:
        return {"estado": "NO_ENCONTRADO", "rad23": rad, "error": proc.error}

    folder = Path(case.folder_path)
    known = _case_hashes(db, case_id)
    rep = {"estado": "OK", "rad23": rad, "found": True,
           "n_actuaciones_con_doc": 0, "descargados": 0, "dedup": 0,
           "errors": 0, "archivos": []}

    con_doc = [a for a in proc.actuaciones if a.con_documentos and a.id_reg_actuacion]
    rep["n_actuaciones_con_doc"] = len(con_doc)

    for act in con_doc:
        if rep["descargados"] >= MAX_DOCS_PER_CASE:
            break
        try:
            docs = rj.documentos_actuacion(act.id_reg_actuacion, s)
        except Exception as e:
            rep["errors"] += 1
            logger.debug("DocumentosActuacion %s falló: %s", act.id_reg_actuacion, e)
            continue
        time.sleep(throttle)
        for d in docs:
            iddoc = d.get("idRegDocumento")
            nombre = d.get("nombre") or d.get("descripcion") or f"doc_{iddoc}"
            if not iddoc:
                continue
            if dry_run:
                rep["archivos"].append({"actuacion": act.actuacion, "fecha": act.fecha,
                                        "nombre": nombre, "idRegDocumento": iddoc})
                rep["descargados"] += 1
                continue
            try:
                data, fn, mime = rj.descargar_documento(iddoc, s)
            except Exception as e:
                rep["errors"] += 1
                logger.debug("Descarga doc %s falló: %s", iddoc, e)
                continue
            if not data or len(data) > MAX_FILE_MB * 1024 * 1024:
                rep["errors"] += 1
                continue
            h = hashlib.sha256(data).hexdigest()
            if h in known:
                rep["dedup"] += 1
                continue
            target = folder / _safe_name(act.fecha, fn or nombre)
            cnt = 1
            while target.exists():
                target = folder / _safe_name(act.fecha, f"{cnt}_{fn or nombre}")
                cnt += 1
            target.write_bytes(data)
            known.add(h)
            rep["descargados"] += 1
            rep["archivos"].append({"actuacion": act.actuacion, "fecha": act.fecha,
                                    "archivo": target.name, "bytes": len(data)})
            time.sleep(throttle)

    # registrar+extraer+verificar lo descargado (misma maquinaria del self-healing)
    if not dry_run and rep["descargados"]:
        from backend.services.sync_service import sync_case_folder
        rep["sync"] = sync_case_folder(db, case, source="rama_judicial_api")
    return rep
