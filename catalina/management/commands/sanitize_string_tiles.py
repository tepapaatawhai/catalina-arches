"""Sanitise string values already stored in tiles (pentest finding WA05).

The save-time patch (catalina.utils.string_sanitize_patch) only covers new
writes. Run this once per environment to clean existing data. Tiles are saved
through the ORM so the search index is updated; use --dry-run first.
"""

from arches.app.models.models import Node, TileModel
from arches.app.models.tile import Tile
from django.core.management.base import BaseCommand

from catalina.utils.string_sanitize_patch import is_rich_text_node, sanitize_node_value


class Command(BaseCommand):
    help = "Strip scripts and unsafe HTML from stored string node values."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, dry_run=False, **options):
        string_nodes = [
            str(nodeid)
            for nodeid in Node.objects.filter(
                datatype="string", graph__isresource=True
            ).values_list("nodeid", flat=True)
        ]
        changed = 0
        for tile_model in TileModel.objects.iterator():
            before = {}
            after = {}
            for nodeid in string_nodes:
                value = (tile_model.data or {}).get(nodeid)
                if not isinstance(value, dict):
                    continue
                import copy

                before[nodeid] = copy.deepcopy(value)
                after[nodeid] = sanitize_node_value(value, is_rich_text_node(nodeid))
            if before == after:
                continue
            changed += 1
            self.stdout.write(f"tile {tile_model.tileid}: sanitised")
            if not dry_run:
                Tile.objects.get(pk=tile_model.pk).save()
        self.stdout.write(
            self.style.SUCCESS(
                f"{changed} tile(s) {'would change' if dry_run else 'updated'}"
            )
        )
