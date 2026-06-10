"""Extrae pretensiones VERBATIM de la DEMANDA leyendo el PDF/DOCX COMPLETO de disco
(sin el cap legacy de 30k). Localiza el encabezado PRETENSIONES/PETICIONES/SUPLICAS y
corta hasta la siguiente seccion (FUNDAMENTOS/DERECHO/COMPETENCIA/PRUEBAS/ANEXOS/...).
NO escribe: emite JSON con la propuesta por caso para revision. Uso: [ids...] o lee TARGET.
"""
import sys, os, re, json
os.environ.setdefault("V9_DISABLE_LLM", "true")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case, Document

TARGET = [1,2,5,17,20,23,27,29,35,41,44,45,53,55,59,60,61,62,63,64,66,67,68,70,71,72,74,77,78,79,80,84,88,90,92,93,98,99,102,103,104,106,107,112,113,117,118,119,121,122,123,126,127,133,134,135,136,141,142,144,145,146,148,151,154,155,160,161,163,166,171,175,177,179,183,187,191,193,198,203,207,209,210,211,212,214,215,216,217,218,219,220,224,229,231,233,240,242,249,252,255,260,264,265,266,267,269,270,272,274,275,277,279,280,282,283,284,289,290,291,292,295,297,298,300,307,308,309,311,318,319,320,323,329,336,337,338,339,341,344,346,347,350,352,353,354,357,358,364,365,366,367,368,369,373,374,376,381,387,388,389,391,392,393,394,396,401,407,409,411,413,416,418,419,420,426,427,428,436,438,439,443,444,448,449,467,472,474,480,481,489,499,508,509,518]
if len(sys.argv) > 1 and sys.argv[1].lstrip("-").isdigit():
    TARGET = [int(x) for x in sys.argv[1:] if x.isdigit()]

# Encabezado que INICIA pretensiones (linea-ancla)
_RE_START = re.compile(
    r"(?im)^\s*(?:[IVXLC]+|[0-9]+|[A-Z])?\s*[.\-)]?\s*"
    r"(PRETENSIONES?|PETICIONES?|PETICI[OÓ]N(?:\s+DE\s+TUTELA)?|S[UÚ]PLICAS?|"
    r"SOLICITUD(?:ES)?|OBJETO\s+DE\s+LA\s+(?:ACCI[OÓ]N|TUTELA|PRETENSI[OÓ]N)|"
    r"PETICI[OÓ]N\s+ESPECIAL)\s*:?\s*$")
# Encabezado de la SIGUIENTE seccion (corta aqui)
_RE_END = re.compile(
    r"(?im)^\s*(?:[IVXLC]+|[0-9]+|[A-Z])?\s*[.\-)]?\s*"
    r"(FUNDAMENTOS?\s+(?:DE\s+)?(?:DERECHO|JUR[IÍ]DICOS?|CONSTITUCIONAL)|"
    r"DERECHO(?:S)?\s+(?:FUNDAMENTAL|VULNERAD|CONSTITUCIONAL|INVOCAD)|"
    r"COMPETENCIA|PROCEDEN(?:CIA|TE)|PROCEDIBILIDAD|LEGITIMACI[OÓ]N|"
    r"JURAMENTO|BAJO\s+(?:LA\s+)?GRAVEDAD\s+DEL\s+JURAMENTO|MANIFESTACI[OÓ]N|"
    r"PRUEBAS?|ANEXOS?|NOTIFICACI[OÓ]N(?:ES)?|DIRECCI[OÓ]N(?:ES)?|"
    r"MEDIDA\s+PROVISIONAL|ANTECEDENTES|HECHOS|CONSIDERACIONES|"
    r"DERECHO\s+DE\s+PETICI[OÓ]N\s+VULNERAD)\s*:?\s*$")


def full_text(doc) -> str:
    fp = getattr(doc, "file_path", None)
    if fp and os.path.exists(fp):
        low = fp.lower()
        try:
            if low.endswith(".pdf"):
                import pymupdf
                d = pymupdf.open(fp)
                n = min(d.page_count, 90)  # guarda: anexos gigantes cuelgan
                t = "\n".join(d[i].get_text() or "" for i in range(n))
                d.close()
                return t
            if low.endswith((".docx",)):
                import docx
                return "\n".join(p.text for p in docx.Document(fp).paragraphs)
        except Exception:
            pass
    return doc.extracted_text or ""


def pick_demanda(db, cid):
    docs = db.query(Document).filter(Document.case_id == cid).all()
    def score(d):
        dt = (d.doc_type or "").upper(); fn = (d.filename or "").upper()
        s = 0
        if "DEMANDA_TUTELA" in dt: s += 10
        elif "ANEXO_DEMANDA" in dt: s += 6
        elif "TUTELA" in dt or "ESCRITO" in dt: s += 4
        if any(k in fn for k in ("TUTELA", "DEMANDA", "ESCRITO")): s += 3
        if "RESPUESTA" in fn or "RESPUESTA" in dt: s -= 8
        if "FALLO" in fn or "SENTENCIA" in dt: s -= 5
        return s
    cand = sorted([d for d in docs if score(d) > 0], key=score, reverse=True)
    return cand


def extract(text):
    starts = list(_RE_START.finditer(text))
    if not starts:
        return None
    # toma el ultimo encabezado (suele ir tras hechos), pero evita el de "SOLICITUD" en anexos
    for m in reversed(starts):
        s = m.end()
        ends = [e for e in _RE_END.finditer(text) if e.start() > s + 30]
        e = ends[0].start() if ends else min(len(text), s + 4000)
        block = text[s:e].strip()
        block = re.sub(r"[ \t]+", " ", block)
        block = re.sub(r"\n{3,}", "\n\n", block).strip(" \n\t:·•-")
        if 60 <= len(block) <= 6000:
            return block[:4500]
    return None


db = SessionLocal()
out = {"ok": [], "fail": []}
for i, cid in enumerate(TARGET):
    print(f"[{i+1}/{len(TARGET)}] c{cid}", flush=True)
    c = db.query(Case).filter(Case.id == cid).first()
    if not c:
        continue
    got = None; src = None
    for d in pick_demanda(db, cid):
        blk = extract(full_text(d))
        if blk:
            got, src = blk, f"doc{d.id}:{d.doc_type}"
            break
    if got:
        out["ok"].append({"case_id": cid, "value": got, "evidence": src,
                          "old_len": len((c.pretensiones or "").strip())})
    else:
        out["fail"].append(cid)
json.dump(out, open("data/pretensiones_disco_plan.json", "w"), ensure_ascii=False, indent=1)
print(f"OK: {len(out['ok'])} | FAIL: {len(out['fail'])}")
print("FAIL ids:", out["fail"])
db.close()
