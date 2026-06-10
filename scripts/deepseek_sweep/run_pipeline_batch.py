#!/usr/bin/env python3
"""
Batch runner del pipeline DeepSeek experimental — 50 casos.
LEE de producción, NUNCA escribe a data/tutelas.db.
Resultados: data/experiment/deepseek_pipeline/<case_id>.json
Excel:       data/experiment/deepseek_pipeline_reporte_50.xlsx

Uso:
    python3 scripts/deepseek_sweep/run_pipeline_batch.py
    python3 scripts/deepseek_sweep/run_pipeline_batch.py --only-excel   # solo genera Excel
"""
from __future__ import annotations
import argparse, json, logging, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── env ANTES de imports backend ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
_ENV = ROOT / "data" / "experiment" / ".env.deepseek_sweep"
if _ENV.exists():
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "data/experiment/deepseek_pipeline/batch.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("batch")

import sqlalchemy
from sqlalchemy.orm import sessionmaker
from backend.deepseek_pipeline.pipeline import run_pipeline, RESULTS_DIR, _load_cached
from backend.deepseek_pipeline.field_extractor import ALL_FIELDS

PROD_DB   = ROOT / "data" / "tutelas.db"
EXCEL_OUT = ROOT / "data" / "experiment" / "deepseek_pipeline_reporte_50.xlsx"

# 50 casos más ricos (>=3 docs con texto) — preseleccionados
CASE_IDS_50 = [
    9,92,298,198,60,72,501,61,59,216,280,85,93,307,198,
    73,74,75,76,77,78,79,80,81,82,83,84,86,87,88,89,90,91,
    94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110
]
# dedup y limitar a 50
CASE_IDS_50 = list(dict.fromkeys(CASE_IDS_50))[:50]


def process_one(engine, case_id: int) -> dict:
    """Procesa un caso. Usa caché si ya existe."""
    cached = _load_cached(case_id)
    if cached:
        return {"case_id": case_id, "status": "cached",
                "folder": cached.folder_name,
                "completitud": cached.extraction.completitud() if cached.extraction else 0,
                "verde": sum(1 for d in cached.diff_vs_v9 if d["semaforo"]=="VERDE"),
                "amarillo": sum(1 for d in cached.diff_vs_v9 if d["semaforo"]=="AMARILLO")}

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()
    try:
        t0 = time.perf_counter()
        result = run_pipeline(db, case_id, classify_docs=True, extract=True)
        elapsed = time.perf_counter() - t0
        if result.error:
            return {"case_id": case_id, "status": "error", "error": result.error}
        return {
            "case_id": case_id, "status": "ok",
            "folder": result.folder_name,
            "completitud": result.extraction.completitud() if result.extraction else 0,
            "verde": sum(1 for d in result.diff_vs_v9 if d["semaforo"]=="VERDE"),
            "amarillo": sum(1 for d in result.diff_vs_v9 if d["semaforo"]=="AMARILLO"),
            "elapsed_s": round(elapsed, 1),
        }
    except Exception as exc:
        log.exception("case%d falló", case_id)
        return {"case_id": case_id, "status": "error", "error": str(exc)[:200]}
    finally:
        db.close()


def build_excel(case_ids: list[int]) -> None:
    """Genera el Excel de comparación DeepSeek vs v9."""
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    # Colores
    GREEN  = PatternFill("solid", fgColor="C6EFCE")
    YELLOW = PatternFill("solid", fgColor="FFEB9C")
    GRAY   = PatternFill("solid", fgColor="F2F2F2")
    HEADER = PatternFill("solid", fgColor="1F3864")
    VIOLET = PatternFill("solid", fgColor="7030A0")

    wb = openpyxl.Workbook()

    # ── Hoja 1: RESUMEN ──────────────────────────────────────────────────────
    ws_res = wb.active
    ws_res.title = "RESUMEN"

    results = []
    for cid in case_ids:
        r = _load_cached(cid)
        if r:
            results.append(r)

    headers_res = ["Case ID","Carpeta","Completitud DS","Completitud v9",
                   "VERDE (fills)","AMARILLO (difs)","Docs clasificados","Tiempo (s)","Estado"]
    for col, h in enumerate(headers_res, 1):
        cell = ws_res.cell(1, col, h)
        cell.fill = HEADER
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    # Obtener completitud v9 de la DB
    conn_r = __import__("sqlite3").connect(str(PROD_DB))
    conn_r.row_factory = __import__("sqlite3").Row

    for row_i, r in enumerate(results, 2):
        cid = r.case_id
        cur = conn_r.execute(
            f"SELECT {', '.join(ALL_FIELDS)} FROM cases WHERE id=?", (cid,)
        )
        db_row = cur.fetchone()
        v9_filled = sum(1 for f in ALL_FIELDS if db_row and db_row[f]) if db_row else 0
        v9_comp = round(100 * v9_filled / len(ALL_FIELDS), 1)

        n_verde   = sum(1 for d in r.diff_vs_v9 if d["semaforo"]=="VERDE")
        n_amarillo= sum(1 for d in r.diff_vs_v9 if d["semaforo"]=="AMARILLO")
        n_docs    = len(r.doc_classifications)
        comp_ds   = r.extraction.completitud() if r.extraction else 0
        elapsed   = r.elapsed_ms_total / 1000

        row_vals = [cid, r.folder_name, f"{comp_ds}%", f"{v9_comp}%",
                    n_verde, n_amarillo, n_docs, round(elapsed,1),
                    "✓ OK" if not r.error else f"⚠ {r.error[:40]}"]
        for col, v in enumerate(row_vals, 1):
            cell = ws_res.cell(row_i, col, v)
            if col == 5 and isinstance(v, int) and v > 0:
                cell.fill = GREEN
            elif col == 6 and isinstance(v, int) and v > 0:
                cell.fill = YELLOW

    ws_res.column_dimensions["B"].width = 42
    for i, w in enumerate([8,22,14,14,10,12,14,10,20], 1):
        ws_res.column_dimensions[get_column_letter(i)].width = w
    conn_r.close()

    # ── Hoja 2: DIFF COMPLETO ────────────────────────────────────────────────
    ws_diff = wb.create_sheet("DIFF_COMPLETO")
    headers_diff = ["Case ID","Carpeta","Campo","Semáforo","Valor v9 actual","DeepSeek propone","Fuente DS","Confianza DS"]
    for col, h in enumerate(headers_diff, 1):
        cell = ws_diff.cell(1, col, h)
        cell.fill = VIOLET
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.alignment = Alignment(horizontal="center")

    row_i = 2
    for r in results:
        if not r.extraction:
            continue
        campos_ds = r.extraction.campos
        for d in r.diff_vs_v9:
            campo = d["campo"]
            fv = campos_ds.get(campo)
            sem = d["semaforo"]
            fill = GREEN if sem=="VERDE" else YELLOW if sem=="AMARILLO" else GRAY
            row_vals = [
                r.case_id, r.folder_name[:40], campo, sem,
                str(d["v9"])[:100], str(d["deepseek"])[:150],
                fv.fuente_doc if fv else "", fv.confianza if fv else "",
            ]
            for col, v in enumerate(row_vals, 1):
                cell = ws_diff.cell(row_i, col, v)
                cell.fill = fill
                cell.alignment = Alignment(wrap_text=True)
            row_i += 1

    for i, w in enumerate([8,35,28,12,60,60,18,10], 1):
        ws_diff.column_dimensions[get_column_letter(i)].width = w
    ws_diff.row_dimensions[1].height = 30

    # ── Hoja 3: CLASIFICACION DE DOCS ────────────────────────────────────────
    ws_cls = wb.create_sheet("CLASIFICACION_DOCS")
    headers_cls = ["Case ID","Carpeta","Doc ID","Filename","Tipo DeepSeek","Tipo v9 actual","Match","Confianza","Razón"]
    for col, h in enumerate(headers_cls, 1):
        cell = ws_cls.cell(1, col, h)
        cell.fill = PatternFill("solid", fgColor="203864")
        cell.font = Font(bold=True, color="FFFFFF", size=10)

    # Mapa canónico → tipos v9
    CANON_TO_V9 = {
        "DEMANDA_TUTELA":["DEMANDA_TUTELA","DEMANDA"],
        "AUTO_ADMISORIO":["AUTO_ADMISORIO","PDF_AUTO_ADMISORIO"],
        "SENTENCIA_1RA":["SENTENCIA_1RA","PDF_SENTENCIA"],
        "RESPUESTA_SED":["RESPUESTA","DOCX_RESPUESTA","RESPUESTA_SED"],
        "SENTENCIA_2DA":["SENTENCIA_2DA","AUTO_2DA"],
        "IMPUGNACION":["IMPUGNACION","PDF_IMPUGNACION","DOCX_IMPUGNACION"],
        "INCIDENTE_DESACATO":["INCIDENTE_DESACATO","PDF_INCIDENTE","DOCX_DESACATO"],
        "AUTO_INCIDENTE":["AUTO_INCIDENTE"],
        "EMAIL_MD":["EMAIL_MD","EMAIL_JUDICIAL","EMAIL_INTERNO","EMAIL_OUTLOOK_PDF"],
        "NOTIFICACION":["NOTIFICACION","NOTIFICACION_FALLO"],
        "OFICIO_CUMPLIMIENTO":["OFICIO_CUMPLIMIENTO"],
        "AUTO_VINCULA":["AUTO_VINCULA"],
        "ACTA_REPARTO":["ACTA_REPARTO"],
        "ANEXO":["ANEXO_DEMANDA","ANEXO_PRUEBA","MEMORIAL_ACCIONANTE"],
        "INSUMO_SED":["INSUMO_CONTESTACION","INSUMO_PROCEDIMIENTO","OFICIO_INTERNO_SED"],
        "AUTO_CONCEDE_IMPUGNACION":["AUTO_CONCEDE_IMPUGNACION"],
    }

    conn2 = __import__("sqlite3").connect(str(PROD_DB))
    conn2.row_factory = __import__("sqlite3").Row
    row_i = 2
    for r in results:
        for dc in r.doc_classifications:
            cur2 = conn2.execute("SELECT doc_type FROM documents WHERE id=?", (dc.doc_id,))
            db_doc = cur2.fetchone()
            v9_tipo = db_doc["doc_type"] if db_doc else "?"
            # ¿coincide?
            accepted = CANON_TO_V9.get(dc.tipo, [dc.tipo])
            match = "✓" if v9_tipo in accepted else "✗"
            fill = GREEN if match=="✓" else PatternFill("solid", fgColor="FFB3B3")
            row_vals = [r.case_id, r.folder_name[:35], dc.doc_id, dc.filename[:50],
                        dc.tipo, v9_tipo, match, dc.confianza, dc.razon[:80]]
            for col, v in enumerate(row_vals, 1):
                cell = ws_cls.cell(row_i, col, v)
                cell.fill = fill
            row_i += 1
    conn2.close()
    for i, w in enumerate([8,30,8,45,25,25,7,10,60], 1):
        ws_cls.column_dimensions[get_column_letter(i)].width = w

    # ── Hoja 4: VERDE para aplicar ────────────────────────────────────────────
    ws_verde = wb.create_sheet("VERDE_PARA_APLICAR")
    headers_v = ["Case ID","Carpeta","Campo","DeepSeek propone","Fuente","Confianza","Aplicar?"]
    for col, h in enumerate(headers_v, 1):
        cell = ws_verde.cell(1, col, h)
        cell.fill = PatternFill("solid", fgColor="375623")
        cell.font = Font(bold=True, color="FFFFFF", size=10)

    row_i = 2
    for r in results:
        if not r.extraction:
            continue
        campos_ds = r.extraction.campos
        for d in [x for x in r.diff_vs_v9 if x["semaforo"]=="VERDE"]:
            campo = d["campo"]
            fv = campos_ds.get(campo)
            row_vals = [
                r.case_id, r.folder_name[:40], campo,
                str(d["deepseek"])[:150],
                fv.fuente_doc if fv else "", fv.confianza if fv else "",
                "SÍ" if (fv and fv.confianza in ("alta","media")) else "REVISAR",
            ]
            for col, v in enumerate(row_vals, 1):
                cell = ws_verde.cell(row_i, col, v)
                conf_ok = fv and fv.confianza in ("alta","media")
                cell.fill = PatternFill("solid", fgColor="C6EFCE") if conf_ok else PatternFill("solid", fgColor="FFEB9C")
            row_i += 1

    for i, w in enumerate([8,40,28,60,18,10,10], 1):
        ws_verde.column_dimensions[get_column_letter(i)].width = w

    wb.save(EXCEL_OUT)
    log.info("Excel guardado: %s", EXCEL_OUT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-excel", action="store_true", help="Solo generar Excel desde resultados existentes")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.only_excel:
        log.info("Generando Excel desde resultados existentes...")
        build_excel(CASE_IDS_50)
        print(f"\nExcel: {EXCEL_OUT}")
        return

    engine = sqlalchemy.create_engine(
        f"sqlite:///{PROD_DB}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    pending = [cid for cid in CASE_IDS_50 if not (RESULTS_DIR / f"{cid}.json").exists()]
    cached_count = len(CASE_IDS_50) - len(pending)
    log.info("50 casos seleccionados | ya en caché: %d | a procesar: %d | workers: %d",
             cached_count, len(pending), args.workers)

    stats = {"ok": 0, "cached": 0, "error": 0, "verde": 0, "amarillo": 0}
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_one, engine, cid): cid for cid in pending}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            cid = r["case_id"]
            if r["status"] == "ok":
                stats["ok"] += 1
                stats["verde"] += r.get("verde", 0)
                stats["amarillo"] += r.get("amarillo", 0)
                log.info("[%d/%d] c%d OK — %.1f%% | VERDE:%d AMARILLO:%d | %ss",
                         i, len(pending), cid,
                         r.get("completitud",0), r.get("verde",0), r.get("amarillo",0), r.get("elapsed_s","?"))
            elif r["status"] == "cached":
                stats["cached"] += 1
                log.info("[%d/%d] c%d caché", i, len(pending), cid)
            else:
                stats["error"] += 1
                log.warning("[%d/%d] c%d ERROR: %s", i, len(pending), cid, r.get("error",""))

    elapsed = time.perf_counter() - t0
    log.info("═══ BATCH COMPLETO ═══")
    log.info("  OK:%d  Caché:%d  Errores:%d", stats["ok"], stats["cached"], stats["error"])
    log.info("  VERDE total:%d  AMARILLO total:%d", stats["verde"], stats["amarillo"])
    log.info("  Tiempo: %.1fs", elapsed)

    log.info("Generando Excel...")
    build_excel(CASE_IDS_50)
    print(f"\n{'='*60}")
    print(f"Excel listo: {EXCEL_OUT}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
