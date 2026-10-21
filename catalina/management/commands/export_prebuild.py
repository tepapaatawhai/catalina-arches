import os

from django.core.management.base import BaseCommand, CommandError

DEFAULT_KEY = "prebuild.tar"


class Command(BaseCommand):
    help = (
        "Export all Active resources (plus their related resources and the "
        "resource model structure) as a starches prebuild package, tar it and "
        "upload it to S3"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-o",
            "--output-dir",
            default="public_export",
            help="Directory to write the package to (default: public_export)",
        )
        parser.add_argument(
            "--states",
            nargs="+",
            default=["Active"],
            help="Lifecycle states to export (default: Active)",
        )
        parser.add_argument(
            "--all-states",
            action="store_true",
            help="Export resources in every lifecycle state, ignoring --states",
        )
        parser.add_argument(
            "--as-user",
            default=None,
            help="Apply this user's nodegroup read permissions. Defaults to the "
            "'anonymous' user (public-visitor view).",
        )
        parser.add_argument(
            "--group",
            default="Public Export",
            help="Group --as-user is expected to belong to (guard check only)",
        )
        parser.add_argument(
            "--indent",
            type=int,
            default=2,
            help="JSON indentation (default: 2, use 0 for compact)",
        )
        parser.add_argument(
            "--no-push",
            action="store_true",
            help="Write the package and archive but skip the S3 upload",
        )
        parser.add_argument(
            "--s3-bucket",
            default=os.environ.get("PREBUILD_S3_BUCKET"),
            help="S3 bucket to upload to (default: $PREBUILD_S3_BUCKET)",
        )
        parser.add_argument(
            "--s3-key",
            default=os.environ.get("PREBUILD_S3_KEY", DEFAULT_KEY),
            help="S3 object key for the archive (default: $PREBUILD_S3_KEY, "
            f"else '{DEFAULT_KEY}').",
        )

    def handle(self, *args, **options):
        from catalina.utils.public_export import (
            package_export,
            resolve_export_user,
            run_export_pipeline,
            upload_artifact,
        )

        try:
            user, user_messages = resolve_export_user(
                options["as_user"], expected_group=options["group"]
            )
        except ValueError as e:
            raise CommandError(str(e))

        pipeline = run_export_pipeline(
            output_dir=options["output_dir"],
            indent=options["indent"] or None,
            user=user,
            states=None if options["all_states"] else options["states"],
        )

        for level, text in user_messages + pipeline["messages"]:
            if level == "error":
                self.stderr.write(self.style.ERROR(text))
            elif level == "warning":
                self.stderr.write(self.style.WARNING(text))
            else:
                self.stdout.write(text)

        if not pipeline["result"]:
            raise CommandError("Export produced no output")

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(pipeline['export_ids'])} resources to "
                f"{pipeline['result']}/"
            )
        )

        archive = package_export(pipeline["result"], archive_name=options["s3_key"])
        self.stdout.write(f"Archive: {archive}")

        if options["no_push"]:
            return

        try:
            url = upload_artifact(
                archive, bucket=options["s3_bucket"], key=options["s3_key"]
            )
        except RuntimeError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Uploaded: {url}"))
