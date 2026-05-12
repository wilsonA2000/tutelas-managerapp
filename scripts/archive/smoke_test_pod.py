"""Smoke test del extraction worker remoto.

Uso:
    export REMOTE_EXTRACTION_URL=https://<pod-id>-8000.proxy.runpod.net
    export REMOTE_EXTRACTION_TOKEN=<tu-token>
    python scripts/smoke_test_pod.py [case_id]

Si pasas un case_id, también hace un POST real con ese caso (útil para
validar el pipeline end-to-end antes de batch).
"""

from __future__ import annotations

import os
import sys
import time


def _require_env(var: str) -> str:
    val = os.environ.get(var, "").strip()
    if not val:
        print(f"❌ Falta env var: {var}")
        sys.exit(1)
    return val


def test_health(url: str) -> bool:
    import httpx
    print(f"\n[1/3] GET {url}/health ...")
    try:
        r = httpx.get(f"{url}/health", timeout=10)
        r.raise_for_status()
        print(f"    ✅ {r.json()}")
        return True
    except Exception as e:
        print(f"    ❌ {e}")
        return False


def test_models_status(url: str, token: str) -> bool:
    import httpx
    print(f"\n[2/3] GET {url}/models/status ...")
    try:
        r = httpx.get(
            f"{url}/models/status",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        print(f"    ok: {data.get('ok')}")
        print(f"    spaCy: {data.get('models', {}).get('spacy')}")
        print(f"    paddle: {data.get('models', {}).get('paddle')}")
        print(f"    gpu: {data.get('gpu')}")
        return data.get("ok", False)
    except Exception as e:
        print(f"    ❌ {e}")
        return False


def test_extract_case(url: str, token: str, case_id: int) -> bool:
    """POST real de un caso. Requiere que el backend local tenga DB."""
    print(f"\n[3/3] POST /cognitive/extract-case case_id={case_id} ...")
    try:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        from backend.database.database import SessionLocal
        from backend.database.models import Case
        from backend.extraction.remote_client import (
            _build_zip_of_documents,
            _post_case_to_pod,
            _serialize_case_for_pod,
            _serialize_document_for_pod,
            _serialize_email_for_pod,
        )
    except Exception as e:
        print(f"    ⚠️  No se pudo importar backend (este test requiere correr desde la raíz del proyecto con .env cargado): {e}")
        return False

    db = SessionLocal()
    try:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            print(f"    ❌ Caso {case_id} no existe en la DB local")
            return False

        import json
        meta = {
            "case": _serialize_case_for_pod(case),
            "documents": [_serialize_document_for_pod(d) for d in case.documents],
            "emails": [_serialize_email_for_pod(e) for e in (case.emails or [])],
        }
        meta_json = json.dumps(meta, ensure_ascii=False).encode("utf-8")
        zip_bytes, missing = _build_zip_of_documents(case.documents)
        print(f"    case: {case.folder_name}  docs={len(case.documents)}  "
              f"zip={len(zip_bytes)/1_048_576:.1f}MB  missing={len(missing)}")

        t0 = time.time()
        result = _post_case_to_pod(url, token, 600, meta_json, zip_bytes)
        elapsed = time.time() - t0

        print(f"    ✅ {elapsed:.1f}s")
        print(f"    case_updates fields: {len(result.get('case_updates') or {})}")
        print(f"    documents_updates: {len(result.get('documents_updates') or [])}")
        print(f"    stats.status: {result.get('stats', {}).get('status')}")
        print(f"    stats.bayesian_verdicts: {result.get('stats', {}).get('bayesian_verdicts')}")
        return True
    finally:
        db.close()


def main() -> int:
    url = _require_env("REMOTE_EXTRACTION_URL")
    token = _require_env("REMOTE_EXTRACTION_TOKEN")

    ok = True
    ok &= test_health(url)
    ok &= test_models_status(url, token)

    if len(sys.argv) > 1:
        try:
            case_id = int(sys.argv[1])
        except ValueError:
            print(f"⚠️  case_id inválido: {sys.argv[1]}")
            return 2
        ok &= test_extract_case(url, token, case_id)

    print("\n" + ("✅ TODO OK" if ok else "❌ FALLOS — ver arriba"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
