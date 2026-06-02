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
import os
import re
import time
from datetime import datetime, timezone
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
    _resolve_acum: bool = True,
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

    # 0. reclasificación de docs (doc_librarian) — autocura etiquetas legacy de docs
    #    añadidos por Sync/upload (el ingest de Gmail ya las pone ricas). DEBE ir antes
    #    del field_extractor_pass, que filtra por doc_type (SENTENCIA_1RA/DEMANDA_TUTELA/…).
    if case is not None:
        t = time.perf_counter()
        try:
            from backend.v9 import doc_librarian
            reclassified = doc_librarian.reclassify_legacy_docs(db, case)
            if reclassified:
                db.flush()  # para que field_extractor_pass vea los nuevos doc_type
                logger.info("extract_case case=%d: %d docs reclasificados por doc_librarian",
                            case_id, len(reclassified))
        except Exception as e:  # noqa: BLE001
            logger.warning("reclasificación doc_librarian falló case=%d: %s", case_id, e)
        timing["reclassify_docs"] = int((time.perf_counter() - t) * 1000)

    # 0.5 PRE-PASS de acumulación procesal. DEBE ir ANTES de extraer campos: si este
    #     caso es el "bucket" de una acumulación (varias tutelas/accionantes juntadas
    #     por el juez), separa los documentos a su caso correcto AHORA, para que la
    #     extracción de abajo lea solo los docs de ESTE caso (cada acumulado termina
    #     con sus propios datos). Crea el hermano faltante (carpeta + sentencia), vincula
    #     RECTOR/ACUMULADO y pone la nota en observaciones. Idempotente; flag
    #     ACUMULACION_AUTO; envuelto en try/except (nunca rompe la extracción). El guard
    #     _resolve_acum evita recursión cuando re-extraemos los hermanos (paso 10).
    _acum_plan = None
    if (case is not None and not dry_run and _resolve_acum
            and os.getenv("ACUMULACION_AUTO", "false").lower() == "true"):
        t = time.perf_counter()
        try:
            from backend.email.acumulacion_resolver import resolve_acumulacion
            _acum_plan = resolve_acumulacion(db, case, apply=True, move_files=True)
            if _acum_plan.is_acumulacion:
                # los docs pudieron moverse a hermanos → recomputar lista de este caso
                folder_name, paths = _list_case_docs(db, case_id)
                _s = getattr(_acum_plan, "_summary", {}) or {}
                if _s.get("created") or _s.get("routed"):
                    warnings.append(
                        f"acumulacion(pre): rector={_acum_plan.rector_rad} "
                        f"creados={len(_s.get('created', []))} "
                        f"docs_enrutados={len(_s.get('routed', []))}")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"acumulacion(pre): {e}")
        timing["acumulacion_pre"] = int((time.perf_counter() - t) * 1000)

    # 0.6 GUARD ANTI-CONFLACIÓN — una DEMANDA con accionante AJENO (misfileada de otra
    #     tutela por rad corto compartido) envenena la extracción de derecho/asunto/
    #     accionante. Se detecta por accionante y se rutea a su caso correcto cuando el
    #     match es inequívoco (si no, flag). DEBE ir antes del field_extractor_pass para
    #     que extraiga solo los docs propios. Flag CONFLATION_AUTO; solo en --apply.
    if (case is not None and not dry_run
            and os.getenv("CONFLATION_AUTO", "true").lower() != "false"):
        t = time.perf_counter()
        try:
            from backend.v9.conflation_guard import route_foreign_demandas
            _cf = route_foreign_demandas(db, case, apply=True)
            if _cf.get("moved"):
                db.flush()
                folder_name, paths = _list_case_docs(db, case_id)  # recomputar: docs salieron
                warnings.append(f"conflacion: {len(_cf['moved'])} demanda(s) ajena(s) ruteada(s) "
                                + ", ".join(f"{m['filename'][:30]}→c{m['to_case']}" for m in _cf['moved']))
            if _cf.get("flagged"):
                warnings.append(f"conflacion: {len(_cf['flagged'])} demanda(s) ajena(s) sin destino único (revisar)")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"conflacion(guard): {e}")
        timing["conflation_guard"] = int((time.perf_counter() - t) * 1000)

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
        # 2. doc_io — con caché por file_hash: reusa Document.extracted_text si el
        #    hash del archivo coincide → no re-OCR-ea escaneados ya extraídos. Tras
        #    extraer fresco, persiste texto+hash (solo si no es dry_run) para que la
        #    próxima corrida pegue caché. Cierra el costo de re-OCR en re-extracciones.
        from backend.database.models import Document as _Doc
        _rows = db.query(_Doc).filter(_Doc.case_id == case_id).all()
        # Kill-switch: V9_DOC_CACHE=false fuerza re-extracción fresca de disco.
        _use_cache = os.getenv("V9_DOC_CACHE", "true").lower() != "false"
        _cache = ({r.file_path: (r.file_hash or "", r.extracted_text or "", r.extraction_method or "")
                   for r in _rows if r.file_path} if _use_cache else None)
        _row_by_path = {r.file_path: r for r in _rows if r.file_path}
        t = time.perf_counter()
        docs = doc_io.read_all(paths, cache=_cache)
        timing["doc_io"] = int((time.perf_counter() - t) * 1000)
        docs_ok = [d for d in docs if d.ok]
        docs_failed = len(docs) - len(docs_ok)
        timing["doc_io_cache_hits"] = sum(1 for d in docs if d.from_cache)

        # Persistir texto recién extraído (no de caché) para acelerar la próxima corrida.
        if not dry_run:
            _persisted = 0
            for d in docs:
                if d.from_cache or not (d.text and d.text.strip()):
                    continue
                row = _row_by_path.get(d.path)
                if row is None:
                    continue
                row.extracted_text = d.text
                row.extraction_method = d.method
                row.extraction_date = datetime.now(timezone.utc)
                if d.file_hash:
                    row.file_hash = d.file_hash
                _persisted += 1
            if _persisted:
                db.commit()
                timing["doc_cache_persist"] = _persisted

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
        # Fallback 3B: si field_context no encontró anclas, armar doc_texts por tipo
        # desde extracted_text en DB y dejar que build_context_for_fields elija los
        # más relevantes para los campos faltantes (mejor que los 3 primeros genéricos).
        doc_texts: "dict[str, str] | None" = None
        if not full_text and docs_ok:
            doc_texts = {}
            # DocText no lleva doc_type; se resuelve desde la fila de DB por path.
            _rbp = locals().get("_row_by_path", {})
            for d in docs_ok:
                _row = _rbp.get(d.path)
                dtype = ((getattr(_row, "doc_type", None) if _row else None) or "PDF_OTRO").upper()
                snippet = (d.text or "")[:4000]
                if snippet:
                    doc_texts[dtype] = (doc_texts.get(dtype, "") + "\n---\n" + snippet).lstrip("\n-")
        fields, llm_calls = llm_gap_fill.run(fields, full_text, doc_texts=doc_texts)
    timing["llm_gap_fill"] = int((time.perf_counter() - t) * 1000)

    # 6.5 post_validator (reglas F1-F16) — valida y corrige antes de persistir.
    # Conecta las reglas del validador al pipeline v9 (antes solo corría desde
    # orchestrator.py). Usa fields.values como dict mutable; aplica correcciones.
    t = time.perf_counter()
    try:
        from backend.extraction.post_validator import validate_extraction
        case_obj = db.query(Case).filter(Case.id == case_id).first()
        if case_obj:
            pv_corrected, pv_warnings = validate_extraction(case_obj, dict(fields.values))
            for campo, val in pv_corrected.items():
                if campo in fields.values and val != fields.values.get(campo):
                    fields.values[campo] = val or ""
            warnings.extend(pv_warnings)
    except Exception as _pv_exc:
        logger.warning("post_validator falló (no-fatal): %s", str(_pv_exc)[:200])
    timing["post_validator"] = int((time.perf_counter() - t) * 1000)

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

    # 10. Cierre de acumulación (tras extraer este caso):
    #     (a) si el pre-pass (0.5) resolvió un bucket, re-extrae cada hermano para que
    #         llene SU cuadro desde SU sentencia. Determinista (use_llm=False) y con
    #         _resolve_acum=False para no recursar. persist solo rellena vacíos → no pisa.
    #     (b) refresca la nota "[ACUMULACIÓN CONJUNTA]" en observaciones de ESTE caso
    #         (cubre el caso de extraer un acumulado directamente, sin bucket).
    if not dry_run and os.getenv("ACUMULACION_AUTO", "false").lower() == "true":
        t = time.perf_counter()
        try:
            from backend.email.acumulacion_resolver import apply_acumulacion_note
            # (a) cascada a hermanos
            if _acum_plan is not None and getattr(_acum_plan, "is_acumulacion", False):
                sibling_ids = {it.case_id for it in _acum_plan.items
                               if it.case_id and it.case_id != case_id}
                for sib_id in sorted(sibling_ids):
                    try:
                        extract_case(db, sib_id, dry_run=False, use_llm=False,
                                     _resolve_acum=False)
                    except Exception as e:  # noqa: BLE001
                        warnings.append(f"acumulacion(cascada #{sib_id}): {e}")
                if sibling_ids:
                    warnings.append(f"acumulacion: hermanos re-extraídos {sorted(sibling_ids)}")
            # (b) nota en este caso
            _case = db.query(Case).filter(Case.id == case_id).first()
            if _case is not None and apply_acumulacion_note(db, _case):
                db.commit()
        except Exception as e:  # noqa: BLE001
            warnings.append(f"acumulacion(post): {e}")
        timing["acumulacion_post"] = int((time.perf_counter() - t) * 1000)

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
