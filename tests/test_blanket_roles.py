"""Tests for the blanket-role permission framework (catalina/permissions/blanket_roles.py)."""

from types import SimpleNamespace
from unittest import mock

from arches.app.permissions.arches_default_deny import (
    ArchesDefaultDenyPermissionFramework,
)
from django.test import SimpleTestCase

from catalina.permissions import blanket_roles
from catalina.permissions.blanket_roles import (
    VIEW_PERM,
    BlanketRoleDenyFramework,
)

BASE = ArchesDefaultDenyPermissionFramework
CHANGE_PERM = "change_resourceinstance"
# blanket_roles reads arches' system_settings object, which override_settings
# does not reach, so use whatever value it actually sees.
SYSTEM_SETTINGS_ID = str(blanket_roles.settings.SYSTEM_SETTINGS_RESOURCE_ID)


def _user(**attrs):
    defaults = {"is_authenticated": True, "is_anonymous": False}
    return SimpleNamespace(**{**defaults, **attrs})


def _framework(full=False, read=False):
    """A framework whose group membership checks are answered from ``full``/``read``."""
    framework = BlanketRoleDenyFramework()

    def in_group(user, names):
        if names is blanket_roles.FULL_ACCESS_GROUPS:
            return full
        if names is blanket_roles.READ_ACCESS_GROUPS:
            return read
        return False

    framework.user_in_group_by_name = in_group
    return framework


class BlanketGrantsTests(SimpleTestCase):
    def test_no_user_is_never_granted(self):
        self.assertFalse(_framework(full=True)._blanket_grants(None, VIEW_PERM))

    def test_unauthenticated_user_is_never_granted(self):
        user = _user(is_authenticated=False)
        self.assertFalse(_framework(full=True)._blanket_grants(user, VIEW_PERM))

    def test_anonymous_user_is_never_granted(self):
        user = _user(is_anonymous=True)
        self.assertFalse(_framework(full=True)._blanket_grants(user, VIEW_PERM))

    def test_system_settings_resource_is_never_granted(self):
        resource = SimpleNamespace(pk=SYSTEM_SETTINGS_ID)
        self.assertFalse(
            _framework(full=True)._blanket_grants(_user(), VIEW_PERM, resource)
        )

    def test_full_access_group_gets_every_permission(self):
        framework = _framework(full=True)
        for permission in (VIEW_PERM, CHANGE_PERM, "delete_resourceinstance"):
            self.assertTrue(framework._blanket_grants(_user(), permission))

    def test_read_access_group_gets_view_only(self):
        framework = _framework(read=True)
        self.assertTrue(framework._blanket_grants(_user(), VIEW_PERM))
        self.assertFalse(framework._blanket_grants(_user(), CHANGE_PERM))

    def test_non_member_is_not_granted(self):
        self.assertFalse(_framework()._blanket_grants(_user(), VIEW_PERM))

    def test_ordinary_resource_is_granted(self):
        resource = SimpleNamespace(pk="some-other-resource")
        self.assertTrue(
            _framework(full=True)._blanket_grants(_user(), VIEW_PERM, resource)
        )


class CheckResourceInstancePermissionsTests(SimpleTestCase):
    def _check(self, framework, base_result):
        with mock.patch.object(
            BASE, "check_resource_instance_permissions", return_value=base_result
        ):
            return framework.check_resource_instance_permissions(
                _user(), "rid", VIEW_PERM
            )

    def test_denial_is_upgraded_for_blanket_member(self):
        result = self._check(_framework(full=True), {"permitted": False})
        self.assertTrue(result["permitted"])

    def test_denial_stands_for_non_member(self):
        result = self._check(_framework(), {"permitted": False})
        self.assertFalse(result["permitted"])

    def test_base_grant_is_never_removed(self):
        result = self._check(_framework(), {"permitted": True})
        self.assertTrue(result["permitted"])


class GetAllowedInstancesTests(SimpleTestCase):
    def test_member_with_explicit_resources_gets_them_back(self):
        resources = ["a", "b"]
        result = _framework(read=True).get_allowed_instances(
            _user(), resources=resources
        )
        self.assertEqual(result, resources)

    def test_member_without_resources_gets_all_but_system_settings(self):
        queryset = mock.MagicMock()
        queryset.exclude.return_value.values_list.return_value = ["id-1", "id-2"]
        with mock.patch.object(blanket_roles.ResourceInstance, "objects", queryset):
            result = _framework(read=True).get_allowed_instances(_user())
        queryset.exclude.assert_called_once_with(resourceinstanceid=SYSTEM_SETTINGS_ID)
        self.assertEqual(result, ["id-1", "id-2"])

    def test_non_member_defers_to_base_framework(self):
        with mock.patch.object(
            BASE, "get_allowed_instances", return_value=["from-base"]
        ) as base:
            result = _framework().get_allowed_instances(_user())
        base.assert_called_once()
        self.assertEqual(result, ["from-base"])


class GetSearchUiPermissionsTests(SimpleTestCase):
    def _ui(self, framework, base_result):
        with mock.patch.object(
            BASE, "get_search_ui_permissions", return_value=base_result
        ):
            return framework.get_search_ui_permissions(_user(), {}, [])

    def test_full_access_member_can_read_and_edit(self):
        result = self._ui(_framework(full=True), {"can_read": False, "can_edit": False})
        self.assertTrue(result["can_read"])
        self.assertTrue(result["can_edit"])

    def test_read_access_member_can_read_but_not_edit(self):
        result = self._ui(_framework(read=True), {"can_read": False, "can_edit": False})
        self.assertTrue(result["can_read"])
        self.assertFalse(result["can_edit"])

    def test_non_member_flags_are_untouched(self):
        result = self._ui(_framework(), {"can_read": False, "can_edit": False})
        self.assertFalse(result["can_read"])
        self.assertFalse(result["can_edit"])

    def test_base_flags_are_never_removed(self):
        result = self._ui(_framework(), {"can_read": True, "can_edit": True})
        self.assertTrue(result["can_read"])
        self.assertTrue(result["can_edit"])


class GetPermissionSearchFilterTests(SimpleTestCase):
    def test_member_gets_an_unrestricted_filter(self):
        result = _framework(read=True).get_permission_search_filter(_user())
        self.assertIsInstance(result, blanket_roles.Bool)

    def test_non_member_defers_to_base_framework(self):
        sentinel = object()
        with mock.patch.object(
            BASE, "get_permission_search_filter", return_value=sentinel
        ):
            result = _framework().get_permission_search_filter(_user())
        self.assertIs(result, sentinel)
