"""Repairs that run after a graph is published.

Publishing replaces the graph's nodes (Graph.promote_draft_graph_to_active_graph).
geojson_geometries and resource_x_resource both reference nodes with ON DELETE
CASCADE, so the rows for the graph's nodes disappear while the tiles they are
derived from survive. Nothing recreates them, so the map loses its markers and
Related Resources lose their relationships. Resource instances can also be left on
the previous publication, which the editor then refuses to open.

run_post_publish() puts that right for one graph. The steps run in this order
because each reads what the one before it writes:

1. migrate stale instances (rewrites tiles; only when AUTO_MIGRATE_STALE_INSTANCES)
2. rebuild geojson_geometries from the tiles
3. add the missing resource_x_resource rows from the tiles
4. clear the cached map tiles, which were built while the rows were missing

Every step is idempotent and one failing does not stop the others.

It is triggered twice per publish. schedule_after_publish() queues it once the
publish transaction commits. When the editor ticks "update resource instance
data", Arches runs that migration as its own Celery job, which can still be going
at that point, so queue_after_data_update() queues it again when that job ends.
"""

import logging
from io import StringIO

from django.conf import settings
from django.core.cache import caches
from django.core.management import call_command
from django.db import connection, transaction

logger = logging.getLogger(__name__)

GEOJSON_DATATYPE = "geojson-feature-collection"
MVT_CACHE_PATTERN = "*mvt_*"
DATA_UPDATE_TASK = "arches.app.tasks.update_resource_instance_data_based_on_graph_diff"
# Gives the data update job that Arches queues beside the publish time to be seen
# by the worker, so that migrate_stale_instances can tell it is running.
MIGRATE_DELAY_SECONDS = 60


def rebuild_geometries(graph_id):
    """Recreate the geojson_geometries rows for one graph's geometry nodes.

    Uses Arches' per-tile function, as a tile save does, rather than
    refresh_geojson_geometries(). That one TRUNCATEs the table, and the exclusive
    lock it needs waits behind any open transaction while every map tile request
    waits behind it.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FROM (
                SELECT refresh_tile_geojson_geometries(t.tileid)
                FROM tiles t
                WHERE t.nodegroupid IN (
                    SELECT n.nodegroupid FROM nodes n
                    WHERE n.graphid = %s AND n.datatype = %s
                )
            ) refreshed
            """,
            [graph_id, GEOJSON_DATATYPE],
        )
        return cursor.fetchone()[0]


# One row per relationship held in a tile of this graph that has no row yet. This
# is the INSERT Arches runs from the datatype's post_tile_save, applied to tiles
# that already exist: Arches' own __arches_create_resource_x_resource_relationships
# does nothing for tiles without a resourceXresourceId in their data, which tiles
# from a bulk load do not have. A target that no longer exists is skipped, since
# the relationship graph cannot draw it. It only ever adds rows.
REBUILD_RELATIONSHIPS_SQL = """
WITH missing AS (
    SELECT t.tileid,
           t.resourceinstanceid AS from_id,
           n.nodeid,
           n.config,
           v.rel,
           (v.rel ->> 'resourceId')::uuid AS to_id
    FROM tiles t
    JOIN resource_instances fi
      ON fi.resourceinstanceid = t.resourceinstanceid AND fi.graphid = %(graph)s
    JOIN nodes n
      ON n.nodegroupid = t.nodegroupid
     AND n.datatype IN ('resource-instance', 'resource-instance-list')
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(t.tiledata -> n.nodeid::text) = 'array'
             THEN t.tiledata -> n.nodeid::text ELSE '[]'::jsonb END
    ) AS v(rel)
    WHERE NOT EXISTS (
        SELECT 1 FROM resource_x_resource r
        WHERE r.tileid = t.tileid
          AND r.nodeid = n.nodeid
          AND r.resourceinstanceidto = (v.rel ->> 'resourceId')::uuid
    )
)
INSERT INTO resource_x_resource (
    resourcexid, notes, relationshiptype, inverserelationshiptype,
    resourceinstanceidfrom, resourceinstanceidto,
    resourceinstancefrom_graphid, resourceinstanceto_graphid,
    tileid, nodeid, created, modified
)
SELECT uuid_generate_v4(),
       '',
       CASE m.rel ->> 'ontologyProperty'
         WHEN '' THEN (
           SELECT g ->> 'ontologyProperty'
           FROM jsonb_array_elements(m.config -> 'graphs') g
           WHERE g ->> 'graphid' = ti.graphid::text)
         ELSE m.rel ->> 'ontologyProperty'
       END,
       CASE m.rel ->> 'inverseOntologyProperty'
         WHEN '' THEN (
           SELECT g ->> 'inverseOntologyProperty'
           FROM jsonb_array_elements(m.config -> 'graphs') g
           WHERE g ->> 'graphid' = ti.graphid::text)
         ELSE m.rel ->> 'inverseOntologyProperty'
       END,
       m.from_id, m.to_id, fi.graphid, ti.graphid,
       m.tileid, m.nodeid, now(), now()
FROM missing m
JOIN resource_instances fi ON fi.resourceinstanceid = m.from_id
JOIN resource_instances ti ON ti.resourceinstanceid = m.to_id
"""


def rebuild_relationships(graph_id):
    """Add the resource_x_resource rows missing for one graph. Returns the count."""
    with connection.cursor() as cursor:
        cursor.execute(REBUILD_RELATIONSHIPS_SQL, {"graph": graph_id})
        return cursor.rowcount


def clear_tile_cache():
    """Delete the cached map tiles, which the tile view keeps for TILE_CACHE_TIMEOUT.

    Returns the number of keys deleted, or None if the cache is not Redis (the
    tiles then refresh when they expire).
    """
    try:
        client = caches["default"]._cache.get_client(write=True)
    except AttributeError:
        logger.warning(
            "Tile cache is not Redis: cached tiles refresh within %s seconds",
            settings.TILE_CACHE_TIMEOUT,
        )
        return None

    deleted = 0
    batch = []
    for key in client.scan_iter(match=MVT_CACHE_PATTERN, count=500):
        batch.append(key)
        if len(batch) >= 500:
            deleted += client.delete(*batch)
            batch = []
    if batch:
        deleted += client.delete(*batch)
    return deleted


def data_update_running():
    """True if a worker is running or holding Arches' resource instance data update.

    False when no worker answers, so a missing broker cannot block the repairs.
    """
    from catalina.celery import app

    try:
        inspector = app.control.inspect(timeout=1)
        found = {}
        found.update(inspector.active() or {})
        for worker, tasks in (inspector.reserved() or {}).items():
            found[worker] = found.get(worker, []) + tasks
    except Exception:
        logger.exception("Could not ask the workers what they are running")
        return False
    return any(
        task.get("name") == DATA_UPDATE_TASK
        for tasks in found.values()
        for task in tasks
    )


def migrate_stale_instances(graph_id, user_id=None):
    """Move this graph's instances onto its current publication.

    Skipped while Arches' own data update is running: both would rewrite the same
    tiles, and queue_after_data_update() repairs the graph when that job ends.
    """
    if data_update_running():
        logger.info("Data update running for graph %s; leaving it to finish", graph_id)
        return None

    args = ["--apply", "--graph-id", str(graph_id)]
    if user_id:
        from django.contrib.auth.models import User

        username = (
            User.objects.filter(pk=user_id).values_list("username", flat=True).first()
        )
        if username:
            args += ["--as-user", username]

    out = StringIO()
    call_command("migrate_stale_instances", *args, stdout=out)
    return out.getvalue().strip()


def run_post_publish(graph_id, user_id=None, migrate=None):
    """Run the repairs for one graph. Returns {step: result or exception}.

    migrate defaults to settings.AUTO_MIGRATE_STALE_INSTANCES.
    """
    if migrate is None:
        migrate = settings.AUTO_MIGRATE_STALE_INSTANCES

    steps = []
    if migrate:
        steps.append(
            (
                "migrate_stale_instances",
                lambda: migrate_stale_instances(graph_id, user_id),
            )
        )
    steps += [
        ("rebuild_geometries", lambda: rebuild_geometries(graph_id)),
        ("rebuild_relationships", lambda: rebuild_relationships(graph_id)),
        ("clear_tile_cache", clear_tile_cache),
    ]

    results = {}
    for name, step in steps:
        try:
            results[name] = step()
            logger.info(
                "Post-publish %s for graph %s: %s", name, graph_id, results[name]
            )
        except Exception as exc:
            results[name] = exc
            logger.exception("Post-publish %s failed for graph %s", name, graph_id)
    return results


def _queue(graph_id, user_id, migrate, countdown=0):
    from catalina.tasks import after_graph_publish

    try:
        after_graph_publish.apply_async(
            (str(graph_id), user_id, migrate), countdown=countdown
        )
    except Exception:
        logger.exception(
            "Could not queue the post-publish repairs for graph %s; "
            "run them by hand",
            graph_id,
        )


def schedule_after_publish(sender, instance, created=False, raw=False, **kwargs):
    """post_save receiver for GraphXPublishedGraph: queue the repairs on commit."""
    if not created or raw:
        return
    graph_id, user_id = instance.graph_id, instance.user_id
    transaction.on_commit(
        lambda: _queue(
            graph_id,
            user_id,
            migrate=settings.AUTO_MIGRATE_STALE_INSTANCES,
            countdown=MIGRATE_DELAY_SECONDS,
        )
    )


def queue_after_data_update(sender=None, args=None, **kwargs):
    """Celery task_postrun receiver: repair the graph when Arches' data update ends.

    Does not migrate: Arches has just done that.
    """
    if getattr(sender, "name", None) != DATA_UPDATE_TASK:
        return
    try:
        graph_id = args[1]["graphid"]
    except (TypeError, IndexError, KeyError):
        logger.warning("Could not read the graph id from the data update arguments")
        return
    _queue(graph_id, user_id=None, migrate=False)
