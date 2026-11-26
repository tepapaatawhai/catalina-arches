"""Per-account login lockout (pentest finding WA01).

The Arches login view only rate limits by source IP, so a single account could
be guessed at indefinitely from rotating addresses. This locks an account after
a number of consecutive failed logins, keyed on the submitted username rather
than the IP, and rejects every attempt (including a correct password) until the
lock expires.

State lives in the default cache (Redis), so it is shared across pods and needs
no migration. Failures are counted for the submitted username whether or not it
exists, so the behaviour does not reveal which usernames are valid. A locked
attempt fails exactly like a wrong password.

Settings:
    ACCOUNT_LOCKOUT_ENABLED   bool, default True
    ACCOUNT_LOCKOUT_ATTEMPTS  failures before locking, default 3
    ACCOUNT_LOCKOUT_SECONDS   lock duration, default 900
"""

import hashlib

from django.conf import settings
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.core.exceptions import PermissionDenied


def _enabled():
    return getattr(settings, "ACCOUNT_LOCKOUT_ENABLED", True)


def _attempts():
    return getattr(settings, "ACCOUNT_LOCKOUT_ATTEMPTS", 3)


def _seconds():
    return getattr(settings, "ACCOUNT_LOCKOUT_SECONDS", 900)


def _key(kind, username):
    digest = hashlib.sha256(str(username).strip().lower().encode()).hexdigest()
    return f"account_lockout:{kind}:{digest}"


def is_locked(username):
    return bool(username) and cache.get(_key("locked", username)) is not None


def record_failure(username):
    """Count a failed login, locking the account once the limit is reached."""
    if not username or is_locked(username):
        # Attempts made while locked must not extend the lock.
        return
    count_key = _key("count", username)
    cache.add(count_key, 0, timeout=_seconds())
    try:
        count = cache.incr(count_key)
    except ValueError:
        count = 1
        cache.set(count_key, count, timeout=_seconds())
    if count >= _attempts():
        cache.set(_key("locked", username), 1, timeout=_seconds())
        cache.delete(count_key)


def clear(username):
    if username:
        cache.delete_many([_key("count", username), _key("locked", username)])


class LockoutBackend(BaseBackend):
    """Must be first in AUTHENTICATION_BACKENDS.

    Raising PermissionDenied makes Django's authenticate() stop trying the
    remaining backends and return None.
    """

    def authenticate(self, request, username=None, **kwargs):
        if _enabled() and is_locked(username):
            raise PermissionDenied("Account temporarily locked")
        return None


def _on_login_failed(sender, credentials, **kwargs):
    if _enabled():
        record_failure(credentials.get("username"))


def _on_logged_in(sender, user, **kwargs):
    if _enabled():
        clear(user.get_username())


def connect():
    user_login_failed.connect(
        _on_login_failed, dispatch_uid="catalina.account_lockout.failed"
    )
    user_logged_in.connect(
        _on_logged_in, dispatch_uid="catalina.account_lockout.success"
    )
