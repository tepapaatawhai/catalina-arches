"""Tests for catalina/utils/createable_resources_patch.py."""

import contextlib
import sys
import types
from unittest import mock

from django.test import SimpleTestCase

from catalina.utils import createable_resources_patch

ACTIVE = "11111111-1111-1111-1111-111111111111"
INACTIVE = "22222222-2222-2222-2222-222222222222"


def _fake_backend(createable):
    return types.SimpleNamespace(
        get_createable_resource_types=mock.Mock(return_value=createable)
    )


def _fake_graph_model(active_ids):
    """A GraphModel stand-in whose filter() honours pk__in and is_active."""

    def filter_(pk__in, is_active):
        assert is_active is True
        rows = [pk for pk in pk__in if str(pk) in active_ids]
        return mock.Mock(values_list=mock.Mock(return_value=rows))

    return mock.Mock(objects=mock.Mock(filter=mock.Mock(side_effect=filter_)))


@contextlib.contextmanager
def _patched_arches(backend, active_ids):
    """Swap in fake arches modules so no Django app registry or DB is needed."""
    models_module = types.ModuleType("arches.app.models.models")
    models_module.GraphModel = _fake_graph_model(active_ids)
    with (
        mock.patch.dict(
            sys.modules,
            {
                "arches.app.utils.permission_backend": backend,
                "arches.app.models.models": models_module,
            },
        ),
        mock.patch("arches.app.utils.permission_backend", backend, create=True),
        mock.patch("arches.app.models.models", models_module, create=True),
    ):
        yield


def _apply(backend, active_ids):
    with _patched_arches(backend, active_ids):
        createable_resources_patch.apply()


class CreateableResourcesPatchTests(SimpleTestCase):
    def test_inactive_graphs_are_removed(self):
        backend = _fake_backend({ACTIVE, INACTIVE})
        _apply(backend, {ACTIVE})
        self.assertEqual(backend.get_createable_resource_types(mock.Mock()), [ACTIVE])

    def test_active_graphs_are_kept_in_original_order(self):
        backend = _fake_backend([ACTIVE, "other"])
        _apply(backend, {ACTIVE, "other"})
        self.assertEqual(
            backend.get_createable_resource_types(mock.Mock()), [ACTIVE, "other"]
        )

    def test_nothing_createable_returns_empty_list(self):
        backend = _fake_backend([])
        _apply(backend, set())
        self.assertEqual(backend.get_createable_resource_types(mock.Mock()), [])

    def test_all_inactive_returns_empty_list(self):
        backend = _fake_backend([INACTIVE])
        _apply(backend, set())
        self.assertEqual(backend.get_createable_resource_types(mock.Mock()), [])

    def test_user_is_passed_to_the_original_function(self):
        backend = _fake_backend([ACTIVE])
        original = backend.get_createable_resource_types
        _apply(backend, {ACTIVE})
        user = mock.Mock()
        backend.get_createable_resource_types(user)
        original.assert_called_once_with(user)

    def test_applying_twice_does_not_wrap_again(self):
        backend = _fake_backend([ACTIVE])
        _apply(backend, {ACTIVE})
        patched = backend.get_createable_resource_types
        _apply(backend, {ACTIVE})
        self.assertIs(backend.get_createable_resource_types, patched)
