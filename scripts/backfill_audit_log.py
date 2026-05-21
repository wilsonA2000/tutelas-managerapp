"""Backfill retroactivo de audit_log desde tablas existentes.

Fase 2a del módulo Auditoría (sesión 2026-05-19).

Genera eventos históricos en `audit_log` reconstruidos desde:
  - cases.created_at           → CASE_CREATED          (~420)
  - emails.date_received       → EMAIL_RECEIVED        (~1490, donde case_id IS NOT NULL)
  - documents JOIN emails      → DOC_ADDED             (~4674)
  - documents.extraction_*     → DOC_EXTRACTED         (23, donde extraction_method está)
  - compliance_tracking.created_at → COMPLIANCE_CREATED (~290)

Todos los eventos se marcan con `meta_json.backfill = true` para distinguirlos
de eventos vivos. Idempotente: si ya existe una fila con la misma
(case_id, action, entity_type, entity_id) y backfill=true, no se duplica.

Uso:
    # 1) DRY-RUN — muestra distribución, no escribe
    python3 scripts/backfill_audit_log.py

    # 2) APLICAR — escribe en la DB
    python3 scripts/backfill_audit_log.py --apply

Backup pre-operación: data/backups/tutelas_pre_audit_log_20260519_174640.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "tutelas.db"

ACTOR_SYSTEM = "system"
ACTOR_GMAIL = "gmail_monitor"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _existing_keys(conn: sqlite3.Connection) -> set[tuple]:
    """Devuelve set de (case_id, action, entity_type, entity_id) ya en audit_log
    con backfill=true, para no duplicar."""
    cur = conn.execute(
        """
        SELECT case_id, action, entity_type, entity_id
          FROM audit_log
         WHERE meta_json LIKE '%"backfill": true%'
            OR meta_json LIKE '%"backfill":true%'
        """
    )
    return {(r["case_id"], r["action"], r["entity_type"], r["entity_id"]) for r in cur.fetchall()}


def _insert(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Inserta filas en audit_log respetando los campos extendidos v95."""
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO audit_log
              (case_id, action, source, timestamp,
               entity_type, entity_id, field_name,
               old_value, new_value, description, meta_json)
        VALUES (:case_id, :action, :source, :timestamp,
               :entity_type, :entity_id, :field_name,
               :old_value, :new_value, :description, :meta_json)
        """,
        rows,
    )
    return len(rows)


def _meta(extra: dict | None = None) -> str:
    m = {"backfill": True}
    if extra:
        m.update(extra)
    return json.dumps(m, ensure_ascii=False)


# ---------- Builders por evento ----------


def build_case_created(conn: sqlite3.Connection, skip: set[tuple]) -> list[dict]:
    rows = []
    for r in conn.execute(
        "SELECT id, radicado_23_digitos, accionante, created_at FROM cases "
        "WHERE created_at IS NOT NULL"
    ):
        key = (r["id"], "CASE_CREATED", "case", r["id"])
        if key in skip:
            continue
        desc = "Expediente creado en el sistema"
        if r["radicado_23_digitos"]:
            desc += f" — rad {r['radicado_23_digitos']}"
        rows.append(
            dict(
                case_id=r["id"],
                action="CASE_CREATED",
                source=ACTOR_SYSTEM,
                timestamp=r["created_at"],
                entity_type="case",
                entity_id=r["id"],
                field_name=None,
                old_value=None,
                new_value=None,
                description=desc,
                meta_json=_meta(
                    {
                        "accionante": r["accionante"],
                        "radicado_23": r["radicado_23_digitos"],
                    }
                ),
            )
        )
    return rows


def build_email_received(conn: sqlite3.Connection, skip: set[tuple]) -> list[dict]:
    rows = []
    for r in conn.execute(
        """
        SELECT id, case_id, subject, sender, date_received,
               match_confidence, match_score, message_id
          FROM emails
         WHERE case_id IS NOT NULL
           AND date_received IS NOT NULL
        """
    ):
        key = (r["case_id"], "EMAIL_RECEIVED", "email", r["id"])
        if key in skip:
            continue
        subj = (r["subject"] or "").strip()
        desc = f"Correo recibido: {subj[:120]}" if subj else "Correo recibido"
        rows.append(
            dict(
                case_id=r["case_id"],
                action="EMAIL_RECEIVED",
                source=ACTOR_GMAIL,
                timestamp=r["date_received"],
                entity_type="email",
                entity_id=r["id"],
                field_name=None,
                old_value=None,
                new_value=None,
                description=desc,
                meta_json=_meta(
                    {
                        "subject": subj[:200],
                        "sender": r["sender"],
                        "match_confidence": r["match_confidence"],
                        "match_score": r["match_score"],
                        "message_id": r["message_id"],
                    }
                ),
            )
        )
    return rows


def build_doc_added(conn: sqlite3.Connection, skip: set[tuple]) -> list[dict]:
    """DOC_ADDED prioridad de timestamp:
       1. emails.date_received vía email_id JOIN
       2. documents.extraction_date
       3. cases.created_at (último recurso)
    """
    rows = []
    for r in conn.execute(
        """
        SELECT d.id          AS doc_id,
               d.case_id     AS case_id,
               d.filename    AS filename,
               d.doc_type    AS doc_type,
               d.email_id    AS email_id,
               d.extraction_date AS extraction_date,
               e.date_received AS email_date,
               e.subject     AS email_subject,
               c.created_at  AS case_created
          FROM documents d
          LEFT JOIN emails e ON e.id = d.email_id
          LEFT JOIN cases  c ON c.id = d.case_id
         WHERE d.case_id IS NOT NULL
        """
    ):
        key = (r["case_id"], "DOC_ADDED", "document", r["doc_id"])
        if key in skip:
            continue
        ts = r["email_date"] or r["extraction_date"] or r["case_created"]
        if not ts:
            continue
        actor = ACTOR_GMAIL if r["email_date"] else ACTOR_SYSTEM
        fname = (r["filename"] or "").strip()
        desc = f"Documento agregado: {fname[:120]}" if fname else "Documento agregado"
        if r["doc_type"]:
            desc += f" ({r['doc_type']})"
        rows.append(
            dict(
                case_id=r["case_id"],
                action="DOC_ADDED",
                source=actor,
                timestamp=ts,
                entity_type="document",
                entity_id=r["doc_id"],
                field_name=None,
                old_value=None,
                new_value=None,
                description=desc,
                meta_json=_meta(
                    {
                        "filename": fname[:200],
                        "doc_type": r["doc_type"],
                        "email_id": r["email_id"],
                        "ts_source": (
                            "email" if r["email_date"]
                            else "extraction" if r["extraction_date"]
                            else "case"
                        ),
                    }
                ),
            )
        )
    return rows


def build_doc_extracted(conn: sqlite3.Connection, skip: set[tuple]) -> list[dict]:
    """Solo donde extraction_method está poblado (23 docs según diag previo)."""
    rows = []
    for r in conn.execute(
        """
        SELECT id, case_id, filename, doc_type,
               extraction_method, extraction_date, page_count
          FROM documents
         WHERE extraction_method IS NOT NULL
           AND extraction_date   IS NOT NULL
           AND case_id           IS NOT NULL
        """
    ):
        key = (r["case_id"], "DOC_EXTRACTED", "document", r["id"])
        if key in skip:
            continue
        method = r["extraction_method"]
        # Mantener el catálogo de actores limpio; el método va en meta_json.
        actor = "v9_regex" if method and "v9" in method.lower() else ACTOR_SYSTEM
        desc = f"Texto extraído: {r['filename']}" if r["filename"] else "Texto extraído"
        desc += f" — método {method}"
        rows.append(
            dict(
                case_id=r["case_id"],
                action="DOC_EXTRACTED",
                source=actor,
                timestamp=r["extraction_date"],
                entity_type="document",
                entity_id=r["id"],
                field_name=None,
                old_value=None,
                new_value=None,
                description=desc,
                meta_json=_meta(
                    {
                        "filename": r["filename"],
                        "method": method,
                        "page_count": r["page_count"],
                    }
                ),
            )
        )
    return rows


def build_compliance_created(conn: sqlite3.Connection, skip: set[tuple]) -> list[dict]:
    rows = []
    for r in conn.execute(
        """
        SELECT id, case_id, ordinal_nombre, instancia,
               destinatario_tipo, tipo_plazo, estado, created_at,
               accion_resumida, plazo_dias
          FROM compliance_tracking
         WHERE created_at IS NOT NULL
        """
    ):
        key = (r["case_id"], "COMPLIANCE_CREATED", "compliance", r["id"])
        if key in skip:
            continue
        ordinal = r["ordinal_nombre"] or ""
        inst = r["instancia"] or ""
        dest = r["destinatario_tipo"] or ""
        desc = f"Orden creada — {ordinal} {inst}".strip()
        if dest:
            desc += f" ({dest})"
        rows.append(
            dict(
                case_id=r["case_id"],
                action="COMPLIANCE_CREATED",
                source=ACTOR_SYSTEM,
                timestamp=r["created_at"],
                entity_type="compliance",
                entity_id=r["id"],
                field_name=None,
                old_value=None,
                new_value=None,
                description=desc,
                meta_json=_meta(
                    {
                        "ordinal_nombre": ordinal,
                        "instancia": inst,
                        "destinatario_tipo": dest,
                        "tipo_plazo": r["tipo_plazo"],
                        "estado_inicial": r["estado"],
                        "plazo_dias": r["plazo_dias"],
                        "accion_resumida": (r["accion_resumida"] or "")[:200],
                    }
                ),
            )
        )
    return rows


# ---------- Distribución / reporte ----------


def _ym(ts: str | None) -> str:
    if not ts:
        return "n/a"
    return ts[:7]


def _report(all_rows: dict[str, list[dict]]) -> None:
    total = sum(len(v) for v in all_rows.values())
    print("\n" + "=" * 64)
    print(f"DRY-RUN — eventos a insertar: {total}")
    print("=" * 64)
    print(f"{'Evento':<22} {'#':>6}")
    print("-" * 30)
    for ev, rows in all_rows.items():
        print(f"{ev:<22} {len(rows):>6}")
    print()
    print("Distribución por año-mes (muestreo):")
    for ev, rows in all_rows.items():
        if not rows:
            continue
        c = Counter(_ym(r["timestamp"]) for r in rows)
        top = sorted(c.items())
        head = ", ".join(f"{ym}:{n}" for ym, n in top[:8])
        if len(top) > 8:
            head += f"  …+{len(top)-8} meses más"
        print(f"  {ev:<22} {head}")
    print()
    print("Actores únicos:")
    actor_c = Counter()
    for rows in all_rows.values():
        for r in rows:
            actor_c[r["source"]] += 1
    for actor, n in actor_c.most_common():
        print(f"  {actor:<20} {n}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Escribir en la DB (default: DRY-RUN).")
    parser.add_argument(
        "--only",
        choices=["case", "email", "doc_added", "doc_extracted", "compliance"],
        action="append",
        help="Procesar solo estos eventos (repetir flag). Default: todos.",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: no existe {DB_PATH}", file=sys.stderr)
        return 1

    print(f"DB: {DB_PATH}")
    print(f"Modo: {'APPLY' if args.apply else 'DRY-RUN'}")
    if args.apply:
        # Aviso de backup
        bk = REPO_ROOT / "data" / "backups" / "tutelas_pre_audit_log_20260519_174640.db"
        if bk.exists():
            print(f"Backup pre-audit-log encontrado: {bk}")
        else:
            print("⚠ No se encontró el backup pre-audit-log; abortando por seguridad.")
            print("  Generá uno con:  cp data/tutelas.db data/backups/tutelas_pre_backfill_$(date +%Y%m%d_%H%M%S).db")
            return 2
    print()

    targets = set(args.only or ["case", "email", "doc_added", "doc_extracted", "compliance"])

    conn = _connect()
    skip = _existing_keys(conn)
    if skip:
        print(f"Skip: {len(skip)} eventos backfill ya existentes (no se duplicarán)")

    all_rows: dict[str, list[dict]] = {}
    if "case" in targets:
        all_rows["CASE_CREATED"] = build_case_created(conn, skip)
    if "email" in targets:
        all_rows["EMAIL_RECEIVED"] = build_email_received(conn, skip)
    if "doc_added" in targets:
        all_rows["DOC_ADDED"] = build_doc_added(conn, skip)
    if "doc_extracted" in targets:
        all_rows["DOC_EXTRACTED"] = build_doc_extracted(conn, skip)
    if "compliance" in targets:
        all_rows["COMPLIANCE_CREATED"] = build_compliance_created(conn, skip)

    _report(all_rows)

    if not args.apply:
        print("DRY-RUN — no se escribió nada. Volvé a correr con --apply para aplicar.")
        return 0

    written = 0
    for ev, rows in all_rows.items():
        n = _insert(conn, rows)
        written += n
        print(f"  insert {ev:<22} {n:>6}")
    conn.commit()
    print(f"\n✅ Aplicado: {written} eventos nuevos en audit_log.")

    # Re-conteo de control
    total_now = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    print(f"   audit_log ahora: {total_now} filas totales.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
