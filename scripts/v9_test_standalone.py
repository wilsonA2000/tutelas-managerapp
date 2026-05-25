#!/usr/bin/env python3
"""Test standalone del pipeline v9 — NO requiere DB ni pymupdf.

Alimenta texto de ejemplo (simulando un PDF ya leído) directamente a
regex_pass + catalog_resolve. Sirve para verificar que la lógica núcleo
funciona antes de tener el venv listo con sqlalchemy/pymupdf.

Uso:
    python3 scripts/v9_test_standalone.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.v9.types import ExtractedFields, FieldSource  # noqa: E402
from backend.v9 import regex_pass, catalog_resolve  # noqa: E402
from backend.v9.doc_io import DocText  # noqa: E402


# ============================================================
# Casos de prueba con texto sintético realista
# ============================================================

CASE_1_AUTO_ADMISORIO = """
JUZGADO PRIMERO PROMISCUO MUNICIPAL DE BUCARAMANGA

AUTO ADMITE TUTELA

Bucaramanga, 15 de marzo de 2026

Por reparto correspondió al despacho la acción de tutela radicada bajo el
número 68001-40-09-001-2026-00095-00 promovida por el señor JUAN PEREZ GOMEZ
identificada con C.C. 91234567 contra GOBERNACION DE SANTANDER.

ACCIONANTE: JUAN PEREZ GOMEZ
DEMANDADO: GOBERNACION DE SANTANDER - SED

Fecha de admisión: 15/03/2026

El número de radicado es 20260009501

SE RESUELVE:
1. AVOCAR conocimiento de la presente acción de tutela.
"""


CASE_1_SENTENCIA = """
JUZGADO PRIMERO PROMISCUO MUNICIPAL DE BUCARAMANGA

SENTENCIA DE TUTELA No. 045 de 2026

Bucaramanga, 25 de marzo de 2026

Radicado: 68001-40-09-001-2026-00095-00
ACCIONANTE: JUAN PEREZ GOMEZ
ACCIONADO: GOBERNACION DE SANTANDER

RESUELVE:
PRIMERO: CONCEDER el amparo del derecho fundamental a la salud invocado por
el señor JUAN PEREZ GOMEZ.
SEGUNDO: ORDENAR a la Gobernación de Santander - Secretaría de Educación,
en cabeza del Director de Talento Humano Docente, dar cumplimiento en el
término de cuarenta y ocho (48) horas.
"""


CASE_1_RESPUESTA = """
GOBERNACIÓN DE SANTANDER
SECRETARÍA DE EDUCACIÓN

Bucaramanga, 20 de marzo de 2026

Señor Juez
JUZGADO PRIMERO PROMISCUO MUNICIPAL

REF: Radicado 2026-00095 - Acción de tutela JUAN PEREZ GOMEZ
Dependencia: Dirección de Talento Humano Docente — Grupo Nómina

Respetado Juez,

En atención a su requerimiento, nos permitimos pronunciarnos respecto de la
acción de tutela radicada con el número arriba citado.

[...]

Cordialmente,

Proyectó: Juan Diego Cruz Lizcano
         Abogado Apoyo Jurídico
         Dirección de Talento Humano Docente
"""

# Dos incidentes de desacato sucesivos (común en tutelas no cumplidas)
CASE_1_INCIDENTE_1 = """
JUZGADO PRIMERO PROMISCUO MUNICIPAL DE BUCARAMANGA

INCIDENTE DE DESACATO

Bucaramanga, 02/04/2026

Por solicitud del accionante JUAN PEREZ GOMEZ, se abre incidente de desacato
contra el responsable Dr. CARLOS ALBERTO MENDOZA RUEDA, Secretario de Educación
Departamental, por incumplimiento de la sentencia de tutela 2026-00095.

Apertura de incidente: 02/04/2026
"""

CASE_1_INCIDENTE_2 = """
JUZGADO PRIMERO PROMISCUO MUNICIPAL DE BUCARAMANGA

SEGUNDO INCIDENTE DE DESACATO

Bucaramanga, 18/04/2026

Persistiendo el incumplimiento, se abre nuevo incidente de desacato.
Apertura de incidente: 18/04/2026
Responsable: Dr. CARLOS ALBERTO MENDOZA RUEDA
"""


def main():
    print("=" * 70)
    print("TEST STANDALONE — v9 regex_pass + catalog_resolve")
    print("=" * 70)

    docs = [
        DocText("auto_admisorio.pdf", "auto_admisorio.pdf", CASE_1_AUTO_ADMISORIO, "pymupdf", pages=1),
        DocText("sentencia.pdf", "sentencia.pdf", CASE_1_SENTENCIA, "pymupdf", pages=1),
        DocText("respuesta.docx", "respuesta.docx", CASE_1_RESPUESTA, "python-docx"),
        DocText("incidente_1.pdf", "incidente_1.pdf", CASE_1_INCIDENTE_1, "pymupdf", pages=1),
        DocText("incidente_2.pdf", "incidente_2.pdf", CASE_1_INCIDENTE_2, "pymupdf", pages=1),
    ]

    # Simular que el Excel CONTROL TUTELAS aporta oficina_responsable
    excel_row = {"oficina_responsable": "Grupo Nómina"}

    fields = ExtractedFields()
    regex_pass.run(docs, fields)

    # Simular excel_reconcile (sin importar el módulo si tiene deps)
    from backend.v9 import excel_reconcile
    excel_reconcile.run(fields, excel_row)

    catalog_resolve.run(fields)

    # Imprimir resultados
    print(f"\nCompletitud: {fields.completitud()}%")
    print(f"\nCampos con valor:")
    for k, v in fields.values.items():
        if v:
            src = fields.sources[k].value
            print(f"  [{src:7}] {k:30} = {v[:80]}")

    empty = fields.missing_fields()
    print(f"\nCampos vacíos ({len(empty)}/28): {', '.join(empty)}")

    print(f"\nCanónicos:")
    print(f"  abogado_canonical:    {fields.abogado_canonical} (conf={fields.abogado_canonical_confidence:.2f})")
    print(f"  dependencia_canonical: {fields.dependencia_canonical} (conf={fields.dependencia_canonical_confidence:.2f})")
    print(f"  Jerarquía SED:")
    print(f"    L1 direccion: {fields.direccion}")
    print(f"    L2 grupo:     {fields.grupo}")
    print(f"    L3 equipo:    {fields.equipo}")

    # Aserciones básicas
    print("\n" + "=" * 70)
    print("VERIFICACIONES")
    print("=" * 70)
    checks = [
        ("radicado_23_digitos", "68001400900120260009500", fields.values["radicado_23_digitos"]),
        ("radicado_forest", "20260009501", fields.values["radicado_forest"]),
        ("accionante", "JUAN PEREZ GOMEZ", fields.values["accionante"]),
        # sentido_fallo_1st YA NO lo extrae regex_pass (autoridad única = field_extractor_pass,
        # commit b1fd0ec). El standalone solo corre regex_pass → debe quedar VACÍO. La
        # clasificación CONCEDE/NIEGA/etc. se prueba aparte en _classify_sentido_fallo (abajo)
        # y end-to-end sobre la DB en v9_test_db.py.
        ("sentido_fallo_1st (regex_pass NO lo setea)", "", fields.values.get("sentido_fallo_1st", "")),
        ("impugnacion", "NO", fields.values["impugnacion"]),
        ("tipo_actuacion", "TUTELA", fields.values["tipo_actuacion"]),
        ("abogado_canonical", "JUAN DIEGO CRUZ LIZCANO", fields.abogado_canonical),
        # Nuevos campos v9.1: incidentes múltiples
        ("incidente", "SI", fields.values["incidente"]),
        ("incidente_2", "SI", fields.values["incidente_2"]),
        ("incidente_3", "NO", fields.values["incidente_3"]),
        ("fecha_apertura_incidente", "02/04/2026", fields.values["fecha_apertura_incidente"]),
        ("fecha_apertura_incidente_2", "18/04/2026", fields.values["fecha_apertura_incidente_2"]),
        # Jerarquía SED derivada
        ("dependencia_canonical", "NOMINA", fields.dependencia_canonical),
        ("direccion (L1)", "DIRECCION_TALENTO_DOCENTE", fields.direccion),
        ("grupo (L2)", "NOMINA", fields.grupo),
        ("equipo (L3)", None, fields.equipo),
    ]
    # Añadir checks de los extractores a nivel CASE que NO necesitan DB
    # (derecho_vulnerado: anclas+tags; juzgado: parser del remitente Rama Judicial).
    extra = _checks_field_extractor()

    failures = 0
    total = len(checks) + len(extra)
    for name, expected, actual in checks + extra:
        ok = actual == expected
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name:32} esperado={expected!r:45} actual={actual!r}")
        if not ok:
            failures += 1
    print()
    if failures == 0:
        print(f"✅ {total}/{total} verificaciones pasaron")
    else:
        print(f"❌ {failures}/{total} fallaron — revisar regex_pass / catalog_resolve / field_extractor")
    print("=" * 70)
    return 0 if failures == 0 else 1


def _checks_field_extractor() -> list[tuple]:
    """Checks de los helpers puros de `field_extractor` (campos 7 y 8).

    No requieren DB. Si sqlalchemy/el módulo no importan (venv incompleto), se
    omiten en vez de fallar.
    """
    try:
        from backend.v9.field_extractor import (
            _extract_derechos_from_text, _juzgado_from_rj_sender, _clean_juzgado,
            _RE_CIUDAD_TAIL_JUZGADO, _RE_CIUDAD_DE_JUZGADO, _ciudad_clean,
            _parse_es_dates, _fecha_auto_from_text, _first_date_near_year,
            _extract_pretensiones_from_text, _clean_abogado_name, _resolve_abogado_combined,
            _ASUNTO_TO_L1, _classify_sentido_fallo,
            _RE_OBS_MEDIDA_PROVISIONAL, _RE_OBS_SEP,
            _normalize_entity_list, _canon_entity, _looks_like_accionado_value,
        )
        from backend.cognition.legal_schema import clasificar_sed_tematica, categoria_tematica_de_asunto
        from backend.v9.regex_pass import _extract_ciudad as _regex_ciudad
    except Exception as e:  # noqa: BLE001
        print(f"\n  (checks de field_extractor omitidos: {e})")
        return []

    def _asunto_cat(text: str):
        return clasificar_sed_tematica(text)[3]

    def _first_date(text: str):
        ds = _parse_es_dates(text)
        return ds[0][1] if ds else None

    def _ciudad_de(juz: str):
        m = _RE_CIUDAD_TAIL_JUZGADO.search(juz) or _RE_CIUDAD_DE_JUZGADO.search(juz)
        return _ciudad_clean(m.group(1)) if m else None

    out: list[tuple] = []
    # --- DERECHO_VULNERADO (campo 7): anclas + tags + orden de prioridad ---
    out.append((
        "derecho: educación+debido proceso",
        "EDUCACION - DEBIDO_PROCESO",
        _join(_extract_derechos_from_text(
            "El accionante invoca la protección de sus derechos fundamentales a la educación "
            "y al debido proceso, los cuales considera vulnerados por la Secretaría de Educación.")),
    ))
    out.append((
        "derecho: petición/salud (multi, orden vocab)",
        "SALUD - PETICION - SEGURIDAD_SOCIAL - MINIMO_VITAL",
        _join(_extract_derechos_from_text(
            "...derechos fundamentales a la seguridad social, petición, mínimo vital y salud, "
            "los cuales considera vulnerados...")),
    ))
    out.append((
        "derecho: boilerplate jurisprudencial → vacío",
        "",
        _join(_extract_derechos_from_text(
            "La acción de tutela protege los derechos fundamentales cuando no se dispone de "
            "otro medio de defensa judicial, para evitar un perjuicio irremediable.")),
    ))
    out.append((
        "derecho: 'Secretaría de Educación' no es derecho",
        "VIDA",
        _join(_extract_derechos_from_text(
            "...derechos fundamentales a la vida digna, los cuales considera vulnerados por la "
            "Secretaría de Educación del Departamento de Santander.")),
    ))
    # --- JUZGADO (campo 8): parser del remitente Rama Judicial ---
    out.append((
        "juzgado: remitente cendoj municipal",
        "JUZGADO 04 CIVIL MUNICIPAL DE GIRÓN (SANTANDER)",
        _juzgado_from_rj_sender("De: Juzgado 04 Civil Municipal - Santander - Girón <j04cmpalgiron@cendoj.ramajudicial.gov.co>"),
    ))
    out.append((
        "juzgado: remitente cendoj circuito + municipio compuesto",
        "JUZGADO 02 PROMISCUO CIRCUITO DE SAN VICENTE DE CHUCURÍ (SANTANDER)",
        _juzgado_from_rj_sender("Para: Juzgado 02 Promiscuo Circuito - Santander - San Vicente de Chucurí <j02prctosvich@cendoj.ramajudicial.gov.co>"),
    ))
    out.append((
        "juzgado: secretaría Sala de Tribunal",
        "TRIBUNAL SUPERIOR DEL DISTRITO JUDICIAL DE BUCARAMANGA - SALA CIVIL FAMILIA",
        _juzgado_from_rj_sender("De: Notificaciones Secretaría Sala Civil Familia - Santander - Bucaramanga <notifscrscfbuc@cendoj.ramajudicial.gov.co>"),
    ))
    out.append((
        "juzgado: limpieza de header con basura",
        "JUZGADO PRIMERO PROMISCUO MUNICIPAL DE BARICHARA",
        _clean_juzgado("JUZGADO PRIMERO PROMISCUO MUNICIPAL DE BARICHARA Veintinueve de febrero de dos mil veintiséis"),
    ))
    # --- CIUDAD (campo 9): municipio derivado del nombre del juzgado ---
    out.append((
        "ciudad: municipio Santander del juzgado",
        "GIRÓN",
        _ciudad_de("JUZGADO 04 CIVIL MUNICIPAL DE GIRÓN (SANTANDER)"),
    ))
    out.append((
        "ciudad: municipio compuesto (conserva tildes)",
        "SAN VICENTE DE CHUCURÍ",
        _ciudad_de("JUZGADO 02 PROMISCUO CIRCUITO DE SAN VICENTE DE CHUCURÍ (SANTANDER)"),
    ))
    out.append((
        "ciudad: juzgado de fuera de Santander",
        "TUNJA",
        _ciudad_de("JUZGADO QUINTO PENAL DEL CIRCUITO DE TUNJA"),
    ))
    out.append((
        "ciudad: derivado de 2da no se confunde (DERIVADO)",
        "SAN GIL",
        _ciudad_de("JUZGADO PROMISCUO DEL CIRCUITO DE SAN GIL (DERIVADO)"),
    ))
    # regex_pass._extract_ciudad (fallback): compuestos y atributos del juzgado
    out.append((
        "ciudad (regex_pass): compuesto 'SAN VICENTE DE CHUCURÍ' (antes solo 'SAN')",
        "SAN VICENTE DE CHUCURÍ",
        _regex_ciudad("JUZGADO 02 PROMISCUO MUNICIPAL DE SAN VICENTE DE CHUCURÍ (SANTANDER)"),
    ))
    out.append((
        "ciudad (regex_pass): 'SABANA DE TORRES' (antes solo 'SABANA')",
        "SABANA DE TORRES",
        _regex_ciudad("JUZGADO PRIMERO PROMISCUO MUNICIPAL DE SABANA DE TORRES"),
    ))
    out.append((
        "ciudad (regex_pass): atributo del juzgado no es ciudad ('EJECUCIÓN DE SENTENCIAS DE X' → X)",
        "BUCARAMANGA",
        _regex_ciudad("JUZGADO PRIMERO CIVIL MUNICIPAL DE EJECUCIÓN DE SENTENCIAS DE BUCARAMANGA"),
    ))
    # --- FECHA_INGRESO (campo 10): parser de fechas en español ---
    out.append((
        "fecha: dateline numérico",
        "13/04/2026",
        _first_date("Bucaramanga, 13/04/2026 — AUTO ADMITE TUTELA"),
    ))
    out.append((
        "fecha: dateline escrito",
        "27/03/2026",
        _first_date("Bucaramanga, 27 de marzo de 2026"),
    ))
    out.append((
        "fecha: 'a los X (NN) días del mes de ... dos mil ...'",
        "15/03/2026",
        _first_date("a los quince (15) días del mes de marzo de dos mil veintiséis"),
    ))
    out.append((
        "fecha: del auto (dateline arriba) con cota de año",
        "27/03/2026",
        _fecha_auto_from_text("JUZGADO PRIMERO PROMISCUO MUNICIPAL DE GÁMBITA\n\nAUTO ADMITE TUTELA\n\nGámbita, 27 de marzo de 2026\n\nPor reparto correspondió...", 2026),
    ))
    out.append((
        "fecha: filtra año fuera de rango (cita vieja)",
        "06/02/2026",
        _first_date_near_year([(0, "28/01/2020"), (50, "06/02/2026")], 2026),
    ))
    # --- ASUNTO (campo 11): vocabulario controlado SED ---
    out.append((
        "asunto: 'traslado del docente' → TRASLADO",
        "TRASLADO",
        _asunto_cat("Solicito el traslado del docente Juan Pérez por motivos de salud, según reubicación pedida."),
    ))
    out.append((
        "asunto: 'transporte escolar' → TRANSPORTE_ESCOLAR",
        "TRANSPORTE_ESCOLAR",
        _asunto_cat("El accionante pide se garantice el transporte escolar / ruta escolar para los menores de la vereda."),
    ))
    out.append((
        "asunto: 'incidente de desacato' → INCIDENTE_DESACATO",
        "INCIDENTE_DESACATO",
        _asunto_cat("Se solicita abrir incidente de desacato por incumplimiento del fallo de tutela."),
    ))
    out.append((
        "asunto: 'nombramiento de docente' → NOMBRAMIENTO",
        "NOMBRAMIENTO",
        _asunto_cat("Solicito el nombramiento de un docente de matemáticas para la institución educativa."),
    ))
    out.append((
        "asunto: 'traslado del cargo' (lo SOLICITA el actor) → TRASLADO",
        "TRASLADO",
        _asunto_cat("Respetuosamente solicito el traslado del cargo a otra institución más cercana a mi domicilio."),
    ))
    # Regresión (DeepSeek): el ACTO PROCESAL "auto de traslado" / "traslado de la
    # demanda" NO es el asunto TRASLADO (aparecía en casi todos los expedientes).
    out.append((
        "asunto: 'auto de traslado de la demanda' NO matchea TRASLADO",
        None,
        _asunto_cat("Por medio del presente auto se corre traslado de la demanda al accionado por el término de un día."),
    ))
    out.append((
        "asunto: subject 'RESPUESTA AUTO DE TRASLADO' NO matchea TRASLADO",
        None,
        _asunto_cat("RESPUESTA AUTO DE TRASLADO - acción de tutela radicado 2026-00099"),
    ))
    # Regresión: substring laxo — "provisional" ⊅ NOMBRAMIENTO, "encargado" ⊅ NOMBRAMIENTO.
    out.append((
        "asunto: 'medida provisional' sola NO matchea NOMBRAMIENTO",
        None,
        _asunto_cat("Se solicita decretar como medida provisional la suspensión del acto administrativo demandado."),
    ))
    out.append((
        "asunto: 'docente encargado' NO matchea NOMBRAMIENTO ('encargado' ≠ 'encargo')",
        None,
        _asunto_cat("El docente encargado del aula renunció y los estudiantes llevan dos semanas sin clase."),
    ))
    # --- ACCIONADOS (campos 5/6): preservar TODAS las entidades listadas ---
    # Regresión (DeepSeek, ~191 casos): antes se descartaba todo lo que no fuera GOB/SecEdu.
    out.append((
        "accionados: lista mixta preserva todas (GOB/SecEdu canónicas, resto tal cual)",
        "FONDO DE PENSIONES Y CESANTÍAS PORVENIR S.A - GOBERNACIÓN DE SANTANDER - "
        "SECRETARÍA DE EDUCACIÓN DEL DEPARTAMENTO DE SANTANDER - FONDO EDUCATIVO DEPARTAMENTAL DE SANTANDER",
        _normalize_entity_list(
            "FONDO DE PENSIONES Y CESANTÍAS PORVENIR S.A. - Gobernación de Santander - "
            "Secretaría de Educación - Fondo Educativo Departamental de Santander"),
    ))
    out.append((
        "accionados: una entidad por línea → todas, separadas por ' - '",
        "LICEO INFANTIL SEMILLITAS - SECRETARÍA DE EDUCACIÓN DE BARRANCABERMEJA - SIMAT",
        _normalize_entity_list("Liceo Infantil Semillitas\nSecretaría de Educación de Barrancabermeja\nSIMAT"),
    ))
    out.append((
        "accionados: SecEdu MUNICIPAL no se confunde con la DEPARTAMENTAL",
        "SECRETARÍA DE EDUCACIÓN MUNICIPAL DE GIRÓN - SECRETARÍA DE EDUCACIÓN DEL DEPARTAMENTO DE SANTANDER",
        _normalize_entity_list("Secretaría de Educación Municipal de Girón - Secretaría de Educación del Departamento de Santander"),
    ))
    out.append((
        "accionados: 'Departamento de Santander' = Gobernación (misma persona jurídica)",
        "GOBERNACIÓN DE SANTANDER",
        _canon_entity("Departamento de Santander"),
    ))
    out.append((
        "accionados: guarda rechaza placeholder '(ninguno)'",
        False,
        _looks_like_accionado_value("(ninguno)"),
    ))
    out.append((
        "accionados: guarda acepta 'LICEO INFANTIL SEMILLITAS' (antes se rechazaba)",
        True,
        _looks_like_accionado_value("LICEO INFANTIL SEMILLITAS"),
    ))
    # --- PRETENSIONES (campo 12): transcripción de la sección de la demanda ---
    out.append((
        "pretensiones: sección con header PRETENSIONES",
        "PRIMERO: Se tutele el derecho a la educación. SEGUNDO: Se ordene a la SED nombrar un docente.",
        _extract_pretensiones_from_text(
            "I. HECHOS\n...\nIII. PRETENSIONES\n\nPRIMERO: Se tutele el derecho a la educación.\n"
            "SEGUNDO: Se ordene a la SED nombrar un docente.\n\nIV. PRUEBAS\n- documento 1\n"),
    ))
    out.append((
        "pretensiones: arranque 'solicito a su despacho:'",
        "1. TUTELAR mis derechos fundamentales. 2. ORDENAR a la Secretaría de Educación responder en 48 horas.",
        _extract_pretensiones_from_text(
            "Con fundamento en los hechos, respetuosamente solicito a su despacho:\n"
            "1. TUTELAR mis derechos fundamentales.\n2. ORDENAR a la Secretaría de Educación responder en 48 horas.\n"
            "\nIV. FUNDAMENTOS DE DERECHO\nEl artículo 86 ...\n"),
    ))
    # --- OFICINA + ABOGADO_RESPONSABLE (campo 13) ---
    out.append((
        "abogado: limpia 'NOMBRE - JEFE APOYO JURÍDICO'",
        "MARÍA CRISTINA VILLAMIZAR SCHILLER",
        _clean_abogado_name("MARÍA CRISTINA VILLAMIZAR SCHILLER - JEFE APOYO JURÍDICO"),
    ))
    out.append((
        "abogado: rechaza 'ABOGADA CONTRATISTA GRUPO TALENTO HUMANO'",
        None,
        _clean_abogado_name("ABOGADA CONTRATISTA APOYO JURÍDICO GRUPO TALENTO HUMANO"),
    ))
    out.append((
        "abogado: limpia 'NOMBRE EXT 1422'",
        "LEIDY JOHANA CERÓN",
        _clean_abogado_name("LEIDY JOHANA CERÓN EXT 1422"),
    ))
    out.append((
        "abogado: resuelve al roster Grupo Jurídico (correo en el doc)",
        "JUAN DIEGO CRUZ LIZCANO",
        _resolve_abogado_combined("J.D. CRUZ - CONTRATISTA", doc_text="... Proyectó: J.D. Cruz, correo cruzlizcano@yahoo.com ...")[0],
    ))
    out.append((
        "oficina: TRASLADO → DIRECCION_TALENTO_DOCENTE",
        "DIRECCION_TALENTO_DOCENTE",
        _ASUNTO_TO_L1.get("TRASLADO"),
    ))
    # --- SENTIDO_FALLO_1ra (campo 14) ---
    out.append((
        "fallo: 'TUTELAR los derechos' → CONCEDE",
        "CONCEDE",
        _classify_sentido_fallo("RESUELVE: PRIMERO. TUTELAR los derechos fundamentales del accionante. SEGUNDO. ORDENAR..."),
    ))
    out.append((
        "fallo: 'DECLARAR IMPROCEDENTE' → IMPROCEDENTE",
        "IMPROCEDENTE",
        _classify_sentido_fallo("RESUELVE: PRIMERO. DECLARAR IMPROCEDENTE la presente acción de tutela."),
    ))
    out.append((
        "fallo: 'carencia actual de objeto' → CARENCIA_OBJETO",
        "CARENCIA_OBJETO",
        _classify_sentido_fallo("RESUELVE: PRIMERO. Declarar la CARENCIA ACTUAL DE OBJETO por hecho superado parcial."),
    ))
    out.append((
        "fallo: 'NEGAR el amparo' → NIEGA",
        "NIEGA",
        _classify_sentido_fallo("RESUELVE: PRIMERO. NEGAR el amparo del derecho a la educación solicitado."),
    ))
    out.append((
        "fallo: 'niega la nulidad' + 'tutela' → CONCEDE (no NIEGA: la negación es accesoria)",
        "CONCEDE",
        _classify_sentido_fallo("RESUELVE: PRIMERO. Niega la nulidad propuesta. SEGUNDO. TUTELAR los derechos fundamentales."),
    ))
    out.append((
        "fallo: 'no tutelar el amparo por improcedente' → IMPROCEDENTE (taxonomía: 'improcedente' es específico)",
        "IMPROCEDENTE",
        _classify_sentido_fallo("RESUELVE: PRIMERO. No tutelar el amparo solicitado por improcedente."),
    ))
    out.append((
        "fallo: 'no tutelar el amparo solicitado' (sin improcedente) → NIEGA",
        "NIEGA",
        _classify_sentido_fallo("RESUELVE: PRIMERO. No tutelar el amparo solicitado por el accionante."),
    ))
    # --- CATEGORIA_TEMATICA (campo 18): derivada del asunto (grupo L2 SED) ---
    out.append((
        "categoria: TRASLADO → CARRERA_DOCENTE",
        "CARRERA_DOCENTE",
        categoria_tematica_de_asunto("TRASLADO"),
    ))
    out.append((
        "categoria: TRANSPORTE_ESCOLAR → PERMANENCIA_ESCOLAR (fallback L2=None)",
        "PERMANENCIA_ESCOLAR",
        categoria_tematica_de_asunto("TRANSPORTE_ESCOLAR"),
    ))
    out.append((
        "categoria: INCIDENTE_DESACATO → APOYO_JURIDICO",
        "APOYO_JURIDICO",
        categoria_tematica_de_asunto("INCIDENTE_DESACATO"),
    ))
    out.append((
        "categoria: NOMBRAMIENTO → ADMINISTRACION_PLANTA",
        "ADMINISTRACION_PLANTA",
        categoria_tematica_de_asunto("NOMBRAMIENTO"),
    ))
    out.append((
        "categoria: SIN_DETERMINAR → None (default lo decide el extractor)",
        None,
        categoria_tematica_de_asunto("SIN_DETERMINAR"),
    ))
    out.append((
        "categoria: OTRO (LLM) → None",
        None,
        categoria_tematica_de_asunto("OTRO"),
    ))
    # --- OBSERVACIONES (campo 18): banderas sobre el escrito de tutela ---
    def _sep_labels(text: str):
        return [label for label, rx in _RE_OBS_SEP if rx.search(text)]
    out.append((
        "obs: 'medida provisional' detectada",
        True,
        bool(_RE_OBS_MEDIDA_PROVISIONAL.search(
            "Solicito que como medida provisional se ordene a la SED reintegrar al docente.")),
    ))
    out.append((
        "obs: sin medida provisional → no detecta",
        False,
        bool(_RE_OBS_MEDIDA_PROVISIONAL.search(
            "Solicito que se ordene a la SED dar respuesta de fondo en 48 horas.")),
    ))
    out.append((
        "obs: SEP discapacidad ('persona con discapacidad')",
        ["persona con discapacidad"],
        _sep_labels("El accionante actúa en nombre de su hijo, persona con discapacidad cognitiva."),
    ))
    out.append((
        "obs: SEP menor de edad ('interés superior del menor')",
        ["menor de edad"],
        _sep_labels("Se debe proteger el interés superior del menor matriculado en la I.E."),
    ))
    out.append((
        "obs: texto neutro → sin banderas SEP",
        [],
        _sep_labels("El docente solicita su traslado por necesidad del servicio."),
    ))
    return out


def _join(tags: list) -> str:
    return " - ".join(tags) if tags else ""


if __name__ == "__main__":
    sys.exit(main())
