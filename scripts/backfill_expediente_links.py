#!/usr/bin/env python3
"""Backfill de links de expediente (OneDrive del juzgado) desde el corpus histórico.

Fase 1 del plan expedientes-SharePoint (memoria project_expedientes_sharepoint_poc):

  1. Cosecha (sin red): barre los documents EMAIL_MD/EMAIL_JUDICIAL (y emails.body_preview)
     buscando links sharepoint → puebla la tabla `expediente_links` (estado PENDIENTE).
  2. --resolve (con red, throttle): resuelve cada link PENDIENTE → cookie FedAuth +
     server_path + rad23_url/etapa. Actualiza estado RESUELTO/REQUIERE_ACCESO/EXPIRADO.
  3. CSV de conflictos: links cuyo rad23_url NO coincide (sufijo[5:21]) con el rad del
     caso al que está asignado su correo → candidatos a cascarón/misasignación.

Uso:
    ./venv/bin/python3 scripts/backfill_expediente_links.py            # solo cosecha
    ./venv/bin/python3 scripts/backfill_expediente_links.py --resolve  # + resolver (red)
    ./venv/bin/python3 scripts/backfill_expediente_links.py --resolve --limit 20 --throttle 1.5
"""

import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal  # noqa: E402
from backend.database.models import Case, Document, Email, ExpedienteLink  # noqa: E402
from backend.email.expediente_links import (  # noqa: E402
    harvest_expediente_links,
    parse_expediente_link,
    rad23_suffix_key,
)

CSV_OUT = Path(__file__).resolve().parent.parent / "data" / "expediente_links_conflictos.csv"


def cosechar(db) -> dict:
    """Barre docs EMAIL_* y body_preview de emails. Idempotente (url UNIQUE)."""
    stats = {"docs_revisados": 0, "links_nuevos": 0, "links_existentes": 0}
    existentes = {u for (u,) in db.query(ExpedienteLink.url).all()}

    fuentes = []
    docs = db.query(Document).filter(
        Document.doc_type.like("EMAIL%"),
        Document.extracted_text.like("%sharepoint.com%"),
    ).all()
    for d in docs:
        fuentes.append((d.extracted_text, d.email_id, d.case_id))
    emails = db.query(Email).filter(Email.body_preview.like("%sharepoint.com%")).all()
    for e in emails:
        fuentes.append((e.body_preview, e.id, e.case_id))

    for text, email_id, case_id in fuentes:
        stats["docs_revisados"] += 1
        for url in harvest_expediente_links(text):
            if url in existentes:
                stats["links_existentes"] += 1
                continue
            info = parse_expediente_link(url)
            db.add(ExpedienteLink(
                url=url, url_kind=info.kind, owner=info.owner,
                juzgado_hint=info.juzgado_hint, server_path=info.server_path,
                rad23_url=info.rad23_url, etapa=info.etapa,
                instancia_hint=info.instancia_hint, archivado=info.archivado,
                case_id=case_id, email_id=email_id,
                estado="RESUELTO" if info.rad23_url else "PENDIENTE",
            ))
            existentes.add(url)
            stats["links_nuevos"] += 1
    db.commit()
    return stats


def resolver(db, limit: int, throttle: float) -> dict:
    """Resuelve links PENDIENTE (red). Actualiza rad/etapa/estado."""
    from backend.services.expediente_fetcher import resolve_share_link
    from backend.core.time import utcnow

    stats = {"resueltos": 0, "requiere_acceso": 0, "expirados": 0, "errores": 0}
    q = db.query(ExpedienteLink).filter(ExpedienteLink.estado == "PENDIENTE")
    if limit:
        q = q.limit(limit)
    links = q.all()
    print(f"Resolviendo {len(links)} links (throttle {throttle}s)...")
    for i, link in enumerate(links, 1):
        time.sleep(throttle)
        res = resolve_share_link(link.url)
        link.last_checked = utcnow()
        estado = res.get("estado", "ERROR")
        if estado == "RESUELTO":
            link.server_path = res["server_path"]
            link.rad23_url = res["rad23_url"]
            link.etapa = res["etapa"]
            link.instancia_hint = res["instancia_hint"]
            link.archivado = bool(res["archivado"])
            link.owner = res["owner"] or link.owner
            link.juzgado_hint = (res["owner"] or "").split("_", 1)[0]
            link.estado = "RESUELTO"
            stats["resueltos"] += 1
        else:
            link.estado = estado
            link.error_detail = res.get("error_detail", "")[:300]
            key = {"REQUIERE_ACCESO": "requiere_acceso", "EXPIRADO": "expirados"}.get(estado, "errores")
            stats[key] += 1
        if i % 10 == 0:
            db.commit()
            print(f"  {i}/{len(links)} — {stats}")
    db.commit()
    return stats


def reporte_conflictos(db) -> int:
    """CSV: links cuyo rad23_url NO coincide con el rad del caso asignado."""
    rows = []
    links = db.query(ExpedienteLink).filter(
        ExpedienteLink.rad23_url != "", ExpedienteLink.case_id.isnot(None),
    ).all()
    for link in links:
        case = db.query(Case).filter(Case.id == link.case_id).first()
        if not case:
            continue
        k_url = rad23_suffix_key(link.rad23_url)
        k_case = rad23_suffix_key(case.radicado_23_digitos)
        if not k_url:
            continue
        if not k_case or k_url != k_case:
            rows.append({
                "link_id": link.id, "case_id": case.id,
                "folder": case.folder_name or "",
                "rad_caso": case.radicado_23_digitos or "",
                "rad_url": link.rad23_url,
                "etapa": link.etapa, "juzgado": link.juzgado_hint,
                "email_id": link.email_id, "url": link.url,
            })
    if rows:
        CSV_OUT.parent.mkdir(exist_ok=True)
        with open(CSV_OUT, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolve", action="store_true", help="resolver links PENDIENTE (red)")
    ap.add_argument("--limit", type=int, default=0, help="máx links a resolver")
    ap.add_argument("--throttle", type=float, default=1.0)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        print("── Cosecha (sin red) ──")
        print(cosechar(db))
        total = db.query(ExpedienteLink).count()
        por_estado = {}
        for (e,) in db.query(ExpedienteLink.estado).all():
            por_estado[e] = por_estado.get(e, 0) + 1
        print(f"Tabla expediente_links: {total} · {por_estado}")

        if args.resolve:
            print("── Resolución (red) ──")
            print(resolver(db, args.limit, args.throttle))

        n = reporte_conflictos(db)
        print(f"── Conflictos rad-URL vs rad-caso: {n} → {CSV_OUT if n else '(sin CSV)'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
