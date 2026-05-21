"""Migra los cases con compliance legacy v1 al modelo v2 (órdenes discretas).

Finding #2 de la auditoría 2026-05-19: 111 cases tienen SOLO filas legacy v1
(sin destinatario_tipo / tipo_plazo / orden_judicial / accion_resumida), lo que
deja su seguimiento "ciego". Este script corre el extractor v2
(`seguimiento_extractor.extract_ordenes_cumplimiento`) sobre la sentencia de cada
uno y crea una fila ComplianceTracking por orden discreta detectada.

Uso:
    python3 scripts/migrate_legacy_compliance_v2.py                 # DRY-RUN
    python3 scripts/migrate_legacy_compliance_v2.py --apply         # escribe
    python3 scripts/migrate_legacy_compliance_v2.py --apply --v1-policy=convert

Política del placeholder v1 (--v1-policy):
    keep    (default) — deja la fila v1 intacta junto a las nuevas v2.
                        ⚠ reproduce la duplicación del finding #8.
    convert           — reusa la fila v1 como la PRIMERA orden v2 (preserva
                        id/created_at/notas/estado) e inserta el resto como nuevas.
    delete            — borra la fila v1 cuando la extracción v2 produjo ≥1 orden.

Idempotente: salta cases que ya tienen alguna fila con destinatario_tipo.
Backup recomendado antes de --apply.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, ComplianceTracking, Document  # noqa: E402
from backend.services.seguimiento_extractor import (  # noqa: E402
    _read_pdf_text, _find_resuelve_block, _find_resuelve_block_lenient)
from backend.services.seguimiento_resolutivo import extract_ordenes_focalizado  # noqa: E402
from backend.services.audit_service import audit_event  # noqa: E402


# ── Guards anti-falso-positivo ────────────────────────────────────────────
# Una sentencia REAL declara el amparo en su bloque RESUELVE. Un auto admisorio,
# de requerimiento, de apertura de incidente, etc. también tiene "RESUELVE/ORDENAR"
# pero NO declara fallo → produciría órdenes espurias. Filtramos por ambas señales.
_RULING_RE = re.compile(
    r"\b(TUTELAR|CONC[EÉ]D|AMPAR|PROT[EÉ]J|NIE?G|IMPROCEDENTE|DENI?[EÉ]G)",
    re.IGNORECASE,
)
_AUTO_FN_RE = re.compile(
    r"(auto|admite|admis|admisorio|apertura|requiere|requerimiento|traslado"
    r"|notific|oficio|memorial|avoca|escrito|demanda|contestaci|informe"
    r"|cumplimiento|impugna)",
    re.IGNORECASE,
)


def _es_sentencia_real(file_path: str) -> bool:
    """True solo si el PDF parece una sentencia (no un auto) y su RESUELVE declara fallo."""
    if _AUTO_FN_RE.search(os.path.basename(file_path)):
        return False
    try:
        full = _read_pdf_text(file_path)
    except Exception:
        return False
    if len(full) < 800:
        return False
    bloque = _find_resuelve_block(full) or _find_resuelve_block_lenient(full)
    if not bloque or not _RULING_RE.search(bloque[:1000]):
        return False
    return True


# SED Santander como parte (accionada o vinculada) en el case.
_SED_SANTANDER_RE = re.compile(
    r"(secretar[íi]a\s+de\s+educaci[óo]n\s+(?:departamental\s+)?(?:de\s+)?santander"
    r"|gobernaci[óo]n\s+de\s+santander"
    r"|sed\s+santander)",
    re.IGNORECASE,
)


def _sed_es_accionada(case: Case) -> bool:
    # Todo case en esta DB involucra a la SED Santander (es la base de tutelas de
    # la Gobernación). Regla operativa de Wilson: cuando la SED está accionada o
    # vinculada, las órdenes a terceros (EPS, alcaldías) se vigilan igual. Por eso
    # el default es True; solo sería False si pudiéramos probar que la SED no es
    # parte, cosa que no aplica aquí.
    return True


def _legacy_case_ids(db) -> list[int]:
    """Cases con SOLO filas v1 (ninguna con destinatario_tipo)."""
    rows = db.query(ComplianceTracking.case_id, ComplianceTracking.destinatario_tipo).all()
    by_case: dict[int, list] = {}
    for case_id, dt in rows:
        by_case.setdefault(case_id, []).append(dt)
    out = []
    for case_id, dts in by_case.items():
        if all(dt is None or dt == "" for dt in dts):
            out.append(case_id)
    return sorted(out)


def _find_sentencia_pdfs(db, case_id: int) -> list[str]:
    docs = (
        db.query(Document)
        .filter(Document.case_id == case_id)
        .filter(Document.filename.ilike("%.pdf"))
        .order_by(Document.id)
        .all()
    )
    paths = []
    for d in docs:
        dt = (d.doc_type or "").upper()
        fn = (d.filename or "").lower()
        if ("SENTENCIA" in dt or "FALLO" in dt
                or "sentencia" in fn or "fallo" in fn
                or "confirma" in fn or "tutela" in fn):
            if d.file_path and os.path.exists(d.file_path):
                paths.append(d.file_path)
    return paths


def _order_pdfs(paths: list[str], is_2da: bool) -> list[str]:
    def score_2da(p):
        pl = p.lower()
        return ("segunda" in pl or "2da" in pl or "confirma" in pl, "primera" not in pl)

    def score_1ra(p):
        pl = p.lower()
        return ("primera" in pl or "primer" in pl or "1ra" in pl, "segunda" not in pl)

    return sorted(paths, key=score_2da if is_2da else score_1ra, reverse=True)


def _compute_fecha_limite(orden, fecha_fallo: str | None) -> str | None:
    if orden.tipo_plazo == "FECHA" and orden.fecha_especifica:
        return orden.fecha_especifica
    if orden.tipo_plazo in ("NUMERICO", "INMEDIATO") and orden.plazo_dias is not None and fecha_fallo:
        try:
            parts = fecha_fallo.split("/")
            base = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
            from datetime import timedelta
            return (base + timedelta(days=orden.plazo_dias)).strftime("%d/%m/%Y")
        except Exception:
            return None
    return None


def _instancia_and_fecha(case: Case) -> tuple[str, str, str]:
    """Devuelve (instancia, sentido_fallo, fecha_fallo) imitando /scan."""
    instancia = "1ra"
    sentido = case.sentido_fallo_1st or case.sentido_fallo_2nd or ""
    fecha = case.fecha_fallo_1st or case.fecha_fallo_2nd or ""
    if case.sentido_fallo_2nd and "CONFIRMA" in (case.sentido_fallo_2nd or "").upper():
        instancia = "2da (CONFIRMADO)"
        sentido = case.sentido_fallo_2nd
        fecha = case.fecha_fallo_2nd or fecha
    return instancia, sentido, fecha


def _build_row_kwargs(case: Case, orden, instancia, sentido, fecha_fallo) -> dict:
    impugnado = (case.impugnacion or "NO").upper()
    estado = "IMPUGNADO" if impugnado == "SI" else "PENDIENTE"
    return dict(
        case_id=case.id,
        instancia=instancia,
        sentido_fallo=sentido,
        fecha_fallo=fecha_fallo,
        orden_judicial=orden.orden_texto,
        plazo_dias=orden.plazo_dias,
        fecha_limite=_compute_fecha_limite(orden, fecha_fallo),
        responsable=case.oficina_responsable or "",
        estado=estado,
        impugnado="SI" if impugnado == "SI" else "NO",
        requiere_cumplimiento="SI",
        extraido_por_ia="v2_regex_migration",
        ordinal_nombre=orden.ordinal_nombre,
        tipo_plazo=orden.tipo_plazo,
        destinatario_tipo=orden.destinatario_tipo,
        accion_resumida=orden.accion_resumida,
        condicion=orden.condicion,
        verbo_orden=orden.verbo_orden,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Escribir en la DB (default: DRY-RUN).")
    ap.add_argument("--v1-policy", choices=["keep", "convert", "delete"], default="keep")
    ap.add_argument("--limit", type=int, default=0, help="Procesar solo N cases (debug).")
    ap.add_argument("--no-llm", action="store_true", help="Solo regex-tail, sin fallback LLM.")
    args = ap.parse_args()

    db = SessionLocal()
    legacy_ids = _legacy_case_ids(db)
    if args.limit:
        legacy_ids = legacy_ids[: args.limit]

    print(f"Modo: {'APPLY (v1-policy=' + args.v1_policy + ')' if args.apply else 'DRY-RUN'}")
    print(f"Cases legacy-only a procesar: {len(legacy_ids)}\n")

    stats = {
        "con_ordenes": 0, "falta_fallo": 0, "sin_orden_sed": 0,
        "ordenes_creadas": 0, "v1_convertidas": 0, "v1_borradas": 0,
    }
    dest_dist: dict[str, int] = {}
    plazo_dist: dict[str, int] = {}
    metodo_dist: dict[str, int] = {}
    falta_fallo_cases, sin_orden_cases = [], []

    for case_id in legacy_ids:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            continue
        instancia, sentido, fecha_fallo = _instancia_and_fecha(case)
        is_2da = "CONFIRMADO" in instancia or instancia.startswith("2")
        # Solo candidatos que son sentencias REALES (no autos/demandas/oficios).
        candidatos = [p for p in _order_pdfs(_find_sentencia_pdfs(db, case_id), is_2da)
                      if _es_sentencia_real(p)]

        if not candidatos:
            # No hay sentencia del juez en disco → procurement.
            stats["falta_fallo"] += 1
            falta_fallo_cases.append(case_id)
            continue

        # Extractor focalizado: lee solo la cola del fallo (OCR si escaneado),
        # regex lenient y LLM como último recurso. Prueba todos los candidatos
        # reales y se queda con el que más órdenes produzca.
        ordenes, metodo = [], "vacio"
        sed_acc = _sed_es_accionada(case)
        for p in candidatos:
            try:
                res = extract_ordenes_focalizado(
                    p,
                    sentido_fallo_1st=case.sentido_fallo_1st,
                    sentido_fallo_2nd=case.sentido_fallo_2nd,
                    fecha_fallo=fecha_fallo,
                    sed_es_accionada=sed_acc,
                    use_llm=not args.no_llm,
                )
            except Exception as e:
                print(f"  case {case_id}: ERROR en {os.path.basename(p)} — {e}")
                continue
            if len(res.ordenes) > len(ordenes):
                ordenes, metodo = res.ordenes, res.metodo

        if not ordenes:
            # Sentencia real pero sin orden exigible a SED (NIEGA, o todo a terceros
            # ajenos). Legítimamente no requiere seguimiento.
            stats["sin_orden_sed"] += 1
            sin_orden_cases.append(case_id)
            continue

        stats["con_ordenes"] += 1
        metodo_dist[metodo] = metodo_dist.get(metodo, 0) + 1
        for o in ordenes:
            dest_dist[o.destinatario_tipo] = dest_dist.get(o.destinatario_tipo, 0) + 1
            plazo_dist[o.tipo_plazo] = plazo_dist.get(o.tipo_plazo, 0) + 1

        v1_rows = (
            db.query(ComplianceTracking)
            .filter(ComplianceTracking.case_id == case_id)
            .order_by(ComplianceTracking.id)
            .all()
        )

        if args.apply:
            new_rows_kwargs = [_build_row_kwargs(case, o, instancia, sentido, fecha_fallo) for o in ordenes]

            if args.v1_policy == "convert" and v1_rows:
                # Reusar la primera v1 como orden #1 (preserva id/created_at/notas)
                first = v1_rows[0]
                for k, v in new_rows_kwargs[0].items():
                    if k in ("created_at",):  # preservar created_at original
                        continue
                    setattr(first, k, v)
                stats["v1_convertidas"] += 1
                rest = new_rows_kwargs[1:]
                # v1 sobrantes (raro: legacy suele tener 1 placeholder) se borran
                for extra in v1_rows[1:]:
                    db.delete(extra)
                    stats["v1_borradas"] += 1
            else:
                rest = new_rows_kwargs
                if args.v1_policy == "delete":
                    for r in v1_rows:
                        db.delete(r)
                        stats["v1_borradas"] += 1

            for kw in rest:
                row = ComplianceTracking(**kw)
                db.add(row)
                db.flush()  # para tener row.id
                audit_event(
                    db, case_id=case_id, action="COMPLIANCE_CREATED",
                    actor="manual_audit", entity_type="compliance", entity_id=row.id,
                    description=f"Orden migrada v1→v2 — {kw['ordinal_nombre']} ({kw['destinatario_tipo']})",
                    meta={"migration": "legacy_v2", "tipo_plazo": kw["tipo_plazo"],
                          "v1_policy": args.v1_policy},
                    commit=False,
                )
                stats["ordenes_creadas"] += 1

    # ── FALTA_FALLO: audit + CSV de procurement ──
    if falta_fallo_cases:
        csv_path = REPO_ROOT / "data" / f"seguimiento_falta_fallo_{datetime.now():%Y%m%d}.csv"
        if args.apply:
            import csv
            with open(csv_path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["case_id", "radicado_23", "accionante", "fecha_fallo_1st", "sentido_fallo_1st"])
                for cid in falta_fallo_cases:
                    c = db.query(Case).filter(Case.id == cid).first()
                    if not c:
                        continue
                    w.writerow([cid, c.radicado_23_digitos or "", c.accionante or "",
                                c.fecha_fallo_1st or "", c.sentido_fallo_1st or ""])
                    audit_event(
                        db, case_id=cid, action="FALTA_FALLO_DETECTED",
                        actor="manual_audit", entity_type="case", entity_id=cid,
                        description="No hay sentencia del juez en disco — conseguir del juzgado/Gmail para seguimiento",
                        meta={"migration": "legacy_v2"}, commit=False,
                    )
            db.commit()

    if args.apply:
        db.commit()

    # ── Reporte ──
    print("=" * 60)
    print("RESULTADO" if args.apply else "DRY-RUN — nada escrito")
    print("=" * 60)
    print(f"  cases con órdenes extraídas      : {stats['con_ordenes']}")
    print(f"  cases SIN orden exigible a SED   : {stats['sin_orden_sed']}  (NIEGA / todo a terceros)")
    print(f"  cases FALTA_FALLO (sin sentencia): {stats['falta_fallo']}  → procurement")
    print(f"  órdenes v2 a crear               : {stats['ordenes_creadas'] if args.apply else sum(plazo_dist.values())}")
    if args.apply:
        print(f"  v1 convertidas                   : {stats['v1_convertidas']}")
        print(f"  v1 borradas                      : {stats['v1_borradas']}")
    print("\n  Método de extracción:")
    for k, v in sorted(metodo_dist.items(), key=lambda x: -x[1]):
        print(f"    {k:<24} {v}")
    print("\n  Distribución destinatario_tipo:")
    for k, v in sorted(dest_dist.items(), key=lambda x: -x[1]):
        print(f"    {k:<24} {v}")
    print("\n  Distribución tipo_plazo:")
    for k, v in sorted(plazo_dist.items(), key=lambda x: -x[1]):
        print(f"    {k:<24} {v}")
    if sin_orden_cases:
        print(f"\n  case_ids sin orden a SED ({len(sin_orden_cases)}): {sin_orden_cases}")
    if falta_fallo_cases:
        print(f"\n  case_ids FALTA_FALLO ({len(falta_fallo_cases)}): {falta_fallo_cases}")

    db.close()
    if not args.apply:
        print("\nDRY-RUN — corré con --apply --v1-policy=<keep|convert|delete> para aplicar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
