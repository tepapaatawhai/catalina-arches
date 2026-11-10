"""Tests for catalina/utils/relationship_label_patch.py."""

from types import SimpleNamespace
from unittest import mock

from arches.app.datatypes import datatypes
from arches.app.models.models import Value
from django.test import SimpleTestCase

from catalina.utils import relationship_label_patch

VALUE_ID = "6aaaa8d5-2a6b-44c9-857f-806271c17451"


class FakeItemValues:
    """Stands in for ListItemValue.objects, keyed on the filters the patch uses."""

    def __init__(self, found=None, siblings=()):
        self.found = found
        self.siblings = list(siblings)

    def filter(self, **kwargs):
        if "pk" in kwargs:
            return FakeQuerySet([self.found] if self.found else [])
        return FakeQuerySet(self.siblings)


class FakeQuerySet:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, **kwargs):
        language = kwargs.get("language_id")
        return FakeQuerySet([r for r in self.rows if r.language_id == language])

    def first(self):
        return self.rows[0] if self.rows else None


def _row(value, language_id="en"):
    return SimpleNamespace(value=value, language_id=language_id, list_item_id="item")


class GetRelationshipDisplayValueTests(SimpleTestCase):
    def _call(self, item_values, language="en"):
        manager = mock.Mock(objects=item_values)
        with (
            mock.patch("arches_controlled_lists.models.ListItemValue", manager),
            mock.patch("django.utils.translation.get_language", return_value=language),
        ):
            return relationship_label_patch.get_relationship_display_value(
                mock.Mock(), VALUE_ID
            )

    def test_controlled_list_item_returns_label_in_current_language(self):
        items = FakeItemValues(
            found=_row("period of professional activity"),
            siblings=[
                _row("te wa", "mi"),
                _row("period of professional activity", "en"),
            ],
        )
        self.assertEqual(self._call(items, "mi"), "te wa")

    def test_regional_language_falls_back_to_base_language(self):
        items = FakeItemValues(found=_row("x"), siblings=[_row("period", "en")])
        self.assertEqual(self._call(items, "en-us"), "period")

    def test_falls_back_to_any_preflabel_when_language_has_none(self):
        items = FakeItemValues(found=_row("x"), siblings=[_row("te wa", "mi")])
        self.assertEqual(self._call(items, "en"), "te wa")

    def test_falls_back_to_the_value_itself_without_preflabels(self):
        items = FakeItemValues(found=_row("only value"), siblings=[])
        self.assertEqual(self._call(items), "only value")

    def test_missing_language_still_resolves(self):
        items = FakeItemValues(found=_row("x"), siblings=[_row("en label", "en")])
        self.assertEqual(self._call(items, None), "en label")

    def test_legacy_concept_value_is_used_when_not_a_list_item(self):
        with mock.patch(
            "arches.app.models.concept.get_preflabel_from_valueid",
            return_value={"value": "is related to"},
        ):
            self.assertEqual(self._call(FakeItemValues()), "is related to")

    def test_legacy_value_without_preflabel_is_none(self):
        with mock.patch(
            "arches.app.models.concept.get_preflabel_from_valueid",
            return_value=None,
        ):
            self.assertIsNone(self._call(FakeItemValues()))

    def test_unknown_id_is_none_instead_of_raising(self):
        with mock.patch(
            "arches.app.models.concept.get_preflabel_from_valueid",
            side_effect=Value.DoesNotExist,
        ):
            with self.assertLogs(relationship_label_patch.logger, "WARNING"):
                self.assertIsNone(self._call(FakeItemValues()))


class ApplyTests(SimpleTestCase):
    def test_apply_replaces_the_method_once(self):
        cls = datatypes.ResourceInstanceDataType
        original = cls.__dict__["get_relationship_display_value"]
        had_flag = "_catalina_relationship_label_patched" in cls.__dict__
        try:
            if had_flag:
                del cls._catalina_relationship_label_patched
            relationship_label_patch.apply()
            self.assertIs(
                cls.__dict__["get_relationship_display_value"],
                relationship_label_patch.get_relationship_display_value,
            )
            cls.get_relationship_display_value = original
            relationship_label_patch.apply()
            self.assertIs(cls.__dict__["get_relationship_display_value"], original)
        finally:
            cls.get_relationship_display_value = original
            if had_flag:
                cls._catalina_relationship_label_patched = True
            elif "_catalina_relationship_label_patched" in cls.__dict__:
                del cls._catalina_relationship_label_patched
