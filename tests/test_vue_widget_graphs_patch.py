"""Tests for catalina/utils/vue_widget_graphs_patch.py."""

import contextlib
import sys
import types
from unittest import mock

from django.test import SimpleTestCase

from catalina.utils import vue_widget_graphs_patch

ACTIVE = "11111111-1111-1111-1111-111111111111"
INACTIVE = "22222222-2222-2222-2222-222222222222"


def _widget(graphs):
    return {"node": {"config": {"graphs": graphs, "other": 1}}}


def _graph_model(active_ids):
    """A GraphModel stand-in whose filter() honours pk__in and is_active."""

    def filter_(pk__in, is_active):
        assert is_active is True
        rows = [pk for pk in pk__in if str(pk) in active_ids]
        return mock.Mock(values_list=mock.Mock(return_value=rows))

    return mock.Mock(objects=mock.Mock(filter=mock.Mock(side_effect=filter_)))


@contextlib.contextmanager
def _fake_arches(active_ids, view_module=None):
    """Swap in fake arches modules so no Django app registry or DB is needed."""
    models_module = types.ModuleType("arches.app.models.models")
    models_module.GraphModel = _graph_model(active_ids)
    modules = {"arches.app.models.models": models_module}
    if view_module is not None:
        package = types.ModuleType("arches_vue_components.views.api")
        package.card_x_node_x_widget = view_module
        modules["arches_vue_components.views.api"] = package
        modules["arches_vue_components.views.api.card_x_node_x_widget"] = view_module
    with (
        mock.patch.dict(sys.modules, modules),
        mock.patch("arches.app.models.models", models_module, create=True),
    ):
        yield


class FilterInactiveGraphsTests(SimpleTestCase):
    def test_inactive_graphs_are_removed(self):
        widget = _widget(
            [{"graphid": ACTIVE, "name": "A"}, {"graphid": INACTIVE, "name": "B"}]
        )
        with _fake_arches({ACTIVE}):
            result = vue_widget_graphs_patch.filter_inactive_graphs(widget)
        self.assertEqual(
            result["node"]["config"]["graphs"], [{"graphid": ACTIVE, "name": "A"}]
        )

    def test_other_config_keys_are_kept(self):
        widget = _widget([{"graphid": INACTIVE}])
        with _fake_arches(set()):
            result = vue_widget_graphs_patch.filter_inactive_graphs(widget)
        self.assertEqual(result["node"]["config"]["graphs"], [])
        self.assertEqual(result["node"]["config"]["other"], 1)

    def test_widgets_without_graphs_are_returned_unchanged(self):
        for widget in ({}, {"node": {}}, {"node": {"config": None}}, _widget([])):
            with _fake_arches(set()):
                self.assertIs(
                    vue_widget_graphs_patch.filter_inactive_graphs(widget), widget
                )


class ApplyTests(SimpleTestCase):
    def _view_module(self, widget):
        return types.SimpleNamespace(
            serialize_card_x_node_x_widget=mock.Mock(return_value=widget)
        )

    def test_serializer_output_is_filtered(self):
        widget = _widget([{"graphid": ACTIVE}, {"graphid": INACTIVE}])
        view = self._view_module(widget)
        with _fake_arches({ACTIVE}, view):
            vue_widget_graphs_patch.apply()
            result = view.serialize_card_x_node_x_widget("w", "factory")
        self.assertEqual(result["node"]["config"]["graphs"], [{"graphid": ACTIVE}])

    def test_arguments_are_passed_through(self):
        view = self._view_module(_widget([]))
        original = view.serialize_card_x_node_x_widget
        with _fake_arches(set(), view):
            vue_widget_graphs_patch.apply()
            view.serialize_card_x_node_x_widget("w", "factory")
        original.assert_called_once_with("w", "factory")

    def test_applying_twice_does_not_wrap_again(self):
        view = self._view_module(_widget([]))
        with _fake_arches(set(), view):
            vue_widget_graphs_patch.apply()
            patched = view.serialize_card_x_node_x_widget
            vue_widget_graphs_patch.apply()
        self.assertIs(view.serialize_card_x_node_x_widget, patched)
