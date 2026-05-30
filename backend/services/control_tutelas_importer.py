"""Importador del cuadro de control externo (CONTROL TUTELAS .xlsx).

Lee el Excel mantenido por la oficina jurídica, agrupa filas por radicado
(cada fila = una actuación administrativa), y aplica reconciliación con la DB
con prioridad por evidencia. NO usa Excel como ground truth — lo trata como
una segunda fuente que se cruza con lo que el pipeline ya extrajo.

Reglas de reconciliación de abogado_canonical:
    DB y Excel coinciden          → mantener (alta confianza)
    DB tiene oficial, Excel vacío → mantener DB
    Excel oficial, DB vacío       → adoptar Excel (origin=excel_administrativo)
    DB no-oficial, Excel oficial  → adoptar Excel (firmante DB queda en log)
    Ambos oficiales pero distintos→ DISENSO, requiere revisión humana

Se persisten TODAS las filas-actuación en `case_actuaciones` para preservar
la bitácora completa (no se pierde información).
"""
from __future__ import annotations
from backend.core.time import utcnow

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from backend.data.abogados_resolver import normalize_abogado, short_to_canonical
from backend.data.dependencias_resolver import normalize_dependencia
from backend.database.models import Case, CaseActuacion, AuditLog


SHEET_PER_YEAR = ["TUTELAS 2023", "TUTELAS 2024", "TUTELAS 2025 ", "TUTELAS 2026"]


def _norm_rad(s: Optional[object]) -> Optional[str]:
    """Extrae rad_corto canónico ('2026-00057') de un string heterogéneo."""
    if s is None:
        return None
    txt = str(s).strip()
    m = re.search(r"(20\d{2})[-\s]?(\d{2,5})", txt)
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):05d}"


def _serialize_fecha(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y")
    s = str(v).strip()
    return s or None


def _classify_actuacion(tutela: str, desacato: str) -> str:
    """Tipo de actuación a partir de las columnas TUTELA y DESACATO del Excel."""
    t = (tutela or "").upper()
    d = (desacato or "").upper()
    if "DESACATO" in d or "INCIDENTE" in d:
        return "DESACATO"
    if "RECURSO" in t or "IMPUGNA" in t:
        return "RECURSO"
    if "RTA" in t or "RESPUESTA" in t:
        return "RTA"
    if "REQUER" in d:
        return "REQUERIMIENTO"
    if "TUTELA" in t:
        return "TUTELA"
    return "OTRO"


def parse_workbook(xlsx_path: str, source_version: Optional[str] = None) -> list[dict]:
    """Lee TODAS las hojas anuales y devuelve lista de filas-actuación."""
    wb = load_workbook(xlsx_path, data_only=True, read_only=True)
    out: list[dict] = []
    for sheet_name in SHEET_PER_YEAR:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        for r in ws.iter_rows(values_only=True):
            if not any(c for c in r):
                continue
            # Defensive: asegurar mínimo 12 columnas
            r = list(r) + [None] * max(0, 12 - len(r))
            rad_raw = r[3]
            rad_corto = _norm_rad(rad_raw)
            if not rad_corto:
                continue
            row = {
                "rad_corto": rad_corto,
                "rad_forest_raw": str(r[9] or "").strip() if r[9] else None,
                "fecha_actuacion": _serialize_fecha(r[0]),
                "tutela": str(r[1] or "").strip(),
                "desacato": str(r[2] or "").strip(),
                "accionante": str(r[4] or "").strip(),
                "correo_juzgado": str(r[5] or "").strip(),
                "tema": str(r[6] or "").strip(),
                "dependencia_raw": str(r[7] or "").strip(),
                "abogado_short": str(r[8] or "").strip(),
                "observaciones": str(r[11] or "").strip(),
                "sheet": sheet_name.strip(),
            }
            row["tipo_actuacion"] = _classify_actuacion(row["tutela"], row["desacato"])
            row["abogado_canonical"] = (
                short_to_canonical(row["abogado_short"]) or normalize_abogado(row["abogado_short"])
            )
            row["dependencia_canonical"] = normalize_dependencia(row["dependencia_raw"])
            row["source_version"] = source_version
            out.append(row)
    return out


def reconcile_abogado(db_abogado: Optional[str], db_canonical: Optional[str],
                       excel_canonical: Optional[str]) -> dict:
    """Aplica reglas de reconciliación. Devuelve diccionario con decisión.

    Returns:
        {
          'final_canonical': str | None,
          'source': 'db'|'excel'|'disenso'|'none',
          'flag': 'OK'|'ADOPTAR_EXCEL'|'DISENSO'|'NO_OFICIAL',
          'note': str (explicación),
        }
    """
    if not db_canonical and not excel_canonical:
        return {"final_canonical": None, "source": "none", "flag": "NO_OFICIAL",
                "note": f"Ningún resolver matchea (DB raw={db_abogado!r})"}
    if db_canonical and not excel_canonical:
        return {"final_canonical": db_canonical, "source": "db", "flag": "OK",
                "note": "Excel sin abogado, mantengo DB"}
    if excel_canonical and not db_canonical:
        return {"final_canonical": excel_canonical, "source": "excel", "flag": "ADOPTAR_EXCEL",
                "note": f"DB no tenía abogado oficial; Excel: {excel_canonical}"}
    if db_canonical == excel_canonical:
        return {"final_canonical": db_canonical, "source": "db", "flag": "OK",
                "note": "DB y Excel coinciden"}
    # Ambos oficiales pero distintos: DISENSO
    return {"final_canonical": db_canonical, "source": "disenso", "flag": "DISENSO",
            "note": f"DB={db_canonical} vs Excel={excel_canonical}"}


def reconcile_dependencia(db_canonical: Optional[str],
                           excel_canonical: Optional[str]) -> dict:
    """Mismas reglas que abogado pero para dependencia."""
    if not db_canonical and not excel_canonical:
        return {"final_canonical": None, "source": "none", "flag": "SIN_INFO"}
    if db_canonical and not excel_canonical:
        return {"final_canonical": db_canonical, "source": "db", "flag": "OK"}
    if excel_canonical and not db_canonical:
        return {"final_canonical": excel_canonical, "source": "excel", "flag": "ADOPTAR_EXCEL"}
    if db_canonical == excel_canonical:
        return {"final_canonical": db_canonical, "source": "db", "flag": "OK"}
    # Conflicto: privilegiar dependencia más específica (MULTI < L1 < L2 < L3)
    return {"final_canonical": db_canonical, "source": "disenso", "flag": "DISENSO"}


def import_control_tutelas(db: Session, xlsx_path: str, source_version: Optional[str] = None,
                            apply_reconciliation: bool = True, dry_run: bool = False) -> dict:
    """Importa todas las hojas anuales del cuadro de control y reconcilia.

    Args:
        xlsx_path: ruta al archivo .xlsx
        source_version: identificador (ej. fecha de export del Excel '2026-05-07')
        apply_reconciliation: si True, actualiza cases.abogado_canonical/dependencia
                              cuando flag=ADOPTAR_EXCEL. Si False, solo persiste actuaciones.
        dry_run: si True, no commitea (preview)

    Returns:
        Reporte completo con métricas y disensos a revisar.
    """
    rows = parse_workbook(xlsx_path, source_version)
    if not source_version:
        source_version = utcnow().strftime("%Y-%m-%d")

    # Indexar cases por rad_corto y rad_23
    db_cases = db.query(Case).all()
    by_rad: dict[str, Case] = {}
    for c in db_cases:
        rc = _norm_rad(c.radicado_23_digitos)
        if rc:
            by_rad[rc] = c

    # Persistir actuaciones (no consolidadas) y agrupar para reconciliación
    by_rad_excel: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_rad_excel[r["rad_corto"]].append(r)

    new_actuaciones = []
    for r in rows:
        case = by_rad.get(r["rad_corto"])
        new_actuaciones.append(CaseActuacion(
            case_id=case.id if case else None,
            radicado_corto=r["rad_corto"],
            radicado_forest=r["rad_forest_raw"],
            fecha_actuacion=r["fecha_actuacion"],
            tipo_actuacion=r["tipo_actuacion"],
            abogado_short=r["abogado_short"] or None,
            abogado_canonical=r["abogado_canonical"],
            dependencia_raw=r["dependencia_raw"] or None,
            dependencia_canonical=r["dependencia_canonical"],
            tema=r["tema"] or None,
            observaciones=r["observaciones"] or None,
            accionante=r["accionante"] or None,
            correo_juzgado=r["correo_juzgado"] or None,
            source="control_tutelas_xlsx",
            source_version=source_version,
        ))

    # Reconciliación a nivel rad (consolida actuaciones del mismo rad)
    rad_consenso = {}
    for rad, acts in by_rad_excel.items():
        abogados_can = [a["abogado_canonical"] for a in acts if a["abogado_canonical"]]
        deps_can = [a["dependencia_canonical"] for a in acts if a["dependencia_canonical"]]
        rad_consenso[rad] = {
            "abogado_excel": Counter(abogados_can).most_common(1)[0][0] if abogados_can else None,
            "dep_excel": Counter(deps_can).most_common(1)[0][0] if deps_can else None,
            "n_actuaciones": len(acts),
            "abogado_disenso_excel": len(set(abogados_can)) > 1,
        }

    # Aplicar reconciliación contra DB y registrar updates/disensos
    report = {
        "source_version": source_version,
        "rows_total": len(rows),
        "actuaciones_persisted": len(new_actuaciones),
        "rads_unicos_excel": len(by_rad_excel),
        "rads_match_db": 0,
        "rads_solo_excel": [],
        "rads_solo_db": [],
        "abogado_ok": 0,
        "abogado_adoptado": 0,
        "abogado_disenso": [],
        "dep_ok": 0,
        "dep_adoptado": 0,
        "dep_disenso": [],
        "abogado_disenso_interno_excel": 0,
        "dry_run": dry_run,
    }

    excel_rads = set(by_rad_excel.keys())
    db_rads = set(by_rad.keys())
    inter = excel_rads & db_rads
    report["rads_match_db"] = len(inter)
    report["rads_solo_excel"] = sorted(excel_rads - db_rads)[:50]
    report["rads_solo_db"] = sorted(db_rads - excel_rads)[:50]
    report["count_solo_excel"] = len(excel_rads - db_rads)
    report["count_solo_db"] = len(db_rads - excel_rads)

    for rad in inter:
        case = by_rad[rad]
        excel = rad_consenso[rad]
        if excel["abogado_disenso_excel"]:
            report["abogado_disenso_interno_excel"] += 1

        # Abogado
        decision = reconcile_abogado(case.abogado_responsable,
                                      case.abogado_canonical,
                                      excel["abogado_excel"])
        if decision["flag"] == "OK":
            report["abogado_ok"] += 1
        elif decision["flag"] == "ADOPTAR_EXCEL":
            report["abogado_adoptado"] += 1
            if apply_reconciliation and not dry_run:
                old = case.abogado_canonical
                case.abogado_canonical = decision["final_canonical"]
                case.abogado_canonical_confidence = 0.85  # fuente excel
                db.add(AuditLog(
                    case_id=case.id, field_name="abogado_canonical",
                    old_value=str(old), new_value=str(decision["final_canonical"]),
                    action="IMPORT_RECONCILE", source=f"excel:{source_version}",
                ))
        elif decision["flag"] == "DISENSO":
            report["abogado_disenso"].append({
                "case_id": case.id, "rad": rad,
                "db": case.abogado_canonical, "excel": excel["abogado_excel"],
                "folder": case.folder_name,
            })

        # Dependencia
        dep_dec = reconcile_dependencia(case.dependencia_canonical, excel["dep_excel"])
        if dep_dec["flag"] == "OK":
            report["dep_ok"] += 1
        elif dep_dec["flag"] == "ADOPTAR_EXCEL":
            report["dep_adoptado"] += 1
            if apply_reconciliation and not dry_run:
                old = case.dependencia_canonical
                case.dependencia_canonical = dep_dec["final_canonical"]
                case.dependencia_canonical_confidence = 0.85
                db.add(AuditLog(
                    case_id=case.id, field_name="dependencia_canonical",
                    old_value=str(old), new_value=str(dep_dec["final_canonical"]),
                    action="IMPORT_RECONCILE", source=f"excel:{source_version}",
                ))
        elif dep_dec["flag"] == "DISENSO":
            report["dep_disenso"].append({
                "case_id": case.id, "rad": rad,
                "db": case.dependencia_canonical, "excel": excel["dep_excel"],
            })

    if not dry_run:
        # Reemplazar actuaciones de esta versión (idempotencia)
        db.query(CaseActuacion).filter(CaseActuacion.source_version == source_version).delete()
        for ac in new_actuaciones:
            db.add(ac)
        db.commit()

    return report
