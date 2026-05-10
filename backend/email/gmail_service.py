"""Cliente Gmail API mínimo (auth + servicio autenticado).

Lee gmail_credentials.json + gmail_token.json del root del proyecto.
Refresca el token automáticamente cuando expira.
"""
from __future__ import annotations

import json
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

_APP_DIR = Path(__file__).resolve().parent.parent.parent
TOKEN_PATH = _APP_DIR / "gmail_token.json"
CREDENTIALS_PATH = _APP_DIR / "gmail_credentials.json"


def _get_gmail_service():
    """Obtener servicio Gmail API autenticado con auto-refresh de token."""
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(
            f"gmail_token.json no encontrado en {TOKEN_PATH}. "
            "Ejecute python gen_token.py para autorizar OAuth2."
        )

    with open(TOKEN_PATH) as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes"),
    )

    if creds.expired or not creds.valid:
        creds.refresh(Request())
        token_data["token"] = creds.token
        with open(TOKEN_PATH, "w") as f:
            json.dump(token_data, f, indent=2)

    return build("gmail", "v1", credentials=creds, cache_discovery=False)
