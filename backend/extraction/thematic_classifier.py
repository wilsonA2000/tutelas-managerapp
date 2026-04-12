"""Clasificador temático de tutelas basado en keywords.

Clasifica cada caso en una categoría temática usando el texto de
ASUNTO + OBSERVACIONES + PRETENSIONES + DERECHO_VULNERADO.
100% local, sin IA. Cada categoría mapea a una oficina responsable
de la Secretaría de Educación de Santander.
"""

import re

# ── Categorías con keywords ──────────────────────────────────────────────────

CATEGORIES: dict[str, list[str]] = {
    "INFRAESTRUCTURA": [
        r"infraestructura", r"construcci[oó]n", r"planta f[ií]sica",
        r"adecuaci[oó]n.*sede", r"mantenimiento.*escuela", r"mantenimiento.*colegio",
        r"reparaci[oó]n", r"ba[nñ]os?", r"techo", r"aula",
        r"restaurante escolar", r"transporte escolar", r"ruta escolar",
        r"sede educativa.*riesgo", r"derrumbe", r"accesibilidad.*sede",
        r"mejoramiento.*colegio", r"mejoramiento.*escuela",
        r"dotaci[oó]n.*sede", r"mobiliario escolar",
    ],
    "INCLUSION": [
        r"inclusi[oó]n", r"discapacidad", r"necesidades educativas especiales",
        r"NEE", r"ajustes razonables", r"educaci[oó]n inclusiva",
        r"condici[oó]n.*discapacidad", r"diagn[oó]stico.*menor",
        r"trastorno", r"autismo", r"s[ií]ndrome",
        r"PIAR", r"barrera.*aprendizaje",
    ],
    "TUTOR_SOMBRA": [
        r"tutor sombra", r"tutora sombra", r"sombra terap[eé]utica",
        r"docente de apoyo.*discapacidad", r"profesional de apoyo.*pedag[oó]gic",
        r"acompa[nñ]amiento.*pedag[oó]gico.*discapacidad",
    ],
    "INTERPRETES": [
        r"int[eé]rprete", r"lengua de se[nñ]as", r"modelo ling[uü][ií]stico",
        r"sordo", r"hipoacusia", r"lenguaje de se[nñ]as",
    ],
    "NOMBRAMIENTOS": [
        r"nombramiento.*docente", r"provisi[oó]n.*cargo.*docente",
        r"vacante.*docente", r"plaza.*docente",
        r"falta de docente", r"sin docente", r"sin profesor",
        r"orientador.*escol", r"psic[oó]logo.*escol",
        r"nombrar.*docente", r"docente.*proveer",
        r"nombramiento.*rector", r"nombramiento.*director",
    ],
    "TRASLADOS": [
        r"traslado.*docente", r"reubicaci[oó]n.*docente",
        r"traslado.*profesor", r"traslado.*educador",
        r"traslado.*laboral.*educaci[oó]n",
        r"comisi[oó]n de servicios",
    ],
    "CARRERA_DOCENTE": [
        r"escalaf[oó]n", r"evaluaci[oó]n.*docente.*ascenso",
        r"ascenso.*docente", r"inscripci[oó]n.*escalaf",
        r"concurso.*docente", r"reubicaci[oó]n.*salarial",
    ],
    "COBERTURA": [
        r"cobertura.*educativ", r"cupo.*escolar", r"matr[ií]cula",
        r"acceso.*educaci[oó]n", r"negaci[oó]n.*cupo",
        r"disponibilidad.*cupo",
    ],
    "CALIDAD_EDUCATIVA": [
        r"calidad educativa", r"curr[ií]culo", r"PEI",
        r"proyecto educativo institucional",
        r"jornada.*escolar", r"jornada [uú]nica",
    ],
    "PRESTACIONES": [
        r"prestaciones sociales", r"pensi[oó]n.*docente",
        r"cesan[tí]as", r"prima.*docente",
        r"seguridad social.*magisterio",
    ],
    "NOMINA": [
        r"n[oó]mina.*docente", r"salario.*docente",
        r"pago.*docente", r"embargo.*salario",
        r"retencion.*salar", r"descuento.*n[oó]mina",
    ],
    "DEBIDO_PROCESO": [
        r"debido proceso", r"proceso disciplinario",
        r"sanci[oó]n.*docente", r"destituci[oó]n",
        r"investig.*disciplinar",
    ],
    "SALUD": [
        r"salud", r"EPS", r"tratamiento m[eé]dico",
        r"cirug[ií]a", r"medicamento", r"atenci[oó]n m[eé]dica",
        r"incapacidad m[eé]dica", r"licencia.*enfermedad",
    ],
    "RESIDENCIA_ESCOLAR": [
        r"residencia escolar", r"internado.*escol",
        r"alojamiento.*estudiante", r"hogar escolar",
    ],
    "DERECHO_PETICION": [
        r"derecho de petici[oó]n", r"petici[oó]n.*sin respuesta",
        r"silencio administrativo", r"respuesta.*petici[oó]n",
    ],
}

# ── Mapeo categoría → oficina responsable ────────────────────────────────────

CATEGORY_TO_OFICINA: dict[str, str] = {
    "INFRAESTRUCTURA": "Grupo de Infraestructura Educativa",
    "INCLUSION": "Dirección de Permanencia Escolar",
    "TUTOR_SOMBRA": "Dirección de Permanencia Escolar",
    "INTERPRETES": "Dirección de Permanencia Escolar",
    "NOMBRAMIENTOS": "Grupo Administración de Planta",
    "TRASLADOS": "Dirección de Talento Humano Docente",
    "CARRERA_DOCENTE": "Grupo Carrera Docente",
    "COBERTURA": "Grupo de Cobertura Educativa",
    "CALIDAD_EDUCATIVA": "Grupo de Calidad Educativa",
    "PRESTACIONES": "Grupo de Prestaciones Sociales del Magisterio",
    "NOMINA": "Grupo de Nómina",
    "DEBIDO_PROCESO": "Grupo de Inspección y Vigilancia",
    "SALUD": "Dirección Administrativa y Financiera",
    "RESIDENCIA_ESCOLAR": "Dirección de Permanencia Escolar",
    "DERECHO_PETICION": "Grupo de Atención al Ciudadano",
    "GENERAL": "Secretaría de Educación",
}

# Lista cerrada de oficinas válidas
OFICINAS_VALIDAS = [
    "Dirección Administrativa y Financiera",
    "Dirección de Permanencia Escolar",
    "Dirección de Talento Humano Docente",
    "Dirección Estratégica",
    "Grupo de Apoyo Jurídico",
    "Equipo de Contabilidad",
    "Equipo de Presupuesto",
    "Equipo de Tesorería",
    "Equipo Fondo de Servicios Educativos",
    "Grupo Administración de Planta",
    "Grupo de Atención al Ciudadano",
    "Grupo de Bienes y Servicios",
    "Grupo de Calidad Educativa",
    "Grupo Carrera Docente",
    "Grupo de Cobertura Educativa",
    "Grupo Desarrollo Docente",
    "Grupo de Desarrollo Organizacional",
    "Grupo de Infraestructura Educativa",
    "Grupo de Inspección y Vigilancia",
    "Grupo de Nómina",
    "Grupo de Planeación Educativa",
    "Grupo de Prestaciones Sociales del Magisterio",
    "Grupo de Sistemas de Información",
    "Grupo Financiero",
    "Grupo de Historias Laborales",
    "Secretaría de Educación",
]


def classify_case(asunto: str, observaciones: str, pretensiones: str, derecho_vulnerado: str) -> str:
    """Clasificar un caso por su categoría temática.

    Returns: nombre de la categoría (ej: 'INFRAESTRUCTURA', 'INCLUSION', 'GENERAL').
    """
    text = f"{asunto} {observaciones} {pretensiones} {derecho_vulnerado}".lower()

    scores: dict[str, int] = {}
    for category, patterns in CATEGORIES.items():
        score = sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))
        if score > 0:
            scores[category] = score

    if not scores:
        return "GENERAL"

    # Subtipos específicos ganan sobre genéricos
    if "TUTOR_SOMBRA" in scores and "INCLUSION" in scores:
        if scores["TUTOR_SOMBRA"] >= 1:
            del scores["INCLUSION"]
    if "INTERPRETES" in scores and "INCLUSION" in scores:
        if scores["INTERPRETES"] >= 1:
            del scores["INCLUSION"]

    return max(scores, key=scores.get)


def suggest_oficina(categoria: str) -> str:
    """Devuelve la oficina responsable para una categoría temática."""
    return CATEGORY_TO_OFICINA.get(categoria, "Secretaría de Educación")
