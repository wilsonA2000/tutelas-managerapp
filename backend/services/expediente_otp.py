"""Recuperación de expedientes vía OTP (links 'personas específicas' del juzgado).

Algunos links del juzgado son share 'personas específicas': al abrirlos anónimo,
SharePoint muestra `guestaccess.aspx` (form ASP.NET WebForms) que pide el correo
del destinatario y le envía un código de verificación (OTP). El código llega al
correo al que el juzgado compartió (apoyojuridicosed@/tutelas@santander.gov.co =
el buzón monitoreado por Wilson). Al ingresarlo, se obtiene cookie FedAuth y el
expediente queda accesible como cualquier otro.

Flujo (frágil — depende del HTML de SharePoint, encapsulado aquí):
  1. trigger_otp(url, email)  → POST email → SharePoint envía código
  2. (afuera) leer el código del Gmail monitoreado
  3. submit_otp(state, code)  → POST código → sesión autenticada + server_path

PoC: el postback es ASP.NET (__VIEWSTATE + __EVENTTARGET=btnSubmitEmail). El
correo destinatario por defecto es el de la cuenta de la SED.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger("tutelas.expediente_otp")

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126 Safari/537.36")
_TIMEOUT = 30

# correos a los que el juzgado suele compartir (orden de intento)
DEFAULT_RECIPIENTS = [
    "apoyojuridicosed@santander.gov.co",
    "tutelas@santander.gov.co",
]


@dataclass
class OtpState:
    """Estado entre el trigger y el submit del código."""
    session: requests.Session
    form_action: str          # URL absoluta del guestaccess.aspx?share=...
    hidden: dict = field(default_factory=dict)  # VIEWSTATE etc. de la página del código
    email: str = ""
    host: str = ""


def _parse_hidden(html: str) -> dict:
    """Extrae los campos hidden ASP.NET (__VIEWSTATE, __EVENTVALIDATION, etc.)."""
    out = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', html, re.IGNORECASE):
        tag = m.group(0)
        n = re.search(r'name="([^"]+)"', tag)
        v = re.search(r'value="([^"]*)"', tag)
        if n:
            out[n.group(1)] = unescape(v.group(1)) if v else ""
    return out


def _form_action(html: str, base_url: str) -> str:
    m = re.search(r'<form[^>]*action="([^"]+)"', html, re.IGNORECASE)
    return urljoin(base_url, unescape(m.group(1))) if m else base_url


def _has_code_field(html: str) -> bool:
    """La página de ingreso de código tiene un input para el OTP."""
    return bool(re.search(r'txt(VerificationCode|Otp|GuestAccessCode|Pin)', html, re.IGNORECASE))


def _has_email_field(html: str) -> bool:
    return "txtTOAAEmail" in html


def trigger_otp(url: str, email: str, session: requests.Session | None = None) -> dict:
    """Dispara el envío del OTP al correo. Retorna {estado, state?, error_detail?}.

    estado: OTP_ENVIADO (código en camino) · YA_ABIERTO (no pedía OTP) ·
            EMAIL_RECHAZADO · EXPIRADO · ERROR
    """
    s = session or requests.Session()
    s.headers["User-Agent"] = _UA
    try:
        r = s.get(url, allow_redirects=True, timeout=_TIMEOUT)
    except requests.RequestException as e:
        return {"estado": "ERROR", "error_detail": f"red: {str(e)[:120]}"}

    final = r.url
    html = r.text
    if "onedrive.aspx?id=" in final:
        return {"estado": "YA_ABIERTO"}  # no requería OTP
    if not _has_email_field(html):
        title = (re.search(r"<title>\s*([^<]*?)\s*</title>", html, re.DOTALL) or [None, ""])
        return {"estado": "EXPIRADO", "error_detail": "no es página de OTP (¿caducado?)"}

    action = _form_action(html, final)
    payload = _parse_hidden(html)
    payload["__EVENTTARGET"] = "btnSubmitEmail"
    payload["__EVENTARGUMENT"] = ""
    payload["txtTOAAEmail"] = email

    try:
        r2 = s.post(action, data=payload, allow_redirects=True, timeout=_TIMEOUT)
    except requests.RequestException as e:
        return {"estado": "ERROR", "error_detail": f"red POST: {str(e)[:120]}"}

    h2 = r2.text
    if _has_code_field(h2):
        st = OtpState(session=s, form_action=_form_action(h2, r2.url),
                      hidden=_parse_hidden(h2), email=email,
                      host=urlparse(r2.url).netloc)
        return {"estado": "OTP_ENVIADO", "state": st}
    if "onedrive.aspx?id=" in r2.url:
        return {"estado": "YA_ABIERTO"}
    # email no autorizado → SharePoint remuestra el form de email (sin code field)
    if _has_email_field(h2):
        return {"estado": "EMAIL_RECHAZADO",
                "error_detail": f"SharePoint no aceptó {email} como destinatario autorizado"}
    return {"estado": "ERROR", "error_detail": "respuesta inesperada tras enviar email"}


# patrón del código en el correo de SharePoint/Microsoft (6-8 dígitos)
_CODE_RE = re.compile(r"\b(\d{6,8})\b")


def extract_code_from_text(text: str) -> str:
    """Extrae el código OTP del cuerpo del correo de SharePoint."""
    if not text:
        return ""
    # priorizar líneas que mencionen 'código'/'code'
    for ln in text.split("\n"):
        if re.search(r"c[oó]digo|code|verif", ln, re.IGNORECASE):
            m = _CODE_RE.search(ln)
            if m:
                return m.group(1)
    m = _CODE_RE.search(text)
    return m.group(1) if m else ""


def submit_otp(state: OtpState, code: str) -> dict:
    """Envía el código OTP. Retorna {estado, session?, server_path?}.

    estado: AUTENTICADO (con session+server_path) · CODIGO_INVALIDO · ERROR
    """
    payload = dict(state.hidden)
    # el campo del código varía; setear todos los candidatos presentes
    for cand in ("txtVerificationCode", "txtOtp", "txtGuestAccessCode", "txtPin"):
        if cand in payload or True:
            payload[cand] = code
    payload["__EVENTTARGET"] = "btnVerifyCode"
    payload["__EVENTARGUMENT"] = ""
    try:
        r = state.session.post(state.form_action, data=payload,
                               allow_redirects=True, timeout=_TIMEOUT)
    except requests.RequestException as e:
        return {"estado": "ERROR", "error_detail": f"red: {str(e)[:120]}"}

    if "onedrive.aspx?id=" in r.url:
        from backend.email.expediente_links import parse_expediente_link
        info = parse_expediente_link(r.url)
        return {"estado": "AUTENTICADO", "session": state.session,
                "host": urlparse(r.url).netloc, "server_path": info.server_path}
    if _has_code_field(r.text):
        return {"estado": "CODIGO_INVALIDO", "error_detail": "el código no fue aceptado"}
    return {"estado": "ERROR", "error_detail": "respuesta inesperada tras enviar código"}
