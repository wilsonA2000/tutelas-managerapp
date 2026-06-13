#!/usr/bin/env python3
"""Fetch de expedientes judiciales (Fase 2 — descarga desde OneDrive del juzgado).

Procesa los links de `expediente_links`: resuelve, lista el manifest remoto,
deduplica por sha256 contra los docs ya archivados del caso, descarga lo NUEVO
plano en la carpeta del caso (prefijo EXPJ_<etapa>_) y lo registra con la
maquinaria del self-healing (clasifica + extrae texto + verifica pertenencia).

Uso:
    ./venv/bin/python3 scripts/fetch_expedientes.py --case 395            # dry-run de un caso
    ./venv/bin/python3 scripts/fetch_expedientes.py --case 395 --apply    # descarga real
    ./venv/bin/python3 scripts/fetch_expedientes.py --all --limit 10      # dry-run batch
    ./venv/bin/python3 scripts/fetch_expedientes.py --all --apply --throttle 2
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, ExpedienteLink  # noqa: E402
from backend.services.expediente_fetcher import fetch_link  # noqa: E402


def _print_report(r: dict, case_name: str = ""):
    print(f"\n— link {r['link_id']} · case {r['case_id']} {case_name}")
    print(f"  estado: {r['estado']}" + (f" · error: {r['error']}" if r.get("error") else ""))
    if r.get("manifest"):
        print(f"  manifest remoto: {len(r['manifest'])} archivos")
        for it in r["manifest"][:12]:
            print(f"    · {it['name']} ({it['size'] >> 10}KB)")
        if len(r["manifest"]) > 12:
            print(f"    … +{len(r['manifest']) - 12} más")
    if r.get("nuevos"):
        print(f"  ✅ NUEVOS registrados ({len(r['nuevos'])}):")
        for n in r["nuevos"]:
            print(f"    + {n}")
    if r.get("duplicados"):
        print(f"  = duplicados byte-idénticos descartados: {r['duplicados']}")
    if r.get("omitidos"):
        print(f"  ~ omitidos: {len(r['omitidos'])} ({'; '.join(r['omitidos'][:4])}…)")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--case", type=int, help="procesar links de un caso")
    g.add_argument("--all", action="store_true", help="procesar todos los links accionables")
    ap.add_argument("--apply", action="store_true", help="descargar de verdad (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--throttle", type=float, default=1.0)
    ap.add_argument("--estado", default="PENDIENTE,RESUELTO",
                    help="estados a procesar (CSV). Default: PENDIENTE,RESUELTO")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        q = db.query(ExpedienteLink).filter(
            ExpedienteLink.estado.in_([e.strip() for e in args.estado.split(",")]))
        if args.case:
            q = q.filter(ExpedienteLink.case_id == args.case)
        else:
            q = q.filter(ExpedienteLink.case_id.isnot(None))
        if args.limit:
            q = q.limit(args.limit)
        links = q.all()
        print(f"{len(links)} link(s) a procesar · {'APPLY' if args.apply else 'DRY-RUN'}")

        resumen = {"DESCARGADO": 0, "SIN_NOVEDAD": 0, "RESUELTO": 0,
                   "REQUIERE_ACCESO": 0, "EXPIRADO": 0, "ERROR": 0, "nuevos": 0}
        for link in links:
            case = db.query(Case).filter(Case.id == link.case_id).first() if link.case_id else None
            r = fetch_link(db, link, dry_run=not args.apply, throttle=args.throttle)
            db.commit()
            _print_report(r, case.folder_name if case else "")
            resumen[r["estado"]] = resumen.get(r["estado"], 0) + 1
            resumen["nuevos"] += len(r.get("nuevos", []))
        print(f"\n══ RESUMEN: {resumen}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
