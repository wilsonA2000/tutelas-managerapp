#!/usr/bin/env python3
"""Detector de accionante mal-etiquetado.

Patrón observado en c66 (decía LAURA, era DIANA) y c97 (decía Personero
Santa Bárbara, era JELIZZA GALVIS Buca): el `cases.accionante` registrado
NO coincide con el accionante real que aparece en la SENTENCIA/DEMANDA del
propio caso.

Estrategia:
1. Para cada caso con docs DEMANDA_TUTELA o SENTENCIA_1RA, extraer el bloque
   "ACCIONANTE: <nombre>" del head del doc (regex robusto).
2. Comparar el nombre extraído (normalizado, sin tildes, sin sufijos) contra
   `cases.accionante`.
3. Si difieren significativamente (no es variante ortográfica), flag para
   revisión humana.

Salida: tabla + CSV. Solo lectura. NO modifica la DB.

Uso:
    python3 scripts/audit_accionante_vs_docs.py
    python3 scripts/audit_accionante_vs_docs.py --threshold 0.4  # menos sensible
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "tutelas.db"

# Doc types prioritarios para extraer el accionante "real"
DOC_TYPES = (
    "DEMANDA_TUTELA", "ANEXO_DEMANDA", "AUTO_ADMISORIO",
    "PDF_AUTO_ADMISORIO", "SENTENCIA_1RA", "PDF_SENTENCIA",
    "NOTIFICACION_FALLO",
)

ACCIONANTE_RX = re.compile(
    r"(?:ACCIONANTE|DEMANDANTE)\s*[:.\-]?\s*([A-ZÁÉÍÓÚÑ\.\s]{8,80})",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    s = (s or "").upper()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    # Quitar palabras boilerplate
    for pat in (r"\bC\.C\.?\s*N[°O]?\.?\s*\d[\d\.\s]*",
                r"\bIDENTIFICAD[OA]\s+CON.*",
                r"\bMAYOR DE EDAD\s*",
                r"\bACTUANDO\s+(?:EN|COMO).*",
                r"\bAGENTE\s+OFICIOS[OA].*",
                r"\bEN\s+REPRESENTACI[OÓ]N\s+DE.*",
                r"\bY\s+OTROS\b.*"):
        s = re.sub(pat, "", s, flags=re.I)
    s = re.sub(r"[^A-Z\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_accionante(text: str) -> str | None:
    """Extrae el primer ACCIONANTE: del head del doc."""
    head = text[:3000]
    m = ACCIONANTE_RX.search(head)
    if not m:
        return None
    raw = m.group(1).strip()
    # cortar en separadores comunes
    raw = re.split(r"[\n,;]|\sACCIONADO|\sACCIONADA|\sIDENT", raw, 1)[0]
    raw = raw.strip()
    if len(raw) < 6:
        return None
    return raw


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def is_personeria_variant(db_acc: str, doc_acc: str, doc_text: str = "") -> bool:
    """Personera presentando = Personería Municipal (regla feedback_personeria).
    También: ICBF / agente oficioso / representación de menor / 'y otros' / boilerplate.
    Se busca evidencia tanto en doc_acc como en la ventana ampliada doc_text."""
    n_db = _norm(db_acc); n_doc = _norm(doc_acc)
    n_text = _norm(doc_text[:2500] if doc_text else "")
    # DB = Personería + doc menciona personero o agente oficioso (en acc o cerca)
    if "PERSONERIA" in n_db:
        if any(k in n_doc for k in ("PERSONER", "AGENTE OFICIOS", "PERSONERO")):
            return True
        if any(k in n_text for k in ("AGENTE OFICIOS", "EN REPRESENTACION", "PERSONERO")):
            return True
    # DB = nombre de persona y doc = ICBF/Defensor Familia (agente oficioso institucional)
    if "ICBF" in n_doc or "DEFENSOR DE FAMILIA" in n_doc:
        return True
    # doc_acc es muy corto o solo describe (no es un nombre real)
    if len(n_doc.split()) <= 2 and any(k in n_doc for k in
            ("EXPUSO", "RECLAMA", "MAYOR DE EDAD", "ACCIONADOS", "SOLICITA",
             "INDICO", "INVOCA", "PRESENTO", "SUPLICA", "INTERPONE",
             "ACTUANDO", "ACUDE", "ACLARO", "ADEMAS", "AFIRMA")):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.55,
                    help="Similitud mínima para considerar match (0-1)")
    args = ap.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    cases = list(db.execute("SELECT id, accionante, folder_name FROM cases "
                            "WHERE accionante IS NOT NULL AND accionante != ''"))
    print(f"Casos: {len(cases)}\n")

    findings = []
    for c in cases:
        cid = c["id"]
        db_acc = c["accionante"]
        # Buscar docs canónicos del caso
        docs = db.execute(
            "SELECT id, doc_type, filename, extracted_text FROM documents "
            "WHERE case_id = ? AND doc_type IN (" + ",".join("?" * len(DOC_TYPES))
            + ") AND extracted_text IS NOT NULL AND LENGTH(extracted_text) > 200 "
            "ORDER BY (CASE doc_type WHEN 'DEMANDA_TUTELA' THEN 1 "
            "         WHEN 'SENTENCIA_1RA' THEN 2 ELSE 3 END), id LIMIT 3",
            (cid, *DOC_TYPES)).fetchall()
        if not docs:
            continue

        # extraer accionante de cada doc
        best_sim = 0.0
        best_doc_acc = None
        best_doc_id = None
        for d in docs:
            doc_acc = extract_accionante(d["extracted_text"] or "")
            if not doc_acc:
                continue
            sim = similarity(db_acc, doc_acc)
            if sim > best_sim:
                best_sim = sim; best_doc_acc = doc_acc; best_doc_id = d["id"]

        if best_doc_acc is None:
            continue
        if best_sim >= args.threshold:
            continue
        # Recuperar doc_text completo del best_doc para hacer una verificación más amplia
        best_text = ""
        if best_doc_id:
            row = db.execute("SELECT extracted_text FROM documents WHERE id=?",
                             (best_doc_id,)).fetchone()
            best_text = row["extracted_text"] if row else ""
        if is_personeria_variant(db_acc, best_doc_acc, best_text):
            continue
        findings.append({"case_id": cid,
                         "db_accionante": db_acc,
                         "doc_accionante": best_doc_acc,
                         "similarity": round(best_sim, 2),
                         "source_doc": best_doc_id,
                         "folder_name": c["folder_name"]})

    findings.sort(key=lambda x: x["similarity"])
    print(f"Casos con accionante posiblemente mal-etiquetado: {len(findings)}\n")
    for f in findings[:30]:
        print(f"  c{f['case_id']:>3} sim={f['similarity']:.2f}  DB={f['db_accionante'][:34]!r:<36} "
              f"DOC={f['doc_accionante'][:40]!r}")
    if len(findings) > 30:
        print(f"  ...+{len(findings)-30} más en CSV")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out = ROOT / "data" / f"audit_accionante_{ts}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "db_accionante", "doc_accionante", "similarity",
                    "source_doc", "folder_name"])
        for f in findings:
            w.writerow([f["case_id"], f["db_accionante"], f["doc_accionante"],
                        f["similarity"], f["source_doc"], f["folder_name"]])
    print(f"\n📄 CSV: {out.relative_to(ROOT)} ({len(findings)} filas)")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
