"""Tests for the export_prebuild management command."""

import contextlib
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from catalina.utils import public_export as pe


def _pipeline(**overrides):
    values = {
        "result": "/out",
        "diagnostics": {},
        "export_ids": ["1", "2"],
        "messages": [("info", "hello"), ("warning", "careful"), ("error", "bad")],
    }
    values.update(overrides)
    return values


@contextlib.contextmanager
def _patched(pipeline=None, user=(None, []), resolve_error=None, upload_error=None):
    with (
        mock.patch.object(
            pe, "resolve_export_user", return_value=user, side_effect=resolve_error
        ) as resolve,
        mock.patch.object(
            pe, "run_export_pipeline", return_value=pipeline or _pipeline()
        ) as run,
        mock.patch.object(pe, "package_export", return_value="/tmp/x.tar") as package,
        mock.patch.object(
            pe, "upload_artifact", return_value="s3://b/k", side_effect=upload_error
        ) as upload,
    ):
        yield SimpleNamespace(resolve=resolve, run=run, package=package, upload=upload)


def _call(*args):
    out, err = StringIO(), StringIO()
    call_command("export_prebuild", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


class ExportPrebuildCommandTests(SimpleTestCase):
    def test_no_push_packages_but_does_not_upload(self):
        with _patched() as mocks:
            out, err = _call(
                "--no-push", "--output-dir", "/out", "--s3-key", "prebuild.tar"
            )
        mocks.run.assert_called_once_with(
            output_dir="/out", indent=2, user=None, states=["Active"]
        )
        mocks.package.assert_called_once_with("/out", archive_name="prebuild.tar")
        mocks.upload.assert_not_called()
        self.assertIn("Exported 2 resources to /out/", out)
        self.assertIn("Archive: /tmp/x.tar", out)
        # Messages are routed by level.
        self.assertIn("hello", out)
        self.assertIn("careful", err)
        self.assertIn("bad", err)

    def test_push_uploads_to_the_given_bucket_and_key(self):
        with _patched() as mocks:
            out, _ = _call("--s3-bucket", "b", "--s3-key", "k")
        mocks.package.assert_called_once_with("/out", archive_name="k")
        mocks.upload.assert_called_once_with("/tmp/x.tar", bucket="b", key="k")
        self.assertIn("Uploaded: s3://b/k", out)

    def test_state_options_are_forwarded(self):
        with _patched() as mocks:
            _call("--no-push", "--states", "Active", "Draft", "--indent", "0")
        mocks.run.assert_called_once_with(
            output_dir="public_export",
            indent=None,
            user=None,
            states=["Active", "Draft"],
        )

        with _patched() as mocks:
            _call("--no-push", "--all-states")
        self.assertIsNone(mocks.run.call_args.kwargs["states"])

    def test_resolved_user_is_passed_to_the_export(self):
        user = object()
        with _patched(user=(user, [("info", "using user")])) as mocks:
            out, _ = _call("--no-push", "--as-user", "svc", "--group", "G")
        mocks.resolve.assert_called_once_with("svc", expected_group="G")
        self.assertIs(mocks.run.call_args.kwargs["user"], user)
        self.assertIn("using user", out)

    def test_invalid_export_user_is_a_command_error(self):
        with _patched(resolve_error=ValueError("superuser")):
            with self.assertRaisesMessage(CommandError, "superuser"):
                _call("--no-push", "--as-user", "root")

    def test_empty_export_is_a_command_error(self):
        with _patched(pipeline=_pipeline(result=None)) as mocks:
            with self.assertRaises(CommandError):
                _call("--no-push")
        mocks.package.assert_not_called()

    def test_upload_misconfiguration_is_a_command_error(self):
        with _patched(upload_error=RuntimeError("not configured")):
            with self.assertRaisesMessage(CommandError, "not configured"):
                _call("--s3-bucket", "b", "--s3-key", "k")
