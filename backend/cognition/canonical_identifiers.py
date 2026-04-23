"""Canonical Identifiers — Capa 2 del pipeline cognitivo v6.0.

Cosecha identificadores de un documento (rad23, rad_corto, FOREST, CC,
proc_gobernacion, sello_juzgado) con metadata por identificador:

- value: el valor normalizado canónico
- kind: tipo del identificador
- source_zone: dónde apareció (HEADER, FOOTER_TAIL, VISUAL_ROTATED, BODY...)
- position_confidence: 0-1, alto si está en zona fuerte
- physical_signal: True si coincide con un hallazgo visual (sello, rotado)
- lr: likelihood ratio base para inferencia Bayesiana posterior

La salida (IdentifierSet) alimenta a Bayesian assignment (Capa 5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from backend.agent.regex_library import (
    RAD_23_CONTINUOUS, RAD_23_WITH_SEPARATORS,
    FOREST_SPECIFIC, FOREST_KEYWORD,
    CC_ACCIONANTE, TUTELA_ONLINE_NO,
    SELLO_RADICADOR, FECHA_RECIBIDO, PROC_GOBERNACION, SELLO_JUZGADO,
)


# Kinds que manejamos
KINDS = (
    "rad23", "rad_corto", "forest",
    "cc", "tutela_online", "proc_gobernacion",
    "sello_radicador", "fecha_recibido", "sello_juzgado",
)


@dataclass
class Identifier:
    value: str
    kind: str
    source_zone: str = "BODY"
    position_confidence: float = 0.5
    physical_signal: bool = False
    lr: float = 1.0                           # ratio base, calibrado en Fase 4
    raw_match: str = ""


@dataclass
class IdentifierSet:
    """Colección de identificadores cosechados de UN documento."""
    filename: str = ""
    items: list[Identifier] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[Identifier]:
        return [i for i in self.items if i.kind == kind]

    def best_of(self, kind: str) -> Identifier | None:
        candidates = self.of_kind(kind)
        if not candidates:
            return None
        return max(candidates, key=lambda i: (i.position_confidence, i.lr, i.physical_signal))

    def has(self, kind: str) -> bool:
        return bool(self.of_kind(kind))

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "items": [
                {"kind": i.kind, "value": i.value, "zone": i.source_zone,
                 "position_confidence": round(i.position_confidence, 3),
                 "physical_signal": i.physical_signal, "lr": round(i.lr, 2)}
                for i in self.items
            ],
        }


# ============================================================
# Priors de zona (position_confidence por zona) y LR base por kind
# ============================================================

# position_confidence según dónde aparece
ZONE_PRIOR = {
    "VISUAL_ROTATED": 0.95,   # sello físico del juzgado rotado
    "HEADER": 0.90,           # encabezado del doc
    "FOOTER": 0.85,           # pie de página con firma del abogado
    "FOOTER_TAIL": 0.85,       # últimas páginas íntegras
    "RADICADO": 0.95,         # zona específica de radicado
    "DATES": 0.75,
    "PARTIES": 0.80,
    "RESOLUTION": 0.85,
    "BODY": 0.55,
    "WATERMARK": 0.80,
    "VISUAL": 0.75,
    "TABLE": 0.60,
}

# LR base por kind (calibrado aproximadamente; se refinará en Fase 4)
LR_BASE = {
    "rad23": 50.0,                  # señal muy fuerte
    "rad_corto": 8.0,
    "forest": 12.0,
    "cc": 20.0,                     # identificador muy específico
    "tutela_online": 15.0,
    "proc_gobernacion": 6.0,
    "sello_radicador": 25.0,        # sello físico es fuerte
    "fecha_recibido": 5.0,
    "sello_juzgado": 10.0,
}


def _norm_rad23(s: str) -> str:
    """Devuelve solo dígitos, sin separadores."""
    return re.sub(r"\D", "", s or "")


def _norm_rad_corto_from_rad23(rad23: str) -> str:
    """Deriva 'YYYY-NNNNN' de un rad23 canonical."""
    digits = _norm_rad23(rad23)
    if len(digits) < 20:
        return ""
    m = re.search(r"(20\d{2})(\d{5})\d{2}$", digits)
    if not m:
        return ""
    return f"{m.group(1)}-{m.group(2)}"


# ============================================================
# Harvest principal
# ============================================================

def harvest_identifiers(doc_ir) -> IdentifierSet:
    """Recorre las zonas del IR y cosecha todos los identificadores.

    Args:
        doc_ir: DocumentIR (de ir_models) con zones y full_text
    """
    found = IdentifierSet(filename=getattr(doc_ir, "filename", ""))
    seen: set[tuple[str, str]] = set()  # (kind, value normalizado) para evitar duplicados

    def _add(kind: str, value: str, zone: str, physical: bool = False,
             lr_bonus: float = 1.0, raw_match: str = ""):
        canon = value.strip()
        if not canon:
            return
        key = (kind, _norm_rad23(canon) if kind in ("rad23", "cc", "forest") else canon.upper())
        if key in seen:
            return
        seen.add(key)
        pos_conf = ZONE_PRIOR.get(zone, 0.55)
        # Si hay señal física, subimos position_confidence
        if physical:
            pos_conf = min(1.0, pos_conf + 0.10)
        lr = LR_BASE.get(kind, 1.0) * lr_bonus
        found.items.append(Identifier(
            value=canon, kind=kind, source_zone=zone,
            position_confidence=pos_conf, physical_signal=physical,
            lr=lr, raw_match=raw_match or canon,
        ))

    # --- Cosecha por zona ---
    visual_sig = getattr(doc_ir, "visual_signature", None) or {}
    has_stamp = bool(visual_sig.get("has_radicador_stamp"))
    has_seal = bool(visual_sig.get("has_juzgado_seal"))

    # 1. Zonas del IR
    for zone in getattr(doc_ir, "zones", []):
        text = zone.text or ""
        ztype = zone.zone_type

        # rad23
        for pat in (RAD_23_CONTINUOUS.pattern, RAD_23_WITH_SEPARATORS.pattern):
            for m in pat.finditer(text):
                val = _norm_rad23(m.group(1))
                if len(val) >= 18:
                    _add("rad23", val, ztype, physical=(ztype == "VISUAL" and has_stamp),
                         raw_match=m.group(1))
                    # Derivar rad_corto
                    rc = _norm_rad_corto_from_rad23(val)
                    if rc:
                        _add("rad_corto", rc, ztype)

        # FOREST
        for pat in (FOREST_SPECIFIC.pattern, FOREST_KEYWORD.pattern):
            for m in pat.finditer(text):
                val = re.sub(r"\D", "", m.group(1))
                if val:
                    _add("forest", val, ztype, raw_match=m.group(0))

        # CC
        for m in CC_ACCIONANTE.pattern.finditer(text):
            val = m.group(1)
            _add("cc", val, ztype, raw_match=m.group(0))

        # Tutela online
        for m in TUTELA_ONLINE_NO.pattern.finditer(text):
            _add("tutela_online", m.group(1), ztype, raw_match=m.group(0))

        # Proc Gobernación
        for m in PROC_GOBERNACION.pattern.finditer(text):
            _add("proc_gobernacion", m.group(1), ztype, raw_match=m.group(0))

        # Sello radicador / fecha recibido / sello juzgado
        # más probables en zona VISUAL/HEADER/FOOTER que en BODY
        if ztype in ("VISUAL", "HEADER", "FOOTER", "FOOTER_TAIL", "WATERMARK"):
            for m in SELLO_RADICADOR.pattern.finditer(text):
                _add("sello_radicador", m.group(1), ztype,
                     physical=(ztype == "VISUAL"), raw_match=m.group(0))
            for m in FECHA_RECIBIDO.pattern.finditer(text):
                _add("fecha_recibido", m.group(1), ztype,
                     physical=(ztype == "VISUAL"), raw_match=m.group(0))
            for m in SELLO_JUZGADO.pattern.finditer(text):
                _add("sello_juzgado", m.group(1).strip(), ztype,
                     physical=has_seal, raw_match=m.group(0))

    # 2. Rotated snippets (sello físico) — explícitamente zona VISUAL_ROTATED
    for snip in visual_sig.get("rotated_snippets", [])[:10]:
        snip = snip or ""
        for m in RAD_23_CONTINUOUS.pattern.finditer(snip):
            val = _norm_rad23(m.group(1))
            if len(val) >= 18:
                _add("rad23", val, "VISUAL_ROTATED", physical=True, lr_bonus=1.5,
                     raw_match=m.group(1))
        for m in SELLO_RADICADOR.pattern.finditer(snip):
            _add("sello_radicador", m.group(1), "VISUAL_ROTATED",
                 physical=True, lr_bonus=1.5, raw_match=m.group(0))
        for m in FECHA_RECIBIDO.pattern.finditer(snip):
            _add("fecha_recibido", m.group(1), "VISUAL_ROTATED",
                 physical=True, lr_bonus=1.5, raw_match=m.group(0))
        for m in SELLO_JUZGADO.pattern.finditer(snip):
            _add("sello_juzgado", m.group(1).strip(), "VISUAL_ROTATED",
                 physical=True, lr_bonus=1.3, raw_match=m.group(0))

    return found


def harvest_from_case_ir(case_ir) -> dict[str, IdentifierSet]:
    """Cosecha identificadores de todos los documentos de un caso.

    Returns: dict filename → IdentifierSet
    """
    out: dict[str, IdentifierSet] = {}
    for doc_ir in getattr(case_ir, "documents", []):
        out[doc_ir.filename] = harvest_identifiers(doc_ir)
    return out
