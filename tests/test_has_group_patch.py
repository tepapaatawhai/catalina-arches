"""Tests for catalina/utils/has_group_patch.py."""

from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from catalina.utils import has_group_patch


def _user(**attrs):
    return SimpleNamespace(**{"is_authenticated": True, "is_superuser": False, **attrs})


class HasGroupTests(SimpleTestCase):
    def _has_group(self, user, names, *, allowed):
        with mock.patch(
            "arches.app.utils.permission_backend.user_in_group_by_name",
            return_value=allowed,
        ) as check:
            return has_group_patch.has_group(user, names), check

    def test_superuser_is_always_true(self):
        result, check = self._has_group(
            _user(is_superuser=True), "Graph Editor", allowed=False
        )
        self.assertTrue(result)
        check.assert_not_called()

    def test_unauthenticated_is_false(self):
        result, _ = self._has_group(
            _user(is_authenticated=False), "Graph Editor", allowed=True
        )
        self.assertFalse(result)

    def test_comma_separated_names_are_split_for_the_framework(self):
        result, check = self._has_group(
            _user(), "RDM Administrator,Graph Editor", allowed=True
        )
        self.assertTrue(result)
        check.assert_called_once_with(mock.ANY, ["RDM Administrator", "Graph Editor"])

    def test_framework_denial_is_false(self):
        result, _ = self._has_group(_user(), "Graph Editor", allowed=False)
        self.assertFalse(result)
