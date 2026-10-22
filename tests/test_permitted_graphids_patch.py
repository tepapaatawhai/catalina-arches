"""Tests for catalina/utils/permitted_graphids_patch.py."""

import sys
import types
from unittest import mock

from django.test import SimpleTestCase

from catalina.utils import permitted_graphids_patch

ONE = "11111111-1111-1111-1111-111111111111"
TWO = "22222222-2222-2222-2222-222222222222"


def _fake_components():
    rtf = types.ModuleType("arches.app.search.components.resource_type_filter")
    rtf.get_permitted_graphids = mock.Mock(name="original")
    sr = types.ModuleType("arches.app.search.components.search_results")
    sr.get_permitted_graphids = rtf.get_permitted_graphids
    package = types.ModuleType("arches.app.search.components")
    package.resource_type_filter = rtf
    package.search_results = sr
    return package, rtf, sr


class PermittedGraphidsPatchTests(SimpleTestCase):
    def _apply(self):
        package, rtf, sr = _fake_components()
        with mock.patch.dict(
            sys.modules,
            {
                "arches.app.search.components": package,
                "arches.app.search.components.resource_type_filter": rtf,
                "arches.app.search.components.search_results": sr,
            },
        ):
            permitted_graphids_patch.apply()
            permitted_graphids_patch.apply()
        return rtf, sr

    def test_both_modules_are_patched(self):
        rtf, sr = self._apply()
        self.assertIs(
            rtf.get_permitted_graphids, permitted_graphids_patch.get_permitted_graphids
        )
        self.assertIs(
            sr.get_permitted_graphids, permitted_graphids_patch.get_permitted_graphids
        )

    def test_returns_set_of_strings_from_a_single_graph_query(self):
        models = types.ModuleType("arches.app.models.models")
        models.Node = mock.Mock()
        graphs = mock.Mock()
        graphs.objects.filter.return_value.exclude.return_value.values_list.return_value = [
            ONE,
            TWO,
        ]
        models.GraphModel = graphs
        with (
            mock.patch.dict(sys.modules, {"arches.app.models.models": models}),
            mock.patch("arches.app.models.models", models, create=True),
        ):
            result = permitted_graphids_patch.get_permitted_graphids(["ng"])
        self.assertEqual(result, {ONE, TWO})
        models.Node.objects.filter.assert_called_once_with(nodegroup__in=["ng"])
        graphs.objects.filter.return_value.exclude.assert_called_once_with(
            is_active=False
        )
