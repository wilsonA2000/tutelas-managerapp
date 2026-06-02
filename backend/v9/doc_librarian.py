"""Etapa 1.5 — Bibliotecario RAG: clasificación, pertenencia e integridad.

Esta capa corre ENTRE `doc_io` y `regex_pass`. Sin saneamiento previo, los
campos extraídos pueden contaminarse con datos de docs mal ubicados.

Responsabilidades (en orden):

  1. CLASIFICA cada doc por contenido real (no solo filename) → 16 doctypes.
  2. VERIFICA pertenencia al caso comparando rad23 extraído vs folder.
  3. AUDITA la integridad del expediente (cardinalidad + cronología).
  4. PROPONE acciones (sin ejecutarlas: mover, eliminar duplicados, etc.).

Se INTEGRA con el sistema existente de la plataforma:
  - `Document.verificacion` (estado: OK / SOSPECHOSO / NO_PERTENECE / REVISAR)
  - `services/sibling_mover.move_document_or_package` (re-ubicación)
  - `routers/cleanup.py` (UI de docs sospechosos)

NO ejecuta movimientos automáticos. Solo reporta. El usuario decide en la UI.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from backend.v9.doc_io import DocText

logger = logging.getLogger("tutelas.v9.librarian")


# ============================================================
# TAXONOMÍA — 16 tipos de doc esperables en un expediente de tutela
# ============================================================

class DocType(str, Enum):
    # Fase pre-judicial
    DEMANDA_TUTELA      = "DEMANDA_TUTELA"        # escrito de tutela del accionante
    ANEXO_DEMANDA       = "ANEXO_DEMANDA"         # certificados, soportes adjuntos a la demanda

    # Fase 1ra instancia
    AUTO_ADMISORIO      = "AUTO_ADMISORIO"        # 🔴 OBLIGATORIO — juzgado avoca/admite
    NOTIFICACION        = "NOTIFICACION"          # juzgado notifica a partes
    RESPUESTA           = "RESPUESTA"             # contestación de la Gobernación (varias posibles)
    SENTENCIA_1RA       = "SENTENCIA_1RA"         # fallo 1ra instancia
    NOTIFICACION_FALLO  = "NOTIFICACION_FALLO"    # notificación del fallo

    # Fase 2da instancia (impugnación)
    IMPUGNACION             = "IMPUGNACION"             # recurso vs sentencia
    AUTO_CONCEDE_IMPUGNACION = "AUTO_CONCEDE_IMPUGNACION"  # auto del juez de 1ra concediendo
    AUTO_2DA                = "AUTO_2DA"                # auto del juez de 2da que avoca
    SENTENCIA_2DA           = "SENTENCIA_2DA"           # fallo de 2da

    # Fase ejecución
    OFICIO_CUMPLIMIENTO  = "OFICIO_CUMPLIMIENTO"  # exigencia de cumplir fallo
    INCIDENTE_DESACATO   = "INCIDENTE_DESACATO"   # apertura incidente
    AUTO_INCIDENTE       = "AUTO_INCIDENTE"       # decisión sobre incidente

    # Comunicación
    EMAIL_JUDICIAL       = "EMAIL_JUDICIAL"       # email del juzgado / @ramajudicial
    EMAIL_INTERNO        = "EMAIL_INTERNO"        # email entre dependencias SED

    # Otros
    DESCONOCIDO          = "DESCONOCIDO"          # no clasificable con confianza


# Cardinalidad esperada por tipo de doc en una carpeta válida.
# (min, max_normal) — valores fuera de rango disparan anomalía.
EXPECTED_CARDINALITY: dict[DocType, tuple[int, Optional[int]]] = {
    DocType.DEMANDA_TUTELA:           (0, 2),    # escrito + a veces anexo separado
    DocType.ANEXO_DEMANDA:            (0, None), # sin tope
    DocType.AUTO_ADMISORIO:           (1, 1),    # 🔴 EXACTAMENTE 1 — anomalía si 0 o ≥2
    DocType.NOTIFICACION:             (0, None),
    DocType.RESPUESTA:                (0, None), # múltiples respuestas válidas (alcance, requerimientos)
    DocType.SENTENCIA_1RA:            (0, 1),
    DocType.NOTIFICACION_FALLO:       (0, None),
    DocType.IMPUGNACION:              (0, 2),    # cada parte puede impugnar
    DocType.AUTO_CONCEDE_IMPUGNACION: (0, 1),
    DocType.AUTO_2DA:                 (0, 1),
    DocType.SENTENCIA_2DA:            (0, 1),
    DocType.OFICIO_CUMPLIMIENTO:      (0, None),
    DocType.INCIDENTE_DESACATO:       (0, 3),    # hasta 3 incidentes
    DocType.AUTO_INCIDENTE:           (0, 3),    # uno por incidente
    DocType.EMAIL_JUDICIAL:           (0, None),
    DocType.EMAIL_INTERNO:            (0, None),
    DocType.DESCONOCIDO:              (0, None),
}


# ============================================================
# CLASIFICADOR MULTI-SEÑAL
# ============================================================

# Filename keywords — peso 30% del score final.
# Cada entry es una lista de "patterns" — pueden ser substrings o regex.
# Las claves más específicas se prueban primero.
_FILENAME_KEYWORDS: dict[DocType, tuple[str, ...]] = {
    # === Tipos MUY específicos (probar primero) ===
    DocType.AUTO_CONCEDE_IMPUGNACION: ("autoconcedeimpugnacion", "concedeimpugnacion", "auto concede impugnacion"),
    DocType.AUTO_2DA: ("autoadmiteimpugnacion", "auto admite impugnacion", "autoavocaimpugnacion", "auto avoca impugnacion"),
    DocType.SENTENCIA_2DA: (
        "sentenciasegundainstancia", "sentencia segunda instancia", "sentencia2da",
        "fallosegundainstancia", "fallo segunda instancia", "fallo2da",
        "anexofallosegundainstancia", "anexosentenciasegundainstancia",
        "tutela2dainstancia", "tutela segunda instancia",
    ),
    DocType.NOTIFICACION_FALLO: (
        "notificafallo", "notifica fallo", "notifica sentencia",
        "notificasentencia", "oficionotificasent", "oficio notifica sent",
        "notificacionfallo", "notificacion fallo", "notificación fallo",
        "notificacion sentencia", "notificación sentencia",
    ),
    DocType.AUTO_INCIDENTE: (
        "autodesacato", "auto desacato", "decideincidente", "decide incidente",
        "autodecideincidente", "autodecidedesacato", "providenciasanciona",
        "providencia sanciona", "sancionadesacato", "sanciona desacato",
        "autoincidente", "auto incidente",
    ),
    # === Tipos generales ===
    DocType.AUTO_ADMISORIO: (
        # Largos (más confianza)
        "autoadmitetutela", "auto admite tutela", "autoavocatutela", "auto avoca tutela",
        "auto admisorio", "admisoriotutela", "auto admis",
        # Medios
        "autoadmis", "autoavoca", "auto avoca", "avocatutela", "avoca tutela",
        "admisorio", "admitetutela", "admite tutela",
        # Cortos pero específicos del dominio (peligro mínimo de falso positivo)
        "admite", "admit", "avoca",
    ),
    DocType.NOTIFICACION: (
        "notificacion", "notificación", "oficionotifica", "oficio notifica",
        "notificaadmis", "notifica admis",
    ),
    DocType.RESPUESTA: (
        "respuesta", "contesta", "contestación", "alcance respuesta", "alcancerespuesta",
        "ampliacionrespuesta", "ampliacion respuesta", "ampliacionrta", "ampliacion rta",
        "con forest", "conforest",
    ),
    DocType.SENTENCIA_1RA: (
        "sentenciatutela", "sentencia tutela", "sentenciaprimera", "sentencia primera",
        "fallotutela", "fallo tutela", "primerainstancia", "primera instancia",
        "sentencia de tutela", "sentenciadepr",  # observados en corpus real
        "sentencia decide tutela", "sentenciadecidetutela",
        "sentencia",  # corto pero muy específico (acepta falsos positivos mitigados por _disambiguate)
        "fallo",
    ),
    DocType.IMPUGNACION: (
        "impugnafallo", "impugnación fallo", "impugnacionfallo",
        "escritoimpugna", "escrito impugna", "ampliaimpugnacion", "amplia impugnacion",
        "contestacionimpugnacion", "contestacion impugnacion",
        "impugna", "impugnacion", "impugnación",
    ),
    DocType.OFICIO_CUMPLIMIENTO: ("cumplimiento", "cumplim", "exigencia cumpl", "oficiocumplim"),
    DocType.INCIDENTE_DESACATO: (
        "abreincidente", "abre incidente", "aperturaincidente", "apertura incidente",
        "escritoincidente", "escrito incidente", "incidentedesacato", "incidente desacato",
        "incidente",
    ),
    DocType.DEMANDA_TUTELA: (
        "escritotutela", "escrito tutela", "escrito_tutela",
        "escritodetutela", "escrito de tutela",  # "EscritoDeTutela" (con "De") — c489
        "acciontutela", "accion_tutela", "acciondetutela", "accion de tutela",
        "demandatutela", "demanda_tutela", "demanda tutela", "demanda y anexos",
        "demanda", "01acciontutela",
    ),
    DocType.ANEXO_DEMANDA: ("anexodemanda", "anexo demanda", "anexosdemanda", "anexos demanda", "anexos"),
}


# Detección PRIMERO de email por filename antes de cualquier otra heurística.
# Cualquier doc cuyo filename empiece con "Email_" o sea .md → EMAIL_*.
def _is_email_filename(filename: str) -> bool:
    fn = filename.lower()
    return (
        fn.startswith("email_") or fn.startswith("email ") or
        fn.startswith("rv_") or fn.startswith("rv ") or
        fn.startswith("re_") or fn.startswith("re ") or
        fn.startswith("gmail") or
        fn.endswith(".md")
    )


def _is_email_internal(filename: str, text: str) -> bool:
    """Heurística: emails internos de la Gobernación (no del juzgado)."""
    fn_low = filename.lower()
    head = (text or "")[:1000].lower()
    if "apoyojuridico@santander" in head or "apoyojuridico" in fn_low:
        return True
    if "@santander.gov.co" in head and "ramajudicial" not in head and "cendoj" not in head:
        return True
    return False


# Frases ancla en HEADER (primeras 600 chars del texto) — peso 40%.
_HEADER_PATTERNS: dict[DocType, list[re.Pattern]] = {
    DocType.AUTO_ADMISORIO: [
        re.compile(r"(?i)\bAUTO\b.{0,80}\b(ADMITE|AVOCA|ADMISORIO)\b"),
        re.compile(r"(?i)\bAVOCA\s+CONOCIMIENTO\b"),
        re.compile(r"(?i)\bAVOQU[EÉ]SE\b"),
        re.compile(r"(?i)\bADM[ÍI]TASE\b"),
    ],
    DocType.SENTENCIA_1RA: [
        re.compile(r"(?i)\bSENTENCIA\b.{0,40}\b(TUTELA|PRIMERA\s+INSTANCIA)\b"),
        re.compile(r"(?i)\bSENTENCIA\s+No\.?\s*\d"),
        re.compile(r"(?i)\bFALLO\s+DE\s+TUTELA\b"),
    ],
    DocType.SENTENCIA_2DA: [
        re.compile(r"(?i)\bSENTENCIA.{0,30}SEGUNDA\s+INSTANCIA\b"),
        re.compile(r"(?i)\bACCION\s+DE\s+TUTELA.{0,30}SEGUNDA\s+INSTANCIA\b"),
    ],
    DocType.IMPUGNACION: [
        re.compile(r"(?i)\bIMPUGNAC[IÓO]N\b.{0,80}(FALLO|SENTENCIA|TUTELA)"),
        re.compile(r"(?i)\bRECURSO\s+DE\s+IMPUGNAC[IÓO]N\b"),
    ],
    DocType.AUTO_CONCEDE_IMPUGNACION: [
        re.compile(r"(?i)\bAUTO\b.{0,40}\bCONCEDE\b.{0,40}\bIMPUGNAC[IÓO]N\b"),
        re.compile(r"(?i)\bSE\s+CONCEDE\s+(?:EL\s+RECURSO\s+DE\s+)?IMPUGNAC[IÓO]N\b"),
    ],
    DocType.AUTO_2DA: [
        re.compile(r"(?i)\bAUTO\b.{0,40}\bADMITE\b.{0,40}\bIMPUGNAC[IÓO]N\b"),
        re.compile(r"(?i)\bAVOCA\b.{0,30}\bSEGUNDA\s+INSTANCIA\b"),
    ],
    DocType.RESPUESTA: [
        re.compile(r"(?i)\bCONTESTACI[ÓO]N\b.{0,30}\bACCI[ÓO]N\s+DE\s+TUTELA\b"),
        re.compile(r"(?i)\bRESPUESTA.{0,30}TUTELA\b"),
        re.compile(r"(?i)AL\s+RESPONDER\s+CITE\s+ESTE\s+NUMERO"),  # header estándar Gobernación
        re.compile(r"(?i)\bREF\s*[:\.]\s*RADICADO\b"),
    ],
    DocType.INCIDENTE_DESACATO: [
        re.compile(r"(?i)\bINCIDENTE\s+DE\s+DESACATO\b"),
        re.compile(r"(?i)\bAPER(?:T|C)URA\s+(?:DE\s+)?INCIDENTE\b"),
    ],
    DocType.AUTO_INCIDENTE: [
        re.compile(r"(?i)\bAUTO\b.{0,40}\bDESACATO\b"),
        re.compile(r"(?i)\bDECIDE\s+INCIDENTE\b"),
    ],
    DocType.NOTIFICACION: [
        re.compile(r"(?i)\bNOTIFIC[AOÓ]\b.{0,60}\b(ACCI[ÓO]N|TUTELA|FALLO|PARTES)\b"),
        re.compile(r"(?i)\bOFICIO\s+(?:DE\s+)?NOTIFICAC[IÓO]N\b"),
    ],
    DocType.OFICIO_CUMPLIMIENTO: [
        re.compile(r"(?i)\bCUMPLIMIENTO\s+(?:DE\s+)?(?:LA\s+)?SENTENCIA\b"),
        re.compile(r"(?i)\bEXIGENCIA\s+DE\s+CUMPLIMIENTO\b"),
    ],
    DocType.DEMANDA_TUTELA: [
        re.compile(r"(?i)\b(SE[ÑN]OR\s+JUEZ|SEÑOR\s+MAGISTRADO)\b"),
        re.compile(r"(?i)\bACCI[ÓO]N\s+DE\s+TUTELA\b.{0,80}\bACCIONANTE\b"),
        re.compile(r"(?i)\bINTERPONGO\s+ACCI[ÓO]N\s+DE\s+TUTELA\b"),
    ],
    DocType.EMAIL_JUDICIAL: [
        re.compile(r"(?i)from:.{0,80}@(?:cendoj|ramajudicial)"),
        re.compile(r"(?i)\bMessage-ID:\b"),
    ],
}


# Frases ancla en CUERPO completo (primeras 4000 chars) — peso 30%.
_BODY_PATTERNS: dict[DocType, list[re.Pattern]] = {
    DocType.AUTO_ADMISORIO: [
        re.compile(r"(?i)\bAVOCAR?\s+CONOCIMIENTO\b"),
        re.compile(r"(?i)\bSE\s+ADMITE\s+(?:LA\s+)?(?:PRESENTE\s+)?ACCI[ÓO]N\s+DE\s+TUTELA\b"),
        re.compile(r"(?i)\bRESUELVE\b.{0,200}\bAVOCAR\b"),
    ],
    DocType.SENTENCIA_1RA: [
        re.compile(r"(?i)\bRESUELV[EO]\b.{0,300}\b(?:TUTELAR|CONCEDER|AMPARAR|NEGAR|DENEGAR|IMPROCEDENTE)\b"),
        re.compile(r"(?i)\bPRIMERO\s*[:\.]\s*(?:TUTELAR|CONCEDER|AMPARAR|NEGAR|IMPROCEDENTE)"),
    ],
    DocType.SENTENCIA_2DA: [
        re.compile(r"(?i)\b(?:CONFIRMAR|REVOCAR|MODIFICAR)\s+(?:LA\s+SENTENCIA|EL\s+FALLO|EN\s+(?:TODAS|SUS))"),
        re.compile(r"(?i)\bSE\s+RESUELVE\s+EL\s+RECURSO\s+DE\s+IMPUGNAC[IÓO]N\b"),
    ],
    DocType.RESPUESTA: [
        re.compile(r"(?i)\bRADICAC[IÓO]N\s*#?\s*[:\.]?\s*\d{8,13}\b"),  # FOREST
        re.compile(r"(?i)\bDep\s+Radicadora\s*[:\.]"),
        re.compile(r"(?i)Proyect[óo]\s*[:\.]"),  # firmante
    ],
    DocType.IMPUGNACION: [
        re.compile(r"(?i)\bINTERPONG[OA]\s+(?:RECURSO\s+DE\s+)?IMPUGNAC[IÓO]N\b"),
        re.compile(r"(?i)\bIMPUGNO\s+(?:LA\s+)?SENTENCIA\b"),
    ],
    DocType.INCIDENTE_DESACATO: [
        re.compile(r"(?i)\bSOLICITO\s+(?:SE\s+)?ABRIR\s+INCIDENTE\b"),
        re.compile(r"(?i)\bINCIDENTE\s+DE\s+DESACATO\b.{0,200}\bSANCION"),
    ],
    # Escrito de tutela del accionante: petición en PRIMERA persona (interpongo/acudo) +
    # las dos partes etiquetadas juntas. Discrimina del recap del juez (3ra persona:
    # "el accionante interpuso/acudió"). El boost por estructura (en _disambiguate) usa
    # estas + SEÑOR JUEZ/PRETENSIONES para rescatar demandas mal clasificadas DESCONOCIDO.
    DocType.DEMANDA_TUTELA: [
        re.compile(r"(?i)\b(?:INTERPONG|INSTAUR|PROMUEV|INCO|FORMUL)\w*\s+(?:LA\s+)?(?:PRESENTE\s+)?ACCI[ÓO]N\s+(?:CONSTITUCIONAL\s+)?DE\s+TUTELA\b"),
        re.compile(r"(?i)\bACUDO\s+(?:RESPETUOSAMENTE\s+)?(?:ANTE\s+)?(?:SU\s+|EL\s+|A\s+SU\s+)?(?:DESPACHO|SE[ÑN]OR[ÍI]A)\b"),
    ],
}


@dataclass
class DocClassification:
    doc: DocText
    doc_type: DocType
    confidence: float                  # 0.0 - 1.0
    method: str                        # "filename" | "header" | "body" | "hybrid"
    signals: dict[str, float] = field(default_factory=dict)


def _filename_score(filename: str) -> dict[DocType, float]:
    """Score por keyword en filename.

    Estrategia:
      - Keywords largos (>=10 chars) → score 1.0 (muy confiable)
      - Keywords medios (6-9 chars)  → score 0.85
      - Keywords cortos (<6 chars)   → score 0.65 (todavía útil para "avoca", "admis")
      - Normaliza separadores (`_`, `-`, `.`) para que "Auto_Avoca_Tutela" matchee "auto avoca".
    """
    fn = filename.lower()
    fn_norm = re.sub(r"[_\-\.]", " ", fn)
    fn_norm = re.sub(r"\s+", " ", fn_norm)

    scores: dict[DocType, float] = {}
    for dt, kws in _FILENAME_KEYWORDS.items():
        for kw in sorted(kws, key=len, reverse=True):
            kw_norm = re.sub(r"[_\-\.]", " ", kw.lower())
            if kw_norm in fn or kw_norm in fn_norm:
                # Score discreto por tramo de longitud
                if len(kw_norm) >= 10:
                    score = 1.0
                elif len(kw_norm) >= 6:
                    score = 0.85
                else:
                    score = 0.65
                scores[dt] = max(scores.get(dt, 0.0), score)
                break
    return scores


def _header_score(text: str) -> dict[DocType, float]:
    head = text[:600] if text else ""
    scores: dict[DocType, float] = {}
    for dt, pats in _HEADER_PATTERNS.items():
        for pat in pats:
            if pat.search(head):
                scores[dt] = 1.0
                break
    return scores


def _body_score(text: str) -> dict[DocType, float]:
    body = text[:4000] if text else ""
    scores: dict[DocType, float] = {}
    for dt, pats in _BODY_PATTERNS.items():
        for pat in pats:
            if pat.search(body):
                scores[dt] = 1.0
                break
    return scores


# Pesos relativos de cada señal en la decisión final.
# Filename pesa más porque los nombres de archivo en el corpus son muy
# descriptivos (operadores los renombran al recibirlos).
_W_FILENAME = 0.50
_W_HEADER   = 0.30
_W_BODY     = 0.20


# Señal robusta de 2da instancia (incluye camelCase "SegundaInstancia", "2da", "Fallo2A",
# "confirma/revoca/modifica fallo"). El chequeo viejo ("SEGUNDA INSTANCIA" con espacio) no
# matcheaba camelCase → fallos de 2da caían en SENTENCIA_1RA y su fecha contaminaba la 1ra.
_RE_2DA_SIGNAL = re.compile(
    r"(?i)segund[ao]\s*inst"                          # segunda instancia / segundainstancia
    r"|2\s*[ªºa]?\.?\s*inst"                          # 2 inst / 2ª inst / 2a inst
    r"|2d[ao]"                                        # 2da/2do (camelCase: sentencia2da, tutela2dainstancia)
    r"|(?:fallo|sentencia|tutela)\s*2\s*[ªºa]"        # fallo2a / sentencia2a
    r"|(?:fallo|sentencia|tutela)\s*segund[ao]"       # fallotutelasegunda
    r"|(?:fallo|sentencia)[^a-z]{0,3}(?:confirma|revoca|modifica)"
    r"|(?:confirma|revoca|modifica)[^a-z]{0,3}(?:fallo|sentencia)"
)
# Un OFICIO/NOTIFICACIÓN que REPORTA un fallo no ES el fallo (no debe ser SENTENCIA).
_RE_NOTIF_SIGNAL = re.compile(r"(?i)\bnotifica|notificaci[óo]n|\boficio")


# Reglas de desambiguación: cuando 2 tipos compiten, hay heurísticas para
# preferir uno (ej: si SENTENCIA_2DA y SENTENCIA_1RA empatan, mirar si
# aparece "SEGUNDA INSTANCIA" → 2DA gana).
def _disambiguate(scores: dict[DocType, float], text: str, filename: str = "") -> dict[DocType, float]:
    head = (text[:600] if text else "").upper()
    fn_up = (filename or "").upper().replace("_", " ").replace("-", " ")

    # AUTO + ADMITE/AVOCA en filename → SIEMPRE es un AUTO (no DEMANDA, no SENTENCIA).
    # Bug observado: "03AutoAdmiteAccionTutela.pdf" se clasificaba DEMANDA porque
    # "accion tutela" matcheaba DEMANDA_TUTELA con score alto.
    has_auto_kw = ("AUTO" in fn_up and ("ADMIT" in fn_up or "AVOCA" in fn_up or "ADMISOR" in fn_up))
    if has_auto_kw:
        # Penalizar competidores que NO son tipo AUTO
        for dt in (DocType.DEMANDA_TUTELA, DocType.SENTENCIA_1RA, DocType.SENTENCIA_2DA,
                   DocType.IMPUGNACION, DocType.RESPUESTA):
            if dt in scores:
                scores[dt] *= 0.2

    # SENTENCIA 1ra vs 2da — detección ROBUSTA de 2da (camelCase, 2da, confirma/revoca).
    _2da_sig = bool(_RE_2DA_SIGNAL.search(fn_up) or _RE_2DA_SIGNAL.search(head)
                    or "SEGUNDA INSTANCIA" in head or "TRIBUNAL" in head)
    if _2da_sig and (DocType.SENTENCIA_1RA in scores or DocType.SENTENCIA_2DA in scores):
        scores[DocType.SENTENCIA_2DA] = max(scores.get(DocType.SENTENCIA_2DA, 0.0), 0.9)
        if DocType.SENTENCIA_1RA in scores:
            scores[DocType.SENTENCIA_1RA] *= 0.3
    # Sin señal de 2da NO penalizamos el 2DA: si su keyword de filename matcheó, es 2da
    # real (los keywords de 2DA son específicos). Penalizar a ciegas regresionaba c103/c150.

    # DOC DE FASE DESACATO: si el filename indica incidente/desacato pero NO nombra el
    # fallo (sin "fallo"/"sentencia"), el doc es de la fase de desacato (escrito de parte,
    # auto, oficio) — su body CITA el fallo que busca ejecutar, pero NO ES la sentencia.
    # Sin esto, "EscritoIncidenteDesacato" caía en SENTENCIA_2DA (el recap del fallo en el
    # body dispara la señal de 2da) sacándolo del bucket incidente. Se respeta el paquete
    # "INCIDENTE DE DESACATO FALLO TUTELA Y ANEXOS" (nombra FALLO → puede traer la sentencia).
    if ("INCIDENTE" in fn_up or "DESACATO" in fn_up) and not ("FALLO" in fn_up or "SENTENCIA" in fn_up):
        for dt in (DocType.SENTENCIA_1RA, DocType.SENTENCIA_2DA):
            if dt in scores:
                scores[dt] *= 0.2

    # ACTA / RESOLUCIÓN ADMINISTRATIVA: un fallo o auto del juez nunca se llama "acta"
    # (registro de reunión) ni "resolución NNNNN" (acto administrativo de la SED, p.ej.
    # "RES_24850 POR LA CUAL SE DA CUMPLIMIENTO AL FALLO"). El substring "fallo" en esos
    # nombres disparaba SENTENCIA_1RA y contaminaba fecha_fallo/sentido del cuadro.
    if re.search(r"(?:^|\s)ACTA(?:\s|$)|RESOLUCI[OÓ]N|(?:^|\s)RES\s?\d", fn_up):
        for dt in (DocType.SENTENCIA_1RA, DocType.SENTENCIA_2DA,
                   DocType.AUTO_ADMISORIO, DocType.AUTO_2DA):
            if dt in scores:
                scores[dt] *= 0.2

    # Un FALLO/SENTENCIA de acción de tutela ES la sentencia, NO la demanda, aunque el
    # nombre diga "AccionTutela" (que matchea DEMANDA_TUTELA fuerte). Sin esto,
    # "FalloAccionTutela.pdf" caía en DEMANDA → sacaba un fallo real del bucket de 1ra.
    if DocType.DEMANDA_TUTELA in scores and (DocType.SENTENCIA_1RA in scores or DocType.SENTENCIA_2DA in scores):
        if "FALLO" in fn_up or "SENTENCIA" in fn_up:
            scores[DocType.DEMANDA_TUTELA] *= 0.3

    # OFICIO/NOTIFICACIÓN que reporta un fallo → NO es la sentencia. Demota SENTENCIA y
    # routea a NOTIFICACION_FALLO (si menciona fallo/sentencia) o NOTIFICACION genérica.
    if _RE_NOTIF_SIGNAL.search(fn_up) and (DocType.SENTENCIA_1RA in scores or DocType.SENTENCIA_2DA in scores):
        tgt = (DocType.NOTIFICACION_FALLO
               if ("FALLO" in fn_up or "SENTENCIA" in fn_up or "FALLO" in head or "SENTENCIA" in head)
               else DocType.NOTIFICACION)
        scores[tgt] = max(scores.get(tgt, 0.0), 0.9)
        scores[DocType.SENTENCIA_1RA] = scores.get(DocType.SENTENCIA_1RA, 0.0) * 0.3
        scores[DocType.SENTENCIA_2DA] = scores.get(DocType.SENTENCIA_2DA, 0.0) * 0.3

    # AUTO ADMISORIO vs AUTO 2DA: si dice "ADMITE IMPUGNACIÓN" → 2DA
    if DocType.AUTO_ADMISORIO in scores and DocType.AUTO_2DA in scores:
        if "IMPUGNAC" in head or "IMPUGNAC" in fn_up or "SEGUNDA" in head:
            scores[DocType.AUTO_ADMISORIO] *= 0.3
        else:
            scores[DocType.AUTO_2DA] *= 0.3

    # AUTO_CONCEDE_IMPUGNACION vs IMPUGNACION: si tiene "AUTO" + "CONCEDE" → AUTO_CONCEDE
    if DocType.IMPUGNACION in scores and DocType.AUTO_CONCEDE_IMPUGNACION in scores:
        if ("AUTO" in head and "CONCEDE" in head) or ("AUTO" in fn_up and "CONCEDE" in fn_up):
            scores[DocType.IMPUGNACION] *= 0.4
        else:
            scores[DocType.AUTO_CONCEDE_IMPUGNACION] *= 0.4

    # AUTO + IMPUGNACION pero sin CONCEDE → AUTO_2DA (admite impugnación), no IMPUGNACION genérica
    if DocType.IMPUGNACION in scores and "AUTO" in fn_up and "IMPUGNAC" in fn_up:
        if "CONCEDE" not in fn_up:
            scores[DocType.IMPUGNACION] *= 0.4
            scores[DocType.AUTO_2DA] = max(scores.get(DocType.AUTO_2DA, 0.0), 0.7)

    # NOTIFICACION_FALLO vs NOTIFICACION genérica: si menciona "fallo" o "sentencia" → ESPECÍFICA
    if DocType.NOTIFICACION in scores:
        if "FALLO" in head or "SENTENCIA" in head or "FALLO" in fn_up or "SENTENCIA" in fn_up:
            scores[DocType.NOTIFICACION_FALLO] = max(
                scores.get(DocType.NOTIFICACION_FALLO, 0.0),
                scores[DocType.NOTIFICACION] * 1.2,
            )
            scores[DocType.NOTIFICACION] *= 0.7

    # DEMANDA por ESTRUCTURA (rescata escritos de tutela mal clasificados DESCONOCIDO cuyo
    # filename no lo dice —"001Tutela.pdf"— y cuyos marcadores caen fuera del header[:600]).
    # El escrito del accionante combina ≥3 señales; se exige que NO sea providencia del juez
    # (sin AVOCA/SE ADMITE/RESUELVE-dispositiva/ADMINISTRANDO JUSTICIA/encabezado JUZGADO N).
    # Rescate de DEMANDA mal clasificada DESCONOCIDO: exige la señal DISCRIMINANTE de
    # primera persona del accionante ("INTERPONGO/ACUDO la acción de tutela") — NO aparece
    # en recaps (3ra persona "interpuso/acudió") ni en providencias. Excluye explícitamente
    # providencia del juez, contestación de la SED e incidente. Solo si el score actual es
    # bajo (<0.5) — los docs ya tipados no se tocan.
    _t8 = (text or "")[:8000]
    # Disparador discriminante: el doc ARRANCA dirigiéndose al juez ("SEÑOR JUEZ…" en el
    # encabezado) — así abre el accionante; autos/sentencias/respuestas abren con
    # "JUZGADO"/membrete — O usa primera persona ("interpongo/acudo la acción de tutela").
    _trigger = bool(_RE_DEMANDA_OPENING.search(_t8[:220]) or _RE_DEMANDA_1P.search(_t8))
    _struct = sum(bool(p.search(_t8.upper())) for p in (
        re.compile(r"ACCIONANTE\s*[:\.]"), re.compile(r"ACCIONAD[OA]S?\s*[:\.]"),
        re.compile(r"\bPRETENSION"), re.compile(r"\bHECHOS\b")))
    if (_trigger and _struct >= 2
            and not _RE_ES_PROVIDENCIA.search(text or "")
            and not _RE_ES_RESPUESTA.search(_t8)
            and not _RE_ES_INCIDENTE.search((filename or "") + " " + _t8)
            and not _RE_ES_INFORME.search((filename or "") + " " + _t8)
            and max(scores.values(), default=0.0) < 0.5):
        scores[DocType.DEMANDA_TUTELA] = max(scores.get(DocType.DEMANDA_TUTELA, 0.0), 0.65)

    # Anti-informe/providencia en el SCORING principal: un informe/oficio/providencia que
    # CITA la tutela (sin escritura en 1ª persona del accionante "interpongo/acudo") NO
    # debe puntuar como DEMANDA — empataba ~0.3 con SENTENCIA y a veces ganaba (32 docs
    # mal rotulados). La demanda real (1ª persona) nunca se suprime.
    if (scores.get(DocType.DEMANDA_TUTELA, 0.0) > 0.0
            and not _RE_DEMANDA_1P.search(_t8)
            and (_RE_ES_INFORME.search((filename or "") + " " + _t8)
                 or _RE_ES_PROVIDENCIA.search(text or ""))):
        scores[DocType.DEMANDA_TUTELA] = 0.0

    return scores


# Señal DISCRIMINANTE de DEMANDA: petición en PRIMERA persona del accionante. Los recaps
# (auto/sentencia) usan 3ra persona pasada ("interpuso/acudió") → no matchea.
_RE_DEMANDA_1P = re.compile(
    r"(?i)\b(?:INTERPONG[OA]|INSTAUR[OA]|PROMUEV[OA]|INCO[OA]|FORMUL[OA])\b[^\n]{0,50}?"
    r"\bACCI[ÓO]N\s+(?:CONSTITUCIONAL\s+)?DE\s+TUTELA\b"
    r"|\bACUDO\s+(?:RESPETUOSAMENTE\s+)?(?:ANTE|A)\s+(?:SU\s+|EL\s+|USTED|ESTE)?\s*"
    r"(?:DESPACHO|SE[ÑN]OR[ÍI]A|JUZGADO|USTED)"
    r"|\bYO,?\s+[A-ZÁÉÍÓÚÑ][^\n]{0,70}?\bidentificad[oa]\b[^\n]{0,90}?"
    r"\b(?:interpong|acudo|instaur|promuev)\w*"
)
# El doc ARRANCA dirigiéndose al juez (apertura típica del escrito del accionante).
_RE_DEMANDA_OPENING = re.compile(
    r"(?i)(?:SE[ÑN]OR(?:A|ES)?|HONORABLE)\s+(?:JUE[ZC]|MAGISTRAD)|"
    r"JUE[ZC]\s+(?:\d+\s+)?(?:CONSTITUCIONAL|PROMISCUO|CIVIL|PENAL|LABORAL|MUNICIPAL|DE\s+TUTELA)"
    r"[^\n]{0,60}\(\s*REPARTO\s*\)"
)
# La SED en su contestación recapitula el petitorio pero NO es demanda.
_RE_ES_RESPUESTA = re.compile(
    r"(?i)\bAL\s+RESPONDER\s+CITE\s+ESTE\s+N[ÚU]MERO\b|\bProyect[óo]\s*[:\.]|"
    r"\bcontestaci[óo]n\s+a\s+la\s+(?:acci[óo]n\s+de\s+)?tutela\b|\bDep\s+Radicadora\b"
)
# Escrito/auto de incidente de desacato (estructura de petición similar a demanda).
_RE_ES_INCIDENTE = re.compile(r"(?i)\bINCIDENTE\s+DE\s+DESACATO\b|\bABRIR\s+INCIDENTE\b|\bincidente\b")
# Informe/oficio de cumplimiento o visita ocular: REPORTA el caso (cita ACCIONANTE +
# acción de tutela) pero NO es la demanda del accionante. El rescate de DEMANDA no lo
# cubría → 32 informes quedaron mal rotulados DEMANDA_TUTELA.
_RE_ES_INFORME = re.compile(
    r"(?i)\bINFORME\s+DE\s+CUMPLIMIENTO\b|\bVISITA\s+(?:DE\s+INSPECCI[ÓO]N\s+)?OCULAR\b|"
    r"\bINSPECCI[ÓO]N\s+OCULAR\b|\bOFICIO\s+REMISORIO\b|"
    r"\bme\s+permito\s+(?:remitir|enviar)\b[^\n]{0,40}\b(?:informe|auto|el)\b"
)
# El doc ES una providencia del juez (NO una demanda): frases inequívocas de auto/sentencia.
_RE_ES_PROVIDENCIA = re.compile(
    r"(?i)\bAVOCAR?\s+CONOCIMIENTO\b|\bSE\s+ADMITE\s+(?:LA\s+)?(?:PRESENTE\s+)?ACCI[ÓO]N\b|"
    r"\bADMINISTRANDO\s+JUSTICIA\b|\bRESUELV[EO]\b[\s\S]{0,200}?\b(?:TUTELAR|CONCEDER|NEGAR|"
    r"DENEGAR|CONFIRMAR|REVOCAR|AVOCAR|ADMITIR)\b|^\s*JUZGADO\s+\w+\s+(?:CIVIL|PENAL|LABORAL|"
    r"PROMISCUO|MUNICIPAL|CONSTITUCIONAL|ADMINISTRATIVO)"
)


def classify(doc: DocText) -> DocClassification:
    """Clasifica un doc combinando filename + header + body con ponderación.

    Atajo: si el doc es claramente un email (.md o filename "Email_..."),
    se clasifica como EMAIL_JUDICIAL/INTERNO sin entrar al multi-señal —
    esto evita que un email titulado "RV: SENTENCIA TUTELA..." se clasifique
    como SENTENCIA_1RA cuando en realidad es un email que reporta una sentencia.
    """
    filename = doc.filename or ""
    text = doc.text or ""

    # ATAJO: emails se reconocen primero por filename
    if _is_email_filename(filename):
        if _is_email_internal(filename, text):
            return DocClassification(
                doc=doc, doc_type=DocType.EMAIL_INTERNO, confidence=0.95,
                method="filename_email", signals={},
            )
        return DocClassification(
            doc=doc, doc_type=DocType.EMAIL_JUDICIAL, confidence=0.95,
            method="filename_email", signals={},
        )

    fn_scores = _filename_score(filename)
    hd_scores = _header_score(text)
    bd_scores = _body_score(text)

    # Combinar
    all_types = set(fn_scores) | set(hd_scores) | set(bd_scores)
    combined: dict[DocType, float] = {}
    for dt in all_types:
        s = (
            fn_scores.get(dt, 0.0) * _W_FILENAME +
            hd_scores.get(dt, 0.0) * _W_HEADER +
            bd_scores.get(dt, 0.0) * _W_BODY
        )
        combined[dt] = s

    combined = _disambiguate(combined, text, filename)

    if not combined:
        return DocClassification(
            doc=doc, doc_type=DocType.DESCONOCIDO, confidence=0.0,
            method="none", signals={},
        )

    # Top-1
    best_dt = max(combined, key=combined.get)
    best_score = combined[best_dt]

    if best_score < 0.2:
        return DocClassification(
            doc=doc, doc_type=DocType.DESCONOCIDO, confidence=best_score,
            method="low_confidence",
            signals={k.value: round(v, 2) for k, v in combined.items() if v > 0},
        )

    # Decidir método predominante
    fn_w = fn_scores.get(best_dt, 0.0) * _W_FILENAME
    hd_w = hd_scores.get(best_dt, 0.0) * _W_HEADER
    bd_w = bd_scores.get(best_dt, 0.0) * _W_BODY
    if fn_w >= max(hd_w, bd_w):
        method = "filename"
    elif hd_w >= bd_w:
        method = "header"
    else:
        method = "body"
    if sum(1 for w in (fn_w, hd_w, bd_w) if w > 0) >= 2:
        method = "hybrid"

    return DocClassification(
        doc=doc, doc_type=best_dt, confidence=round(best_score, 3),
        method=method,
        signals={k.value: round(v, 2) for k, v in combined.items() if v > 0},
    )


# ============================================================
# VERIFICADOR DE PERTENENCIA — rad23 doc vs case
# ============================================================

class BelongsVerdict(str, Enum):
    OK            = "OK"             # rad23 del doc coincide con el del case
    SUSPICIOUS    = "SOSPECHOSO"     # rad23 ausente o ambiguo
    NO_PERTENECE  = "NO_PERTENECE"   # rad23 distinto al esperado
    INDETERMINADO = "INDETERMINADO"  # no hay rad23 ni en doc ni en folder, no se puede juzgar


@dataclass
class BelongsCheck:
    verdict: BelongsVerdict
    rad23_in_doc: Optional[str]
    rad23_expected: Optional[str]
    detail: str = ""


def verify_belongs(
    doc: DocText,
    *,
    case_rad23: Optional[str] = None,
    folder_rad_corto: Optional[str] = None,
) -> BelongsCheck:
    """Compara el rad23 extraído del doc vs el rad23/folder del case.

    Args:
        doc: documento a verificar
        case_rad23: rad23 ya conocido del case (DB o ya extraído)
        folder_rad_corto: rad corto del folder_name (p.ej. "2026-00095")
    """
    from backend.v9.regex_pass import _extract_radicado_23

    rad_in_doc = _extract_radicado_23(doc.text)
    expected = case_rad23

    # Si no hay rad23 en doc Y tampoco hay esperado → indeterminable
    if not rad_in_doc and not expected:
        # Intentar fallback: rad corto del folder en el texto
        if folder_rad_corto and folder_rad_corto in doc.text:
            return BelongsCheck(
                verdict=BelongsVerdict.OK, rad23_in_doc=None,
                rad23_expected=None,
                detail=f"rad corto del folder '{folder_rad_corto}' aparece en doc",
            )
        return BelongsCheck(
            verdict=BelongsVerdict.INDETERMINADO, rad23_in_doc=None,
            rad23_expected=expected,
            detail="sin rad23 en doc ni en case",
        )

    # Hay rad23 en doc pero no esperado → tomamos el del doc como referencia
    if rad_in_doc and not expected:
        return BelongsCheck(
            verdict=BelongsVerdict.OK, rad23_in_doc=rad_in_doc,
            rad23_expected=None,
            detail="case sin rad23 previo, doc aporta uno válido",
        )

    # Esperado sin rad en doc → sospechoso (no hay forma de corroborar)
    if expected and not rad_in_doc:
        # Si el folder corto sí aparece, OK
        if folder_rad_corto and folder_rad_corto in doc.text:
            return BelongsCheck(
                verdict=BelongsVerdict.OK, rad23_in_doc=None,
                rad23_expected=expected,
                detail=f"rad corto del folder '{folder_rad_corto}' aparece en doc",
            )
        return BelongsCheck(
            verdict=BelongsVerdict.SUSPICIOUS, rad23_in_doc=None,
            rad23_expected=expected,
            detail="doc no tiene rad23 visible — no se puede corroborar",
        )

    # Ambos presentes — comparar rad21 (sin los 2 dígitos finales del consecutivo
    # de recursos). Misma tutela en 1ra y 2da instancia tiene rad21 idéntico:
    # 1ra inst: ...XXX00, 2da inst: ...XXX01.
    if rad_in_doc[:21] == expected[:21]:
        same_recurso = (rad_in_doc == expected)
        return BelongsCheck(
            verdict=BelongsVerdict.OK, rad23_in_doc=rad_in_doc,
            rad23_expected=expected,
            detail=("rad23 coincide" if same_recurso
                    else f"misma tutela, distinta etapa procesal (recurso {rad_in_doc[-2:]} vs {expected[-2:]})"),
        )

    return BelongsCheck(
        verdict=BelongsVerdict.NO_PERTENECE, rad23_in_doc=rad_in_doc,
        rad23_expected=expected,
        detail=f"rad distinto: doc='{rad_in_doc}' vs case='{expected}'",
    )


# ============================================================
# AUDITOR DE INTEGRIDAD DEL EXPEDIENTE
# ============================================================

@dataclass
class Anomaly:
    code: str        # ej. "MISSING_AUTO_ADMISORIO", "MULTIPLE_AUTO_ADMISORIO"
    severity: str    # "CRITICA" | "ALTA" | "MEDIA" | "BAJA"
    message: str
    affected_docs: list[int] = field(default_factory=list)


@dataclass
class ExpedienteReport:
    case_id: int
    folder_name: str
    docs_total: int
    docs_classified: list[DocClassification] = field(default_factory=list)
    docs_belonging: list[BelongsCheck] = field(default_factory=list)
    type_counts: dict[str, int] = field(default_factory=dict)
    anomalies: list[Anomaly] = field(default_factory=list)
    integrity_score: float = 1.0    # 1.0 = expediente perfecto

    def has_critical_anomaly(self) -> bool:
        return any(a.severity == "CRITICA" for a in self.anomalies)


def audit_expediente(
    case_id: int,
    folder_name: str,
    docs: list[DocText],
    *,
    case_rad23: Optional[str] = None,
    folder_rad_corto: Optional[str] = None,
) -> ExpedienteReport:
    """Clasifica todos los docs del case y detecta anomalías."""
    classifications = [classify(d) for d in docs]
    type_counts: dict[DocType, int] = {}
    for c in classifications:
        type_counts[c.doc_type] = type_counts.get(c.doc_type, 0) + 1

    belongs = [
        verify_belongs(c.doc, case_rad23=case_rad23, folder_rad_corto=folder_rad_corto)
        for c in classifications
    ]

    anomalies: list[Anomaly] = []

    # Regla 1: ¿hay AUTO_ADMISORIO? (CRÍTICA)
    n_auto = type_counts.get(DocType.AUTO_ADMISORIO, 0)
    if n_auto == 0:
        anomalies.append(Anomaly(
            code="MISSING_AUTO_ADMISORIO",
            severity="CRITICA",
            message="Expediente sin auto admisorio — no es expediente válido",
        ))

    # Regla 2: ¿más de 1 AUTO_ADMISORIO? (ALTA)
    if n_auto > 1:
        anomalies.append(Anomaly(
            code="MULTIPLE_AUTO_ADMISORIO",
            severity="ALTA",
            message=f"{n_auto} autos admisorios — debería ser 1 (clasificador puede haberse roto)",
        ))

    # Regla 3: cardinalidades fuera de rango (MEDIA)
    for dt, count in type_counts.items():
        min_n, max_n = EXPECTED_CARDINALITY.get(dt, (0, None))
        if max_n is not None and count > max_n:
            anomalies.append(Anomaly(
                code=f"EXCESS_{dt.value}",
                severity="MEDIA",
                message=f"{count} docs tipo {dt.value} (máximo esperado {max_n})",
            ))

    # Regla 4: SENTENCIA_2DA sin IMPUGNACION (ALTA)
    n_sent2 = type_counts.get(DocType.SENTENCIA_2DA, 0)
    n_imp = type_counts.get(DocType.IMPUGNACION, 0)
    n_auto_concede = type_counts.get(DocType.AUTO_CONCEDE_IMPUGNACION, 0)
    if n_sent2 > 0 and n_imp == 0 and n_auto_concede == 0:
        anomalies.append(Anomaly(
            code="SENTENCIA_2DA_SIN_IMPUGNACION",
            severity="ALTA",
            message="Hay sentencia de 2da pero no hay impugnación archivada",
        ))

    # Regla 5: AUTO_INCIDENTE sin INCIDENTE (ALTA)
    n_auto_inc = type_counts.get(DocType.AUTO_INCIDENTE, 0)
    n_inc = type_counts.get(DocType.INCIDENTE_DESACATO, 0)
    if n_auto_inc > 0 and n_inc == 0:
        anomalies.append(Anomaly(
            code="AUTO_INCIDENTE_SIN_INCIDENTE",
            severity="ALTA",
            message="Hay auto de incidente pero no hay incidente archivado",
        ))

    # Regla 6: docs marcados NO_PERTENECE (CRÍTICA)
    foreign_doc_indices = [i for i, b in enumerate(belongs) if b.verdict == BelongsVerdict.NO_PERTENECE]
    if foreign_doc_indices:
        anomalies.append(Anomaly(
            code="FOREIGN_DOCS",
            severity="CRITICA",
            message=f"{len(foreign_doc_indices)} docs con rad23 distinto al case",
            affected_docs=foreign_doc_indices,
        ))

    # Regla 7: muchos docs DESCONOCIDOS (BAJA)
    n_unknown = type_counts.get(DocType.DESCONOCIDO, 0)
    if docs and n_unknown / len(docs) > 0.5:
        anomalies.append(Anomaly(
            code="MANY_UNKNOWN_DOCS",
            severity="BAJA",
            message=f"{n_unknown}/{len(docs)} docs no clasificables — clasificador puede necesitar afinación",
        ))

    # Score: 1.0 - penalización por anomalías
    severity_weights = {"CRITICA": 0.4, "ALTA": 0.2, "MEDIA": 0.1, "BAJA": 0.05}
    integrity_score = max(0.0, 1.0 - sum(severity_weights[a.severity] for a in anomalies))

    return ExpedienteReport(
        case_id=case_id,
        folder_name=folder_name,
        docs_total=len(docs),
        docs_classified=classifications,
        docs_belonging=belongs,
        type_counts={dt.value: n for dt, n in type_counts.items()},
        anomalies=anomalies,
        integrity_score=round(integrity_score, 3),
    )


# Etiquetas que NO provienen del doc_librarian, sino del clasificador legacy por
# filename (`classify_doc_type`, usado por sync/upload/gmail_monitor). Solo estas se
# reclasifican: las etiquetas ricas ya asignadas (la familia DocType, incl. EMAIL_* y
# un DESCONOCIDO de un pase previo del librarian) se respetan (first-classifier-wins).
_LEGACY_DOC_TYPES = frozenset({
    "PDF_OTRO", "PDF_AUTO_ADMISORIO", "PDF_SENTENCIA", "PDF_INCIDENTE",
    "PDF_IMPUGNACION", "PDF_GMAIL", "DOCX_OTRO", "DOCX_RESPUESTA",
    "DOCX_CUMPLIMIENTO", "DOCX_SOLICITUD", "DOCX_MEMORIAL", "DOCX_CARTA",
    "DOCX_DESACATO", "DOCX_IMPUGNACION", "OTRO", "EMAIL_DB", "SCREENSHOT", "",
    # DESCONOCIDO: el clasificador legacy / ingestas no-Gmail dejaban demandas y
    # fallos genuinos como DESCONOCIDO → invisibles a los extractores (filtran por
    # DEMANDA_TUTELA/SENTENCIA_*). reclassify los recupera con `classify()` por
    # contenido; si sigue siendo DESCONOCIDO o conf<min, NO se toca (idempotente).
    "DESCONOCIDO",
})


def reclassify_legacy_docs(db, case, *, min_conf: float = 0.5) -> list[dict]:
    """Reclasifica con el doc_librarian (por contenido) los docs del `case` que aún
    tengan etiqueta legacy por-filename, persistiendo la etiqueta rica cuando la
    confianza ≥ `min_conf` y no es DESCONOCIDO.

    Por qué: solo el ingest de Gmail clasificaba con el librarian; los docs añadidos
    soltando la carpeta + Sync quedaban con `PDF_*`/`DOCX_*`, que los extractores de
    `field_extractor.py` (filtran por `SENTENCIA_1RA`/`DEMANDA_TUTELA`/`RESPUESTA`/…)
    no reconocen → fallo/derecho/etc. vacíos. Esto autocura cualquier vía de ingesta.

    Usa el `extracted_text` ya en DB (no re-lee disco). NO toca docs con etiqueta rica.
    Devuelve [{doc_id, filename, old, new, conf}]. El caller hace commit.
    """
    from backend.database.models import Document  # local: no acoplar el módulo a la capa DB

    changes: list[dict] = []
    for d in db.query(Document).filter(Document.case_id == case.id).all():
        cur = d.doc_type or ""
        if cur not in _LEGACY_DOC_TYPES:
            continue
        txt = d.extracted_text or ""
        if len(txt) < 80:
            continue  # sin texto suficiente para clasificar por contenido
        dt = DocText(path=d.file_path or "", filename=d.filename or "", text=txt,
                     method="db", pages=0, has_scanned_pages=False, error=None)
        cl = classify(dt)
        if cl.doc_type == DocType.DESCONOCIDO or cl.confidence < min_conf:
            continue
        new = cl.doc_type.value
        if new != cur:
            d.doc_type = new
            changes.append({"doc_id": d.id, "filename": d.filename,
                            "old": cur, "new": new, "conf": round(cl.confidence, 2)})
    return changes
