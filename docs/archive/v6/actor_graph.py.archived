"""Actor Graph — Capa 3 del pipeline cognitivo v6.0.

En vez de tratar accionantes/accionados/vinculados como strings separados,
construye un GRAFO donde cada persona/entidad es un nodo con atributos
(CC, rol, documento fuente) y las relaciones son aristas
(acciona_contra, vincula, proyecta, emite, impugna).

Beneficios sobre la v5.5:
- Soporta litisconsorcio (múltiples accionantes en un caso) sin truncar.
- Resuelve correferencias: "el accionante" en un auto ↔ nombre completo en
  el escrito de tutela.
- Permite queries tipo "¿quién proyectó la respuesta?" o "¿contra quién
  acciona?" sin parsear strings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from backend.cognition.entity_extractor import extract_actors, Actor


# ============================================================
# Nodos y aristas
# ============================================================

@dataclass
class ActorNode:
    node_id: str                             # id canónico (e.g. "PERS:paola_andrea_garcia" o "ORG:gobernacion_santander")
    kind: str                                # PERSON / ORGANIZATION / JUZGADO
    canonical_name: str
    aliases: set[str] = field(default_factory=set)
    cc: str = ""                             # si es persona y se conoce
    roles: set[str] = field(default_factory=set)   # accionante, accionado, vinculado, abogado, juez...
    source_docs: set[str] = field(default_factory=set)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "canonical_name": self.canonical_name,
            "aliases": sorted(self.aliases),
            "cc": self.cc,
            "roles": sorted(self.roles),
            "source_docs": sorted(self.source_docs),
            "confidence": round(self.confidence, 3),
        }


@dataclass
class Relation:
    source_id: str
    target_id: str
    kind: str            # acciona_contra, vincula, proyecta, impugna, emite
    source_doc: str = ""
    confidence: float = 0.7

    def to_dict(self) -> dict:
        return {
            "source": self.source_id,
            "target": self.target_id,
            "kind": self.kind,
            "doc": self.source_doc,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class ActorGraph:
    nodes: dict[str, ActorNode] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)

    def add_or_merge(self, node: ActorNode) -> ActorNode:
        if node.node_id in self.nodes:
            existing = self.nodes[node.node_id]
            existing.aliases |= node.aliases
            existing.roles |= node.roles
            existing.source_docs |= node.source_docs
            if not existing.cc and node.cc:
                existing.cc = node.cc
            existing.confidence = max(existing.confidence, node.confidence)
            return existing
        self.nodes[node.node_id] = node
        return node

    def add_relation(self, rel: Relation) -> None:
        # Dedupe simple
        for r in self.relations:
            if (r.source_id == rel.source_id and r.target_id == rel.target_id
                    and r.kind == rel.kind):
                r.confidence = max(r.confidence, rel.confidence)
                return
        self.relations.append(rel)

    def actors_with_role(self, role: str) -> list[ActorNode]:
        return [n for n in self.nodes.values() if role in n.roles]

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "relations": [r.to_dict() for r in self.relations],
        }


# ============================================================
# Normalización canónica de nombres
# ============================================================

def _norm_name(s: str) -> str:
    """Normaliza nombre para matching: sin acentos, UPPERCASE, trimeado."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s.strip()).upper()
    return s


def _node_id(kind: str, name: str) -> str:
    nn = _norm_name(name)
    slug = re.sub(r"[^A-Z0-9]+", "_", nn).strip("_").lower()
    return f"{kind[:3]}:{slug[:50]}"


# Token genéricos que NO son un nombre real (false positives del NER)
GENERIC_STOPWORDS = {
    "ACCIONANTE", "ACCIONADO", "ACCIONADA", "DEMANDANTE", "DEMANDADO",
    "TUTELANTE", "REPRESENTANTE", "LEGAL", "MUNICIPAL", "SEÑOR", "SEÑORA",
    "DOCTOR", "DOCTORA", "MENOR", "AGENTE", "OFICIOSO",
}


def _is_generic(name: str) -> bool:
    tokens = _norm_name(name).split()
    if not tokens:
        return True
    real_tokens = [t for t in tokens if t not in GENERIC_STOPWORDS and len(t) >= 3]
    return len(real_tokens) < 2


# ============================================================
# Construcción principal
# ============================================================

def build_from_case(case, case_ir=None, ids_by_doc: dict | None = None) -> ActorGraph:
    """Construye ActorGraph de UN caso a partir del IR + identificadores cosechados.

    Args:
        case: SQLAlchemy Case (para abogado_responsable, juzgado...)
        case_ir: CaseIR con .documents (cada uno con zones, full_text)
        ids_by_doc: dict filename → IdentifierSet (opcional) para cross-matching CC/nombres
    """
    g = ActorGraph()

    # 1. Juzgado del caso (si existe)
    if getattr(case, "juzgado", None):
        j = ActorNode(
            node_id=_node_id("JUZ", case.juzgado),
            kind="JUZGADO",
            canonical_name=case.juzgado,
            roles={"juzgado"},
            confidence=0.9,
        )
        g.add_or_merge(j)

    # 2. Abogado responsable (Gobernación)
    if getattr(case, "abogado_responsable", None):
        ab = ActorNode(
            node_id=_node_id("PERS", case.abogado_responsable),
            kind="PERSON",
            canonical_name=case.abogado_responsable,
            roles={"abogado"},
            confidence=0.9,
        )
        g.add_or_merge(ab)

    # 3. Recorrer documentos del IR y extraer actores por doc
    for doc_ir in getattr(case_ir, "documents", []) if case_ir else []:
        full_text = getattr(doc_ir, "full_text", "") or ""
        if not full_text:
            continue
        try:
            actors = extract_actors(full_text, zones=None)
        except Exception:
            continue

        for a in actors.accionantes:
            _add_actor_to_graph(g, a, role="accionante", doc_ir=doc_ir)
        for a in actors.accionados:
            _add_actor_to_graph(g, a, role="accionado", doc_ir=doc_ir)
        for a in actors.vinculados:
            _add_actor_to_graph(g, a, role="vinculado", doc_ir=doc_ir)

        # Cruzar con IdentifierSet para vincular CC a nodo persona
        if ids_by_doc:
            ids = ids_by_doc.get(doc_ir.filename)
            if ids:
                ccs = [i.value for i in ids.of_kind("cc")]
                # Heurística: la primera CC del doc tiende a ser del accionante
                if ccs and actors.accionantes:
                    node_id = _node_id("PERS", actors.accionantes[0].name)
                    if node_id in g.nodes:
                        g.nodes[node_id].cc = ccs[0]

    # 4. Construir relaciones simples accionante → accionado
    accionantes = g.actors_with_role("accionante")
    accionados = g.actors_with_role("accionado")
    for a in accionantes:
        for d in accionados:
            g.add_relation(Relation(
                source_id=a.node_id, target_id=d.node_id,
                kind="acciona_contra", confidence=0.85,
            ))

    # 5. Abogado → proyecta docs de respuesta
    abogados = g.actors_with_role("abogado")
    for ab in abogados:
        for doc_ir in getattr(case_ir, "documents", []) if case_ir else []:
            if doc_ir.doc_type and "RESPUESTA" in doc_ir.doc_type:
                g.add_relation(Relation(
                    source_id=ab.node_id, target_id=doc_ir.filename,
                    kind="proyecta", source_doc=doc_ir.filename, confidence=0.8,
                ))

    return g


def _add_actor_to_graph(g: ActorGraph, actor: Actor, role: str, doc_ir) -> None:
    """Agrega un Actor (del entity_extractor) al ActorGraph con merge inteligente."""
    name = (actor.name or "").strip()
    if not name or _is_generic(name):
        return
    kind = "PERSON" if _looks_like_person(name) else "ORGANIZATION"
    node = ActorNode(
        node_id=_node_id(kind, name),
        kind=kind,
        canonical_name=name,
        aliases={_norm_name(name)},
        roles={role},
        source_docs={doc_ir.filename} if doc_ir else set(),
        confidence=getattr(actor, "confidence", 0.6),
    )
    g.add_or_merge(node)


def _looks_like_person(name: str) -> bool:
    """Heurística: ¿este string es probablemente un nombre de persona?"""
    nn = _norm_name(name)
    # Organizaciones comunes
    org_markers = ("GOBERNACION", "SECRETARIA", "MINISTERIO", "ALCALDIA",
                   "JUZGADO", "TRIBUNAL", "PERSONERIA", "FISCALIA",
                   "EPS", "IPS", "INSTITUCION", "MUNICIPIO", "DEPARTAMENTO",
                   "CONTRALORIA", "PROCURADURIA")
    if any(m in nn for m in org_markers):
        return False
    # Si tiene 2-5 tokens de letras y cada uno >=3 chars → probablemente persona
    tokens = [t for t in nn.split() if len(t) >= 3]
    return 2 <= len(tokens) <= 6
