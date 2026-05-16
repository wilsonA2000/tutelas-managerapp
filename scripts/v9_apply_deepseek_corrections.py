#!/usr/bin/env python3
"""Aplica (conservadoramente) las correcciones que DeepSeek detectó en la revisión del cuadro.

Parte del reporte `reports/revision_deepseek_*.md` (el más reciente) y:
  1. Escribe un reporte CORTO con las discrepancias "alta" agrupadas por campo + un CSV.
  2. Identifica los expedientes CONFLADOS (DeepSeek dijo que tienen docs de otra tutela) — a esos
     NO se les aplica nada (hay que separarlos primero); se listan aparte.
  3. En los expedientes NO conflados, aplica las correcciones de bajo riesgo: asunto, ciudad,
     fechas (con cota de año), estado, quien_impugno, impugnacion, incidente, decision_incidente,
     accionados (cuando DeepSeek dio una lista más completa), juzgado, y pretensiones cuando la
     extracción había puesto la CONTESTACIÓN de la entidad en vez de las del accionante.
     NO toca: accionante (síntoma de conflación), derecho_vulnerado / oficina_responsable /
     categoria_tematica (vocabulario controlado — categoria_tematica se re-deriva del asunto nuevo).
  4. Re-deriva categoria_tematica (de los asuntos cambiados) y estado (de los fallos cambiados).

Uso:
    ./venv/bin/python3 scripts/v9_apply_deepseek_corrections.py                # dry-run + reportes
    ./venv/bin/python3 scripts/v9_apply_deepseek_corrections.py --apply        # aplica a la DB
    ./venv/bin/python3 scripts/v9_apply_deepseek_corrections.py --report FILE   # usar otro reporte
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case  # noqa: E402
from backend.cognition.legal_schema import MUNICIPIOS_SANTANDER  # noqa: E402

_RE_HEADER = re.compile(r"^###\s+#(\d+)\s+—\s+(.*)$")
_RE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(alta|media|baja)\s*\|\s*(.*?)\s*\|\s*$")
_RE_CONFLATED = re.compile(r"(?i)otro\s+expediente|otro\s+proceso|otro\s+caso\b|otra\s+tutela|docs?\s+mezclad|"
                           r"confusi[oó]n\s+con\s+otro|corresponde\s+a\s+otro|pertenece\s+a\s+otro|de\s+otro\s+radicado")
_RE_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_META_VALS = {"", "none", "null", "n/a", "no consta", "no constan", "no consta en los documentos",
              "(vacío)", "coincide", "se mantiene", "—"}
_FALLO_WORDS = {"CONCEDE", "NIEGA", "IMPROCEDENTE", "IMPROCEDENCIA", "RECHAZA", "CARENCIA DE OBJETO",
                "CARENCIA ACTUAL DE OBJETO", "HECHO SUPERADO", "DAÑO CONSUMADO", "NULIDAD", "CONFIRMA",
                "REVOCA", "MODIFICA", "TUTELA", "AMPARA", "NEGADA", "CONCEDIDA"}
_CONTESTACION_MARKERS = re.compile(r"(?i)tener\s+por\s+contestad|se\s+opone\s+a|negar\s+las\s+pretensi|"
                                   r"en\s+los\s+t[eé]rminos\s+se[ñn]alados|ratificad[ao]\s+la\s+respuesta|"
                                   r"la\s+secretar[ií]a.*carece\s+de\s+legitimaci")
_NO_FALLO_NOTE = re.compile(r"(?i)no\s+hay\s+(sentencia|fallo)|no\s+(consta|obra)\s+(una\s+)?(sentencia|fallo)|"
                            r"el\s+fallo\s+(que\s+aparece\s+)?(es|corresponde)\s+(a\s+|de\s+)?otro")
_RAD_YEAR = re.compile(r"^\D*(\d{12})(\d{4})")


def _parse_report(path: Path):
    """[(case_id, folder, campo, valor_actual, valor_docs, gravedad, nota)]  — solo la sección 'Discrepancias por caso'."""
    out = []
    cur_id, cur_folder = None, ""
    in_appendix = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Apéndice"):
            in_appendix = True
        if in_appendix:
            continue
        m = _RE_HEADER.match(line)
        if m:
            cur_id, cur_folder = int(m.group(1)), m.group(2)
            continue
        m = _RE_ROW.match(line)
        if m and cur_id is not None and m.group(1).lower() not in ("campo",):
            campo, va, vd, grav, nota = m.group(1).strip().lower(), m.group(2), m.group(3), m.group(4), m.group(5)
            out.append((cur_id, cur_folder, campo, va, vd, grav, nota))
    return out


def _rad_year(c: Case):
    m = _RAD_YEAR.match((c.radicado_23_digitos or "").replace("-", "").replace(" ", ""))
    if m:
        y = int(m.group(2))
        if 2015 <= y <= 2030:
            return y
    return None


def _clean(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "")).strip().strip('"').strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    reports_dir = ROOT / "reports"
    if args.report:
        rpt_path = Path(args.report)
    else:
        cands = sorted(reports_dir.glob("revision_deepseek_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        cands = [p for p in cands if "resumen" not in p.name]
        if not cands:
            print("No encuentro reports/revision_deepseek_*.md", file=sys.stderr)
            return 1
        rpt_path = cands[0]
    print(f"Reporte fuente: {rpt_path}")
    discr = _parse_report(rpt_path)
    print(f"Discrepancias parseadas: {len(discr)}")

    # casos conflados (algún nota menciona docs de otro expediente)
    conflated: dict[int, list] = {}
    for cid, folder, campo, va, vd, grav, nota in discr:
        if _RE_CONFLATED.search(nota or ""):
            conflated.setdefault(cid, []).append((campo, _clean(nota)[:160]))
    print(f"Expedientes CONFLADOS (docs de otra tutela mezclados): {len(conflated)}\n")

    # ── reporte corto + CSV (todas las 'alta', agrupadas por campo) ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    altas = [d for d in discr if d[5] == "alta"]
    by_campo: dict[str, list] = {}
    for d in altas:
        by_campo.setdefault(d[2], []).append(d)
    short_rpt = reports_dir / f"revision_deepseek_resumen_{ts}.md"
    with open(short_rpt, "w", encoding="utf-8") as fh:
        fh.write(f"# Discrepancias DeepSeek — solo gravedad ALTA, agrupadas por campo — {ts}\n\n")
        fh.write(f"Total discrepancias 'alta': **{len(altas)}** · expedientes conflados: **{len(conflated)}** (no se autocorrigen, ver abajo).\n\n")
        for campo in sorted(by_campo, key=lambda k: -len(by_campo[k])):
            fh.write(f"\n## `{campo}` — {len(by_campo[campo])} casos\n\n")
            fh.write("| # | Carpeta | Extracción | Según documentos | Nota |\n|---|---|---|---|---|\n")
            for cid, folder, c, va, vd, g, nota in sorted(by_campo[campo]):
                cv = lambda x: str(x or "").replace("|", "\\|").replace("\n", " ")[:220]
                fh.write(f"| {cid} | {cv(folder)[:40]} | {cv(va)} | {cv(vd)} | {cv(nota)} |\n")
        fh.write("\n\n---\n\n## Expedientes conflados (revisar/separar a mano)\n\n")
        for cid in sorted(conflated):
            fh.write(f"- **#{cid}** — {'; '.join(f'{c}: {n}' for c, n in conflated[cid][:3])}\n")
    csv_path = reports_dir / f"revision_deepseek_alta_{ts}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "carpeta", "campo", "valor_actual", "valor_documentos", "gravedad", "conflado", "nota"])
        for cid, folder, c, va, vd, g, nota in altas:
            w.writerow([cid, folder, c, va, vd, g, "SÍ" if cid in conflated else "", _clean(nota)])
    print(f"Reporte corto: {short_rpt}")
    print(f"CSV: {csv_path}\n")

    # ── aplicar correcciones conservadoras (solo en casos NO conflados) ──
    db = SessionLocal()
    changes: dict[str, int] = {}
    asunto_dirty: set[int] = set()
    fallo_dirty: set[int] = set()
    touched: set[int] = set()
    try:
        for cid, folder, campo, va, vd, grav, nota in altas:
            if grav != "alta" or cid in conflated:
                continue
            c = db.get(Case, cid)
            if not c:
                continue
            vd_c = _clean(vd)
            vd_low = vd_c.lower()
            cur = (str(getattr(c, campo, "") or "")).strip() if hasattr(c, campo) else None

            def _set(field, value):
                if args.apply:
                    setattr(c, field, value)
                changes[field] = changes.get(field, 0) + 1
                touched.add(cid)

            if campo == "asunto":
                # solo si la extracción tiene un código corto y DeepSeek dio una frase real
                if (cur or "").upper() in {"TRASLADO","NOMBRAMIENTO","MATRICULA","INCIDENTE_DESACATO","SIN_DETERMINAR",
                    "PENSION","PROTECCION_MENOR","INCLUSION_DISCAPACIDAD","TUTELA_GENERICA","TESORERIA","SALUD_DOCENTE",
                    "TRANSPORTE_ESCOLAR","SALARIO","REINTEGRO","DERECHO_PETICION","CESANTIAS","PRESTACIONES_SOCIALES",
                    "CALIDAD_EDUCATIVA","COBERTURA"} or len((cur or "").split()) <= 2:
                    if vd_low not in _META_VALS and 8 <= len(vd_c) <= 220 and not vd_low.startswith("coincide"):
                        _set("asunto", vd_c[:220]); asunto_dirty.add(cid)
            elif campo == "ciudad":
                u = vd_c.upper()
                # tomar solo la 1ª palabra-ciudad si DeepSeek puso "MEDELLÍN (radicación); CIMITARRA (sentencia)"
                head = re.split(r"[;(]", u)[0].strip()
                head = re.sub(r"\s+SANTANDER$|\(SANTANDER\)", "", head).strip()
                if (head in MUNICIPIOS_SANTANDER) or (head in {"BOGOTÁ","BOGOTA","MEDELLÍN","MEDELLIN","CALI","BARRANQUILLA"}) or \
                   (re.fullmatch(r"[A-ZÁÉÍÓÚÑ ]{3,30}", head) and " DE" not in f" {head} " and head not in {"FAMILIA","CIVIL","PENAL","LABORAL","PROMISCUO","MUNICIPAL","CIRCUITO"}):
                    if head and head != (cur or "").upper():
                        _set("ciudad", head)
            elif campo in ("fecha_ingreso","fecha_fallo_1st","fecha_fallo_2nd","fecha_respuesta","fecha_apertura_incidente"):
                if _RE_DATE.match(vd_c):
                    ok = True
                    if campo == "fecha_ingreso":
                        ry = _rad_year(c)
                        yr = int(vd_c.split("/")[-1])
                        if ry is not None and abs(yr - ry) > 1:
                            ok = False
                    if ok and vd_c != cur:
                        _set(campo, vd_c)
            elif campo == "estado":
                # no se aplica directo: 'estado' es derivado; al final se re-deriva para todos los tocados
                touched.add(cid)
            elif campo == "quien_impugno":
                if vd_low not in _META_VALS and 3 <= len(vd_c) <= 150:
                    _set("quien_impugno", vd_c[:150])
            elif campo == "impugnacion":
                if vd_c.upper() in ("SI","NO") and vd_c.upper() != (cur or "").upper():
                    _set("impugnacion", vd_c.upper())
                elif vd_low in _META_VALS and re.search(r"(?i)no\s+(consta|hay|obra)\s+impugnaci", nota or "") and (cur or "").upper() == "SI":
                    _set("impugnacion", "NO")
            elif campo in ("incidente","decision_incidente"):
                if vd_low not in _META_VALS and 2 <= len(vd_c) <= 220:
                    _set(campo, vd_c[:220])
            elif campo == "sentido_fallo_1st" or campo == "sentido_fallo_2nd":
                if vd_c.upper() in _FALLO_WORDS and vd_c.upper() != (cur or "").upper():
                    _set(campo, vd_c.upper()); fallo_dirty.add(cid)
                elif vd_low in _META_VALS and _NO_FALLO_NOTE.search(nota or "") and cur:
                    if args.apply:
                        setattr(c, campo, None)
                    changes[campo + " (vaciado)"] = changes.get(campo + " (vaciado)", 0) + 1
                    fallo_dirty.add(cid)
            elif campo == "juzgado":
                if vd_c.upper().startswith("JUZGADO") and 10 <= len(vd_c) <= 160 and vd_c.upper() != (cur or "").upper():
                    _set("juzgado", vd_c[:160])
            elif campo == "accionados":
                if vd_low not in _META_VALS and 10 <= len(vd_c) <= 1500 and not vd_c.lower().startswith(("no ","el doc","la extrac")):
                    # solo si añade información (más largo o claramente distinto)
                    if len(vd_c) > len(cur or "") or _clean(cur).lower() not in vd_c.lower():
                        _set("accionados", vd_c[:1500])
            elif campo == "pretensiones":
                if _CONTESTACION_MARKERS.search(cur or "") and vd_low not in _META_VALS and 15 <= len(vd_c) <= 3000 \
                   and not vd_c.lower().startswith(("no se especific","no constan","no consta")):
                    _set("pretensiones", vd_c[:3000])
            # accionante, derecho_vulnerado, oficina_responsable, categoria_tematica → NO se tocan

        # re-derivar categoria_tematica de los asuntos cambiados
        n_cat = 0
        if asunto_dirty:
            try:
                from backend.cognition.legal_schema import categoria_tematica_de_asunto
                for cid in asunto_dirty:
                    c = db.get(Case, cid)
                    nueva = categoria_tematica_de_asunto(c.asunto or "")
                    if nueva and nueva != (c.categoria_tematica or ""):
                        if args.apply:
                            c.categoria_tematica = nueva
                        n_cat += 1
            except Exception as e:  # noqa: BLE001
                print(f"  (no se pudo re-derivar categoria_tematica: {e})")
        # re-derivar estado para TODOS los casos tocados (estado es derivado → mantiene consistencia)
        n_est = 0
        try:
            from backend.v9.field_extractor import extract_estado_for_case
            for cid in touched:
                c = db.get(Case, cid)
                nuevo = extract_estado_for_case(db, c)
                if nuevo and nuevo != (c.estado or ""):
                    if args.apply:
                        c.estado = nuevo
                    n_est += 1
        except Exception as e:  # noqa: BLE001
            print(f"  (no se pudo re-derivar estado: {e})")

        if args.apply:
            db.commit()
        print(f"{'APLICADO' if args.apply else 'DRY-RUN'} — celdas {'cambiadas' if args.apply else 'a cambiar'} (solo casos no conflados):")
        for f in sorted(changes):
            print(f"  {f:28s}: {changes[f]}")
        print(f"  categoria_tematica (re-derivada): {n_cat}")
        print(f"  estado (re-derivado): {n_est}")
        print(f"\nExpedientes conflados que NO se tocaron (separar a mano): {sorted(conflated)}")
        print(f"Total celdas: {sum(changes.values()) + n_cat + n_est}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
