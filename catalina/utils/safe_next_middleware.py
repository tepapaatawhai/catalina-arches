"""Stop login redirects leaving the site (pentest finding WA03).

Arches' login views redirect to the ``next`` parameter without checking it, so
``/auth/?next=https://evil.example`` bounces the user to an attacker's site
right after they authenticate. ``next`` is read in many places (the login view,
the TOTP step, the external OAuth and Azure flows, and the login template that
echoes it back into a hidden field), so rather than patch each one this
rewrites any unsafe ``next`` to ``/`` before the view sees it.

Only same-host relative URLs or URLs on this request's own host are kept.
Protocol-relative (``//evil``), backslash and ``javascript:`` tricks are
rejected by Django's ``url_has_allowed_host_and_scheme``.
"""

import re

from django.utils.http import url_has_allowed_host_and_scheme

SAFE_FALLBACK = "/"

# POST bodies are only parsed on login routes, so other POST requests (uploads,
# JSON APIs) are never touched.
_LOGIN_POST_PATH = re.compile(
    r"/(auth/?|admin/login/?|two-factor-authentication-login.*|azure_auth/.*)$"
)


def _clean(querydict, host, secure):
    values = querydict.getlist("next")
    if not values or all(
        url_has_allowed_host_and_scheme(v, {host}, require_https=secure) for v in values
    ):
        return querydict
    cleaned = querydict.copy()
    cleaned.setlist(
        "next",
        [
            (
                v
                if url_has_allowed_host_and_scheme(v, {host}, require_https=secure)
                else SAFE_FALLBACK
            )
            for v in values
        ],
    )
    return cleaned


class SafeNextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host()
        secure = request.is_secure()
        if "next" in request.GET:
            request.GET = _clean(request.GET, host, secure)
        if request.method == "POST" and _LOGIN_POST_PATH.search(request.path):
            request.POST = _clean(request.POST, host, secure)
        return self.get_response(request)
