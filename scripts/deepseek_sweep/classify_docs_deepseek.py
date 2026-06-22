#!/usr/bin/env python3
"""
Fase 2 del experimento DeepSeek end-to-end: clasificador de documentos.

El clasificador actual (doc_ops.py::classify_doc_type) usa SOLO el nombre
de archivo. Este experimento usa DeepSeek con contenido + filename + reglas
de edge-cases explícitas en el system prompt.

Métricas: accuracy por tipo vs ground-truth en DB.
Muestra: 300 docs estratificados (30 por tipo principal, 20 DESCONOCIDO/PDF_OTRO).

Uso:
    python3 scripts/deepseek_sweep/classify_docs_deepseek.py --sample 300
    python3 scripts/deepseek_sweep/classify_docs_deepseek.py --sample 50 --workers 2   # piloto
    python3 scripts/deepseek_sweep/classify_docs_deepseek.py --report   # solo reporte

Resultados: data/experiment/classify_results/<doc_id>.json
Reporte:    data/experiment/classify_report.txt
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── env (DeepSeek) ANTES de imports backend ──────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
_ENV = ROOT / "data" / "experiment" / ".env.deepseek_sweep"
if _ENV.exists():
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(ROOT))

import sqlalchemy                          # noqa: E402
from sqlalchemy.orm import sessionmaker    # noqa: E402
from backend.database.models import Document, Case  # noqa: E402

RESULTS_DIR  = ROOT / "data" / "experiment" / "classify_results"
REPORT_FILE  = ROOT / "data" / "experiment" / "classify_report.txt"
PROD_DB      = ROOT / "data" / "tutelas.db"
LLM_URL      = os.getenv("LLM_LOCAL_URL", "https://api.deepseek.com")
LLM_KEY      = os.getenv("V9_LLM_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_LOCAL_MODEL_ID", "deepseek-v4-flash")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(RESULTS_DIR / "classify.log", encoding="utf-8")],
)
log = logging.getLogger("classify")

# ── Taxonomía canónica (18 tipos) ─────────────────────────────────────────
CANONICAL_TYPES = [
    "DEMANDA_TUTELA",
    "AUTO_ADMISORIO",
    "SENTENCIA_1RA",
    "NOTIFICACION",
    "RESPUESTA_SED",
    "IMPUGNACION",
    "AUTO_CONCEDE_IMPUGNACION",
    "SENTENCIA_2DA",
    "INCIDENTE_DESACATO",
    "AUTO_INCIDENTE",
    "EMAIL_MD",
    "ACTA_REPARTO",
    "AUTO_VINCULA",
    "OFICIO_CUMPLIMIENTO",
    "ANEXO",
    "INSUMO_SED",
    "AUTO_OTRO",
    "OTRO",
]

# Mapeo DB → canónico (para calcular ground-truth)
CANONICAL_MAP = {
    "SENTENCIA_1RA":            "SENTENCIA_1RA",
    "PDF_SENTENCIA":            "SENTENCIA_1RA",
    "SENTENCIA_2DA":            "SENTENCIA_2DA",
    "AUTO_2DA":                 "SENTENCIA_2DA",
    "AUTO_2DA_INSTANCIA":       "SENTENCIA_2DA",
    "AUTO_ADMISORIO":           "AUTO_ADMISORIO",
    "PDF_AUTO_ADMISORIO":       "AUTO_ADMISORIO",
    "DEMANDA_TUTELA":           "DEMANDA_TUTELA",
    "DEMANDA":                  "DEMANDA_TUTELA",
    "NOTIFICACION":             "NOTIFICACION",
    "NOTIFICACION_FALLO":       "NOTIFICACION",
    "OFICIO_NOTIFICACION":      "NOTIFICACION",
    "RESPUESTA":                "RESPUESTA_SED",
    "DOCX_RESPUESTA":           "RESPUESTA_SED",
    "RESPUESTA_SED":            "RESPUESTA_SED",
    "IMPUGNACION":              "IMPUGNACION",
    "PDF_IMPUGNACION":          "IMPUGNACION",
    "DOCX_IMPUGNACION":         "IMPUGNACION",
    "AUTO_CONCEDE_IMPUGNACION": "AUTO_CONCEDE_IMPUGNACION",
    "INCIDENTE_DESACATO":       "INCIDENTE_DESACATO",
    "PDF_INCIDENTE":            "INCIDENTE_DESACATO",
    "DOCX_DESACATO":            "INCIDENTE_DESACATO",
    "AUTO_INCIDENTE":           "AUTO_INCIDENTE",
    "EMAIL_JUDICIAL":           "EMAIL_MD",
    "EMAIL_MD":                 "EMAIL_MD",
    "EMAIL_INTERNO":            "EMAIL_MD",
    "EMAIL_OUTLOOK_PDF":        "EMAIL_MD",
    "EMAIL_DB":                 "EMAIL_MD",
    "PDF_GMAIL":                "EMAIL_MD",
    "ANEXO_DEMANDA":            "ANEXO",
    "ANEXO_PRUEBA":             "ANEXO",
    "MEMORIAL_ACCIONANTE":      "ANEXO",
    "DOCX_SOLICITUD":           "ANEXO",
    "DOCX_MEMORIAL":            "ANEXO",
    "DOCX_CARTA":               "ANEXO",
    "INFORME":                  "ANEXO",
    "AUTO_VINCULA":             "AUTO_VINCULA",
    "OFICIO_CUMPLIMIENTO":      "OFICIO_CUMPLIMIENTO",
    "DOCX_CUMPLIMIENTO":        "OFICIO_CUMPLIMIENTO",
    "INSUMO_CONTESTACION":      "INSUMO_SED",
    "INSUMO_PROCEDIMIENTO":     "INSUMO_SED",
    "INSUMO_ADMINISTRATIVO":    "INSUMO_SED",
    "OFICIO_INTERNO_SED":       "INSUMO_SED",
    "DOCX_OTRO":                "INSUMO_SED",
    "ACTA_REPARTO":             "ACTA_REPARTO",
    "RESOLUCION":               "AUTO_OTRO",
    "AUTO_NULIDAD":             "AUTO_OTRO",
    "AUTO_OBEDEZCASE_Y_CUMPLASE": "AUTO_OTRO",
    "AUTO_DESISTIMIENTO":       "AUTO_OTRO",
    "AUTO_ACUMULACION":         "AUTO_OTRO",
    "AUTO_ARCHIVA":             "AUTO_OTRO",
    "PDF_OTRO":                 "OTRO",
    "OTRO_NO_CLASIFICABLE":     "OTRO",
    "SCREENSHOT":               "OTRO",
    "DESCONOCIDO":              "DESCONOCIDO",   # unknowns se tratan aparte
}

# ── System prompt ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un clasificador experto en documentos de acciones de tutela colombianas.
El contexto es la Gobernación de Santander, Secretaría de Educación (SED Santander).
Los documentos son de procesos judiciales de tutela contra la SED por derechos de educación.

TAXONOMÍA — Debes devolver uno de estos 18 tipos exactos:
  DEMANDA_TUTELA         | AUTO_ADMISORIO        | SENTENCIA_1RA
  NOTIFICACION           | RESPUESTA_SED         | IMPUGNACION
  AUTO_CONCEDE_IMPUGNACION | SENTENCIA_2DA       | INCIDENTE_DESACATO
  AUTO_INCIDENTE         | EMAIL_MD              | ACTA_REPARTO
  AUTO_VINCULA           | OFICIO_CUMPLIMIENTO   | ANEXO
  INSUMO_SED             | AUTO_OTRO             | OTRO

═══════════════════════════════════════════════════════════════
DESCRIPCIÓN DE CADA TIPO
═══════════════════════════════════════════════════════════════

DEMANDA_TUTELA
  Qué es: La acción que presenta el ciudadano o su representante ante el juzgado.
  Señales en filename: "EscritoTutela", "Tutela", "accion_tutela", "demanda"
  Señales en contenido:
    - "Señor JUZGADO" o "Señor Juez" al inicio
    - Sección "ACCIONANTE:" y "ACCIONADO:" o "ACCIONADOS:"
    - "acudo ante usted", "promover acción de tutela"
    - Primera persona del solicitante describiendo su situación
  Ejemplo de filename: EscritoTutela2026-00034.pdf, 01EscritoTutela_NombrePersona.pdf

AUTO_ADMISORIO
  Qué es: Auto del juzgado que admite (o no avoca) la tutela. Asigna radicado.
  Señales en filename: "AutoAdmite", "AutoAdmisorio", "Auto_Avoca", "AutoNoAvoca"
  Señales en contenido:
    - "Se admite la acción de tutela" o "ADMÍTASE la acción"
    - "AVÓQUESE el conocimiento" o "NO SE AVOCA"
    - Número de radicado de 23 dígitos cerca de "Radicación N°"
    - "NOTIFÍQUESE Y CÚMPLASE"
  OJO: Un auto que ABRE un incidente de desacato NO es AUTO_ADMISORIO aunque
       tenga formato de auto de admisión.

SENTENCIA_1RA
  Qué es: El fallo de primera instancia del juez. Decide si CONCEDE o NIEGA el amparo.
  Señales en filename: "Sentencia", "SentenciaTutela", "FalloTutela", "010Sentencia"
  Señales en contenido:
    - Sección "RESUELVE:" o "EN MÉRITO DE LO EXPUESTO"
    - Verbos decisorios: CONCEDE, NIEGA, IMPROCEDENTE, CARENCIA DE OBJETO,
      CARENCIA_OBJETO, HECHO SUPERADO, NULIDAD
    - "Se decide la acción de tutela instaurada por"
    - Firma del juez al final
  CRÍTICO: Un "Acta de seguimiento al cumplimiento del fallo" NO es SENTENCIA_1RA.
           Es una reunión de verificación posterior → clasificar como AUTO_OTRO.

NOTIFICACION
  Qué es: Oficio del juzgado que notifica a las partes de un auto o sentencia.
  Señales en filename: "OFICIO_NOTIFICACION", "OficioNotifica", "NOTIF", "NotificandoFallo"
  Señales en contenido:
    - "Por medio del presente oficio me permito NOTIFICAR"
    - "Se notifica el auto / la sentencia de fecha..."
    - Dirigido a la Gobernación, SED, accionante, o Procuraduría
    - Número de caso y fecha de la providencia notificada

RESPUESTA_SED
  Qué es: Respuesta oficial de la Secretaría de Educación al juzgado.
  Señales en filename: "respuesta", "RESPUESTA", "contestacion", "con_forest", "forest"
  Señales en contenido:
    - Encabezado GOBERNACIÓN DE SANTANDER / Secretaría de Educación
    - Número FOREST (formato: NNNNNN o N-YYYY-NNNNNN-NNNNNN)
    - "AL RESPONDER CITE ESTE NÚMERO" o "Proc #:"
    - "Proyectó:" o "Revisó:" con nombre de abogado al final
    - "En respuesta a la acción de tutela" o "En atención al requerimiento"
  Nota: puede ser PDF o DOCX.

IMPUGNACION
  Qué es: Escrito que una parte presenta impugnando el fallo de primera instancia.
  Señales en filename: "Impugnacion", "IMPU_", "RecursoImpugnacion"
  Señales en contenido:
    - "IMPUGNACIÓN" o "recurso de impugnación"
    - "No estamos de acuerdo con el fallo" o "apelamos el fallo"
    - Dirigido al juzgado, solicitando que se envíe al superior
  OJO: El AUTO que concede el trámite de impugnación es AUTO_CONCEDE_IMPUGNACION.

AUTO_CONCEDE_IMPUGNACION
  Qué es: Auto del juzgado que admite la impugnación y la envía al superior.
  Señales en filename: "AutoConcedeImpugnacion", "AutoConcedeImpugnación"
  Señales en contenido:
    - "Se concede la impugnación interpuesta" o "CONCÉDASE la impugnación"
    - "Remítase al Tribunal" o "al superior jerárquico"

SENTENCIA_2DA
  Qué es: Fallo del tribunal o juzgado superior que resuelve la impugnación.
  Señales en filename: "FalloSegundaInstancia", "Sentencia2da", "SentenciaTutela_2da",
                        "FalloSegunda", "AnexoFalloSentenciaSegundaInstancia"
  Señales en contenido:
    - CONFIRMA, MODIFICA, REVOCA, IMPROCEDENTE (como segunda decisión)
    - "Conoce el despacho de la impugnación interpuesta"
    - Tribunal o Juzgado Circuito como órgano decisor (no el municipal)
    - Referencia al fallo de primera instancia

INCIDENTE_DESACATO
  Qué es: Escrito o auto que ABRE el incidente de desacato por incumplimiento.
  Señales en filename: "AutoAbreIncidente", "EscritoIncidDesacato", "AutoRequierePrevio",
                        "AutoAperturaFormalIncidente"
  Señales en contenido:
    - "incidente de desacato" + "APERTURA" o "Se abre el incidente"
    - "artículo 27 del Decreto 2591 de 1991"
    - Nombre del funcionario incumplidor como destinatario del requerimiento
    - Mención del fallo incumplido

AUTO_INCIDENTE
  Qué es: Auto dentro del trámite del incidente (pruebas, descargos, sanción, archivo).
  Señales en filename: "AutoNoSanciona", "AutoCierraDesacato", "AutoDecretaPruebas",
                        "AutoRequerimiento", "AutoSanciona"
  Señales en contenido:
    - "incidente de desacato" ya abierto (no apertura)
    - Decreto de pruebas, audiencia de descargos, decisión de sanción o archivo
    - "ARCHÍVESE el incidente" o "se SANCIONA" o "se ABSUELVE"

EMAIL_MD
  Qué es: Correo electrónico — notificación judicial enviada por el juzgado, o
          comunicación entre partes. También PDFs generados de correos Outlook.
  Señales en filename: "Email_", email_*.md, "gmail", "rv_", "elementos_enviados"
  Señales en contenido:
    - Empieza con "De:", "Para:", "Asunto:", "Fecha:" (headers de correo)
    - O es un PDF generado de Outlook con tabla de mensajes enviados
    - "[ENCABEZADO]" seguido de metadata de envío

ACTA_REPARTO
  Qué es: Acta del sistema judicial que asigna la tutela a un juzgado específico.
  Señales en filename: "acta_individual_de_reparto", "actareparto", "ActaReparto"
  Señales en contenido:
    - "Acta individual de reparto" o "ACTA DE REPARTO"
    - Sistema de reparto automatizado de la Rama Judicial
    - Juzgado asignado, fecha y turno

AUTO_VINCULA
  Qué es: Auto que vincula a un tercero al proceso de tutela.
  Señales en filename: "AutoVincula", "vincula_a"
  Señales en contenido:
    - "VINCULESE" o "se vincula a" + nombre de entidad
    - Generalmente vincula a una EPS, IPS, municipio, o institución educativa

OFICIO_CUMPLIMIENTO
  Qué es: Oficio de la SED reportando al juzgado el cumplimiento del fallo.
  Señales en filename: "cumplimiento", "informe_cumplimiento", "CUMPLIMIENTO"
  Señales en contenido:
    - "En cumplimiento del fallo" o "Dando cumplimiento a la orden"
    - Informa acciones concretas: traslado efectuado, cupo asignado, pago realizado
    - Firma de funcionario SED

ANEXO
  Qué es: Documento de soporte o prueba adjunto (resoluciones, certificados,
          contratos, actos administrativos de nómina, soportes SIMAT).
  Señales en filename: "ANEXO", "SOPORTE", "CERT_", "PANTALLAZO", "CamScanner",
                        "registro_presupuestal", "RP_", "CDP_"
  Señales en contenido:
    - Resoluciones de nombramiento, traslado, retiro
    - Certificados de afiliación, escalafón
    - Pantallazos de sistemas (SIMAT, HUMANO)
    - Documentos que NO son acciones procesales sino pruebas

INSUMO_SED
  Qué es: Documentos internos de trabajo de la SED (estudios técnicos, insumos
          de contestación, informes de coordinación, memorandos internos).
  Señales en filename: "rt_NNNN-M", "insumo", "estudio_tecnico", "ip-gu", "oficio_interno"
  Señales en contenido:
    - Membrete SED sin dirección al juzgado
    - "Para uso interno" o informe de coordinación jurídica
    - Formato de insumo de contestación de la SED (rt_)

AUTO_OTRO
  Qué es: Auto judicial que no encaja en las categorías anteriores.
  Incluye: autos de nulidad, obedecer y cumplir, abstenerse de abrir incidente,
           autos de acumulación, desistimiento, archivo.
  Señales en filename: "nulidad", "obedezcase", "abstenerseabrir", "acumulacion",
                        "AutoDesistimiento", "AutoArchiva"
  También: "Acta de seguimiento al cumplimiento del fallo" (reunión, NO sentencia)

OTRO
  Qué es: Todo lo que no encaje en ninguna categoría anterior.
  Incluye: imágenes, screenshots, PDFs sin texto legible, documentos de otras entidades.

═══════════════════════════════════════════════════════════════
REGLAS DE PRIORIDAD (se aplican ANTES que el análisis de contenido)
═══════════════════════════════════════════════════════════════

REGLA 1 — EMAIL SIEMPRE GANA:
  Si el texto empieza con "De:", "Para:", "Asunto:", "Fecha:", o hay estructura
  de headers de correo electrónico → EMAIL_MD, sin importar qué más diga el contenido.
  Razón: un email puede HABLAR sobre una sentencia sin SER una sentencia.

REGLA 2 — ACTA DE SEGUIMIENTO ≠ SENTENCIA:
  Si el filename o contenido tiene "acta" + "seguimiento" (+ opcionalmente "fallo")
  → AUTO_OTRO, NUNCA SENTENCIA_1RA.
  Razón: es una reunión de verificación posterior al fallo, no el fallo mismo.
  Ejemplo real que falló: "ActaSeguimientoFallo2026-00045.pdf" → era una reunión.

REGLA 3 — INCIDENTE ≠ AUTO_ADMISORIO:
  Si menciona "incidente de desacato" + apertura/auto → INCIDENTE_DESACATO o AUTO_INCIDENTE,
  NUNCA AUTO_ADMISORIO aunque tenga formato de auto de admisión.

REGLA 4 — RESPUESTA_SED puede ser PDF o DOCX:
  Si tiene número FOREST, membrete Gobernación, y/o "Proyectó:" → RESPUESTA_SED.
  El error histórico era que PDFs de respuesta caían a OTRO por no tener extensión .docx.

REGLA 5 — BOILERPLATE ≠ IMPUGNACIÓN PRESENTADA:
  La frase "procede el recurso de impugnación" en los CONSIDERANDOS de una sentencia
  es boilerplate (le informa a las partes que PUEDEN impugnar). NO es IMPUGNACION.
  Solo clasifica como IMPUGNACION si alguien PRESENTA el recurso.

═══════════════════════════════════════════════════════════════
FORMATO DE RESPUESTA
═══════════════════════════════════════════════════════════════

Devuelve SOLO este JSON (sin markdown, sin explicación):
{
  "tipo": "<UNO_DE_LOS_18_TIPOS>",
  "instancia": "<1RA|2DA|N/A>",
  "confianza": "<alta|media|baja>",
  "señales_usadas": ["señal1", "señal2"],
  "razon": "<1 oración explicando la clasificación>"
}

Si el documento es ininteligible (imagen sin OCR, texto basura) → tipo: "OTRO", confianza: "baja".
"""


def _call_deepseek(messages: list[dict]) -> str:
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LLM_KEY}"}
    req = urllib.request.Request(
        LLM_URL + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    raw = urllib.request.urlopen(req, timeout=60).read().decode()
    return json.loads(raw)["choices"][0]["message"]["content"] or ""


def classify_one(doc_id: int, filename: str, text: str, ground_truth_canonical: str) -> dict:
    result_file = RESULTS_DIR / f"{doc_id}.json"
    if result_file.exists():
        return {**json.loads(result_file.read_text()), "cached": True}

    # head + tail del texto (patrón validado — suficiente para clasificar)
    head = text[:2000] if text else ""
    tail = text[-1000:] if len(text) > 2500 else ""
    content_snippet = head + ("\n[...]\n" + tail if tail else "")

    user_msg = f"""Clasifica este documento.

NOMBRE DE ARCHIVO: {filename}

CONTENIDO (extracto):
{content_snippet}"""

    t0 = time.perf_counter()
    try:
        raw = _call_deepseek([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ])
        elapsed = int((time.perf_counter() - t0) * 1000)
        result = json.loads(raw)
        tipo_propuesto = result.get("tipo", "OTRO")
        correcto = tipo_propuesto == ground_truth_canonical
        output = {
            "doc_id":        doc_id,
            "filename":      filename,
            "ground_truth":  ground_truth_canonical,
            "tipo_propuesto": tipo_propuesto,
            "instancia":     result.get("instancia", "N/A"),
            "confianza":     result.get("confianza", ""),
            "señales":       result.get("señales_usadas", []),
            "razon":         result.get("razon", ""),
            "correcto":      correcto,
            "elapsed_ms":    elapsed,
        }
    except Exception as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        output = {
            "doc_id": doc_id, "filename": filename,
            "ground_truth": ground_truth_canonical,
            "tipo_propuesto": "ERROR", "correcto": False,
            "error": str(exc)[:200], "elapsed_ms": elapsed,
        }

    result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    return output


def sample_docs(engine, n_per_type: int = 20) -> list[dict]:
    """Muestra estratificada: n_per_type por cada tipo canónico."""
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        docs = db.query(Document).filter(
            Document.extracted_text.isnot(None),
            sqlalchemy.func.length(Document.extracted_text) > 200,
            Document.doc_type.isnot(None),
        ).all()

        # agrupar por canónico
        by_canonical: dict[str, list] = {}
        for d in docs:
            canon = CANONICAL_MAP.get(d.doc_type or "", None)
            if canon is None:
                continue
            by_canonical.setdefault(canon, []).append(d)

        sample = []
        for canon, group in sorted(by_canonical.items()):
            chosen = random.sample(group, min(n_per_type, len(group)))
            for d in chosen:
                sample.append({
                    "doc_id":    d.id,
                    "filename":  d.filename or "",
                    "text":      d.extracted_text or "",
                    "gt_raw":    d.doc_type or "",
                    "gt_canon":  canon,
                })
        return sample
    finally:
        db.close()


def build_report(results: list[dict]) -> str:
    from collections import Counter, defaultdict
    total = len(results)
    correct = sum(1 for r in results if r.get("correcto"))
    errors  = sum(1 for r in results if r.get("tipo_propuesto") == "ERROR")
    acc = 100 * correct / max(total - errors, 1)

    # accuracy por tipo
    by_type: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        if r.get("tipo_propuesto") != "ERROR":
            by_type[r["ground_truth"]].append(r["correcto"])

    # confusion: ground_truth → Counter(propuesto)
    confusion: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        if r.get("tipo_propuesto") not in ("ERROR",):
            confusion[r["ground_truth"]][r["tipo_propuesto"]] += 1

    lines = [
        "═══════════════════════════════════════════════════════════════",
        " REPORTE — Clasificador DeepSeek vs clasificador filename",
        "═══════════════════════════════════════════════════════════════",
        f" Total docs: {total}   Correctos: {correct}   Errores API: {errors}",
        f" Accuracy global: {acc:.1f}%",
        "",
        f" {'TIPO':<30} {'N':>4}  {'ACC%':>6}  Errores frecuentes",
        " " + "-"*70,
    ]
    for tipo, verdicts in sorted(by_type.items(), key=lambda x: -len(x[1])):
        n = len(verdicts)
        acc_t = 100 * sum(verdicts) / n
        wrong = [f"{t}×{c}" for t, c in confusion[tipo].items() if t != tipo]
        wrong_str = ", ".join(wrong[:3]) if wrong else "—"
        lines.append(f" {tipo:<30} {n:>4}  {acc_t:>5.1f}%  {wrong_str}")

    # DESCONOCIDO — qué propone DeepSeek para los que el sistema no sabe
    desconocidos = [r for r in results if r.get("ground_truth") == "DESCONOCIDO"]
    if desconocidos:
        lines += ["",
                  f" DESCONOCIDO ({len(desconocidos)} docs) — propuestas de DeepSeek:"]
        cnt = Counter(r["tipo_propuesto"] for r in desconocidos)
        for t, c in cnt.most_common():
            lines.append(f"   {t}: {c}")

    lines += [
        "",
        f" Avg latencia: {sum(r.get('elapsed_ms',0) for r in results)/max(total,1):.0f}ms/doc",
        "═══════════════════════════════════════════════════════════════",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clasificador DeepSeek — Fase 2 experimento")
    parser.add_argument("--sample",  type=int, default=20, help="Docs por tipo a muestrear")
    parser.add_argument("--workers", type=int, default=4,  help="Threads paralelos")
    parser.add_argument("--seed",    type=int, default=42, help="Semilla aleatoria")
    parser.add_argument("--report",  action="store_true",  help="Solo generar reporte de resultados existentes")
    args = parser.parse_args()

    if not LLM_KEY:
        print("ERROR: V9_LLM_API_KEY no seteada."); sys.exit(1)

    random.seed(args.seed)

    engine = sqlalchemy.create_engine(
        f"sqlite:///{PROD_DB}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    if args.report:
        results = [json.loads(p.read_text()) for p in sorted(RESULTS_DIR.glob("*.json"))
                   if p.name != "classify.log"]
        print(build_report(results))
        REPORT_FILE.write_text(build_report(results), encoding="utf-8")
        return

    docs = sample_docs(engine, n_per_type=args.sample)
    # filtrar ya procesados
    done = {int(p.stem) for p in RESULTS_DIR.glob("*.json")}
    pending = [d for d in docs if d["doc_id"] not in done]

    log.info("Muestra total: %d  Pendientes: %d  Workers: %d", len(docs), len(pending), args.workers)

    results_all = [json.loads((RESULTS_DIR / f"{d['doc_id']}.json").read_text())
                   for d in docs if d["doc_id"] in done]

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(classify_one, d["doc_id"], d["filename"], d["text"], d["gt_canon"]): d
            for d in pending
        }
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            results_all.append(r)
            status = "✓" if r.get("correcto") else ("ERR" if r.get("tipo_propuesto") == "ERROR" else "✗")
            log.info("[%d/%d] %s doc%d  GT=%-25s propuesto=%-25s %dms",
                     i, len(pending), status, r["doc_id"],
                     r["ground_truth"], r.get("tipo_propuesto","?"), r.get("elapsed_ms",0))

    elapsed = time.perf_counter() - t0
    report = build_report(results_all)
    print(report)
    REPORT_FILE.write_text(report, encoding="utf-8")
    log.info("Tiempo total: %.1fs  Reporte: %s", elapsed, REPORT_FILE)


if __name__ == "__main__":
    import sqlalchemy.sql.expression as _  # noqa: F401 — trigger sqlalchemy import
    import sqlalchemy.func as sqlalchemy_func  # noqa: F401
    # fix: sqlalchemy.func no está en el namespace global del script
    import sqlalchemy as sqlalchemy_mod
    sqlalchemy.func = sqlalchemy_mod.func
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    main()
