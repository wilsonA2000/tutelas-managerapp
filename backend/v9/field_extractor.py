"""Fase 2 — Extracción de campos a nivel CASE.

A diferencia de `regex_pass.py` (que opera doc-por-doc), este módulo opera
sobre el CASE completo: ve todos sus docs + emails, los ordena cronológicamente,
y aplica heurísticas que necesitan contexto multi-doc.

Cada función `extract_<campo>_for_case(db, case)` devuelve el valor extraído
(o None) sin escribir a DB — eso lo hace el caller (`scripts/v9_extract_fields.py`).

Filosofía: regex primero, LLM solo donde regex no alcanza (Fase 2b).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.models import Case, Document, Email
from backend.v9.regex_pass import _extract_forest

logger = logging.getLogger("tutelas.v9.field_extractor")


def _read_doc_text(doc: Document) -> str:
    """Devuelve el texto del doc. Para .md lee del disco; para PDF/DOCX usa extracted_text."""
    if doc.doc_type in ("EMAIL_JUDICIAL", "EMAIL_INTERNO") or (doc.filename or "").endswith(".md"):
        p = Path(doc.file_path) if doc.file_path else None
        if p and p.exists():
            try:
                return p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""
        return ""
    return doc.extracted_text or ""


def _emails_chronological(db: Session, case_id: int) -> list[Email]:
    """Emails del case ordenados del más antiguo al más reciente."""
    return (
        db.query(Email)
        .filter(Email.case_id == case_id)
        .order_by(Email.date_received.asc())
        .all()
    )


# ============================================================
# RADICADO_FOREST + FOREST_IMPUGNACION
# ============================================================

# Keywords del subject que indican que el FOREST de ese email es de impugnación
_IMPUGNACION_SUBJECT_KW = ("impugna", "impugnación", "impugnacion", "recurso de impugna")


def extract_forest_for_case(db: Session, case: Case) -> tuple[Optional[str], Optional[str]]:
    """Extrae (radicado_forest, forest_impugnacion) del case.

    Estrategia:
      1. Recorrer emails .md del case CRONOLÓGICAMENTE (más antiguo primero).
      2. En cada .md buscar el FOREST con `_extract_forest` (patrón canónico de
         tutelas@santander.gov.co + variantes).
      3. Clasificar por el subject del email:
         - subject menciona "impugna" → ese FOREST va a `forest_impugnacion`
         - sino → primer FOREST encontrado → `radicado_forest`
      4. Fallback: si no hay .md con FOREST, mirar el header de los DOCX RESPUESTA.

    Returns: (radicado_forest, forest_impugnacion) — cualquiera puede ser None.
    """
    radicado_forest: Optional[str] = None
    forest_impugnacion: Optional[str] = None

    emails = _emails_chronological(db, case.id)
    for email in emails:
        # .md de este email
        md_doc = (
            db.query(Document)
            .filter(
                Document.email_id == email.id,
                Document.doc_type.in_(["EMAIL_JUDICIAL", "EMAIL_INTERNO"]),
            )
            .first()
        )
        if not md_doc:
            continue
        text = _read_doc_text(md_doc)
        if not text:
            continue
        forest = _extract_forest(text)
        if not forest:
            continue

        subj_low = (email.subject or "").lower()
        is_impugnacion = any(kw in subj_low for kw in _IMPUGNACION_SUBJECT_KW)
        if is_impugnacion:
            if not forest_impugnacion:
                forest_impugnacion = forest
        else:
            if not radicado_forest:
                radicado_forest = forest

    # Fallback: header de DOCX RESPUESTA — ordenado por id ASC (orden de inserción,
    # mejor proxy disponible de "primera respuesta": Document no tiene created_at) para
    # anclar al FOREST de la PRIMERA respuesta enviada (1E, fix 2026-06-01).
    if not radicado_forest:
        respuestas = (
            db.query(Document)
            .filter(Document.case_id == case.id,
                    Document.doc_type.in_(["RESPUESTA", "DOCX_RESPUESTA", "RESPUESTA_SED"]))
            .order_by(Document.id.asc())
            .all()
        )
        for d in respuestas:
            forest = _extract_forest(d.extracted_text or "")
            if forest:
                radicado_forest = forest
                break

    # Fallback adicional: cualquier doc del case
    if not radicado_forest:
        for d in db.query(Document).filter(Document.case_id == case.id).all():
            text = _read_doc_text(d)
            forest = _extract_forest(text)
            if forest:
                radicado_forest = forest
                break

    return radicado_forest, forest_impugnacion


# ============================================================
# ACCIONANTE (+ nota para observaciones)
# ============================================================

import unicodedata as _ud

# Doctypes donde el accionante aparece con más fiabilidad (orden de prioridad).
# El escrito de tutela y el auto lo nombran limpio; la RESPUESTA de la SED trae una tabla
# REF/ACCIONANTE muy fiable; las sentencias/autos/incidentes lo recapitulan ("promovida por …").
_ACCIONANTE_DOC_PRIORITY = [
    # PDF_AUTO_ADMISORIO: tipo legacy equivalente a AUTO_ADMISORIO (1ra inst inequívoca).
    # Sin él, autos admisorios mal etiquetados quedaban invisibles al extractor (c519).
    "AUTO_ADMISORIO", "PDF_AUTO_ADMISORIO", "DEMANDA_TUTELA", "ANEXO_DEMANDA",
    "SENTENCIA_1RA", "RESPUESTA",
    "IMPUGNACION",
    "INCIDENTE_DESACATO", "AUTO_INCIDENTE", "NOTIFICACION", "NOTIFICACION_FALLO",
    "OFICIO_CUMPLIMIENTO", "DESCONOCIDO",
]
# FIX (2026-05-28): docs 2da instancia EXCLUIDOS del rastreo de accionante.
# Bug detectado: en autos AUTO_AVOCA/AUTO_CONCEDE_IMPUGNACION de algunos
# juzgados (ej. Juz1 Promiscuo Familia Socorro), el campo "ACCIONANTE:" en
# el formato del auto contiene en realidad el JUZGADO de 1ra inst, no el
# accionante real. Afectó c176/c503. Solo se usan estos docs si todo lo
# demás falla (fallback explícito al final del flujo).
_ACCIONANTE_DOC_FALLBACK = [
    "SENTENCIA_2DA", "AUTO_2DA", "AUTO_CONCEDE_IMPUGNACION",
]

# Personería/Personero Municipal de X — el municipio puede venir partido por \n.
# Capturamos cualquier variante (Personero/Personería) → normalizamos siempre a
# "PERSONERÍA MUNICIPAL DE X" (institución, nunca el funcionario, porque cambia).
_PAT_PERSONERIA = re.compile(
    r"(?i)personer[íioa]+a?\s*\n?\s*municipal\s*\n?\s*(?:de|del)\s*\n?\s*(?:el\s+)?"
    r"([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ.\s\n]{2,35}?)(?=[\s\n]*(?:en\s+represent|en\s+su\s+condici|,|\.|\bcontra\b|\bquien\b|\bactuando\b|\bsantander\b|$))",
    re.IGNORECASE,
)
# Rol de agencia (para la nota): "agente oficioso" vs "representante legal" vs "en representación"
_PAT_ROL_AGENCIA = re.compile(
    r"(?i)(agente\s+oficios[oa]|representante\s+legal|en\s+representaci[óo]n)\s+"
    r"(?:de\s+)?(?:l[aoes]+\s+)?([^\n,\.]{2,90}?)(?=\s*[,\.\n]|\s+(?:y\s+en\s+contra|en\s+contra|contra|identificad|C\.?C\.?)|$)"
)
# ACCIONANTE: NOMBRE  (etiqueta a inicio de línea). El nombre puede venir partido en varias
# líneas por el extractor de PDF — se captura hasta una línea en blanco, el siguiente rótulo
# en MAYÚSCULAS terminado en ":"/".", o un "C.C. #…".
# El separador tras "ACCIONANTE" puede ser ":", "." o "|" (celda de tabla del DOCX de respuesta).
_PAT_ACC_LABEL = re.compile(
    r"(?ims)^[ \t]*(?:Accionant[ea]s?|ATE)[ \t]*[:\.|][ \t]*"
    r"(.{0,180}?)"
    r"(?=\n[ \t]*\n|\n[ \t]*[A-ZÁÉÍÓÚÑ][^\n:|]{1,45}[:\.|][ \t]*(?:\n|$)|\n[ \t]*C\.?\s?C\.?\s*[#N°.\d]|$)"
)
# instaurada/presentada/promovida/interpuesta/formulada por NOMBRE — se consumen tratamientos
# sueltos antes del nombre; el nombre puede cruzar saltos de línea (no comas ni pipes).
_PAT_ACC_INSTAURADA = re.compile(
    r"(?i)(?:instaurad[oa]|presentad[oa]|promovid[oa]|interpuest[oa]|formulad[oa]|incoad[oa])\s+por\s+"
    r"(?:(?:el|la|l[oa]s)\s+|se[ñn]ora?\s+|ciudadan[oa]\s+|doctora?\s+|abogad[oa]\s+|dra?\.?\s+)*"
    r"([A-ZÁÉÍÓÚÑ][^,|]{4,90}?)"
    r"(?=\s+(?:en\s+contra|contra|actuando|como|quien|mayor\b|identificad[oa]|en\s+calidad|"
    r"en\s+representaci[óo]n|en\s+nombre|en\s+su\s+propio|C\.?\s?C\.?\b|c[ée]dula|y\s+otros?)|[,\.]|$)"
)
# "NOMBRE, actuando en nombre propio, instauró/interpuso/presentó acción de tutela" — el sujeto
# va ANTES del verbo (típico del encabezado del auto admisorio: "RADICADO …\nNOMBRE … instauró…").
_PAT_ACC_INSTAURO = re.compile(
    r"(?im)^[ \t]*([A-ZÁÉÍÓÚÑ][^,|\n\d]{4,80}?)\s*,?\s*"
    r"(?:actuando[^,\n]{0,60})?\s*,?\s*"
    r"(?:instaur[oó]|interp(?:uso|usie?ron)|present[oó]|formul[oó]|incoo|incoó|promovi[oó])\s+"
    r"(?:la\s+|una\s+)?acci[oó]n\s+(?:constitucional\s+)?de\s+tutela"
)
# Apertura en primera persona del escrito de tutela: "yo, NOMBRE, identificado/mayor de edad…"
_PAT_ACC_YO = re.compile(
    r"(?i)\byo[,\s]+([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s]{5,60}?)[,\s]+"
    r"(?:mayor\s+de\s+edad|identificad[oa]|en\s+(?:mi|uso\s+de\s+mi)\s+calidad|colombian[oa]|vecin[oa]\s+de|portador[a]?\s+de)"
)

# Stopwords que NO pueden ser parte de un nombre de accionante (palabras-rol, conectores, basura)
_ACC_STOPWORDS = {
    "ACCIONADOS", "ACCIONADO", "ACCIONADAS", "ACCIONADA", "DEMANDADO", "DEMANDADA",
    "ALLEGO", "REMITO", "ENVIO", "ADJUNTO", "SE", "EL", "LA", "LOS", "LAS",
    "AUTO", "TUTELA", "ACCION", "ACCIÓN", "JUZGADO", "GOBERNACION", "GOBERNACIÓN",
    "SECRETARIA", "SECRETARÍA", "MINISTERIO", "EPS", "ESE", "DOCTOR", "DOCTORA",
    "DR", "DRA", "PARTE", "POR", "PARA", "CONTRA", "FALLO", "SENTENCIA",
    # rol / conectores / falsos positivos vistos en el corpus
    "CIUDADANO", "CIUDADANA", "SEÑOR", "SEÑORA", "TITULAR", "AGENTE", "OFICIOSO", "OFICIOSA",
    "REPRESENTANTE", "DESPACHO", "MENOR", "MENORES", "NNA", "PERSONERO", "PERSONERA",
    "SI", "SÍ", "NO", "CUMPLE", "CUMPLIO", "CUMPLIÓ", "QUIEN", "ABOGADO", "ABOGADA",
    "ACCIONANTE", "ACCIONANTES", "DEMANDANTE", "PETICIONARIO", "PETICIONARIA",
    # palabras de la fórmula "yo, … mayor de edad / identificado / en mi calidad"
    "EN", "MI", "USO", "CALIDAD", "MAYOR", "EDAD", "PROPIO", "PROPIA", "COLOMBIANO",
    "COLOMBIANA", "VECINO", "VECINA", "RESIDENTE", "IDENTIFICADO", "IDENTIFICADA",
    "DOMICILIADO", "DOMICILIADA", "PORTADOR", "PORTADORA", "OBRANDO", "ACTUANDO", "NOMBRE",
    # entidades / cargos que NO son una persona accionante
    "RECTOR", "RECTORA", "INSTITUTO", "INSTITUCION", "INSTITUCIÓN", "COLEGIO", "ESCUELA",
    "MUNICIPIO", "DEPARTAMENTO", "PROMOTOR", "PROMOTORA", "SINDICATO", "ASOCIACION",
    "ASOCIACIÓN", "SOCIEDAD", "EMPRESA", "ENTIDAD", "COMUNIDAD", "FUNDACION", "FUNDACIÓN",
    "CORDIAL", "SALUDO", "SALUDOS", "CORDIALMENTE", "ATENTAMENTE", "FAVOR", "REMITIR",
    "INFORMARLO", "DEPENDENCIA", "PETICION", "PETICIÓN", "RESPUESTA", "OFICIO", "MEDIDA",
    # conectores / verbos que delatan una frase, no un nombre (basura "PERO QUE FUE
    # RADICADA EN DOS JUZGADOS" capturada del cuerpo de un correo, 2026-05-25)
    "PERO", "QUE", "FUE", "FUERON", "RADICADA", "RADICADO", "MEDIANTE", "ANTE",
    "SEGUN", "SEGÚN", "COMO", "SOBRE", "CUYO", "CUYA", "DONDE", "PORQUE", "AVOCA",
    "VINCULA", "INSTAURADA", "INSTAURADO", "INTERPUESTA", "INTERPUESTO", "PRESENTADA",
    "PRESENTADO", "MANERA", "SIMULTANEA", "SIMULTÁNEA", "DOS",
}


def _norm_municipio(s: str) -> str:
    """Normaliza nombre de municipio: une líneas, quita puntos sueltos, MAYÚSCULAS."""
    s = re.sub(r"[\n\r]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.rstrip(".").strip()
    return s.upper()


def _looks_like_name(s: str) -> bool:
    """¿Pinta a un nombre propio de persona?"""
    s = s.strip()
    words = s.split()
    if not (2 <= len(words) <= 6):
        return False
    head = [w.upper() for w in words[:3]]
    if any(w in _ACC_STOPWORDS for w in head):
        return False
    if not all(len(w) >= 2 and w[0].isalpha() for w in words):
        return False
    return True


def _clean_acc_value(raw: str) -> Optional[str]:
    """Limpia un valor candidato de accionante. Devuelve None si no es válido."""
    if not raw:
        return None
    v = re.sub(r"[\n\r]+", " ", raw)
    v = re.sub(r"\s+", " ", v).strip()
    # Quitar basura de borde de celda de tabla / etiquetas al inicio ("| ", ": ", "- ", "– ", "• ")
    v = re.sub(r"^[\s|:.\-–·•>]+", "", v).strip()
    # Quitar tratamientos sueltos al inicio ("Sr. ", "Sra. ", "Dr. ", "el señor ", "ciudadano ", …)
    v = re.sub(
        r"(?i)^(?:(?:el|la|l[oa]s)\s+)?(?:se[ñn]ora?\.?\s+|sr[a]?\.?\s+|dra?\.?\s+|doctora?\s+|"
        r"ciudadan[oa]\s+|abogad[oa]\s+)+", "", v
    ).strip()
    # Cortar antes de palabras-frontera (incluye abreviaturas de rol legal)
    v = re.split(
        r"(?i)\b(?:identificad[oa]|C\.?C\.?|c[ée]dula|N\.?U\.?I\.?P\.?|actuando|como|en\s+contra|contra|"
        r"quien|en\s+representaci[óo]n|en\s+(?:su\s+)?(?:propio\s+)?nombre\b|en\s+su\s+(?:condici[óo]n|calidad)|"
        r"R\.?\s?L\.?|representante\s+legal|A\.?\s?O\.?\b|"
        r"agente\s+oficios|menor(?:es)?\b|hij[oa]s?\b|mayor\s+de\s+edad|"
        r"vecin[oa]\s+de|residente|domiciliad[oa]|"
        # FIX (2026-06-03): datos de contacto que la cabecera de la tutela imprime
        # tras el nombre ("ACCIONANTE: NOMBRE  CORREO ELECTRÓNICO: x@y.com / TEL ...").
        # Sin esto el accionante quedaba "NOMBRE CORREO ELECTRONICO" (c160/c229).
        r"correo\s+electr[óo]nico|correo\b|e-?mail|tel[ée]fono|celular|"
        r"n[úu]mero\s+de\s+(?:contacto|celular|tel[ée]fono)|direcci[óo]n\b|notificaci[óo]n(?:es)?\b|@|"
        r"y\s+(?:otros?\b|dem[áa]s\b|padres\s+de\b|los\s+(?:padres|dem[áa]s)\b|en\s+representaci|en\s+nombre\b))\b", v
    )[0].strip()
    v = v.strip(" |:;,.·•").strip()
    # FIX (2026-06-03): handles/usuarios de email pegados tras el nombre, en MINÚSCULA,
    # cuando la cabecera viene en mayúscula inicial ("Lucinda Antolinez Maldonado
    # lucymaldonado" → cae "lucymaldonado"). Solo si hay mezcla de casing (señal de
    # que las minúsculas son un handle, no parte del nombre); preserva nombres que
    # vienen todos en minúscula (no se toca si NINGÚN token es Mayúscula/UPPER).
    _ws = v.split()
    if len(_ws) > 2 and any(w[:1].isupper() for w in _ws):
        while len(_ws) > 2 and _ws[-1].isalpha() and _ws[-1].islower():
            _ws.pop()
        v = " ".join(_ws)
    if 5 <= len(v) <= 70 and _looks_like_name(v):
        return v.upper()
    return None


def _clean_agenciado(raw: str) -> Optional[str]:
    """Limpia el nombre del agenciado para la nota de observaciones."""
    if not raw:
        return None
    v = re.sub(r"\s+", " ", raw).strip().rstrip(",.;")
    # Quitar prefijos sueltos: "de su", "del", "su", "los", "legal de", "y representante legal de"
    v = re.sub(r"^(?:y\s+)?(?:representante\s+legal\s+(?:de\s+)?|legal\s+(?:de\s+)?|del?\s+|su\s+|l[oa]s\s+)+", "", v, flags=re.IGNORECASE).strip()
    # Si quedó muy corto o solo una inicial → descartar (probablemente anonimizado)
    if len(v) < 3:
        return None
    return v


def extract_accionante_for_case(db: Session, case: Case) -> tuple[Optional[str], Optional[str]]:
    """Extrae (accionante, nota_observaciones) del case.

    Reglas (en orden):
      1. Si detecta "Personería Municipal de X" → accionante = "PERSONERÍA MUNICIPAL DE X"
         (institución; el personero nunca actúa a título propio). Si además es agente
         oficioso de Y → nota = "Agente oficioso de Y".
      2. Si detecta "agente oficioso de Y" o "representante legal de Y" → accionante = quien
         firma/instaura; nota = "Agente oficioso de Y" / "Representante legal de Y".
      3. Persona natural simple → accionante = nombre extraído.

    Fuentes: AUTO_ADMISORIO > DEMANDA_TUTELA > SENTENCIA. Fallback: folder_name.

    Returns: (accionante, nota_observaciones). Nota puede ser None.
    """
    # Filtro de pertenencia: si la carpeta tiene docs "prestados" de otras tutelas,
    # NO leer el accionante desde ahí. Aquí no podemos usar acc_tokens (es lo que
    # estamos extrayendo), así que filtramos SOLO por radicados del case.
    # Regla (feedback Wilson 2026-05-18): el doc debe citar el rad23 o rad_forest
    # (globalmente únicos) o el rad corto en el filename (señal operativa fuerte).
    from backend.v9.regex_pass import (
        doc_belongs_to_case as _doc_belongs_to_case_acc,
        _rad_corto_from_23 as _rc23_acc,
        _rad_corto_from_folder as _rcfolder_acc,
    )
    _rads_acc = {r for r in (
        getattr(case, "radicado_23_digitos", None),
        getattr(case, "radicado_forest", None),
        _rc23_acc(getattr(case, "radicado_23_digitos", None)),
        _rcfolder_acc(getattr(case, "folder_name", None)),
    ) if r}

    # Reunir texto de los docs prioritarios. Para cada doc se mira el head (donde va el
    # encabezado de partes) y, si el doc trae una sección "[TABLAS]" más abajo (los DOCX
    # de respuesta de la SED tienen ahí la tabla REF/ACCIONANTE), también ese tramo.
    texts_by_priority: list[tuple[str, str]] = []  # (doctype, search_text)
    for dt in _ACCIONANTE_DOC_PRIORITY:
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            text = _read_doc_text(d)
            if not text or len(text) <= 150:
                continue
            # Filtro de pertenencia (solo por radicados — el accionante todavía no se sabe)
            if _rads_acc and not _doc_belongs_to_case_acc(
                set(), _rads_acc, text, getattr(d, "filename", "") or ""
            ):
                continue
            search_text = text[:10000]  # encabezado de partes + (en sentencias largas) el RESUELVE recap
            ti = text.find("[TABLAS]")
            if ti >= 9000:  # la sección de tablas quedó fuera del head → anexarla
                search_text += "\n" + text[ti:ti + 4000]
            texts_by_priority.append((dt, search_text))

    accionante: Optional[str] = None
    nota: Optional[str] = None

    def _build_nota(head_text: str) -> Optional[str]:
        """Construye la nota de agencia (Agente oficioso de X / Representante legal de X)."""
        m = _PAT_ROL_AGENCIA.search(head_text)
        if not m:
            return None
        rol_raw = m.group(1).lower()
        agenciado = _clean_agenciado(m.group(2))
        if not agenciado:
            return None
        rol = "Representante legal de" if "representante legal" in rol_raw else "Agente oficioso de"
        return f"{rol} {agenciado}"

    # En docs de la SED (RESPUESTA, NOTIFICACION, OFICIO) el cuerpo lo escribe la Secretaría
    # en primera persona ("Yo, YANETH KARINA ARAUJO MAESTRE…") y firma su funcionario → ahí
    # SOLO es fiable la celda "ACCIONANTE:" de la tabla, no los patrones de recap/primera persona.
    _SED_SIDE_DOCS = {"RESPUESTA", "NOTIFICACION", "NOTIFICACION_FALLO", "OFICIO_CUMPLIMIENTO"}

    def _cand_from(head_text: str, doctype: str) -> Optional[str]:
        """Primer nombre de persona razonable: tabla/etiqueta → 'instaurada por' → 'yo, NOMBRE'."""
        patterns = (_PAT_ACC_LABEL,) if doctype in _SED_SIDE_DOCS else (_PAT_ACC_LABEL, _PAT_ACC_INSTAURADA, _PAT_ACC_INSTAURO, _PAT_ACC_YO)
        for rx in patterns:
            m = rx.search(head_text)
            if m:
                c = _clean_acc_value(m.group(1))
                if c:
                    return c
        return None

    # FIX (2026-05-28): pattern "yo NOMBRE PROPIO ... interpongo/presento" indica
    # que el verdadero accionante es esa persona, no la Personería que solo está
    # vinculada como ministerio público. Patrón "yo, JUAN PÉREZ ... interpongo" o
    # "El suscrito, NOMBRE ... presento acción". Si match → priorizar la persona.
    _PAT_YO_INTERPONGO = re.compile(
        r"(?i)(?:yo|el\s+suscrito|la\s+suscrita)[\s,]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{4,80}?)"
        r"[\s,]+(?:identificad[oa]\s+con|mayor\s+de\s+edad|en\s+nombre\s+propio|"
        r"interpongo|presento|impetro)\b"
    )
    # Personería ACCIONANTE LEGÍTIMA solo si firma "en calidad de Personero/a Municipal de X"
    _PAT_PERSONERIA_EN_CALIDAD = re.compile(
        r"(?i)en\s+(?:mi\s+)?calidad\s+de\s+personer[oa]\s+municipal"
    )

    for _dt, head in texts_by_priority:
        # --- Caso 0 (NUEVO 2026-05-28): si hay "yo NOMBRE ... interpongo",
        # priorizar la PERSONA real sobre la Personería (vinculada/asesora). ---
        m_yo = _PAT_YO_INTERPONGO.search(head[:5000])
        if m_yo and not _PAT_PERSONERIA_EN_CALIDAD.search(head[:5000]):
            cand_yo = _clean_acc_value(m_yo.group(1))
            if cand_yo and len(cand_yo) >= 6:
                accionante = cand_yo
                nota = _build_nota(head)
                break

        # --- Caso 1: Personería (siempre normalizar a institución) ---
        # Solo si NO se detectó persona propia interponiendo arriba.
        m_pers = _PAT_PERSONERIA.search(head)
        if m_pers:
            muni = _norm_municipio(m_pers.group(1))
            muni = re.sub(r"\s+SANTANDER\.?$", "", muni).strip()
            # FIX 2026-06-01: el regex sobre-captura boilerplate tras el municipio
            # ("CONFINES CORDIAL SALUDO", "MOGOTES CON EL FIN DE QUE", "ESTA LOCALIDAD
            # PARA QUE"). Validar/recortar contra la lista oficial de municipios: solo
            # aceptamos un municipio RECONOCIDO → forma canónica. La lista es el
            # componente parametrizable por entidad/departamento (generalización).
            from backend.agent.extractors.municipios_santander import (
                find_municipio_in_text, is_municipio_santander,
            )
            canon = find_municipio_in_text(muni) or (muni if is_municipio_santander(muni) else None)
            if canon and canon not in _ACC_STOPWORDS and len(canon) >= 3:
                accionante = f"PERSONERÍA MUNICIPAL DE {canon}"
                nota = _build_nota(head)
                break  # personería tiene prioridad máxima
            # municipio no reconocido (basura capturada) → NO crear personería sucia;
            # seguir a otros casos/docs (la carpeta curada suele tenerlo bien).

        # --- Caso 2: agente oficioso / representante legal → accionante = quien firma; nota = agenciado ---
        nota_cand = _build_nota(head)
        cand = _cand_from(head, _dt)
        if cand:
            accionante = cand
            nota = nota_cand  # puede ser None (persona natural simple)
            break

    # --- Fallback: folder_name (formato "<rad_corto> <ACCIONANTE>") ---
    if not accionante and case.folder_name:
        m = re.match(r"^\d{4}[-\s]\d{3,5}(?:\s+\d{6,7})?\s+(.+)$", case.folder_name.strip())
        if m:
            raw = m.group(1).strip()
            raw = re.sub(r"\s+(?:ACCIONAD[OA]S?|VS\.?|CONTRA|Y\s+OTROS?|INCIDENTE_HUERFANO.*).*$", "", raw, flags=re.IGNORECASE)
            raw_up = raw.upper().strip()
            if "PERSONER" in raw_up:
                # Normalizar a institución: extraer el municipio tras "DE"
                mm = re.search(r"DE\s+(.+)$", raw_up)
                muni = mm.group(1).strip() if mm else raw_up
                muni = re.sub(r"\s+SANTANDER\.?$", "", muni).strip()
                if muni and len(muni) >= 3:
                    accionante = f"PERSONERÍA MUNICIPAL DE {muni}"
            elif raw_up and raw_up != "SIN_ACCIONANTE" and _looks_like_name(raw_up):
                accionante = raw_up

    return accionante, nota


# ============================================================
# ACCIONADOS + VINCULADOS
# ============================================================

# Formas canónicas de las entidades de la SED (para normalizar)
_CANON_GOBERNACION = "GOBERNACIÓN DE SANTANDER"
_CANON_SECRETARIA = "SECRETARÍA DE EDUCACIÓN DEL DEPARTAMENTO DE SANTANDER"

# Label "Accionado(s): ENTIDAD [- ENTIDAD ...]" — captura el valor de la línea de la
# etiqueta + líneas de continuación INDENTADAS (algunos autos listan una entidad por
# línea). Se detiene al ver una nueva etiqueta "Palabra:".
_PAT_ACCIONADO_LABEL = re.compile(
    r"(?im)^[ \t]*Accionad[oa]s?(?:\s*\(s\))?[ \t]*[:\.]+[ \t]*"
    r"("
    r"[^\r\n]{0,400}"
    r"(?:\n[ \t]+(?![A-ZÁÉÍÓÚÑ][a-záéíóúñ]+\s*[:\.])[^\r\n]{1,250}){0,8}"
    r")"
)
# Palabras que identifican una entidad (pública / privada / educativa). Sirve como
# guarda para aceptar el valor de la etiqueta "Accionado:" y para validar fragmentos.
_ENTITY_WORD_RE = re.compile(
    r"(?i)\b(?:GOBERNACI[ÓO]N|GOBIERNO|DEPARTAMENTO|MUNICIPIO|ALCALD[ÍI]A|"
    r"SECRETAR[ÍI]A|MINISTERIO|DIRECCI[ÓO]N\s+(?:DE|GENERAL|TERRITORIAL)|"
    r"SUBDIRECCI[ÓO]N|UNIDAD\s+(?:ADMINISTRATIVA|DE)|AGENCIA|INSTITUTO|INSTITUCI[ÓO]N|"
    r"COLEGIO|ESCUELA|LICEO|UNIVERSIDAD|CENTRO\s+EDUCATIVO|JARD[ÍI]N\s+INFANTIL|"
    r"FUNDACI[ÓO]N|CORPORACI[ÓO]N|ASOCIACI[ÓO]N|COOPERATIVA|CAJA\b|FONDO\b|EMPRESA|"
    r"HOSPITAL|CL[ÍI]NICA|E\.?S\.?E\.?\b|ESE\b|E\.?P\.?S\.?\b|EPS\b|A\.?R\.?L\.?\b|"
    r"ARL\b|A\.?F\.?P\.?\b|AFP\b|FOMAG|FIDUPREVISORA|PORVENIR|PROTECCI[ÓO]N\s+S|"
    r"COLFONDOS|COLPENSIONES|PERSONER[ÍI]A|FISCAL[ÍI]A|PROCURADUR[ÍI]A|DEFENSOR[ÍI]A|"
    r"CONTRALOR[ÍI]A|REGISTRADUR[ÍI]A|CONSEJO\b|TRIBUNAL|JUZGADO|NACI[ÓO]N\b|RECTOR|"
    r"SENA\b|ICBF|SIMAT|CNSC|COMISAR[ÍI]A|NOTAR[ÍI]A|S\.?A\.?S?\.?\b|LTDA|EICE|"
    r"E\.?I\.?C\.?E\.?|S\.?A\.?S\.?\b|ENTIDAD|UAE\b|UAESP|ANSPE)\b"
)
# "en contra de [ENTIDAD]" — entidades reconocibles por keyword inicial
_ENTITY_KW = (
    r"GOBERNACI[ÓO]N|MUNICIPIO|ALCALD[ÍI]A|SECRETAR[ÍI]A|MINISTERIO|"
    r"INSTITUCI[ÓO]N\s+EDUCATIVA|INSTITUTO|COLEGIO|ESCUELA|LICEO|UNIVERSIDAD|"
    r"E\.?S\.?E\.?|ESE\b|EPS|HOSPITAL|FUNDACI[ÓO]N|PERSONER[ÍI]A|FISCAL[ÍI]A|"
    r"DEPARTAMENTO|CONSEJO|UAE|RECTOR\w*|FONDO|PORVENIR|COLPENSIONES"
)
_PAT_EN_CONTRA_ENTITY = re.compile(
    rf"(?i)\b(?:en\s+contra\s+de(?:l)?|contra\s+(?:el\s+|la\s+|los\s+|las\s+|del\s+)?)\s*"
    rf"((?:LA\s+|EL\s+)?(?:{_ENTITY_KW})[A-ZÁÉÍÓÚÑ\s,\-–.0-9]{{3,180}}?)"
    rf"(?=\s+(?:procurando|por\s+(?:considerar|cuanto|la|el|haber|no)|para\s+(?:que|la|el)|"
    rf"toda\s+vez|y\s+(?:de\s+)?oficio|en\s+procura|solicitando|al\s+considerar|\.|\bquien\b))"
)
# Vinculación: "se ordena/dispone la vinculación de..." / "se vincula a..." / "vincúlese a..."
_PAT_VINCULACION = re.compile(
    r"(?i)(?:se\s+(?:ordena\s+(?:la\s+)?|dispone\s+(?:la\s+)?)?vinculaci[óo]n\s+(?:de\s+)?(?:oficio(?:sa)?\s+)?(?:al?\s+|a\s+l[aoes]+\s+|del?\s+)?"
    r"|se\s+vincula(?:n)?\s+(?:de\s+oficio\s+)?(?:al?\s+|a\s+l[aoes]+\s+)?(?:tr[áa]mite\s+tutelar\s+a;?\s*|presente\s+(?:tr[áa]mite|asunto)\s+a\s+)?"
    r"|vinc[úu]lese\s+(?:de\s+oficio\s+)?(?:al?\s+|a\s+l[aoes]+\s+)?)"
    r"([A-ZÁÉÍÓÚÑ][^\.]{8,400}?)(?=\s*(?:\.|,?\s*toda\s+vez|por\s+cuanto|quienes|para\s+que|en\s+atenci[óo]n|a\s+fin\s+(?:de|que)))"
)


# Separadores entre entidades dentro del campo accionados: salto de línea, " - ",
# " | ", " · ", ";", " + ", "  y otros". (NO partimos por coma sola: rompería nombres
# como "SECRETARÍA DE EDUCACIÓN, CULTURA Y DEPORTE".)
_ENTITY_SPLIT_RE = re.compile(
    r"(?:[\r\n]+|\s+[-–—|·•]\s+|\s*;\s*|\s+\+\s+|\s+y\s+otr[oa]s?\b\s*)", re.IGNORECASE
)
# Placeholders que NO son una entidad real.
_ACC_NON_VALUE_RE = re.compile(
    r"(?i)^\s*(?:ningun[oa]s?|n\.?\s*a\.?|no\s+aplica|sin\s+(?:accionad|determin)|"
    r"-+|\.+|s/?d|x+|por\s+determinar)\s*$"
)


# Cláusulas que cuelgan del nombre de la entidad pero no son parte de él
# ("DEPARTAMENTO DE SANTANDER, REPRESENTADO LEGALMENTE POR JUVENAL DÍAZ MATEUS, O QUIEN…").
_ENTITY_TAIL_CLAUSE_RE = re.compile(
    r"(?i)[,;]?\s*(?:representad[oa]s?\b|en\s+cabeza\s+de\b|a\s+trav[ée]s\s+de\b|"
    r"por\s+(?:conducto|intermedio)\s+de\b|en\s+la\s+persona\s+de\b|en\s+su\s+calidad\s+de\b|"
    r"qui[eé]n(?:es)?\s+(?:haga|hagan)\b|o\s+qui[eé]n\b|representante\s+legal\b|"
    r"identificad[oa]\b|con\s+(?:c\.?c\.?|nit)\b).*$"
)


def _canon_entity(s: str) -> str:
    """Normaliza UNA entidad. Gobernación / Secretaría de Educación departamental de
    Santander → forma canónica; cualquier otra (IE, municipio, EPS, fondo, secretaría
    municipal, ministerio…) se conserva tal cual, limpia y en mayúsculas."""
    u = re.sub(r"\s+", " ", s or "").strip().strip(",.;:·-–—()[]\"'").upper()
    u = _ENTITY_TAIL_CLAUSE_RE.sub("", u).strip().strip(",.;:·-–—").strip()
    if not u or len(u) < 3:
        return ""
    # Gobernación de Santander (también "DEPARTAMENTO/DEPARTAMENTAL DE SANTANDER" — misma
    # persona jurídica, o un fragmento de "Secretaría de Educación Departamental de Santander")
    if re.search(r"\bGOBERNACI[ÓO]N\b", u) or re.fullmatch(r"(?:EL\s+)?DEPARTAMENT(?:O|AL)\s+DE\s+SANTANDER\.?", u):
        return _CANON_GOBERNACION
    # Secretaría de Educación — ¿la DEPARTAMENTAL de Santander, o una municipal/nacional/otra?
    if re.search(r"SECRETAR[ÍI]A\s+(?:DEPARTAMENTAL\s+)?DE\s+EDUCA[CS]I?[ÓO]?N?\b", u):
        es_municipal = bool(re.search(r"\bMUNICIPAL\b", u))
        es_nacional = bool(re.search(r"\bNACIONAL\b", u))
        # ¿menciona un lugar que NO es Santander? (p.ej. "DE GIRÓN", "DE BARRANCABERMEJA")
        otro_lugar = bool(
            re.search(r"\bDE\s+(?!SANTANDER\b|EDUCA|LA\b|EL\b|LOS\b)[A-ZÁÉÍÓÚÑ]{4,}", u)
            and not re.search(r"\bSANTANDER\b", u)
        )
        if not (es_municipal or es_nacional or otro_lugar):
            return _CANON_SECRETARIA
        return re.sub(r"^(?:LA|EL)\s+", "", u).strip()[:180]
    # Otra entidad: quitar artículo inicial
    u = re.sub(r"^(?:LA|EL|LOS|LAS|UNA?)\s+", "", u).strip()
    return u[:180]


def _looks_like_accionado_value(raw: str) -> bool:
    """¿El texto tras la etiqueta 'Accionado:' parece una entidad (o lista de
    entidades) y no un placeholder / basura de OCR?"""
    if not raw:
        return False
    v = re.sub(r"\s+", " ", raw).strip()
    if len(v) < 4 or len(v) > 500 or _ACC_NON_VALUE_RE.match(v):
        return False
    # Debe tener alguna palabra-entidad reconocible (o ser GOB/SecEdu, ya cubiertos por
    # _ENTITY_WORD_RE vía GOBERNACI/SECRETAR), o al menos un bloque de 4+ mayúsculas.
    return bool(_ENTITY_WORD_RE.search(v) or re.search(r"[A-ZÁÉÍÓÚÑ]{4,}", v))


_CANON_ENTITIES = {_CANON_GOBERNACION, _CANON_SECRETARIA}


def _normalize_entity_list(raw: str) -> str:
    """Normaliza la lista de accionados PRESERVANDO TODAS las entidades listadas.
    (Antes se descartaban las que no fueran GOB/SecEdu, dejando 'accionados' incompleto
    — DeepSeek lo señaló en ~191 casos: Porvenir SA, Ministerio de Educación, IE, etc.)"""
    pieces = [p for p in _ENTITY_SPLIT_RE.split(raw or "") if p and p.strip()]
    if not pieces:
        pieces = [raw or ""]
    out: list[str] = []
    dropped: list[str] = []
    for p in pieces:
        c = _canon_entity(p)
        if not c or c in out:
            continue
        # Si hay >1 fragmento, descartar los que no parecen una entidad (suelen ser el
        # nombre del representante legal o ruido de OCR colado tras un " - ").
        if len(pieces) > 1 and c not in _CANON_ENTITIES and not _ENTITY_WORD_RE.search(c):
            dropped.append(c)
            continue
        out.append(c)
    if not out and dropped:  # todos quedaron descartados → mejor devolver algo
        out = [dropped[0]]
    if out:
        return " - ".join(out)
    return _canon_entity(raw or "")[:200]


def extract_accionados_for_case(db: Session, case: Case) -> Optional[str]:
    """Extrae los accionados. Estrategia:
      1. Si el auto admisorio dice ACCIONADO: explícito → usarlo (puede ser IE,
         municipio, Gobernación, Secretaría). Normaliza GOB/SEC a forma canónica.
      2. "en contra de [ENTIDAD]" en cualquier doc.
      3. Default: GOBERNACIÓN + SECRETARÍA DE EDUCACIÓN — porque las tutelas que
         gestiona la SED son SIEMPRE contra ellos (lo confirmó el usuario), salvo
         que el auto especifique otra entidad principal (caso: la SED es solo vinculada).

    Default aplica a cualquier case con rad23 (= tutela válida).
    """
    # Texto de los autos admisorios primero, luego cualquier doc
    autos = db.query(Document).filter(Document.case_id == case.id, Document.doc_type == "AUTO_ADMISORIO").all()
    for d in autos:
        text = d.extracted_text or ""
        if not text or len(text) < 150:
            continue
        head = text[:4000]
        # 1. Label ACCIONADO: (puede listar varias entidades, en una o varias líneas)
        m = _PAT_ACCIONADO_LABEL.search(head)
        if m:
            raw = m.group(1).strip()
            if _looks_like_accionado_value(raw):
                return _normalize_entity_list(raw)
        # 2. "en contra de [ENTIDAD]"
        m = _PAT_EN_CONTRA_ENTITY.search(head)
        if m:
            return _normalize_entity_list(m.group(1))

    # Sin auto admisorio claro → buscar "en contra de" en cualquier doc
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        text = _read_doc_text(d)
        if not text or len(text) < 150:
            continue
        m = _PAT_EN_CONTRA_ENTITY.search(text[:4000])
        if m:
            return _normalize_entity_list(m.group(1))
        m = _PAT_ACCIONADO_LABEL.search(text[:4000])
        if m:
            raw = m.group(1).strip()
            if _looks_like_accionado_value(raw):
                return _normalize_entity_list(raw)

    # 3. Default — toda tutela gestionada por la SED es contra GOB+SEC
    if case.radicado_23_digitos:  # es una tutela válida
        return f"{_CANON_GOBERNACION} - {_CANON_SECRETARIA}"
    return None


# Preámbulo de vinculación a recortar: el extractor (regex/LLM) suele capturar el
# verbo + conectores antes de la 1ra entidad ("VINCULAR la presente acción a la
# SECRETARÍA…", "trámite tutelar a; FUNDACIÓN…", "de manera oficiosa a…"). Se
# recorta hasta el inicio de la entidad real. 2026-06-01.
_RE_VINC_LEAD = re.compile(
    r"(?i)^(?:\s*[-:;,]\s*)*"
    r"(?:(?:la|el|los|las|al|a|de|del|en|por|y|este|esta|presente|tr[áa]mite|tutelar|"
    r"tutela|demanda|asunto|actuaci[óo]n|acci[óo]n|accionar|litis|resguardo|"
    r"constitucional|manera|oficios[ao]|pasiva|calidad|accionad[oa]s|intermedio|sus|"
    r"representantes|legales|adem[áa]s|oficio|orden[ae]se|v[íi]ncul\w*|cont[ée]stese|"
    r"p[óo]ngase|conocimiento|se|se[ñn]or|director)\b[\s.,;:-]*)+"
)


def _clean_vinculados_lead(v: str) -> str:
    """Recorta el preámbulo de vinculación. Devuelve "" si no queda entidad."""
    s = (v or "").strip()
    s = _RE_VINC_LEAD.sub("", s).strip(" .,;:-")
    return s if len(s) >= 4 else ""


def extract_vinculados_for_case(db: Session, case: Case) -> Optional[str]:
    """Extrae los vinculados del cuerpo del auto admisorio (frases 'se vincula a...')."""
    autos = db.query(Document).filter(Document.case_id == case.id, Document.doc_type == "AUTO_ADMISORIO").all()
    for d in autos:
        text = d.extracted_text or ""
        if not text or len(text) < 150:
            continue
        head = text[:5000]
        m = _PAT_VINCULACION.search(head)
        if m:
            raw = m.group(1)
            v = re.sub(r"[\n\r]+", " ", raw)
            v = re.sub(r"\s+", " ", v).strip().rstrip(",.;")
            # Cortar antes de cláusulas de cierre
            v = re.split(r"(?i)\b(?:toda\s+vez|por\s+cuanto|quienes|para\s+que|en\s+atenci[óo]n|a\s+fin\s+(?:de|que)|al\s+considerar)\b", v)[0].strip().rstrip(",.;")
            v = _clean_vinculados_lead(v)  # recortar preámbulo "VINCULAR a la …"
            if 8 <= len(v) <= 300:
                return v[:250]
    return None


# ============================================================
# DERECHO_VULNERADO  (campo 7 — semántico, regex de tags + LLM fallback)
# ============================================================

# Vocabulario controlado cerrado. Orden = prioridad: cuando una tutela invoca
# varios derechos, la columna los concatena "A - B - C" en ESTE orden (estable,
# auditable). `OTRO` sólo lo puede emitir el LLM (derecho real fuera de la lista).
# `SIN_DETERMINAR` es el default cuando ni regex ni LLM logran nada.
DERECHO_VOCAB: tuple[str, ...] = (
    "EDUCACION",
    "SALUD",
    "PETICION",
    "DEBIDO_PROCESO",
    "VIDA",
    "SEGURIDAD_SOCIAL",
    "MINIMO_VITAL",
    "TRABAJO",
    "IGUALDAD",
    "INTIMIDAD",
    "HABEAS_DATA",
    "OTRO",
)
_DERECHO_PRIORITY = {tag: i for i, tag in enumerate(DERECHO_VOCAB)}
DERECHO_SIN_DETERMINAR = "SIN_DETERMINAR"

# Keyword (sobre texto sin tildes, minúsculas) → tag canónico. Multi-palabra
# primero para que "seguridad social" gane antes que "social" suelto, etc.
_DERECHO_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("seguridad social", "SEGURIDAD_SOCIAL"),
    ("minimo vital", "MINIMO_VITAL"),
    ("debido proceso", "DEBIDO_PROCESO"),
    ("habeas data", "HABEAS_DATA"),
    ("proteccion de datos", "HABEAS_DATA"),
    ("datos personales", "HABEAS_DATA"),
    ("transporte escolar", "EDUCACION"),
    ("educac", "EDUCACION"),            # educación / educacion / educativa / educativo
    ("ensenanza", "EDUCACION"),
    ("escolar", "EDUCACION"),
    ("salud", "SALUD"),
    ("peticion", "PETICION"),
    ("vida digna", "VIDA"),
    ("dignidad humana", "VIDA"),
    ("integridad personal", "VIDA"),
    ("integridad fisica", "VIDA"),
    (" vida", "VIDA"),                  # con espacio: evita "convivencia", etc.
    ("trabajo", "TRABAJO"),
    ("igualdad", "IGUALDAD"),
    ("no discriminacion", "IGUALDAD"),
    ("discriminacion", "IGUALDAD"),
    ("intimidad", "INTIMIDAD"),
    ("buen nombre", "INTIMIDAD"),
)

# Derechos "raros" que el LLM 4B tiende a ALUCINAR (sobre-etiqueta sistemática
# medida 2026-06-02: ~50% de los cambios de derecho del 4B agregaban estos sin
# respaldo). Solo se conservan si la demanda los EVIDENCIA textualmente; los "core"
# (EDUCACION/SALUD/VIDA/TRABAJO/PETICION/DEBIDO_PROCESO/IGUALDAD) pasan sin filtro.
# La evidencia REUSA `_DERECHO_KEYWORDS` (+ sinónimos inequívocos).
_SPECULATIVE_DERECHOS = frozenset({"INTIMIDAD", "HABEAS_DATA", "MINIMO_VITAL", "SEGURIDAD_SOCIAL"})
_SPEC_EVIDENCE: dict[str, tuple[str, ...]] = {
    tag: tuple(kw for kw, t in _DERECHO_KEYWORDS if t == tag)
    for tag in _SPECULATIVE_DERECHOS
}
_SPEC_EVIDENCE["SEGURIDAD_SOCIAL"] += ("pension", "pensional")
_SPEC_EVIDENCE["MINIMO_VITAL"] += ("subsistencia",)


def _ground_speculative_derechos(tags: list[str], text: str) -> list[str]:
    """Descarta los derechos especulativos que el LLM propuso pero que la demanda
    NO respalda textualmente (anti-alucinación del 4B). Determinista. Los tags core
    pasan intactos."""
    folded = _fold(text or "")
    out: list[str] = []
    for t in tags:
        if t in _SPECULATIVE_DERECHOS and not any(kw in folded for kw in _SPEC_EVIDENCE.get(t, ())):
            continue  # tag especulativo sin evidencia → descartar (alucinación)
        out.append(t)
    return out

# Marcadores que CIERRAN la enumeración de derechos: lo que sigue ya no son
# derechos del reclamo, sino quién los vulneró / a quién pertenecen / etc.
# Se busca sobre el texto ORIGINAL de la región (con tildes, case-insensitive).
_DERECHO_REGION_END = re.compile(
    r"(?i)\b(?:"
    r"los?\s+cuales?|las?\s+cuales?|"
    r"que\s+(?:considera|estima|cree|denomina|fueron|han\s+sido|estim[oó]|se\b|le\b)|"
    r"toda\s+vez|por\s+cuanto|presuntamente|supuestamente|en\s+raz[óo]n|debido\s+a|"
    r"como\s+consecuencia|con\s+ocasi[óo]n|a\s+causa|"
    r"por\s+(?:la|el|las|los)\s+(?:acci[óo]n|omisi[óo]n|negativa|falta|conducta|actuaci[óo]n|decisi[óo]n)|"
    r"por\s+parte\s+de|vulnerad[oa]s?\s+por|amenazad[oa]s?\s+por|"
    r"accionant|accionad|demandant|demandad|"
    r"de\s+(?:la|el|su|mi|sus|mis)\s+(?:menor|ni[ñn][oa]s?|hij[oa]s?|agenciad[oa]s?|representad[oa]s?|poderdant|prohijad[oa])|"
    r"contra\s+l[oa]s?\b|en\s+contra"
    r")\b"
)
# Nombres de entidades que contienen "educación" pero NO son el derecho: la
# Secretaría / Ministerio de Educación es la ACCIONADA, no el derecho vulnerado.
_DERECHO_ENTITY_NOISE = (
    "secretaria de educacion", "ministerio de educacion", "subsecretaria de educacion",
    "departamental de educacion", "departamento de educacion", "secretaria de educa",
    "direccion de educacion", "viceministerio de educacion",
)

# Ancla: el reclamo de la tutela se enuncia como "derechos fundamentales a la X,
# Y y Z" (a veces "constitucionales"). Capturamos ~160 chars de "región" tras el
# conector para escanear sólo ahí. El conector (a la / al / de) es opcional, pero
# si la región empieza con boilerplate jurisprudencial ("...cuando no se dispone
# de otro medio...", "...del actor", "...amenazados y vulnerados. En tal
# sentido...") la descartamos: ahí "derechos fundamentales" se usa en abstracto,
# no es la enumeración del caso.
_DERECHO_ANCHOR = re.compile(
    r"(?i)derechos?\s+(?:fundamental(?:es)?|constitucional(?:es)?(?:\s+y\s+legal(?:es)?)?)\s*"
    r"(?:(?:presuntamente\s+|supuestamente\s+)?(?:vulnerad[oa]s?|amenazad[oa]s?)?\s*)?"
    r"(?:a\s+l[oa]s?\s+|al\s+|a\s+las\s+|de\s+l[oa]s?\s+|de\s+|,\s*)?"
    r"(.{0,180})",
    re.DOTALL,
)

# Sólo escaneamos el encabezado del doc (parte resolutiva del auto / antecedentes
# de la sentencia / petitorio de la demanda). Más allá vienen las "CONSIDERACIONES"
# con jurisprudencia que menciona derechos en abstracto → ruido (mitigado además
# por `_DERECHO_REGION_STOPSTART` y `_DERECHO_REGION_END`).
_DERECHO_SCAN_CHARS = 8000
# Si la región (lo que sigue al conector) ARRANCA con una de estas frases, NO es
# la enumeración del reclamo sino texto considerativo / jurisprudencial.
_DERECHO_REGION_STOPSTART = re.compile(
    r"(?i)^\s*(?:"
    r"cuando\b|respecto\b|consagrad|previst|son\b|como\b|que\b|y\b|cuy[oa]s?\b|"
    r"seg[uú]n\b|tales?\b|los?\s+cuales?\b|las?\s+cuales?\b|del?\s+actor|"
    r"del?\s+accionante|del?\s+demandante|del?\s+funcionario|del?\s+servidor|"
    r"del?\s+peticionari|personas?\b|ciudadan|colombian|usuari|asociad[oa]s|"
    r"en\s+(?:tal|el\s+presente|este|aras|virtud)|"
    r"para\b|presunta|amenazad[oa]s?\b|vulnerad[oa]s?\s+(?:por|en\b|de\b|;|\.)|"
    r"invocad|no\s+se\s+dispone|frente\s+a|sin\s+que|al\s+ser\b|reconocid"
    r")"
)


def _fold(s: str) -> str:
    """minúsculas + sin tildes (para matching robusto de keywords)."""
    s = _ud.normalize("NFKD", s)
    return "".join(c for c in s if not _ud.combining(c)).lower()


def _tags_in_region(region: str) -> list[str]:
    """Devuelve los tags canónicos presentes en una 'región' de texto, dedup.

    Antes de buscar keywords: (1) trunca la región en el cierre de la enumeración
    (`_DERECHO_REGION_END`), (2) trunca en el primer fin de oración ('. ' + may.),
    (3) borra nombres de entidades que contienen 'educación' (la Secretaría es la
    accionada, no el derecho).
    """
    m = _DERECHO_REGION_END.search(region)
    if m:
        region = region[:m.start()]
    m = re.search(r"\.\s+[A-ZÁÉÍÓÚÑ]", region)
    if m:
        region = region[:m.start()]
    folded = _fold(region)
    for noise in _DERECHO_ENTITY_NOISE:
        folded = folded.replace(noise, " ")
    found: list[str] = []
    for kw, tag in _DERECHO_KEYWORDS:
        if kw in folded and tag not in found:
            found.append(tag)
    return found


def _extract_derechos_from_text(text: str) -> list[str]:
    """Escanea el ENCABEZADO del doc buscando enumeraciones de derechos tras el
    ancla y devuelve la lista de tags canónicos (dedup, orden de prioridad).

    Descarta las regiones que arrancan con boilerplate (`_DERECHO_REGION_STOPSTART`).
    No corta en la primera región: una enumeración real puede partirse en varias
    (p.ej. el auto repite el reclamo en su parte resolutiva), pero al limitar el
    escaneo a `_DERECHO_SCAN_CHARS` se evita la zona de "CONSIDERACIONES".
    """
    if not text:
        return []
    head = text[:_DERECHO_SCAN_CHARS]
    found: list[str] = []
    for m in _DERECHO_ANCHOR.finditer(head):
        region = m.group(1)
        if _DERECHO_REGION_STOPSTART.search(region):
            continue
        for tag in _tags_in_region(region):
            if tag not in found:
                found.append(tag)
    found.sort(key=lambda t: _DERECHO_PRIORITY.get(t, 999))
    return found


def _format_derechos(tags: list[str]) -> Optional[str]:
    if not tags:
        return None
    return " - ".join(tags)


# Doctypes donde el derecho invocado aparece con más fiabilidad (prioridad)
_DERECHO_DOC_PRIORITY = ["AUTO_ADMISORIO", "DEMANDA_TUTELA", "SENTENCIA_1RA", "SENTENCIA_2DA"]


def _llm_classify_derecho(text: str) -> Optional[str]:
    """Fallback LLM (Qwen3-4B local): clasifica el/los derecho(s) invocado(s)
    al vocabulario controlado. Devuelve "A - B" o None si falla / texto pobre.

    Respeta `V9_DISABLE_LLM=true`. Si llama-server no responde, devuelve None
    silenciosamente (NO rompe la extracción).
    """
    if os.getenv("V9_DISABLE_LLM", "false").lower() == "true":
        return None
    text = (text or "").strip()
    if len(text) < 150:
        return None
    try:
        from backend.extraction.ai_extractor import _call_local
    except ImportError as e:
        logger.warning("ai_extractor no importable: %s", e)
        return None

    vocab = ", ".join(t for t in DERECHO_VOCAB)
    prompt = (
        "/no_think\n"
        "Eres un clasificador jurídico. Lee el texto de una acción de tutela y di "
        "qué derecho(s) fundamental(es) se invocan como vulnerados.\n"
        f"Responde ÚNICAMENTE con uno o varios de estos tags, separados por ' - ': {vocab}.\n"
        "Usa 'OTRO' sólo si el derecho real no está en la lista. Si no puedes determinarlo, "
        "responde exactamente 'SIN_DETERMINAR'. No expliques nada más.\n\n"
        f"Texto:\n{text[:3500]}"
    )
    msgs = [
        {"role": "system", "content": "Clasificas derechos fundamentales. Respondes sólo con los tags pedidos."},
        {"role": "user", "content": prompt},
    ]
    try:
        raw, _, _ = _call_local(msgs, "qwen3-4b-iuris", max_tokens=64)
    except Exception as e:
        logger.warning("LLM derecho_vulnerado falló: %s", str(e)[:200])
        return None
    if not raw:
        return None
    raw_fold = _fold(raw)
    # 1. ¿el modelo dijo explícitamente SIN_DETERMINAR? respétalo
    if re.search(r"\bsin[ _]determinar\b", raw_fold) and not re.search(
        r"\b(?:educac|salud|peticion|debido|vida|trabajo|igualdad|intimidad|habeas)\b", raw_fold
    ):
        return DERECHO_SIN_DETERMINAR
    # 2. Buscar tags del vocab por nombre (tolerando ' ' por '_') o por keyword del dominio
    tags: list[str] = []
    for tag in DERECHO_VOCAB:
        tag_pat = re.escape(tag).replace(r"\_", r"[ _]").lower()
        if re.search(rf"\b{tag_pat}\b", raw_fold) and tag not in tags:
            tags.append(tag)
    # 3. fallback: si el modelo respondió en prosa, mapear keywords del dominio
    if not tags:
        tags = _tags_in_region(" " + raw + " ")
    if not tags:
        return None
    # Grounding: descartar derechos especulativos que el LLM alucinó sin evidencia.
    tags = _ground_speculative_derechos(tags, text)
    if not tags:
        return None
    if "OTRO" in tags and len(tags) > 1:
        tags = [t for t in tags if t != "OTRO"]  # OTRO sólo si es lo único
    tags.sort(key=lambda t: _DERECHO_PRIORITY.get(t, 999))
    return " - ".join(tags)


# ============================================================
# Selección de doc fuente para campos SEMÁNTICOS (asunto / derecho)
# ============================================================
# El asunto y el derecho describen el RECLAMO ORIGINAL del accionante. Si se lee
# el doc equivocado —un auto de desacato, un informe de cumplimiento, o un PDF
# mal rotulado como DEMANDA_TUTELA que en realidad es un AutoNoSanciona— el
# clasificador (regex o LLM) describe la ETAPA PROCESAL en vez del reclamo.
# `_best_claim_text` elige el doc que mejor refleja el reclamo original.
_CLAIM_DEM_MARK = [r"BAJO LA GRAVEDAD DEL JURAMENTO", r"NO HE PRESENTADO OTRA",
                   r"PRETENSIONES", r"\bHECHOS\b", r"JURAMENTO", r"ACCION DE TUTELA",
                   r"instaur", r"interpong", r"agente oficios", r"en mi calidad de"]
# Head que delata una etapa procesal POSTERIOR (no la demanda original).
_CLAIM_NOT_DEMANDA = re.compile(
    r"INCIDENTE DE DESACATO|\bAUTO\b|INFORME DE CUMPLIMIENTO|VISITA OCULAR|"
    r"REQUERIMIENTO PREVIO|DECIDE SANCI|APERTURA.{0,8}PRUEBAS|NO SANCIONA", re.I)


def _best_claim_text(db: Session, case: Case, max_chars: int = 9000) -> tuple[str, bool]:
    """Devuelve (texto, es_demanda_real) del doc que mejor refleja el reclamo
    original del accionante. Penaliza autos/desacato/informes (etapa procesal).
    `es_demanda_real=False` ⇒ no hay demanda fiable → el caller debe ser honesto
    (SIN_DETERMINAR/flag) en vez de clasificar una etapa procesal."""
    scored: list[tuple[int, str]] = []
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        t = d.extracted_text if d.extracted_text else (_read_doc_text(d) or "")
        if len(t) < 250:
            continue
        head = t[:6000]
        sc = sum(2 for m in _CLAIM_DEM_MARK if re.search(m, head, re.I))
        dt = d.doc_type or "OTRO"
        if dt in ("DEMANDA_TUTELA", "ANEXO_DEMANDA"):
            sc += 2
        if dt == "AUTO_ADMISORIO":
            sc += 3  # el auto admisorio reenuncia el reclamo original limpio
        if dt in ("RESPUESTA", "DOCX_RESPUESTA", "RESPUESTA_SED"):
            sc -= 4   # defensa de la SED, NO el reclamo del accionante
        if _CLAIM_NOT_DEMANDA.search(t[:1400]):
            sc -= 6   # head de etapa procesal posterior → NO es la demanda
        scored.append((sc, t[:max_chars]))
    if not scored:
        return "", False
    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    sc, t = scored[0]
    return t, sc >= 4


def extract_derecho_vulnerado_for_case(
    db: Session, case: Case, *, use_llm: bool = True
) -> tuple[Optional[str], str]:
    """Extrae derecho_vulnerado del case. Campo SEMÁNTICO → autoridad = LLM.

    Estrategia (2026-06, LLM-first):
      1. Si `use_llm` y el LLM local está disponible: lee la demanda real
         (`_best_claim_text`, que excluye autos/desacato/informes) y clasifica
         al vocabulario controlado. ESTA es la autoridad — el regex de keywords
         sobre-aplica EDUCACION (lo dispara el nombre del accionado
         "Secretaría de Educación" o una mención de paso) y no distingue el
         derecho del ESTUDIANTE del reclamo LABORAL del docente.
      2. FALLBACK regex (determinista; airgapped / `V9_DISABLE_LLM=true` / el LLM
         no concluyó): tags por DOCTYPE en orden de prioridad; el primero con
         señal gana.
      3. Si todo falla: ("SIN_DETERMINAR", "default").

    Returns: (valor, fuente)  — fuente ∈ {"llm", "regex", "default"}.
    """
    # 1. LLM-first (autoridad del campo semántico)
    if use_llm and os.getenv("V9_DISABLE_LLM", "false").lower() != "true":
        claim_text, _is_real = _best_claim_text(db, case)
        if claim_text and len(claim_text) >= 150:
            val = _llm_classify_derecho(claim_text)
            # "OTRO" pelado = el LLM no identificó un derecho del vocab → inconcluso;
            # preferir el regex (no regresar un EDUCACION correcto a OTRO).
            if val and val not in (DERECHO_SIN_DETERMINAR, "OTRO"):
                return val, "llm"

    # 2. FALLBACK regex por doctype, en orden de prioridad — el primero con señal gana
    docs_by_type: dict[str, list[Document]] = {}
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        docs_by_type.setdefault(d.doc_type or "OTRO", []).append(d)

    ordered_types = _DERECHO_DOC_PRIORITY + [t for t in docs_by_type if t not in _DERECHO_DOC_PRIORITY]
    for dt in ordered_types:
        found: list[str] = []
        for d in docs_by_type.get(dt, []):
            text = d.extracted_text if d.extracted_text else _read_doc_text(d)
            if not text or len(text) < 200:
                continue
            for tag in _extract_derechos_from_text(text):
                if tag not in found:
                    found.append(tag)
        if found:
            found.sort(key=lambda t: _DERECHO_PRIORITY.get(t, 999))
            return _format_derechos(found), "regex"

    # 3. Default
    return DERECHO_SIN_DETERMINAR, "default"


# ============================================================
# JUZGADO  (campo 8 — estructural; 1ra y 2da instancia)
# ============================================================
#
# El juzgado aparece en todo doc oficial del despacho. La fuente CANÓNICA es el
# remitente/destinatario de los emails de la Rama Judicial: las cuentas de
# cendoj.ramajudicial.gov.co / notificacionesrj.gov.co se llaman, p.ej.:
#   "Juzgado 04 Civil Municipal - Santander - Girón <j04cmpalgiron@cendoj...>"
#   "Juzgado 03 Laboral Circuito - Santander - Barrancabermeja <...>"
#   "Notificaciones Secretaría Sala Civil Familia - Santander - Bucaramanga <...>"
# → de ahí salen número, especialidad, NIVEL (Municipal/Circuito) y municipio.
#
# Dos slots:
#   - juzgado     → 1ra instancia (el que lleva la tutela; en tutelas contra la
#                   SED departamental, por reparto, casi siempre es un Juez
#                   Municipal del lugar de los hechos → nivel MUNICIPAL).
#   - juzgado_2nd → 2da instancia (solo si hubo impugnación) → nivel CIRCUITO o
#                   TRIBUNAL. Si no se puede extraer explícito, se DERIVA con el
#                   mapa judicial canónico (`backend/cognition/legal_schema.py`).

# Remitente/destinatario Rama Judicial: "<nombre> - Santander - <municipio> <email@(cendoj|notificacionesrj)>"
_RE_RJ_SENDER = re.compile(
    r"(?i)\b(?P<nombre>(?:juzgado|tribunal|notificaciones)[^<>\n]{3,70}?)\s*[-–]\s*santander\s*[-–]\s*"
    r"(?P<muni>[^<>\n]{2,40}?)\s*<[^>\n]*@(?:cendoj\.ramajudicial|notificacionesrj|ramajudicial)\.gov\.co>"
)
# Fallback: "JUZGADO ..." / "TRIBUNAL ..." dentro del cuerpo de un doc (header/sello).
_RE_JUZGADO_RAW = re.compile(r"(?i)\b(juzgad[oa]\s+[^\n]{4,95})")
_RE_TRIBUNAL_RAW = re.compile(r"(?i)\b(tribunal\s+(?:superior|administrativo|contencioso)[^\n]{0,80})")
# Donde "termina" el nombre del juzgado en texto libre (a partir de aquí es basura).
_JUZGADO_STOP = re.compile(
    r"(?i)\b(?:acta\b|reparto\b|radicaci|radicad|expediente\b|accionant|accionad|"
    r"demandant|demandad|se[ñn]or\b|se[ñn]ora\b|doctor\b|doctora\b|asunto\b|ref\b|"
    r"referencia\b|oficio\b|n[uú]mero\b|n[°º]\b|nro\b|fecha\b|d[ií]a\b|me\s+permito|"
    r"buen\s+d[ií]a|cordial|atentamente|avoca\b|avoqu|admite\b|adm[ií]t|conoce\b|"
    r"profiri|profer|emiti|dentro\s+de|mediante\b|notific|para\s+reparto|"
    r"sala\s+de\s+decisi|de\s+conformidad|conforme\s+a|sobre\s+la\b|en\s+raz[óo]n|"
    r"al\s+confirmar|por\s+considerar|de\s+este\s+distrito|de\s+esta\s+ciudad|"
    r"veinti\w+|trein\w+|cuaren\w+|cincuen\w+|sesen\w+|seten\w+|"
    r"ochen\w+|noven\w+|actuando\b|quien\b|en\s+su\b|el\s+cual\b|la\s+cual\b)"
)
# Salas válidas de un Tribunal Superior (para no capturar texto de más).
_RE_SALA = re.compile(
    r"(?i)\bsala\s+(civil[\s\-]*familia[\s\-]*laboral|civil[\s\-]*familia|civil|penal|laboral|familia|[úu]nica|mixta)\b"
)
_JUZGADO_KEY_TOKENS = re.compile(
    r"(?i)\b(?:municipal|del\s+circuito|circuito|civil|penal|laboral|administrativ[oa]|"
    r"promiscu[oa]|familia|peque[ñn]as\s+causas|ejecuci[oó]n|oralidad|garant[íi]as|adolescentes|sala)\b"
)


def _juzgado_nivel(name: str) -> str:
    """'TRIBUNAL' | 'CIRCUITO' | 'MUNICIPAL' | 'OTRO' a partir del nombre."""
    t = _fold(name)
    if "tribunal" in t or re.search(r"\bsala\b", t):
        return "TRIBUNAL"
    if "circuito" in t:
        return "CIRCUITO"
    if "municipal" in t or "pequenas causas" in t:
        return "MUNICIPAL"
    return "OTRO"


def _norm_muni_titlecase(m: str) -> str:
    """'san vicente de chucurí' → 'San Vicente de Chucurí' (sin tocar tildes)."""
    small = {"de", "del", "la", "las", "los", "y"}
    parts = re.sub(r"\s+", " ", m).strip().split(" ")
    out = []
    for i, p in enumerate(parts):
        out.append(p if (i and p.lower() in small) else (p[:1].upper() + p[1:].lower()))
    return " ".join(out)


def _juzgado_from_rj_sender(line: str) -> Optional[str]:
    """Parsea una línea de remitente/destinatario de la Rama Judicial.
    'Juzgado 04 Civil Municipal - Santander - Girón <j04...@cendoj...>'
    → 'JUZGADO 04 CIVIL MUNICIPAL DE GIRÓN (SANTANDER)'.
    'Notificaciones Secretaría Sala Civil Familia - Santander - Bucaramanga <...>'
    → 'TRIBUNAL SUPERIOR DEL DISTRITO JUDICIAL DE BUCARAMANGA - SALA CIVIL FAMILIA'.
    """
    m = _RE_RJ_SENDER.search(line)
    if not m:
        return None
    nombre = re.sub(r"\s+", " ", m.group("nombre")).strip(" -–")
    muni = _norm_muni_titlecase(m.group("muni"))
    nombre_low = _fold(nombre)
    if "sala" in nombre_low and not nombre_low.startswith("juzgado"):
        # Secretaría de una Sala de Tribunal Superior
        ms = _RE_SALA.search(nombre)
        sala = re.sub(r"\s+", " ", ms.group(1)).strip().upper().replace("  ", " ") if ms else ""
        sala = re.sub(r"\s*-\s*", " ", sala)
        distrito = "BUCARAMANGA" if _fold(muni) == "bucaramanga" else ("SAN GIL" if "gil" in _fold(muni) else muni.upper())
        base = f"TRIBUNAL SUPERIOR DEL DISTRITO JUDICIAL DE {distrito}"
        return f"{base} - SALA {sala}" if sala else base
    if nombre_low.startswith("tribunal"):
        nu = nombre.upper()
        return nu if _fold(muni) in nombre_low else f"{nu} ({muni.upper()})"
    # Juzgado normal
    return f"{nombre.upper()} DE {muni.upper()} (SANTANDER)"


def _clean_juzgado(raw: str) -> Optional[str]:
    """Limpia un candidato de juzgado extraído de texto libre (header/sello).
    Devuelve MAYÚSCULAS, recortado al final del municipio Santander si aparece,
    o None si no parece válido."""
    if not raw:
        return None
    v = re.sub(r"[\s\n\r]+", " ", raw).strip()
    m = _JUZGADO_STOP.search(v)
    if m and m.start() > 8:
        v = v[:m.start()].strip()
    v = v.rstrip(" ,.;:-–—").strip()
    try:
        from backend.cognition.legal_schema import MUNICIPIOS_SANTANDER as _MUNIS
    except Exception:
        _MUNIS = set()
    v_fold_up = _fold(v).upper()
    best_end = -1
    for muni in sorted(_MUNIS, key=len, reverse=True):
        idx = v_fold_up.find(" " + muni)
        if idx >= 0:
            end = idx + 1 + len(muni)
            nxt = v_fold_up[end:end + 1]
            if nxt in ("", " ", ",", ".", ";", ":"):
                if best_end == -1 or end < best_end:
                    best_end = end
    if best_end > 0:
        kept = v[:best_end].rstrip(" ,.;")
        rest = v[best_end:].lstrip(" ,")
        if rest[:9].upper().startswith("SANTANDER"):
            kept = kept + " " + rest.split()[0].rstrip(",.;")
        v = kept
    v = re.sub(r"\s+", " ", v).strip(" ,.;:-–—").upper()
    if not (10 <= len(v) <= 90):
        return None
    if not (v.startswith("JUZGADO") or v.startswith("TRIBUNAL")):
        return None
    if not _JUZGADO_KEY_TOKENS.search(v):
        return None
    return v


def _rj_sender_candidates(db: Session, case_id: int) -> list[str]:
    """Todos los juzgados normalizados que aparecen como remitente/destinatario
    Rama Judicial (cendoj/notificacionesrj) en el case — la fuente más limpia.

    Escanea CUALQUIER doc (no solo EMAIL_JUDICIAL/EMAIL_INTERNO) + el `sender` de los
    emails: el remitente RJ suele venir embebido en un PDF de demanda/auto forwarded
    o en el header del email, no solo en los .md (gap que dejaba juzgados incompletos
    en c411/c369/c219/… — fix 2026-06-02). El ranking del caller (MUNICIPAL>CIRCUITO)
    resuelve los casos con varios remitentes (p.ej. 1ra inst. municipal vs 2da circuito)."""
    out: list[str] = []
    blobs: list[str] = []
    for d in db.query(Document).filter(Document.case_id == case_id).all():
        t = d.extracted_text if d.extracted_text else _read_doc_text(d)
        if t:
            blobs.append(t[:8000])  # cota: el remitente va en el encabezado
    for e in db.query(Email).filter(Email.case_id == case_id).all():
        if e.sender:
            blobs.append(e.sender)
    for t in blobs:
        for m in _RE_RJ_SENDER.finditer(t):
            j = _juzgado_from_rj_sender(m.group(0))
            if j and j not in out:
                out.append(j)
    return out


def _juzgado_candidates_from_text(text: str) -> list[str]:
    """Nombres de juzgado/tribunal limpios que aparecen en un texto libre."""
    if not text:
        return []
    out: list[str] = []
    for pat in (_RE_TRIBUNAL_RAW, _RE_JUZGADO_RAW):
        for m in pat.finditer(text):
            c = _clean_juzgado(m.group(1))
            if c and c not in out:
                out.append(c)
    return out


_JUZGADO_2ND_DOCTYPES = ["SENTENCIA_2DA", "AUTO_2DA", "AUTO_CONCEDE_IMPUGNACION", "IMPUGNACION"]


def extract_juzgado_for_case(db: Session, case: Case) -> Optional[str]:
    """Extrae el juzgado de 1ra instancia (el que lleva la tutela).

    Reúne candidatos de dos fuentes y ordena por (nivel, fuente, longitud):
      - remitente/destinatario Rama Judicial (cendoj/notificacionesrj) — fuente
        más limpia y canónica (`source=0`).
      - header/sello de AUTO_ADMISORIO / SENTENCIA_1RA / NOTIFICACION / OFICIO
        (`source=1..6`).
    Nivel MUNICIPAL gana sobre CIRCUITO/TRIBUNAL (la 1ra instancia de una tutela
    contra la SED departamental casi siempre es un Juez Municipal del lugar de
    los hechos).
    """
    cands: list[tuple[int, str]] = []  # (source_rank, name)  — menor source_rank = mejor fuente

    # Fuente 0: remitente Rama Judicial (limpio, formato estándar "JUZGADO NN ...")
    for j in _rj_sender_candidates(db, case.id):
        cands.append((0, j))

    # Fuentes 1..6: texto de docs oficiales del despacho (header/sello)
    src_map = {"AUTO_ADMISORIO": 1, "SENTENCIA_1RA": 2, "NOTIFICACION": 3,
               "NOTIFICACION_FALLO": 4, "OFICIO_CUMPLIMIENTO": 5, "RESPUESTA": 6}
    for dt, src in src_map.items():
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            text = d.extracted_text or ""
            if not text:
                continue
            for c in _juzgado_candidates_from_text(text[:2800]):
                cands.append((src, c))

    if not cands:
        return None

    def sort_key(item: tuple[int, str]):
        src, name = item
        rank = {"MUNICIPAL": 0, "CIRCUITO": 1, "TRIBUNAL": 2, "OTRO": 3}[_juzgado_nivel(name)]
        return (rank, src, len(name))

    cands.sort(key=sort_key)
    raw = cands[0][1]
    # 1B: normalizar a forma canónica (número → escrito, sin paréntesis depto)
    from backend.v9.catalog_resolve import normalize_juzgado
    return normalize_juzgado(raw)


def extract_juzgado_2nd_for_case(db: Session, case: Case, juzgado_1st: Optional[str]) -> tuple[Optional[str], str]:
    """Extrae (o deriva) el juzgado de 2da instancia. Solo si hubo impugnación
    (`impugnacion == 'SI'` o existe un doc de 2da instancia).

    Returns: (valor, fuente) — fuente ∈ {"regex", "derivado", "none"}.
    """
    has_2nd_doc = (
        db.query(Document)
        .filter(Document.case_id == case.id, Document.doc_type.in_(_JUZGADO_2ND_DOCTYPES))
        .first()
        is not None
    )
    impugno = (getattr(case, "impugnacion", None) or "").upper() == "SI"
    if not (has_2nd_doc or impugno):
        return None, "none"

    j1_fold = _fold(juzgado_1st) if juzgado_1st else ""

    # 1) remitente Rama Judicial de nivel CIRCUITO/TRIBUNAL, distinto al de 1ra
    rj = _rj_sender_candidates(db, case.id)
    rj_2nd = [j for j in rj if _juzgado_nivel(j) in ("CIRCUITO", "TRIBUNAL") and _fold(j) != j1_fold]
    if rj_2nd:
        rj_2nd.sort(key=lambda j: (0 if _juzgado_nivel(j) == "TRIBUNAL" else 1, len(j)))
        from backend.v9.catalog_resolve import normalize_juzgado
        return normalize_juzgado(rj_2nd[0]), "regex"

    # 2) extracción explícita en docs de 2da instancia
    cands: list[str] = []
    for dt in _JUZGADO_2ND_DOCTYPES:
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            text = d.extracted_text or ""
            if not text:
                continue
            for c in _juzgado_candidates_from_text(text[:3500]):
                if _fold(c) != j1_fold and _juzgado_nivel(c) in ("CIRCUITO", "TRIBUNAL"):
                    cands.append(c)
    if cands:
        cands.sort(key=lambda c: (0 if _juzgado_nivel(c) == "TRIBUNAL" else 1, len(c)))
        from backend.v9.catalog_resolve import normalize_juzgado
        return normalize_juzgado(cands[0]), "regex"

    # 3) derivación con el mapa judicial canónico
    if juzgado_1st:
        try:
            from backend.cognition.legal_schema import derivar_juzgado_segunda
            ciudad = getattr(case, "ciudad", None)
            der = derivar_juzgado_segunda(juzgado_1st, municipio_hechos=ciudad)
            if der and der.juzgado_2nd:
                jl = der.juzgado_2nd.lower()
                if "no determin" not in jl and "no identificad" not in jl:
                    val = der.juzgado_2nd
                    if der.sala and der.sala.lower() not in jl:
                        val = f"{val} - Sala {der.sala}"
                    return val.upper() + " (DERIVADO)", "derivado"
        except Exception as e:
            logger.warning("derivar_juzgado_segunda falló: %s", str(e)[:200])
    return None, "none"


# ============================================================
# CIUDAD  (campo 9 — municipio del juzgado de 1ra instancia = lugar de los hechos)
# ============================================================
#
# Regla (confirmada por el usuario): `ciudad` = municipio del Juzgado que conoce
# la tutela en 1ra instancia. Por competencia "a prevención" (Decreto 2591/1991),
# la tutela se tramita en el lugar donde ocurrió la presunta vulneración, así que
# el municipio del juzgado ≈ lugar de los hechos. El análisis del corpus (80
# cases con demanda+auto) confirma el patrón: coincide con "Señor Juez de X" de
# la demanda 9/9 y con "Juzgado de X" del auto admisorio 27/28.
#
# Como `juzgado` ya viene con el municipio embebido (`...DE GIRÓN (SANTANDER)`),
# `ciudad` se DERIVA de ahí. Fallbacks: header del auto / "Señor Juez de X" de la
# demanda. Para juzgados de fuera de Santander (ej. Tunja) se toma el municipio
# tal cual del nombre del juzgado (sigue siendo el lugar de los hechos).

# "Juzgado ... [Municipal|del Circuito] de <CIUDAD>" en el header del auto admisorio
_RE_AUTO_JUZ_CIUDAD = re.compile(
    r"(?is)\bjuzgad\w+\b[^\n]{0,55}?\b(?:municipal|del?\s+circuito|circuito|promiscu\w+)\b[^\n]{0,8}?\bde\b\s+"
    r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ\.\s]{2,28}?)(?=\s*[\(\),\.\n\-]|\s+santander|\s+\bquien\b)"
)
# "Señor Juez ... de <CIUDAD> (Reparto)" al inicio de la demanda
_RE_DEM_JUEZ_CIUDAD = re.compile(
    r"(?is)\bjue[zc]\w*\b(?:\s+(?:promiscu\w+|civil|penal|laboral|municipal|de\s+familia|del?\s+circuito|de\s+reparto))*\s+"
    r"(?:de\s+(?:la\s+ciudad\s+de\s+)?|del\s+municipio\s+de\s+)"
    r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ\.\s]{2,28}?)(?=\s*[\(\),\.\n\-]|\s+\bE\.?\s?S\.?\s?D\.?|\s+\bquien\b)"
)
# Extraer el municipio del propio nombre del juzgado normalizado:
#   "JUZGADO 04 CIVIL MUNICIPAL DE GIRÓN (SANTANDER)" → "GIRÓN"
#   "JUZGADO 02 PROMISCUO CIRCUITO DE SAN VICENTE DE CHUCURÍ (SANTANDER)" → "SAN VICENTE DE CHUCURÍ"
#   "JUZGADO QUINTO PENAL DEL CIRCUITO DE TUNJA"      → "TUNJA"  (fuera de Santander)
#   "JUZGADO PROMISCUO DEL CIRCUITO DE SAN GIL (DERIVADO)" → "SAN GIL"
# El "DE <Ciudad>" final (antes de "(SANTANDER)"/"(DERIVADO)"/fin) — conserva tildes.
_RE_CIUDAD_TAIL_JUZGADO = re.compile(
    r"(?i)\bde\s+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ'\.\s]{2,28}?)\s*(?:\((?:santander|derivado)\)\s*$|\(|$)"
)
# Fallback más laxo: "<nivel> de <Ciudad>" en cualquier posición.
_RE_CIUDAD_DE_JUZGADO = re.compile(
    r"(?i)\b(?:municipal|del\s+circuito|circuito|familia|conocimiento|garant[íi]as|adolescentes|mixto|sentencias)\s+de\s+"
    r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ'\.\s]{2,28}?)\s*(?:\(|$)"
)


_CIUDAD_NOISE = {
    "SANTANDER", "REPARTO", "FAMILIA", "CIRCUITO", "MUNICIPAL", "JUSTICIA",
    "ESTE DISTRITO", "ESTA CIUDAD", "CONOCIMIENTO", "GARANTIAS", "GARANTÍAS",
    "EJECUCION", "EJECUCIÓN", "DESCONGESTION", "DESCONGESTIÓN", "ADOLESCENTES",
    "PEQUEÑAS CAUSAS", "MIXTO", "ORALIDAD", "SENTENCIAS", "ADMINISTRATIVO",
    "CONTROL", "PROMISCUO", "CIVIL", "PENAL", "LABORAL", "ESTE",
    # No son ciudades: aparecen en frases como "conoce de la TUTELA / ACCIÓN de AMPARO"
    "TUTELA", "ACCION", "ACCIÓN", "AMPARO", "DEMANDA", "PROCESO", "ASUNTO", "REFERENCIA",
}


def _ciudad_clean(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    v = re.sub(r"\s+", " ", raw).strip(" ,.;:-–—()").upper()
    v = re.sub(r"\s+SANTANDER$", "", v).strip()
    if v in _CIUDAD_NOISE or re.search(r"\d", v):
        return None
    if not (3 <= len(v) <= 30):
        return None
    return v


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


# Municipio de AFECTACIÓN: la I.E./sede donde labora el docente (o el colegio del
# estudiante), NO la sede del juzgado. Para traslados se ancla a la PLAZA DE ORIGEN
# ("labora/adscrito/asignado/presta servicios en ... municipio de X"), no al destino
# solicitado. Regla confirmada por el usuario; corrige el sesgo histórico de tomar
# el municipio del juzgado (que suele ser Bucaramanga por reparto).
_RE_PLAZA_ORIGEN = re.compile(
    r"(?i)\b(?:labor[oa]|me desempe\w+|se desempe\w+|adscrit[oa]|asignad[oa]|"
    r"nombrad[oa]\s+en|presta\s+(?:sus\s+)?servicios|vinculad[oa]\s+a|plaza\s+de\s+origen|"
    r"donde\s+labora|titular\s+de\s+la\s+plaza)\b"
    # span corto: permite puntos de abreviaturas ('I.E.') y saltos de línea del PDF
    r"[\s\S]{0,140}?\bmunicipio\s+de\s+(?:la\s+)?([A-Za-zÁÉÍÓÚÑáéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ .']{2,40})"
)


def _longest_valid_municipio(cand: str, valid_keys: set) -> Optional[str]:
    """De un span capturado ('Valle de San José y solicita...'), devuelve el PREFIJO de
    palabras más largo que sea un municipio válido ('VALLE DE SAN JOSÉ'). Maneja
    municipios de varias palabras sin truncar ni sobre-capturar."""
    words = re.split(r"\s+", (cand or "").strip())
    for n in range(min(len(words), 5), 0, -1):
        pref = " ".join(words[:n])
        v = _ciudad_clean(pref)
        if v and _strip_accents(v).upper() in valid_keys:
            return v
    return None


# Contexto de DESTINO/solicitud: si "municipio de X" viene tras estas palabras, X es
# el destino pedido (traslado), NO la plaza de origen → se rechaza.
_RE_DESTINO_CTX = re.compile(
    r"(?i)\b(?:traslad\w*\s+(?:a|al|hacia)|solicit\w*\s+(?:el\s+)?traslad|reubic\w*\s+(?:a|en)|"
    r"pretend\w+|aspira\b|preferiblemente|cercan\w+\s+a|al\s+municipio\s+de|"
    r"a\s+una\s+(?:plaza|instituci))\s*$"
)


def _extract_municipio_afectacion(db: Session, case: Case) -> Optional[str]:
    """Municipio de la I.E./plaza donde se afecta el derecho (no la sede del juzgado).
    CONSERVADOR (alta precisión, baja cobertura): solo el ancla fuerte de PLAZA DE ORIGEN
    ("labora/adscrito/asignado ... municipio de X"), rechazando contextos de DESTINO
    ("traslado a ... municipio de Z"). El 80% restante cae al juzgado (provisional) y la
    afectación real la resuelve el pase semántico (LLM gap-fill) que SÍ razona origen vs
    destino. Valida contra MUNICIPIOS_SANTANDER (normaliza acentos: la lista va sin tildes)."""
    try:
        from backend.cognition.legal_schema import MUNICIPIOS_SANTANDER
        valid_keys = {_strip_accents(m).upper() for m in MUNICIPIOS_SANTANDER}
    except Exception:
        return None

    for dt in ("RESPUESTA_SED", "DOCX_RESPUESTA", "RESPUESTA", "DEMANDA_TUTELA", "ANEXO_DEMANDA"):
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            t = d.extracted_text or ""
            if len(t) < 300:
                continue
            for m in _RE_PLAZA_ORIGEN.finditer(t):
                pre = t[max(0, m.start(1) - 45):m.start(1)]
                if _RE_DESTINO_CTX.search(pre):
                    continue  # el municipio es el destino solicitado, no el origen
                v = _longest_valid_municipio(m.group(1), valid_keys)
                if v:
                    return v
    return None


# El municipio del juzgado SOLO se desacopla de la afectación en estos HUBS de reparto
# (municipios certificados con muchos juzgados, donde caen tutelas de toda la provincia).
# En juzgados de pueblo la tutela se radica localmente → el juzgado ES la afectación.
_REPARTO_HUBS = {"BUCARAMANGA", "FLORIDABLANCA", "GIRON", "BARRANCABERMEJA", "PIEDECUESTA"}


def _ciudad_del_juzgado(db: Session, case: Case) -> tuple[Optional[str], str]:
    """Municipio embebido en el nombre del juzgado / header del auto / demanda.
    Returns (valor, fuente∈{"juzgado","auto","demanda","none"})."""
    juz = getattr(case, "juzgado", None) or ""

    # 1) municipio embebido en el nombre del juzgado ya extraído (conserva tildes)
    if juz:
        m = _RE_CIUDAD_TAIL_JUZGADO.search(juz)
        if not m:
            m = _RE_CIUDAD_DE_JUZGADO.search(juz)
        if m:
            v = _ciudad_clean(m.group(1))
            if v:
                return v, "juzgado"
        # Último intento dentro del juzgado: cualquier municipio Santander embebido
        try:
            from backend.cognition.legal_schema import extraer_municipio_de_juzgado, MUNICIPIOS_SANTANDER
            mm = extraer_municipio_de_juzgado(juz)
            if mm and mm in MUNICIPIOS_SANTANDER:
                return mm.upper(), "juzgado"
        except Exception:
            pass

    # 2) "Juzgado ... de <ciudad>" en el header del auto admisorio
    for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == "AUTO_ADMISORIO").all():
        t = d.extracted_text or ""
        if not t:
            continue
        m = _RE_AUTO_JUZ_CIUDAD.search(t[:1800])
        if m:
            v = _ciudad_clean(m.group(1))
            if v:
                return v, "auto"

    # 3) "Señor Juez de <ciudad>" en el encabezado de la demanda
    for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == "DEMANDA_TUTELA").all():
        t = d.extracted_text or ""
        if not t or len(t) < 400:
            continue
        m = _RE_DEM_JUEZ_CIUDAD.search(t[:2200])
        if m:
            v = _ciudad_clean(m.group(1))
            if v:
                return v, "demanda"

    return None, "none"


def extract_ciudad_for_case(db: Session, case: Case) -> tuple[Optional[str], str]:
    """`ciudad` = municipio de AFECTACIÓN (la I.E./plaza del docente o el colegio del
    estudiante). El municipio del juzgado se usa como valor, SALVO cuando el juzgado es un
    HUB de reparto (Bucaramanga/Floridablanca/Girón/Barrancabermeja/Piedecuesta) — ahí se
    desacopla de la afectación y prima la lectura de la PLAZA DE ORIGEN en la demanda/
    respuesta (regla del usuario). Valor PROVISIONAL/auditable (fuente registrada); la
    afectación fina en casos ambiguos (origen vs destino) la resuelve el operador o el
    pase semántico. Returns (valor, fuente∈{"afectacion","juzgado","auto","demanda","none"})."""
    juz_muni, juz_src = _ciudad_del_juzgado(db, case)
    # El juzgado solo NO sirve como afectación en los hubs de reparto (o si no se obtuvo).
    if juz_muni is None or _strip_accents(juz_muni).upper() in _REPARTO_HUBS:
        muni = _extract_municipio_afectacion(db, case)
        if muni:
            return muni, "afectacion"
    if juz_muni:
        return juz_muni, juz_src
    return None, "none"


# ============================================================
# FECHA_INGRESO  (campo 10 — fecha del AUTO ADMISORIO)
# ============================================================
#
# Regla (confirmada por el usuario): `fecha_ingreso` = fecha del auto que admite/
# avoca la tutela. (Nota procesal aparte: la entidad se entiende notificada al día
# SIGUIENTE de la llegada del correo del juzgado, y el término empieza a correr
# desde ahí — eso no es `fecha_ingreso`, sería un campo derivado futuro.)
#
# La fecha del auto está en el "dateline": "Bucaramanga, 27 de marzo de 2026" /
# "a los quince (15) días del mes de marzo de dos mil veintiséis" / "13/04/2026",
# usualmente arriba del todo o junto a la firma ("NOTIFÍQUESE Y CÚMPLASE").
# Fallback: la fecha del primer email del juzgado (≈ fecha del auto, 0-2 días después).

_FECHA_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
# Día en palabra (1-31). Suficiente para los datelines colombianos.
_FECHA_DIA_PALABRA = {
    "primero": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintidos": 22, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26, "veintisiete": 27,
    "veintiocho": 28, "veintinueve": 29, "treinta": 30, "treinta y uno": 31, "treintaiuno": 31,
}
# Año en palabra: "dos mil veintiséis" → 2026 (rango realista 2020-2030).
_FECHA_ANIO_PALABRA = {
    "veinte": 2020, "veintiuno": 2021, "veintidos": 2022, "veintitres": 2023,
    "veinticuatro": 2024, "veinticinco": 2025, "veintiseis": 2026, "veintisiete": 2027,
    "veintiocho": 2028, "veintinueve": 2029, "treinta": 2030,
}
_FECHA_YEAR_MIN, _FECHA_YEAR_MAX = 2023, 2028

# Fecha escrita: "(a los) <DD|palabra> (días del mes) de <mes> de <YYYY|dos mil X>"
_RE_FECHA_ESCRITA = re.compile(
    r"(?i)(?:a\s+los?\s+)?"
    r"(?:(\d{1,2})|([a-záéíóúñ]+(?:\s+y\s+[a-záéíóúñ]+)?))\s*"          # día (núm o palabra)
    r"(?:\(\s*(\d{1,2})\s*\)\s*)?"                                       # (NN) override
    r"(?:d[ií]as?\s+(?:del?\s+mes\s+)?)?"
    r"de\s+(" + "|".join(_FECHA_MESES) + r")\s+"                          # mes
    r"(?:de\s+)?(?:(20\d{2}|2\.0\d{2})|dos\s+mil\s+([a-záéíóúñ]+))"      # año (núm o "dos mil X")
)
_RE_FECHA_NUM = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](20\d{2})\b")


def _fecha_to_ddmmyyyy(d: int, m: int, y: int) -> Optional[str]:
    if not (1 <= d <= 31 and 1 <= m <= 12 and _FECHA_YEAR_MIN <= y <= _FECHA_YEAR_MAX):
        return None
    return f"{d:02d}/{m:02d}/{y}"


def _parse_es_dates(text: str) -> list[tuple[int, str]]:
    """Devuelve [(posición, 'DD/MM/AAAA')] de todas las fechas válidas (año en rango)."""
    out: list[tuple[int, str]] = []
    if not text:
        return out
    folded = _fold(text)  # sin tildes/minúsculas para matchear meses/palabras
    for m in _RE_FECHA_ESCRITA.finditer(folded):
        d_num, d_word, d_paren, mes_w, y_num, y_word = m.groups()
        if d_paren:
            day = int(d_paren)
        elif d_num:
            day = int(d_num)
        elif d_word:
            day = _FECHA_DIA_PALABRA.get(d_word.strip())
            if day is None:
                continue
        else:
            continue
        mes = _FECHA_MESES.get(mes_w)
        if not mes:
            continue
        if y_num:
            year = int(y_num.replace(".", ""))
        elif y_word:
            year = _FECHA_ANIO_PALABRA.get(y_word.strip())
            if year is None:
                continue
        else:
            continue
        v = _fecha_to_ddmmyyyy(day, mes, year)
        if v:
            out.append((m.start(), v))
    for m in _RE_FECHA_NUM.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        v = _fecha_to_ddmmyyyy(d, mo, y)
        if v:
            out.append((m.start(), v))
    out.sort(key=lambda x: x[0])
    return out


def _rad_year(case: Case) -> Optional[int]:
    """Año del radicado de 23 dígitos (chars 12-15) — usado como cota de cordura
    para las fechas (el auto/admisión cae el mismo año o ±1 del radicado)."""
    rad = getattr(case, "radicado_23_digitos", None) or ""
    rad = re.sub(r"\D", "", rad)
    if len(rad) >= 16:
        try:
            y = int(rad[12:16])
            if 2018 <= y <= 2030:
                return y
        except ValueError:
            pass
    return None


def _first_date_near_year(dates: list[tuple[int, str]], year_hint: Optional[int], tol: int = 1) -> Optional[str]:
    """De [(pos,'DD/MM/AAAA')] devuelve la primera cuyo año esté dentro de ±tol del
    `year_hint` (si hay hint); si no hay hint, la primera."""
    for _pos, v in dates:
        if year_hint is None:
            return v
        try:
            if abs(int(v[-4:]) - year_hint) <= tol:
                return v
        except ValueError:
            continue
    return None


def _fecha_auto_from_text(text: str, year_hint: Optional[int] = None) -> Optional[str]:
    """Fecha del auto, leída del propio auto: "auto de fecha X" explícito, luego el
    dateline de arriba, luego la zona de la firma. Filtra por `year_hint` (±1)."""
    if not text:
        return None
    m = re.search(r"(?i)(?:auto|providencia)\s+(?:de|del?)\s+fecha[:\s]+([^\n]{4,42})", text[:3000])
    if m:
        v = _first_date_near_year(_parse_es_dates(m.group(1)), year_hint)
        if v:
            return v
    head = text[:800]
    tail = text[-2000:] if len(text) > 2000 else ""
    for zone in (head, tail):
        v = _first_date_near_year(_parse_es_dates(zone), year_hint)
        if v:
            return v
    return None


# En sentencias / notificaciones / respuestas suele recapitularse la admisión del
# auto: "mediante auto del DD de MMMM de AAAA se admitió la tutela", "auto
# admisorio de fecha X", "admitida mediante providencia del X", "el X se avocó
# conocimiento", "la tutela fue radicada el X y admitida el Y", etc.
_RE_AUTO_ADMIS_RECAP = re.compile(
    r"(?i)(?:"
    r"auto\s+(?:admisori\w+|que\s+admit\w+|de\s+admisi[óo]n)"
    r"|(?:mediante|por|en|con|a\s+trav[ée]s\s+de(?:l)?|seg[úu]n)\s+(?:auto|providencia|prove[íi]do)\b[^.\n]{0,55}?\b(?:admit\w+|avoc\w+|admisori\w+|admisi[óo]n)"
    r"|(?:se\s+)?(?:admit\w+|avoc\w+(?:\s+(?:el\s+)?conocimiento)?|inadmit\w+)\b[^.\n]{0,55}?\b(?:auto|providencia|prove[íi]do)\b"
    r"|(?:fue\s+)?(?:admit\w+|radicad\w+)\s+(?:la\s+(?:presente\s+)?(?:acci[óo]n\s+de\s+)?tutela\s+)?(?:el\s+(?:d[ií]a\s+)?)?"
    r")[^.\n]{0,55}"
)


def _fecha_auto_recap_from_text(text: str, year_hint: Optional[int] = None) -> Optional[str]:
    """Busca la fecha del auto admisorio recapitulada en OTRO doc (sentencia, etc.).
    Filtra por `year_hint` (±1) para descartar fechas de jurisprudencia / otros radicados."""
    if not text:
        return None
    for m in _RE_AUTO_ADMIS_RECAP.finditer(text[:14000]):
        s, e = max(0, m.start() - 25), min(len(text), m.end() + 60)
        v = _first_date_near_year(_parse_es_dates(text[s:e]), year_hint)
        if v:
            return v
    return None


# Subject de email que indica que lleva/notifica el auto admisorio (≈ fecha del auto)
_RE_SUBJECT_AUTO_ADMIS = re.compile(
    r"(?i)\bauto\b(?![^|]*concede\s*impugna)[^|]*?\b(?:admit\w*|admisori\w*|avoc\w*|traslad\w*)\b"
    r"|notificac\w*\s+(?:de\s+)?auto\b|\badmisi[óo]n\b|\badmiti[óo]\b|\bavoc[óa]\b|\bavoca\b"
)


def extract_fecha_ingreso_for_case(db: Session, case: Case) -> tuple[Optional[str], str]:
    """`fecha_ingreso` = fecha del auto que admite/avoca la tutela.

    Returns: (valor 'DD/MM/AAAA', fuente) — fuente ∈ {"auto", "recap", "email", "none"}.
    """
    yh = _rad_year(case)

    # 1) fecha en el texto del propio auto admisorio
    for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == "AUTO_ADMISORIO").all():
        t = d.extracted_text or ""
        if not t or len(t) < 120:
            continue
        v = _fecha_auto_from_text(t, yh)
        if v:
            return v, "auto"

    # 2) recap del auto admisorio en otros docs (sentencia recapitula "mediante auto del ...")
    #    Cota: la admisión SIEMPRE precede al fallo. Un recap posterior al fallo más
    #    temprano conocido (1ra o 2da) NO es la fecha de admisión — suele ser una fecha
    #    de incidente/requerimiento citada en docs de incidente. Sin esta cota, casos de
    #    folder incidente-only quedaban con fecha_ingreso posterior (o futura) al fallo.
    _fallos = [f for f in (_parse_ddmmyyyy(getattr(case, "fecha_fallo_1st", None)),
                           _parse_ddmmyyyy(getattr(case, "fecha_fallo_2nd", None))) if f]
    _earliest_fallo = min(_fallos) if _fallos else None
    for dt in ("SENTENCIA_1RA", "SENTENCIA_2DA", "NOTIFICACION", "NOTIFICACION_FALLO",
               "RESPUESTA", "OFICIO_CUMPLIMIENTO", "INCIDENTE_DESACATO"):
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            t = d.extracted_text or ""
            if not t:
                continue
            v = _fecha_auto_recap_from_text(t, yh)
            if v:
                vd = _parse_ddmmyyyy(v)
                if _earliest_fallo and vd and vd > _earliest_fallo:
                    continue  # posterior al fallo → no es la admisión
                return v, "recap"

    # 3) fecha del primer email cuyo subject indica que lleva/notifica el auto admisorio.
    #    OJO: la fecha de RECEPCIÓN del correo ≠ fecha del auto (el correo puede llegar
    #    semanas después, o ser una notificación tardía). Solo se usa si es coherente:
    #    no puede ser POSTERIOR al fallo de 1ra (no se admite una tutela ya fallada).
    fallo1 = _parse_ddmmyyyy(getattr(case, "fecha_fallo_1st", None))
    for e in _emails_chronological(db, case.id):
        subj = e.subject or ""
        if subj and _RE_SUBJECT_AUTO_ADMIS.search(subj) and e.date_received:
            if yh is not None and abs(e.date_received.year - yh) > 1:
                continue
            if fallo1 is not None and e.date_received.date() > fallo1:
                continue  # fecha del correo posterior al fallo → no es la fecha de ingreso
            try:
                return e.date_received.strftime("%d/%m/%Y"), "email"
            except Exception:
                pass

    return None, "none"


# ============================================================
# ASUNTO  (campo 11 — qué pide la tutela, mapeado a vocabulario controlado)
# ============================================================
#
# Regla (confirmada por el usuario): `asunto` = etiqueta del vocabulario controlado
# (el verbo del reclamo se normaliza al sustantivo: "trasladar" → TRASLADO). Se usa
# el taxonomía SED ya existente `legal_schema.SED_TEMA_MAPPING` /
# `clasificar_sed_tematica()`. Keyword matching primero; LLM (Qwen3-4B local)
# como fallback para los que no matchean; default `SIN_DETERMINAR`.

def _asunto_vocab() -> list[str]:
    try:
        from backend.cognition.legal_schema import SED_TEMA_MAPPING
        out: list[str] = []
        for _kws, _l1, _l2, _l3, cat in SED_TEMA_MAPPING:
            if cat and cat not in out:
                out.append(cat)
        return out
    except Exception:
        return []


# Doctypes que enuncian el RECLAMO DEL ACCIONANTE (o el juez recapitulándolo). NO
# incluye la RESPUESTA/contestación de la SED ni oficios de cumplimiento: ahí la SED
# cita normativa ("reubicación", "traslado del titular") que contamina el asunto con
# un tema que no es el del caso. Se usan en el PASE 1 (autoritativo).
_ASUNTO_PRIMARY_DOCTYPES = [
    "DEMANDA_TUTELA", "ANEXO_DEMANDA", "AUTO_ADMISORIO", "SENTENCIA_1RA",
    "SENTENCIA_2DA", "AUTO_2DA", "AUTO_CONCEDE_IMPUGNACION", "IMPUGNACION",
]
# Doctypes que solo se miran en el PASE 2 (fallback) — pueden traer la defensa SED.
_ASUNTO_SECONDARY_DOCTYPES = [
    "INCIDENTE_DESACATO", "NOTIFICACION", "NOTIFICACION_FALLO",
    "OFICIO_CUMPLIMIENTO", "RESPUESTA", "DESCONOCIDO",
]


def _asunto_case_text(db: Session, case: Case, limit_per_doc: int = 6000, *, primary_only: bool = False) -> str:
    """Texto del case para clasificar el asunto: asuntos de emails + docs con texto.

    `primary_only=True` (PASE 1): solo el reclamo del accionante (demanda/auto/sentencia),
    SIN la RESPUESTA de la SED — evita que la normativa citada en la defensa
    ('reubicación', 'traslado del titular') gane sobre el reclamo real. Si el PASE 1 no
    clasifica, el caller reintenta con `primary_only=False` (todos los docs, como antes —
    recupera cases que solo conservan docs de 2da/respuesta)."""
    doctypes = _ASUNTO_PRIMARY_DOCTYPES if primary_only else (_ASUNTO_PRIMARY_DOCTYPES + _ASUNTO_SECONDARY_DOCTYPES)
    parts: list[str] = []
    for e in db.query(Email).filter(Email.case_id == case.id).all():
        if e.subject:
            parts.append(e.subject)
    for d in db.query(Document).filter(
        Document.case_id == case.id,
        Document.doc_type.in_(doctypes),
    ).all():
        if d.extracted_text:
            parts.append(d.extracted_text[:limit_per_doc])
    # cabecera de los .md de los emails (subject + headers + arranque del cuerpo) — los
    # subjects "SOLICITUD DE DESIGNACIÓN DE DOCENTE", "RESPUESTA AUTO DE TRASLADO" etc.
    # caen directo en `clasificar_sed_tematica`; el cuerpo a veces tiene más ("en
    # cumplimiento al fallo de tutela radicado ... [tema]").
    for d in db.query(Document).filter(
        Document.case_id == case.id, Document.doc_type.in_(["EMAIL_JUDICIAL", "EMAIL_INTERNO"])
    ).all():
        t = _read_doc_text(d)
        if t:
            parts.append(t[:2500])
    return "\n".join(parts)


def _llm_classify_asunto(text: str, vocab: list[str]) -> Optional[str]:
    if os.getenv("V9_DISABLE_LLM", "false").lower() == "true":
        return None
    text = (text or "").strip()
    if len(text) < 150 or not vocab:
        return None
    try:
        from backend.extraction.ai_extractor import _call_local
    except ImportError:
        return None
    prompt = (
        "/no_think\n"
        "Eres un clasificador de tutelas de la Secretaría de Educación. Lee el texto y di "
        "el ASUNTO (de qué trata el reclamo).\n"
        f"Responde ÚNICAMENTE con UNO de estos tags: {', '.join(vocab)}.\n"
        "Si ninguno aplica, responde exactamente 'OTRO'. No expliques nada más.\n\n"
        f"Texto:\n{text[:3500]}"
    )
    try:
        raw, _, _ = _call_local(
            [{"role": "system", "content": "Clasificas asuntos de tutelas. Respondes solo con el tag pedido."},
             {"role": "user", "content": prompt}],
            "qwen3-4b-iuris", max_tokens=24,
        )
    except Exception as e:
        logger.warning("LLM asunto falló: %s", str(e)[:200])
        return None
    if not raw:
        return None
    raw_up = re.sub(r"[^A-Z_ ]", " ", _fold(raw).upper())
    for tag in vocab + ["OTRO"]:
        tag_pat = re.escape(tag).replace(r"\_", r"[ _]")
        if re.search(rf"\b{tag_pat}\b", raw_up):
            return tag
    return None


ASUNTO_SIN_DETERMINAR = "SIN_DETERMINAR"


# Categorías de asunto LABORAL-DOCENTE: el accionante es el DOCENTE y el derecho
# en juego es TRABAJO/SALUD/SEGURIDAD_SOCIAL — no la educación de un menor.
_ASUNTO_DOCENTE_LABORAL = {
    "NOMBRAMIENTO", "TRASLADO", "SALUD_DOCENTE", "PENSION", "SALARIO", "CESANTIAS",
    "REINTEGRO", "TESORERIA", "CNSC_CONCURSO", "HISTORIA_LABORAL", "ACOSO_LABORAL", "FSE",
}
# Categorías genéricas/débiles que conviene refinar con el LLM.
_ASUNTO_GENERICAS = {"EDUCACION", "TUTELA_GENERICA", "INCIDENTE_DESACATO"}
# Señales de que el verdadero afectado es un ESTUDIANTE/MENOR (no el docente) —
# el caso típico mal clasificado (estudiante etiquetado como asunto de docente).
_ASUNTO_MENOR_MARK = re.compile(
    r"\b(mi\s+hij[oa]|menor\s+de\s+edad|ni[ñn][oa]\b|estudiante|alumn[oa]|"
    r"NNA\b|discapacidad|autism|\bTEA\b|inclusi[óo]n\s+educativ|matr[íi]cul|"
    r"cupo\s+escolar|sustituci[óo]n\s+de\s+docente|tutor\s+sombra)\b", re.I)


def _asunto_needs_llm(regex_cat: Optional[str], claim_text: str) -> bool:
    """Arbitraje: ¿consultar al LLM en vez de quedarse con el regex? Sí cuando
    (a) el regex no clasificó, (b) la categoría es genérica/débil, o (c) el regex
    dice 'docente-laboral' pero el texto habla de un menor/estudiante — la
    confusión estudiante↔docente que el keyword matcher no distingue."""
    if not regex_cat:
        return True
    if regex_cat in _ASUNTO_GENERICAS:
        return True
    if regex_cat in _ASUNTO_DOCENTE_LABORAL and claim_text and _ASUNTO_MENOR_MARK.search(claim_text):
        return True
    return False


def extract_asunto_for_case(db: Session, case: Case, *, use_llm: bool = True) -> tuple[Optional[str], str]:
    """`asunto` = etiqueta del vocabulario controlado SED. Campo SEMÁNTICO con
    arbitraje LLM. Returns (valor, fuente) con fuente ∈ {"regex","llm","default"}.

    regex-first (rápido y suele acertar el docente real) PERO consulta al LLM
    cuando el regex es dudoso: vacío, genérico, o 'docente-laboral' sobre un texto
    que habla de un menor/estudiante. Ver `_asunto_needs_llm`. El LLM lee la
    demanda real vía `_best_claim_text` (no los subjects de email ni los autos de
    desacato). Con `V9_DISABLE_LLM` o `use_llm=False` → solo regex."""
    vocab = _asunto_vocab()
    regex_cat: Optional[str] = None
    try:
        from backend.cognition.legal_schema import clasificar_sed_tematica
        # PASE 1: solo el reclamo del accionante (sin la defensa SED).
        _l1, _l2, _l3, cat = clasificar_sed_tematica(_asunto_case_text(db, case, primary_only=True))
        if not cat:
            # PASE 2 (fallback): todos los docs — recupera cases sin demanda archivada.
            _l1, _l2, _l3, cat = clasificar_sed_tematica(_asunto_case_text(db, case))
        regex_cat = cat or None
    except Exception:
        pass

    # Arbitraje LLM: solo cuando el regex es dudoso (no gasta LLM si el regex es firme).
    if use_llm and os.getenv("V9_DISABLE_LLM", "false").lower() != "true":
        claim_text, _is_real = _best_claim_text(db, case)
        if _asunto_needs_llm(regex_cat, claim_text) and claim_text and len(claim_text) >= 150:
            v = _llm_classify_asunto(claim_text, vocab)
            if v and v != "OTRO":
                return v, "llm"

    if regex_cat:
        return regex_cat, "regex"
    return ASUNTO_SIN_DETERMINAR, "default"


# ============================================================
# PRETENSIONES  (campo 12 — transcripción literal de lo solicitado en la demanda)
# ============================================================
#
# Regla (confirmada por el usuario): `pretensiones` se TRANSCRIBE (literal) del
# escrito de tutela (sección PRETENSIONES / PETICIÓN / SOLICITO). Regex de sección
# primero; LLM como fallback (instruido a copiar textual, no parafrasear).

# Encabezado de la sección de pretensiones (línea propia, opc. con numeral romano/árabe)
_RE_PRET_HEADER = re.compile(
    r"(?im)^[\s\W]*(?:(?:[IVXLC]+|\d{1,2})\s*[\.\)\-–]?\s*)?"
    r"(?:PRETENSIONES?|PETICI[ÓO]NES?|S[ÚU]PLICAS?|SOLICITUDES?|SOLICITO\b|"
    r"HECHOS\s+Y\s+PRETENSIONES|PRETENSIONES?\s+Y\s+HECHOS|OBJETO\s+DE\s+LA\s+(?:ACCI[ÓO]N|TUTELA|SOLICITUD)|"
    r"SOLICITUD\s+DE\s+AMPARO|PARTE\s+RESOLUTIVA\s+SOLICITAD\w+|EN\s+CONSECUENCIA(?:\s+SOLICITO)?|"
    r"RUEGO\s+A\s+SU\s+(?:SE[ÑN]OR[ÍI]A|DESPACHO))"
    r"\s*[:\.\-–]?\s*$"
)
# Arranque de las pretensiones dentro de una frase: "...respetuosamente solicito:",
# "ruego a su despacho:", "con fundamento en los hechos solicito que:",
# "por lo anterior/expuesto, solicito:", "en consecuencia solicito:",
# "los hechos y pretensiones que fundamentan la solicitud de amparo son:".
_RE_PRET_INLINE = re.compile(
    r"(?im)"
    r"(?:(?:respetuosa|comedida|atenta|formal|com|cordial)mente\s+|de\s+manera\s+respetuosa\s+)?"
    r"(?:solicito|ruego|pido|peticiono|impetro|deprecat?o?|reclamo)\w*\b[^\n]{0,45}?"
    r"(?:a\s+su\s+(?:señor[íi]a|despacho(?:\s+judicial)?)\s*)?[:\-–]\s*$"
    r"|(?:con\s+fundamento\s+en\s+(?:l[oa]s\s+)?(?:hechos|argumentos|fundamentos|consideraciones)"
    r"|por\s+(?:lo|todo\s+lo)\s+(?:anterior|antes\s+expuesto|expuesto)"
    r"|en\s+(?:m[ée]rito\s+de\s+lo\s+expuesto|consecuencia)|en\s+raz[óo]n\s+de\s+lo\s+anterior)"
    r"\b[^\n]{0,70}?(?:solicito|pido|ruego|peticiono|pretensiones)\b[^\n]{0,25}?[:\-–]?\s*$"
    r"|^[\s\W]*ruego\s+a\s+su\s+(?:señor[íi]a|despacho)\s*[:\-–]?\s*$"
    r"|(?:los?\s+)?hechos\s+y\s+pretensiones\s+que\s+(?:fundamentan|sustentan|motivan)\b[^\n]{0,50}?(?:\bson\b|[:\-–])\s*$"
)
# Recap en auto/sentencia: "...promovida por X solicitando que se ordene/tutele/ampare ..."
# El verbo dispositivo va en LOOKAHEAD: así `m.end()` queda ANTES del verbo y la sección
# transcrita lo INCLUYE ("ordene a los accionados…"), en vez de truncarlo a "a los
# accionados…" (bug de truncamiento, c488/c397).
_RE_PRET_RECAP = re.compile(
    r"(?i)(?:solicit(?:a|ando|o)|pretend(?:e|iendo)|pidiendo|deprecando|aspira(?:ndo)?\s+a|persigue)\s+"
    r"(?:que\s+)?(?:se\s+)?(?:le\s+)?"
    r"(?=(?:ordene|tutele|ampare|disponga|protej|garantic|reconozc|reintegr|nombr|traslad|provea))"
)
# Encabezado de la siguiente sección (corta la transcripción aquí)
_RE_PRET_END = re.compile(
    r"(?im)^[\s\W]*(?:(?:[IVXLC]+|\d{1,2})\s*[\.\)\-–]?\s*)?"
    r"(?:PRUEBAS?|MEDIOS?\s+DE\s+PRUEBA|ANEXOS?|NOTIFICACIONES?|JURAMENTO|COMPETENCIA|JURISPRUDENCIA|"
    r"FUNDAMENTOS?\s+(?:DE\s+|JUR[ÍI]DICOS?|CONSTITUCIONALES?|F[ÁA]CTICOS?)|FUNDAMENTOS\b|"
    r"DERECHOS?\s+(?:FUNDAMENTAL\w+|VULNERAD\w+|CONSTITUCIONAL\w+|TRANSGREDID\w+)|VULNERACI[ÓO]N|"
    r"MEDIDAS?\s+(?:PROVISIONAL\w+|CAUTELAR\w+)|HECHOS?|ANTECEDENTES|RAZONES?\s+(?:DE\s+DERECHO|F[ÁA]CTICAS?)|"
    r"CONSIDERACIONES?|CONSIDERANDO|FIRMA|CORDIALMENTE|ATENTAMENTE|MARCO\s+(?:NORMATIVO|CONSTITUCIONAL|LEGAL)|"
    r"ACTUACI[ÓO]N\s+PROCESAL|TR[ÁA]MITE\s+(?:PROCESAL|IMPARTIDO)|INTERVENCI[ÓO]N\s+DE\s+LOS?\s+VINCULAD|"
    r"DIRECCI[ÓO]N\s+(?:DE\s+)?NOTIFICACI[ÓO]N|PROCEDENCIA\s+DE\s+LA\s+ACCI[ÓO]N|LEGITIMACI[ÓO]N)\b"
)
# Frases de la DEFENSA del accionado: si aparecen, lo que sigue son SUS pretensiones de
# rechazo, no las del accionante → cortar el texto ahí antes de buscar (legacy v9.4.3).
_RE_PRET_DEFENSE = re.compile(
    r"(?i)\b(?:improcedencia\s+de\s+las\s+pretensiones|se\s+(?:rechac|nieg|deniegu)\w*\s+las\s+pretensiones"
    r"|sea\s+desestimad[ao]\s+la\s+acci[óo]n|niegue\s+(?:el\s+amparo|la\s+tutela)|"
    r"contestaci[óo]n\s+a\s+la\s+(?:acci[óo]n\s+de\s+)?tutela|oposici[óo]n\s+a\s+la\s+tutela|"
    r"en\s+respuesta\s+a\s+la\s+acci[óo]n\s+de\s+tutela)\b"
)
# Header "PRETENSIONES" seguido EN LA MISMA LÍNEA por el arranque del petitorio. El
# escrito de tutela suele venir con el PDF aplanado ("PRETENSIONES Solicito
# respetuosamente al despacho: 1. Tutelar...") → sin salto de línea tras el título, ni
# `_RE_PRET_HEADER` (exige fin de línea) ni `_RE_PRET_INLINE` (exige ':' + fin de línea)
# matcheaban. Se exige un verbo de petición FINITO o "se tutele/ordene..." en lookahead
# (no participios como "pretensiones solicitadas") para no disparar en prosa.
_RE_PRET_HEADER_INLINE = re.compile(
    r"(?i)\bPRETENSIONES?\b[\s.\-–:]*"
    # El petitorio debe seguir INMEDIATAMENTE al título (sin tolerancia de lead-in: ésta
    # causaba que un 'PRETENSIONES … de la acción de tutela, en los siguientes términos:'
    # capturara el framing en vez del petitorio, y desplazaba al RECAP que sí daba 'ordene…').
    r"(?=(?:(?:respetuosa|atenta|comedida|formal|cordial|com)mente\s+)?"
    r"(?:solicit(?:o|a|amos|an)\b|rueg(?:o|amos)\b|pid(?:o|imos)\b|peticion(?:o|amos)\b|"
    r"impetr(?:o|amos)\b|deprec(?:o|amos)\b|"
    r"se\s+(?:tutele|ordene|ampare|disponga|proteja|garantice|reconozca|reintegre|nombre)|"
    # Listado por ordinal ("PRIMERA. Amparar…", "1. Tutelar…") o por verbo infinitivo
    # directo (escritos que omiten "solicito": "V.PRETENSIONES PRIMERA. Amparar…", c502).
    r"(?:primer[oa]|segund[oa]|tercer[oa]|cuart[oa]|quint[oa])\b|"
    r"\d{1,2}\s*[.\)\-]\s|"
    r"(?:amparar|tutelar|ordenar|proteger|garantizar|reconocer|reintegrar|nombrar|"
    r"declarar|disponer|conceder|reanudar|reubicar|trasladar|asignar|entregar|"
    r"certificar|liquidar|reliquidar|cancelar|pagar|suspender|revocar|dejar\s+sin)\b))"
)
# La SED, en su contestación, también escribe "PRETENSIONES"/"SOLICITO" pero para PEDIR
# que se NIEGUE la tutela. Eso NO son las pretensiones del accionante → se descarta la
# sección entera (regla del usuario: pretensiones = transcripción del escrito de tutela).
_RE_PRET_DEFENSE_SECTION = re.compile(
    r"(?i)(?:declar\w*\s+(?:la\s+)?improceden|improceden\w*\s+de\s+las\s+pretensiones|"
    r"(?:se\s+)?(?:niegue|nieguen|deniegue|denieguen|niega|deniega|negar|denegar|"
    r"desestime|desestimen|desestimar|rechace|rechacen|rechazar)\b"
    r"[^.]{0,45}(?:tutela|pretensiones|amparo|acci[óo]n)|"
    r"tener\s+por\s+contestad|"
    r"pronunciamiento\s+de\s+fondo\s+y\s+excepciones|"
    r"(?:al\s+)?considera\w*\s+que\s+no\s+(?:ha|han|se\s+ha)\s+vulnerad|"
    r"no\s+(?:ha|han|se\s+ha)\s+vulnerad\w*\s+(?:los?\s+)?derecho|"
    r"exoner\w+\s+a\s+(?:la\s+)?(?:secretar|gobernaci|entidad|naci[óo]n))"
)
# NO es petitorio sino NARRATIVA DE HECHOS / ENCABEZADO / texto de la entidad: la sección
# arranca describiendo lo que el accionante "alega/adujo" (hechos), presentando a las
# partes, o con un título de sección. Se descarta (≠ "solicita/pretende QUE SE ordene…",
# que sí es recap del petitorio). Se evalúa sobre el INICIO de la sección.
_RE_PRET_NOTPETITION = re.compile(
    r"(?i)^[\s\W]*(?:"
    r"(?:el|la|los|las)\s+accionantes?\b[^.]{0,70}?\b(?:alega|adujo|aduce|manifiesta|narra|sostiene|expone|relata|refiere|argumenta|vinculad[oa])\b"
    r"|(?:los|las)\s+accionantes?,?\s+actuando\b"
    r"|en\s+apoyo\s+de\s+sus\s+pretensiones\b"
    r"|argumentos\s+f[áa]cticos\s+y\s+jur[íi]dicos"
    r"|frente\s+a\s+los\s+hechos\b"
    r"|el\s+grupo\s+de\s+talento\s+humano\b"
    r"|(?:la|el)\s+secretar[íi]a\s+de\s+educaci[óo]n\b[^.]{0,40}?\b(?:considera|manifiesta|informa)\b"
    r"|dado\s+que\s+esta\s+situaci[óo]n"
    r"|se[ñn]or\s+juez,?\s+[A-ZÁÉÍÓÚÑ]"          # arranca con el encabezado de la demanda
    r")"
)


def _extract_pretensiones_from_text(text: str, *, strip_defense: bool = False, recap_ok: bool = False) -> Optional[str]:
    """Transcribe la sección de pretensiones de un texto.

    `strip_defense`: trunca el texto en la primera frase de defensa del accionado
        (para escanear RESPUESTA / docs que pueden contener la contestación SED).
    `recap_ok`: además del encabezado/arranque, acepta el recap "solicitando que se
        ordene ..." (típico del auto admisorio / antecedentes de la sentencia).
    """
    if not text:
        return None
    if strip_defense:
        md = _RE_PRET_DEFENSE.search(text)
        if md:
            text = text[:md.start()]
            if len(text) < 200:
                return None
    m = _RE_PRET_HEADER.search(text) or _RE_PRET_HEADER_INLINE.search(text) or _RE_PRET_INLINE.search(text)
    if not m and recap_ok:
        m = _RE_PRET_RECAP.search(text)
    if not m:
        return None
    rest = text[m.end():]
    me = _RE_PRET_END.search(rest)
    section = rest[:me.start()] if me else rest[:4500]
    section = re.sub(r"\s+", " ", section).strip()
    section = section.lstrip(" ·•-–—:").strip()  # quita bullets/sep iniciales, conserva el punto final
    if len(section) < 12:
        return None
    # Guard anti-defensa: si la sección es la petición de la SED (que se niegue/declare
    # improcedente la tutela), NO son las pretensiones del accionante → descartar.
    if _RE_PRET_DEFENSE_SECTION.search(section[:400]):
        return None
    # Guard NO-petitorio: narrativa de hechos / encabezado / texto de la entidad.
    if _RE_PRET_NOTPETITION.search(section[:120]):
        return None
    # Quality-gate de truncamiento: si arranca a media frase (minúscula sin verbo
    # petitorio cerca, o fragmento 'n '/'o '/'arse'/'despacho:') → captura defectuosa,
    # descartar para que caiga a otra fuente / al LLM verbatim.
    head40 = section[:40]
    _bad_frag = re.match(r"(?i)^(?:n\s|o\s|arse\b|despacho\s*:)", section)
    _starts_lower = bool(re.match(r"^[a-záéíóúñ]", section)) and not re.search(
        r"(?i)\b(?:solicit|rueg|pid|peticion|tutel|ampar|orden|proteg|garantic|reconozc|"
        r"reintegr|nombr|declar|provee?r|asignaci|mantener|entregar|informar|reanud)\w*", head40
    )
    if _bad_frag or _starts_lower:
        return None
    return section[:4000].strip()


def _flexible_substr_pos(text: str, snippet: str) -> Optional[int]:
    """Posición (índice en `text`) de `snippet`, tolerante a mayúsculas, tildes y
    cantidad de espacios. Devuelve None si no aparece."""
    if not snippet or len(snippet) < 6:
        return None
    # tomar las primeras ~8 palabras del snippet como ancla
    words = snippet.split()[:8]
    if len(words) < 2:
        return None
    pat = r"\s+".join(re.escape(w) for w in words)
    # ignorar tildes: reemplazar vocales acentuadas por clases — más simple: usar IGNORECASE
    # y aceptar que en español la mayoría de docs no varían tildes en el cuerpo.
    m = re.search(pat, text, re.IGNORECASE)
    if m:
        return m.start()
    # reintento con menos palabras (3) por si el snippet del LLM tiene una variación tardía
    if len(words) > 3:
        pat3 = r"\s+".join(re.escape(w) for w in words[:3])
        m = re.search(pat3, text, re.IGNORECASE)
        if m:
            return m.start()
    return None


def _llm_locate_pretensiones(text: str) -> Optional[str]:
    """LLM como LOCALIZADOR (no transcriptor): le pide las primeras ~12 palabras
    EXACTAS de la primera pretensión; luego se localiza ese ancla en el texto ORIGINAL
    y se extrae la sección VERBATIM desde ahí con `_RE_PRET_END`. Así el LLM no
    parafrasea nada (la transcripción sale del texto original) y la llamada es barata
    (~30-50 tokens generados, no ~400). Respeta `V9_DISABLE_LLM=true`."""
    if os.getenv("V9_DISABLE_LLM", "false").lower() == "true":
        return None
    text = (text or "").strip()
    if len(text) < 300:
        return None
    try:
        from backend.extraction.ai_extractor import _call_local
    except ImportError:
        return None
    prompt = (
        "/no_think\n"
        "En este escrito de tutela, ubica la sección de PRETENSIONES del ACCIONANTE — lo que "
        "el demandante (o su abogado) le PIDE al juez, normalmente bajo un encabezado "
        "'PRETENSIONES'/'PETICIÓN'/'SOLICITO' o frases como 'Se tutele...', 'Se ordene a la "
        "accionada...', 'Ruego a su despacho...'. NO confundas con las órdenes del JUEZ "
        "('VINCULAR', 'REQUERIR', 'AVOCAR', 'ADMITIR', 'NOTIFICAR') ni con la contestación de "
        "la entidad accionada. Responde ÚNICAMENTE con las PRIMERAS 8 A 12 PALABRAS, COPIADAS "
        "TEXTUALMENTE (sin cambiar mayúsculas ni puntuación), de la primera pretensión del "
        "accionante. No expliques nada. Si no encuentras pretensiones del accionante, responde "
        "exactamente 'NO_HAY'.\n\n"
        f"Texto:\n{text[:7000]}"
    )
    try:
        raw, _, _ = _call_local(
            [{"role": "system", "content": "Localizas frases en texto jurídico. Respondes solo con la copia textual pedida."},
             {"role": "user", "content": prompt}],
            "qwen3-4b-iuris", max_tokens=48,
        )
    except Exception as e:
        logger.warning("LLM pretensiones (locator) falló: %s", str(e)[:200])
        return None
    if not raw:
        return None
    anchor = re.sub(r"\s+", " ", raw).strip().strip('"\'`*').strip()
    if not anchor or "no_hay" in _fold(anchor) or len(anchor) < 8:
        return None
    # Rechazar meta-comentarios del LLM (editorializa en vez de copiar): "(extraído del
    # resumen, no verbatim)", "no consta…", "no se especifica… se infiere".
    if re.search(r"(?i)extra[íi]do|no\s+verbatim|no\s+consta|no\s+se\s+especific|se\s+infiere", anchor):
        return None
    pos = _flexible_substr_pos(text, anchor)
    if pos is None:
        return None
    rest = text[pos:]
    me = _RE_PRET_END.search(rest)
    section = rest[:me.start()] if me else rest[:4500]
    section = re.sub(r"\s+", " ", section).strip().lstrip(" ·•-–—:").strip()
    if len(section) < 15:
        return None
    return section[:4000].strip()


# Orden de fuentes para pretensiones (la demanda es la fuente autoritativa; los demás
# la recapitulan). Los docs que pueden traer la DEFENSA del accionado se escanean con
# `strip_defense=True`.
_PRET_DOC_ORDER = (
    ("DEMANDA_TUTELA", False, False),
    ("ANEXO_DEMANDA", False, False),
    ("SENTENCIA_1RA", True, True),
    ("SENTENCIA_2DA", True, True),
    ("AUTO_ADMISORIO", True, True),
    ("AUTO_2DA", True, True),
    ("AUTO_CONCEDE_IMPUGNACION", True, True),
    ("IMPUGNACION", True, True),
    ("INCIDENTE_DESACATO", True, True),
    ("NOTIFICACION", True, True),
    ("NOTIFICACION_FALLO", True, True),
    ("RESPUESTA", True, False),       # la SED suele citar las pretensiones del accionante
    ("DESCONOCIDO", True, True),
    # NOTA: OFICIO_CUMPLIMIENTO se excluye a propósito — ahí "solicito:" es la
    # solicitud de la SED en su informe de cumplimiento, no las pretensiones de la tutela.
)


def extract_pretensiones_for_case(db: Session, case: Case, *, use_llm: bool = True) -> tuple[Optional[str], str]:
    """`pretensiones` = transcripción literal de lo solicitado en el escrito de tutela
    (la fuente autoritativa); si la demanda no está archivada o vino truncada, se busca
    el recap en sentencia/auto/otros docs. LLM como último recurso.

    Returns (valor, fuente) con fuente ∈ {"regex", "llm", "none"}."""
    docs_by_type: dict[str, list[Document]] = {}
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        docs_by_type.setdefault(d.doc_type or "DESCONOCIDO", []).append(d)

    longest_text = ""
    demanda_text = ""  # texto de la demanda más larga — preferido para el LLM (no tiene
                       # las órdenes del juez ni la contestación de la SED)
    for dt, strip_def, recap_ok in _PRET_DOC_ORDER:
        for d in docs_by_type.get(dt, []):
            t = d.extracted_text or ""
            if not t or len(t) < 300:
                continue
            if len(t) > len(longest_text):
                longest_text = t
            if dt in ("DEMANDA_TUTELA", "ANEXO_DEMANDA") and len(t) > len(demanda_text):
                demanda_text = t
            v = _extract_pretensiones_from_text(t, strip_defense=strip_def, recap_ok=recap_ok)
            if v:
                return v, "regex"

    # LLM como LOCALIZADOR: ubica el inicio de las pretensiones del accionante y se extrae
    # la sección VERBATIM desde ahí (el LLM no parafrasea — solo apunta). Se prefiere el
    # texto de la DEMANDA si existe (no contamina con órdenes del juez / contestación SED).
    if use_llm:
        src_text = demanda_text or longest_text
        if src_text:
            v = _llm_locate_pretensiones(src_text)
            if v:
                return v, "llm"
    return None, "none"


# ============================================================
# OFICINA_RESPONSABLE + ABOGADO_RESPONSABLE  (campo 13 — asignación interna SED)
# ============================================================
#
# Lógica (usa campos ya extraídos): `oficina_responsable` = la Dirección SED dueña
# del ASUNTO de fondo (se deriva del `asunto` ya extraído vía `legal_schema`); el
# abogado que firma la respuesta es casi siempre del Grupo de Apoyo Jurídico
# (escribe el escrito de defensa), por eso `abogado_responsable` es un dato aparte:
# sale del footer "Proyectó: NOMBRE" del DOCX de respuesta → se resuelve al catálogo
# de 17 abogados oficiales (`abogados_canonicos.json`).

from backend.v9.regex_pass import _extract_abogado_footer as _rp_abogado_footer  # noqa: E402

# Sufijos de cargo/rol/entidad que ensucian el nombre del abogado en "Proyectó:"
_RE_ABOGADO_TAIL_NOISE = re.compile(
    r"(?i)(?:"
    r"\s*[-–/|]\s*(?:jefe|coordinador\w*|abogad[oa]\b|profesional|contratista|director\w*|asesor\w*|"
    r"grupo\b|subdirector\w*|cps\b|ops\b|t\.?p\.?\b|tarjeta\s+profesional|sed\b|gobernaci[óo]n)"
    r"|\s+(?:contratista|grupo\s+de\s+apoyo|apoyo\s+jur[íi]dico|secretar[íi]a\s+de\s+educaci|"
    r"gobernaci[óo]n|jefe\b|coordinador\w*|abogad[oa]\s+(?:grupo|de)|t\.?p\.?\s*\d)"
    r").*$"
)


def _clean_abogado_name(raw: str) -> Optional[str]:
    if not raw:
        return None
    v = re.sub(r"\s+", " ", raw).strip()
    v = re.sub(r"(?i)^(?:dra?\.?\s+|doctora?\s+|abg\.?\s+|ab\.?\s+)", "", v).strip()
    v = re.sub(r"(?i)\s*(?:ext\.?|extensi[óo]n|tel\.?|t\.?p\.?)\s*\.?\s*\d.*$", "", v).strip()
    v = _RE_ABOGADO_TAIL_NOISE.sub("", v).strip(" .,;:-–/|·•").strip()
    v = re.sub(r"\s*\d.*$", "", v).strip()  # cualquier número al final → corta ahí
    if not (5 <= len(v) <= 55):
        return None
    words = v.split()
    if not (2 <= len(words) <= 6):
        return None
    if not all(w[:1].isalpha() for w in words):
        return None
    # descartar si contiene palabras que no son de un nombre de persona
    bad = {"SECRETARIA", "SECRETARÍA", "EDUCACION", "EDUCACIÓN", "GOBERNACION", "GOBERNACIÓN",
           "GRUPO", "APOYO", "JURIDICO", "JURÍDICO", "DEPENDENCIA", "DEPARTAMENTO", "JEFE",
           "COORDINADOR", "COORDINADORA", "CONTRATISTA", "ABOGADO", "ABOGADA", "PROFESIONAL",
           "TALENTO", "HUMANO", "NOMINA", "NÓMINA", "DIRECCION", "DIRECCIÓN", "OFICINA", "ASESOR",
           "ASESORA", "DESPACHO", "EXT", "EXTENSION", "EXTENSIÓN"}
    if any(w.upper() in bad for w in words):
        return None
    return v.upper()


# Roster del Grupo Jurídico de la SecEdu (nombre + correo) — aportado por el usuario
# (`GRUPO JURIDICO ABOGADOS SEC EDUCACION.xlsx` → `backend/data/grupo_juridico_abogados.json`).
import json as _json  # noqa: E402

_GRUPO_JURIDICO_CACHE: Optional[list[dict]] = None

def _grupo_juridico() -> list[dict]:
    global _GRUPO_JURIDICO_CACHE
    if _GRUPO_JURIDICO_CACHE is None:
        p = Path(__file__).resolve().parents[1] / "data" / "grupo_juridico_abogados.json"
        try:
            _GRUPO_JURIDICO_CACHE = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _GRUPO_JURIDICO_CACHE = []
    return _GRUPO_JURIDICO_CACHE


def _resolve_abogado_combined(name_or_text: str, doc_text: str = "") -> tuple[Optional[str], str]:
    """Resuelve un nombre/footer de abogado contra (1) los correos del Grupo Jurídico
    si aparece un correo en el doc, (2) el roster del Grupo Jurídico por nombre, (3) el
    catálogo `abogados_canonicos.json` (catalog_resolve). Returns (canónico|crudo, fuente)."""
    roster = _grupo_juridico()
    # 1) correo en el doc → match exacto
    if doc_text:
        for ab in roster:
            c = (ab.get("correo") or "").strip().lower()
            if c and c in doc_text.lower():
                return ab["nombre"].upper(), "roster_correo"
    cleaned = _clean_abogado_name(name_or_text)
    if not cleaned:
        return None, "none"
    # 2) roster Grupo Jurídico por nombre (exacto / substring / fuzzy)
    from difflib import SequenceMatcher
    import unicodedata as _u
    def _n(s):
        s = _u.normalize("NFD", (s or "").upper())
        s = "".join(ch for ch in s if _u.category(ch) != "Mn")
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()
    nc = _n(cleaned)
    best = (0.0, None)
    for ab in roster:
        nn = _n(ab["nombre"])
        if nc == nn:
            return ab["nombre"].upper(), "roster_nombre"
        if nc and (nc in nn or nn in nc) and abs(len(nc) - len(nn)) <= 12:
            return ab["nombre"].upper(), "roster_nombre"
        r = SequenceMatcher(None, nc, nn).ratio()
        if r > best[0]:
            best = (r, ab["nombre"])
    if best[0] >= 0.86 and best[1]:
        return best[1].upper(), "roster_fuzzy"
    # 3) catálogo abogados_canonicos.json
    try:
        from backend.v9.catalog_resolve import resolve_abogado
        canon, conf = resolve_abogado(cleaned)
        if canon and conf >= 0.85:
            return canon.upper(), "catalogo"
    except Exception:
        pass
    # 4) Regla cerrada (feedback Wilson 2026-05-18, mem feedback-abogado-responsable-fuente):
    #    si el firmante extraído NO está en el roster del Grupo Jurídico ni en
    #    abogados_canonicos.json, NO escribir nada. La respuesta puede ser un
    #    oficio insumo, proyectado externo o de otra dependencia — no es el
    #    abogado SED responsable del caso.
    return None, "no_match"


from backend.v9.regex_pass import (
    accionante_tokens as _accionante_tokens,
    doc_belongs_to_case as _doc_belongs_to_case,
    _rad_corto_from_23,
    _rad_corto_from_folder,
)  # noqa: E402


# Firmante EXTERNO (contratista CPS no-roster): se acepta SOLO si el footer trae el
# nombre INMEDIATAMENTE seguido del rol de abogado ("Proyectó: Jaime Restrepo – Abogado
# Contratista CPS"). La adyacencia nombre↔rol evita capturar prosa ("proyectó CELEBRADA
# CON EL contrato…"): un fragmento de prosa no va seguido de "Abogado/CPS".
_RE_EXT_ABOG = re.compile(
    r"(?i)\b(?:proyect[oó]|elabor[oó]|redact[oó])\s*[:.]?\s+"
    r"([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ.]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ.]+){1,3})"
    r"\s*[-–/,]\s*"
    r"(?:abogad[oa]|contratista|cps\b|profesional\s+especializ|grupo\s+(?:de\s+)?apoyo\s+jur)"
)


def extract_abogado_responsable_for_case(
    db: Session, case: Case, *, allow_external: bool = True
) -> tuple[Optional[str], str]:
    """`abogado_responsable` = el REDACTOR ('Proyectó/Elaboró NOMBRE') de la respuesta SED.

    Reglas (feedback Wilson 2026-05-18 / 06-02):
    (1) Solo cuentan docs de respuesta SED (`_is_respuesta_doc`: RESPUESTA/DOCX_RESPUESTA
        o filename con 'respuesta'/'contesta'); excluye judiciales/incidente/email.
    (2) El doc debe pertenecer al case (accionante O radicado) — anti-insumo-prestado.
    (3) El firmante resuelve al roster de 17; si NO resuelve pero el footer trae un rol
        de ABOGADO claro (Abogado/CPS/Contratista/Grupo Apoyo Jurídico) y `allow_external`,
        se conserva su nombre — es un contratista externo SED, el responsable real (antes
        se descartaba y dejaba el caso sin abogado pese a tener respuesta).
    (4) El SUPERVISOR (Aprobó/Revisó = la coordinadora) nunca cuenta (ver _rp_abogado_footer).
    Roster preferido sobre externo; dentro de cada grupo el más frecuente (empate → último).
    Returns (valor, fuente) ∈ {roster_*/catalogo, externo_cps, none}."""
    from collections import Counter
    acc_tokens = _accionante_tokens(case.accionante)
    rads = {r for r in (
        getattr(case, "radicado_23_digitos", None),
        getattr(case, "radicado_forest", None),
        _rad_corto_from_23(getattr(case, "radicado_23_digitos", None)),
        _rad_corto_from_folder(getattr(case, "folder_name", None)),
    ) if r}
    roster_c: list[tuple[str, str]] = []
    ext_c: list[str] = []
    for d in db.query(Document).filter(
        Document.case_id == case.id
    ).order_by(Document.id.asc()).all():
        if not _is_respuesta_doc(d):
            continue
        t = d.extracted_text or ""
        # ANCLA DE FOOTER: el footer ('Proyectó NOMBRE') va al FINAL y el extracted_text
        # legacy está capado a ~30k = solo cabeza → sin footer. Re-leemos la cola del
        # disco. El chequeo de pertenencia usa la CABEZA (accionante/rad); la extracción
        # del footer usa la COLA. (Espejo de cómo el sentido_fallo usa _dispositiva_zone.)
        footer = _footer_zone(d)
        belong_text = t or footer or ""
        if not belong_text:
            continue
        if (acc_tokens or rads) and not _doc_belongs_to_case(
            acc_tokens, rads, belong_text, getattr(d, "filename", "") or ""
        ):
            continue
        foot_text = footer or t
        if not foot_text:
            continue
        f = _rp_abogado_footer(foot_text)
        if not f:
            continue
        val, src = _resolve_abogado_combined(f, doc_text=foot_text)
        if val:
            roster_c.append((val, src))
        elif allow_external:
            m = _RE_EXT_ABOG.search(foot_text[-3000:])  # nombre adyacente a rol abogado
            if m:
                cleaned = _clean_abogado_name(m.group(1))
                if cleaned and len(cleaned.split()) >= 2:
                    ext_c.append(cleaned.upper())  # abogado externo CPS
    if roster_c:
        vals = [v for v, _ in roster_c]
        cnt = Counter(vals); top = cnt.most_common(1)[0][1]
        chosen = next(v for v in reversed(vals) if cnt[v] == top)
        return chosen, next(s for v, s in reversed(roster_c) if v == chosen)
    if ext_c and allow_external:
        cnt = Counter(ext_c); top = cnt.most_common(1)[0][1]
        return next(v for v in reversed(ext_c) if cnt[v] == top), "externo_cps"
    return None, "none"


# asunto (categoría) → Dirección L1 de la SED — derivado de legal_schema.SED_TEMA_MAPPING
def _asunto_to_l1_map() -> dict[str, str]:
    try:
        from backend.cognition.legal_schema import SED_TEMA_MAPPING
        return {cat: l1 for _kw, l1, _l2, _l3, cat in SED_TEMA_MAPPING if cat and l1}
    except Exception:
        return {}


_ASUNTO_TO_L1 = _asunto_to_l1_map()

# correo-de-área SED → código L1 — de `areas_encargadas.json` (hoja "Contactos por Área"
# del Excel que aportó el usuario). Si en los emails del case aparece uno de estos correos
# (en Para/Cc/De), ese es el área a la que la oficina de Apoyo Jurídico ASIGNÓ el caso —
# señal más fuerte que la derivación heurística por keyword del asunto.
_AREA_CORREO_CACHE: Optional[dict[str, str]] = None

def _area_correo_to_l1() -> dict[str, str]:
    global _AREA_CORREO_CACHE
    if _AREA_CORREO_CACHE is None:
        p = Path(__file__).resolve().parents[1] / "data" / "areas_encargadas.json"
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
            _AREA_CORREO_CACHE = {e["correo"].lower(): e["l1"] for e in data if e.get("l1") and e.get("correo")}
        except Exception:
            _AREA_CORREO_CACHE = {}
    return _AREA_CORREO_CACHE


def _oficina_from_email_assignment(db: Session, case: Case) -> Optional[str]:
    """L1 del área a la que se asignó el caso, leído de los correos-de-área que
    aparecen en los .md de los emails del case (Para/Cc/De). None si no hay señal."""
    amap = _area_correo_to_l1()
    if not amap:
        return None
    from collections import Counter
    seen: Counter = Counter()
    for d in db.query(Document).filter(
        Document.case_id == case.id, Document.doc_type.in_(["EMAIL_JUDICIAL", "EMAIL_INTERNO"])
    ).all():
        t = _read_doc_text(d)
        if not t:
            continue
        low = t.lower()
        for correo, l1 in amap.items():
            if correo in low:
                seen[l1] += 1
    if not seen:
        return None
    return seen.most_common(1)[0][0]


def extract_oficina_responsable_for_case(db: Session, case: Case) -> tuple[Optional[str], str]:
    """`oficina_responsable` = Dirección SED responsable del ASUNTO de fondo
    (la que tiene que ACTUAR). Prioridad:
      1. EMAIL DE ASIGNACIÓN: si en los emails del case aparece un correo de un área
         de la SED (hoja "Contactos por Área") → ese es el área a la que Apoyo Jurídico
         asignó el caso (señal real).
      2. derivada del `asunto` ya extraído (`legal_schema.SED_TEMA_MAPPING` → L1) —
         heurística por keyword, fallback.
    NO se usa el footer del DOCX de respuesta (siempre apunta a Apoyo Jurídico).
    Returns (valor, fuente) con fuente ∈ {"email_asignacion","asunto","none"}."""
    l1_email = _oficina_from_email_assignment(db, case)
    if l1_email:
        return l1_email, "email_asignacion"
    asunto = getattr(case, "asunto", None)
    if asunto:
        l1 = _ASUNTO_TO_L1.get(asunto)
        if l1:
            return l1, "asunto"
    return None, "none"


# ============================================================
# SENTIDO_FALLO_1ra + FECHA_FALLO_1ra  (campo 14 — fallo de 1ra instancia)
# ============================================================

SENTIDO_FALLO_VOCAB: tuple[str, ...] = (
    "CONCEDE", "CONCEDE_PARCIAL", "NIEGA", "IMPROCEDENTE", "HECHO_SUPERADO", "CARENCIA_OBJETO",
    "DESISTIMIENTO",  # desistimiento aceptado por el juez (art. 26 D2591/91): termina sin fallo de fondo
    "NULIDAD",  # 2da instancia decreta nulidad de lo actuado y devuelve a 1ra → reabre el proceso
)

# La parte resolutiva del fallo: lo que sigue a "RESUELVE:" / "RESUELVO:" (max ~2500 chars).
# Se busca el ÚLTIMO match (la zona dispositiva está al final; las menciones previas a
# "resuelve" en el cuerpo son texto considerativo).
_RE_RESUELVE_ZONE = re.compile(r"(?is)\bRESUELV[EO]\b\s*[:\.]?(.{0,2500})")


def _last_resuelve_zone(text: str) -> Optional[str]:
    """Devuelve la última ocurrencia de la zona RESUELVE (la dispositiva real)."""
    matches = list(_RE_RESUELVE_ZONE.finditer(text))
    return matches[-1].group(1) if matches else None


# La dispositiva (zona RESUELVE) está SIEMPRE al final de un fallo/sentencia. Pero el
# `extracted_text` de la DB se truncó a 30000 chars desde el PRINCIPIO, así que en fallos
# largos el resolutivo queda AFUERA y lo que se halla es un "RESUELVE" citado/recapeado a
# media página, sin el verbo dispositivo real (bug caso 20: decía NEGAR y salía CONCEDE;
# casos 98/247: zona sin verbo). Por eso para clasificar el sentido leemos la dispositiva
# desde el FINAL del PDF (últimas páginas completas, sin depender del texto capado).
# (El antiguo cap de 30000 chars se ELIMINÓ — doc_io lee head+tail completo. Quedó dato
#  legacy en DB con extracted_text capado a 30k que pierde el footer/RESUELVE del final;
#  se re-extrae con scripts/recap_30k.py. Ver reference: cap 30k.)


# La dispositiva empieza con "PRIMERO: <VERBO>" aunque el keyword RESUELVE/FALLA no quede
# pegado (a veces va en la página anterior, o sale como "R E S U E L V E" espaciado, o el
# OCR lo pierde). Anclamos en el último PRIMERO seguido de un verbo dispositivo (caso 247:
# "PRIMERO: DENEGAR POR CARENCIA ACTUAL DE OBJETO" sin RESUELVE captrable).
_RE_PRIMERO_DECISION = re.compile(
    r"(?is)\bPRIMERO\b\s*[:.\-–]?\s*[-\s]*"
    r"(?=DENEGAR|NEGAR|NIEG|NO\s+(?:TUTELAR|AMPARAR|CONCEDER|SE)|CONCED|CONCÉD|TUTEL|AMPAR|"
    r"DECLAR|ORDEN|PROTEG|OTORG|REVOCAR|CONFIRMAR)"
)


def _footer_zone(d) -> Optional[str]:
    """ANCLA DE FOOTER: cola del documento leída del DISCO (donde va el bloque de firma
    administrativo: 'Proyectó/Elaboró/Revisó/Aprobó <NOMBRE>'). Espejo de
    `_dispositiva_zone` pero para el footer de las RESPUESTAS SED.

    Por qué existe: el `extracted_text` legacy está capado a ~30k chars = solo la CABEZA;
    el footer va al FINAL → se perdía y `abogado_responsable` quedaba vacío en respuestas
    largas. Esta ancla re-lee la cola del disco, así NO depende del texto capado.

    Returns la cola (texto) o None si no hay file_path legible.
    """
    fp = getattr(d, "file_path", None)
    if not fp or not os.path.exists(fp):
        return None
    suf = str(fp).lower()
    try:
        if suf.endswith(".pdf"):
            from backend.extraction.pdf_extractor import extract_pdf
            return (extract_pdf(fp, first_pages=0, last_pages=3).text or "") or None
        if suf.endswith((".docx", ".doc")):
            from backend.v9 import doc_io
            full = doc_io.read_one(fp).text or ""
            # El footer va al final; devolvemos la cola (con margen de sobra).
            return (full[-6000:] if full else "") or None
    except Exception as e:  # pragma: no cover
        logger.debug("footer_zone falló (doc#%s): %s", getattr(d, "id", "?"), e)
    return None


def _dispositiva_zone(d) -> Optional[str]:
    """Zona dispositiva leída del FINAL del documento (donde SIEMPRE está el resolutivo).
    En PDFs re-lee las últimas páginas completas y ancla en el último RESUELVE/FALLA o, si
    no aparece el keyword, en el último 'PRIMERO: <VERBO>'. NO cae al texto almacenado
    capado a 30k (cuya cola es narrativa media → falsos positivos)."""
    fp = getattr(d, "file_path", None)
    if fp and str(fp).lower().endswith(".pdf"):
        try:
            from backend.extraction.pdf_extractor import extract_pdf
            tail = extract_pdf(fp, first_pages=0, last_pages=5).text or ""
            z = _last_resuelve_zone(tail)
            if z:
                return z
            m = list(_RE_PRIMERO_DECISION.finditer(tail))
            if m:
                return tail[m[-1].start():m[-1].start() + 2500]
            return None
        except Exception as e:  # pragma: no cover
            logger.debug("dispositiva PDF falló (doc#%s): %s", getattr(d, "id", "?"), e)
    # No-PDF (docx/.doc): usar la zona RESUELVE del texto (estos rara vez son fallos).
    return _last_resuelve_zone(d.extracted_text or "")


# ── Transcripción VERBATIM de la parte resolutiva (requisito del jurado) ──
# A diferencia de `_dispositiva_zone` (que recorta a 2500 chars DESPUÉS de RESUELVE para
# clasificar el sentido), aquí copiamos el resolutivo COMPLETO e INCLUYENDO el encabezado,
# cortando en el cierre estándar de tutela. Tarea determinista (localizar + copiar), 0 LLM.
# Inicio (inclusive) de la parte resolutiva: "RESUELVE/RESUELVO" o "FALLA:".
_RE_RESUELVE_START = re.compile(r"(?is)\bRESUELV[EO]\b|\bFALLA\s*[:.]")
# Cierre de la dispositiva: "NOTIFÍQUESE Y CÚMPLASE" / "CÚMPLASE" (CÚMPLASE casi solo
# aparece en el cierre, no a media orden). Cortamos ANTES para no arrastrar la firma.
_RE_FALLO_CLOSE = re.compile(r"(?i)NOTIF[IÍ]QUE?SE\s+Y\s+C[UÚ]MPLASE|\bC[UÚ]MPLASE\b")


def _resuelve_verbatim(text: str, cap: int = 4000) -> Optional[str]:
    """Transcribe VERBATIM la parte resolutiva: desde el último 'RESUELVE/RESUELVO/FALLA:'
    (o, si no aparece el keyword, el último 'PRIMERO: <verbo>') hasta el cierre
    'NOTIFÍQUESE Y CÚMPLASE'/'CÚMPLASE'. Normaliza espacios suavemente (conserva la
    estructura PRIMERO/SEGUNDO). Devuelve None si quedan <20 chars útiles."""
    if not text:
        return None
    starts = list(_RE_RESUELVE_START.finditer(text))
    if starts:
        start = starts[-1].start()
    else:
        m = list(_RE_PRIMERO_DECISION.finditer(text))
        if not m:
            return None
        start = m[-1].start()
    span = text[start:start + cap]
    mc = _RE_FALLO_CLOSE.search(span)
    if mc:
        span = span[:mc.start()]
    # Normalización suave: colapsa espacios/tabs, comprime líneas en blanco repetidas.
    span = re.sub(r"[ \t]+", " ", span)
    span = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", span)
    span = span.strip(" \n\t·•-–—")
    return span if len(span) >= 20 else None


def _dispositiva_verbatim(d) -> Optional[str]:
    """Como `_dispositiva_zone` (lee el resolutivo del FINAL del PDF, sin el cap de 30k),
    pero devuelve la transcripción VERBATIM completa (RESUELVE…CÚMPLASE)."""
    fp = getattr(d, "file_path", None)
    if fp and str(fp).lower().endswith(".pdf"):
        try:
            from backend.extraction.pdf_extractor import extract_pdf
            tail = extract_pdf(fp, first_pages=0, last_pages=5).text or ""
            v = _resuelve_verbatim(tail)
            if v:
                return v
        except Exception as e:  # pragma: no cover
            logger.debug("resolutiva PDF falló (doc#%s): %s", getattr(d, "id", "?"), e)
    return _resuelve_verbatim(d.extracted_text or "")


def extract_parte_resolutiva_incidente_for_case(db: Session, case: Case) -> tuple[Optional[str], str]:
    """Transcribe verbatim el RESUELVE del auto que DECIDE el incidente de desacato
    (SANCIONA / CIERRA / NO_SANCIONA) — contiene las órdenes y el plazo de cumplimiento,
    para saber si se está en término. Solo se llena cuando el incidente ya tiene una
    decisión terminal (no EN_TRAMITE). Prioriza el auto que SANCIONA.
    Returns (texto|None, fuente∈{"auto_incidente","none"})."""
    autos = [
        d for d in db.query(Document).filter(
            Document.case_id == case.id,
            Document.doc_type.in_(["AUTO_INCIDENTE", "INCIDENTE_DESACATO"]),
        ).all() if (d.extracted_text or "") and len(d.extracted_text) > 300
    ]
    # Solo autos con decisión terminal; prioriza SANCIONA, luego CIERRA/NO_SANCIONA.
    _PRIO = {"SANCIONA": 0, "CIERRA": 1, "NO_SANCIONA": 2}
    decided = []
    for d in autos:
        dec = _classify_decision_incidente(d.extracted_text or "")
        if dec in _PRIO:
            decided.append((_PRIO[dec], -len(d.extracted_text or ""), d))
    decided.sort(key=lambda x: (x[0], x[1]))
    for _p, _l, d in decided:
        v = _dispositiva_verbatim(d)
        if v:
            return v, "auto_incidente"
    return None, "none"


def extract_parte_resolutiva_1ra_for_case(db: Session, case: Case) -> tuple[Optional[str], str]:
    """Transcribe verbatim la parte resolutiva de la SENTENCIA_1RA (misma selección de doc
    que `extract_sentido_fallo_1ra_for_case`: descarta 2da mal etiquetada, fallback a
    DESCONOCIDO con dispositiva clara). Returns (texto|None, fuente∈{"sentencia","desconocido","none"})."""
    from backend.extraction.doc_ops import _es_resolucion_admin
    sents = [
        d for d in db.query(Document).filter(
            Document.case_id == case.id, Document.doc_type == "SENTENCIA_1RA"
        ).all() if (d.extracted_text or "") and len(d.extracted_text) > 500
    ]
    sents.sort(key=lambda d: -len(d.extracted_text or ""))
    for d in sents:
        if _is_segunda_instancia(d) or _es_resolucion_admin(d.extracted_text or ""):
            continue
        v = _dispositiva_verbatim(d)
        if v:
            return v, "sentencia"
    for d in db.query(Document).filter(
        Document.case_id == case.id, Document.doc_type == "DESCONOCIDO"
    ).all():
        t = d.extracted_text or ""
        if not t or len(t) < 800 or _is_segunda_instancia(d) or _es_resolucion_admin(t):
            continue
        v = _dispositiva_verbatim(d)
        if v:
            return v, "desconocido"
    return None, "none"


def extract_parte_resolutiva_2da_for_case(db: Session, case: Case) -> tuple[Optional[str], str]:
    """Transcribe verbatim la parte resolutiva de la SENTENCIA_2DA (misma selección que
    `sentido_fallo_2nd` en `extract_impugnacion_cluster_for_case`). Returns
    (texto|None, fuente∈{"sentencia_2da","none"})."""
    sents = [
        d for d in db.query(Document).filter(
            Document.case_id == case.id, Document.doc_type == "SENTENCIA_2DA"
        ).all() if (d.extracted_text or "") and len(d.extracted_text) > 500
    ]
    sents.sort(key=lambda d: -len(d.extracted_text or ""))
    for d in sents:
        v = _dispositiva_verbatim(d)
        if v:
            return v, "sentencia_2da"
    return None, "none"


# Un doc clasificado SENTENCIA_1RA puede ser realmente de 2da instancia (mal etiquetado por
# el librarian). El filename suele delatarlo ("SegundaInstancia", "fallo_confirma", etc.);
# si no, el contenido (_doc_es_realmente_2da). Para `sentido_fallo_1st` debemos descartarlos.
# Cobertura ampliada (2026-05-24): variantes que se escapaban y dejaban fallos de 2da
# etiquetados SENTENCIA_1RA → "FalloTutela2A", "2da" pegado, "Fallo2ªInstancia",
# "SENTENCIA_CONFIRMA", "FALLO_2DA_CONFIRMA", "Sentencia2daInstanciaModifica".
_RE_2DA_FILENAME = re.compile(
    r"(?i)"
    r"segund[ao]\s*inst"                            # "segunda instancia", "segundainstancia"
    r"|2\s*[ªºao]?\.?\s*inst"                       # "2 inst", "2a.inst", "2ª inst"
    r"|2da"                                         # "2da", "2daInstancia", "FalloTutela2da"
    r"|(?:fallo|sentencia|tutela)[ _\-]*2[ªºa]"     # "FalloTutela2A", "sentencia2a"
    r"|fallo[^a-z]*confirma|confirma[^a-z]*fallo|fallo[^a-z]*revoca|revoca[^a-z]*fallo"
    r"|(?:fallo|sentencia)[^a-z]{0,3}(?:confirma|revoca|modifica)"   # "SENTENCIA_CONFIRMA"
    r"|(?:confirma|revoca|modifica)[^a-z]{0,3}(?:fallo|sentencia|subsidiar)"  # "CONFIRMA_SUBSIDIARIEDAD"
)

# El filename dice EXPLÍCITAMENTE 1ra. Sirve de override negativo: un fallo de 1ra real
# que en su cuerpo menciona "segunda instancia"/"Tribunal Superior" (boilerplate de los
# derechos de impugnación) NO debe ser descartado como 2da por _RE_ES_2DA (bug c73/c114).
_RE_1RA_FILENAME = re.compile(r"(?i)primera\s*inst|1[ºªea]*r?a?\s*inst|primerainstancia")


# Verbo del PRIMER ordinal de la dispositiva — señal DECISIVA de instancia.
# 2da: CONFIRMA/REVOCA/MODIFICA/INHIBE (decide sobre el fallo del a-quo).
# 1ra: verbo de mérito (TUTELA/AMPARA/CONCEDE/NIEGA/DENEGA/DECLARA, incl. "NO CONCEDER").
_RE_PRIMER_VERBO_DISP = re.compile(
    r"(?i)\b(?:primero|[úu]nico)\b\s*[\.\:\)\-–—\s]{0,4}\s*(?:LA\s+|EL\s+|LOS\s+|LAS\s+)?"
    r"(NO\s+(?:CONCED|TUTELA|AMPAR|PROTEG)\w*|CONFIRMA\w*|REVOCA\w*|MODIFICA\w*|INHIB\w*|"
    r"TUTELA\w*|AMPARA\w*|AMP[ÁA]RES\w*|CONCED\w*|NEGA\w*|NIEG[AUE]\w*|DENEGA\w*|DENIEGA\w*|DECLARA\w*)"
)


def _instancia_por_dispositiva(disp: str) -> Optional[str]:
    """'2da'/'1ra'/None según el verbo del primer ordinal de la dispositiva."""
    if not disp:
        return None
    m = _RE_PRIMER_VERBO_DISP.search(disp[:300])
    if not m:
        return None
    return "2da" if re.match(r"CONFIRMA|REVOCA|MODIFICA|INHIB", m.group(1).upper()) else "1ra"


def _is_segunda_instancia(d) -> bool:
    fn = d.filename or ""
    fn_2da = bool(_RE_2DA_FILENAME.search(fn))
    # Filename explícito de 1ra y SIN señal de 2da → es 1ra (evita falso+ por boilerplate).
    if _RE_1RA_FILENAME.search(fn) and not fn_2da:
        return False
    if fn_2da:
        return True
    # Señal DECISIVA: verbo del primer ordinal de la dispositiva REAL (leída del PDF).
    # Antes se usaba solo el boilerplate del encabezado (_RE_ES_2DA), que marcaba como
    # 2da a sentencias de 1ra que mencionan "segunda instancia"/"Tribunal Superior" en
    # los derechos de impugnación (falso+ → se perdía su resolutiva y su sentido).
    inst = _instancia_por_dispositiva(_dispositiva_verbatim(d) or "")
    if inst == "2da":
        return True
    if inst == "1ra":
        return False
    # Sin verbo dispositivo claro → último recurso: marcador de cabecera.
    return _doc_es_realmente_2da(d.extracted_text or "")


# Marcadores de que un doc clasificado SENTENCIA_1RA es REALMENTE una sentencia de 2da
# (mal clasificada por el librarian): "segunda instancia", "Tribunal Superior", o el
# verbo dispositivo es CONFIRMAR/REVOCAR/MODIFICAR (= verbos de 2da).
_RE_ES_2DA = re.compile(
    r"(?i)\b(?:segunda\s+instancia|sentencia\s+de\s+segunda|tribunal\s+superior|"
    r"tribunal\s+administrativo|sala\s+(?:civil|penal|laboral|administrativa)\s+(?:de\s+decisi[óo]n\s+)?(?:del\s+tribunal|de\s+tutela)|"
    r"acci[óo]n\s+de\s+tutela\s+(?:de\s+)?2\s*instancia)"
)
# Verbos dispositivos de 2da (si aparecen en el RESUELVE, no clasifican 1ra).
_RE_VERBOS_2DA = re.compile(r"(?i)^\s*(?:primero\s*[\.\:]?\s*[-–]?\s*)?(?:CONFIRMAR|REVOCAR|MODIFICAR|INHIBIR)")

# Patrones por sentido — orden importa (más específicos primero).
# Desistimiento ACEPTADO por el juez (no basta el escrito del accionante): el
# proceso termina sin fallo de fondo. Señal decisiva → va primero en _FALLO_PATTERNS.
_RE_DESIST_ACEPTADO = re.compile(
    r"(?:acept\w+|admit\w+|aprob\w+|reconoc\w+)\s+(?:el\s+|al\s+|del\s+|l[ao]\s+)?desistimiento"
    # "tener por desistida la acción/tutela": exige que sea de la ACCIÓN (no del incidente)
    # y NO condicional ("so pena de tener por desistido el incidente" — caso 40 falso+).
    # permite palabras intermedias ("la PRESENTE acción") pero NO 'incidente' (evita falso+)
    r"|(?<!pena de )\btener\s+por\s+desistid[ao]\s+(?:(?!incidente)[a-záéíóúñ]+\s+){0,3}?(?:acci[óo]n|tutela|solicitud|amparo)"
    r"|desistimiento[^.\n]{0,40}(?:archív|d[ae]r\s+por\s+terminad)",
    re.I,
)

_FALLO_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("DESISTIMIENTO",   _RE_DESIST_ACEPTADO),
    ("CARENCIA_OBJETO", re.compile(r"(?i)\bcarenc[ií]a\s+(?:actual\s+)?de\s+objeto|sustracci[óo]n\s+de\s+materia")),
    ("HECHO_SUPERADO",  re.compile(r"(?i)\bhecho\s+super(?:ad|aci|ar)|da[ñn]o\s+consumad")),
    ("IMPROCEDENTE",    re.compile(r"(?i)\bdeclarar?\s+(?:la\s+)?improcedente|\bimprocedenc[ií]a\s+(?:de|del|por|en)|"
                                   r"\bimprocedente\s+(?:el\s+|la\s+|por\s+|esta\s+|present)|"
                                   r"\bIMPROCEDENTE\b|\bpor\s+improcedente\b")),
    ("CONCEDE_PARCIAL", re.compile(r"(?is)\b(?:concede\w*|conceder\b|amparar?\w*|amp[áa]rese|tutela\w*|tut[ée]lese|protege\w*)"
                                   r"[^.\n]{0,90}?\bparcial(?:ment\w+|idad)?")),
    # NIEGA antes de CONCEDE: si el verbo negar (o "no concede/tutela/ampara") va seguido
    # de "amparo|tutela|acción|derechos fundamentales" dentro de ~80 chars, es NIEGA.
    # Si NIEGA es accesorio ("niega la nulidad", "niega medida provisional") no se enlaza
    # a amparo/tutela y cae a CONCEDE.
    # El objeto tras la negación va SIN exigir calificador exacto: los fallos dicen
    # "NO CONCEDER la protección solicitada" / "NO TUTELAR los derechos" (no siempre
    # "protección constitucional" / "derecho fundamental") — exigirlo dejaba esos
    # fallos como CONCEDE (bug #504).
    ("NIEGA",           re.compile(r"(?i)\b(?:negar|nieg[ueao]\w*|niegues\w*|deneg\w+|"
                                   r"no\s+(?:se\s+)?(?:concede\w*|tutela\w*|tutelar|tut[ée]les\w*|amparar?\w*|amp[áa]res\w*|protege\w*))"
                                   r"\b[^.\n]{0,80}?\b(?:amparo|tutela|acci[óo]n\s+de\s+tutela|protecci[óo]n|"
                                   r"derecho[s]?|petici[óo]n)")),
    # CONCEDE: verbos del amparo + verbos dispositivos del SED context (cuando el juez
    # CONCEDE, ordena traslados/reintegros/nombramientos/dejar-sin-efecto-de-actos-SED).
    # OJO: solo VERBOS del amparo. El sustantivo "tutela"/"acción de tutela" NO debe contar
    # (antes `tutel[aaerio]\w*` pescaba "acción de tutela interpuesta por…" → falso CONCEDE,
    # casos 98/247). Verbos: tutelar/tutélese, conceder, ampárese/amparar, proteger, otorgar.
    ("CONCEDE",         re.compile(r"(?i)\b(?:tutelar\w*|tut[ée]les[ea]|conced[eaiou]\w*|conceder\b|"
                                   r"amp[áa]rese|amparar?\w*|protege\w*|otorga\w+|otorgar\b|"
                                   r"ordenar\s+(?:a|al)|ord[ée]nese|ord[ée]nase|"
                                   r"trasladar?\b|traslade?se|reintegrar?\b|rein[té]ges\w*|"
                                   r"nombrar?\b|n[óo]mbrese|"
                                   r"dejar?\s+sin\s+efecto|dej[éa]se\s+sin\s+efecto|"
                                   r"revocar?\s+(?:el\s+|la\s+|los\s+|las\s+)?(?:acto|resoluci[óo]n|decisi[óo]n|negativa|comunicado))")),
)


# Concesión SUSTANTIVA del amparo (verbo de amparo ligado a derecho/amparo/pretensión),
# para detectar coexistencia con NIEGA en fallos MIXTOS. NO incluye órdenes procesales
# ("ordénese notificar") para evitar falsos CONCEDE_PARCIAL sobre NIEGA puros.
_RE_CONCEDE_SUSTANTIVO = re.compile(
    r"(?i)\b(?:tutelar|tut[ée]les[ea]|conced[eaiou]\w*|conceder|amparar?\w*|amp[áa]rese|"
    r"protege\w*|prot[ée]jase)\b[^.\n]{0,45}?\b(?:derecho|amparo|tutela|pretensi|acci[óo]n)"
)


def _classify_sentido_fallo(zone: str) -> Optional[str]:
    if not zone:
        return None
    result = None
    for tag, pat in _FALLO_PATTERNS:
        if pat.search(zone):
            result = tag
            break
    # Fallo MIXTO: el RESUELVE NIEGA un derecho pero CONCEDE otro (sin decir "parcial").
    # Regla: leer todo el RESUELVE. Una concesión SUSTANTIVA NO negada (que no sea
    # "NO TUTELAR / NO CONCEDER") coexistiendo con la negación → CONCEDE_PARCIAL.
    if result == "NIEGA":
        for m in _RE_CONCEDE_SUSTANTIVO.finditer(zone):
            prefix = zone[max(0, m.start() - 14):m.start()].lower()
            if not re.search(r"\b(?:no|deneg\w*|niega\w*|niegan|negar)\s*$", prefix):
                return "CONCEDE_PARCIAL"  # concesión real (no negada) → fallo mixto
    return result


# Recap del sentido del 1RA dentro de una sentencia de 2da (u otro doc): "Mediante
# sentencia [de fecha X] el a-quo CONCEDIÓ/NEGÓ/DECLARÓ IMPROCEDENTE/HECHO SUPERADO el amparo".
# Capturamos una ventana corta tras el ancla y clasificamos con los mismos patrones.
_RE_RECAP_FALLO_1RA = re.compile(
    r"(?is)(?:mediante\s+sentencia|sentencia\s+(?:proferida|emitida|de\s+(?:fecha|primera\s+instancia))|"
    r"(?:el|la)\s+(?:a-?quo|juez\s+(?:de\s+)?primera\s+instancia|despacho\s+de\s+primera)|"
    r"fallo\s+(?:de\s+|proferido\s+(?:en|por).{0,40}?))\b(.{0,400})"
)


def _doc_es_realmente_2da(text: str) -> bool:
    """Heurística: True si un doc clasificado SENTENCIA_1RA es realmente de 2da (mal
    clasificado por el librarian). Marcadores: 'segunda instancia', 'Tribunal Superior',
    'sala civil-familia', o el RESUELVE empieza con CONFIRMAR/REVOCAR/MODIFICAR."""
    if not text:
        return False
    head = text[:2000]
    if _RE_ES_2DA.search(head):
        return True
    zone = _last_resuelve_zone(text)
    if zone and _RE_VERBOS_2DA.search(zone[:200]):
        return True
    return False


def _classify_recap_1ra(text: str) -> Optional[str]:
    """Busca en un texto (sentencia 2da, auto de impugnación, etc.) el recap del fallo
    de 1ra y clasifica. Devuelve None si no hay recap claro."""
    if not text:
        return None
    for m in _RE_RECAP_FALLO_1RA.finditer(text[:8000]):
        window = m.group(1)
        tag = _classify_sentido_fallo(window)
        if tag:
            return tag
    return None


def _desistimiento_aceptado(db: Session, case: Case) -> bool:
    """True si el accionante desistió y el juez lo ACEPTÓ → el proceso termina sin
    fallo de fondo. Señal fuerte: filename de un AUTO que ACEPTA/ADMITE el
    desistimiento, o texto que lo acepta. NO basta el escrito de desistimiento del
    accionante (eso es solo la solicitud); debe haber aceptación judicial."""
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        fn = (d.filename or "").upper()
        if "DESISTIMIENT" in fn and ("ACEPTA" in fn or "ADMITE" in fn):
            return True
        txt = d.extracted_text or ""
        if txt and _RE_DESIST_ACEPTADO.search(txt):
            return True
    return False


def extract_sentido_fallo_1ra_for_case(db: Session, case: Case) -> tuple[Optional[str], str]:
    """Lee la zona RESUELVE de la SENTENCIA_1RA del case y la clasifica al vocab
    `SENTIDO_FALLO_VOCAB`. Si no hay sentencia 1ra usable, recurre al recap dentro de la
    SENTENCIA_2DA / AUTO_CONCEDE_IMPUGNACION / IMPUGNACION / DESCONOCIDO (procesalmente
    OBLIGA a que haya habido fallo de 1ra si hay impugnación o incidente — art. 32 D2591/91).
    Returns (valor, fuente) — fuente ∈ {"desistimiento","sentencia","desconocido","recap_2da","none"}."""
    # Guard: una RESOLUCIÓN ADMINISTRATIVA de la SED ("RESUELVE: ARTÍCULO PRIMERO:
    # TRASLADAR/NOMBRAR") NO es un fallo judicial — aunque quede mal rotulada
    # SENTENCIA_1RA/DESCONOCIDO. El extractor la rechaza al leer (casos c2/c95/c164/c179/c468).
    from backend.extraction.doc_ops import _es_resolucion_admin

    # 1) SENTENCIA_1RA "real" (descarta las 2da mal etiquetadas por filename O contenido).
    # La dispositiva se lee del FINAL del PDF (no del texto capado), donde vive el resolutivo.
    sents = [
        d for d in db.query(Document).filter(
            Document.case_id == case.id, Document.doc_type == "SENTENCIA_1RA"
        ).all() if (d.extracted_text or "") and len(d.extracted_text) > 500
    ]
    sents.sort(key=lambda d: -len(d.extracted_text or ""))
    for d in sents:
        if _is_segunda_instancia(d):
            continue  # es 2da mal etiquetada; su sentido va a sentido_fallo_2nd
        if _es_resolucion_admin(d.extracted_text or ""):
            continue  # resolución administrativa SED, no fallo judicial
        zone = _dispositiva_zone(d)
        tag = _classify_sentido_fallo(zone) if zone else None
        if tag:
            return tag, "sentencia"

    # 2) DESCONOCIDO con dispositiva clara (sentencia 1ra mal clasificada por el librarian)
    for d in db.query(Document).filter(
        Document.case_id == case.id, Document.doc_type == "DESCONOCIDO"
    ).all():
        t = d.extracted_text or ""
        if not t or len(t) < 800:
            continue
        if _is_segunda_instancia(d) or _es_resolucion_admin(t):
            continue
        zone = _dispositiva_zone(d)
        if not zone:
            continue
        tag = _classify_sentido_fallo(zone)
        if tag:
            return tag, "desconocido"

    # 3) Recap del 1ra dentro de un doc de 2da / impugnación: "el a-quo CONCEDIÓ/NEGÓ..."
    for dt in ("SENTENCIA_2DA", "AUTO_CONCEDE_IMPUGNACION", "IMPUGNACION", "AUTO_2DA", "NOTIFICACION_FALLO"):
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            t = d.extracted_text or ""
            if not t or len(t) < 500:
                continue
            tag = _classify_recap_1ra(t)
            if tag:
                return tag, "recap_2da"

    # 4) DESISTIMIENTO aceptado — ÚLTIMO RECURSO, solo si NO hay fallo de mérito propio.
    # Jurídicamente un fallo de fondo (AMPARAR/NEGAR/carencia) SIEMPRE gobierna: el
    # desistimiento aceptado solo define el sentido cuando el proceso terminó SIN
    # sentencia (art. 26 D2591/91). Correrlo al final evita que un auto de
    # desistimiento AJENO —carpeta mezclada por rad corto compartido entre juzgados
    # distintos— clasifique mal un caso que sí tuvo fallo (bug casos 25/37: 2026-00037
    # y 2026-00014 contaminados por el desistimiento de 2026-00014-00 del Hato).
    if _desistimiento_aceptado(db, case):
        return "DESISTIMIENTO", "desistimiento"
    return None, "none"


def _parse_ddmmyyyy(s: Optional[str]):
    """'DD/MM/AAAA' → datetime.date | None."""
    if not s:
        return None
    try:
        from datetime import date as _date
        d, m, y = s.split("/")
        return _date(int(y), int(m), int(d))
    except Exception:
        return None


def extract_fecha_fallo_1ra_for_case(db: Session, case: Case) -> tuple[Optional[str], str]:
    """Fecha del dateline de la SENTENCIA_1RA. Cota: año del rad23 ±1 (los fallos
    de tutela caen 10-30 días después del auto; pueden cruzar año si el auto fue en
    diciembre). Además: si ya hay `fecha_ingreso`, el fallo debe ser ≥ a ella (si todos
    los candidatos violan, se devuelve None — evita capturar fechas citadas o del auto
    recapeado dentro del cuerpo de la sentencia)."""
    yh = _rad_year(case)
    fi = _parse_ddmmyyyy(getattr(case, "fecha_ingreso", None))
    sents = [
        d for d in db.query(Document).filter(
            Document.case_id == case.id, Document.doc_type == "SENTENCIA_1RA"
        ).all() if (d.extracted_text or "") and len(d.extracted_text) > 500
    ]
    sents.sort(key=lambda d: -len(d.extracted_text or ""))

    def _consistent(v: Optional[str]) -> bool:
        if not v:
            return False
        if fi is None:
            return True
        df = _parse_ddmmyyyy(v)
        return bool(df) and df >= fi

    for d in sents:
        t = d.extracted_text
        # candidatos: todas las fechas del head + tail, filtrar por año y por cronología
        cands = (_parse_es_dates(t[:800]) + _parse_es_dates(t[-2200:]))
        for _pos, v in cands:
            # filtro por año del rad ±1
            if yh is not None:
                try:
                    if abs(int(v[-4:]) - yh) > 1:
                        continue
                except ValueError:
                    continue
            # filtro cronológico: fecha_fallo ≥ fecha_ingreso
            if _consistent(v):
                return v, "sentencia_dateline"
        # si ninguna fecha cumple el filtro cronológico, fallback al primer match año-OK
        # (solo si no hay fecha_ingreso para comparar — sin esa cota, lo mejor disponible)
        if fi is None:
            v = _first_date_near_year(cands, yh, tol=1)
            if v:
                return v, "sentencia_dateline"
    return None, "none"


# ============================================================
# CLUSTER DE IMPUGNACIÓN  (campo 15)
# ============================================================
# Cuatro campos relacionados (todos surgen de los docs de 2da instancia):
#   - impugnacion      SI / NO              (¿hubo recurso de impugnación?)
#   - quien_impugno    ACCIONANTE / ACCIONADO / MINISTERIO_PUBLICO / AMBOS
#   - sentido_fallo_2nd ∈ SENTIDO_FALLO_2DA_VOCAB
#   - fecha_fallo_2nd  DD/MM/AAAA, con cota fallo_2nd ≥ fallo_1st
# (forest_impugnacion y juzgado_2nd ya hechos en campos 3b y 8.)
#
# Lectura focal: aplicamos la heurística del usuario ("primeras 5 págs + últimas
# 3 págs") → `_RE_RESUELVE_ZONE` se busca en `text[-3500:]` (la dispositiva está
# al final del fallo de 2da); `_RE_QUIEN_IMPUGNO` en `text[:6000]` (suele estar
# en los VISTOS / antecedentes del auto que concede / sentencia de 2da).

SENTIDO_FALLO_2DA_VOCAB: tuple[str, ...] = (
    "CONFIRMA", "CONFIRMA_PARCIAL", "REVOCA", "MODIFICA", "INHIBE", "NULIDAD",
)
QUIEN_IMPUGNO_VOCAB: tuple[str, ...] = (
    "ACCIONANTE", "ACCIONADO", "MINISTERIO_PUBLICO", "AMBOS",
)

# Doctypes que evidencian impugnación (NOTIFICACION_FALLO se excluye: notifica
# CUALQUIER fallo, no es marca específica de 2da instancia).
_IMPUGNACION_DOCTYPES = ("SENTENCIA_2DA", "AUTO_2DA", "AUTO_CONCEDE_IMPUGNACION", "IMPUGNACION")

# "impugnación interpuesta/presentada/formulada/apelada por ..." / "del/de la accionante"
# / "recurso de impugnación o apelación presentado por ...". Captura quién en group(1).
_RE_QUIEN_IMPUGNO = re.compile(
    r"(?is)(?:"
    r"(?:impugnaci[óo]n|recurso\s+de\s+(?:impugnaci[óo]n|apelaci[óo]n|alzada)|apelaci[óo]n)\s+"
    r"(?:interpuest[ao]|presentad[ao]|formulad[ao]|incoad[ao]|allegad[ao]|radicad[ao]|sustentad[ao])?\s*"
    r"(?:por\s+(?:la\s+parte\s+|el\s+|la\s+|los\s+|las\s+|señor\w*\s+|doctor\w*\s+|dra?\.?\s+)?|"
    r"del?\s+(?:la\s+)?|de\s+la\s+)"
    r"|se\s+concede\s+(?:el\s+)?recurso\s+(?:de\s+(?:impugnaci[óo]n|apelaci[óo]n)\s+)?(?:interpuest[ao]\s+|presentad[ao]\s+)?por\s+(?:el\s+|la\s+|los\s+|las\s+)?"
    r")"
    r"([^,.\n;:()]{3,90})"
)
# En el SUBJECT de un email: "IMPUGNACIÓN DEL ACCIONANTE", "PRESENTADA POR LA ACCIONADA",
# "RECURSO DE IMPUGNACIÓN PRESENTADO POR EL ACCIONANTE", "IMPUGNACIÓN DE LA SED".
_RE_SUBJ_QUIEN_IMPUGNO = re.compile(
    r"(?i)(?:impugnaci[óo]n|recurso\s+de\s+(?:impugnaci[óo]n|apelaci[óo]n))\s*"
    r"(?:del?\s+(?:la\s+)?|de\s+la\s+|presentad[oa]\s+por\s+(?:el\s+|la\s+)?|interpuest[oa]\s+por\s+(?:el\s+|la\s+)?)"
    r"(accionant\w*|accionad[oa]\w*|vinculad[oa]\w*|secretar[íi]a\w*|gobernaci[óo]n|s\.?\s?e\.?\s?d\b|"
    r"ministerio\s+p[úu]blico|personer\w*)"
)
# Marca de que la impugnación SE INTERPUSO / SE CONCEDIÓ / hubo 2da instancia — NO
# la mera mención de que "procede el recurso de impugnación" (boilerplate de todo fallo).
_RE_IMPUG_FLAG = re.compile(
    r"(?i)(?:"
    r"auto\s+(?:que\s+)?(?:concede|admite|avoca\s+(?:el\s+conocimiento\s+de\s+)?(?:la\s+)?(?:impugnaci|2)|concede)\s+(?:el\s+recurso\s+de\s+)?impugna"
    r"|se\s+concede\s+(?:el\s+)?recurso\s+de\s+(?:impugnaci[óo]n|apelaci[óo]n)"
    r"|(?:impugnaci[óo]n|recurso\s+de\s+(?:impugnaci[óo]n|apelaci[óo]n)|escrito\s+de\s+impugnaci[óo]n)\s+(?:fue\s+)?(?:interpuest[oa]|presentad[oa]|formulad[oa]|incoad[oa]|radicad[oa]|sustentad[oa])"
    r"|notificaci[óo]n\s+(?:de\s+(?:la\s+|el\s+)?|del\s+)?(?:impugnaci[óo]n|recurso\s+de\s+impugna|escrito\s+de\s+impugna|auto\s+(?:que\s+)?concede\s+impugna)"
    r"|(?:fallo|sentencia|providencia|notificaci[óo]n\s+fallo|notificaci[óo]n\s+sentencia)\s+(?:de\s+)?(?:segunda\s+instancia|2[ªa]\.?\s*(?:inst\b|instancia))"
    r"|^[#\s>]*(?:rv\s*:|re\s*:|fwd?\s*:)?\s*impugnaci[óo]n\b"
    r"|^[#\s>]*(?:rv\s*:|re\s*:|fwd?\s*:)?\s*recurso\s+de\s+(?:impugnaci[óo]n|apelaci[óo]n)\b"
    r")",
    re.MULTILINE,
)

# Patrones de sentido de 2da, orden importa (específicos primero).
_FALLO_2DA_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("NULIDAD",          re.compile(r"(?i)\bdeclarar?\s+(?:la\s+)?nulidad\s+de\s+lo\s+actuad|\bdeclar[óa]r?se\s+(?:la\s+)?nulidad|\bdecretar?\s+(?:la\s+)?nulidad")),
    ("INHIBE",           re.compile(r"(?i)\binhibirse\b|\binh[íi]bese\b|\bdecisi[óo]n\s+inhibitori|\babstenerse\s+de\s+(?:pronunciar|emitir|decidir)")),
    ("REVOCA",           re.compile(r"(?i)\brevocar?\s+(?:parcialmente\s+)?(?:el|la|los|las|en\s+su)?\s*(?:sentencia|fallo|providencia|decisi[óo]n|numeral|ordinal)|\brev[óo]ques\w*\s+(?:el|la|parcialmente)|\brev[óo]case")),
    ("MODIFICA",         re.compile(r"(?i)\bmodificar?\s+(?:el|la|los|las)?\s*(?:sentencia|fallo|providencia|numeral|ordinal|decisi[óo]n)|\bmod[ií]f[íi]ques\w*")),
    ("CONFIRMA_PARCIAL", re.compile(r"(?is)\bconfirmar?\b[^.\n]{0,90}?\bparcial(?:ment\w+|idad)?|"
                                    r"\bconfirmar?\s+parcialmente\b|"
                                    r"\bconfirmar?\b[^.\n]{0,40}?\b(?:numeral|ordinal)\s+(?:primero|segundo|tercero|\d)|"
                                    r"\bconfirmar?\b[^.\n]{0,150}?\b(?:y\s+)?revocar?\b|\brevocar?\b[^.\n]{0,150}?\b(?:y\s+)?confirmar?\b")),
    ("CONFIRMA",         re.compile(r"(?i)\bconfirmar?\b|\bconf[íi]rmes\w*|\bconfirmar?\s+(?:el|la|los|las|en\s+su)\s+(?:sentencia|fallo|providencia|integridad|totalidad)|"
                                    r"\bnegar?\s+(?:el\s+)?recurso\s+de\s+impugna|\bdeneg\w+\s+(?:el\s+)?recurso\s+de\s+impugna")),
)


def _classify_sentido_fallo_2da(zone: str) -> Optional[str]:
    if not zone:
        return None
    for tag, pat in _FALLO_2DA_PATTERNS:
        if pat.search(zone):
            return tag
    return None


def _classify_quien_impugno(raw: str, case: Case) -> Optional[str]:
    """Dado el string que viene después de 'impugnación interpuesta por...', clasifica
    al vocab QUIEN_IMPUGNO_VOCAB."""
    if not raw:
        return None
    f = _fold(raw)
    # marcas léxicas directas
    if "ministerio publico" in f or "procurador" in f or "agente del ministerio" in f:
        return "MINISTERIO_PUBLICO"
    if re.search(r"\baccionant", f):
        return "ACCIONANTE"
    if re.search(r"\baccionad[oa]\b|\bdemandad[oa]\b", f):
        return "ACCIONADO"
    # entidades = ACCIONADO (Gobernación, SED, colegio, IE, municipio, alcaldía)
    if re.search(r"\b(?:secretaria|gobernacion|ministerio|colegio|institucion\s+educativa|escuela|municipio|alcald[íi]a|departamento|hospital|eps|ese)\b", f):
        return "ACCIONADO"
    # personería municipal cuando NO es la accionante → MINISTERIO_PUBLICO (agente)
    if "personeria" in f or "personero" in f:
        acc = (getattr(case, "accionante", "") or "").upper()
        if "PERSONER" not in acc:
            return "MINISTERIO_PUBLICO"
        return "ACCIONANTE"
    # quedan los nombres de persona — comparar con case.accionante
    acc = (getattr(case, "accionante", "") or "")
    if acc:
        # tokens del nombre extraído del case
        acc_tokens = set(_fold(acc).split())
        raw_tokens = set(f.split())
        common = acc_tokens & raw_tokens
        if common and len([w for w in common if len(w) >= 4]) >= 2:
            return "ACCIONANTE"
    # default razonable: si parece nombre propio (capitalizado), tira a ACCIONANTE
    if re.match(r"^[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+", raw.strip()):
        return "ACCIONANTE"
    return None


def extract_impugnacion_cluster_for_case(db: Session, case: Case) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], str]:
    """Devuelve (impugnacion_flag, quien_impugno, sentido_fallo_2nd, fecha_fallo_2nd, fuente).
    fuente ∈ {"docs_2da", "emails", "no"}.

    Escanea tanto los PDFs/DOCX de 2da como el SUBJECT/cuerpo de los emails .md
    (que descarga el monitor) — esos correos suelen traer en el asunto info de oro
    ("NOTIFICACIÓN AUTO CONCEDE IMPUGNACIÓN — PRESENTADA POR LA ACCIONADA")."""
    docs_2da = db.query(Document).filter(
        Document.case_id == case.id,
        Document.doc_type.in_(_IMPUGNACION_DOCTYPES),
    ).all()
    # textos de los emails .md (cabecera ~2000 chars = subject + headers) + Email.subject de la DB
    email_heads: list[str] = []
    for d in db.query(Document).filter(
        Document.case_id == case.id, Document.doc_type.in_(["EMAIL_JUDICIAL", "EMAIL_INTERNO"])
    ).all():
        t = _read_doc_text(d)
        if t:
            email_heads.append(t[:2500])
    for e in db.query(Email).filter(Email.case_id == case.id).all():
        if e.subject:
            email_heads.append(e.subject)

    has_2da = len(docs_2da) > 0
    flag_from_email = any(_RE_IMPUG_FLAG.search(h) for h in email_heads)

    # 1) flag SI/NO
    if not has_2da and not flag_from_email:
        return ("NO", None, None, None, "no")
    fuente = "docs_2da" if has_2da else "emails"

    # 2) quien_impugno — de los docs de 2da (head 8000 + body recap) Y de los emails
    quien_set: set = set()
    for d in docs_2da:
        t = d.extracted_text or ""
        if not t:
            continue
        for m in _RE_QUIEN_IMPUGNO.finditer(t[:8000]):
            tag = _classify_quien_impugno(m.group(1), case)
            if tag:
                quien_set.add(tag)
    # emails: subject pattern (preciso) + body pattern (genérico)
    for h in email_heads:
        m = _RE_SUBJ_QUIEN_IMPUGNO.search(h)
        if m:
            tag = _classify_quien_impugno(m.group(1), case)
            if tag:
                quien_set.add(tag)
    for d in db.query(Document).filter(
        Document.case_id == case.id, Document.doc_type.in_(["EMAIL_JUDICIAL", "EMAIL_INTERNO"])
    ).all():
        t = _read_doc_text(d)
        if not t:
            continue
        for m in _RE_QUIEN_IMPUGNO.finditer(t[:6000]):
            tag = _classify_quien_impugno(m.group(1), case)
            if tag:
                quien_set.add(tag)
    quien = None
    if quien_set:
        if "ACCIONANTE" in quien_set and "ACCIONADO" in quien_set:
            quien = "AMBOS"
        else:
            for tag in ("ACCIONANTE", "ACCIONADO", "MINISTERIO_PUBLICO"):
                if tag in quien_set:
                    quien = tag
                    break

    # 3) sentido_fallo_2nd — RESUELVE de SENTENCIA_2DA (últimas ~3500 chars = parte resolutiva al final)
    sentido_2nd = None
    sents_2da = [d for d in docs_2da if d.doc_type == "SENTENCIA_2DA" and (d.extracted_text or "") and len(d.extracted_text) > 500]
    sents_2da.sort(key=lambda d: -len(d.extracted_text or ""))
    for d in sents_2da:
        # Igual que la 1ra instancia: leer la dispositiva del FINAL del PDF con
        # `_dispositiva_zone` (re-lee las últimas páginas y ancla en RESUELVE o en
        # "PRIMERO: <verbo>" incl. CONFIRMAR/REVOCAR). Robusto ante extracted_text
        # capado/sin "RESUELVE" en DB (antes fallaba: fecha_fallo_2nd salía pero
        # sentido_fallo_2nd quedaba vacío — c338). Fallback al texto en DB.
        t = d.extracted_text or ""
        zone = _dispositiva_zone(d) or _last_resuelve_zone(t[-3500:]) or _last_resuelve_zone(t)
        if zone:
            tag = _classify_sentido_fallo_2da(zone)
            if tag:
                sentido_2nd = tag
                break

    # 4) fecha_fallo_2nd — dateline de SENTENCIA_2DA con cota (fecha ≥ fecha_fallo_1st)
    fecha_2nd = None
    yh = _rad_year(case)
    f1 = _parse_ddmmyyyy(getattr(case, "fecha_fallo_1st", None))
    for d in sents_2da:
        t = d.extracted_text
        cands = _parse_es_dates(t[:800]) + _parse_es_dates(t[-2200:])
        for _pos, v in cands:
            # cota por año del rad ±1 (2da puede ser ese año o el siguiente)
            if yh is not None:
                try:
                    if abs(int(v[-4:]) - yh) > 1:
                        continue
                except ValueError:
                    continue
            # cronología: fecha_fallo_2nd ≥ fecha_fallo_1st
            if f1:
                df = _parse_ddmmyyyy(v)
                if df and df < f1:
                    continue
            fecha_2nd = v
            break
        if fecha_2nd:
            break

    return ("SI", quien, sentido_2nd, fecha_2nd, fuente)


# ============================================================
# CLUSTER DE INCIDENTES DE DESACATO  (campo 16 — slots 1/2/3)
# ============================================================
# 12 campos: incidente / fecha_apertura_incidente / responsable_desacato /
# decision_incidente — y sus _2 y _3. Un case puede tener 0-3 incidentes; los
# slots 2/3 solo se llenan si hay ≥2 / ≥3 escritos de incidente distintos.
# Fuente PRIMARIA = los .md de los emails (el monitor descarga subjects/cuerpos
# tipo "AUTO APERTURA INCIDENTE DESACATO RAD X", "AUTO SANCIONA DESACATO",
# "AUTO TERMINACION INCIDENTE", "RESPUESTA REQUERIMIENTO INCIDENTE") + los docs
# INCIDENTE_DESACATO (escrito del incidentante) y AUTO_INCIDENTE (la decisión).

DECISION_INCIDENTE_VOCAB: tuple[str, ...] = (
    "SANCIONA", "NO_SANCIONA", "NIEGA_APERTURA", "CIERRA", "EN_TRAMITE",
)

# ¿Hay señal de incidente de desacato? (en subject/cuerpo de email o en texto de doc)
_RE_INCIDENTE_SIGNAL = re.compile(
    r"(?i)\bincidente\s+de\s+desacato|\bincidente\s+(?:n[°º.]?\s*)?\d{4}-?\d|\bapertur\w+\s+(?:formal\s+)?(?:de\s+)?(?:incidente|desacato)|"
    r"\babr[ií]\w*\s+(?:el\s+)?incidente|\bincidente\b[^.\n]{0,30}\bdesacato\b|\bdesacato\b[^.\n]{0,30}\bincidente\b|"
    r"\b(?:requerimiento|requiere\s+previo|previo\s+(?:a\s+(?:la\s+)?)?apertura)\s+(?:de\s+(?:la\s+)?)?(?:incidente|desacato)|"
    r"\b(?:respuesta\s+)?requerimiento\s+incidente|\bterminaci[óo]n\s+(?:del?\s+)?incidente|"
    r"\bdesacato\s+(?:de\s+(?:la\s+)?(?:sentencia|fallo|orden)|tutela\s+rad|2\d{3}-?\d)"
)
# Verbo dispositivo del AUTO de incidente / pista en el subject del email → decision_incidente
_DECISION_INC_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    # NO_SANCIONA y NIEGA_APERTURA van ANTES que SANCIONA: "abstenerse de imponer
    # sanciones" contiene "imponer sanción" y matchearía SANCIONA por error (caso c12).
    ("NO_SANCIONA",    re.compile(r"(?i)\babstenerse\s+de\s+(?:imponer|sancionar)|\babst[ée]ngase\s+de\s+sancionar|\bno\s+sancionar?\b|\bno\s+(?:se\s+)?(?:impone|impondr[áa])\s+sanci[óo]n")),
    ("NIEGA_APERTURA", re.compile(r"(?i)\b(?:negar|rechazar|inadmitir|denegar|no\s+(?:dar\s+)?(?:apertura|tr[áa]mite))\b[^.\n]{0,40}?\b(?:apertura|incidente|tr[áa]mite\s+incidental)|\bauto\s+(?:que\s+)?(?:niega|rechaza|inadmite)\s+(?:la\s+)?apertura|\babstenerse\s+de\s+(?:dar\s+)?(?:apertura|abrir|tr[áa]mit\w+)")),
    ("SANCIONA",       re.compile(r"(?i)\bsancionar?\b(?!\s+(?:el\s+)?archivo)|\bsancion[óa]\b|\bimpon\w+\s+(?:la\s+)?sanci[óo]n|\bauto\s+sanciona|providencia\s+sanciona|sancionar?\s+por\s+desacato")),
    ("CIERRA",         re.compile(r"(?i)\barchivar?\b|\barch[íi]vese\b|\b(?:ordenar?|decretar?|dispon\w+|declarar?)\s+(?:el\s+)?archivo\b|\barchivo\s+(?:definitivo\s+)?de\s+(?:las?\s+|los\s+|el\s+|este\s+)?(?:presentes\s+)?(?:diligencias|actuaciones|incidente|expediente)|\bterminar?\b[^.\n]{0,20}\bincidente|\bterminaci[óo]n\s+(?:del?\s+)?incidente|\bcerrar?\b[^.\n]{0,20}\bincidente|\bcl[áa]usura\s+(?:del?\s+)?incidente|\bauto\s+(?:que\s+)?(?:archiva|termina|cierra)")),
    ("EN_TRAMITE",     re.compile(r"(?i)\bapertur\w+\s+(?:formal\s+)?(?:del?\s+)?incidente|\babr[ií]r?\s+(?:el\s+)?incidente|\brequer\w+\s+previo|\bauto\s+(?:que\s+)?(?:abre|apertura|requiere|admite)\b|\bcorrer?\s+traslado|\bdecretar?\s+pruebas|\bauto\s+(?:de\s+)?pruebas")),
)
# Nombre del responsable del desacato — "contra/a [NOMBRE]" / "REQUERIR a [NOMBRE]"
_RE_RESPONSABLE_DESACATO = re.compile(
    r"(?is)(?:"
    r"(?:incidente\s+de\s+desacato|aper(?:t|c)ur\w+\s+(?:formal\s+)?(?:del?\s+)?incidente)\s+(?:de\s+desacato\s+)?(?:en\s+)?contra\s+(?:de(?:l)?\s+)?(?:la\s+|el\s+)?(?:se[ñn]ora?\s+|doctora?\s+|dra?\.?\s+|funcionari[oa]\s+)?"
    r"|requerir\s+(?:a\s+)?(?:la\s+|el\s+|los\s+)?(?:se[ñn]ora?\s+|doctora?\s+|dra?\.?\s+)?"
    r"|sancionar?\s+(?:por\s+desacato\s+)?(?:a\s+)?(?:la\s+|el\s+|los\s+)?(?:ciudadan[oa]\s+|se[ñn]ora?\s+|doctora?\s+|dra?\.?\s+|funcionari[oa]\s+)?"
    r"|abstenerse\s+de\s+(?:imponer\s+sanci\w+\s+(?:en\s+contra\s+de|a)\s+|sancionar?\s+(?:por\s+desacato\s+)?(?:a\s+))(?:la\s+|el\s+)?(?:ciudadan[oa]\s+|se[ñn]ora?\s+|doctora?\s+|dra?\.?\s+)?"
    r"|vincular?\s+(?:al?\s+)?(?:incidente\s+)?(?:de\s+desacato\s+)?(?:al?\s+|a\s+l[ao]s?\s+)?(?:se[ñn]ora?\s+|doctora?\s+|dra?\.?\s+)?"
    r")"
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ.\s]{6,70}?)(?=\s*(?:,|\.|;|\bidentificad|\bC\.?C\.?|\bc[ée]dula|\ben\s+su\s+calidad|\ben\s+calidad|\bpara\s+que|\by\s+(?:a\s+)?su\s+superior|\bquien\b|$))"
)


def _classify_decision_incidente(text: str) -> Optional[str]:
    if not text:
        return None
    for tag, pat in _DECISION_INC_PATTERNS:
        if pat.search(text):
            return tag
    return None


def _clean_responsable_desacato(raw: str, doc_text: str = "") -> Optional[str]:
    """Limpia y normaliza el responsable_desacato = la AUTORIDAD/PERSONA NOMBRADA en
    el incidente (contra quien va el desacato y sobre quien recaería la sanción).

    CORRECCIÓN 2026-06-02 (Wilson): responsable_desacato NO es el abogado — es el
    sancionado: el Gobernador, la Secretaria de Educación, un rector, etc. (lo que el
    auto requiere/sanciona). El abogado que proyecta la respuesta al desacato va en la
    casilla aparte `abogado_incidente`. Antes este helper validaba contra el catálogo
    de 17 abogados y rechazaba las instituciones — exactamente al revés.

    Normaliza autoridades comunes a su forma canónica; conserva rectores / nombres
    propios / otras entidades en MAYÚSCULAS. `doc_text` ya no se usa (queda por compat).
    """
    if not raw:
        return None
    v = re.sub(r"\s+", " ", raw).strip(" ,.;:-").strip()
    v = re.sub(r"(?i)^(?:se[ñn]ora?\s+|doctora?\s+|dra?\.?\s+|funcionari[oa]\s+|ciudadan[oa]\s+"
               r"|al?\s+|el\s+|la\s+|los\s+|las\s+|lo\s+)+", "", v).strip()
    if not (4 <= len(v) <= 80):
        return None
    f = _fold(v)
    # Autoridades SED/Gobernación → forma canónica del cuadro.
    if "secretaria de educacion" in f or ("secretaria" in f and "educacion" in f):
        return "SECRETARÍA DE EDUCACIÓN DE SANTANDER"
    if "gobernacion" in f or "departamento de santander" in f or "gobernador" in f:
        return "GOBERNACIÓN DE SANTANDER"
    # Boilerplate del auto capturado sin entidad real → None ("PREVIA APERTURA FORMAL
    # INCIDENTE…", "LAS MENCIONADAS EN EL NUMERAL ANTERIOR…", "PARA QUE…").
    if re.search(r"\b(?:apertura|incidente|desacato|mencionad|numeral|anterior|previa|"
                 r"requerimiento|cumplimiento|para que|providencia|t[ée]rmino|"
                 r"accionad[oa]s?|vinculad[oa]s?|entidades|responsabl\w*|encargad[oa]s?|"
                 r"persona\s+encargada|superior\s+jer[áa]rquic|qued[óo])\b", f):
        return None
    # Rechazar SOLO si el valor es puramente un conector (no un nombre que empieza por él).
    if re.fullmatch(r"(?i)(?:para que|que|de la|del|al|y|en su)\s*", v):
        return None
    # Guard anti-fragmento: una entidad/nombre real tiene ≥1 palabra de ≥4 letras.
    # Capturas malformadas del regex tipo "AL MR. GR" (solo iniciales/abreviaturas ≤3
    # letras) son basura y NO deben persistirse (caso c92/c230, 2026-06-02).
    if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", v):
        return None
    # Rector / institución / nombre propio del funcionario sancionado → conservar.
    return v.upper()[:80]


def extract_incidentes_cluster_for_case(db: Session, case: Case) -> dict:
    """Devuelve dict con los 12 campos de incidentes (3 slots × {flag, fecha_apertura,
    responsable_desacato, decision}). Slots vacíos → flag="NO", el resto None."""
    out = {
        "incidente": "NO", "fecha_apertura_incidente": None, "responsable_desacato": None, "decision_incidente": None,
        "incidente_2": "NO", "fecha_apertura_incidente_2": None, "responsable_desacato_2": None, "decision_incidente_2": None,
        "incidente_3": "NO", "fecha_apertura_incidente_3": None, "responsable_desacato_3": None, "decision_incidente_3": None,
        "_n_incidentes": 0,
    }
    docs = db.query(Document).filter(Document.case_id == case.id).all()
    inc_escritos = [d for d in docs if d.doc_type == "INCIDENTE_DESACATO" and (d.extracted_text or "") and len(d.extracted_text) > 200]
    autos_inc = [d for d in docs if d.doc_type == "AUTO_INCIDENTE" and (d.extracted_text or "") and len(d.extracted_text) > 200]
    emails = [d for d in docs if d.doc_type in ("EMAIL_JUDICIAL", "EMAIL_INTERNO")]
    email_heads: list[str] = []
    for d in emails:
        t = _read_doc_text(d)
        if t:
            email_heads.append((t[:1200], getattr(getattr(d, "email", None), "date_received", None) or None, t))
    email_subjects = [(e.subject or "", e.date_received) for e in db.query(Email).filter(Email.case_id == case.id).all() if e.subject]

    # ¿hay señal de incidente?
    has_signal = bool(inc_escritos) or bool(autos_inc)
    if not has_signal:
        for h, _d, _t in email_heads:
            if _RE_INCIDENTE_SIGNAL.search(h):
                has_signal = True
                break
        if not has_signal:
            for s, _d in email_subjects:
                if _RE_INCIDENTE_SIGNAL.search(s):
                    has_signal = True
                    break
    if not has_signal:
        return out

    # nº de incidentes ≈ nº de escritos distintos (por fecha); si 0, asumimos 1
    yh = _rad_year(case)
    f1 = _parse_ddmmyyyy(getattr(case, "fecha_fallo_1st", None))

    def _fecha_de_doc(text: str) -> Optional[str]:
        # dateline del doc o cualquier fecha en las primeras ~1500 chars, cota año rad±2 y ≥ fallo_1st
        for _pos, v in _parse_es_dates(text[:1500]):
            if yh is not None:
                try:
                    if abs(int(v[-4:]) - yh) > 2:
                        continue
                except ValueError:
                    continue
            if f1:
                dv = _parse_ddmmyyyy(v)
                if dv and dv < f1:
                    continue
            return v
        return None

    # Contar incidentes DISTINTOS = por fecha de apertura única (varios escritos con la
    # MISMA fecha = el mismo incidente, no varios). Si no hay ninguno con fecha → 1 incidente
    # (existe pero indatado).
    def _key(s: str):
        try:
            dd, mm, yy = s.split("/")
            return (int(yy), int(mm), int(dd))
        except Exception:
            return (9999, 99, 99)
    # Solo los ESCRITOS de incidente cuentan como "incidentes distintos" (las múltiples
    # actuaciones — auto previo, auto que decide — son ETAPAS de uno, no incidentes nuevos).
    # Dedup por fecha de presentación; si dos escritos tienen la misma fecha → mismo incidente.
    by_date: dict[str, Document] = {}
    for d in inc_escritos:
        fd = _fecha_de_doc(d.extracted_text)
        if fd and fd not in by_date:
            by_date[fd] = d
        elif not fd and "__sin_fecha__" not in by_date:
            by_date["__sin_fecha__"] = d
    dated_all = sorted([(k, v) for k, v in by_date.items() if k != "__sin_fecha__"], key=lambda x: _key(x[0]))
    # Colapsar fechas cercanas (≤ 21 días = etapas del mismo incidente, no incidentes nuevos):
    # un "segundo incidente" se abre semanas después del primero (nuevo desacato del mismo fallo).
    dated: list[tuple[str, Document]] = []
    for fd, d in dated_all:
        if not dated:
            dated.append((fd, d))
            continue
        prev = _parse_ddmmyyyy(dated[-1][0])
        cur = _parse_ddmmyyyy(fd)
        if prev and cur and (cur - prev).days <= 21:
            continue  # mismo incidente, distinta etapa
        dated.append((fd, d))
    if not dated and "__sin_fecha__" in by_date:
        dated = [("9999/99/9999", by_date["__sin_fecha__"])]
    elif not dated:
        # sin escritos archivados (señal solo de email/auto) → 1 incidente, sin doc representativo
        dated = [("9999/99/9999", inc_escritos[0] if inc_escritos else (autos_inc[0] if autos_inc else None))]
    escrito_dates = dated[:3]  # como máximo 3 slots
    n_inc = max(1, min(3, len(escrito_dates)))
    out["_n_incidentes"] = n_inc

    # decisión: del AUTO que decide el incidente, leyendo su zona dispositiva (RESUELVE).
    # El auto puede estar etiquetado AUTO_INCIDENTE o (mal) INCIDENTE_DESACATO — lo
    # reconocemos por "auto" en el nombre del archivo (los ESCRITOS incidentales del
    # accionante no lo llevan). Se prefiere una decisión TERMINAL (sanción/archivo/cierre)
    # sobre una de mera apertura/trámite, y entre terminales la del auto más reciente
    # (los operadores numeran los docs cronológicamente: 03_, 07_, 10_…).
    deciding_docs = list(autos_inc) + [d for d in inc_escritos if "auto" in (d.filename or "").lower()]
    deciding_docs.sort(key=lambda d: (d.filename or ""))
    decision_global = None
    for d in deciding_docs:
        zone = _last_resuelve_zone(d.extracted_text) or d.extracted_text[:2000]
        dec = _classify_decision_incidente(zone)
        if dec and dec != "EN_TRAMITE":
            decision_global = dec  # sin break: nos quedamos con la última (más reciente) terminal
    if not decision_global:
        for d in deciding_docs:
            zone = _last_resuelve_zone(d.extracted_text) or d.extracted_text[:2000]
            dec = _classify_decision_incidente(zone)
            if dec:
                decision_global = dec
                break
    if not decision_global:
        # buscar pistas en subjects/heads de emails
        for src in [s for s, _d in email_subjects] + [h for h, _d, _t in email_heads]:
            dec = _classify_decision_incidente(src)
            if dec:
                decision_global = dec
                break
    if not decision_global:
        decision_global = "EN_TRAMITE"  # hay incidente pero sin auto que lo decida → en trámite

    # responsable: del escrito de incidente / AUTO / email body — buscar el primero que matchee.
    # Pasa el doc_text al cleaner para habilitar match-por-correo en el roster (paso 1
    # del _resolve_abogado_combined). Regla c456: solo se acepta canónico/roster; el
    # cargo "Secretaria de Educación" o "Gobernador" → None (no es responsable jurídico).
    resp_global = None
    for d in (inc_escritos + autos_inc):
        t = d.extracted_text[:8000]
        m = _RE_RESPONSABLE_DESACATO.search(t)
        if m:
            r = _clean_responsable_desacato(m.group(1), doc_text=t)
            if r:
                resp_global = r
                break
    if not resp_global:
        for h, _d, t in email_heads:
            head = t[:8000]
            m = _RE_RESPONSABLE_DESACATO.search(head)
            if m:
                r = _clean_responsable_desacato(m.group(1), doc_text=head)
                if r:
                    resp_global = r
                    break
    # Nota: antes había aquí un default "SECRETARIO DE EDUCACIÓN DEPARTAMENTAL DE
    # SANTANDER" cuando decision_global ∈ {SANCIONA, NO_SANCIONA}. Eliminado porque
    # introducía un cargo no-canónico que la auditoría (audit_responsables_canonicos.py)
    # marca como INSTITUCIONAL. Si el responsable canónico no se puede identificar,
    # dejar None es preferible (regla c456 + feedback_abogado_responsable).

    # fecha de apertura del incidente 1: la del 1er escrito, o del email "apertura incidente", o None
    fecha_inc1 = escrito_dates[0][0] if escrito_dates and escrito_dates[0][0] != "9999/99/9999" else None
    if not fecha_inc1:
        for s, dr in email_subjects:
            if dr and _RE_INCIDENTE_SIGNAL.search(s):
                try:
                    cand = dr.strftime("%d/%m/%Y")
                    cdv = _parse_ddmmyyyy(cand)
                    if (not f1 or (cdv and cdv >= f1)):
                        fecha_inc1 = cand
                        break
                except Exception:
                    pass

    # slot 1 (siempre, ya que has_signal)
    out["incidente"] = "SI"
    out["fecha_apertura_incidente"] = fecha_inc1
    out["responsable_desacato"] = resp_global
    out["decision_incidente"] = decision_global
    # slots 2 y 3 — solo si hay ≥2 / ≥3 escritos distintos con fecha
    if len(escrito_dates) >= 2:
        out["incidente_2"] = "SI"
        out["fecha_apertura_incidente_2"] = escrito_dates[1][0] if escrito_dates[1][0] != "9999/99/9999" else None
        # responsable/decision por slot: best-effort del 2do escrito
        t2 = escrito_dates[1][1].extracted_text[:8000]
        m = _RE_RESPONSABLE_DESACATO.search(t2)
        out["responsable_desacato_2"] = _clean_responsable_desacato(m.group(1), doc_text=t2) if m else None
        # FIX 2026-06-02: derivar la decisión del doc del slot (SANCIONA/CIERRA/etc.)
        # si tiene marcador; antes estaba hardcoded a EN_TRAMITE → falso ACTIVO.
        out["decision_incidente_2"] = _classify_decision_incidente(t2) or "EN_TRAMITE"
    if len(escrito_dates) >= 3:
        out["incidente_3"] = "SI"
        out["fecha_apertura_incidente_3"] = escrito_dates[2][0] if escrito_dates[2][0] != "9999/99/9999" else None
        t3 = escrito_dates[2][1].extracted_text[:8000]
        m = _RE_RESPONSABLE_DESACATO.search(t3)
        out["responsable_desacato_3"] = _clean_responsable_desacato(m.group(1), doc_text=t3) if m else None
        out["decision_incidente_3"] = _classify_decision_incidente(t3) or "EN_TRAMITE"
    return out


# ============================================================
# ESTADO (ACTIVO/INACTIVO) + FECHA_RESPUESTA  (campo 17)
# ============================================================

def extract_estado_for_case(db: Session, case: Case) -> str:
    """`estado` ∈ {ACTIVO, INACTIVO}. Derivado de los campos ya extraídos
    (decisión del usuario): INACTIVO si hay fallo de 1ra Y (no hay impugnación, o la
    2da ya falló) Y (no hay incidente, o el/los incidente(s) ya se decidieron — no
    EN_TRAMITE). ACTIVO en cualquier otro caso (sin fallo aún, impugnación en curso,
    o incidente EN_TRAMITE)."""
    sentido1 = getattr(case, "sentido_fallo_1st", None)
    if (sentido1 or "").upper() == "DESISTIMIENTO":
        return "INACTIVO"  # desistimiento aceptado termina el proceso (art. 26 D2591/91)
    if not sentido1:
        return "ACTIVO"  # sin fallo de 1ra (en curso, o no archivado → tratar como pendiente)
    impug = (getattr(case, "impugnacion", "") or "").upper()
    sentido2 = getattr(case, "sentido_fallo_2nd", None)
    # NULIDAD de 2da REABRE el proceso (el superior anula lo actuado sin decidir el mérito)
    # → ACTIVO hasta que un NUEVO fallo de mérito lo concluya (al capturarlo, sentido_fallo_2nd
    # deja de ser NULIDAD y estado re-deriva a INACTIVO). Regla del usuario; determinista.
    if (sentido2 or "").upper() in ("NULIDAD", "DECLARA_NULIDAD"):
        return "ACTIVO"
    if impug == "SI" and not sentido2:
        return "ACTIVO"  # impugnación interpuesta, 2da aún sin fallo
    for n in ("", "_2", "_3"):
        if (getattr(case, f"incidente{n}", "") or "").upper() == "SI":
            d = getattr(case, f"decision_incidente{n}", None)
            if not d or str(d).upper() == "EN_TRAMITE":
                return "ACTIVO"  # incidente de desacato abierto sin decidir
    return "INACTIVO"


_RESPUESTA_DOC_TYPES = frozenset({"RESPUESTA", "DOCX_RESPUESTA", "RESPUESTA_SED"})


def _is_respuesta_doc(d: Document) -> bool:
    """True si el documento es (o parece) un oficio de respuesta/contestación.

    Robusto ante misclasificación: el clasificador por-filename a veces deja los PDF
    de respuesta como PDF_OTRO/DESCONOCIDO (no tenía regla 'respuesta' para PDFs),
    así que se reconoce por doc_type de respuesta O por nombre de archivo. Se
    excluyen los correos (EMAIL*): un "Email_..._RESPUESTA..." es la notificación,
    no el oficio (su fecha la maneja el fallback por email)."""
    dt = d.doc_type or ""
    if dt.startswith("EMAIL") or "INCIDENTE" in dt or "DESACATO" in dt:
        return False
    if dt in _RESPUESTA_DOC_TYPES:
        return True
    fn = (d.filename or "").lower()
    if "incidente" in fn or "desacato" in fn:
        return False
    return ("respuesta" in fn) or ("contesta" in fn)


# Marcadores de contexto cuya fecha NO es la del oficio sino boilerplate:
#  - "FECHA DE APROBACIÓN" del formato (p.ej. 11/04/2024 de AP-AI-RG-110) → caso 397.
#  - nombramiento/posesión de la Secretaria ("Decreto número 562 del 27 de octubre de
#    2025 y acta de posesión No 216 del 04 de noviembre...") que aparece en toda
#    respuesta SED → caso 72 (daba 27/10/2025).
_TEMPLATE_DATE_MARKERS = (
    "aprobaci", "versi", "codig", "vigencia",
    "decreto", "posesi", "nombramiento", "acta de",
)


def extract_fecha_respuesta_for_case(db: Session, case: Case) -> tuple[Optional[str], str]:
    """`fecha_respuesta` = fecha del oficio de respuesta de la SED (dateline "Ciudad, DD
    de MMMM de AAAA" o header de email "Fecha … DD/MM/AAAA"). Si hay varias respuestas,
    la más temprana (la contestación inicial). Solo se aceptan fechas con ancla de
    dateline (coma de ciudad o "fecha") → descarta fechas de nombramiento/decreto
    ("…del 27 de octubre…") y de plantilla ("FECHA DE APROBACIÓN"). Cotas: año entre
    rad23-1 y el año actual+1 (una respuesta puede llegar años después en casos viejos
    con desacatos) y fecha ≥ fecha_ingreso. Fallback: `date_received` del email .md cuyo
    subject es "RESPUESTA … TUTELA …".
    Returns (valor, fuente) — fuente ∈ {"docx_respuesta","email","none"}."""
    yh = _rad_year(case)
    fi = _parse_ddmmyyyy(getattr(case, "fecha_ingreso", None))
    _now_y = date.today().year

    def _ok(v: str) -> bool:
        try:
            vy = int(v[-4:])
        except ValueError:
            return False
        if yh is not None and (vy < yh - 1 or vy > _now_y + 1):
            return False
        if fi:
            dv = _parse_ddmmyyyy(v)
            if dv and dv < fi:
                return False
        return True

    def _key(v: str):
        try:
            dd, mm, yy = v.split("/")
            return (int(yy), int(mm), int(dd))
        except Exception:
            return (9999, 99, 99)

    # 1) datelines de los oficios de respuesta → la fecha más temprana válida.
    #    Selección robusta vía _is_respuesta_doc (no depende de doc_type=="RESPUESTA"
    #    exacto; un PDF de respuesta mal etiquetado PDF_OTRO también cuenta).
    #    Para cada fecha exigimos un ANCLA de dateline:
    #      - coma justo antes ("Bucaramanga, 22 de mayo…") → oficio, o
    #      - "fecha" en el contexto ("Fecha Vie 22/05/2026") → header de email.
    #    y descartamos las precedidas por marcadores de plantilla/nombramiento. Así no
    #    se cuela "…del 27 de octubre de 2025" (decreto) ni "FECHA DE APROBACIÓN".
    cands: list[str] = []
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        if not _is_respuesta_doc(d):
            continue
        t = d.extracted_text or ""
        if not t or len(t) < 200:
            continue
        head = t[:1500]
        head_l = head.lower()
        for _pos, v in _parse_es_dates(head):
            ctx = head_l[max(0, _pos - 40):_pos]
            if any(mk in ctx for mk in _TEMPLATE_DATE_MARKERS):
                continue  # fecha de plantilla/nombramiento, no del oficio
            near = head_l[max(0, _pos - 4):_pos]
            if ("," not in near) and ("fecha" not in ctx):
                continue  # sin ancla de dateline (ciudad+coma) ni header de email
            if _ok(v):
                cands.append(v)
                break  # solo el primer dateline de cada oficio
    if cands:
        return min(cands, key=_key), "docx_respuesta"

    # 2) fallback: email .md "RESPUESTA … TUTELA …" → su date_received
    _RE_RESP_SUBJ = re.compile(r"(?i)\brespuesta\b[^|\n]{0,60}?\b(?:tutela|acci[óo]n\s+de\s+tutela|auto\s+(?:de\s+traslado|admisori\w+)|requerimiento)|\bcontestaci[óo]n\b[^|\n]{0,40}?tutela")
    best: Optional[str] = None
    for e in db.query(Email).filter(Email.case_id == case.id).order_by(Email.date_received.asc()).all():
        s = e.subject or ""
        if s and _RE_RESP_SUBJ.search(s) and e.date_received:
            try:
                v = e.date_received.strftime("%d/%m/%Y")
                if _ok(v):
                    best = v
                    break
            except Exception:
                pass
    if not best:
        # también en los heads de los .md
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type.in_(["EMAIL_JUDICIAL", "EMAIL_INTERNO"])).all():
            t = _read_doc_text(d)
            if not t:
                continue
            if _RE_RESP_SUBJ.search(t[:600]):
                dr = getattr(getattr(d, "email", None), "date_received", None)
                if dr:
                    try:
                        v = dr.strftime("%d/%m/%Y")
                        if _ok(v):
                            best = v
                            break
                    except Exception:
                        pass
    if best:
        return best, "email"
    return None, "none"


# ============================================================
# CATEGORIA_TEMATICA + OBSERVACIONES  (campo 18 — los últimos del cuadro)
# ============================================================
#
# Decisiones del usuario:
#  - `categoria_tematica` = agrupación temática (grupo L2 de la SED) DERIVADA del
#    `asunto` ya extraído (`legal_schema.categoria_tematica_de_asunto`). Capa
#    intermedia entre `asunto` (acción concreta: TRASLADO) y `oficina_responsable`
#    (Dirección L1). No usa LLM ni lee docs nuevos — 1 autoridad por campo.
#  - `observaciones` = texto libre (lo edita la coordinadora). v9 lo SIEMBRA con
#    notas estructuradas, append-only e idempotente: la nota de agente oficioso /
#    personería (la pone el campo 4 ACCIONANTE) + un par de banderas de alto valor
#    detectadas sobre el escrito de tutela: "se solicitó medida provisional" y
#    "sujeto de especial protección: <menor|discapacidad|adulto mayor|gestante>".
#    NO se sacan de los subjects de los emails (URGENTE / perjuicio irremediable son
#    boilerplate de toda tutela → ruido).

CATEGORIA_TEMATICA_SIN_DETERMINAR = "SIN_DETERMINAR"


def extract_categoria_tematica_for_case(db: Session, case: Case) -> tuple[str, str]:
    """`categoria_tematica` derivada del `asunto`. Returns (valor, fuente) con
    fuente ∈ {"asunto","default"}."""
    asunto = (getattr(case, "asunto", "") or "").strip()
    if asunto:
        try:
            from backend.cognition.legal_schema import categoria_tematica_de_asunto
            cat = categoria_tematica_de_asunto(asunto)
            if cat:
                return cat, "asunto"
        except Exception:
            pass
    return CATEGORIA_TEMATICA_SIN_DETERMINAR, "default"


# Escritos de PARTE (donde el accionante pide la medida provisional / se identifica
# como sujeto de especial protección). No los autos/sentencias (el juez decide la
# medida con frases boilerplate; "menor"/"discapacidad" en jurisprudencia citada).
_OBS_DOC_TYPES = ("DEMANDA_TUTELA", "ANEXO_DEMANDA", "IMPUGNACION", "INCIDENTE_DESACATO")

_RE_OBS_MEDIDA_PROVISIONAL = re.compile(
    r"(?i)\bmedida(?:s)?\s+provisional(?:es)?\b|\bcomo\s+medida\s+provisional\b"
    r"|\bsuspensi[óo]n\s+provisional\b\s+del?\s+acto"
)

# Banderas de sujeto de especial protección (regex conservadoras: solo frases fuertes)
_RE_OBS_SEP: tuple[tuple[str, re.Pattern], ...] = (
    ("persona con discapacidad", re.compile(
        r"(?i)\b(?:persona|condici[óo]n|situaci[óo]n)\s+(?:con|de|en)\s+discapacidad\b"
        r"|\bdiscapacidad\s+(?:f[íi]sica|cognitiva|mental|sensorial|m[úu]ltiple|intelectual|auditiva|visual)\b"
        r"|\bs[íi]ndrome\s+de\s+down\b|\btrastorno\s+del\s+espectro\s+autista\b|\bautismo\b|\binvidente\b")),
    ("menor de edad", re.compile(
        r"(?i)\bmenor(?:es)?\s+de\s+edad\b|\binter[ée]s\s+superior\s+(?:del?\s+)?(?:menor|ni[ñn][oa])\b"
        r"|\bN\.?\s?N\.?\s?A\.?\b|\bhij[oa]\s+menor\b|\ben\s+representaci[óo]n\s+de\s+su\s+hij[oa]\b")),
    ("adulto mayor / tercera edad", re.compile(
        r"(?i)\badult[oa]\s+mayor\b|\btercera\s+edad\b|\bpersona\s+de\s+la\s+tercera\s+edad\b")),
    ("mujer gestante / en embarazo", re.compile(
        r"(?i)\bgestante\b|\ben\s+estado\s+de\s+(?:embarazo|gestaci[óo]n)\b|\bmujer\s+embarazada\b"
        r"|\bfuero\s+de\s+maternidad\b|\blicencia\s+de\s+maternidad\b")),
)


def extract_observaciones_for_case(db: Session, case: Case) -> list[str]:
    """Banderas estructuradas a sembrar en `observaciones` (además de la nota de
    agente oficioso/personería que pone el campo 4). Lista de strings; el caller las
    anexa a `case.observaciones` solo si no están ya (idempotente). Vacía si nada."""
    medida = False
    sep_labels: list[str] = []
    for dt in _OBS_DOC_TYPES:
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            t = _read_doc_text(d)
            if not t or len(t) < 200:
                continue
            head = t[:12000]
            if _RE_OBS_MEDIDA_PROVISIONAL.search(head):
                medida = True
            for label, rx in _RE_OBS_SEP:
                if label not in sep_labels and rx.search(head):
                    sep_labels.append(label)
    flags: list[str] = []
    if medida:
        flags.append("Se solicitó medida provisional")
    if sep_labels:
        flags.append("Sujeto de especial protección: " + ", ".join(sep_labels))
    return flags


# ── observaciones: resumen narrativo del caso vía LLM (append-only, fechado) ──
# El campo `observaciones` se construye en capas: banderas (arriba) + una o varias
# líneas "[DD/MM/AAAA] <resumen>". Cuando llega una actuación nueva, el caller añade
# una línea nueva con su fecha SIN borrar las anteriores (contexto acumulado).

_OBS_SUMMARY_DOCTYPES_DEMANDA = ("DEMANDA_TUTELA", "ANEXO_DEMANDA")
_OBS_SUMMARY_DOCTYPES_FALLO = ("SENTENCIA_1RA", "SENTENCIA_2DA", "AUTO_INCIDENTE", "INCIDENTE_DESACATO")
_RE_OBS_LINE = re.compile(r"^\s*\[\d{1,2}/\d{1,2}/\d{4}\]", re.M)  # detecta si ya hay una línea fechada


def case_has_dated_observacion(case: Case) -> bool:
    """True si `observaciones` ya tiene al menos una línea '[DD/MM/AAAA] ...' (resumen LLM)."""
    return bool(_RE_OBS_LINE.search(case.observaciones or ""))


def _doc_head(db: Session, case: Case, doctypes: tuple[str, ...], n: int) -> str:
    for dt in doctypes:
        for d in db.query(Document).filter(Document.case_id == case.id, Document.doc_type == dt).all():
            t = _read_doc_text(d)
            if t and len(t) >= 200:
                return t[:n]
    return ""


def llm_summarize_case_state(db: Session, case: Case) -> Optional[str]:
    """Resumen factual (2-3 frases, español) del estado de la tutela vía LLM local.

    Se construye SOLO con los campos ya extraídos + un fragmento de la demanda/fallo.
    El LLM no inventa: si los datos son pobres devuelve None. Respeta V9_DISABLE_LLM.
    """
    if os.getenv("V9_DISABLE_LLM", "false").lower() == "true":
        return None
    parts: list[str] = []

    def _add(label: str, val) -> None:
        v = (str(val or "")).strip()
        if v:
            parts.append(f"{label}: {v}")

    _add("Accionante", case.accionante)
    _add("Accionados", case.accionados)
    _add("Derecho(s) invocado(s)", (case.derecho_vulnerado or "").replace(" - ", ", "))
    _add("Asunto", case.asunto)
    _add("Pretensiones (extracto)", (case.pretensiones or "")[:400])
    _add("Fallo 1ª instancia", case.sentido_fallo_1st)
    _add("Fecha fallo 1ª instancia", case.fecha_fallo_1st)
    impg = f"{case.impugnacion or ''} {('por ' + case.quien_impugno) if case.quien_impugno else ''}".strip()
    _add("Impugnación", impg)
    _add("Fallo 2ª instancia", case.sentido_fallo_2nd)
    _add("Incidente de desacato", case.incidente)
    _add("Decisión del incidente", case.decision_incidente)
    _add("Estado", case.estado)
    demanda = _doc_head(db, case, _OBS_SUMMARY_DOCTYPES_DEMANDA, 1400)
    fallo = _doc_head(db, case, _OBS_SUMMARY_DOCTYPES_FALLO, 900)
    if len(parts) < 2 and not demanda and not fallo:
        return None  # datos demasiado pobres para un resumen útil

    ctx = "\n".join(parts)
    if demanda:
        ctx += f"\n\n--- Extracto del escrito de tutela ---\n{demanda}"
    if fallo:
        ctx += f"\n\n--- Extracto del fallo/incidente ---\n{fallo}"

    prompt = (
        "/no_think\n"
        "Eres un asistente jurídico de la Secretaría de Educación. Con base ÚNICAMENTE en los "
        "datos de abajo, escribe en español 2 o 3 frases factuales que resuman esta acción de "
        "tutela: (1) qué solicita el accionante, (2) qué se ha decidido (fallo de 1ª o 2ª "
        "instancia, incidente de desacato) si lo hay, y (3) en qué va el trámite. "
        "No inventes nada que no esté en los datos. No repitas el radicado. No uses viñetas ni "
        "encabezados. Si no hay información suficiente, responde exactamente: SIN_RESUMEN.\n\n"
        f"DATOS DEL EXPEDIENTE:\n{ctx[:5000]}"
    )
    msgs = [
        {"role": "system", "content": "Resumes expedientes de tutela en 2-3 frases factuales. No inventas."},
        {"role": "user", "content": prompt},
    ]
    try:
        from backend.extraction.ai_extractor import _call_local
        raw, _, _ = _call_local(msgs, "qwen3-4b-iuris", max_tokens=260)
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM observaciones falló para case=%d: %s", case.id, str(e)[:200])
        return None
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
    raw = re.sub(r"\s+", " ", raw).strip().strip('"').strip()
    if not raw or len(raw) < 25 or re.fullmatch(r"(?i)sin[_ ]resumen\.?", raw):
        return None
    if len(raw) > 700:
        cut = raw[:700]
        last = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        raw = (cut[:last + 1] if last > 200 else cut).strip()
    return raw
