from django.core.management.base import BaseCommand

from catalina.overlays.apply import apply_overlays


class Command(BaseCommand):
    help = (
        "Write the overlay registry (catalina/overlays/registry.py) to the "
        "map layers and sources. Runs after every migrate; use this after an "
        "env change without a deploy."
    )

    def handle(self, *args, **options):
        applied, removed, failed = apply_overlays()
        self.stdout.write(f"Applied: {', '.join(applied) or 'none'}")
        self.stdout.write(f"Removed: {', '.join(removed) or 'none'}")
        if failed:
            self.stderr.write(f"Failed (see log): {', '.join(failed)}")
