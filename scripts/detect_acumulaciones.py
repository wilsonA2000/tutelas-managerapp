#!/usr/bin/env python3
"""Detector de acumulaciones de tutelas en el corpus v9.

Escanea `documents.extracted_text` + `filename` buscando indicios de acumulación
procesal (Decreto 2591/1991 art. 13 + CGP art. 159 supletorio):

  Patrones de auto de acumulación:
    - "ACUMÚLESE" / "ACÚMULESE" / "se acumula" / "ACUMULAR"
    - "AUTO ACUMULA" / "AutoAcumula" en filename
    - "tutela(s) acumulada(s)" / "expedientes acumulados"
    - "se ordena la acumulación"

  Patrones de sentencia conjunta:
    - 2+ rads-23 distintos en el encabezado del documento
    - "Resuelve el Despacho LAS Acciones de Tutela" (plural)

Para cada match, identifica los rads involucrados, los cruza con cases en DB,
y propone pares (rector, acumulado).

NO modifica la DB por defecto. Usa --apply para registrar en cases.acumulado_a_case_id.

Uso:
    ./venv/bin/python3 scripts/detect_acumulaciones.py            # dry-run
    ./venv/bin/python3 scripts/detect_acumulaciones.py --apply    # registra
    ./venv/bin/python3 scripts/detect_acumulaciones.py --case 24  # solo este case
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, Document  # noqa: E402


# Señales fuertes de auto/decisión de acumulación
RX_ACUMULA_VERBO = re.compile(
    r"\b(?:AC[ÚU]MULESE|AC[ÚU]MULENSE|"
    r"se\s+acumula[nr]?|se\s+ordena\s+(?:la\s+)?acumulaci[oó]n|"
    r"ACUMULAR\s+(?:la|las|el)\s+(?:acci[oó]n|tutela|expediente|incidente)|"
    r"ORDENAR\s+(?:LA\s+)?ACUMULACI[ÓO]N|"
    r"expediente[s]?\s+acumulad[ao]s?|tutela[s]?\s+acumulada[s]?)\b",
    re.IGNORECASE,
)

# Señales en filename
RX_ACUMULA_FILE = re.compile(
    r"(?i)(?:AcumulaTutela|Auto[\s_]?Acumula|Acumulaci[oó]n|"
    r"Acumula\d+[\-_]\d+)"
)

# Rad-23 (12+4+5+2) o rad-21 con separadores tolerantes
RX_RAD = re.compile(
    r"(\d{12})[\.\-\s]*(20\d{2})[\.\-\s]*(\d{5})(?:[\.\-\s]*(\d{2}))?"
)


def find_rads(text: str) -> list[str]:
    """Devuelve rad-21 (12+4+5) únicos hallados en el texto."""
    out: list[str] = []
    seen = set()
    if not text:
        return out
    s = text.replace("–", "-").replace("—", "-")
    for m in RX_RAD.finditer(s):
        desp, year, consec = m.group(1), m.group(2), m.group(3)
        if not year.startswith("202"):
            continue
        rad21 = desp + year + consec
        if rad21 in seen:
            continue
        seen.add(rad21)
        out.append(rad21)
    return out


def find_acumula_signals(text: str, filename: str) -> dict:
    """Detecta señales de acumulación. Devuelve dict con flags + matches."""
    info: dict = {"verbo": False, "file": False, "rads": [], "snippet": None}
    if filename and RX_ACUMULA_FILE.search(filename):
        info["file"] = True
    if text:
        m = RX_ACUMULA_VERBO.search(text)
        if m:
            info["verbo"] = True
            pos = m.start()
            # snippet de contexto: 80 chars antes + 200 después
            start = max(0, pos - 80)
            info["snippet"] = text[start : pos + 200].replace("\n", " ")
    # Rads del texto (siempre)
    info["rads"] = find_rads((text or "") + " " + (filename or ""))
    return info


def parse_fecha_es(text: str) -> str | None:
    """Extrae primera fecha en español del estilo 'DD de MES de AAAA' o 'DD/MM/AAAA'."""
    if not text:
        return None
    # DD/MM/AAAA
    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](20\d{2})\b", text)
    if m:
        return f"{m.group(1).zfill(2)}/{m.group(2).zfill(2)}/{m.group(3)}"
    # DD de MES de AAAA
    meses = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "setiembre": "09", "octubre": "10",
        "noviembre": "11", "diciembre": "12",
    }
    m = re.search(
        r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"se?ptiembre|octubre|noviembre|diciembre)\s+de\s+(20\d{2})\b",
        text, re.IGNORECASE,
    )
    if m:
        return f"{m.group(1).zfill(2)}/{meses[m.group(2).lower()]}/{m.group(3)}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="registra en DB (default: dry-run)")
    ap.add_argument("--case", type=int, help="solo este case_id")
    ap.add_argument("--show-snippet", action="store_true", help="muestra contexto textual")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        # Cargar todos los cases con rad para hacer lookup
        cases = db.query(Case).filter(
            Case.radicado_23_digitos != None,
            Case.folder_name != "__SIN_RADICADO__",
        ).all()
        rad21_to_case = {}
        for c in cases:
            if c.radicado_23_digitos and len(c.radicado_23_digitos) >= 21:
                rad21_to_case[c.radicado_23_digitos[:21]] = c
        print(f"Cases con rad: {len(rad21_to_case)}")

        # Iterar documents
        q = db.query(Document).filter(Document.extracted_text != None)
        if args.case:
            q = q.filter(Document.case_id == args.case)
        docs = q.all()
        print(f"Docs a escanear: {len(docs)}")

        # case_id → {rector_case_id, auto_doc, fecha, evidence}
        proposals: dict[int, dict] = {}

        for d in docs:
            info = find_acumula_signals(d.extracted_text, d.filename or "")
            signal = info["verbo"] or info["file"]
            if not signal:
                continue
            rads = info["rads"]
            if len(rads) < 2:
                continue
            # ¿Cuáles de esos rads están en la DB?
            cases_hit = [(r, rad21_to_case.get(r)) for r in rads]
            hits = [(r, c) for r, c in cases_hit if c is not None]
            if len(hits) < 2:
                continue
            # El case origen del doc es uno de los hits idealmente
            own_case = next((c for r, c in hits if c.id == d.case_id), None)
            if not own_case:
                continue
            # Resto son candidatos a acumulados
            otros = [c for r, c in hits if c.id != d.case_id]

            # Determinar rector vs acumulado: el de rad-corto MENOR es el rector
            # (primero radicado). En "ACUMULA 2026-00034 a 2026-00033", el rector
            # es 2026-00033 (menor consec).
            def consec_int(case: Case) -> int:
                r = case.radicado_23_digitos
                try:
                    return int(r[16:21])
                except Exception:
                    return 99999

            all_cases = [own_case] + otros
            rector = min(all_cases, key=consec_int)
            for c in all_cases:
                if c.id == rector.id:
                    role = "RECTOR"
                else:
                    role = "ACUMULADO"
                fecha = parse_fecha_es(info["snippet"] or "") or parse_fecha_es(d.extracted_text[:1500] or "")
                p = proposals.setdefault(c.id, {
                    "case": c,
                    "role": role,
                    "rector_id": rector.id,
                    "auto_doc_id": d.id,
                    "fecha": fecha,
                    "evidence_docs": set(),
                    "snippet": info["snippet"],
                })
                # No degradar RECTOR a ACUMULADO si ya fue marcado
                if p["role"] == "ACUMULADO" and role == "RECTOR":
                    p["role"] = "RECTOR"
                    p["rector_id"] = rector.id
                p["evidence_docs"].add(d.id)

        print(f"\nPropuestas: {len(proposals)} cases involucrados en acumulaciones\n")
        # Agrupar por rector
        groups: dict[int, list[dict]] = {}
        for p in proposals.values():
            groups.setdefault(p["rector_id"], []).append(p)

        for rector_id, members in sorted(groups.items()):
            rector_p = next((m for m in members if m["case"].id == rector_id), None)
            rector_case = rector_p["case"] if rector_p else db.get(Case, rector_id)
            print(f"\n=== RECTOR #{rector_id} «{rector_case.folder_name[:55]}» rad={rector_case.radicado_23_digitos} ===")
            for m in members:
                c = m["case"]
                marker = "★ RECTOR " if c.id == rector_id else "  acumulado"
                ev_count = len(m["evidence_docs"])
                fecha = m["fecha"] or "(sin fecha)"
                print(f"  {marker} #{c.id:3d} {c.folder_name[:55]:55s} rad={c.radicado_23_digitos} fecha={fecha} evidencia={ev_count}d")
                if args.show_snippet and m["snippet"]:
                    print(f"     snippet: …{m['snippet'][:180]}…")

        if not args.apply:
            print("\n(dry-run — sin cambios. Usa --apply para registrar.)")
            return 0

        # Aplicar
        changed = 0
        for p in proposals.values():
            c = p["case"]
            if c.id == p["rector_id"]:
                new_type = "RECTOR"
                new_acumulado_a = None
            else:
                new_type = "ACUMULADO"
                new_acumulado_a = p["rector_id"]
            # Idempotente
            if (c.tipo_acumulacion == new_type and
                c.acumulado_a_case_id == new_acumulado_a):
                continue
            c.tipo_acumulacion = new_type
            c.acumulado_a_case_id = new_acumulado_a
            c.acumulacion_auto_doc_id = p["auto_doc_id"]
            c.acumulacion_fecha = p["fecha"]
            changed += 1
        db.commit()
        print(f"\n✓ {changed} cases actualizados.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
