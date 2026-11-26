"""Tests for catalina/utils/string_sanitize_patch.py (needs ``nh3``)."""

from django.test import SimpleTestCase

from catalina.utils.string_sanitize_patch import (
    sanitize_node_value,
    sanitize_plain_text,
    sanitize_rich_text,
)

PAYLOADS = [
    "<img src=x onerror=alert(document.location)>",
    "<script>alert(1)</script>",
    '<a href="javascript:alert(1)">x</a>',
    "<svg onload=alert(1)>",
    '<p onclick="alert(1)">x</p>',
]


class RichTextTests(SimpleTestCase):
    def test_script_vectors_are_removed(self):
        for payload in PAYLOADS:
            with self.subTest(payload=payload):
                out = sanitize_rich_text(payload).lower()
                for bad in ("onerror", "onload", "onclick", "<script", "javascript:"):
                    self.assertNotIn(bad, out)

    def test_formatting_is_kept(self):
        html = (
            "<p>Some <strong>bold</strong> and <em>italic</em></p><ul><li>a</li></ul>"
        )
        self.assertEqual(sanitize_rich_text(html), html)

    def test_safe_links_are_kept(self):
        self.assertIn(
            'href="https://example.org/"',
            sanitize_rich_text('<a href="https://example.org/">x</a>'),
        )


class PlainTextTests(SimpleTestCase):
    def test_tags_are_stripped(self):
        for payload in PAYLOADS:
            with self.subTest(payload=payload):
                self.assertNotIn("<", sanitize_plain_text(payload))

    def test_ampersands_survive(self):
        self.assertEqual(sanitize_plain_text("Smith & Sons"), "Smith & Sons")


class NodeValueTests(SimpleTestCase):
    def test_every_language_is_sanitised(self):
        value = {
            "en": {"value": PAYLOADS[0], "direction": "ltr"},
            "mi": {"value": "<b>kia ora</b>", "direction": "ltr"},
        }
        out = sanitize_node_value(value, rich=False)
        self.assertNotIn("<", out["en"]["value"])
        self.assertEqual(out["mi"]["value"], "kia ora")
        self.assertEqual(out["en"]["direction"], "ltr")

    def test_non_dict_values_pass_through(self):
        self.assertIsNone(sanitize_node_value(None, rich=True))
