"""Re-extrae a la DB los docs con extracted_text capado al viejo límite de 30k chars
(que pierde el footer "Proyectó"/RESUELVE del FINAL). doc_io lee head+tail completo, así
que recupera la cola. Afecta abogado_responsable (footer), parte_resolutiva/sentido (RESUELVE).

El cap legacy ~30000 era HEAD-only (sin cola). La re-extracción canónica (head+tail) trae
la cola → se reemplaza siempre que la lectura de disco dé texto no-trivial.

Uso:
  recap_30k.py [--apply] [--types RESPUESTA,SENTENCIA_1RA,...] [--ocr]
  --ocr   re-extrae también escaneados (necesita PaddleOCR; por defecto OFF = solo capa texto).
"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
APPLY = "--apply" in sys.argv
USE_OCR = "--ocr" in sys.argv
os.environ["V9_OCR_SCANNED"] = "true" if USE_OCR else "false"
types = None
if "--types" in sys.argv:
    types = sys.argv[sys.argv.index("--types") + 1].split(",")

from backend.database.database import SessionLocal
from backend.database.models import Document
from backend.v9 import doc_io

db = SessionLocal()
q = db.query(Document)
if types:
    q = q.filter(Document.doc_type.in_(types))
capados = [d for d in q.all() if d.extracted_text and 29900 <= len(d.extracted_text) <= 30050]
print(f"Docs capados ~30k{' (' + ','.join(types) + ')' if types else ''}: {len(capados)}")

upd = skip = 0
for d in capados:
    if not d.file_path or not os.path.exists(d.file_path):
        skip += 1; continue
    try:
        t = doc_io.read_one(d.file_path).text or ""
    except Exception:
        t = ""
    # Reemplazar cuando la lectura canónica (head+tail) trae texto no-trivial. Un
    # escaneado sin OCR devuelve vacío/corto → se conserva el viejo (skip).
    if len(t) >= 1000 and t != d.extracted_text:
        if APPLY:
            d.extracted_text = t
            d.extraction_method = "recap_headtail"
        upd += 1
    else:
        skip += 1
if APPLY:
    db.commit()
print(f"{'Re-extraídos' if APPLY else 'Se re-extraerían'}: {upd} | conservados (escaneado/no-disco): {skip}")
db.close()
