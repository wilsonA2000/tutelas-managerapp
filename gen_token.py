"""Generar nuevo token OAuth2 para Gmail API.

Multiplataforma: detecta WSL y usa workaround /tmp+cp para evitar bugs de
escritura directa a NTFS desde WSL. En Windows nativo o Linux puro escribe
directo al destino.

Uso:
    python gen_token.py
"""
from google_auth_oauthlib.flow import InstalledAppFlow
from pathlib import Path
import json
import platform
import shutil
import sys

APP_DIR = Path(__file__).resolve().parent
CRED_PATH = APP_DIR / "gmail_credentials.json"
TOKEN_PATH = APP_DIR / "gmail_token.json"


def _is_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except FileNotFoundError:
        return False


def main() -> int:
    if not CRED_PATH.exists():
        print(f"ERROR: no se encontro {CRED_PATH}", file=sys.stderr)
        print("Descarga gmail_credentials.json desde Google Cloud Console.", file=sys.stderr)
        return 1

    print(f"Credenciales: {CRED_PATH}", flush=True)
    print(f"Token se guardara en: {TOKEN_PATH}", flush=True)

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CRED_PATH),
        scopes=['https://www.googleapis.com/auth/gmail.modify'],
    )

    print("\nAbre http://localhost:8091 en tu navegador para autorizar:", flush=True)
    open_browser = platform.system() == "Windows"
    creds = flow.run_local_server(port=8091, open_browser=open_browser)

    token_data = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': list(creds.scopes),
    }

    if _is_wsl():
        # WSL→NTFS tiene bug ocasional al escribir JSON directo; pasar por /tmp lo evita.
        tmp_token = Path("/tmp/gmail_token_new.json")
        with open(tmp_token, 'w') as f:
            json.dump(token_data, f, indent=2)
        shutil.copyfile(tmp_token, TOKEN_PATH)
    else:
        with open(TOKEN_PATH, 'w') as f:
            json.dump(token_data, f, indent=2)

    with open(TOKEN_PATH) as f:
        verify = json.load(f)

    print(f"\nToken generado OK", flush=True)
    print(f"  Client ID: {verify['client_id'][:40]}...", flush=True)
    print(f"  Token:     {verify['token'][:25]}...", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
