"""Validador pre-envío: zero-PII gate (v5.3).

Se corre DESPUÉS de redactar. Si detecta PII literal que escapó al redactor,
bloquea el envío a IA externa (modo strict) o marca el caso REVISION (modo warn).

Importante: detectar PII no es lo mismo que bloquear. El detector siempre
encuentra PII (su trabajo); el gate solo bloquea si **sobrevive la redacción**.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.privacy.policies import AGGRESSIVE_KINDS, SELECTIVE_KINDS, Mode
from backend.privacy.calibration import is_false_positive_cc


@dataclass(frozen=True)
class Violation:
    kind: str
    snippet: str
    position: int
    doc_index: int


# Patrones "control" que buscan PII numérica que NO debería haber sobrevivido.
# Si el redactor hizo su trabajo, estos patrones no deberían matchear (salvo en
# segmentos de contenido legítimo entre corchetes, que quedan afuera).
_CONTROL_PATTERNS: dict[str, re.Pattern] = {
    # CC 1,098,765 — excluye fechas DD.MM.YYYY (tercer grupo 4 dígitos 19xx-20xx)
    "CC": re.compile(r"(?<!\w)(?<!#)(?!(?:0?[1-9]|[12]\d|3[01])\.(?:0?[1-9]|1[0-2])\.(?:19|20)\d{2}\b)\d{1,3}\.\d{3}\.\d{3,4}(?!\w)"),
    "CC_BARE": re.compile(r"(?<!\w)(?<!#)\d{7,10}(?!\w)"),                            # 1098765432 suelto (no radicados 23d)
    "NUIP": re.compile(r"(?:RC|Registro\s+Civil|NUIP)\s*(?:No\.?\s*)?\d{10,11}", re.IGNORECASE),
    "PHONE_MOBILE": re.compile(r"(?<!\w)3[0-5]\d[\s\-]?\d{3}[\s\-]?\d{4}(?!\w)"),
    "EMAIL": re.compile(r"[\w\.\-\+]+@[\w\.\-]+\.\w{2,}"),
    "ADDRESS_EXACT": re.compile(
        r"\b(?:Calle|Cll|Carrera|Cra|Kra|Transversal|Tv|Diagonal|Diag|Avenida|Av)\.?\s*\d{1,3}[A-Z]?\s*#?\s*\d{1,3}\s*[\-–]\s*\d{1,3}\b"
    ),
}


def assert_clean(
    docs: list[dict],
    mode: Mode = "selective",
    known_entities: dict[str, list[str]] | None = None,
    strict: bool = True,
) -> list[Violation]:
    """Valida que los docs ya redactados no contengan PII literal.

    En modo `aggressive` además verifica que ningún nombre de `known_entities["PERSON"]`
    aparezca literal. En modo `selective` los nombres están permitidos (son públicos).

    Args:
        docs: lista [{filename, text}] ya redactados.
        mode: selective | aggressive.
        known_entities: para chequeo adicional de nombres en modo aggressive.
        strict: si True, lanza nada pero retorna violaciones. El llamador
                decide si bloquea envío. El flag existe para futuras extensiones.

    Returns:
        Lista de `Violation` — si está vacía, zero PII.
    """
    violations: list[Violation] = []
    kinds = AGGRESSIVE_KINDS if mode == "aggressive" else SELECTIVE_KINDS

    for i, doc in enumerate(docs):
        text = doc.get("text") or ""
        if not text:
            continue
        # Sacar el contenido DENTRO de tokens [...] antes de validar para no marcar
        # "[CC_####5432]" como CC bruta.
        stripped = re.sub(r"\[[A-Z][A-Z0-9_#]*\]", " ", text)

        if "CC" in kinds:
            for m in _CONTROL_PATTERNS["CC"].finditer(stripped):
                if is_false_positive_cc(m.group(), stripped, m.start(), m.end()):
                    continue
                violations.append(Violation("CC", m.group(), m.start(), i))
            for m in _CONTROL_PATTERNS["CC_BARE"].finditer(stripped):
                # Excepción: radicados FOREST (11 dígitos empezando por 2026)
                # se permiten en modo selective (son identificadores internos públicos).
                if mode == "selective" and m.group().startswith("2026") and len(m.group()) == 11:
                    continue
                # Excepción: FOREST interno (7-8 dígitos empezando por 28, 34, etc.)
                if mode == "selective" and is_false_positive_cc(m.group(), stripped, m.start(), m.end()):
                    continue
                violations.append(Violation("CC_BARE", m.group(), m.start(), i))
        if "NUIP" in kinds:
            for m in _CONTROL_PATTERNS["NUIP"].finditer(stripped):
                violations.append(Violation("NUIP", m.group(), m.start(), i))
        if "PHONE" in kinds:
            for m in _CONTROL_PATTERNS["PHONE_MOBILE"].finditer(stripped):
                violations.append(Violation("PHONE", m.group(), m.start(), i))
        if "EMAIL" in kinds:
            for m in _CONTROL_PATTERNS["EMAIL"].finditer(stripped):
                violations.append(Violation("EMAIL", m.group(), m.start(), i))
        if "ADDRESS_EXACT" in kinds:
            for m in _CONTROL_PATTERNS["ADDRESS_EXACT"].finditer(stripped):
                violations.append(Violation("ADDRESS_EXACT", m.group(), m.start(), i))

        # En modo aggressive: chequear nombres de blacklist
        if mode == "aggressive" and known_entities:
            for v in known_entities.get("PERSON", []):
                if not v or len(v.strip()) < 3:
                    continue
                pat = re.compile(re.escape(v.strip()), re.IGNORECASE)
                for m in pat.finditer(stripped):
                    violations.append(Violation("PERSON_LEAK", m.group(), m.start(), i))

    return violations
