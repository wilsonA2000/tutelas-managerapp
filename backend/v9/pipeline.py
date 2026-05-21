"""Orquestador v9. Pipeline lineal.

    extract_case(db, case_id, dry_run=True, use_llm=False) -> ExtractionResult

Pasos:
  1. field_extractor_pass.run() — extractores a nivel CASE (los 18 campos del cuadro;
     autoridad principal — corre primero, los demás solo rellenan huecos)
  2. doc_io.read_all()      — texto crudo de PDFs/DOCX
  3. regex_pass.run()        — campos restantes con patterns determinísticos
  4. catalog_resolve.run()   — abogado_canonical + dependencia_canonical
  5. excel_reconcile.run()   — fila CONTROL TUTELAS si existe (opcional)
  6. llm_gap_fill.run()      — UNA llamada multi-campo si quedan huecos (no-op con V9_DISABLE_LLM)
  7. persist.persist()       — escritura con source tracking (opcional)

NO usa: cognitive_complementary_ai, cognitive_fill, focused_field_extractors,
bayesian_assignment, live_consolidator, agent/orchestrator, narrative_builder.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.v9 import doc_io, regex_pass, catalog_resolve, excel_reconcile, llm_gap_fill, persist, field_extractor_pass, field_extractor
from backend.v9.types import ExtractedFields, ExtractionResult

logger = logging.getLogger("tutelas.v9.pipeline")


def _list_case_docs(db: Session, case_id: int) -> tuple[str, list[Path]]:
    """Devuelve (folder_name, [paths]) para el caso. Reusa la tabla Document.

    Si Document tiene rutas absolutas, las usa. Si no, intenta resolver
    contra el folder_path del case.
    """
    from backend.database.models import Case, Document

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return "", []

    folder = case.folder_name or f"case_{case_id}"
    docs = db.query(Document).filter(Document.case_id == case_id).all()
    paths = []
    for d in docs:
        if not d.file_path:
            continue
        p = Path(d.file_path)
        if p.exists():
            paths.append(p)
    return folder, paths


# Placeholders que la ingesta/monitor generan automáticamente cuando aún no se
# conoce el accionante. SOLO estos disparan el auto-rename del paso 9 — las notas
# humanas de revisión (ej. "[REVISAR — JUZGADO 68547 CASO DINY-WILMER]") se respetan.
_AUTO_PLACEHOLDER_RE = re.compile(r"SIN[_ ]ACCIONANTE|\[PENDIENTE|\[REVISAR_ACCIONANTE\]", re.I)


def _folder_is_auto_placeholder(folder_name: str) -> bool:
    """True si el folder es un placeholder de ingesta (renombrable automáticamente)."""
    return bool(_AUTO_PLACEHOLDER_RE.search(folder_name or ""))


def extract_case(
    db: Session,
    case_id: int,
    *,
    dry_run: bool = True,
    excel_row: Optional[dict] = None,
    use_llm: bool = False,
) -> ExtractionResult:
    """Ejecuta el pipeline v9 sobre 1 caso. Retorna ExtractionResult.

    Args:
        db: sesión SQLAlchemy
        case_id: id del caso a extraer
        dry_run: si True, no escribe a DB. Default True (seguro).
        excel_row: fila normalizada del CONTROL TUTELAS para este caso (opcional)
        use_llm: habilita los fallbacks LLM (derecho/asunto/pretensiones + gap-fill).
                 Default False — el preview es rápido (regex + extractores CASE-level);
                 ponlo True solo en CLI/batch (y con el llama-server libre).
    """
    from backend.database.models import Case

    t0 = time.perf_counter()
    timing: dict[str, int] = {}
    warnings: list[str] = []

    case = db.query(Case).filter(Case.id == case_id).first()
    folder_name, paths = _list_case_docs(db, case_id)
    fields = ExtractedFields()

    # 1. field_extractor_pass — extractores a nivel CASE (autoridad de los 18 campos del
    #    cuadro). Usa la DB (Document.extracted_text + .md), así que corre aunque no
    #    haya PDFs legibles en disco.
    if case is not None:
        t = time.perf_counter()
        try:
            field_extractor_pass.run(db, case, fields, use_llm=use_llm)
        except Exception as e:  # noqa: BLE001
            logger.exception("field_extractor_pass falló para case=%d", case_id)
            warnings.append(f"field_extractor_pass: {e}")
        timing["field_extractor"] = int((time.perf_counter() - t) * 1000)
    else:
        warnings.append("case no existe en DB")

    docs_ok = []
    docs_failed = 0
    if paths:
        # 2. doc_io
        t = time.perf_counter()
        docs = doc_io.read_all(paths)
        timing["doc_io"] = int((time.perf_counter() - t) * 1000)
        docs_ok = [d for d in docs if d.ok]
        docs_failed = len(docs) - len(docs_ok)

        # 3. regex_pass — rellena los campos doc-a-doc que el paso 1 no cubrió.
        #    Pasamos accionante/radicados desde DB explícitamente: si la carpeta
        #    está contaminada con docs prestados, el extractor de accionante puede
        #    escribir un valor erróneo en `fields` y envenenar el filtro de
        #    pertenencia para abogado_responsable. Usar `case.accionante` de DB es
        #    más fiable.
        from backend.v9.regex_pass import _rad_corto_from_23, _rad_corto_from_folder
        case_acc = getattr(case, "accionante", None) if case else None
        case_rads = {r for r in (
            getattr(case, "radicado_23_digitos", None) if case else None,
            getattr(case, "radicado_forest", None) if case else None,
            _rad_corto_from_23(getattr(case, "radicado_23_digitos", None) if case else None),
            _rad_corto_from_folder(folder_name),
        ) if r}
        t = time.perf_counter()
        regex_pass.run(
            docs_ok, fields, folder_name=folder_name,
            case_accionante=case_acc, case_radicados=case_rads,
        )
        timing["regex_pass"] = int((time.perf_counter() - t) * 1000)
    else:
        warnings.append("sin documentos legibles en disco")
        logger.warning("Case %d sin PDFs/DOCX legibles; solo extractores CASE-level + DB", case_id)

    # 4. catalog_resolve
    t = time.perf_counter()
    catalog_resolve.run(fields)
    timing["catalog_resolve"] = int((time.perf_counter() - t) * 1000)

    # 5. excel_reconcile (opcional)
    t = time.perf_counter()
    excel_reconcile.run(fields, excel_row)
    timing["excel_reconcile"] = int((time.perf_counter() - t) * 1000)

    # 6. llm_gap_fill (último recurso, 0 o 1 llamada; no-op si use_llm=False o V9_DISABLE_LLM)
    t = time.perf_counter()
    llm_calls = 0
    if use_llm:
        # Retrieval field-aware: solo las páginas relevantes a los campos que faltan
        # (demanda primeras N para asunto/pretensiones; incidente últimas N; etc.).
        # Reemplaza el head+tail genérico de los primeros 5 docs → más rápido y sin
        # contaminación. Ver backend/v9/field_context.py.
        from backend.v9 import field_context
        missing = [f for f in fields.missing_fields() if f in llm_gap_fill._LLM_FILLABLE]
        full_text = field_context.build_field_context(db, case, missing) if missing else ""
        if not full_text:  # fallback defensivo si no halló docs por tipo
            full_text = "\n\n".join(d.text for d in docs_ok[:3])[:5000]
        fields, llm_calls = llm_gap_fill.run(fields, full_text)
    timing["llm_gap_fill"] = int((time.perf_counter() - t) * 1000)

    # 7. persist (opcional según dry_run)
    t = time.perf_counter()
    persist_out = persist.persist(db, case_id, fields, dry_run=dry_run)
    timing["persist"] = int((time.perf_counter() - t) * 1000)

    # 8. Observaciones — resumen semántico (LLM, append-only fechado). Solo en apply
    #    con use_llm. Complementa los campos semánticos con una narrativa factual del
    #    estado del caso; NO pisa notas manuales ni resúmenes previos (idempotente).
    if use_llm and not dry_run:
        t = time.perf_counter()
        try:
            from datetime import datetime as _dt
            _case = db.query(Case).filter(Case.id == case_id).first()
            if _case is not None and not field_extractor.case_has_dated_observacion(_case):
                resumen = field_extractor.llm_summarize_case_state(db, _case)
                if resumen:
                    prev = (_case.observaciones or "").rstrip()
                    linea = f"[{_dt.now().strftime('%d/%m/%Y')}] {resumen}"
                    _case.observaciones = (prev + "\n" + linea) if prev else linea
                    db.commit()
                    llm_calls += 1
        except Exception as e:  # noqa: BLE001
            warnings.append(f"observaciones_summary: {e}")
        timing["obs_summary"] = int((time.perf_counter() - t) * 1000)

    # 9. Auto-rename de carpeta. La ingesta crea el caso con accionante="" → folder
    #    "<rad> SIN_ACCIONANTE". Una vez que la extracción pobló `accionante`, la
    #    carpeta debe seguir la convención "<rad_corto> <ACCIONANTE>". Idempotente:
    #    no toca carpetas ya limpias. Cierra el bug histórico de folders SIN_ACCIONANTE
    #    que nunca se renombraban tras descubrir el accionante.
    #
    #    GUARD: solo actuamos sobre placeholders generados por la ingesta/monitor
    #    (SIN_ACCIONANTE, [PENDIENTE, [REVISAR_ACCIONANTE]). NO tocamos folders con
    #    notas humanas de revisión (ej. "[REVISAR — JUZGADO 68547 CASO DINY-WILMER]"),
    #    aunque la heurística de needs_rename los marcaría como "sucios". El operador
    #    pone esas notas a propósito; renombrarlas perdería contexto.
    if not dry_run:
        t = time.perf_counter()
        try:
            from backend.cognition.folder_renamer import rename_folder_if_needed
            _case = db.query(Case).filter(Case.id == case_id).first()
            _fn = (_case.folder_name or "") if _case is not None else ""
            if _case is not None and _folder_is_auto_placeholder(_fn):
                ren = rename_folder_if_needed(db, _case)
                if ren.get("action") == "renamed":
                    folder_name = ren["new_name"]
                    warnings.append(f"folder_renamed: {ren['old_name']!r} → {ren['new_name']!r}")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"folder_rename: {e}")
        timing["folder_rename"] = int((time.perf_counter() - t) * 1000)

    timing["__total"] = int((time.perf_counter() - t0) * 1000)

    return ExtractionResult(
        case_id=case_id,
        folder_name=folder_name,
        fields=fields,
        docs_processed=len(docs_ok),
        docs_failed=docs_failed,
        timing_ms=timing,
        warnings=warnings,
        llm_calls=llm_calls,
    )
