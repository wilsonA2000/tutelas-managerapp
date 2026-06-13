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


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 4:
        return 99
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[len(b)]


def _clasificar_conflicto(rad_url: str, rad_caso: str) -> str:
    """TYPO_MISMO_CASO (typo del juzgado) / OTRO_JUZGADO_MISMA_SEQ / DISTINTO."""
    from backend.email.rad_utils import normalize_rad23
    ru, rc = normalize_rad23(rad_url), normalize_rad23(rad_caso)
    if _lev(ru, rc) <= 2:
        return "TYPO_MISMO_CASO"
    if len(ru) >= 21 and len(rc) >= 21 and ru[:12] != rc[:12] and ru[16:21] == rc[16:21]:
        return "OTRO_JUZGADO_MISMA_SEQ"
    return "DISTINTO"


def reporte_conflictos(db, marcar: bool = True) -> int:
    """CSV: links cuyo rad23_url NO coincide (sufijo [5:21]) con el rad del caso.

    Clasifica cada conflicto y, con marcar=True, pone estado=CONFLICTO en DB a
    los que NO son typo del mismo caso (esos no deben bajarse sin revisión)."""
    rows = []
    links = db.query(ExpedienteLink).filter(
        ExpedienteLink.rad23_url != "", ExpedienteLink.case_id.isnot(None),
        ExpedienteLink.url.like("%etbcsj%"),
    ).all()
    for link in links:
        case = db.query(Case).filter(Case.id == link.case_id).first()
        if not case:
            continue
        k_url = rad23_suffix_key(link.rad23_url)
        k_case = rad23_suffix_key(case.radicado_23_digitos)
        if not k_url or (k_case and k_url == k_case):
            continue
        clase = _clasificar_conflicto(link.rad23_url, case.radicado_23_digitos or "")
        rows.append({
            "link_id": link.id, "case_id": case.id, "clase": clase,
            "folder": case.folder_name or "", "accionante": case.accionante or "",
            "rad_caso": case.radicado_23_digitos or "", "rad_url": link.rad23_url,
            "etapa": link.etapa, "juzgado": link.juzgado_hint,
            "email_id": link.email_id, "url": link.url,
        })
        if marcar and clase != "TYPO_MISMO_CASO" and link.estado in (
                "RESUELTO", "SIN_NOVEDAD", "PENDIENTE"):
            link.estado = "CONFLICTO"
            link.error_detail = (f"{clase}: rad link {link.rad23_url} ≠ rad caso "
                                 f"{case.radicado_23_digitos} — revisar antes de bajar")
    if marcar:
        db.commit()
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
