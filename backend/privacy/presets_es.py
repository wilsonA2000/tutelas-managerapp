"""Recognizers personalizados para Presidio — Colombia (v5.3).

Complementan los recognizers built-in de Presidio ES con patrones específicos:
- Cédula colombiana (CC)
- NUIP menor (Registro Civil)
- Radicado 23 dígitos
- FOREST interno Gobernación
- Diagnóstico CIE-10
- Teléfono móvil / fijo Colombia
"""

from presidio_analyzer import Pattern, PatternRecognizer


CO_CC_RECOGNIZER = PatternRecognizer(
    supported_entity="CC",
    supported_language="es",
    patterns=[
        Pattern(
            name="cc_label_dots",
            # 63.498.732 con label explícito (CC / cédula)
            regex=r"(?:C\.?C\.?|[Cc][eé]dula(?:\s+de\s+[Cc]iudadan[íi]a)?)[\s:\.]*(?:No\.?\s*)?\d{1,3}\.\d{3}\.\d{3,4}\b",
            score=0.92,
        ),
        Pattern(
            name="cc_label_bare",
            regex=r"(?:C\.?C\.?|[Cc][eé]dula(?:\s+de\s+[Cc]iudadan[íi]a)?)[\s:\.]*(?:No\.?\s*)?\d{6,10}\b",
            score=0.85,
        ),
        Pattern(
            name="cc_bare_dots",
            # CC "suelta" con separadores de miles — adultos normalmente 7-9 cifras
            regex=r"\b\d{1,3}\.\d{3}\.\d{3}\b",
            score=0.55,
        ),
    ],
    context=["cédula", "cedula", "identificado", "identificada", "CC", "C.C."],
)


CO_NUIP_RECOGNIZER = PatternRecognizer(
    supported_entity="NUIP",
    supported_language="es",
    patterns=[
        Pattern(
            name="nuip_rc_bare",
            regex=r"(?:RC|Registro\s+Civil|NUIP)\s*(?:No\.?\s*)?\d{10,11}\b",
            score=0.95,
        ),
        Pattern(
            name="nuip_rc_dots",
            # NUIP menor con separadores de miles: 1.098.765.432
            regex=r"(?:RC|Registro\s+Civil|NUIP)\s*(?:No\.?\s*)?\d{1,3}\.\d{3}\.\d{3}\.\d{3}\b",
            score=0.98,
        ),
        Pattern(
            name="nuip_bare_dots",
            # 4 grupos de puntos → casi siempre NUIP (11 dígitos) incluso sin label
            regex=r"\b\d{1,3}\.\d{3}\.\d{3}\.\d{3}\b",
            score=0.7,
        ),
    ],
    context=["registro", "civil", "NUIP", "menor", "RC"],
)


CO_RADICADO_FOREST_RECOGNIZER = PatternRecognizer(
    supported_entity="RADICADO_FOREST",
    supported_language="es",
    patterns=[
        Pattern(
            name="forest_11d",
            regex=r"\b(2026\d{7})\b",  # FOREST empieza por 2026 + 7 dígitos
            score=0.7,
        ),
    ],
    context=["FOREST", "radicado", "tutelas@santander"],
)


CIE10_RECOGNIZER = PatternRecognizer(
    supported_entity="DX_DETAIL",
    supported_language="es",
    patterns=[
        Pattern(
            name="cie10_full",
            # Letra + 2 dígitos + opcional punto + 1-2 dígitos (ej: G80.9, F20, C50.1)
            regex=r"\b(?:CIE[\s\-]?10|CIE10)?\s*[A-TV-Z]\d{2}(?:\.\d{1,2})?\b",
            score=0.85,
        ),
    ],
    context=["CIE-10", "CIE10", "diagnóstico", "diagnostico"],
)


CO_PHONE_RECOGNIZER = PatternRecognizer(
    supported_entity="PHONE",
    supported_language="es",
    patterns=[
        Pattern(
            name="mobile_co",
            regex=r"\b3[0-5]\d[\s\-]?\d{3}[\s\-]?\d{4}\b",
            score=0.8,
        ),
        Pattern(
            name="landline_bga",
            regex=r"\b(?:60)?[67][\s\-]?\d{7}\b",
            score=0.55,
        ),
    ],
    context=["teléfono", "telefono", "celular", "móvil", "movil", "contacto"],
)


ADDRESS_EXACT_RECOGNIZER = PatternRecognizer(
    supported_entity="ADDRESS_EXACT",
    supported_language="es",
    patterns=[
        Pattern(
            name="calle_carrera",
            regex=r"\b(?:Calle|Cll|Carrera|Cra|Kra|Transversal|Tv|Diagonal|Diag|Avenida|Av)\.?\s*\d{1,3}[A-Z]?\s*(?:#|No\.?|Nº|N°|n\.)?\s*\d{1,3}\s*[\-–]\s*\d{1,3}\b",
            score=0.8,
        ),
    ],
    context=["dirección", "direccion", "residente", "domicilio"],
)


CUSTOM_RECOGNIZERS = [
    CO_CC_RECOGNIZER,
    CO_NUIP_RECOGNIZER,
    CO_RADICADO_FOREST_RECOGNIZER,
    CIE10_RECOGNIZER,
    CO_PHONE_RECOGNIZER,
    ADDRESS_EXACT_RECOGNIZER,
]
