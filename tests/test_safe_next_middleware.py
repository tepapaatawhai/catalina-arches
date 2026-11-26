"""Tests for catalina/utils/safe_next_middleware.py."""

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from catalina.utils.safe_next_middleware import SafeNextMiddleware


def _run(method, path, data):
    seen = {}

    def view(request):
        seen["get"] = request.GET.get("next")
        seen["post"] = request.POST.get("next")
        return HttpResponse()

    rf = RequestFactory()
    request = (
        rf.get(path, data, HTTP_HOST="app.example.nz")
        if method == "GET"
        else rf.post(path, data, HTTP_HOST="app.example.nz")
    )
    SafeNextMiddleware(view)(request)
    return seen


@override_settings(ALLOWED_HOSTS=["app.example.nz"])
class SafeNextTests(SimpleTestCase):
    def test_external_urls_are_replaced_on_get(self):
        for bad in (
            "https://bastionsecurity.co.nz",
            "//evil.example",
            "/\\evil.example",
            "javascript:alert(1)",
            "https://app.example.nz.evil.example/",
        ):
            with self.subTest(bad=bad):
                self.assertEqual(_run("GET", "/en/auth/", {"next": bad})["get"], "/")

    def test_external_url_is_replaced_on_login_post(self):
        for path in (
            "/en/auth/",
            "/en/admin/login/",
            "/en/two-factor-authentication-login",
        ):
            with self.subTest(path=path):
                seen = _run("POST", path, {"next": "https://bastionsecurity.co.nz"})
                self.assertEqual(seen["post"], "/")

    def test_internal_paths_are_kept(self):
        for good in ("/en/index.htm", "/resource/abc?x=1", "http://app.example.nz/x"):
            with self.subTest(good=good):
                self.assertEqual(_run("GET", "/en/auth/", {"next": good})["get"], good)

    def test_other_post_bodies_are_untouched(self):
        seen = _run("POST", "/en/api/thing", {"next": "https://evil.example"})
        self.assertEqual(seen["post"], "https://evil.example")
