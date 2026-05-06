"""Knowledge base jurídico Santander v9.1 — mapa judicial + reglas de derivación.

Fuente: Mapa Judicial Consejo Seccional de la Judicatura de Santander.
Aplicable a tutelas contra la Secretaría de Educación de Santander.
"""
from __future__ import annotations

from dataclasses import dataclass

# ─── Distritos judiciales de Santander ──────────────────────────────

DISTRITO_BUCARAMANGA = "BUCARAMANGA"
DISTRITO_SAN_GIL = "SAN_GIL"

# Tribunal Administrativo único para todo Santander (sede Bucaramanga)
TRIBUNAL_ADMINISTRATIVO_SANTANDER = "Tribunal Administrativo de Santander"

# Tribunales Superiores por distrito
TRIBUNAL_SUPERIOR_BUCARAMANGA = "Tribunal Superior del Distrito Judicial de Bucaramanga"
TRIBUNAL_SUPERIOR_SAN_GIL = "Tribunal Superior del Distrito Judicial de San Gil"

# ─── Circuitos judiciales (cada municipio pertenece a uno) ──────────
# Fuente: Mapa Judicial Consejo Seccional Santander (PDF oficial).
# Esto es CRÍTICO: cuando 1ra instancia es Juez Municipal, la 2da sube
# al Juez del Circuito al que pertenece el municipio.

# Distrito Bucaramanga — 4 circuitos (oficial Rama Judicial)
CIRCUITO_BUCARAMANGA = "BUCARAMANGA"
CIRCUITO_BARRANCABERMEJA = "BARRANCABERMEJA"
CIRCUITO_MALAGA = "MALAGA"
CIRCUITO_SAN_VICENTE = "SAN_VICENTE_DE_CHUCURI"   # incluye El Carmen
# Distrito San Gil — 6 circuitos
CIRCUITO_SAN_GIL = "SAN_GIL"
CIRCUITO_CIMITARRA = "CIMITARRA"                  # corregido: distrito San Gil
CIRCUITO_CHARALA = "CHARALA"
CIRCUITO_PUENTE_NACIONAL = "PUENTE_NACIONAL"
CIRCUITO_SOCORRO = "SOCORRO"
CIRCUITO_VELEZ = "VELEZ"

# Mapeo circuito → distrito superior
CIRCUITO_A_DISTRITO: dict[str, str] = {
    CIRCUITO_BUCARAMANGA: DISTRITO_BUCARAMANGA,
    CIRCUITO_BARRANCABERMEJA: DISTRITO_BUCARAMANGA,
    CIRCUITO_MALAGA: DISTRITO_BUCARAMANGA,
    CIRCUITO_SAN_VICENTE: DISTRITO_BUCARAMANGA,
    CIRCUITO_SAN_GIL: DISTRITO_SAN_GIL,
    CIRCUITO_CIMITARRA: DISTRITO_SAN_GIL,
    CIRCUITO_CHARALA: DISTRITO_SAN_GIL,
    CIRCUITO_PUENTE_NACIONAL: DISTRITO_SAN_GIL,
    CIRCUITO_SOCORRO: DISTRITO_SAN_GIL,
    CIRCUITO_VELEZ: DISTRITO_SAN_GIL,
}

# Mapeo municipio → circuito (mucho más fino que → distrito)
MUNICIPIO_CIRCUITO: dict[str, str] = {
    # Circuito Bucaramanga
    "BUCARAMANGA": CIRCUITO_BUCARAMANGA,
    "FLORIDABLANCA": CIRCUITO_BUCARAMANGA,
    "GIRON": CIRCUITO_BUCARAMANGA,
    "PIEDECUESTA": CIRCUITO_BUCARAMANGA,
    "LEBRIJA": CIRCUITO_BUCARAMANGA,
    "RIONEGRO": CIRCUITO_BUCARAMANGA,
    "EL PLAYON": CIRCUITO_BUCARAMANGA,
    "TONA": CIRCUITO_BUCARAMANGA,
    "CHARTA": CIRCUITO_BUCARAMANGA,
    "MATANZA": CIRCUITO_BUCARAMANGA,
    "SURATA": CIRCUITO_BUCARAMANGA,
    "CALIFORNIA": CIRCUITO_BUCARAMANGA,
    "VETAS": CIRCUITO_BUCARAMANGA,
    "LOS SANTOS": CIRCUITO_BUCARAMANGA,
    "CEPITA": CIRCUITO_BUCARAMANGA,
    "BETULIA": CIRCUITO_BUCARAMANGA,
    "SANTA BARBARA": CIRCUITO_BUCARAMANGA,
    "CACHIRA": CIRCUITO_BUCARAMANGA,        # marca (NS) en mapa nacional, judicialmente Santander
    "LA ESPERANZA": CIRCUITO_BUCARAMANGA,   # idem
    "ZAPATOCA": CIRCUITO_BUCARAMANGA,
    # Circuito Barrancabermeja
    "BARRANCABERMEJA": CIRCUITO_BARRANCABERMEJA,
    "PUERTO WILCHES": CIRCUITO_BARRANCABERMEJA,
    "PUERTO PARRA": CIRCUITO_BARRANCABERMEJA,
    "SABANA DE TORRES": CIRCUITO_BARRANCABERMEJA,
    # Circuito San Vicente (incluye El Carmen — corregido según Mapa Judicial nacional)
    "SAN VICENTE DE CHUCURI": CIRCUITO_SAN_VICENTE,
    "EL CARMEN DE CHUCURI": CIRCUITO_SAN_VICENTE,
    "EL CARMEN": CIRCUITO_SAN_VICENTE,
    # Circuito Málaga (incluye San Andrés)
    "MALAGA": CIRCUITO_MALAGA,
    "CERRITO": CIRCUITO_MALAGA,
    "CONCEPCION": CIRCUITO_MALAGA,
    "ENCISO": CIRCUITO_MALAGA,
    "CAPITANEJO": CIRCUITO_MALAGA,
    "CARCASI": CIRCUITO_MALAGA,
    "GUACA": CIRCUITO_MALAGA,
    "SAN JOSE DE MIRANDA": CIRCUITO_MALAGA,
    "MACARAVITA": CIRCUITO_MALAGA,
    "MOLAGAVITA": CIRCUITO_MALAGA,
    "SAN ANDRES": CIRCUITO_MALAGA,
    "SAN MIGUEL": CIRCUITO_MALAGA,
    # Circuito San Gil
    "SAN GIL": CIRCUITO_SAN_GIL,
    "ARATOCA": CIRCUITO_SAN_GIL,
    "BARICHARA": CIRCUITO_SAN_GIL,
    "CABRERA": CIRCUITO_SAN_GIL,
    "CURITI": CIRCUITO_SAN_GIL,
    "MOGOTES": CIRCUITO_SAN_GIL,
    "ONZAGA": CIRCUITO_SAN_GIL,
    "PARAMO": CIRCUITO_SAN_GIL,
    "SAN JOAQUIN": CIRCUITO_SAN_GIL,
    "VALLE DE SAN JOSE": CIRCUITO_SAN_GIL,
    "VILLANUEVA": CIRCUITO_SAN_GIL,
    "JORDAN": CIRCUITO_SAN_GIL,
    "PINCHOTE": CIRCUITO_SAN_GIL,
    "GALAN": CIRCUITO_SAN_GIL,
    "PALMA DEL SOCORRO": CIRCUITO_SAN_GIL,
    # Circuito Charalá
    "CHARALA": CIRCUITO_CHARALA,
    "COROMORO": CIRCUITO_CHARALA,
    "ENCINO": CIRCUITO_CHARALA,
    "OCAMONTE": CIRCUITO_CHARALA,
    # Circuito Puente Nacional
    "PUENTE NACIONAL": CIRCUITO_PUENTE_NACIONAL,
    "ALBANIA": CIRCUITO_PUENTE_NACIONAL,
    "FLORIAN": CIRCUITO_PUENTE_NACIONAL,
    "JESUS MARIA": CIRCUITO_PUENTE_NACIONAL,
    "LA BELLEZA": CIRCUITO_PUENTE_NACIONAL,
    "SUCRE": CIRCUITO_PUENTE_NACIONAL,
    # Circuito Socorro (15 municipios según mapa nacional)
    "SOCORRO": CIRCUITO_SOCORRO,
    "EL SOCORRO": CIRCUITO_SOCORRO,
    "AGUADA": CIRCUITO_SOCORRO,
    "CHIMA": CIRCUITO_SOCORRO,
    "CONFINES": CIRCUITO_SOCORRO,
    "CONTRATACION": CIRCUITO_SOCORRO,
    "EL GUACAMAYO": CIRCUITO_SOCORRO,
    "GAMBITA": CIRCUITO_SOCORRO,
    "GUADALUPE": CIRCUITO_SOCORRO,
    "GUAPOTA": CIRCUITO_SOCORRO,
    "HATO": CIRCUITO_SOCORRO,
    "OIBA": CIRCUITO_SOCORRO,
    "PALMAR": CIRCUITO_SOCORRO,                # añadido
    "PALMAS DE SOCORRO": CIRCUITO_SOCORRO,     # añadido (sustituye PALMA DEL SOCORRO)
    "PALMA DEL SOCORRO": CIRCUITO_SOCORRO,     # alias por seguridad
    "SIMACOTA": CIRCUITO_SOCORRO,
    "SUAITA": CIRCUITO_SOCORRO,
    # Circuito Vélez (10 municipios)
    "VELEZ": CIRCUITO_VELEZ,
    "BARBOSA": CIRCUITO_VELEZ,
    "BOLIVAR": CIRCUITO_VELEZ,
    "EL PEÑON": CIRCUITO_VELEZ,
    "CHIPATA": CIRCUITO_VELEZ,
    "GUAVATA": CIRCUITO_VELEZ,
    "GUEPSA": CIRCUITO_VELEZ,
    "LA PAZ": CIRCUITO_VELEZ,
    "SAN BENITO": CIRCUITO_VELEZ,
    "SANTA HELENA": CIRCUITO_VELEZ,            # alias
    "STA ELENA DEL OPON": CIRCUITO_VELEZ,      # nombre oficial
    "SANTA ELENA DEL OPON": CIRCUITO_VELEZ,    # alias completo
    # Circuito Cimitarra
    "CIMITARRA": CIRCUITO_CIMITARRA,
    "LANDAZURI": CIRCUITO_CIMITARRA,
}


# ─── Jueces del Circuito disponibles en cada cabecera ────────────────
# Fuente: PDF Mapa Judicial Consejo Seccional Santander.
# Si una especialidad NO está en la lista, esa especialidad NO existe
# en ese circuito y la apelación sube al Promiscuo del Circuito.

JUZGADOS_DEL_CIRCUITO: dict[str, list[str]] = {
    CIRCUITO_BUCARAMANGA: [
        "CIVIL", "PENAL", "LABORAL", "ADMINISTRATIVO", "FAMILIA", "PROMISCUO",
        # Bucaramanga distrito tiene 2 Promiscuos del Circuito (PDF Despachos 2025)
    ],
    CIRCUITO_BARRANCABERMEJA: [
        "CIVIL", "PENAL", "LABORAL", "ADMINISTRATIVO", "FAMILIA",
    ],
    CIRCUITO_SAN_VICENTE: [
        "PROMISCUO",   # Promiscuo del Circuito San Vicente (cubre San Vicente + El Carmen)
    ],
    CIRCUITO_MALAGA: [
        "PROMISCUO", "FAMILIA",   # Promiscuo del Circuito + Promiscuo de Familia
    ],
    CIRCUITO_SAN_GIL: [
        "CIVIL", "PENAL", "LABORAL", "ADMINISTRATIVO", "FAMILIA", "PROMISCUO",
    ],
    CIRCUITO_CIMITARRA: [
        "PROMISCUO",   # solo Promiscuo del Circuito Cimitarra
    ],
    CIRCUITO_CHARALA: [
        "PROMISCUO",   # solo Promiscuo del Circuito Charalá
    ],
    CIRCUITO_PUENTE_NACIONAL: [
        "CIVIL", "PENAL",
    ],
    CIRCUITO_SOCORRO: [
        "CIVIL", "PENAL", "FAMILIA",
    ],
    CIRCUITO_VELEZ: [
        "CIVIL", "PENAL", "FAMILIA",
    ],
}

# Cabeceras de circuito (nombre legible para construir el nombre del juzgado)
CIRCUITO_CABECERA: dict[str, str] = {
    CIRCUITO_BUCARAMANGA: "Bucaramanga",
    CIRCUITO_BARRANCABERMEJA: "Barrancabermeja",
    CIRCUITO_SAN_VICENTE: "San Vicente de Chucurí",
    CIRCUITO_MALAGA: "Málaga",
    CIRCUITO_SAN_GIL: "San Gil",
    CIRCUITO_CIMITARRA: "Cimitarra",
    CIRCUITO_CHARALA: "Charalá",
    CIRCUITO_PUENTE_NACIONAL: "Puente Nacional",
    CIRCUITO_SOCORRO: "Socorro",
    CIRCUITO_VELEZ: "Vélez",
}

# Circuitos sin juez del circuito propio → fallback al circuito vecino.
# Tras corrección con Mapa Judicial nacional, ningún circuito de Santander
# está sin juez del circuito propio. Se mantiene el dict por extensibilidad.
CIRCUITO_FALLBACK: dict[str, str] = {}



# MUNICIPIO_DISTRITO se deriva automáticamente de MUNICIPIO_CIRCUITO + CIRCUITO_A_DISTRITO
# (más abajo, después de definir esos dos). Se mantiene el nombre por compatibilidad.
MUNICIPIO_DISTRITO: dict[str, str] = {}    # poblado al final del módulo

MUNICIPIOS_SANTANDER: set[str] = set()     # idem


def normalize_municipio(s: str | None) -> str | None:
    """Normaliza nombre de municipio: mayúsculas, sin tildes, sin espacios extra."""
    if not s:
        return None
    import unicodedata
    txt = unicodedata.normalize("NFD", s)
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = " ".join(txt.upper().split())
    return txt or None


def es_municipio_santander(nombre: str | None) -> bool:
    norm = normalize_municipio(nombre)
    return norm in MUNICIPIOS_SANTANDER if norm else False


def distrito_de(municipio: str | None) -> str | None:
    norm = normalize_municipio(municipio)
    return MUNICIPIO_DISTRITO.get(norm) if norm else None


def circuito_de(municipio: str | None) -> str | None:
    """Devuelve el código del circuito al que pertenece el municipio."""
    norm = normalize_municipio(municipio)
    return MUNICIPIO_CIRCUITO.get(norm) if norm else None


# ─── Detección de nivel del juzgado de 1ra instancia ─────────────────

def detectar_nivel_juzgado(juzgado_1st: str | None) -> str | None:
    """Devuelve 'MUNICIPAL' | 'CIRCUITO' | 'TRIBUNAL' | None.

    Usa pistas léxicas estándar de la denominación oficial de juzgados Colombia.
    """
    if not juzgado_1st:
        return None
    txt = juzgado_1st.lower()
    if "tribunal" in txt:
        return "TRIBUNAL"
    if "del circuito" in txt or "circuito de" in txt:
        return "CIRCUITO"
    # Promiscuo del Circuito → CIRCUITO; Promiscuo Municipal → MUNICIPAL
    if "promiscuo del circuito" in txt:
        return "CIRCUITO"
    if "municipal" in txt or "promiscuo municipal" in txt:
        return "MUNICIPAL"
    # Fallback heurístico
    if "civil municipal" in txt or "penal municipal" in txt:
        return "MUNICIPAL"
    if "civil del circuito" in txt or "penal del circuito" in txt:
        return "CIRCUITO"
    return None


def extraer_municipio_de_juzgado(juzgado_1st: str | None) -> str | None:
    """Intenta extraer el municipio mencionado en el nombre del juzgado.

    Busca cualquier municipio de Santander conocido dentro del texto del juzgado.
    """
    if not juzgado_1st:
        return None
    txt = (normalize_municipio(juzgado_1st) or "").upper()
    # Ordenar municipios por longitud descendente para priorizar matches específicos
    for m in sorted(MUNICIPIOS_SANTANDER, key=len, reverse=True):
        if m in txt:
            return m
    return None


# ─── Derivación jurídica ────────────────────────────────────────────

@dataclass
class JuzgadoSegundaDerivacion:
    """Resultado del razonamiento sobre el juzgado de 2da instancia."""
    juzgado_2nd: str
    sala: str | None             # 'Civil-Familia' | 'Penal' | 'Laboral' | 'Administrativa'
    sede: str                    # 'Bucaramanga' | 'San Gil'
    distrito: str | None
    razonamiento: str            # explicable en UI


# Patrones de juzgado 1ra instancia → especialidad
ESPECIALIDAD_PATTERNS = {
    "ADMINISTRATIVO": ["administrativo", "contencioso administrativo"],
    "CIVIL": ["civil", "promiscuo civil"],
    "PENAL": ["penal", "control de garantias", "control de garantías"],
    "LABORAL": ["laboral", "pequeñas causas laborales"],
    "FAMILIA": ["familia", "promiscuo de familia", "promiscuo familia"],
    "PROMISCUO": ["promiscuo municipal", "promiscuo del circuito"],
}


def detectar_especialidad(juzgado_1st: str | None) -> str | None:
    if not juzgado_1st:
        return None
    txt = juzgado_1st.lower()
    for esp, kws in ESPECIALIDAD_PATTERNS.items():
        for kw in kws:
            if kw in txt:
                return esp
    return None


def derivar_juzgado_segunda(
    juzgado_1st: str | None,
    accionados: str | None = None,
    municipio_hechos: str | None = None,
) -> JuzgadoSegundaDerivacion | None:
    """Determina el juez/tribunal de 2da instancia por **factor funcional**.

    Marco normativo:
      - Decreto 2591/1991 art. 32: la impugnación se conoce por el "superior
        jerárquico correspondiente" del juez de 1ra.
      - Decreto 1983/2017: las tutelas contra autoridades departamentales,
        distritales o municipales se reparten en 1ra instancia a Jueces
        Municipales (juez del lugar de los hechos).
      - Auto 269/19 Corte Const.: confirma que el superior funcional para 2da
        depende del NIVEL jerárquico del juez de 1ra (municipal → circuito;
        circuito → tribunal).

    Cadena jerárquica:
      MUNICIPAL → Juez del Circuito al que pertenece el municipio
      CIRCUITO  → Tribunal Superior (ordinaria) o Tribunal Administrativo (admin)
      TRIBUNAL  → Corte Suprema / Consejo de Estado (raro en tutelas)

    Args:
      juzgado_1st: nombre del juzgado de 1ra instancia (texto extraído).
      accionados: para diagnóstico (no determina por sí solo el tribunal).
      municipio_hechos: municipio donde ocurrieron los hechos. Si no se da,
        se intenta extraer del nombre del juzgado de 1ra.
    """
    if not juzgado_1st:
        return None

    nivel = detectar_nivel_juzgado(juzgado_1st)
    especialidad = detectar_especialidad(juzgado_1st)

    # Determinar municipio: hechos > extraído del nombre del juzgado
    mun = normalize_municipio(municipio_hechos) or extraer_municipio_de_juzgado(juzgado_1st)
    circuito = MUNICIPIO_CIRCUITO.get(mun) if mun else None

    # ── Caso 1: 1ra instancia es Juez Municipal ──
    # Sube al juez del CIRCUITO al que pertenece el municipio,
    # respetando qué especialidades EXISTEN realmente en ese circuito.
    if nivel == "MUNICIPAL":
        if not circuito:
            return JuzgadoSegundaDerivacion(
                juzgado_2nd="Juzgado del Circuito (circuito no identificado)",
                sala=None,
                sede="?",
                distrito=None,
                razonamiento=(
                    "Juzgado de 1ra es municipal pero no se pudo identificar el "
                    "municipio/circuito. Verifica el escrito de tutela."
                ),
            )

        # Resolver fallback si el circuito no tiene jueces del circuito propios
        circuito_resuelto = circuito
        nota_fallback = ""
        if not JUZGADOS_DEL_CIRCUITO.get(circuito):
            fb = CIRCUITO_FALLBACK.get(circuito)
            if fb:
                circuito_resuelto = fb
                nota_fallback = (
                    f" El circuito de {CIRCUITO_CABECERA[circuito]} no tiene jueces del "
                    f"circuito propios, por lo que la apelación se reasigna a "
                    f"{CIRCUITO_CABECERA[fb]}."
                )

        especialidades_disponibles = JUZGADOS_DEL_CIRCUITO.get(circuito_resuelto, [])
        cabecera = CIRCUITO_CABECERA[circuito_resuelto]
        municipio_nombre = mun.title() if mun else "?"

        # Mapping especialidad → nombre canónico del juzgado del circuito
        nombres_juzgado = {
            "CIVIL": "Civil del Circuito",
            "PENAL": "Penal del Circuito",
            "LABORAL": "Laboral del Circuito",
            "ADMINISTRATIVO": "Administrativo del Circuito",
            "FAMILIA": "Promiscuo de Familia",
            "PROMISCUO": "Promiscuo del Circuito",
        }

        # Decidir qué juzgado del circuito conoce de la apelación
        esp_objetivo = especialidad or "PROMISCUO"
        if esp_objetivo in especialidades_disponibles:
            sala_circuito = nombres_juzgado[esp_objetivo]
            razon_extra = (
                f"En el Circuito de {cabecera} existe juez {esp_objetivo.lower()} del "
                f"circuito; la apelación sube allí."
            )
        elif "PROMISCUO" in especialidades_disponibles:
            # No hay juez especializado del circuito → sube al Promiscuo del Circuito,
            # que conoce de todas las especialidades.
            sala_circuito = "Promiscuo del Circuito"
            razon_extra = (
                f"En el Circuito de {cabecera} NO existe juez {esp_objetivo.lower()} "
                f"del circuito, pero sí existe Juez Promiscuo del Circuito que conoce "
                f"de todas las especialidades; por eso la apelación sube ahí."
            )
        elif especialidades_disponibles:
            # Hay otras especialidades pero no la pedida ni promiscuo → tomamos
            # la primera disponible y advertimos
            sala_circuito = nombres_juzgado.get(
                especialidades_disponibles[0], "del Circuito")
            razon_extra = (
                f"En el Circuito de {cabecera} no hay juez {esp_objetivo.lower()} "
                f"ni Promiscuo del Circuito; se asume {especialidades_disponibles[0]} "
                f"del Circuito. Verifica con el reparto judicial."
            )
        else:
            # Circuito vacío incluso después del fallback → escalamos al Tribunal del distrito
            distrito = CIRCUITO_A_DISTRITO.get(circuito_resuelto, DISTRITO_BUCARAMANGA)
            tribunal = (TRIBUNAL_SUPERIOR_SAN_GIL if distrito == DISTRITO_SAN_GIL
                        else TRIBUNAL_SUPERIOR_BUCARAMANGA)
            return JuzgadoSegundaDerivacion(
                juzgado_2nd=tribunal,
                sala="Civil-Familia",
                sede="San Gil" if distrito == DISTRITO_SAN_GIL else "Bucaramanga",
                distrito=distrito,
                razonamiento=(
                    f"El Circuito de {cabecera} no tiene jueces del circuito "
                    f"identificados en el mapa judicial. La apelación escala "
                    f"directamente al Tribunal Superior del distrito.{nota_fallback}"
                ),
            )

        return JuzgadoSegundaDerivacion(
            juzgado_2nd=f"Juzgado {sala_circuito} de {cabecera}",
            sala=sala_circuito,
            sede=cabecera,
            distrito=CIRCUITO_A_DISTRITO.get(circuito_resuelto),
            razonamiento=(
                f"La 1ra instancia fue un Juez Municipal en {municipio_nombre} "
                f"(circuito {CIRCUITO_CABECERA[circuito]}). Por factor funcional "
                f"(Decreto 1983/2017 + art. 32 Decreto 2591/1991), la impugnación "
                f"sube al Juez del Circuito de {cabecera}. {razon_extra}{nota_fallback}"
            ),
        )

    # ── Caso 2: 1ra instancia es Juez del Circuito ──
    # Sube al Tribunal según especialidad.
    if nivel == "CIRCUITO":
        if especialidad == "ADMINISTRATIVO":
            return JuzgadoSegundaDerivacion(
                juzgado_2nd=TRIBUNAL_ADMINISTRATIVO_SANTANDER,
                sala="Administrativa",
                sede="Bucaramanga",
                distrito=DISTRITO_BUCARAMANGA,
                razonamiento=(
                    "1ra instancia: Juzgado Administrativo del Circuito. "
                    "Superior funcional: Tribunal Administrativo de Santander "
                    "(único en el departamento, sede Bucaramanga)."
                ),
            )

        # Civil/Penal/Laboral/Familia/Promiscuo del Circuito → Tribunal Superior
        distrito = CIRCUITO_A_DISTRITO.get(circuito) if circuito else DISTRITO_BUCARAMANGA
        sala_map = {
            "CIVIL": "Civil-Familia",
            "FAMILIA": "Civil-Familia",
            "PENAL": "Penal",
            "LABORAL": "Laboral",
            "PROMISCUO": "Civil-Familia",
        }
        sala = sala_map.get(especialidad or "PROMISCUO", "Civil-Familia")

        if distrito == DISTRITO_SAN_GIL:
            if sala == "Laboral":
                sala = "Civil-Familia-Laboral"
            return JuzgadoSegundaDerivacion(
                juzgado_2nd=TRIBUNAL_SUPERIOR_SAN_GIL,
                sala=sala,
                sede="San Gil",
                distrito=DISTRITO_SAN_GIL,
                razonamiento=(
                    f"1ra instancia: Juzgado del Circuito ({especialidad or '?'}) en "
                    f"distrito San Gil. Superior funcional: Tribunal Superior de "
                    f"San Gil — Sala {sala}."
                ),
            )

        return JuzgadoSegundaDerivacion(
            juzgado_2nd=TRIBUNAL_SUPERIOR_BUCARAMANGA,
            sala=sala,
            sede="Bucaramanga",
            distrito=DISTRITO_BUCARAMANGA,
            razonamiento=(
                f"1ra instancia: Juzgado del Circuito ({especialidad or '?'}) en "
                f"distrito Bucaramanga. Superior funcional: Tribunal Superior de "
                f"Bucaramanga — Sala {sala}."
            ),
        )

    # ── Caso 3: nivel desconocido ──
    return JuzgadoSegundaDerivacion(
        juzgado_2nd="(no determinable)",
        sala=None,
        sede="?",
        distrito=None,
        razonamiento=(
            f"No se pudo determinar el nivel del juzgado de 1ra instancia "
            f"({juzgado_1st!r}). Verifica el documento del fallo o el "
            f"auto admisorio."
        ),
    )


# ─── Mapeo temático SED → jerarquía L1/L2/L3 ────────────────────────
# Reglas extraídas de Decretos 544/2021 + 048/2022 (estructura SED Santander)
# Cada entrada: keyword/patrón en asunto → (L1, L2, L3, categoria_tematica)

SED_TEMA_MAPPING: list[tuple[list[str], str, str, str | None, str]] = [
    # (keywords, direccion_L1, grupo_L2, equipo_L3, categoria_tematica)
    # ─── Talento Docente / Carrera Docente ───
    (["traslado", "reubicacion", "permuta"],
     "DIRECCION_TALENTO_DOCENTE", "CARRERA_DOCENTE", None, "TRASLADO"),
    (["reintegro laboral", "reintegro al cargo", "reintegrar"],
     "DIRECCION_TALENTO_DOCENTE", "CARRERA_DOCENTE", None, "REINTEGRO"),
    (["nombramiento", "vacante", "provision", "encargo"],
     "DIRECCION_TALENTO_DOCENTE", "ADMINISTRACION_PLANTA", None, "NOMBRAMIENTO"),
    (["pension", "jubilacion", "reconocimiento pension"],
     "DIRECCION_TALENTO_DOCENTE", "PRESTACIONES_SOCIALES", None, "PENSION"),
    (["cesantias", "auxilio cesantia"],
     "DIRECCION_TALENTO_DOCENTE", "PRESTACIONES_SOCIALES", None, "CESANTIAS"),
    (["historia laboral", "tiempo servicio", "certificacion laboral"],
     "DIRECCION_TALENTO_DOCENTE", "HISTORIAS_LABORALES", None, "HISTORIA_LABORAL"),
    (["concurso", "cnsc", "ingreso meritos"],
     "DIRECCION_TALENTO_DOCENTE", "CARRERA_DOCENTE", None, "CNSC_CONCURSO"),
    (["acoso laboral", "violencia laboral"],
     "DIRECCION_TALENTO_DOCENTE", "DESARROLLO_DOCENTE", None, "ACOSO_LABORAL"),
    (["salud docente", "enfermedad profesional", "riesgo psicosocial",
      "tratamiento", "medicamento", "incapacidad medica"],
     "DIRECCION_TALENTO_DOCENTE", "PRESTACIONES_SOCIALES", None, "SALUD_DOCENTE"),

    # ─── Admin Financiera ───
    (["salario", "sueldo", "pago salarios", "retencion salarial"],
     "DIRECCION_ADMIN_FINANCIERA", "NOMINA", None, "SALARIO"),
    (["fondo servicios educativos", "fse"],
     "DIRECCION_ADMIN_FINANCIERA", "FINANCIERA", "EQUIPO_FONDOS_SERVICIOS", "FSE"),
    (["tesoreria", "pago", "giro"],
     "DIRECCION_ADMIN_FINANCIERA", "FINANCIERA", "EQUIPO_TESORERIA", "TESORERIA"),

    # ─── Estratégica / Cobertura Educativa ───
    (["tutor sombra", "acompañante pedagogico", "apoyo pedagogico"],
     "DIRECCION_ESTRATEGICA", "COBERTURA_EDUCATIVA", None, "TUTOR_SOMBRA"),
    (["inclusion", "discapacidad", "necesidad educativa especial", "nee", "tea", "autismo"],
     "DIRECCION_ESTRATEGICA", "COBERTURA_EDUCATIVA", None, "INCLUSION_DISCAPACIDAD"),
    (["matricula", "cupo", "acceso institucion", "admision escolar"],
     "DIRECCION_ESTRATEGICA", "COBERTURA_EDUCATIVA", None, "MATRICULA"),
    (["proteccion de derechos del menor", "proteccion del menor",
      "derechos del menor", "interes superior", "nna", "niño", "niña"],
     "DIRECCION_ESTRATEGICA", "COBERTURA_EDUCATIVA", None, "PROTECCION_MENOR"),
    (["tutela por vulneracion a educacion", "vulneracion a educacion",
      "vulneracion educacion"],
     "DIRECCION_ESTRATEGICA", "COBERTURA_EDUCATIVA", None, "EDUCACION"),
    (["calidad educativa", "evaluacion docente"],
     "DIRECCION_ESTRATEGICA", "CALIDAD_EDUCATIVA", None, "CALIDAD_EDUCATIVA"),

    # ─── Permanencia ───
    (["transporte escolar", "ruta escolar"],
     "DIRECCION_PERMANENCIA", None, None, "TRANSPORTE_ESCOLAR"),
    (["alimentacion escolar", "pae", "refrigerio"],
     "DIRECCION_PERMANENCIA", None, None, "ALIMENTACION_PAE"),

    # ─── Apoyo Directo / Jurídico ───
    (["incidente de desacato", "incidente desacato", "desacato",
      "incumplimiento del fallo", "cumplimiento del fallo"],
     "APOYO_DIRECTO", "APOYO_JURIDICO", None, "INCIDENTE_DESACATO"),
    (["derecho de peticion", "respuesta a peticion", "respuesta peticion",
      "solicita respuesta", "solicito respuesta"],
     "APOYO_DIRECTO", "APOYO_JURIDICO", None, "DERECHO_PETICION"),
    (["debido proceso", "vulneracion a debido proceso",
      "vulneracion debido proceso"],
     "APOYO_DIRECTO", "APOYO_JURIDICO", None, "DEBIDO_PROCESO"),
    (["inspeccion", "vigilancia", "supervision educativa"],
     "APOYO_DIRECTO", "INSPECCION_VIGILANCIA", None, "INSPECCION"),

    # ─── Genérico de tutela (fallback amplio) ───
    (["tutela por vulneracion a derechos fundamentales",
      "vulneracion a derechos fundamentales",
      "tutela por vulneracion derechos"],
     "DIRECCION_ESTRATEGICA", None, None, "TUTELA_GENERICA"),
]


def clasificar_sed_tematica(texto: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """Clasifica el caso en (L1, L2, L3, categoria_tematica) por keyword matching.

    Devuelve la primera coincidencia ordenada por especificidad. Si no hay match,
    retorna (None, None, None, None) para que la cadena IA tome el relevo.
    """
    if not texto:
        return (None, None, None, None)
    txt = normalize_municipio(texto) or ""  # reusa normalizador (lower+sin tildes)
    txt = txt.lower()
    for kws, l1, l2, l3, cat in SED_TEMA_MAPPING:
        for kw in kws:
            if kw in txt:
                return (l1, l2, l3, cat)
    return (None, None, None, None)


# ─── Derivación automática de MUNICIPIO_DISTRITO y MUNICIPIOS_SANTANDER ────
# Una única fuente de verdad: MUNICIPIO_CIRCUITO. El distrito se deriva.
MUNICIPIO_DISTRITO.update({
    mun: CIRCUITO_A_DISTRITO[circ]
    for mun, circ in MUNICIPIO_CIRCUITO.items()
    if circ in CIRCUITO_A_DISTRITO
})
MUNICIPIOS_SANTANDER.update(MUNICIPIO_CIRCUITO.keys())

