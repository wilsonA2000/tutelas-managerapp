"""Tests F5: actor_graph — Capa 3."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.cognition.actor_graph import (
    ActorGraph, ActorNode, Relation,
    _norm_name, _node_id, _is_generic, _looks_like_person,
    build_from_case,
)


class TestNormalizacion:
    def test_norm_sin_acentos(self):
        assert _norm_name("Nuñez") == "NUNEZ"
        assert _norm_name("  PAOLA  andrea ") == "PAOLA ANDREA"

    def test_node_id_estable(self):
        a = _node_id("PERSON", "Paola Andrea García")
        b = _node_id("PERSON", "PAOLA ANDREA GARCIA")
        assert a == b

    def test_is_generic(self):
        assert _is_generic("ACCIONANTE")
        assert _is_generic("Señor")
        assert not _is_generic("Paola Andrea García")

    def test_looks_like_person(self):
        assert _looks_like_person("Paola Andrea García Núñez")
        assert not _looks_like_person("GOBERNACIÓN DE SANTANDER")
        assert not _looks_like_person("Juzgado Noveno Civil")


class TestActorGraphBasico:
    def test_add_or_merge(self):
        g = ActorGraph()
        n1 = ActorNode(node_id="per:x", kind="PERSON", canonical_name="X",
                       roles={"accionante"}, confidence=0.7)
        n2 = ActorNode(node_id="per:x", kind="PERSON", canonical_name="X",
                       roles={"vinculado"}, confidence=0.5)
        g.add_or_merge(n1)
        g.add_or_merge(n2)
        assert len(g.nodes) == 1
        assert g.nodes["per:x"].roles == {"accionante", "vinculado"}
        assert g.nodes["per:x"].confidence == 0.7

    def test_relation_dedup(self):
        g = ActorGraph()
        g.add_relation(Relation(source_id="a", target_id="b", kind="X", confidence=0.5))
        g.add_relation(Relation(source_id="a", target_id="b", kind="X", confidence=0.8))
        assert len(g.relations) == 1
        assert g.relations[0].confidence == 0.8

    def test_actors_with_role(self):
        g = ActorGraph()
        g.add_or_merge(ActorNode(node_id="a", kind="PERSON", canonical_name="A",
                                 roles={"accionante"}))
        g.add_or_merge(ActorNode(node_id="b", kind="PERSON", canonical_name="B",
                                 roles={"accionado"}))
        g.add_or_merge(ActorNode(node_id="c", kind="PERSON", canonical_name="C",
                                 roles={"accionante", "vinculado"}))
        assert len(g.actors_with_role("accionante")) == 2
        assert len(g.actors_with_role("vinculado")) == 1


class TestBuildFromCase:
    def test_caso_con_juzgado_y_abogado(self):
        class _C:
            id = 1
            juzgado = "Juzgado Noveno Civil de Bucaramanga"
            abogado_responsable = "Juan Diego Cruz Lizcano"
        g = build_from_case(_C())
        assert g.actors_with_role("juzgado")
        assert g.actors_with_role("abogado")
        assert g.nodes[_node_id("PERS", "Juan Diego Cruz Lizcano")].canonical_name == "Juan Diego Cruz Lizcano"

    def test_serializable(self):
        class _C:
            id = 1
            juzgado = "Juzgado X"
            abogado_responsable = "Ab Y"
        g = build_from_case(_C())
        d = g.to_dict()
        assert "nodes" in d
        assert "relations" in d
