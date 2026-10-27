from django.core.management.base import BaseCommand, CommandError


def diff_graphs(initial, updated):
    """Return (removed nodegroup ids, removed node ids, added node ids)."""
    old_ng = {n["nodegroupid"] for n in initial["nodegroups"]}
    new_ng = {n["nodegroupid"] for n in updated["nodegroups"]}
    old_nodes = {n["nodeid"] for n in initial["nodes"]}
    new_nodes = {n["nodeid"] for n in updated["nodes"]}
    return old_ng - new_ng, old_nodes - new_nodes, new_nodes - old_nodes


class Command(BaseCommand):
    help = (
        "Find resource instances left on an older graph publication (which the "
        "editor refuses to open) and move them to the graph's current publication, "
        "using the same task as 'update resource instance data' on publish. "
        "Dry run unless --apply is given. Back up the database before --apply: "
        "tiles of removed nodegroups are deleted and data of removed nodes is dropped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Migrate the instances (default: report only)",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit with an error if any instance is on a stale publication",
        )
        parser.add_argument(
            "--graph",
            default=None,
            help="Only graphs whose name contains this text (case-insensitive)",
        )
        parser.add_argument(
            "--graph-id",
            default=None,
            help="Only the graph with this id (exact, unlike --graph)",
        )
        parser.add_argument(
            "--exclude",
            nargs="+",
            default=[],
            help="Exact graph names to skip",
        )
        parser.add_argument(
            "--as-user",
            default="admin",
            help="User to notify on completion (default: admin)",
        )

    def handle(self, *args, **options):
        from django.conf import settings
        from django.contrib.auth.models import User
        from django.db.models import Count

        from arches.app import tasks
        from arches.app.models import models

        apply = options["apply"]
        graphs = models.GraphModel.objects.filter(
            isresource=True, source_identifier__isnull=True, publication__isnull=False
        ).order_by("name")
        if options["graph"]:
            graphs = graphs.filter(name__icontains=options["graph"])
        if options["graph_id"]:
            graphs = graphs.filter(pk=options["graph_id"])
        if options["exclude"]:
            graphs = graphs.exclude(name__in=options["exclude"])

        user = None
        if apply:
            try:
                user = User.objects.get(username=options["as_user"])
            except User.DoesNotExist:
                raise CommandError(f"No such user: {options['as_user']}")

        def serialized(publication_id):
            return models.PublishedGraph.objects.get(
                publication_id=publication_id, language=settings.LANGUAGE_CODE
            ).serialized_graph

        total = 0
        for graph in graphs:
            current_pub = graph.publication_id
            stale = (
                models.ResourceInstance.objects.filter(graph=graph)
                .exclude(graph_publication_id=current_pub)
                .values("graph_publication_id")
                .annotate(n=Count("pk"))
            )
            for row in stale:
                old_pub, count = row["graph_publication_id"], row["n"]
                total += count
                if old_pub is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"SKIP {graph.name}: {count} instances with no publication"
                        )
                    )
                    continue

                initial, updated = serialized(old_pub), serialized(current_pub)
                removed_ng, removed_nodes, added_nodes = diff_graphs(initial, updated)
                orphan_tiles = models.TileModel.objects.filter(
                    nodegroup_id__in=removed_ng,
                    resourceinstance__graph_publication_id=old_pub,
                ).count()
                self.stdout.write(
                    f"{graph.name}: {count} instances on {old_pub} -> {current_pub} | "
                    f"nodegroups removed={len(removed_ng)} (tiles to delete={orphan_tiles}), "
                    f"nodes removed={len(removed_nodes)}, nodes added={len(added_nodes)}"
                )

                if apply:
                    # a celery task object called directly runs synchronously
                    tasks.update_resource_instance_data_based_on_graph_diff(
                        initial, updated, user.pk
                    )
                    # the task logs its own failures, so verify rather than assume
                    left = models.ResourceInstance.objects.filter(
                        graph_publication_id=old_pub
                    ).count()
                    style = self.style.SUCCESS if left == 0 else self.style.ERROR
                    self.stdout.write(
                        style(f"  instances still on old publication: {left}")
                    )

        if not total:
            self.stdout.write("No stale resource instances.")
        elif not apply:
            self.stdout.write("Dry run only. Pass --apply to migrate.")
        if options["check"] and total and not apply:
            raise CommandError(f"{total} resource instances are on a stale publication")
