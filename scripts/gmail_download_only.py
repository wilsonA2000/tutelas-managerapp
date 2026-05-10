"""Descarga raw del inbox de Gmail a una carpeta plana.

Sin matching de radicado, sin DB writes, sin clasificación. Solo baja todo a:
    /home/wilsonarguello/iuris-data/_raw_emails/{message_id}/
        ├── email.md         (headers + body limpio)
        └── <attachments>    (filename original sanitizado)

Y escribe MANIFEST.csv con una fila por mensaje.

Reanudable: salta message_ids que ya tienen email.md.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import html
import logging
import re
import sys
import time
from email.utils import parseaddr
from pathlib import Path

# Permitir import de backend.* desde scripts/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.email.gmail_service import _get_gmail_service  # noqa: E402

OUT_ROOT = Path("/home/wilsonarguello/iuris-data/_raw_emails")
MANIFEST_PATH = OUT_ROOT / "MANIFEST.csv"
LOG_PATH = OUT_ROOT / "download.log"

PAGE_SIZE = 100  # máximo permitido por Gmail API
MAX_RETRIES = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH, mode="a")],
)
log = logging.getLogger("gmail-download")


def sanitize_filename(name: str) -> str:
    """Filesystem-safe filename, preservando extensión."""
    name = name or "attachment"
    name = re.sub(r"[\r\n\t]+", " ", name)
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", name)
    return name.strip()[:200]


def headers_dict(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def get_body_text(payload: dict) -> str:
    """Extraer body en texto plano (priorizando text/plain, luego text/html)."""
    def walk(part, prefer="text/plain"):
        mime = part.get("mimeType", "")
        if mime == prefer:
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
        for sub in part.get("parts", []) or []:
            r = walk(sub, prefer)
            if r:
                return r
        return None

    text = walk(payload, "text/plain")
    if text:
        return text
    html_body = walk(payload, "text/html")
    if html_body:
        # Strip tags muy básico (no Beautifulsoup para no agregar deps)
        text = re.sub(r"<style[^>]*>.*?</style>", "", html_body, flags=re.S | re.I)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S | re.I)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</p>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text
    return ""


def list_attachment_parts(payload: dict) -> list[dict]:
    """Recursivamente recolecta partes con attachmentId."""
    out: list[dict] = []

    def walk(part):
        body = part.get("body", {})
        if body.get("attachmentId") and part.get("filename"):
            out.append(part)
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return out


def call_with_retry(fn, *args, **kwargs):
    """Reintentos exponenciales para errores transitorios de Gmail API."""
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs).execute()
        except Exception as e:
            wait = 2 ** attempt
            log.warning(f"API error attempt {attempt + 1}: {e}; waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries")


def list_all_message_ids(svc) -> list[str]:
    """Listar TODOS los message_ids del inbox (paginado)."""
    ids: list[str] = []
    next_token = None
    page = 0
    while True:
        page += 1
        kwargs = dict(userId="me", maxResults=PAGE_SIZE)
        if next_token:
            kwargs["pageToken"] = next_token
        resp = call_with_retry(svc.users().messages().list, **kwargs)
        msgs = resp.get("messages", []) or []
        ids.extend(m["id"] for m in msgs)
        log.info(f"Page {page}: +{len(msgs)} ids (total {len(ids)})")
        next_token = resp.get("nextPageToken")
        if not next_token:
            break
    return ids


def download_message(svc, msg_id: str, manifest_writer) -> bool:
    """Descarga un mensaje completo a su carpeta. Returns True si se descargó (False si saltado)."""
    out_dir = OUT_ROOT / msg_id
    email_md = out_dir / "email.md"

    if email_md.exists():
        return False

    out_dir.mkdir(parents=True, exist_ok=True)

    msg = call_with_retry(
        svc.users().messages().get, userId="me", id=msg_id, format="full"
    )
    payload = msg.get("payload", {})
    h = headers_dict(payload)

    subject = h.get("subject", "")
    sender = h.get("from", "")
    to = h.get("to", "")
    cc = h.get("cc", "")
    date = h.get("date", "")
    msg_id_header = h.get("message-id", msg_id)

    body = get_body_text(payload)

    md_content = (
        f"# Email {msg_id}\n\n"
        f"- **Message-ID**: {msg_id_header}\n"
        f"- **Date**: {date}\n"
        f"- **From**: {sender}\n"
        f"- **To**: {to}\n"
        f"- **Cc**: {cc}\n"
        f"- **Subject**: {subject}\n\n"
        f"---\n\n{body}\n"
    )
    email_md.write_text(md_content, encoding="utf-8")

    # Adjuntos
    attachments = list_attachment_parts(payload)
    att_count = 0
    total_att_bytes = 0
    for part in attachments:
        att_id = part["body"]["attachmentId"]
        filename = sanitize_filename(part.get("filename", "attachment"))
        if not filename:
            continue
        try:
            att = call_with_retry(
                svc.users().messages().attachments().get,
                userId="me", messageId=msg_id, id=att_id,
            )
            data = att.get("data", "")
            if not data:
                continue
            decoded = base64.urlsafe_b64decode(data + "===")
            target = out_dir / filename
            # Si ya existe (mismo nombre, distinto attachment), agregar sufijo
            if target.exists():
                stem = target.stem
                suf = target.suffix
                target = out_dir / f"{stem}_{att_id[:8]}{suf}"
            target.write_bytes(decoded)
            att_count += 1
            total_att_bytes += len(decoded)
        except Exception as e:
            log.warning(f"Attachment fail {msg_id}/{filename}: {e}")

    sha = hashlib.sha256(md_content.encode("utf-8")).hexdigest()[:16]
    name, addr = parseaddr(sender)

    manifest_writer.writerow([
        msg_id,
        date,
        addr,
        subject.replace("\n", " ").replace(",", ";"),
        att_count,
        total_att_bytes,
        sha,
    ])
    return True


def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    log.info(f"Output: {OUT_ROOT}")

    svc = _get_gmail_service()
    log.info("Authenticated with Gmail API")

    log.info("Listing all message ids in inbox...")
    ids = list_all_message_ids(svc)
    log.info(f"Total messages in inbox: {len(ids)}")

    # Append-mode manifest (resumable)
    manifest_exists = MANIFEST_PATH.exists()
    f = MANIFEST_PATH.open("a", newline="", encoding="utf-8")
    writer = csv.writer(f)
    if not manifest_exists:
        writer.writerow([
            "message_id", "date", "from_addr", "subject",
            "attachment_count", "attachment_bytes", "email_md_sha256_short",
        ])

    downloaded = 0
    skipped = 0
    failed = 0
    try:
        for i, mid in enumerate(ids, 1):
            try:
                if download_message(svc, mid, writer):
                    downloaded += 1
                else:
                    skipped += 1
            except Exception as e:
                log.error(f"FAIL {mid}: {e}")
                failed += 1
            if i % 50 == 0:
                f.flush()
                log.info(f"Progress {i}/{len(ids)} — downloaded={downloaded} skipped={skipped} failed={failed}")
    finally:
        f.close()

    log.info(
        f"DONE total={len(ids)} downloaded={downloaded} "
        f"skipped={skipped} failed={failed}"
    )


if __name__ == "__main__":
    main()
