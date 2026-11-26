"""Tests for catalina/utils/account_lockout.py."""

from types import SimpleNamespace

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from catalina.utils import account_lockout

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
BACKENDS = [
    "catalina.utils.account_lockout.LockoutBackend",
    "tests.test_account_lockout.AcceptSecretBackend",
]


class AcceptSecretBackend:
    """Stand-in for ModelBackend: only the password 'secret' is correct."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if password == "secret":
            return SimpleNamespace(
                pk=1,
                is_active=True,
                get_username=lambda: username,
                backend="x",
            )
        return None


@override_settings(CACHES=LOCMEM, AUTHENTICATION_BACKENDS=BACKENDS)
class AccountLockoutTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        account_lockout.connect()

    def setUp(self):
        cache.clear()

    def _fail(self, username="alice", times=1):
        for _ in range(times):
            authenticate(username=username, password="wrong")

    def test_third_failure_locks_the_account(self):
        self._fail(times=2)
        self.assertFalse(account_lockout.is_locked("alice"))
        self._fail()
        self.assertTrue(account_lockout.is_locked("alice"))

    def test_correct_password_is_rejected_while_locked(self):
        self._fail(times=3)
        self.assertIsNone(authenticate(username="alice", password="secret"))

    def test_lock_is_per_account_not_per_source(self):
        self._fail("alice", times=3)
        self.assertFalse(account_lockout.is_locked("bob"))

    def test_username_match_ignores_case_and_whitespace(self):
        self._fail("Alice", times=3)
        self.assertTrue(account_lockout.is_locked(" alice "))

    def test_unknown_usernames_are_counted_the_same(self):
        self._fail("nobody", times=3)
        self.assertTrue(account_lockout.is_locked("nobody"))

    def test_attempts_while_locked_do_not_extend_the_lock(self):
        self._fail(times=3)
        with override_settings(ACCOUNT_LOCKOUT_SECONDS=1):
            self._fail(times=5)
        self.assertTrue(account_lockout.is_locked("alice"))
        cache.delete(account_lockout._key("locked", "alice"))
        self.assertFalse(account_lockout.is_locked("alice"))
        self.assertIsNone(cache.get(account_lockout._key("count", "alice")))

    def test_success_resets_the_failure_count(self):
        # Call our receiver directly: sending the real signal also runs other
        # apps' receivers (Arches' needs user.backend, Django's needs save()).
        user = SimpleNamespace(get_username=lambda: "alice")

        self._fail(times=2)
        account_lockout._on_logged_in(sender=None, user=user)
        self._fail(times=2)
        self.assertFalse(account_lockout.is_locked("alice"))

    @override_settings(ACCOUNT_LOCKOUT_ENABLED=False)
    def test_can_be_disabled(self):
        self._fail(times=10)
        self.assertFalse(account_lockout.is_locked("alice"))
        self.assertIsNotNone(authenticate(username="alice", password="secret"))
