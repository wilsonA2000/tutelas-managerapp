"""Ingesta del Excel histórico CONTROL TUTELAS al SQLite.

Crea tabla `historical_cases` y la pobla con las 4 hojas TUTELAS 2023-2026.
Aplica normalizadores (dependencia/abogado/fallo/tema) y matchea con corpus
actual (`cases`) por radicado_forest / radicado_corto / accionante fuzzy.

Uso:
    python -m backend.ml.data.import_historical /path/to/CONTROL_TUTELAS.xlsx
"""

from __future__ import annotations
import logging
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import openpyxl

from backend.database.database import SessionLocal, engine
from backend.database.models import Base, Case
from sqlalchemy import (
    Column, Integer, String, Float, Date, Text, UniqueConstraint, text
)

from backend.ml.data.normalizers import (
    normalize_dependencia, normalize_abogado, classify_fallo, normalize_tema,
    normalize_radicado_corto, is_abogado_activo,
)

logger = logging.getLogger("tutelas.ml.import_historical")


# ============================================================
# Modelo SQLAlchemy
# ============================================================

class HistoricalCase(Base):
    __tablename__ = "historical_cases"

    id = Column(Integer, primary_key=True)
    source_sheet = Column(String, nullable=False)
    source_row = Column(Integer, nullable=False)

    fecha_raw = Column(String)
    fecha = Column(Date)
    tipo = Column(String)              # TUTELA / DESACATO
    radicado_corto = Column(String, index=True)
    radicado_forest = Column(String, index=True)
    accionante = Column(String, index=True)
    correo_juzgado = Column(String)
    tema_raw = Column(Text)
    tema_normalized = Column(String)
    dependencia_raw = Column(String)
    dependencia_normalized = Column(String, index=True)
    abogado_raw = Column(String)
    abogado_full = Column(String, index=True)
    abogado_activo = Column(Integer)   # 1 = activo, 0 = inactivo
    termino_raw = Column(String)
    observaciones = Column(Text)
    observaciones_henser = Column(Text)
    fallo_raw = Column(Text)
    fallo_class = Column(String)
    matched_case_id = Column(Integer, index=True)
    confidence_match = Column(Float)
    match_strategy = Column(String)    # forest / radcorto+accionante / accionante_fuzzy / none

    __table_args__ = (
        UniqueConstraint("source_sheet", "source_row", name="uq_hist_source"),
    )


# ============================================================
# Helpers
# ============================================================

def _strip_accents(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper().strip()


def _parse_fecha(raw):
    """Excel cells pueden ser str ('24 enero'), datetime, o int (serial)."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        s = raw.strip().lower()
        # No es prioritario; el año viene del nombre del sheet
        return None
    return None


def _accionante_words(s: str) -> set[str]:
    s = _strip_accents(s)
    return {w for w in s.split() if len(w) >= 4}


def _fuzzy_accionante_match(name_excel: str, name_db: str) -> float:
    """Ratio de overlap de palabras (Jaccard simple)."""
    if not name_excel or not name_db:
        return 0.0
    a = _accionante_words(name_excel)
    b = _accionante_words(name_db)
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


# ============================================================
# Match Excel ↔ corpus actual
# ============================================================

def match_to_db_case(
    db, hist_radicado_forest: str, hist_radicado_corto: str,
    hist_accionante: str, hist_year: int | None,
) -> tuple[int | None, float, str]:
    """Devuelve (case_id, confidence, strategy) o (None, 0, 'none')."""

    # 1) Match exacto por forest
    if hist_radicado_forest:
        r = db.execute(
            text("SELECT id FROM cases WHERE radicado_forest = :f"),
            {"f": hist_radicado_forest.strip()},
        ).fetchone()
        if r:
            return r[0], 1.0, "forest"

    # 2) Match por radicado_corto (formato YYYY-NNNNN) — combinar con accionante
    if hist_radicado_corto:
        # Extraer año y número del corto: "2024-00001"
        import re as _re
        m = _re.match(r"(\d{4})-(\d{1,5})", hist_radicado_corto)
        if m:
            year_str = m.group(1)
            num_str = m.group(2).lstrip("0") or "0"  # sin zeros leading para LIKE flexible
            # rad23 colombiano contiene año + número en posiciones específicas
            patterns = [
                f"%{year_str}{num_str.zfill(5)}%",  # 202400001
                f"%{year_str}-{num_str.zfill(5)}%",
                f"%{year_str}{num_str.zfill(2)}%",
            ]
            rows = []
            for p in patterns:
                rows = db.execute(
                    text("SELECT id, accionante FROM cases WHERE radicado_23_digitos LIKE :p"),
                    {"p": p},
                ).fetchall()
                if rows:
                    break
        else:
            rows = []
        if rows:
            # Si solo 1 → confiar
            if len(rows) == 1:
                return rows[0][0], 0.85, "radcorto"
            # Si varios, desempatar por accionante
            best = None
            best_score = 0.0
            for rid, acc in rows:
                score = _fuzzy_accionante_match(hist_accionante, acc or "")
                if score > best_score:
                    best, best_score = rid, score
            if best and best_score >= 0.5:
                return best, 0.7 + 0.2 * best_score, "radcorto+accionante"

    # 3) Match por accionante fuzzy (riesgo: nombres comunes)
    if hist_accionante and len(hist_accionante) >= 8:
        rows = db.execute(
            text("SELECT id, accionante FROM cases WHERE accionante IS NOT NULL"),
        ).fetchall()
        best = None
        best_score = 0.0
        for rid, acc in rows:
            score = _fuzzy_accionante_match(hist_accionante, acc or "")
            if score > best_score:
                best, best_score = rid, score
        if best and best_score >= 0.85:
            return best, 0.5 + 0.4 * best_score, "accionante_fuzzy"

    return None, 0.0, "none"


# ============================================================
# Parser principal
# ============================================================

SHEET_YEARS = {
    "TUTELAS 2023": 2023,
    "TUTELAS 2024": 2024,
    "TUTELAS 2025 ": 2025,
    "TUTELAS 2026": 2026,
}


def _normalize_radicado_with_year(raw, year):
    """Si el radicado es '24-1', '23-267', etc. y no tiene año completo, usar el del sheet."""
    if not raw:
        return ""
    s = str(raw).strip()
    import re
    m = re.search(r"\b(\d{2,4})[-\s]+(\d{1,5})", s)
    if not m:
        return s
    raw_year = m.group(1)
    num = m.group(2)
    if len(raw_year) == 2:
        full_year = ("20" if int(raw_year) < 70 else "19") + raw_year
        # Si difiere del sheet, confiar en el del radicado
        return f"{full_year}-{num.zfill(5)}"
    return f"{raw_year}-{num.zfill(5)}"


def parse_excel_and_load(excel_path: str) -> dict:
    """Lee el Excel, normaliza, persiste a `historical_cases` y matchea."""
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    db = SessionLocal()
    Base.metadata.create_all(bind=engine)  # crea tabla si no existe

    # Reset previo
    db.execute(text("DELETE FROM historical_cases"))
    db.commit()

    stats = {
        "total_rows": 0, "with_radicado": 0, "loaded": 0,
        "matched_forest": 0, "matched_radcorto": 0, "matched_fuzzy": 0,
        "unmatched": 0,
        "abogado_activo": 0, "abogado_inactivo": 0, "abogado_unknown": 0,
        "by_year": {}, "by_dependencia": {}, "by_fallo": {}, "by_tema": {},
    }

    for sheet_name, year in SHEET_YEARS.items():
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        headers = [str(c.value).strip().lower() if c.value else "" for c in ws[1]]

        for row_idx in range(2, ws.max_row + 1):
            stats["total_rows"] += 1
            row = dict(zip(headers, [c.value for c in ws[row_idx]]))
            if not row.get("radicado"):
                continue
            stats["with_radicado"] += 1

            radicado_corto = _normalize_radicado_with_year(row.get("radicado"), year)
            forest = str(row.get("radicado forest") or "").strip()
            accionante = str(row.get("accionante") or "").strip()

            # Normalizaciones
            dep_raw = str(row.get("dependencia") or "").strip()
            dep_norm = normalize_dependencia(dep_raw)
            abog_raw = str(row.get("abogado") or "").strip()
            abog_full = normalize_abogado(abog_raw)
            abog_activo = 1 if is_abogado_activo(abog_full) else 0
            tema_raw = str(row.get("tema") or "").strip()
            tema_norm = normalize_tema(tema_raw)
            fallo_raw = str(row.get("fallo") or "").strip()
            fallo_class = classify_fallo(fallo_raw)

            # Tipo
            tutela_val = str(row.get("tutela") or "").strip()
            desacato_val = str(row.get("desacato") or "").strip()
            tipo = "DESACATO" if desacato_val and not tutela_val else "TUTELA"

            # Match con corpus actual
            mid, conf, strat = match_to_db_case(
                db, forest, radicado_corto, accionante, year,
            )
            if strat == "forest":
                stats["matched_forest"] += 1
            elif strat in ("radcorto", "radcorto+accionante"):
                stats["matched_radcorto"] += 1
            elif strat == "accionante_fuzzy":
                stats["matched_fuzzy"] += 1
            else:
                stats["unmatched"] += 1

            if abog_full.startswith("INACTIVO_"):
                stats["abogado_inactivo"] += 1
            elif abog_full.startswith("<"):
                stats["abogado_unknown"] += 1
            elif abog_full:
                stats["abogado_activo"] += 1

            stats["by_year"][year] = stats["by_year"].get(year, 0) + 1
            stats["by_dependencia"][dep_norm] = stats["by_dependencia"].get(dep_norm, 0) + 1
            stats["by_fallo"][fallo_class or "<vacío>"] = stats["by_fallo"].get(fallo_class or "<vacío>", 0) + 1
            stats["by_tema"][tema_norm or "<vacío>"] = stats["by_tema"].get(tema_norm or "<vacío>", 0) + 1

            hc = HistoricalCase(
                source_sheet=sheet_name, source_row=row_idx,
                fecha_raw=str(row.get("fecha") or ""),
                fecha=_parse_fecha(row.get("fecha")),
                tipo=tipo,
                radicado_corto=radicado_corto,
                radicado_forest=forest or None,
                accionante=accionante or None,
                correo_juzgado=str(row.get("correo juzgado") or "").strip() or None,
                tema_raw=tema_raw or None,
                tema_normalized=tema_norm,
                dependencia_raw=dep_raw or None,
                dependencia_normalized=dep_norm,
                abogado_raw=abog_raw or None,
                abogado_full=abog_full or None,
                abogado_activo=abog_activo,
                termino_raw=str(row.get("término") or row.get("termino") or "").strip() or None,
                observaciones=str(row.get("observaciones") or "").strip() or None,
                observaciones_henser=str(row.get("observaciones henser") or "").strip() or None,
                fallo_raw=fallo_raw or None,
                fallo_class=fallo_class or None,
                matched_case_id=mid,
                confidence_match=conf,
                match_strategy=strat,
            )
            db.add(hc)
            stats["loaded"] += 1

        # Commit por sheet
        db.commit()
        logger.info("Sheet %s: %d filas cargadas", sheet_name, stats["by_year"].get(year, 0))

    db.close()
    return stats


def report(stats: dict):
    print("=" * 60)
    print("INGESTA HISTÓRICA — RESUMEN")
    print("=" * 60)
    print(f"Total filas Excel:       {stats['total_rows']}")
    print(f"Con radicado:            {stats['with_radicado']}")
    print(f"Cargadas a DB:           {stats['loaded']}")
    print()
    print("Match con corpus actual (213 casos):")
    print(f"  por forest:              {stats['matched_forest']}")
    print(f"  por radicado corto:      {stats['matched_radcorto']}")
    print(f"  por accionante fuzzy:    {stats['matched_fuzzy']}")
    print(f"  sin match:               {stats['unmatched']}")
    total_matched = stats['matched_forest'] + stats['matched_radcorto'] + stats['matched_fuzzy']
    print(f"  TOTAL matched:           {total_matched} ({100*total_matched/max(stats['loaded'],1):.1f}%)")
    print()
    print("Abogados:")
    print(f"  activos (sed.json):      {stats['abogado_activo']}")
    print(f"  inactivos:               {stats['abogado_inactivo']}")
    print(f"  desconocidos:            {stats['abogado_unknown']}")
    print()
    print("Por año:", dict(sorted(stats["by_year"].items())))
    print()
    print("Top 10 dependencias:")
    for k, v in sorted(stats["by_dependencia"].items(), key=lambda x: -x[1])[:10]:
        print(f"  {v:>5}  {k}")
    print()
    print("Top 10 temas:")
    for k, v in sorted(stats["by_tema"].items(), key=lambda x: -x[1])[:10]:
        print(f"  {v:>5}  {k}")
    print()
    print("Distribución FALLO:")
    for k, v in sorted(stats["by_fallo"].items(), key=lambda x: -x[1])[:10]:
        print(f"  {v:>5}  {k}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/c/Users/wilso/Downloads/CONTROL TUTELAS.xlsx"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stats = parse_excel_and_load(path)
    report(stats)
