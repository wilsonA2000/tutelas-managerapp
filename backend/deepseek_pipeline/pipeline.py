"""Orquestador del pipeline experimental DeepSeek end-to-end."""
from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from sqlalchemy.orm import Session

from .types import PipelineResult
from .doc_classifier import classify_case_docs
from .field_extractor import extract_fields, ALL_FIELDS

log = logging.getLogger("tutelas.deepseek_pipeline.pipeline")

RESULTS_DIR = Path(__file__).resolve().parents[2] / "data" / "experiment" / "deepseek_pipeline"


def _load_cached(case_id: int) -> PipelineResult | None:
    p = RESULTS_DIR / f"{case_id}.json"
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text())
        return _dict_to_result(raw)
    except Exception:
        return None


def _save_result(result: PipelineResult) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    p = RESULTS_DIR / f"{result.case_id}.json"
    p.write_text(json.dumps(_result_to_dict(result), ensure_ascii=False, indent=2))


def _result_to_dict(r: PipelineResult) -> dict:
    from dataclasses import asdict
    return {
        "case_id": r.case_id,
        "folder_name": r.folder_name,
        "doc_classifications": [
            {"doc_id": dc.doc_id, "filename": dc.filename, "tipo": dc.tipo,
             "instancia": dc.instancia, "confianza": dc.confianza, "razon": dc.razon}
            for dc in r.doc_classifications
        ],
        "extraction": {
            "campos": {
                k: {"valor": v.valor, "fuente": v.fuente_doc, "confianza": v.confianza}
                for k, v in (r.extraction.campos.items() if r.extraction else {})
            },
            "docs_usados": r.extraction.docs_usados if r.extraction else [],
            "elapsed_ms": r.extraction.elapsed_ms if r.extraction else 0,
            "completitud": r.extraction.completitud() if r.extraction else 0,
            "error": r.extraction.error if r.extraction else None,
        } if r.extraction else None,
        "diff_vs_v9": r.diff_vs_v9,
        "elapsed_ms_total": r.elapsed_ms_total,
        "error": r.error,
    }


def _dict_to_result(d: dict) -> PipelineResult:
    from .types import DocClassification, FieldExtractionResult, FieldValue
    docs = [
        DocClassification(
            doc_id=dc["doc_id"], filename=dc["filename"],
            tipo=dc["tipo"], instancia=dc["instancia"],
            confianza=dc["confianza"], señales=[], razon=dc.get("razon", ""),
        )
        for dc in d.get("doc_classifications", [])
    ]
    ext_raw = d.get("extraction")
    extraction = None
    if ext_raw:
        campos = {
            k: FieldValue(
                valor=v.get("valor", ""),
                fuente_doc=v.get("fuente", ""),
                confianza=v.get("confianza", "baja"),
            )
            for k, v in ext_raw.get("campos", {}).items()
        }
        extraction = FieldExtractionResult(
            case_id=d["case_id"],
            folder_name=d["folder_name"],
            campos=campos,
            docs_usados=ext_raw.get("docs_usados", []),
            elapsed_ms=ext_raw.get("elapsed_ms", 0),
            error=ext_raw.get("error"),
        )
    return PipelineResult(
        case_id=d["case_id"],
        folder_name=d["folder_name"],
        doc_classifications=docs,
        extraction=extraction,
        diff_vs_v9=d.get("diff_vs_v9", []),
        elapsed_ms_total=d.get("elapsed_ms_total", 0),
        error=d.get("error"),
    )


def _build_diff(db: Session, case_id: int, deepseek_campos: dict) -> list[dict]:
    """Compara campos DeepSeek vs valores actuales de la DB."""
    from backend.database.models import Case
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return []

    diffs = []
    for campo in ALL_FIELDS:
        v9_val = str(getattr(case, campo, "") or "").strip()
        ds_val = deepseek_campos.get(campo, "")

        if v9_val == ds_val:
            semaforo = "IGUAL"
        elif not v9_val and ds_val:
            semaforo = "VERDE"       # DeepSeek llena un vacío
        elif v9_val and not ds_val:
            semaforo = "GRIS"        # DeepSeek no encontró nada, mantener v9
        else:
            semaforo = "AMARILLO"    # Ambos tienen valor, son distintos

        if semaforo != "IGUAL":
            diffs.append({
                "campo": campo,
                "semaforo": semaforo,
                "v9": v9_val,
                "deepseek": ds_val,
            })
    return diffs


def run_pipeline(
    db: Session,
    case_id: int,
    *,
    use_cached: bool = False,
    classify_docs: bool = True,
    extract: bool = True,
) -> PipelineResult:
    """
    Corre el pipeline DeepSeek completo para un caso.

    Fases:
    1. (opcional) Clasificar documentos con DeepSeek
    2. Extraer los 43 campos con DeepSeek
    3. Comparar con valores actuales de v9 en la DB

    use_cached: si True y existe resultado guardado, lo devuelve sin re-correr.
    classify_docs: si True, clasifica los docs con DeepSeek antes de extraer.
    extract: si True, extrae los 43 campos.
    """
    from backend.database.models import Case

    if use_cached:
        cached = _load_cached(case_id)
        if cached:
            log.info("case%d: usando resultado cacheado", case_id)
            return cached

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return PipelineResult(case_id=case_id, folder_name="", error="Caso no encontrado")

    folder_name = case.folder_name or f"case_{case_id}"
    t0 = time.perf_counter()

    result = PipelineResult(case_id=case_id, folder_name=folder_name)

    # ── Fase 1: Clasificación de documentos ──────────────────────────────
    classified_types: dict[int, str] | None = None
    if classify_docs:
        log.info("case%d: clasificando documentos...", case_id)
        result.doc_classifications = classify_case_docs(db, case_id)
        classified_types = {dc.doc_id: dc.tipo for dc in result.doc_classifications}
        log.info("case%d: %d documentos clasificados", case_id, len(result.doc_classifications))

    # ── Fase 2: Extracción de 43 campos ──────────────────────────────────
    if extract:
        log.info("case%d: extrayendo 43 campos con DeepSeek...", case_id)
        extraction = extract_fields(db, case_id, classified_types)
        result.extraction = extraction
        if extraction.error:
            log.warning("case%d: extracción con error: %s", case_id, extraction.error)
        else:
            log.info("case%d: %.1f%% completitud en %dms",
                     case_id, extraction.completitud(), extraction.elapsed_ms)

    # ── Fase 3: Diff vs v9 ────────────────────────────────────────────────
    if result.extraction and not result.extraction.error:
        deepseek_flat = result.extraction.to_flat_dict()
        result.diff_vs_v9 = _build_diff(db, case_id, deepseek_flat)
        n_verde = sum(1 for d in result.diff_vs_v9 if d["semaforo"] == "VERDE")
        n_amarillo = sum(1 for d in result.diff_vs_v9 if d["semaforo"] == "AMARILLO")
        log.info("case%d: diff vs v9 — %d VERDE, %d AMARILLO", case_id, n_verde, n_amarillo)

    result.elapsed_ms_total = int((time.perf_counter() - t0) * 1000)

    # Guardar resultado
    _save_result(result)
    log.info("case%d: pipeline completo en %dms", case_id, result.elapsed_ms_total)
    return result


def apply_to_db(db: Session, case_id: int, mode: str = "fill-empty") -> dict:
    """
    Aplica los resultados del pipeline DeepSeek a la DB de producción.

    mode:
      'fill-empty'    — solo llena campos vacíos (seguro)
      'all-non-manual'— llena vacíos + sobrescribe no-manuales (revisar antes)
    """
    from backend.database.models import Case
    import json as _json

    cached = _load_cached(case_id)
    if not cached or not cached.extraction:
        return {"error": "No hay resultado cacheado. Corre run_pipeline primero."}

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return {"error": f"Caso {case_id} no encontrado"}

    # Leer campos manuales protegidos
    try:
        manual_set = {
            k for k, v in
            _json.loads(case.field_confidences_json or "{}").get("v9_sources", {}).items()
            if v == "manual"
        }
    except Exception:
        manual_set = set()

    updated = []
    skipped_manual = []

    for diff in cached.diff_vs_v9:
        campo = diff["campo"]
        semaforo = diff["semaforo"]
        ds_val = diff["deepseek"]

        if campo in manual_set:
            skipped_manual.append(campo)
            continue

        if semaforo == "VERDE" or (mode == "all-non-manual" and semaforo == "AMARILLO"):
            if ds_val:
                setattr(case, campo, ds_val)
                # Actualizar source en field_confidences_json
                try:
                    conf = _json.loads(case.field_confidences_json or "{}")
                    conf.setdefault("v9_sources", {})[campo] = "deepseek"
                    case.field_confidences_json = _json.dumps(conf, ensure_ascii=False)
                except Exception:
                    pass
                updated.append(campo)

    db.commit()
    return {
        "case_id": case_id,
        "updated": updated,
        "updated_count": len(updated),
        "skipped_manual": skipped_manual,
        "mode": mode,
    }
