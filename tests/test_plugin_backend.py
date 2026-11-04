"""Tests for catalina/permissions/plugin_backend.py."""

from types import SimpleNamespace
from unittest import mock

from arches.app.models.models import Plugin
from django.test import SimpleTestCase

from catalina.permissions import plugin_backend
from catalina.permissions.plugin_backend import PluginPermissionBackend


def _user(**attrs):
    return SimpleNamespace(**{"is_active": True, **attrs})


class PluginPermissionBackendTests(SimpleTestCase):
    def _has_perm(self, user, perm="view_plugin", obj=None, *, exists=True):
        obj = Plugin() if obj is None else obj
        queryset = mock.MagicMock()
        queryset.filter.return_value.exists.return_value = exists
        with mock.patch.object(plugin_backend.Permission, "objects", queryset):
            return PluginPermissionBackend().has_perm(user, perm, obj), queryset

    def test_group_with_view_plugin_sees_the_plugin(self):
        result, _ = self._has_perm(_user())
        self.assertTrue(result)

    def test_app_label_prefixed_permission_is_accepted(self):
        result, _ = self._has_perm(_user(), "models.view_plugin")
        self.assertTrue(result)

    def test_group_without_the_permission_is_denied(self):
        result, _ = self._has_perm(_user(), exists=False)
        self.assertFalse(result)

    def test_other_permissions_are_not_granted(self):
        result, queryset = self._has_perm(_user(), "change_plugin")
        self.assertFalse(result)
        queryset.filter.assert_not_called()

    def test_non_plugin_objects_are_ignored(self):
        result, queryset = self._has_perm(_user(), obj=object())
        self.assertFalse(result)
        queryset.filter.assert_not_called()

    def test_inactive_user_is_denied(self):
        result, queryset = self._has_perm(_user(is_active=False))
        self.assertFalse(result)
        queryset.filter.assert_not_called()

    def test_answer_is_cached_on_the_user(self):
        user = _user()
        queryset = mock.MagicMock()
        queryset.filter.return_value.exists.return_value = True
        with mock.patch.object(plugin_backend.Permission, "objects", queryset):
            backend = PluginPermissionBackend()
            backend.has_perm(user, "view_plugin", Plugin())
            backend.has_perm(user, "view_plugin", Plugin())
        queryset.filter.assert_called_once()
