"""
Audit no-destructivo de carpetas de tutelas.
Detecta cross-contamination según las reglas R1-R5 del proceso jurídico tutelar.

NO mueve, NO borra, NO modifica DB. Solo lee y reporta.

Outputs:
  /tmp/audit_carpetas_report.json  — datos completos
  /tmp/audit_carpetas_report.xlsx  — vista para humano

Uso:
  .venv/bin/python3 scripts/audit_carpetas_canonical.py [--limit N] [--folders "name1,name2"]
"""
from __future__ import annotations

import re
import json
import sys
import argparse
import traceback
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

BASE_DIR = Path("/home/wilsonarguello/iuris-data/tutelas-files")

# ─── Regex de identidad ─────────────────────────────────────────────

# Rad23: 23 dígitos consecutivos, posiblemente con separadores - / . espacio
RE_RAD23 = re.compile(r'(?<!\d)((?:\d[\s./\-]?){22}\d)(?!\d)')

# Patrones para extraer accionante desde Auto Avoca / texto legal
RE_ACCIONANTE = [
    re.compile(r'ACCIONANTE\s*[:\-]\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]+?)(?:\n|ACCIONAD|CONTRA|VINCULAD|ACCIÓN|RAD)', re.I),
    re.compile(r'(?:tutela|acci[óo]n)\s+(?:presentada|instaurada|interpuesta)\s+por(?:\s+(?:el|la|los|las|el\s+se[ñn]or|la\s+se[ñn]ora))?\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]{6,80}?)(?:[,.\n]|\s+act|\s+en\s+contra|\s+contra)', re.I),
    re.compile(r'TUTELA\s+INSTAURADA\s+POR\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.]+?)(?:\n|\s+CONTRA|\s+EN\s+CONTRA)', re.I),
]

# Indicadores Auto Avoca/Admisorio en filename y contenido
AUTO_AVOCA_FNAME = [
    'auto avoca', 'auto admisorio', 'autoavoca', 'autoadmisorio', 'auto-avoca',
    'auto-admisorio', 'avoca', 'admisor', 'admite tut', 'admitase',
    'auto que avoca', 'auto que admite', 'obedezcase', 'autoobedezcase',
    'autoavocaconocimiento', 'autoavocaconoc',
]
AUTO_AVOCA_CONTENT = [
    'AVOCA EL CONOCIMIENTO', 'AVOCAR EL CONOCIMIENTO', 'AVOCA CONOCIMIENTO',
    'ADMITE LA TUTELA', 'ADMÍTASE LA ACCIÓN', 'ADMITASE LA ACCION',
    'ADMÍTASE LA TUTELA', 'ADMITASE LA TUTELA',
]

# Jurisdicciones AJENAS (no Santander → no son del sistema de Wilson)
AJENAS = [
    'NORTE DE SANTANDER', 'CÚCUTA', 'CUCUTA', 'PAMPLONA', 'OCAÑA', 'OCANA',
    'TIBÚ', 'TIBU', 'VILLA DEL ROSARIO',
    # otras jurisdicciones colombianas (no son Santander)
    'ANTIOQUIA', 'BOGOTÁ', 'BOGOTA', 'CUNDINAMARCA', 'VALLE', 'CAUCA',
    'BOLÍVAR', 'BOLIVAR', 'ATLÁNTICO', 'ATLANTICO', 'NARIÑO', 'NARINO',
    'TOLIMA', 'BOYACÁ', 'BOYACA', 'HUILA', 'CALDAS', 'RISARALDA', 'QUINDÍO',
    'QUINDIO', 'META', 'CASANARE', 'CESAR', 'GUAJIRA', 'MAGDALENA', 'CÓRDOBA',
    'CORDOBA', 'SUCRE',
]

# ─── Helpers ────────────────────────────────────────────────────────

def normalize_rad23(raw: str) -> str | None:
    """Devuelve los 23 dígitos limpios o None si no son 23."""
    digits = re.sub(r'\D', '', raw)
    return digits if len(digits) == 23 else None

def extract_rad23s(text: str) -> set[str]:
    """Encuentra todos los rad23 en el texto."""
    found = set()
    if not text:
        return found
    for m in RE_RAD23.finditer(text):
        norm = normalize_rad23(m.group(1))
        if norm:
            found.add(norm)
    return found

def extract_accionante(text: str) -> str | None:
    """Intenta extraer el accionante desde un Auto Avoca."""
    if not text:
        return None
    # Considerar primeros ~3000 chars (Autos Avoca son cortos)
    snippet = text[:5000]
    for pattern in RE_ACCIONANTE:
        m = pattern.search(snippet)
        if m:
            cand = m.group(1).strip().rstrip(',.').strip()
            # Limpiar líneas múltiples
            cand = ' '.join(cand.split())
            # Validar: nombre razonable (2-90 chars, no toda mayúscula garbage)
            if 5 <= len(cand) <= 120:
                return cand
    return None

def extract_text_pdf(path: Path, max_pages: int = 5) -> tuple[str, int]:
    """Devuelve (texto, num_pages_leidas). Solo primeras max_pages."""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            n = min(len(pdf.pages), max_pages)
            text = ""
            for i in range(n):
                try:
                    t = pdf.pages[i].extract_text() or ""
                    text += t + "\n"
                except Exception:
                    pass
            return text, len(pdf.pages)
    except Exception:
        return "", 0

def extract_text_docx(path: Path) -> str:
    try:
        from docx import Document as DocxDoc
        d = DocxDoc(path)
        return "\n".join(p.text for p in d.paragraphs if p.text.strip())[:8000]
    except Exception:
        return ""

def extract_text_md(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='ignore')[:8000]
    except Exception:
        return ""

def get_doc_text(path: Path) -> tuple[str, int]:
    """Devuelve (texto, total_pages) para PDF o (texto, 1) para otros."""
    suf = path.suffix.lower()
    if suf == '.pdf':
        return extract_text_pdf(path)
    elif suf in ('.docx', '.doc'):
        return extract_text_docx(path), 1
    elif suf in ('.md', '.txt'):
        return extract_text_md(path), 1
    return "", 0

def is_auto_avoca(filename: str, text: str, total_pages: int) -> bool:
    """Heurística combinada: filename, contenido, pageas."""
    fn = filename.lower()
    has_fn_hint = any(h in fn for h in AUTO_AVOCA_FNAME)
    has_content_hint = any(h in text.upper() for h in AUTO_AVOCA_CONTENT) if text else False
    short_doc = total_pages == 0 or total_pages <= 6
    # Filename strong + short
    if has_fn_hint and short_doc:
        return True
    # Content strong (incluso si filename no es claro)
    if has_content_hint and short_doc:
        return True
    return False

def detect_ajena(text: str) -> str | None:
    """Detecta si el doc menciona jurisdicción no-Santander."""
    if not text:
        return None
    upper = text[:4000].upper()
    # Santander tiene precedencia: si menciona "DEPARTAMENTO DE SANTANDER" o juzgado de Bucaramanga es Santander
    if 'BUCARAMANGA' in upper or 'DEPARTAMENTO DE SANTANDER' in upper or 'GOBERNACIÓN DE SANTANDER' in upper or 'GOBERNACION DE SANTANDER' in upper:
        # Pero Norte de Santander también dice "SANTANDER"... chequear primero N. de S.
        if 'NORTE DE SANTANDER' in upper:
            return 'NORTE DE SANTANDER'
        return None
    for ajena in AJENAS:
        if ajena in upper:
            return ajena
    return None

# ─── Análisis por carpeta ───────────────────────────────────────────

def analyze_folder(folder: Path) -> dict:
    """Analiza una carpeta de caso. Devuelve dict con resultado."""
    result = {
        "folder": folder.name,
        "n_docs": 0,
        "ground_truth": {"rad23": None, "accionante": None, "source_doc": None, "auto_avoca_count": 0},
        "rad23s_seen": [],   # todos los rad23 encontrados en cualquier doc
        "ajena_detected": None,
        "docs": [],          # por doc: filename, classification, rad23s, accionante
        "issues": [],
        "status": "UNKNOWN",  # OK | REVIEW | RED | MIXED | NO_AVOCA | AJENO
    }
    if not folder.is_dir():
        result["status"] = "NOT_A_DIR"
        return result

    files = [f for f in folder.iterdir() if f.is_file()]
    result["n_docs"] = len(files)

    # Pasada 1: extraer texto de cada doc + clasificar como avoca o no
    docs_data = []
    for f in files:
        try:
            text, pages = get_doc_text(f)
            avoca = is_auto_avoca(f.name, text, pages)
            rad23s = extract_rad23s(text)
            accionante = extract_accionante(text) if avoca else None
            ajena = detect_ajena(text) if text else None
            docs_data.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "pages": pages,
                "is_avoca": avoca,
                "rad23s": list(rad23s),
                "accionante_in_doc": accionante,
                "ajena_jurisdiction": ajena,
            })
        except Exception as e:
            docs_data.append({
                "filename": f.name,
                "error": str(e)[:120],
            })

    # Pasada 2: identificar Auto Avoca canónico
    avocas = [d for d in docs_data if d.get("is_avoca")]
    result["ground_truth"]["auto_avoca_count"] = len(avocas)

    # Si hay 0 avocas → NO_AVOCA
    if not avocas:
        result["status"] = "NO_AVOCA"
        result["issues"].append("No se identificó Auto Avoca/Admisorio en la carpeta")
        # Aún así, juntar rad23s vistos
        all_rad23s = set()
        for d in docs_data:
            for r in d.get("rad23s", []):
                all_rad23s.add(r)
        result["rad23s_seen"] = sorted(all_rad23s)
        result["docs"] = docs_data
        return result

    # Si hay 2+ avocas con rad23s distintos → MIXED (carpeta tiene 2+ casos)
    avoca_rad23s = set()
    for a in avocas:
        for r in a.get("rad23s", []):
            avoca_rad23s.add(r)

    if len(avoca_rad23s) >= 2:
        result["status"] = "MIXED"
        result["issues"].append(f"Carpeta con {len(avoca_rad23s)} Autos Avoca con rad23 distintos: {sorted(avoca_rad23s)}")
        result["ground_truth"]["rad23"] = "MULTIPLE"
        result["rad23s_seen"] = sorted(avoca_rad23s)
        result["docs"] = docs_data
        return result

    # Caso normal: 1 avoca o múltiples avocas con mismo rad23
    primary_avoca = avocas[0]
    # Si hay varios, preferir el con texto + accionante
    for a in avocas:
        if a.get("accionante_in_doc"):
            primary_avoca = a
            break

    result["ground_truth"]["rad23"] = (primary_avoca.get("rad23s") or [None])[0]
    result["ground_truth"]["accionante"] = primary_avoca.get("accionante_in_doc")
    result["ground_truth"]["source_doc"] = primary_avoca["filename"]

    # Si el avoca menciona jurisdicción ajena → AJENO
    if primary_avoca.get("ajena_jurisdiction"):
        result["status"] = "AJENO"
        result["issues"].append(f"Auto Avoca menciona jurisdicción ajena: {primary_avoca['ajena_jurisdiction']}")
        result["ajena_detected"] = primary_avoca["ajena_jurisdiction"]
        result["docs"] = docs_data
        return result

    # Pasada 3: clasificar cada doc contra ground truth
    truth_rad23 = result["ground_truth"]["rad23"]
    truth_accionante = (result["ground_truth"]["accionante"] or "").upper().split()
    truth_apellidos = set(w for w in truth_accionante if len(w) >= 4)  # heurística para match nombre

    intrusos = 0
    huerfanos = 0
    propios = 0
    ajenos_docs = 0
    for d in docs_data:
        if "error" in d:
            d["classification"] = "ERROR_LECTURA"
            continue
        rads = set(d.get("rad23s") or [])
        rads_distintos = rads - {truth_rad23} if truth_rad23 else rads
        if d.get("ajena_jurisdiction"):
            d["classification"] = "AJENO"
            ajenos_docs += 1
        elif truth_rad23 and truth_rad23 in rads:
            d["classification"] = "PROPIO_RAD23"
            propios += 1
        elif rads_distintos and not (truth_rad23 in rads):
            # Tiene rad23 pero distinto del canónico → INTRUSO
            d["classification"] = "INTRUSO_RAD23"
            d["intruso_rad23"] = sorted(rads_distintos)
            intrusos += 1
        elif d.get("accionante_in_doc") and truth_apellidos:
            # Sin rad23 pero con accionante → comparar
            doc_acc = (d["accionante_in_doc"] or "").upper().split()
            doc_apellidos = set(w for w in doc_acc if len(w) >= 4)
            if doc_apellidos & truth_apellidos:
                d["classification"] = "PROPIO_ACCIONANTE"
                propios += 1
            else:
                d["classification"] = "INTRUSO_ACCIONANTE"
                intrusos += 1
        else:
            d["classification"] = "HUERFANO"
            huerfanos += 1

    result["docs"] = docs_data
    result["rad23s_seen"] = sorted({r for d in docs_data for r in (d.get("rad23s") or [])})

    summary = {
        "propios": propios,
        "intrusos": intrusos,
        "huerfanos": huerfanos,
        "ajenos": ajenos_docs,
    }
    result["summary"] = summary

    # Status final
    if intrusos > 0:
        result["status"] = "RED"
        result["issues"].append(f"{intrusos} doc(s) con rad23 o accionante de OTRO caso")
    elif ajenos_docs > 0:
        result["status"] = "AJENO_PARCIAL"
        result["issues"].append(f"{ajenos_docs} doc(s) de jurisdicción ajena")
    elif huerfanos > result["n_docs"] * 0.5:
        result["status"] = "REVIEW"
        result["issues"].append(f"{huerfanos}/{result['n_docs']} docs huérfanos (sin rad23 ni accionante reconocible)")
    else:
        result["status"] = "OK"

    return result

# ─── XLSX writer ────────────────────────────────────────────────────

def write_xlsx(report: list[dict], out_path: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    # Hoja 1: Resumen
    ws = wb.active
    ws.title = "Resumen"
    ws.append(["Total carpetas", len(report)])
    by_status = defaultdict(int)
    for r in report:
        by_status[r["status"]] += 1
    ws.append([])
    ws.append(["Status", "Cantidad"])
    for k, v in sorted(by_status.items(), key=lambda x: -x[1]):
        ws.append([k, v])

    # Hoja 2: Por carpeta
    ws2 = wb.create_sheet("Por carpeta")
    ws2.append(["Status", "Carpeta", "n_docs", "Auto Avoca count", "rad23 truth", "Accionante truth",
                "Propios", "Intrusos", "Huérfanos", "Ajenos", "Issues"])
    fill_red = PatternFill("solid", fgColor="FEE2E2")
    fill_yellow = PatternFill("solid", fgColor="FEF3C7")
    fill_green = PatternFill("solid", fgColor="DCFCE7")
    for r in sorted(report, key=lambda x: (x["status"] not in ("RED", "MIXED", "AJENO"), x["folder"])):
        s = r["summary"] if "summary" in r else {}
        row = [
            r["status"], r["folder"], r["n_docs"],
            r["ground_truth"]["auto_avoca_count"],
            r["ground_truth"]["rad23"] or "",
            r["ground_truth"]["accionante"] or "",
            s.get("propios", ""), s.get("intrusos", ""),
            s.get("huerfanos", ""), s.get("ajenos", ""),
            "; ".join(r.get("issues", []))[:200],
        ]
        ws2.append(row)
        last = ws2.max_row
        if r["status"] in ("RED", "MIXED"):
            for c in range(1, len(row)+1):
                ws2.cell(last, c).fill = fill_red
        elif r["status"] in ("AJENO", "AJENO_PARCIAL", "REVIEW", "NO_AVOCA"):
            for c in range(1, len(row)+1):
                ws2.cell(last, c).fill = fill_yellow
        elif r["status"] == "OK":
            for c in range(1, len(row)+1):
                ws2.cell(last, c).fill = fill_green

    # Hoja 3: Docs intrusos
    ws3 = wb.create_sheet("Docs intrusos")
    ws3.append(["Carpeta", "Doc filename", "Classification", "rad23 doc", "Accionante doc"])
    for r in report:
        for d in r.get("docs", []):
            cls = d.get("classification", "")
            if cls in ("INTRUSO_RAD23", "INTRUSO_ACCIONANTE", "AJENO"):
                ws3.append([
                    r["folder"], d.get("filename", ""), cls,
                    ", ".join(d.get("rad23s") or [])[:50],
                    d.get("accionante_in_doc") or "",
                ])

    # Hoja 4: Carpetas mezcla (MIXED)
    ws4 = wb.create_sheet("Carpetas mezcla")
    ws4.append(["Carpeta", "rad23s detectados", "Issues"])
    for r in report:
        if r["status"] == "MIXED":
            ws4.append([r["folder"], ", ".join(r.get("rad23s_seen", [])), "; ".join(r.get("issues", []))])

    wb.save(out_path)

# ─── Main ───────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Límite de carpetas a procesar (0 = todas)")
    ap.add_argument("--folders", type=str, default="", help="Lista CSV de carpetas específicas")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out-json", type=str, default="/tmp/audit_carpetas_report.json")
    ap.add_argument("--out-xlsx", type=str, default="/tmp/audit_carpetas_report.xlsx")
    args = ap.parse_args()

    if not BASE_DIR.exists():
        print(f"ERROR: BASE_DIR no existe: {BASE_DIR}")
        sys.exit(1)

    if args.folders:
        targets = [BASE_DIR / name for name in args.folders.split(",")]
    else:
        targets = sorted([f for f in BASE_DIR.iterdir() if f.is_dir()])
        if args.limit:
            targets = targets[:args.limit]

    print(f"Auditando {len(targets)} carpetas con {args.workers} workers...")

    report = []
    if args.workers > 1 and len(targets) > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(analyze_folder, t): t for t in targets}
            for i, fut in enumerate(as_completed(futs), 1):
                t = futs[fut]
                try:
                    r = fut.result()
                    report.append(r)
                except Exception as e:
                    print(f"  ERROR en {t.name}: {e}")
                    report.append({"folder": t.name, "status": "ERROR", "error": str(e)})
                if i % 10 == 0 or i == len(targets):
                    print(f"  procesadas {i}/{len(targets)}")
    else:
        for i, t in enumerate(targets, 1):
            r = analyze_folder(t)
            report.append(r)
            print(f"  [{i}/{len(targets)}] {r['status']:8s} {t.name[:55]}")

    # Resumen
    by_status = defaultdict(int)
    for r in report:
        by_status[r["status"]] += 1
    print("\n=== Resumen ===")
    for k, v in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {k:18s}: {v}")

    # Save JSON
    Path(args.out_json).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nJSON: {args.out_json}")

    # Save XLSX
    write_xlsx(report, Path(args.out_xlsx))
    print(f"XLSX: {args.out_xlsx}")


if __name__ == "__main__":
    main()
