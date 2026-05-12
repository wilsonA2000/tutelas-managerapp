#!/usr/bin/env python3
"""Re-autoriza el acceso a Gmail (token expirado o revocado).

Abre el browser para que el usuario apruebe el acceso. Genera un nuevo
gmail_token.json con permisos para leer y modificar emails.

Uso:
    python3 scripts/reauth_gmail.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

CREDENTIALS_PATH = ROOT / "gmail_credentials.json"
TOKEN_PATH = ROOT / "gmail_token.json"


def main():
    if not CREDENTIALS_PATH.exists():
        print(f"ERROR: no existe {CREDENTIALS_PATH}")
        return 1

    # Borrar token viejo si existe
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        print(f"Token viejo borrado: {TOKEN_PATH}")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_PATH), SCOPES
    )
    print()
    print("Abriendo browser para autorización Gmail...")
    print("Después de aprobar, vuelve a la terminal.")
    print()
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json())
    print(f"\n✅ Token guardado en {TOKEN_PATH}")
    print(f"   Cuenta autorizada: {creds.id_token if hasattr(creds, 'id_token') else 'OK'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
