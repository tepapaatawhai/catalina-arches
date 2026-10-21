"""Tests for catalina/utils/graph_validation_patch.py."""

from unittest import mock

from django.test import SimpleTestCase

from catalina.utils import graph_validation_patch


def _fake_graph_class(validate_calls=5):
    """A stand-in for arches' Graph that counts how often widgets are computed."""

    class FakeGraph:
        def __init__(self):
            self.widget_calls = 0

        def get_widgets(self, use_raw_i18n_json=False, force_recalculation=False):
            self.widget_calls += 1
            return [use_raw_i18n_json, force_recalculation]

        def validate(self):
            for _ in range(validate_calls):
                self.get_widgets()
            return "validated"

    return FakeGraph


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
