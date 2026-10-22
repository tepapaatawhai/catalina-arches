"""Tests for catalina/utils/graph_validation_patch.py."""

import types
from unittest import mock

from django.test import SimpleTestCase

from catalina.utils import graph_validation_patch


def _fake_graph_class(validate_calls=5):
    """A stand-in for arches' Graph that counts how often widgets are computed."""

    class FakeGraph:
        ontology = None

        def __init__(self):
            self.widget_calls = 0

        def get_widgets(self, use_raw_i18n_json=False, force_recalculation=False):
            self.widget_calls += 1
            return [use_raw_i18n_json, force_recalculation]

        def validate(self):
            for _ in range(validate_calls):
                self.get_widgets()
            return "validated"

        def get_sibling_nodes(self, node):
            """Same logic as arches' Graph.get_sibling_nodes."""
            self.sibling_scans = getattr(self, "sibling_scans", 0) + 1
            sibling_nodes = []
            if node.istopnode is False:
                incoming_edge = list(
                    filter(lambda x: x.rangenode_id == node.nodeid, self.edges.values())
                )[0]
                parent_node_id = incoming_edge.domainnode_id
                sibling_nodes = [
                    edge.rangenode
                    for edge in filter(
                        lambda x: x.domainnode_id == parent_node_id,
                        self.edges.values(),
                    )
                    if edge.rangenode.nodeid != node.nodeid
                ]
            return sibling_nodes

    return FakeGraph


def _node(nodeid, istopnode=False):
    return types.SimpleNamespace(nodeid=nodeid, istopnode=istopnode)


def _tree_graph(graph_class):
    """root -> a, b, c ; a -> d, e"""
    nodes = {n: _node(n, istopnode=(n == "root")) for n in "root a b c d e".split()}
    edges = {}
    for i, (parent, child) in enumerate(
        [("root", "a"), ("root", "b"), ("root", "c"), ("a", "d"), ("a", "e")]
    ):
        edges[f"edge{i}"] = types.SimpleNamespace(
            domainnode_id=parent, rangenode_id=child, rangenode=nodes[child]
        )
    graph = graph_class()
    graph.nodes = nodes
    graph.edges = edges
    return graph


def _apply(graph_class):
    with mock.patch("arches.app.models.graph.Graph", graph_class):
        graph_validation_patch.apply()


class GraphValidationPatchTests(SimpleTestCase):
    def test_widgets_are_computed_once_per_validation(self):
        graph_class = _fake_graph_class()
        _apply(graph_class)
        graph = graph_class()
        self.assertEqual(graph.validate(), "validated")
        self.assertEqual(graph.widget_calls, 1)

    def test_different_arguments_are_cached_separately(self):
        graph_class = _fake_graph_class(validate_calls=0)

        def validate(self):
            for _ in range(3):
                self.get_widgets()
                self.get_widgets(use_raw_i18n_json=True)

        graph_class.validate = validate
        _apply(graph_class)
        graph = graph_class()
        graph.validate()
        self.assertEqual(graph.widget_calls, 2)

    def test_nothing_is_cached_outside_validation(self):
        graph_class = _fake_graph_class()
        _apply(graph_class)
        graph = graph_class()
        graph.validate()
        graph.get_widgets()
        graph.get_widgets()
        self.assertEqual(graph.widget_calls, 3)
        self.assertNotIn("_validate_widgets_cache", graph.__dict__)

    def test_cache_is_removed_when_validation_fails(self):
        graph_class = _fake_graph_class()

        def validate(self):
            self.get_widgets()
            raise ValueError("invalid graph")

        graph_class.validate = validate
        _apply(graph_class)
        graph = graph_class()
        with self.assertRaises(ValueError):
            graph.validate()
        self.assertNotIn("_validate_widgets_cache", graph.__dict__)

    def test_applying_twice_does_not_wrap_again(self):
        graph_class = _fake_graph_class()
        _apply(graph_class)
        patched = graph_class.validate
        _apply(graph_class)
        self.assertIs(graph_class.validate, patched)
        graph = graph_class()
        graph.validate()
        self.assertEqual(graph.widget_calls, 1)


class SiblingNodesPatchTests(SimpleTestCase):
    def _sibling_ids_during_validation(self, graph_class, graph):
        results = {}

        def validate(self):
            for nodeid, node in self.nodes.items():
                results[nodeid] = [n.nodeid for n in self.get_sibling_nodes(node)]

        graph_class.validate = validate
        _apply(graph_class)
        graph.validate()
        return results

    def test_matches_the_original_for_every_node(self):
        expected_class = _fake_graph_class()
        expected_graph = _tree_graph(expected_class)
        expected = {
            nodeid: [n.nodeid for n in expected_graph.get_sibling_nodes(node)]
            for nodeid, node in expected_graph.nodes.items()
        }

        graph_class = _fake_graph_class()
        graph = _tree_graph(graph_class)
        actual = self._sibling_ids_during_validation(graph_class, graph)

        self.assertEqual(actual, expected)
        self.assertEqual(actual["a"], ["b", "c"])
        self.assertEqual(actual["d"], ["e"])
        self.assertEqual(actual["root"], [])

    def test_edges_are_scanned_only_by_the_original_not_during_validation(self):
        graph_class = _fake_graph_class()
        graph = _tree_graph(graph_class)
        self._sibling_ids_during_validation(graph_class, graph)
        # Only the top node falls back to the original (which does no scan).
        self.assertEqual(getattr(graph, "sibling_scans", 0), 1)

    def test_outside_validation_uses_the_original(self):
        graph_class = _fake_graph_class()
        _apply(graph_class)
        graph = _tree_graph(graph_class)
        graph.get_sibling_nodes(graph.nodes["d"])
        graph.get_sibling_nodes(graph.nodes["d"])
        self.assertEqual(graph.sibling_scans, 2)

    def test_node_without_an_incoming_edge_still_raises_like_the_original(self):
        graph_class = _fake_graph_class()
        graph = _tree_graph(graph_class)
        graph.nodes["orphan"] = _node("orphan")

        def validate(self):
            self.get_sibling_nodes(self.nodes["orphan"])

        graph_class.validate = validate
        _apply(graph_class)
        with self.assertRaises(IndexError):
            graph.validate()

    def test_index_is_dropped_after_validation(self):
        graph_class = _fake_graph_class()
        graph = _tree_graph(graph_class)
        self._sibling_ids_during_validation(graph_class, graph)
        self.assertNotIn("_validate_widgets_cache", graph.__dict__)


class _FakeManager:
    class DoesNotExist(Exception):
        pass

    class MultipleObjectsReturned(Exception):
        pass

    model = types.SimpleNamespace(
        DoesNotExist=DoesNotExist,
        MultipleObjectsReturned=MultipleObjectsReturned,
        _meta=types.SimpleNamespace(object_name="OntologyClass"),
    )

    def __init__(self, classes):
        self.classes = classes
        self.all_calls = 0
        self.get_calls = []

    def all(self):
        self.all_calls += 1
        return list(self.classes)

    def get(self, *args, **kwargs):
        self.get_calls.append(kwargs)
        return "real"

    def count(self):
        return len(self.classes)


def _ontology_class(source):
    return types.SimpleNamespace(source=source)


class OntologyClassesShimTests(SimpleTestCase):
    def test_get_by_source_loads_the_classes_once(self):
        manager = _FakeManager([_ontology_class("E1"), _ontology_class("E2")])
        shim = graph_validation_patch._ValidationOntologyClasses(manager)
        self.assertEqual(shim.get(source="E1").source, "E1")
        self.assertEqual(shim.get(source="E2").source, "E2")
        self.assertEqual(shim.get(source="E1").source, "E1")
        self.assertEqual(manager.all_calls, 1)
        self.assertEqual(manager.get_calls, [])

    def test_missing_source_raises_does_not_exist(self):
        shim = graph_validation_patch._ValidationOntologyClasses(
            _FakeManager([_ontology_class("E1")])
        )
        with self.assertRaises(_FakeManager.DoesNotExist):
            shim.get(source="nope")

    def test_duplicate_source_raises_multiple_objects_returned(self):
        shim = graph_validation_patch._ValidationOntologyClasses(
            _FakeManager([_ontology_class("E1"), _ontology_class("E1")])
        )
        with self.assertRaises(_FakeManager.MultipleObjectsReturned):
            shim.get(source="E1")

    def test_other_lookups_and_attributes_go_to_the_real_manager(self):
        manager = _FakeManager([_ontology_class("E1")])
        shim = graph_validation_patch._ValidationOntologyClasses(manager)
        self.assertEqual(shim.get(pk=1), "real")
        self.assertEqual(shim.get(source="E1", ontology=2), "real")
        self.assertEqual(
            manager.get_calls, [{"pk": 1}, {"source": "E1", "ontology": 2}]
        )
        self.assertEqual(shim.count(), 1)


class OntologyDescriptorTests(SimpleTestCase):
    def test_real_manager_outside_validation_and_shim_during_it(self):
        manager = _FakeManager([_ontology_class("E1")])

        class Original:
            def __get__(self, instance, owner=None):
                return manager

            def __set__(self, instance, value):
                pass

        class Ontology:
            ontologyclasses = graph_validation_patch._OntologyClassesDescriptor(
                Original()
            )

        ontology = Ontology()
        self.assertIs(ontology.ontologyclasses, manager)

        ontology.__dict__[graph_validation_patch._ONTOLOGY_CLASSES_ATTR] = {}
        shim = ontology.ontologyclasses
        self.assertIsInstance(shim, graph_validation_patch._ValidationOntologyClasses)
        self.assertIs(ontology.ontologyclasses, shim)

        del ontology.__dict__[graph_validation_patch._ONTOLOGY_CLASSES_ATTR]
        self.assertIs(ontology.ontologyclasses, manager)
