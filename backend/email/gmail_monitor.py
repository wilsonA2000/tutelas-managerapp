"""Monitor de Gmail via API REST para notificaciones de tutelas.

Arquitectura: 15 funciones independientes y testeables.
Flujo: Email → Clasificar tipo → Extraer radicado → Match/Crear caso → Descargar adjuntos → Guardar .md
"""

import base64
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from backend.config import BASE_DIR
from backend.database.models import Email, Case, Document, AuditLog
from backend.database.seed import classify_document
# F0-A: helpers compartidos con el script de ingesta (misma lógica F1/F2 en ambas rutas).
from backend.email.case_resolver import (
    adopt_shell as _resolver_adopt_shell,
    match_by_rad_corto as _resolver_match_rad_corto,
    extract_juzgado_municipio as _resolver_juz_muni,
)

logger = logging.getLogger("tutelas.gmail")


def _utcnow() -> datetime:
    """UTC naive — reemplazo de datetime.utcnow() (deprecado en 3.12+).

    Mantiene el contrato naive-UTC que usa el resto del módulo (date_received,
    processed_at, etc. se guardan naive vía .replace(tzinfo=None))."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

_APP_DIR = Path(__file__).resolve().parent.parent.parent
TOKEN_PATH = _APP_DIR / "gmail_token.json"
CREDENTIALS_PATH = _APP_DIR / "gmail_credentials.json"

VALID_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx"}

# Correos que se ignoran (alertas, spam, no jurídicos)
IGNORE_SENDERS = {
    "noreply@google.com", "no-reply@accounts.google.com", "googleplay-noreply@google.com",
    # v6.0.1: newsletters de proveedores IA (rescatamos de falsos positivos en histórico)
    "info@cerebras.net", "noreply@cerebras.net",
    "no-reply@openai.com", "noreply@openai.com",
    "noreply@anthropic.com", "no-reply@anthropic.com", "claude.com",
    "noreply@deepseek.com",
    "noreply@huggingface.co",
    # LinkedIn / social / marketing genérico
    "notifications-noreply@linkedin.com", "messages-noreply@linkedin.com",
    "invitations@linkedin.com", "news-noreply@linkedin.com",
    "noreply@medium.com", "noreply@substack.com",
}
IGNORE_SUBJECTS = {
    "alerta de seguridad", "configurar tu dispositivo", "privacidad en play", "verify your",
    # v6.0.1: notificaciones de producto/newsletter (no jurídicas)
    "model deprecation notice", "new api", "pricing update",
    "weekly digest", "newsletter", "your subscription",
    "account verification", "reset your password",
}

# Typos comunes en subjects judiciales
SUBJECT_TYPOS = {
    "NOTIFIA": "NOTIFICA", "ADMISORIIO": "ADMISORIO", "NOTIFICAICON": "NOTIFICACION",
    "TUTLEA": "TUTELA", "SENTECIA": "SENTENCIA", "DESACTO": "DESACATO",
    "IMPUGNAICON": "IMPUGNACION", "AVOACAR": "AVOCAR",
}


# ═══════════════════════════════════════════════════════════
# 1. AUTENTICACIÓN GMAIL
# ═══════════════════════════════════════════════════════════

def _get_gmail_service():
    """Obtener servicio Gmail API autenticado con auto-refresh de token.
    Returns: googleapiclient.discovery.Resource del servicio Gmail."""
    if not TOKEN_PATH.exists():
        raise Exception("gmail_token.json no encontrado. Ejecute la autorizacion OAuth2.")

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


# ═══════════════════════════════════════════════════════════
# 2-6. FUNCIONES DE EXTRACCIÓN Y CLASIFICACIÓN
# ═══════════════════════════════════════════════════════════

def _normalize_typos(subject: str) -> str:
    """Corregir typos comunes en subjects judiciales.
    Returns: subject corregido."""
    result = subject or ""
    for wrong, correct in SUBJECT_TYPOS.items():
        result = result.replace(wrong, correct)
    return result


def _should_ignore(subject: str, sender: str) -> bool:
    """Determinar si un email debe ignorarse (alertas Google, spam, etc).
    Returns: True si debe ignorarse."""
    s = (sender or "").lower()
    for ignore in IGNORE_SENDERS:
        if ignore in s:
            return True
    subj_lower = (subject or "").lower()
    for ignore in IGNORE_SUBJECTS:
        if ignore in subj_lower:
            return True
    return False


def classify_email_type(subject: str, sender: str) -> str:
    """Clasificar tipo de actuación judicial del email por su subject.
    Returns: TUTELA_NUEVA|AUTO_ADMISORIO|FALLO_1RA|FALLO_2DA|IMPUGNACION|
             INCIDENTE_DESACATO|NOTIFICACION|TRASLADO|REQUERIMIENTO|SALIENTE|OTRO"""
    subj = (subject or "").upper()

    # Correos salientes (reenviados por la Gobernación)
    if "ELEMENTOS ENVIADOS" in subj or "CORREO ENVIADO" in subj:
        return "SALIENTE"

    if "INCIDENTE" in subj or "DESACATO" in subj:
        return "INCIDENTE_DESACATO"
    if "SEGUNDA INSTANCIA" in subj or "2DA INSTANCIA" in subj or "FALLO 2" in subj:
        return "FALLO_2DA"
    if "IMPUGNA" in subj:
        return "IMPUGNACION"
    if "SENTENCIA" in subj or "FALLO" in subj:
        return "FALLO_1RA"
    if "ADMITE" in subj or "ADMISORIO" in subj or "AVOCA" in subj:
        return "AUTO_ADMISORIO"
    if "TRASLADO" in subj:
        return "TRASLADO"
    if "REQUERIMIENTO" in subj:
        return "REQUERIMIENTO"
    if "NOTIFIC" in subj:
        return "NOTIFICACION"
    if "TUTELA" in subj:
        return "TUTELA_NUEVA"
    return "OTRO"


def extract_radicado(text: str) -> dict:
    """Extraer radicado judicial del texto (subject + body).
    F2 (v5.0): si existe rad_23 valido, SIEMPRE derivar rad_corto del rad_23 antes de
    probar patrones de etiqueta. Evita que "numero de radicado 20260066132" (FOREST)
    se interprete como 2026-66132 cuando el subject ya tenia "TUTELA 2026-00057".
    Returns: {'radicado_23': str, 'radicado_corto': str}"""
    from backend.agent.regex_library import (
        RAD_23_CONTINUOUS, RAD_23_WITH_SEPARATORS, RAD_T_FORMAT, RAD_LABEL, RAD_GENERIC,
        RAD_CONTINUOUS_SHORT, RAD_JUDICIAL_CONTEXT, RAD_SIX_DIGITS,
    )
    result = {"radicado_23": "", "radicado_corto": ""}

    # Ignorar la línea de anotación "**Caso:** <folder_name>" que save_email_md
    # escribe en los .md: contiene el rad del caso de destino → si se re-extrae el
    # .md (doc EMAIL_MD), ese rad es auto-referencial y contaminaría la extracción
    # si el .md estuviera traspapelado. No es contenido del email original.
    if text and "**Caso:**" in text:
        text = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("**Caso:**"))

    # Patrón 1: Radicado completo 23 dígitos (estricto primero, laxo como fallback)
    m = RAD_23_CONTINUOUS.pattern.search(text)
    if not m:
        m = RAD_23_WITH_SEPARATORS.pattern.search(text)
    if not m:
        m = re.search(r"(68[\d]{5,7}[-\s\.]?[\d]{3,4}[-\s\.]?[\d]{4}[-\s\.]?[\d]{5}[-\s\.]?[\d]{2})", text)
    if not m:
        # Formato SEGMENTADO con prefijo de municipio (juzgados penales/promiscuos):
        # "68001-3107-001-2026-00015" = DANE(5)-juzgado(4)-secc(3)-año(4)-consec(5) = rad-21.
        # Los patrones de arriba NO lo capturan (exigen ≥5 díg contiguos tras "68").
        # Este SÍ trae el prefijo de municipio (68001) que desambigua rad cortos
        # compartidos entre juzgados (ver matcher Fase 4). El " NI 6539" (nro interno)
        # queda fuera por el \b final → nunca contamina el rad23.
        m = re.search(r"\b(68\d{3}[-\s.]\d{4}[-\s.]\d{3}[-\s.]20\d{2}[-\s.]\d{5})\b", text)
    if m:
        result["radicado_23"] = m.group(1)

    # F2: PRIORITARIO — Si hay rad23 valido, derivar rad_corto directamente de el.
    # Esto PREVIENE que RAD_LABEL/RAD_GENERIC interpreten FOREST (20260066132)
    # como rad_corto (2026-66132) cuando el rad23 ya contiene el consecutivo real.
    # v6.0.1: usar derive_rad_corto_from_rad23 que tiene fallback para 21d truncado
    if result["radicado_23"]:
        from backend.email.rad_utils import derive_rad_corto_from_rad23
        derived = derive_rad_corto_from_rad23(result["radicado_23"])
        if derived:
            result["radicado_corto"] = derived
            return result

    # Patrón 2: Formato T-00053/2026
    m = RAD_T_FORMAT.pattern.search(text)
    if m:
        result["radicado_corto"] = f"{m.group(2)}-{m.group(1).zfill(5)}"
        return result

    # Patrón 3: RAD 2026-00053 o Radicado 2026-053 (regex F1 endurecido)
    m = RAD_LABEL.pattern.search(text)
    if m:
        result["radicado_corto"] = f"{m.group(1)}-{m.group(2).zfill(5)}"
        return result

    # Patrón 5: Fallback generico 20XX-NNNNN (regex F1 endurecido con separador obligatorio)
    if not result["radicado_corto"]:
        m = RAD_GENERIC.pattern.search(text)
        if m:
            result["radicado_corto"] = f"{m.group(1)}-{m.group(2).zfill(5)}"
            return result

    # v6.0.1 Patrón 6: 6 dígitos con leading-zero strip (ej. "2026-000115" → "2026-00115")
    if not result["radicado_corto"]:
        m = RAD_SIX_DIGITS.pattern.search(text)
        if m:
            seq = m.group(2).lstrip("0")
            if 1 <= len(seq) <= 5:
                result["radicado_corto"] = f"{m.group(1)}-{seq.zfill(5)}"
                return result

    # v6.0.1 Patrón 7: continuo YYYYNNNNN sin separador (9d exactos)
    if not result["radicado_corto"]:
        m = RAD_CONTINUOUS_SHORT.pattern.search(text)
        if m:
            result["radicado_corto"] = f"{m.group(1)}-{m.group(2)}"
            return result

    # v6.0.1 Patrón 8: 3-4 dígitos con marcador judicial ampliado (FALLO/TUTELA/OFICIO/etc)
    # El patrón acepta marker antes o después — dos alternativas en la regex.
    # Groups 1-2: orden MARKER ... rad. Groups 3-4: orden rad ... MARKER.
    if not result["radicado_corto"]:
        m = RAD_JUDICIAL_CONTEXT.pattern.search(text)
        if m:
            year = m.group(1) or m.group(3)
            seq = m.group(2) or m.group(4)
            if year and seq:
                result["radicado_corto"] = f"{year}-{seq.zfill(5)}"

    return result


def resolve_radicado(subject: str, body: str) -> dict:
    """Resuelve el radicado con una jerarquía de confianza explícita, evitando
    que la sopa de rads de la cadena reenviada contamine la identidad del caso.

    Bug que corrige (2026-05-22, conflación 0053→0080): el email "RESPUESTA
    TUTELA 2026-0053" (sin rad23) se asignó a 2026-0080 porque al buscar en
    `subject + body` el short-rad ajeno del body (bundle reenviado) le ganó al
    rad explícito del subject.

    Jerarquía (validada contra los 1660 emails reales — ver
    [[project_fix_matcher_subject_rad]]):
      1. rad23 en el SUBJECT → manda (ID nacional único de 23 díg).
      2. rad23 en el BODY (bloques, raíz primero) → manda. Es más autoritativo
         que un short-rad: en los 9 conflictos reales subject↔body el rad23 del
         body siempre fue el correcto (typos de año en subject, números de
         oficio espurios, números de sanción).
      3. SIN rad23 en ningún lado → short-rad del SUBJECT (anti-conflación: el
         subject es curado y señala el caso; el body trae rads ajenos).
      4. Subject sin short-rad → short-rad del body (bloques, raíz primero).

    Returns: {'radicado_23': str, 'radicado_corto': str}
    """
    subj = extract_radicado(subject or "")
    # 1. rad23 en el subject.
    if subj.get("radicado_23"):
        return subj

    blocks = _split_forwarded_blocks(body) if body else []
    scan = blocks if blocks else ([body] if body else [])

    # 2. rad23 en el body (raíz primero).
    for blk in scan:
        b = extract_radicado(blk)
        if b.get("radicado_23"):
            return b

    # 3. Sin rad23 → short-rad del subject manda.
    if subj.get("radicado_corto"):
        return subj

    # 4. Subject sin rad → short-rad del body (raíz primero).
    for blk in scan:
        b = extract_radicado(blk)
        if b.get("radicado_corto"):
            return b

    return {"radicado_23": "", "radicado_corto": ""}


def extract_forest(body: str, attachment_names: list[str]) -> str:
    """Extraer número FOREST del body del correo.
    FOREST válido SOLO proviene de tutelas@santander.gov.co.
    Returns: número FOREST (10-13 dígitos o formato nuevo con guiones) o '' si no se encuentra."""
    from backend.agent.forest_extractor import (
        FOREST_PATTERN, FOREST_NUEVO_PATTERN, FOREST_BLACKLIST, is_valid_forest,
    )

    # Prioridad: nuevo formato Gobernación con guiones (p.ej. "2-2026-104200-001912").
    mn = FOREST_NUEVO_PATTERN.search(body or "")
    if mn and mn.group(1) not in FOREST_BLACKLIST:
        return mn.group(1)

    # FOREST_PATTERN dispara con frases como "Ref:" / "número de radicación:" que pueden
    # preceder al radicado JUDICIAL (68...) — validar con is_valid_forest (exige año-prefijo)
    # para no escribir el rad23 ni un Proc# en el campo FOREST.
    m = FOREST_PATTERN.search(body or "")
    if m and m.group(1) not in FOREST_BLACKLIST and is_valid_forest(m.group(1)):
        return m.group(1)

    # NO buscar en nombres de archivos DOCX — esos números son radicados internos de salida
    return ""


def _split_forwarded_blocks(body: str) -> list[str]:
    """F6 (v5.0): partir el body en bloques de emails reenviados anidados.
    Cada bloque separado por "________________________________" + "De:"/"From:" hasta 3-4 niveles.
    Returns: lista de bloques (strings), del mas superficial al mas profundo.
    """
    if not body:
        return []
    # Separadores comunes: linea larga de underscores, ---, === o "De:"/"From:" al inicio de linea
    parts = re.split(r"(?:_{5,}|-{5,}|={5,})\s*\n", body)
    # Dentro de cada parte, subdividir por "De:"/"From:" que empieza en linea
    blocks = []
    for part in parts:
        # Algunas cadenas tienen "De: X\nEnviado: Y\n..." seguidas sin separador grafico
        sub = re.split(r"\n(?=(?:De|From):\s)", part)
        for s in sub:
            s = s.strip()
            if s:
                blocks.append(s)
    return blocks


def extract_accionante(subject: str, body: str) -> str:
    """Extraer nombre del accionante del email.
    F6 (v5.0): busca en subject + TODOS los bloques forwarded (no solo primeros 2000 chars).
    Returns: nombre en MAYÚSCULAS o '' si no se encuentra."""
    SKIP_WORDS = {
        "ACCION", "TUTELA", "AUTO", "JUZGADO", "NOTIFICACION", "SENTENCIA",
        "FALLO", "REMITE", "OFICIO", "MUNICIPAL", "CIRCUITO", "PROMISCUO",
        "SECRETARIA", "EDUCACION", "DEPARTAMENTAL", "SANTANDER", "GOBERNACION",
        "RADICADO", "NOTIFICA", "ADMISION", "COMPETENCIA", "TRASLADO",
        "BUCARAMANGA", "BARRANCABERMEJA", "FLORIDABLANCA", "COLOMBIA",
        "REPUBLICA", "HONORABLE", "DESPACHO", "URGENTE", "PERSONERIA",
    }

    patterns = [
        r"(?i)accionante[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,50})",
        r"(?i)demandante[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,50})",
        r"(?i)promovida?\s+por\s+(?:el señor |la señora )?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,50})",
    ]

    # F6: buscar en subject + cada bloque forwarded (max 5 bloques para no gastar)
    texts_to_scan = [subject or ""]
    texts_to_scan.extend(_split_forwarded_blocks(body or "")[:5])
    # Garantizar que tambien revisemos los primeros 5000 chars del body crudo
    if body and len(body) > 2000:
        texts_to_scan.append(body[:5000])

    # F6 v5.0: tokens que marcan fin del nombre del accionante (no son parte del nombre)
    # F5 (2026-05-21): + saludos/cierres de correo, ACCIONADA(S)/SECR/VINCULAD*, etc.
    # que se colaban como "nombre" (p.ej. "...CARREÑO NIÑO CORDIAL SALUDO",
    # "...GALVIS VELÁSQUEZ ACCIONADAS SECR").
    STOP_TOKENS = {
        "ACCIONADO", "ACCIONADOS", "ACCIONADA", "ACCIONADAS", "ACCIONANTE",
        "CC", "C.C", "DEMANDADO", "IDENTIFICADO", "IDENTIFICADA", "MAYOR",
        "ACTUANDO", "VS", "CONTRA", "EN", "REPRESENTACION", "REPRESENTACIÓN",
        "NOMBRE", "VINCULADO", "VINCULADOS", "VINCULADA", "SECR", "SECRETARIA",
        "SECRETARÍA", "IMPUGNA", "RESPUESTA",
        # saludos / cierres de correo
        "CORDIAL", "SALUDO", "SALUDOS", "ATENTAMENTE", "CORDIALMENTE", "GRACIAS",
        "BUENOS", "BUENAS", "BUEN", "ADJUNTO", "ADJUNTOS", "FAVOR", "AGRADEZCO",
        "QUEDO", "ATENTO", "ATENTA", "REMITO", "ENVIO", "ENVÍO", "ANEXO", "ANEXOS",
        "CONFORME", "REMITIMOS", "REMITE", "SEÑORES", "SEÑOR", "SEÑORA",
        # conectores / verbos que no forman parte de un nombre (cierran el nombre)
        "PERO", "QUE", "FUE", "RADICADA", "RADICADO", "ANTE", "MEDIANTE",
        "SEGUN", "SEGÚN", "COMO", "SOBRE", "PRESENTADA", "PRESENTADO",
        "INSTAURADA", "INSTAURADO", "INTERPUESTA", "INTERPUESTO", "PROMOVIDA",
        "PROMOVIDO", "CUYO", "CUYA", "DONDE", "PORQUE", "AVOCA", "VINCULA",
    }

    def _is_garbage_token(tok: str) -> bool:
        """Token que NO es parte de un nombre real: email pegado, código, número.
        Nombres reales raramente superan ~15 letras por palabra."""
        t = tok.strip(".,:;")
        if "@" in t or any(ch.isdigit() for ch in t):
            return True
        if len(t) > 16:  # 'KARENLORENAREYESARROYO' = email/concatenación sin espacios
            return True
        return False

    # FIX 8 — usar helpers compartidos del cognitive layer para consistencia
    # con folder_renamer/cognitive_fill (mismas reglas en monitor e ingesta).
    from backend.cognition.folder_renamer import clean_accionante as _clean
    from backend.cognition.folder_renamer import is_likely_real_name as _is_real

    for text in texts_to_scan:
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                name = re.sub(r"[\n\r]+", " ", match.group(1).strip())
                name = re.sub(r"\s+", " ", name).strip()
                # F6: truncar en el primer STOP_TOKEN (ACCIONADO, CC, etc.)
                tokens = name.split()
                trimmed = []
                for tok in tokens:
                    tu = tok.upper().strip(".,:;")
                    if tu in STOP_TOKENS:
                        break
                    if _is_garbage_token(tok):
                        break
                    # email pegado = concatenación de los nombres ya vistos ('JUANPEREZ')
                    if trimmed and tu == "".join(w.upper() for w in trimmed):
                        break
                    trimmed.append(tok)
                if trimmed:
                    name = " ".join(trimmed)
                else:
                    # la truncación dejó vacío (el match empezaba en un STOP_TOKEN,
                    # p.ej. "promovida por PERO QUE FUE RADICADA") → no es un nombre
                    continue
                # FIX 8 — sanitizar y validar con helpers compartidos
                name = _clean(name)
                if not name or not _is_real(name):
                    continue
                words = name.upper().split()
                non_skip = [w for w in words if w not in SKIP_WORDS and len(w) > 2]
                if len(non_skip) >= 2:
                    return name.upper()[:60]

    # Fallback: personería municipal mencionada en subject o body
    combined = f"{subject or ''} {(body or '')[:5000]}"
    m_pers = re.search(
        r"(?i)(?:personero|personera|personería|personeria)\s+(?:municipal\s+)?(?:de|del)\s+(?:el\s+)?([A-Za-záéíóúñÁÉÍÓÚÑ\s]{3,40})",
        combined,
    )
    if m_pers:
        municipio = m_pers.group(1).strip().upper()
        municipio = re.sub(r"\s+", " ", municipio).split()[0]
        if len(municipio) >= 3 and municipio not in {"SANTANDER", "LA", "DE", "DEL", "EL"}:
            return f"PERSONERIA MUNICIPAL DE {municipio}"

    return ""


# ═══════════════════════════════════════════════════════════
# 7-8. FUNCIONES DE PARSEO DE EMAIL
# ═══════════════════════════════════════════════════════════

def _extract_body_complete(payload: dict) -> str:
    """Extraer texto plano del payload del email (recursivo para multipart).
    Returns: texto del body completo."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _extract_body_complete(part)
        if result:
            return result

    return ""


def _find_attachment_parts(payload: dict) -> list[dict]:
    """Encontrar todas las partes que son adjuntos (recursivo).
    Returns: lista de dicts con filename, attachmentId, size."""
    attachments = []
    filename = payload.get("filename", "")
    body = payload.get("body", {})

    if filename and body.get("attachmentId"):
        attachments.append({
            "filename": filename,
            "attachmentId": body["attachmentId"],
            "size": body.get("size", 0),
        })

    for part in payload.get("parts", []):
        attachments.extend(_find_attachment_parts(part))

    return attachments


# ═══════════════════════════════════════════════════════════
# 9-11. FUNCIONES DE MATCHING Y CREACIÓN DE CASOS
# ═══════════════════════════════════════════════════════════

def _is_duplicate(db: Session, radicado_corto: str, tipo: str, date: datetime) -> bool:
    """Verificar si un email es duplicado (mismo radicado+tipo en últimas 24h).
    Returns: True si ya existe un email similar reciente."""
    if not radicado_corto:
        return False
    from datetime import timedelta
    since = date - timedelta(hours=24) if date else _utcnow() - timedelta(hours=24)
    existing = db.query(Email).filter(
        Email.subject.contains(radicado_corto),
        Email.date_received >= since,
    ).first()
    return existing is not None


def _normalize_rad_num(text: str) -> str | None:
    """Normalizar radicado a formato 'YEAR:SEQ' para comparación."""
    m = re.match(r"(20\d{2})[-\s]?0*(\d+)", str(text or ""))
    return f"{m.group(1)}:{m.group(2)}" if m else None


def match_to_case(db: Session, radicado_data: dict, accionante: str) -> Case | None:
    """Buscar caso existente para vincular email.
    Prioridad: rad_23 completo > rad_23 parcial > CC (v5.2) > FOREST > rad_corto > personería > accionante.
    Returns: Case o None."""
    rad_23 = radicado_data.get("radicado_23", "")
    rad_corto = radicado_data.get("radicado_corto", "")
    forest = radicado_data.get("forest", "")
    cc_accionante = radicado_data.get("cc_accionante", "")  # v5.2

    # 1a. Radicado 23 dígitos COMPLETO (20 dígitos normalizados)
    if rad_23:
        norm_new = re.sub(r"[^0-9]", "", rad_23)
        if len(norm_new) >= 18:
            cases = db.query(Case).filter(
                Case.radicado_23_digitos.isnot(None), Case.radicado_23_digitos != ""
            ).all()
            for c in cases:
                norm_ex = re.sub(r"[^0-9]", "", c.radicado_23_digitos or "")
                if len(norm_ex) >= 18 and norm_new[:20] == norm_ex[:20]:
                    return c

            # 1b. Match parcial: mismo departamento (5 dígitos) + misma secuencia (últimos 12)
            for c in cases:
                norm_ex = re.sub(r"[^0-9]", "", c.radicado_23_digitos or "")
                if len(norm_ex) >= 18 and norm_new[:5] == norm_ex[:5] and norm_new[-12:] == norm_ex[-12:]:
                    logger.info("Match parcial rad23: email=%s case=%s (mismo dept+secuencia)", norm_new, norm_ex)
                    return c

    # 1.4 (v5.2) CC del accionante — identificador ÚNICO por persona, no reusable
    # Buscar en observaciones/accionante donde la CC haya sido guardada previamente
    if cc_accionante and len(cc_accionante) >= 7:
        from sqlalchemy import or_
        case_by_cc = db.query(Case).filter(
            Case.processing_status != "DUPLICATE_MERGED",
            or_(
                Case.observaciones.like(f"%{cc_accionante}%"),
                Case.accionante.like(f"%{cc_accionante}%"),
                Case.asunto.like(f"%{cc_accionante}%"),
            ),
        ).first()
        if case_by_cc:
            logger.info("Match por CC %s → case_id=%d (v5.2)", cc_accionante, case_by_cc.id)
            return case_by_cc

    # 1.5. FOREST como clave secundaria
    if forest and len(forest) >= 8:
        case_by_forest = db.query(Case).filter(Case.radicado_forest == forest).first()
        if case_by_forest:
            logger.info("Match por FOREST: %s → case_id=%d", forest, case_by_forest.id)
            return case_by_forest

    # 2. Radicado corto EXACTO en folder_names
    if rad_corto:
        m = re.match(r"(20\d{2})[-]?0*(\d+)", rad_corto)
        if m:
            year, num = m.group(1), m.group(2)
            target = f"{year}:{num}"
            cases = db.query(Case).filter(Case.folder_name.ilike(f"{year}%")).all()
            # Todos los casos con ese mismo "año:secuencia". OJO: puede haber HOMÓNIMOS
            # (dos tutelas distintas con el mismo rad_corto pero juzgados distintos —
            # p.ej. "2026-00041" Juzgado 6 Bquilla vs "2026-00041" Juzgado 1 San Gil).
            matches = [c for c in cases if _normalize_rad_num(c.folder_name) == target]

            def _juzgado_compatible(c: Case) -> bool:
                # F7 (v5.0): si email y caso tienen rad23, el código de juzgado (díg. 6-12
                # del rad23 canónico) debe coincidir. Sin rad23 no se puede verificar → no
                # se descarta por esto (pero tampoco da certeza).
                if not (rad_23 and c.radicado_23_digitos):
                    return True
                a = re.sub(r"[^0-9]", "", rad_23)
                b = re.sub(r"[^0-9]", "", c.radicado_23_digitos or "")
                if len(a) < 18 or len(b) < 18:
                    return True
                return a[5:12] == b[5:12]

            verified = [c for c in matches if _juzgado_compatible(c)]
            if len(verified) == 1:
                return verified[0]
            if len(verified) > 1:
                # Homonimia year:seq y no se puede desambiguar por juzgado → NO auto-asignar
                # (conflar dos expedientes es peor que dejar el email sin caso). El llamador
                # lo deja PENDIENTE / lo manda a cuarentena.
                logger.warning(
                    "match_to_case: rad_corto %s ambiguo (%d casos: %s) — no se auto-asigna",
                    target, len(verified), [c.id for c in verified],
                )
                return None
            if matches and not verified:
                # Había caso(s) con ese rad_corto pero el juzgado NO coincide → es otra
                # tutela. Se deja seguir a personería/accionante (ya sin radicado que valide).
                logger.info(
                    "F7: rad_corto %s rechazado en %d caso(s) (juzgado distinto)",
                    target, len(matches),
                )

    # 3. Personería por municipio
    if accionante:
        m = re.search(
            r"(?:personero|personera|personería|personeria)\s+(?:municipal\s+)?(?:de|del)\s+(?:el\s+)?([A-Za-záéíóúñÁÉÍÓÚÑ]+)",
            accionante, re.IGNORECASE,
        )
        if m:
            municipio = m.group(1).strip().upper()
            if len(municipio) >= 3 and municipio not in {"SANTANDER", "LA", "DE"}:
                cases = db.query(Case).filter(Case.accionante.ilike(f"%{municipio}%")).all()
                for c in cases:
                    acc = (c.accionante or "").upper()
                    if any(kw in acc for kw in ("PERSONERO", "PERSONERA", "PERSONERÍA")):
                        # Verificar radicado no sea diferente
                        if rad_corto:
                            case_norm = _normalize_rad_num(c.folder_name)
                            email_norm = _normalize_rad_num(rad_corto)
                            if case_norm and email_norm and case_norm != email_norm:
                                continue  # Radicado diferente → no es este caso
                        return c

    # 4. Accionante — SOLO si radicado coincide o no hay radicado
    if accionante and len(accionante) >= 8:
        case = db.query(Case).filter(Case.accionante.ilike(f"%{accionante[:20]}%")).first()
        if case:
            if rad_corto:
                case_norm = _normalize_rad_num(case.folder_name)
                m = re.match(r"(20\d{2})[-]?0*(\d+)", rad_corto)
                email_norm = f"{m.group(1)}:{m.group(2)}" if m else None
                if case_norm and email_norm and case_norm != email_norm:
                    logger.info(f"Accionante '{accionante[:20]}' existe pero rad {rad_corto} diferente → caso nuevo")
                    return None
            return case

    return None


def create_new_case(db: Session, radicado_data: dict, accionante: str) -> Case | None:
    """Crear carpeta y caso nuevo en la DB.
    Returns: Case creado o None si no hay radicado."""
    rad_corto = radicado_data.get("radicado_corto", "")
    rad_23 = radicado_data.get("radicado_23", "")
    # Normalizar rad23 a formato CONTINUO (solo dígitos). El asunto trae a veces
    # "680014003016-2026-00381-00" con guiones; si se guarda así, la igualdad de
    # rad23 para dedup/match falla contra los rads continuos del resto de la DB.
    if rad_23:
        from backend.email.rad_utils import normalize_rad23
        _norm = normalize_rad23(rad_23)
        if len(_norm) >= 18:
            rad_23 = _norm
    if not rad_corto:
        return None

    # Verificar que NO exista ya
    m = re.match(r"(20\d{2})[-]?0*(\d+)", rad_corto)
    if m:
        year, num = m.group(1), m.group(2)
        existing = db.query(Case).filter(Case.folder_name.ilike(f"{year}%")).all()
        for ec in existing:
            norm = _normalize_rad_num(ec.folder_name)
            if norm and norm == f"{year}:{num}":
                return ec

    clean_acc = re.sub(r"[\n\r]", " ", accionante or "").strip()
    if not clean_acc:
        clean_acc = "[PENDIENTE REVISION]"
    folder_name = re.sub(r'[<>:"/\\|?*]', '', f"{rad_corto} {clean_acc}").strip()[:80]
    folder_path = BASE_DIR / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)

    # v5.2: guardar CC en observaciones para que match_to_case pueda encontrarlo después
    cc_note = ""
    if radicado_data.get("cc_accionante"):
        cc_note = f"CC accionante: {radicado_data['cc_accionante']}"

    case = Case(
        folder_name=folder_name,
        folder_path=str(folder_path),
        accionante=clean_acc if clean_acc != "[PENDIENTE REVISION]" else None,
        radicado_23_digitos=rad_23 or None,
        processing_status="PENDIENTE",
        estado="ACTIVO",
        tipo_actuacion="TUTELA",
        observaciones=cc_note or None,
    )
    db.add(case)
    db.flush()

    db.add(AuditLog(
        case_id=case.id,
        action="CREAR",
        source="gmail_api",
        new_value=f"Caso creado desde email. Accionante: {clean_acc[:50]}",
    ))
    db.commit()
    logger.info(f"Caso creado: {folder_name}")
    return case


# ═══════════════════════════════════════════════════════════
# 12-14. FUNCIONES DE DESCARGA Y GUARDADO
# ═══════════════════════════════════════════════════════════

def _sha256_bytes(data: bytes) -> str:
    """sha256 hex de bytes — clave de dedup byte-idéntico (F4, 2026-05-21)."""
    return hashlib.sha256(data).hexdigest()


def download_attachments(
    service, msg_id: str, case: Case | None, db: Session,
    email_id: int | None = None, email_message_id: str | None = None,
) -> tuple[list, list]:
    """Descargar adjuntos del email y registrar en DB.
    Returns: (guardados: list[dict], ignorados: list[str])"""
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    att_parts = _find_attachment_parts(msg.get("payload", {}))

    save_dir = Path(case.folder_path) if case and case.folder_path else BASE_DIR / "_emails_sin_clasificar"
    save_dir.mkdir(parents=True, exist_ok=True)

    guardados = []
    ignorados = []
    deduped = 0  # F3: adjuntos válidos que ya estaban en el caso (reenvío)

    for att in att_parts:
        filename = re.sub(r"[\r\n]+", " ", att["filename"]).strip()
        ext = Path(filename).suffix.lower()
        if ext not in VALID_EXTENSIONS:
            ignorados.append(filename)
            continue

        att_data = service.users().messages().attachments().get(
            userId="me", messageId=msg_id, id=att["attachmentId"]
        ).execute()
        file_data = base64.urlsafe_b64decode(att_data["data"])

        # F4: dedup byte-idéntico DENTRO del mismo caso. Si ya existe un Document con
        # este sha256 en este caso (reenvío/re-adjunto), no duplicar archivo ni fila.
        file_hash = _sha256_bytes(file_data)
        if case:
            dup = db.query(Document).filter(
                Document.case_id == case.id, Document.file_hash == file_hash,
            ).first()
            if dup:
                logger.info("F4 dedup: adjunto %s ya existe en caso %s (sha %s) — omitido",
                            filename, case.id, file_hash[:10])
                deduped += 1
                continue

        save_path = save_dir / filename
        counter = 1
        while save_path.exists():
            save_path = save_dir / f"{Path(filename).stem}_{counter}{ext}"
            counter += 1

        save_path.write_bytes(file_data)
        guardados.append({"filename": save_path.name, "saved_path": str(save_path)})

        if case:
            # v4.8 Provenance: vincular al email de origen (si lo conocemos).
            # Garantiza que los hermanos del mismo email viajen juntos.
            db.add(Document(
                case_id=case.id, filename=save_path.name, file_path=str(save_path),
                doc_type=classify_document(save_path.name), file_size=len(file_data),
                file_hash=file_hash,
                email_id=email_id,
                email_message_id=email_message_id or msg_id,
            ))

    # F3: reenvío que no aportó adjuntos nuevos (todos byte-idénticos ya en el caso).
    # Se marca el Email (no se borra: conserva provenance). NO se colapsa por subject.
    if email_id and deduped > 0 and not guardados:
        try:
            db.query(Email).filter(Email.id == email_id).update({"status": "REENVIO_SIN_NUEVOS"})
        except Exception as e:
            logger.debug("No se pudo marcar email %s como REENVIO_SIN_NUEVOS: %s", email_id, e)

    return guardados, ignorados


def save_email_md(save_dir: Path, metadata: dict, body: str, adjuntos: list,
                   db: Session = None, case_id: int = None,
                   email_id: int | None = None, email_message_id: str | None = None) -> str | None:
    """Guardar email como .md en la carpeta del caso y registrar como Document.

    Args: save_dir, metadata={subject, sender, date, folder_name}, body, adjuntos,
          db (optional): Session para registrar como Document, case_id (optional),
          email_id (optional): FK al Email de origen (v4.8 Provenance),
          email_message_id (optional): gmail message_id string
    Returns: filename si se creó, None si ya existía o falló.
    """
    if not save_dir.exists():
        return None

    date_part = _utcnow().strftime("%Y%m%d")
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(metadata.get("date", ""))
        date_part = dt.strftime("%Y%m%d")
    except Exception as e:
        logger.debug("Fecha de email no parseable (%r), uso fecha actual: %s", metadata.get("date", ""), e)

    clean_subject = re.sub(r'[<>:"/\\|?*\n\r]', '', (metadata.get("subject") or "sin_asunto")[:50]).strip()
    clean_subject = re.sub(r'\s+', '_', clean_subject)
    filename = f"Email_{date_part}_{clean_subject}.md"

    save_path = save_dir / filename
    if save_path.exists():
        return None  # NO sobreescribir

    att_list = ""
    if adjuntos:
        att_list = "\n## Adjuntos\n" + "\n".join(f"- {a.get('filename', '?')}" for a in adjuntos)

    content = f"""# {metadata.get('subject') or '(Sin asunto)'}

**De:** {metadata.get('sender', '')}
**Fecha:** {metadata.get('date', '')}
**Caso:** {metadata.get('folder_name', '')}

---

{body}
{att_list}
"""
    try:
        save_path.write_text(content, encoding="utf-8")
        logger.info("Email .md guardado: %s", filename)
    except Exception as e:
        logger.error("Error guardando email .md %s: %s", filename, e)
        return None

    # Registrar como Document en DB si tenemos session y case_id
    if db and case_id:
        try:
            from backend.database.models import Document
            # Verificar que no existe ya
            existing = db.query(Document).filter(
                Document.case_id == case_id,
                Document.filename == filename,
            ).first()
            if not existing:
                doc = Document(
                    case_id=case_id,
                    filename=filename,
                    file_path=str(save_path),
                    doc_type="EMAIL_MD",
                    extracted_text=content,
                    extraction_method="email_md",
                    extraction_date=_utcnow(),
                    verificacion="OK",
                    verificacion_detalle="Email del caso (generado automaticamente)",
                    file_size=len(content.encode("utf-8")),
                    file_hash=_sha256_bytes(content.encode("utf-8")),
                    # v4.8 Provenance: el .md es parte del paquete del email origen
                    email_id=email_id,
                    email_message_id=email_message_id,
                )
                db.add(doc)
                db.commit()
                logger.info("Document registrado para email .md: %s (case_id=%d, email_id=%s)", filename, case_id, email_id)
        except Exception as e:
            logger.error("Error registrando email .md como Document: %s", e)

    return filename


def update_case_fields(db: Session, case: Case, tipo: str, data: dict) -> list[str]:
    """Actualizar campos del caso con datos del email si están vacíos.
    Returns: lista de campos actualizados."""
    updated = []
    rad_23 = data.get("radicado_23", "")
    forest = data.get("forest", "")
    accionante = data.get("accionante", "")

    if rad_23 and not case.radicado_23_digitos:
        case.radicado_23_digitos = rad_23
        updated.append("RADICADO_23_DIGITOS")

    if forest and not case.radicado_forest:
        case.radicado_forest = forest
        updated.append("RADICADO_FOREST")

    if accionante and not case.accionante:
        case.accionante = accionante
        updated.append("ACCIONANTE")

    if tipo == "INCIDENTE_DESACATO" and (not case.incidente or case.incidente != "SI"):
        case.incidente = "SI"
        updated.append("INCIDENTE")

    if tipo == "IMPUGNACION" and (not case.impugnacion or case.impugnacion != "SI"):
        case.impugnacion = "SI"
        updated.append("IMPUGNACION")

    if updated:
        case.updated_at = _utcnow()
        for field in updated:
            db.add(AuditLog(
                case_id=case.id, field_name=field,
                old_value="", new_value=getattr(case, field.lower(), ""),
                action="IMPORT_EMAIL", source="gmail_api",
            ))

    return updated


# ═══════════════════════════════════════════════════════════
# 15. FUNCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════

def get_gmail_total() -> dict:
    """Consultar total de correos en Gmail (etiqueta INBOX, sin spam/papelera).
    Returns: {'total': int, 'unread': int}"""
    try:
        service = _get_gmail_service()

        # Total en label "INBOX" (excluye spam, papelera, borradores)
        label_info = service.users().labels().get(userId="me", id="INBOX").execute()
        total = label_info.get("messagesTotal", 0)
        unread = label_info.get("messagesUnread", 0)

        return {"total": total, "unread": unread}
    except Exception as e:
        logger.error(f"Error consultando total Gmail: {e}")
        return {"total": 0, "unread": 0, "error": str(e)}


def sync_inbox(db: Session, progress_cb=None) -> list[dict]:
    """Sincronizar TODOS los correos de Gmail a DB (solo registro, NO crea carpetas ni casos).
    Importa correos faltantes como registros en la tabla Email sin efectos secundarios.

    progress_cb: callable(processed:int, total:int, last_subject:str, imported:int, skipped:int) | None
                 — invocado al inicio (con total) y por cada email procesado.
    Returns: lista de dicts con resultado por cada email importado."""
    results = []

    try:
        service = _get_gmail_service()
        existing_ids = {e.message_id for e in db.query(Email.message_id).all()}

        # Fallback: indexar por subject+sender para detectar duplicados con message_id diferente
        existing_subjects = set()
        for e in db.query(Email.subject, Email.sender).all():
            if e.subject and e.sender:
                existing_subjects.add((e.subject.strip()[:100], e.sender.strip()[:50]))

        # Paginar TODOS los mensajes del inbox
        messages = []
        page_token = None
        while True:
            kwargs = {"userId": "me", "labelIds": ["INBOX"], "maxResults": 100}
            if page_token:
                kwargs["pageToken"] = page_token
            response = service.users().messages().list(**kwargs).execute()
            messages.extend(response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        if not messages:
            if progress_cb:
                try: progress_cb(0, 0, "", 0, 0)
                except Exception: pass
            return results

        imported = 0
        skipped = 0
        total_msgs = len(messages)
        if progress_cb:
            try: progress_cb(0, total_msgs, "", 0, 0)
            except Exception: pass

        for idx, msg_ref in enumerate(messages, start=1):
            last_subject_for_progress = ""
            try:
                msg = service.users().messages().get(userId="me", id=msg_ref["id"], format="metadata",
                    metadataHeaders=["Subject", "From", "Date", "Message-ID", "Message-Id"]).execute()
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                message_id = headers.get("Message-ID", headers.get("Message-Id", msg_ref["id"]))

                if message_id in existing_ids:
                    skipped += 1
                else:
                    subject = _normalize_typos(headers.get("Subject", ""))
                    sender = headers.get("From", "")
                    date_str = headers.get("Date", "")
                    last_subject_for_progress = subject[:80]

                    if _should_ignore(subject, sender):
                        skipped += 1
                    else:
                        subj_key = (subject.strip()[:100], sender.strip()[:50])
                        if subj_key in existing_subjects:
                            skipped += 1
                            existing_ids.add(message_id)
                        else:
                            try:
                                from email.utils import parsedate_to_datetime
                                from datetime import timezone
                                dt = parsedate_to_datetime(date_str)
                                date_received = dt.astimezone(timezone.utc).replace(tzinfo=None)
                            except Exception:
                                date_received = _utcnow()

                            tipo = classify_email_type(subject, sender)
                            radicado_data = extract_radicado(f"{subject}")
                            case = match_to_case(db, radicado_data, "")

                            email_record = Email(
                                message_id=message_id, subject=subject, sender=sender,
                                date_received=date_received, body_preview="",
                                case_id=case.id if case else None,
                                attachments=[], status="ASIGNADO" if case else "PENDIENTE",
                                processed_at=_utcnow(),
                            )
                            db.add(email_record)
                            existing_ids.add(message_id)
                            existing_subjects.add(subj_key)
                            imported += 1

                            if imported % 50 == 0:
                                db.commit()
                                logger.info(f"Sync: {imported} importados, {skipped} omitidos...")

            except Exception as e:
                logger.error(f"Error sync email: {e}")
            finally:
                if progress_cb:
                    try: progress_cb(idx, total_msgs, last_subject_for_progress, imported, skipped)
                    except Exception: pass

        db.commit()
        results.append({"imported": imported, "skipped": skipped, "total_gmail": len(messages)})
        logger.info(f"Sync completado: {imported} importados, {skipped} omitidos de {len(messages)} en Gmail")

    except Exception as e:
        logger.error(f"Error sync Gmail: {e}")
        results.append({"error": str(e)})

    return results


def check_inbox(db: Session) -> list[dict]:
    """Revisar bandeja de Gmail: solo emails NO LEIDOS, procesa completo (descarga adjuntos, crea casos).
    Returns: lista de dicts con resultado por cada email procesado."""
    results = []

    try:
        service = _get_gmail_service()

        # Solo emails no leidos
        messages = []
        page_token = None
        while True:
            kwargs = {"userId": "me", "q": "is:unread", "maxResults": 100}
            if page_token:
                kwargs["pageToken"] = page_token
            response = service.users().messages().list(**kwargs).execute()
            messages.extend(response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token or len(messages) >= 500:
                break

        if not messages:
            return results

        # Procesar del MÁS ANTIGUO al MÁS RECIENTE. La Gmail API devuelve los mensajes
        # en orden descendente por fecha (newest-first); invertir da cronológico
        # ascendente. Así, cuando llega una respuesta (RV:/Re:), su correo padre ya fue
        # ingerido → el match por hilo (in_reply_to → case del padre) funciona, y el
        # contexto de acumulación se construye en orden. (Fix 2026-05-25.)
        messages.reverse()

        existing_ids = {e.message_id for e in db.query(Email.message_id).all()}

        for msg_ref in messages:
            try:
                msg = service.users().messages().get(userId="me", id=msg_ref["id"], format="full").execute()
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                message_id = headers.get("Message-ID", headers.get("Message-Id", msg_ref["id"]))

                # Duplicado en DB → solo marcar como leído
                if message_id in existing_ids:
                    try:
                        service.users().messages().modify(
                            userId="me", id=msg_ref["id"], body={"removeLabelIds": ["UNREAD"]}
                        ).execute()
                    except Exception as e:
                        logger.debug("No se pudo marcar leído (duplicado) %s: %s", msg_ref.get("id"), e)
                    continue

                subject = _normalize_typos(headers.get("Subject", ""))
                sender = headers.get("From", "")
                date_str = headers.get("Date", "")
                # v5.4.4: threading headers (RFC 5322)
                in_reply_to_hdr = headers.get("In-Reply-To", "") or headers.get("In-reply-to", "")
                references_hdr = headers.get("References", "") or headers.get("references", "")

                # Ignorar emails no jurídicos
                if _should_ignore(subject, sender):
                    try:
                        service.users().messages().modify(
                            userId="me", id=msg_ref["id"], body={"removeLabelIds": ["UNREAD"]}
                        ).execute()
                    except Exception as e:
                        logger.debug("No se pudo marcar leído (ignorado) %s: %s", msg_ref.get("id"), e)
                    results.append({"subject": subject, "accion": "IGNORADO", "error": None})
                    continue

                # Parsear fecha y normalizar a UTC
                date_received = None
                try:
                    from email.utils import parsedate_to_datetime
                    from datetime import timezone
                    dt = parsedate_to_datetime(date_str)
                    date_received = dt.astimezone(timezone.utc).replace(tzinfo=None)
                except Exception:
                    date_received = _utcnow()

                # Extraer body y adjuntos
                body = _extract_body_complete(msg.get("payload", {}))
                att_parts = _find_attachment_parts(msg.get("payload", {}))
                att_names = [a["filename"] for a in att_parts]

                # ── CLASIFICAR ──
                tipo = classify_email_type(subject, sender)
                # Subject-rad prioritario (anti-conflación 0053→0080): el rad del
                # subject le gana al rad ajeno de la cadena reenviada. Ver resolve_radicado.
                radicado_data = resolve_radicado(subject, body)
                forest = extract_forest(body, att_names)
                radicado_data["forest"] = forest  # v5.0: FOREST como clave de matching
                accionante = extract_accionante(subject, body)

                # v5.2: extraer CC con regex forensic (identificador más confiable que nombre)
                try:
                    from backend.agent.regex_library import CC_ACCIONANTE
                    cc_match = CC_ACCIONANTE.pattern.search(f"{subject}\n{body[:5000]}")
                    if cc_match:
                        radicado_data["cc_accionante"] = cc_match.group(1)
                except Exception as e:
                    logger.debug("Extracción de CC accionante falló: %s", e)

                # v5.4.4: aplicar rad_utils.reconcile para fix zfill bug
                # Si rad23 es válido, descartar rad_corto extraído por regex y re-derivar
                from backend.email.rad_utils import reconcile as _rad_reconcile
                _rc23, _rc_corto = _rad_reconcile(
                    radicado_data.get("radicado_23", ""),
                    radicado_data.get("radicado_corto", ""),
                )
                radicado_data["radicado_23"] = _rc23
                radicado_data["radicado_corto"] = _rc_corto

                logger.info(f"Email: tipo={tipo} rad={radicado_data.get('radicado_corto','')} forest={forest} cc={radicado_data.get('cc_accionante','-')} acc={accionante[:20]}")

                # ── MATCH MULTI-CRITERIO (v5.4.4) ──
                # Resolver thread parent desde headers In-Reply-To/References
                thread_parent_case_id = None
                if in_reply_to_hdr or references_hdr:
                    try:
                        from backend.email.matcher import resolve_thread_parent
                        thread_parent_case_id = resolve_thread_parent(
                            db, in_reply_to_hdr, references_hdr,
                        )
                        if thread_parent_case_id:
                            logger.info(f"Thread parent detectado: email→caso {thread_parent_case_id}")
                    except Exception as _e:
                        logger.warning(f"Thread resolver fallo: {_e}")

                # Construir señales y scoring
                from backend.email.case_lookup_cache import get_cache
                from backend.email.matcher import EmailSignals, score_case_match

                signals = EmailSignals(
                    rad23=radicado_data.get("radicado_23", ""),
                    rad_corto=radicado_data.get("radicado_corto", ""),
                    forest=forest,
                    cc_accionante=radicado_data.get("cc_accionante", ""),
                    accionante_name=accionante,
                    sender=sender,
                    thread_parent_case_id=thread_parent_case_id,
                )

                case = None
                match_score = 0
                match_confidence = "NONE"
                match_signals_json = None
                match_route = None  # ruta de asignación (auditabilidad #3.5)
                created_new = False
                accion = "CASO_EXISTENTE"

                if tipo == "SALIENTE":
                    accion = "SALIENTE"
                elif signals.has_any():
                    cache = get_cache()
                    if cache.is_built:
                        match = score_case_match(db, cache, signals)
                        match_score = match.score
                        match_confidence = match.confidence
                        match_signals_json = match.to_signals_json()
                        logger.info(
                            f"Matcher: score={match.score} conf={match.confidence} "
                            f"case_id={match.case_id} breakdown={match.breakdown}"
                        )
                        if match.is_auto_match:
                            case = db.query(Case).filter(Case.id == match.case_id).first()
                        elif match.confidence == "MEDIUM":
                            # Ambiguo — guardar email sin asignar, para revisión manual (quarantine v5.5a)
                            case = None
                            accion = "AMBIGUO"
                    else:
                        # Fallback a matcher secuencial v5.3 si cache no está listo (cold start)
                        case = match_to_case(db, radicado_data, accionante)
                        if case:
                            match_route = "cold_start_sequential"

                # F0-A: antes de crear caso nuevo, aplicar F2 (desambiguar respuesta SED por
                # municipio del juzgado) + F1 (adoptar shell sin rad23) — misma lógica que el
                # script de ingesta, para que las dos rutas NO creen casos que compiten (RC-1).
                if accion not in ("SALIENTE", "AMBIGUO") and not case:
                    _rad23 = radicado_data.get("radicado_23", "") or ""
                    _rc_raw = radicado_data.get("radicado_corto", "") or ""
                    _m = re.match(r"(20\d{2})\D?0*(\d{1,5})", _rc_raw)
                    _rc = f"{_m.group(1)}-{_m.group(2).zfill(5)}" if _m else None
                    if _rc:
                        _muni = _resolver_juz_muni(f"{subject} {(body or '')[:3000]}")
                        _c2, _mth = _resolver_match_rad_corto(
                            db, _rc, accionante=accionante or "", municipio=_muni,
                            email_rad23=_rad23)
                        if _c2:
                            case = _c2
                            match_route = f"F2:{_mth}"
                            logger.info(f"F2: respuesta matcheada a caso {_c2.id} por {_mth}")
                        elif _mth == "rad_corto_cross_juzgado_blocked":
                            logger.info(
                                f"F2: rad_corto {_rc} bloqueado — email trae rad23 {_rad23} "
                                f"de juzgado distinto al único caso con ese consecutivo "
                                f"(fix #11, evita conflación cross-juzgado)")
                    if not case and len(re.sub(r"\D", "", _rad23)) >= 21:
                        _sh = _resolver_adopt_shell(db, _rad23, accionante or "")
                        if _sh:
                            case = _sh
                            match_route = "F1_adopt_shell"
                            logger.info(f"F1: shell {_sh.id} adoptado (rad23 {_rad23})")

                # Si no se encontró caso y no es SALIENTE/AMBIGUO → crear nuevo
                if accion not in ("SALIENTE", "AMBIGUO") and not case:
                    case = create_new_case(db, radicado_data, accionante)
                    if case:
                        created_new = True
                        accion = "CASO_NUEVO"
                        match_route = "create_new"
                        # Refrescar cache con el nuevo caso
                        try:
                            get_cache().refresh_one(db, case.id)
                        except Exception as e:
                            logger.debug("refresh_one de cache falló para caso %s: %s", case.id, e)

                # ── REGISTRAR EMAIL EN DB PRIMERO (v4.8 Provenance) ──
                # Creamos el Email antes que los Documents para tener email_id
                # disponible al crear los hijos (adjuntos + .md). Esto garantiza
                # que todos los docs del mismo email queden vinculados y viajen
                # juntos al reasignar entre casos.
                # Auditabilidad (#3.5): si se asignó/creó un caso por una ruta
                # determinista que NO pasó por el scoring (F1/F2/cold-start/create_new),
                # registrar igual las señales que llevaron a la decisión. Backstop
                # único → ninguna asignación queda con match_signals_json=None,
                # incl. rutas futuras (se atrapan acá, no por-rama).
                if case and match_signals_json is None:
                    match_signals_json = json.dumps({
                        "score": match_score,
                        "confidence": match_confidence,
                        "breakdown": {
                            "route": match_route or accion,
                            "rad23": radicado_data.get("radicado_23", ""),
                            "rad_corto": radicado_data.get("radicado_corto", ""),
                            "forest": forest,
                            "accionante": accionante,
                        },
                        "alternatives": [],
                    }, ensure_ascii=False)

                _email_status = "ASIGNADO" if case else ("AMBIGUO" if accion == "AMBIGUO" else "PENDIENTE")

                # F-DEDUP (2026-05-28): evita duplicados por dual-ingestion (Sync paralela
                # crea emails sin gmail_id en message_id mientras el monitor los crea
                # con suffix _gmailid_). Detecta dup por (case_id, subject, sender,
                # fecha±1día) — mismo contenido en distinta envoltura.
                if case is not None and subject:
                    from datetime import timedelta as _td
                    win = _td(days=1)
                    dup_q = db.query(Email).filter(
                        Email.case_id == case.id,
                        Email.subject == subject,
                        Email.sender == sender,
                        Email.date_received >= (date_received - win),
                        Email.date_received <= (date_received + win),
                    ).first()
                    if dup_q is not None:
                        logger.info(
                            "Email dup detectado (case=%d subj='%s'), skip",
                            case.id, subject[:50]
                        )
                        continue

                email_record = Email(
                    message_id=message_id, subject=subject, sender=sender,
                    date_received=date_received, body_preview=body or "",
                    case_id=case.id if case else None,
                    attachments=[],  # se actualiza despues de download
                    status=_email_status,
                    processed_at=_utcnow(),
                    in_reply_to=in_reply_to_hdr or None,
                    references_header=references_hdr or None,
                    match_score=match_score or None,
                    match_confidence=match_confidence if match_confidence != "NONE" else None,
                    match_signals_json=match_signals_json,
                )
                db.add(email_record)
                db.flush()  # obtener email_record.id sin commit

                # ── DESCARGAR ADJUNTOS (con email_id propagado) ──
                guardados, ignorados = download_attachments(
                    service, msg_ref["id"], case, db,
                    email_id=email_record.id,
                    email_message_id=message_id,
                )
                # Actualizar attachments en el Email ahora que ya descargamos
                email_record.attachments = guardados

                # ── GUARDAR .md (+ registrar como Document con email_id) ──
                if case and case.folder_path and body:
                    save_email_md(
                        Path(case.folder_path),
                        {"subject": subject, "sender": sender, "date": date_str, "folder_name": case.folder_name},
                        body, guardados,
                        db=db, case_id=case.id,
                        email_id=email_record.id,
                        email_message_id=message_id,
                    )

                # ── ACTUALIZAR CAMPOS DEL CASO ──
                campos_actualizados = []
                if case:
                    data = {**radicado_data, "forest": forest, "accionante": accionante}
                    campos_actualizados = update_case_fields(db, case, tipo, data)

                if case:
                    db.add(AuditLog(
                        case_id=case.id, action="IMPORT_EMAIL", source="gmail_api",
                        new_value=f"Email: {subject[:100]}",
                    ))

                # ── MARCAR COMO LEÍDO ──
                try:
                    service.users().messages().modify(
                        userId="me", id=msg_ref["id"], body={"removeLabelIds": ["UNREAD"]}
                    ).execute()
                except Exception as e:
                    logger.debug("No se pudo marcar leído (procesado) %s: %s", msg_ref.get("id"), e)

                results.append({
                    "subject": subject,
                    "tipo": tipo,
                    "radicado_corto": radicado_data.get("radicado_corto", ""),
                    "radicado_23": radicado_data.get("radicado_23", ""),
                    "forest": forest,
                    "accionante": accionante[:40],
                    "matched_case": case.folder_name if case else None,
                    "accion": accion,
                    "adjuntos_guardados": len(guardados),
                    "adjuntos_ignorados": len(ignorados),
                    "campos_actualizados": campos_actualizados,
                    "error": None,
                })

            except Exception as e:
                logger.error(f"Error procesando email: {e}", exc_info=True)
                # v5.4.3: rollback defensivo — una excepción en un email puede
                # dejar la sesión contaminada y hacer que el siguiente email falle
                # con "Session rolled back due to previous exception during flush".
                # Mismo patrón que v5.4.2 aplicó a unified.py.
                try:
                    db.rollback()
                except Exception:
                    pass
                results.append({"subject": "", "accion": "ERROR", "error": str(e)[:100]})
                continue

        db.commit()

    except Exception as e:
        logger.error(f"Error Gmail API: {e}")
        results.append({"error": f"Error Gmail API: {e}"})

    return results


# ═══════════════════════════════════════════════════════════
# UTILIDAD: Retroactivamente crear .md de emails existentes
# ═══════════════════════════════════════════════════════════

def save_existing_emails_as_md(db: Session) -> int:
    """Guardar todos los emails existentes como .md en sus carpetas.
    Returns: número de emails guardados."""
    emails = db.query(Email).filter(
        Email.case_id.isnot(None), Email.body_preview.isnot(None), Email.body_preview != "",
    ).all()

    saved = 0
    for em in emails:
        case = db.query(Case).filter(Case.id == em.case_id).first()
        if not case or not case.folder_path:
            continue
        date_str = em.date_received.strftime("%a, %d %b %Y %H:%M") if em.date_received else ""
        result = save_email_md(
            Path(case.folder_path),
            {"subject": em.subject or "", "sender": em.sender or "", "date": date_str, "folder_name": case.folder_name},
            em.body_preview, em.attachments or [],
            db=db, case_id=case.id,
            # v4.8 Provenance: el .md generado retroactivamente tambien hereda el email_id
            email_id=em.id,
            email_message_id=em.message_id,
        )
        if result:
            saved += 1
    return saved
