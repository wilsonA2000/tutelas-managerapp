"""Normalizadores Excel histórico → enums canónicos.

Excel CONTROL TUTELAS tiene typos, abreviaciones y texto libre. Este módulo
mapea las variantes a categorías limpias para usar como labels de training.

NO se aplica hasta que Wilson valide los mapeos vía
`python -m backend.ml.data.normalizers report`.
"""

from __future__ import annotations
import re
import unicodedata
from pathlib import Path
import json


# ============================================================
# DEPENDENCIA — oficina_responsable canonical (12 categorías)
# ============================================================

# Mapeo Excel histórico → códigos canónicos del organigrama SED.
# Usa códigos definidos en `backend/ml/data/sed_org.py` (Decretos 544/2021, 048/2022).
DEPENDENCIA_MAP: dict[str, str] = {
    # === TALENTO HUMANO DOCENTE (la dirección con más casos: 1824 en histórico) ===
    "TALENTO HUMANO": "DIRECCION_TALENTO_DOCENTE",  # genérico → L1, sin grupo específico
    "TALENTO HUMANO DOCENTE": "DIRECCION_TALENTO_DOCENTE",
    "TALENTO HUAMNO": "DIRECCION_TALENTO_DOCENTE",  # typo
    "TAELNTO HUMANO": "DIRECCION_TALENTO_DOCENTE",
    "TALNTO HUMANO": "DIRECCION_TALENTO_DOCENTE",
    "TALENTRO HUMANO": "DIRECCION_TALENTO_DOCENTE",
    "T HUMANO": "DIRECCION_TALENTO_DOCENTE",
    "T. HUMANO": "DIRECCION_TALENTO_DOCENTE",
    "TALENTO": "DIRECCION_TALENTO_DOCENTE",
    # Sub-grupos de Talento Docente (cuando se especifican)
    "NOMINA": "NOMINA",
    "NÓMINA": "NOMINA",
    "HISTORIAS": "HISTORIAS_LABORALES",
    "HISTORIAS LABORALES": "HISTORIAS_LABORALES",
    "H LABORALES": "HISTORIAS_LABORALES",
    "ADMINISTRACION PLANTA": "ADMINISTRACION_PLANTA",
    "ADMINISTRACIÓN PLANTA": "ADMINISTRACION_PLANTA",
    "DESARROLLO DOCENTE": "DESARROLLO_DOCENTE",
    "CARRERA DOCENTE": "CARRERA_DOCENTE",
    "PRESTACIONES SOCIALES": "PRESTACIONES_SOCIALES",
    "PRESTACIONES SOCIALES DEL MAGISTERIO": "PRESTACIONES_SOCIALES",

    # === DIRECCIÓN ADMINISTRATIVA Y FINANCIERA ===
    "FINANCIERA": "FINANCIERA",
    "FIANANCIERA": "FINANCIERA",
    "FIANNCIERA": "FINANCIERA",
    "FINANCIERA - TALENTO HUMANO": "FINANCIERA",  # combinada → asignar al principal
    "FINANCIERA RECURSOS FISIC": "FINANCIERA",
    "FINANCIERA RECURSOS FISICOS": "FINANCIERA",
    "GRUPO FINANCIERA": "FINANCIERA",
    "ADMINISTRATIVA": "DIRECCION_ADMIN_FINANCIERA",
    "ADMINISTRATIVA Y FINANCIERA": "DIRECCION_ADMIN_FINANCIERA",
    # Sub-equipos de Financiera
    "TESORERIA": "EQUIPO_TESORERIA",
    "TESORERÍA": "EQUIPO_TESORERIA",
    "PRESUPUESTO": "EQUIPO_PRESUPUESTO",
    "CONTABILIDAD": "EQUIPO_CONTABILIDAD",
    "FONDO DE SERVICIOS EDUCATIVOS": "EQUIPO_FONDOS_SERVICIOS",
    "FSE": "EQUIPO_FONDOS_SERVICIOS",
    # Otros grupos de Admin/Financiera
    "ATENCION AL CIUDADANO": "ATENCION_CIUDADANO",
    "ATENCIÓN AL CIUDADANO": "ATENCION_CIUDADANO",
    "BIENES Y SERVICIOS": "BIENES_SERVICIOS",
    "BIENES": "BIENES_SERVICIOS",
    "SISTEMAS DE INFORMACION": "SISTEMAS_INFORMACION",
    "SISTEMAS DE INFORMACIÓN": "SISTEMAS_INFORMACION",
    "SISTEMAS": "SISTEMAS_INFORMACION",
    # Histórico: "RECURSOS FISICOS" / "INFRAESTRUCTURA" → BIENES Y SERVICIOS (post-2022)
    "RECURSOS FISICOS": "BIENES_SERVICIOS",
    "RECURSOS FÍSICOS": "BIENES_SERVICIOS",
    "INFRAESTRUCTURA": "BIENES_SERVICIOS",

    # === DIRECCIÓN ESTRATÉGICA ===
    "ESTRATEGICA": "DIRECCION_ESTRATEGICA",
    "ESTRATÉGICA": "DIRECCION_ESTRATEGICA",
    "ESTARTEGICA": "DIRECCION_ESTRATEGICA",  # typo
    "DIRECCION ESTRATEGICA": "DIRECCION_ESTRATEGICA",
    "DIRECCIÓN ESTRATÉGICA": "DIRECCION_ESTRATEGICA",
    "CALIDAD": "CALIDAD_EDUCATIVA",
    "CALIDAD EDUCATIVA": "CALIDAD_EDUCATIVA",
    "COBERTURA": "COBERTURA_EDUCATIVA",
    "COBERTURA EDUCATIVA": "COBERTURA_EDUCATIVA",

    # === DIRECCIÓN DE PERMANENCIA ESCOLAR ===
    "PERMANENCIA": "DIRECCION_PERMANENCIA",
    "PERMANENCIA ESCOLAR": "DIRECCION_PERMANENCIA",
    "DIRECCION DE PERMANENCIA": "DIRECCION_PERMANENCIA",
    # PAE/Nutrición/Transporte caen aquí (suelen ser temas de permanencia)
    "PAE": "DIRECCION_PERMANENCIA",
    "NUTRICION": "DIRECCION_PERMANENCIA",
    "ALIMENTACION ESCOLAR": "DIRECCION_PERMANENCIA",
    "TRANSPORTE": "DIRECCION_PERMANENCIA",
    "TRANSPORTE ESCOLAR": "DIRECCION_PERMANENCIA",

    # === APOYO DIRECTO DESPACHO ===
    "INSPECCION Y VIGILANCIA": "INSPECCION_VIGILANCIA",
    "INSPECCIÓN Y VIGILANCIA": "INSPECCION_VIGILANCIA",
    "INSPECCION": "INSPECCION_VIGILANCIA",
    "INSPECCIÓN": "INSPECCION_VIGILANCIA",
    "APOYO JURIDICO": "APOYO_JURIDICO",
    "APOYO JURÍDICO": "APOYO_JURIDICO",
    "JURIDICA": "APOYO_JURIDICO",
    "JURIDICO": "APOYO_JURIDICO",
    "SUPERVISORES": "SUPERVISORES_NUCLEO",
    "DIRECTORES DE NUCLEO": "SUPERVISORES_NUCLEO",
    "DIRECTORES DE NÚCLEO": "SUPERVISORES_NUCLEO",
    "PLANEACION EDUCATIVA": "PLANEACION_EDUCATIVA",
    "PLANEACIÓN EDUCATIVA": "PLANEACION_EDUCATIVA",
    "PLANEACION": "PLANEACION_EDUCATIVA",

    # === ESPECIALES ===
    "TODAS": "MULTI",
    "VARIAS": "MULTI",
    "MULTI": "MULTI",
    # FALTA LEG no es dependencia (es tema), va a SIN_ASIGNAR
    "FALTA LEG": "SIN_ASIGNAR",
    "X": "SIN_ASIGNAR",
    "": "SIN_ASIGNAR",
    "SIN DEFINIR": "SIN_ASIGNAR",
    "DESARROLLO SOCIAL": "SIN_ASIGNAR",  # no existe en SED, era externo
    "DESARROLLO SOCIAL -": "SIN_ASIGNAR",
}


# ============================================================
# ABOGADO — nombres cortos del Excel → completos del sed.json
# ============================================================

ABOGADO_SHORT_TO_FULL: dict[str, str] = {
    # ACTIVOS — en abogados_sed.json (vigentes 2026)
    "VICTOR": "VICTOR ALFONSO COLMENARES NIÑO",
    "ANGELICA": "ANGELICA YADIRA BARROSO SARMIENTO",
    "OTILIA": "OTILIA LUNA LOPEZ",
    "JUAN DIEGO": "JUAN DIEGO CRUZ LIZCANO",
    "JHON": "JHON ALEXANDER BOHORQUEZ CAMARGO",
    "JHON ALEXANDER": "JHON ALEXANDER BOHORQUEZ CAMARGO",
    "LUIS EDUARDO": "LUIS EDUARDO MEZA JURADO",
    "DIEGO OTILIO": "DIEGO OTILIO RODRIGUEZ NUÑEZ",
    "DIEGO": "DIEGO OTILIO RODRIGUEZ NUÑEZ",
    "DANNA": "DANNA VALENTINA GARCIA",
    "DANNA VALENTINA": "DANNA VALENTINA GARCIA",
    "CHRISTIAN": "CHRISTIAN ALEXANDER FLOREZ GUERRERO",
    "FERNANDO": "FERNANDO MAURICIO CAMACHO PICO",
    "MARIA CRISTINA": "MARIA CRISTINA VILLAMIZAR SCHILLER",
    "DRA CRISTINA": "MARIA CRISTINA VILLAMIZAR SCHILLER",
    "DRA. CRISTINA": "MARIA CRISTINA VILLAMIZAR SCHILLER",
    "DOC CRIS": "MARIA CRISTINA VILLAMIZAR SCHILLER",
    "JORGE JAVIER": "JORGE JAVIER SEPULVEDA JAIMES",
    "JORGE": "JORGE JAVIER SEPULVEDA JAIMES",
    "KAREN": "KAREN NATHALIA TIRADO PARRA",
    "JUAN CAMILO": "JUAN CAMILO NAVAS MARTINEZ",
    "YALECXY": "YALECXY YULIANA SALAZAR RINCON",
    "SANDRA": "SANDRA VIVIANA VILLAMIZAR CARRILLO",
    "WILSON": "WILSON ANDRES ARGUELLO CASTELLANOS",
    "WILSON ANDRES": "WILSON ANDRES ARGUELLO CASTELLANOS",
    # INACTIVOS — funcionarios anteriores. Los datos históricos quedan
    # etiquetados como INACTIVO_<nombre> para que el modelo NO los aprenda
    # como predicciones válidas (solo activos pueden ser predichos).
    "LILIANA": "INACTIVO_LILIANA",
    "LILI": "INACTIVO_LILIANA",
    "HENSER": "INACTIVO_HENSER",
    "HANER": "INACTIVO_HENSER",  # typo
    "HEIDY": "INACTIVO_HEIDY",
    "HEYDI": "INACTIVO_HEIDY",  # typo
    "LAURA": "INACTIVO_LAURA",
    "VANESA": "INACTIVO_VANESA",
    "VANE": "INACTIVO_VANESA",
    "JULIANA": "INACTIVO_JULIANA",
    "DIANA": "INACTIVO_DIANA",
    "AURA": "INACTIVO_AURA",
    "PAOLA": "INACTIVO_PAOLA",
    "LEAMIS": "INACTIVO_LEAMIS",
}


def is_abogado_activo(full_name: str) -> bool:
    """True si el abogado está activo (en abogados_sed.json)."""
    if not full_name or full_name.startswith(("INACTIVO_", "<DESCONOCIDO")):
        return False
    return True


# ============================================================
# FALLO — texto libre → enum (CONCEDE/NIEGA/IMPROCEDENTE/HECHO_SUPERADO/DESISTIMIENTO)
# ============================================================

FALLO_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Orden importa: más específicas primero
    (re.compile(r"\bhecho\s+superad", re.IGNORECASE), "HECHO_SUPERADO"),
    (re.compile(r"\bhecho\s+cesad", re.IGNORECASE), "HECHO_SUPERADO"),
    (re.compile(r"\bdesist", re.IGNORECASE), "DESISTIMIENTO"),
    (re.compile(r"\bimprocedente?\b", re.IGNORECASE), "IMPROCEDENTE"),
    (re.compile(r"\bniega\b|\bnegar\b|\bno\s+conced|\bno\s+tutelar", re.IGNORECASE), "NIEGA"),
    (re.compile(r"\brevocar(?:on|aron)?\b.*\btutelar(?:on|aron)?\b", re.IGNORECASE), "CONCEDE"),
    (re.compile(r"\btutelar(?:on|aron)?\b|\bampar(?:o|a)?\b|\bconced", re.IGNORECASE), "CONCEDE"),
    (re.compile(r"\bfavorable.*acced", re.IGNORECASE), "CONCEDE"),
    (re.compile(r"\bfavorable.*conced", re.IGNORECASE), "CONCEDE"),
    (re.compile(r"\bfavorable", re.IGNORECASE), "CONCEDE"),  # asumir favorable=concede
]


# ============================================================
# TEMA — texto libre → categoría (clasificador 30 clases)
# ============================================================

TEMA_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\btraslad", re.IGNORECASE), "TRASLADO"),
    # Derecho de petición: capturar también abreviaciones DER PET, DERE PET, etc.
    (re.compile(r"\bder(?:echo)?\s*(?:de\s*)?petic[ií]?on", re.IGNORECASE), "DERECHO_PETICION"),
    (re.compile(r"\bder(?:e)?\s+pet", re.IGNORECASE), "DERECHO_PETICION"),
    (re.compile(r"\bpetic[ií]on", re.IGNORECASE), "DERECHO_PETICION"),
    (re.compile(r"\bfalta\s+leg", re.IGNORECASE), "FALTA_LEGITIMACION"),
    (re.compile(r"\bfalta\s+(?:de\s+)?legitima", re.IGNORECASE), "FALTA_LEGITIMACION"),
    (re.compile(r"\bret[eé]n\b", re.IGNORECASE), "RETEN"),
    (re.compile(r"\bcetil\b|\bsat\b", re.IGNORECASE), "CETIL_SAT"),
    (re.compile(r"\bcnsc\b|\bconcurso\b", re.IGNORECASE), "CNSC_CONCURSO"),
    (re.compile(r"\binclusi[oó]n", re.IGNORECASE), "INCLUSION_DISCAPACIDAD"),
    (re.compile(r"\btransporte\s+escolar", re.IGNORECASE), "TRANSPORTE_ESCOLAR"),
    (re.compile(r"\bpae\b|aliment", re.IGNORECASE), "PAE_ALIMENTACION"),
    (re.compile(r"\binfraestructura|mantenimiento|adecuaci[oó]n", re.IGNORECASE), "INFRAESTRUCTURA"),
    (re.compile(r"\bmatr[ií]cula|cupo\s+escolar", re.IGNORECASE), "MATRICULA_CUPO"),
    (re.compile(r"\bnombramient", re.IGNORECASE), "NOMBRAMIENTO"),
    (re.compile(r"\bdocente\s+(?:de\s+)?apoyo", re.IGNORECASE), "DOCENTE_APOYO"),
    (re.compile(r"\bdocente", re.IGNORECASE), "DOCENTES"),
    (re.compile(r"\bsancion|disciplinari", re.IGNORECASE), "SANCION_DISCIPLINARIA"),
    (re.compile(r"\bpensi[oó]n", re.IGNORECASE), "PENSION"),
    (re.compile(r"\bcesant[ií]a", re.IGNORECASE), "CESANTIAS"),
    (re.compile(r"\bsalari|prestaci", re.IGNORECASE), "SALARIOS_PRESTACIONES"),
    (re.compile(r"\bdescuento", re.IGNORECASE), "DESCUENTOS"),
    (re.compile(r"\bestabilidad|reintegr", re.IGNORECASE), "ESTABILIDAD_REINTEGRO"),
    (re.compile(r"\bvivienda", re.IGNORECASE), "VIVIENDA"),
    (re.compile(r"\bsalud|eps|tratamiento|medicament", re.IGNORECASE), "SALUD_EPS"),
    (re.compile(r"\btecho\s+cordillera|infraestructura\s+escuela", re.IGNORECASE), "INFRAESTRUCTURA_ESCUELA"),
    (re.compile(r"\btutor\s+sombra", re.IGNORECASE), "TUTOR_SOMBRA"),
    (re.compile(r"\bpermut", re.IGNORECASE), "PERMUTA"),
    (re.compile(r"\bcomodato", re.IGNORECASE), "COMODATO"),
    (re.compile(r"\bsimat\b", re.IGNORECASE), "MATRICULA_CUPO"),
    (re.compile(r"\bcertificad", re.IGNORECASE), "CERTIFICADOS"),
    (re.compile(r"\bcupo\b", re.IGNORECASE), "MATRICULA_CUPO"),
]


# ============================================================
# Funciones públicas
# ============================================================

def _strip_norm(s: str) -> str:
    s = (s or "").strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.upper()


def normalize_dependencia(raw: str | None) -> str:
    """Excel `dependencia_raw` → código canónico del organigrama SED.

    Devuelve códigos de `backend/ml/data/sed_org.py` (L1, L2 o L3).
    Para acceder a la jerarquía: `from backend.ml.data.sed_org import get_l1, get_unit`.
    """
    if not raw:
        return "SIN_ASIGNAR"
    key = _strip_norm(str(raw))
    if key in DEPENDENCIA_MAP:
        return DEPENDENCIA_MAP[key]
    # Fallback: buscar substring (orden por longitud descendente para preferir matches específicos)
    for k in sorted(DEPENDENCIA_MAP.keys(), key=len, reverse=True):
        if k and len(k) >= 5 and k in key:
            return DEPENDENCIA_MAP[k]
    return "SIN_ASIGNAR"  # ya no usamos "OTROS"; lo desconocido va a SIN_ASIGNAR


def get_dependencia_l1(code: str) -> str:
    """Devuelve la Dirección/L1 ancestro de un código de dependencia."""
    from backend.ml.data.sed_org import get_l1
    return get_l1(code)


def normalize_abogado(raw: str | None) -> str:
    if not raw:
        return ""
    key = _strip_norm(str(raw))
    if key in ABOGADO_SHORT_TO_FULL:
        return ABOGADO_SHORT_TO_FULL[key]
    # Fallback: si es un nombre compuesto que coincide con prefijo
    for short, full in ABOGADO_SHORT_TO_FULL.items():
        if short and len(short) >= 4 and key.startswith(short):
            return full
    return f"<DESCONOCIDO:{key[:30]}>"


def classify_fallo(raw: str | None) -> str:
    """Texto libre del campo FALLO → enum."""
    if not raw or len(str(raw).strip()) < 3:
        return ""
    text = str(raw)
    for pat, label in FALLO_PATTERNS:
        if pat.search(text):
            return label
    return "OTRO"  # texto libre que no matchea ningún patrón conocido


def normalize_tema(raw: str | None) -> str:
    if not raw:
        return ""
    # Strip accents para que regex con [oó] o sin acentos funcione en upper-case
    text = unicodedata.normalize("NFD", str(raw))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    matches = []
    for pat, label in TEMA_PATTERNS:
        if pat.search(text):
            matches.append(label)
    if not matches:
        return "OTRO"
    return matches[0]  # primer match (orden de TEMA_PATTERNS = prioridad)


def normalize_radicado_corto(raw: str | None) -> str:
    """Excel '24-1', '2020-002', '23-267 T-9998915' → 'YYYY-NNNNN'."""
    if not raw:
        return ""
    s = str(raw).strip()
    # Extraer primer pattern de tipo YY-NN o YYYY-NN
    m = re.search(r"\b(\d{2,4})[-\s]+(\d{1,5})", s)
    if not m:
        return s
    year = m.group(1)
    num = m.group(2)
    if len(year) == 2:
        year = ("20" if int(year) < 70 else "19") + year
    return f"{year}-{num.zfill(5)}"


# ============================================================
# CLI: reporte para validar mapeos
# ============================================================

def report_mappings(excel_path: str) -> dict:
    """Genera reporte de cómo se mapearían los valores del Excel.

    Wilson valida ANTES de cargar a DB.
    """
    import openpyxl
    from collections import Counter

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    raw_dependencia = Counter()
    raw_abogado = Counter()
    raw_fallo = Counter()
    raw_tema = Counter()

    for sheet in ["TUTELAS 2023", "TUTELAS 2024", "TUTELAS 2025 ", "TUTELAS 2026"]:
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        headers = [str(c.value).strip().lower() if c.value else "" for c in ws[1]]
        for r in range(2, ws.max_row + 1):
            row = dict(zip(headers, [c.value for c in ws[r]]))
            if not row.get("radicado"):
                continue
            if row.get("dependencia"):
                raw_dependencia[str(row["dependencia"]).strip().upper()] += 1
            if row.get("abogado"):
                raw_abogado[str(row["abogado"]).strip().upper()] += 1
            if row.get("fallo"):
                raw_fallo[str(row["fallo"]).strip()[:80]] += 1
            if row.get("tema"):
                raw_tema[str(row["tema"]).strip().upper()[:60]] += 1

    # Aplicar normalización y contar
    normalized = {
        "dependencia": Counter(),
        "abogado": Counter(),
        "fallo": Counter(),
        "tema": Counter(),
    }
    unmatched = {"dependencia": [], "abogado": [], "fallo": [], "tema": []}

    for raw, n in raw_dependencia.items():
        norm = normalize_dependencia(raw)
        normalized["dependencia"][norm] += n
        if norm in ("OTROS", "SIN_ASIGNAR") and n >= 5:
            unmatched["dependencia"].append((raw, n))

    for raw, n in raw_abogado.items():
        norm = normalize_abogado(raw)
        normalized["abogado"][norm] += n
        if norm.startswith("<") and n >= 5:
            unmatched["abogado"].append((raw, n))

    for raw, n in raw_fallo.items():
        norm = classify_fallo(raw)
        normalized["fallo"][norm or "<vacío>"] += n
        if norm == "OTRO" and n >= 3:
            unmatched["fallo"].append((raw, n))

    for raw, n in raw_tema.items():
        norm = normalize_tema(raw)
        normalized["tema"][norm or "<vacío>"] += n
        if norm == "OTRO" and n >= 5:
            unmatched["tema"].append((raw, n))

    return {"normalized": normalized, "unmatched": unmatched}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        path = sys.argv[2] if len(sys.argv) > 2 else "/mnt/c/Users/wilso/Downloads/CONTROL TUTELAS.xlsx"
        result = report_mappings(path)
        print("=" * 60)
        print("REPORTE DE NORMALIZACIÓN — Excel CONTROL TUTELAS")
        print("=" * 60)
        for field in ["dependencia", "abogado", "fallo", "tema"]:
            print(f"\n--- {field.upper()} (post-normalización) ---")
            total = sum(result["normalized"][field].values())
            for cat, n in result["normalized"][field].most_common(20):
                pct = 100 * n / total if total else 0
                print(f"  {n:>5}  ({pct:>5.1f}%)  {cat}")
            print(f"\n--- {field.upper()} sin match (>=5 ocurrencias) ---")
            for raw, n in sorted(result["unmatched"][field], key=lambda x: -x[1])[:15]:
                print(f"  {n:>4}  {str(raw)[:80]}")
