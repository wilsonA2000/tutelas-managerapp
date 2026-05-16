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

# Anchor docs: documentos del juzgado que dan identidad. Por peso (mayor = más confiable)
# Cada anchor tiene: weight, fname_hints, content_hints
ANCHOR_DOCS = [
    {
        "type": "auto_avoca",
        "weight": 100,
        "fname": [
            'auto avoca', 'auto admisorio', 'autoavoca', 'autoadmisorio',
            'auto-avoca', 'auto-admisorio', 'admisor', 'admite tut', 'admitase',
            'auto que avoca', 'auto que admite', 'obedezcase', 'autoobedezcase',
            'autoavocaconocimiento', 'autoavocaconoc', 'autoadmite',
            'auto admite', 'autoadmiteacciontutela',
            '003autoavoca', '002autoadmite', '001autoavoca',
        ],
        "content": [
            'AVOCA EL CONOCIMIENTO', 'AVOCAR EL CONOCIMIENTO', 'AVOCA CONOCIMIENTO',
            'ADMITE LA TUTELA', 'ADMÍTASE LA ACCIÓN', 'ADMITASE LA ACCION',
            'ADMÍTASE LA TUTELA', 'ADMITASE LA TUTELA', 'ADMÍTESE LA',
            'AVOCAR CONOCIMIENTO',
        ],
        "max_pages": 8,
    },
    {
        "type": "auto_vincula",
        "weight": 80,
        "fname": ['auto vincula', 'autovincula', 'vincula y decreta', 'autovinculayde'],
        "content": ['VINCULASE A', 'VINCÚLASE A', 'VINCULAR A', 'VINCULA A LA', 'ORDÉNASE VINCULAR'],
        "max_pages": 10,
    },
    {
        "type": "sentencia_1ra",
        "weight": 70,
        "fname": ['fallo1ra', 'fallo1da', 'fallotutela', 'sentencia1ra', 'sentencia1d',
                  'fallodetutela', 'sentenciatutela', 'falloprimerainst',
                  'fallo de tutela', 'sentencia de tutela', 'fallo tutela'],
        "content": ['CONCEDE EL AMPARO', 'NIEGA EL AMPARO', 'AMPARA EL DERECHO',
                    'TUTELA EL DERECHO', 'NO TUTELA', 'IMPROCEDENTE LA ACCION',
                    'IMPROCEDENTE LA ACCIÓN', 'CONCEDE LA TUTELA', 'NIEGA LA TUTELA',
                    'RESUELVE: PRIMERO', 'PARTE RESOLUTIVA'],
        "max_pages": 50,
    },
    {
        "type": "sentencia_2da",
        "weight": 60,
        "fname": ['fallo2da', 'sentencia2da', 'sentenciasegunda', 'fallo2dainstancia',
                  'segundainstancia', 'fallosegundainstancia'],
        "content": ['CONFIRMA LA SENTENCIA', 'REVOCA LA SENTENCIA', 'MODIFICA LA SENTENCIA',
                    'CONFIRMA EL FALLO', 'REVOCA EL FALLO', 'CONFIRMA INTEGRAMENTE'],
        "max_pages": 60,
    },
    {
        "type": "auto_incidente",
        "weight": 50,
        "fname": ['autoabreincidente', 'autoincidente', 'aperturaincidente',
                  'incidentedesacato', 'autoadmiteincidente', 'autoabreincid'],
        "content": ['ÁBRASE INCIDENTE DE DESACATO', 'ABRASE INCIDENTE DE DESACATO',
                    'ADMITASE EL INCIDENTE', 'ADMÍTASE EL INCIDENTE',
                    'INCIDENTE DE DESACATO', 'AUTO QUE ABRE INCIDENTE'],
        "max_pages": 12,
    },
    {
        "type": "auto_requiere",
        "weight": 40,
        "fname": ['autorequiere', 'autoarequerimiento', 'autoque requiere',
                  'requierepreviarapertura', 'autorequierepreviarapertura'],
        "content": ['REQUIÉRASE A', 'REQUIERE A LA', 'REQUIÉRASE AL', 'PREVIO REQUERIMIENTO',
                    'PREVIA APERTURA DE INCIDENTE'],
        "max_pages": 12,
    },
]

# Para retro-compat:
AUTO_AVOCA_FNAME = ANCHOR_DOCS[0]["fname"]
AUTO_AVOCA_CONTENT = ANCHOR_DOCS[0]["content"]

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
    """LEGACY: solo Auto Avoca strict. Use classify_anchor en su lugar."""
    return classify_anchor(filename, text, total_pages)["type"] == "auto_avoca"

def classify_anchor(filename: str, text: str, total_pages: int) -> dict:
    """Clasifica un doc como anchor (con peso) o no.

    Returns: {"type": str|None, "weight": int}
    None = no es anchor.
    """
    fn = filename.lower()
    upper = text.upper() if text else ""
    pages = total_pages or 0

    best = {"type": None, "weight": 0}
    for anchor in ANCHOR_DOCS:
        if pages and pages > anchor["max_pages"]:
            continue
        has_fn = any(h in fn for h in anchor["fname"])
        has_content = any(h in upper for h in anchor["content"])
        if has_fn or has_content:
            # Boost si AMBOS aciertan
            score = anchor["weight"] + (10 if (has_fn and has_content) else 0)
            if score > best["weight"]:
                best = {"type": anchor["type"], "weight": score}
    return best

# Patrón para extraer accionante desde encabezado FOREST de DOCX_RESPUESTA
RE_FOREST_ACCIONANTE = re.compile(
    r'ACCIONANTE\s*[:\-]\s*\n*\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.,]{4,120}?)(?:\s*\n\s*ACCIONAD|\s*ACCIONAD|\s*ACCIONA)',
    re.I,
)

def extract_forest_accionante(text: str) -> str | None:
    """Para DOCX_RESPUESTA (FOREST): extrae ACCIONANTE del encabezado."""
    if not text:
        return None
    m = RE_FOREST_ACCIONANTE.search(text[:3000])
    if m:
        cand = ' '.join(m.group(1).split()).rstrip(',.').strip()
        if 5 <= len(cand) <= 150:
            return cand
    return None

def is_personero_folder(folder_name: str) -> bool:
    """Detecta carpetas asociadas a Personero/Personeria Municipal (alta sospecha de mezcla)."""
    upper = folder_name.upper()
    return ('PERSONERO' in upper or 'PERSONERIA' in upper or 'PERSONERÍA' in upper)

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

    # Pasada 1: extraer texto + clasificar como ANCHOR (con peso) o no
    docs_data = []
    for f in files:
        try:
            text, pages = get_doc_text(f)
            anchor = classify_anchor(f.name, text, pages)
            rad23s = extract_rad23s(text)
            # Accionante: del anchor (preferido) o desde FOREST si es DOCX_RESPUESTA
            accionante = None
            if anchor["type"]:
                accionante = extract_accionante(text)
            if not accionante and f.suffix.lower() in ('.docx', '.doc'):
                accionante = extract_forest_accionante(text)
            ajena = detect_ajena(text) if text else None
            docs_data.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "pages": pages,
                "anchor_type": anchor["type"],
                "anchor_weight": anchor["weight"],
                "is_avoca": (anchor["type"] == "auto_avoca"),  # retro-compat
                "rad23s": list(rad23s),
                "accionante_in_doc": accionante,
                "ajena_jurisdiction": ajena,
            })
        except Exception as e:
            docs_data.append({
                "filename": f.name,
                "error": str(e)[:120],
            })

    # Pasada 2: identificar el ANCHOR de mayor peso → ground truth
    anchors = [d for d in docs_data if d.get("anchor_type")]
    avocas_strict = [d for d in anchors if d["anchor_type"] == "auto_avoca"]
    result["ground_truth"]["auto_avoca_count"] = len(avocas_strict)
    result["ground_truth"]["anchors_count"] = len(anchors)
    result["ground_truth"]["anchor_types"] = sorted({d["anchor_type"] for d in anchors})

    # Si hay 0 anchors de cualquier tipo → NO_AVOCA real
    if not anchors:
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

    # Anchors con rad23: agrupar por rad23 distintos
    anchor_rad23s = set()
    for a in anchors:
        for r in a.get("rad23s", []):
            anchor_rad23s.add(r)

    # Si hay 2+ rad23 distintos en anchors → MIXED
    if len(anchor_rad23s) >= 2:
        result["status"] = "MIXED"
        result["issues"].append(f"Carpeta con {len(anchor_rad23s)} casos pegados (rad23 en anchors): {sorted(anchor_rad23s)}")
        result["ground_truth"]["rad23"] = "MULTIPLE"
        result["rad23s_seen"] = sorted(anchor_rad23s)
        result["docs"] = docs_data
        return result

    # Caso normal: 1 rad23 en anchors o varios anchors con mismo rad23
    # Elegir anchor primary: mayor peso, con accionante si posible
    anchors_sorted = sorted(anchors, key=lambda a: (-(a.get("anchor_weight", 0)), 0 if a.get("accionante_in_doc") else 1))
    primary_anchor = anchors_sorted[0]
    # Mejorar: si el primary no tiene accionante pero otro de mismo peso sí, preferirlo
    for a in anchors_sorted:
        if a.get("accionante_in_doc") and a.get("anchor_weight", 0) >= primary_anchor.get("anchor_weight", 0) - 10:
            primary_anchor = a
            break

    result["ground_truth"]["rad23"] = (primary_anchor.get("rad23s") or [None])[0]
    result["ground_truth"]["accionante"] = primary_anchor.get("accionante_in_doc")
    result["ground_truth"]["source_doc"] = primary_anchor["filename"]
    result["ground_truth"]["primary_anchor_type"] = primary_anchor.get("anchor_type")
    result["ground_truth"]["primary_anchor_weight"] = primary_anchor.get("anchor_weight")
    # Flag: si ground truth no viene de Auto Avoca strict, marcar
    if primary_anchor.get("anchor_type") != "auto_avoca":
        result["issues"].append(f"Ground truth NO viene de Auto Avoca; usado fallback {primary_anchor.get('anchor_type')}")
    # Personero flag
    if is_personero_folder(folder.name):
        result["personero_carpeta"] = True
        # Si aún tiene 1 solo rad23 pero es personero, sigue OK pero con flag
        result["issues"].append("Carpeta de Personero/Personería Municipal: revisar manualmente por mezcla potencial")

    # Si el avoca menciona jurisdicción ajena → AJENO
    if primary_anchor.get("ajena_jurisdiction"):
        result["status"] = "AJENO"
        result["issues"].append(f"Auto Avoca menciona jurisdicción ajena: {primary_anchor['ajena_jurisdiction']}")
        result["ajena_detected"] = primary_anchor["ajena_jurisdiction"]
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
