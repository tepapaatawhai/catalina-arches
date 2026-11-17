"""Tests for catalina/utils/descriptor_language_fallback_patch.py."""

from types import SimpleNamespace
from unittest import mock

from arches.app.models.resource import Resource
from django.test import SimpleTestCase, override_settings

from catalina.utils import descriptor_language_fallback_patch as patch_module

MI_PLACEHOLDER = "Kāore i tautuhitia"
NAME = "Bream Head Archaeological Landscape"


@override_settings(LANGUAGE_CODE="en")
class GetDescriptorTests(SimpleTestCase):
    """Drive the patched Resource.get_descriptor with a fake stored-descriptor table."""

    def setUp(self):
        self.stored = {}
        self.live = {}
        self.stored_calls = []

        def original(resource, descriptor, context):
            language = (context or {}).get("language")
            self.stored_calls.append((language, descriptor))
            return self.stored.get((language, descriptor))

        def compute_live(resource, descriptor, language):
            return self.live.get((language, descriptor))

        self.original = original
        for patcher in (
            mock.patch.object(Resource, "get_descriptor", original),
            mock.patch.object(
                Resource, "_catalina_descriptor_fallback_patched", False, create=True
            ),
            mock.patch.object(
                patch_module,
                "_placeholders",
                {None, "", "Undefined", "undefined", MI_PLACEHOLDER},
            ),
            mock.patch.object(patch_module, "_compute_live", compute_live),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        patch_module.apply()
        self.resource = SimpleNamespace()

    def _get(self, descriptor="name", language="mi"):
        return Resource.get_descriptor(
            self.resource, descriptor, {"language": language}
        )

    def test_value_stored_for_active_language_is_returned_untouched(self):
        self.stored[("mi", "name")] = "Te Ingoa"
        self.stored[("en", "name")] = NAME
        self.assertEqual(self._get(), "Te Ingoa")
        self.assertEqual(self.stored_calls, [("mi", "name")])

    def test_english_placeholder_falls_back_to_stored_default(self):
        self.stored[("mi", "name")] = "Undefined"
        self.stored[("en", "name")] = NAME
        self.assertEqual(self._get(), NAME)

    def test_translated_placeholder_falls_back_to_stored_default(self):
        self.stored[("mi", "name")] = MI_PLACEHOLDER
        self.stored[("en", "name")] = NAME
        self.assertEqual(self._get(), NAME)

    def test_empty_string_and_none_fall_back_to_stored_default(self):
        self.stored[("en", "name")] = NAME
        for empty in ("", None):
            with self.subTest(empty=empty):
                self.stored[("mi", "name")] = empty
                self.assertEqual(self._get(), NAME)

    def test_falls_back_for_other_descriptors_too(self):
        self.stored[("mi", "description")] = MI_PLACEHOLDER
        self.stored[("en", "description")] = "<p>Early landscape</p>"
        self.assertEqual(self._get("description"), "<p>Early landscape</p>")

    def test_nothing_stored_computes_live_for_active_language_first(self):
        self.live[("mi", "name")] = "Te Ingoa"
        self.live[("en", "name")] = NAME
        self.assertEqual(self._get(), "Te Ingoa")

    def test_nothing_stored_uses_live_default_when_active_language_is_empty(self):
        self.live[("mi", "name")] = MI_PLACEHOLDER
        self.live[("en", "name")] = NAME
        self.assertEqual(self._get(), NAME)

    def test_default_language_with_nothing_stored_computes_live(self):
        self.live[("en", "name")] = NAME
        self.assertEqual(self._get(language="en"), NAME)

    def test_default_language_does_not_look_up_the_stored_default_twice(self):
        self.stored[("en", "name")] = "Undefined"
        self._get(language="en")
        self.assertEqual(self.stored_calls, [("en", "name")])

    def test_returns_original_result_when_every_source_is_empty(self):
        self.stored[("mi", "name")] = MI_PLACEHOLDER
        self.assertEqual(self._get(), MI_PLACEHOLDER)

    def test_returns_none_when_nothing_exists_anywhere(self):
        self.assertIsNone(self._get())

    def test_language_comes_from_active_translation_when_context_is_none(self):
        self.stored[("mi", "name")] = MI_PLACEHOLDER
        self.stored[("en", "name")] = NAME
        # apply() binds get_language when it runs, so re-apply under the mock.
        Resource.get_descriptor = self.original
        Resource._catalina_descriptor_fallback_patched = False
        with mock.patch("django.utils.translation.get_language", return_value="mi"):
            patch_module.apply()
        self.assertEqual(Resource.get_descriptor(self.resource, "name", None), NAME)

    def test_apply_twice_does_not_wrap_again(self):
        wrapped = Resource.get_descriptor
        patch_module.apply()
        self.assertIs(Resource.get_descriptor, wrapped)


class PlaceholderTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(patch_module, "_placeholders", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    @override_settings(LANGUAGES=[("en", "English"), ("mi", "Māori")])
    def test_collects_the_translation_of_undefined_for_every_language(self):
        with mock.patch(
            "django.utils.translation.gettext",
            side_effect=["Undefined", MI_PLACEHOLDER],
        ):
            placeholders = patch_module._get_placeholders()
        self.assertTrue(
            {None, "", "Undefined", "undefined", MI_PLACEHOLDER} <= placeholders
        )

    @override_settings(LANGUAGES=[("en", "English")])
    def test_result_is_cached(self):
        first = patch_module._get_placeholders()
        with mock.patch("django.utils.translation.gettext") as gettext:
            second = patch_module._get_placeholders()
        self.assertIs(first, second)
        gettext.assert_not_called()

    @override_settings(LANGUAGES=[("en", "English")])
    def test_is_empty(self):
        for value in (None, "", "Undefined", "undefined"):
            self.assertTrue(patch_module._is_empty(value), value)
        self.assertFalse(patch_module._is_empty(NAME))


class ComputeLiveTests(SimpleTestCase):
    GRAPH_ID = "076f9381-7b00-11e9-8d6b-80000b44d1d9"

    def _function_x_graph(self, module):
        function = mock.Mock()
        function.get_class_module.return_value = lambda: module
        return SimpleNamespace(
            function=function,
            config={"descriptor_types": {"name": {"string_template": "<Name>"}}},
        )

    def _compute(self, function_x_graph=None, raises=None):
        queryset = mock.MagicMock()
        first = queryset.filter.return_value.select_related.return_value.first
        if raises:
            first.side_effect = raises
        else:
            first.return_value = function_x_graph
        manager = mock.Mock(objects=queryset)
        resource = SimpleNamespace(graph_id=self.GRAPH_ID)
        with mock.patch("arches.app.models.models.FunctionXGraph", manager):
            return patch_module._compute_live(resource, "name", "en"), queryset

    def test_returns_the_name_the_descriptor_function_computes(self):
        module = mock.Mock()
        module.get_primary_descriptor_from_nodes.return_value = NAME
        result, queryset = self._compute(self._function_x_graph(module))
        self.assertEqual(result, NAME)
        queryset.filter.assert_called_once_with(
            graph_id=self.GRAPH_ID, function__functiontype="primarydescriptors"
        )
        args = module.get_primary_descriptor_from_nodes.call_args.args
        self.assertEqual(args[1], {"string_template": "<Name>"})
        self.assertEqual(args[2], {"language": "en"})
        self.assertEqual(args[3], "name")

    def test_returns_none_when_graph_has_no_primary_descriptor_function(self):
        result, _ = self._compute(None)
        self.assertIsNone(result)

    def test_returns_none_when_the_function_raises(self):
        module = mock.Mock()
        module.get_primary_descriptor_from_nodes.side_effect = ValueError("boom")
        result, _ = self._compute(self._function_x_graph(module))
        self.assertIsNone(result)

    def test_returns_none_when_the_lookup_raises(self):
        result, _ = self._compute(raises=RuntimeError("db down"))
        self.assertIsNone(result)

    def test_returns_none_when_descriptor_type_is_not_configured(self):
        module = mock.Mock()
        function_x_graph = self._function_x_graph(module)
        function_x_graph.config = {"descriptor_types": {}}
        result, _ = self._compute(function_x_graph)
        self.assertIsNone(result)
