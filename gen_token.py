"""Generar nuevo token OAuth2 para Gmail API."""
from google_auth_oauthlib.flow import InstalledAppFlow
from pathlib import Path
import json
import subprocess

APP_DIR = Path(__file__).resolve().parent
CRED_PATH = APP_DIR / "gmail_credentials.json"
TOKEN_PATH = APP_DIR / "gmail_token.json"
TMP_TOKEN = Path("/tmp/gmail_token_new.json")

print(f"Credenciales: {CRED_PATH}", flush=True)
print(f"Token se guardara en: {TOKEN_PATH}", flush=True)

flow = InstalledAppFlow.from_client_secrets_file(
    str(CRED_PATH),
    scopes=['https://www.googleapis.com/auth/gmail.modify']
)

print("Abre http://localhost:8091 en tu navegador para autorizar:", flush=True)
creds = flow.run_local_server(port=8091, open_browser=False)

token_data = {
    'token': creds.token,
    'refresh_token': creds.refresh_token,
    'token_uri': creds.token_uri,
    'client_id': creds.client_id,
    'client_secret': creds.client_secret,
    'scopes': list(creds.scopes),
}

# Escribir a /tmp primero (Linux nativo), luego copiar a Windows
with open(str(TMP_TOKEN), 'w') as f:
    json.dump(token_data, f, indent=2)

# Copiar con cp para forzar write al NTFS
subprocess.run(['cp', '-f', str(TMP_TOKEN), str(TOKEN_PATH)], check=True)

# Verificar
with open(str(TOKEN_PATH)) as f:
    verify = json.load(f)

print(f'Token generado OK', flush=True)
print(f'Client ID: {verify["client_id"][:40]}...', flush=True)
print(f'Token: {verify["token"][:25]}...', flush=True)
