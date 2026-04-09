#!/usr/bin/env python3
"""Cleanup Diagnosis CLI v4.8.

Genera un reporte del desorden actual (DB + disco) en JSON o markdown.
No modifica nada — solo lee.

Uso:
    python scripts/diagnosis.py                         # markdown a stdout
    python scripts/diagnosis.py --output json           # JSON a stdout
    python scripts/diagnosis.py --save data/diag.md     # guardar en archivo
"""

import argparse
import json
import sys
from pathlib import Path

# Path setup para que los imports del backend funcionen
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import SessionLocal  # noqa: E402
from backend.services.cleanup_diagnosis import diagnose, render_markdown  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Cleanup diagnosis v4.8")
    parser.add_argument(
        "--output",
        choices=["json", "md"],
        default="md",
        help="Formato de salida (default: md)",
    )
    parser.add_argument(
        "--save",
        help="Guardar el reporte en este archivo (en vez de imprimir a stdout)",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        report = diagnose(db)

    if args.output == "json":
        content = json.dumps(report, indent=2, default=str)
    else:
        content = render_markdown(report)

    if args.save:
        path = Path(args.save)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"Reporte guardado en: {path}", file=sys.stderr)
        # Resumen corto a stdout
        t = report.get("totals", {})
        print(f"  Casos: {t.get('cases', 0)} / Documents: {t.get('documents', 0)} / Emails: {t.get('emails', 0)}")
        print(f"  Fragmentos: {len(report.get('fragments', []))}")
        print(f"  Grupos auto-mergeables: {report.get('identity_groups', {}).get('auto_count', 0)}")
        print(f"  Docs sin hash: {report.get('docs_without_hash', {}).get('count', 0)}")
        print(f"  Docs NO_PERTENECE: {report.get('docs_no_pertenece', {}).get('count', 0)}")
    else:
        print(content)


if __name__ == "__main__":
    main()
