"""Point resource-instance relationship ids at controlled-list item values.

Resource-instance nodes store ``relationshipConcept`` and
``inverseRelationshipConcept`` ids in their config. For the Person graph (and the
Group graph's ``name_source``) those are legacy RDM value ids that no longer
exist: the relationship labels now live in controlled lists, whose item values
have new ids. Saving a relationship picked through the editor therefore failed
when Arches tried to resolve the label.

This rewrites the old ids to the item values with the same prefLabel, in the same
list the node declares as ``relationshipCollection``. The label is looked up at
run time because item value ids are generated on import and differ per
environment. Tiles need no change: existing ones hold CIDOC property URIs.

Both copies of each config are updated: ``nodes.config`` and the nodes inside
``published_graphs.serialized_graph`` (what the editor actually loads).

Safe to re-run: configs already pointing at list items are left alone. If a list
or label is not loaded yet, that id is skipped with a warning and the migration
can be re-applied after the lists exist. Originals are kept in ``_bak_relconcept_*``
tables, and the reverse restores them.
"""

import json
import logging

from django.db import migrations

logger = logging.getLogger(__name__)

PERSON_LIST = "cb3e0447-a6f4-4137-b376-99c3c32bd4c6"
GROUP_LIST = "54414cde-b8e6-4ab7-8b9e-cd3694f178d8"

# list id -> {legacy value id: prefLabel of the controlled-list item}
LEGACY_IDS = {
    PERSON_LIST: {
        # birth_during
        "61730926-a05d-440b-a9fb-554850e5af69": "period of birth event",
        "bcc0dc37-c289-4dc7-a96f-5c5e2eceaf9e": "period of birth of",
        # death_during
        "f4e2242d-5258-4da5-b765-4fd2fe92bb79": "period of death event",
        "d0724013-776a-4add-b464-6dbc2c0fd714": "period of death of",
        # profession_activity_during
        "5ff87be8-b7cb-4742-8431-f37e9b4e1de9": "period of professional activity",
        "97c2e045-2a12-4d98-b5b9-34b7418cf2a0": "period of professional activity of",
        # birth_location
        "1c531c63-0a76-4452-bb5d-8eaaff20c231": "location of birth event",
        "fbaabe34-d488-4518-ae3e-82f840caebc9": "location of birth of",
        # death_location
        "42b256a8-0ea5-436d-8bcd-98228aa4348d": "location of death event",
        "aae49e1e-89c9-401f-9ca6-77c8f7efbc2d": "location of death of",
        # profession_activity_location
        "da364102-fc71-4f22-81c4-8deab03c00ab": "location of professional activity",
        "bcbe364d-083e-42c9-aa56-bf819600b6f2": "location of professional activity of",
        # profession_activity_used_object
        "4d555e82-f710-4ede-b94e-98b1a2f3a4f1": "physical object used in professional activity",
        "f6d7fed5-5fd5-4544-b67c-cef484ebbfd5": "used in professional activity of",
        # profession_activity_influence (same pair on every target graph)
        "d751902f-9a9d-4cc4-bf7b-7dff8a67d78d": "influence on professional activity",
        "bd6c5303-349b-4333-a317-4bb1df11b84d": "influence on professional activity of",
        # birth_source
        "2191cba6-6c85-4ba3-8738-952d5ac228b2": "source reference work for birth event",
        "bb2ba390-d9b6-49d4-b529-24087a23e095": "source reference for birth of",
        # death_source
        "3ac16cef-6327-4838-b657-1a32ff7308ee": "source reference work for death event",
        "43a2f393-bec8-4c91-9952-95f1316b65d6": "source reference for death of",
        # name_source
        "36e577b4-febe-4029-8cd7-34829405fb57": "source reference work for name",
        "d9bf1253-2246-4006-a540-b1ac70481d78": "source reference for name of",
        # identifier_source
        "b5adee9e-a5f5-414d-a9a1-48a122baa9df": "source reference work for identifier",
        "e9a643a2-2b21-4e0b-aba7-2d53933e26a2": "source reference for identifier of",
        # profession_activity_source
        "54f89853-70f1-46ba-af5b-e758ec17bdc0": "source reference work for professional activity",
        "b0428dee-be4b-46b1-b795-5757c0da99f7": "source reference for professional activity of",
    },
    GROUP_LIST: {
        # Group name_source reuses Person's legacy ids but another list.
        "36e577b4-febe-4029-8cd7-34829405fb57": "source reference work for name",
        "d9bf1253-2246-4006-a540-b1ac70481d78": "source reference for name of",
    },
}

KEYS = ("relationshipConcept", "inverseRelationshipConcept")

BACKUP = """
CREATE TABLE IF NOT EXISTS _bak_relconcept_nodes (nodeid uuid PRIMARY KEY, config jsonb);
CREATE TABLE IF NOT EXISTS _bak_relconcept_published (id bigint PRIMARY KEY, serialized_graph jsonb);
"""


def _load_new_ids(cursor):
    """{list id: {prefLabel: item value id}} for the lists we remap."""
    new_ids = {}
    for list_id in LEGACY_IDS:
        cursor.execute(
            """
            SELECT liv.value, liv.id::text
            FROM arches_controlled_lists_listitemvalue liv
            JOIN arches_controlled_lists_listitem li ON li.id = liv.list_item_id
            WHERE li.list_id = %s AND liv.valuetype_id = 'prefLabel'
            ORDER BY liv.value, liv.id
            """,
            [list_id],
        )
        labels = {}
        for label, value_id in cursor.fetchall():
            labels.setdefault(label, []).append(value_id)
        new_ids[list_id] = labels
    return new_ids


def _remap_config(config, mapping):
    """Rewrite legacy ids in one node config. Returns (changed, config)."""
    if not isinstance(config, dict) or not isinstance(config.get("graphs"), list):
        return False, config
    changed = False
    for graph in config["graphs"]:
        if not isinstance(graph, dict):
            continue
        replacements = mapping.get(graph.get("relationshipCollection"))
        if not replacements:
            continue
        for key in KEYS:
            if graph.get(key) in replacements:
                graph[key] = replacements[graph[key]]
                changed = True
    return changed, config


def _build_mapping(new_ids):
    """{list id: {legacy id: new item value id}}, skipping anything unresolved."""
    mapping = {}
    for list_id, legacy in LEGACY_IDS.items():
        resolved = {}
        for old_id, label in legacy.items():
            candidates = new_ids.get(list_id, {}).get(label, [])
            if len(candidates) == 1:
                resolved[old_id] = candidates[0]
            else:
                logger.warning(
                    "Relationship label %r not resolved in list %s (%d matches); "
                    "id %s left unchanged.",
                    label,
                    list_id,
                    len(candidates),
                    old_id,
                )
        mapping[list_id] = resolved
    return mapping


def _forward(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(BACKUP)
        mapping = _build_mapping(_load_new_ids(cursor))
        if not any(mapping.values()):
            logger.warning(
                "No controlled-list relationship labels found; nothing remapped."
            )
            return

        updated_nodes = 0
        cursor.execute(
            "SELECT nodeid, config FROM nodes WHERE config::text LIKE '%%relationshipConcept%%'"
        )
        for nodeid, config in cursor.fetchall():
            if isinstance(config, str):
                config = json.loads(config)
            original = json.loads(json.dumps(config))
            changed, config = _remap_config(config, mapping)
            if not changed:
                continue
            cursor.execute(
                "INSERT INTO _bak_relconcept_nodes (nodeid, config) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (nodeid) DO NOTHING",
                [nodeid, json.dumps(original)],
            )
            cursor.execute(
                "UPDATE nodes SET config = %s::jsonb WHERE nodeid = %s",
                [json.dumps(config), nodeid],
            )
            updated_nodes += 1

        updated_published = 0
        cursor.execute(
            "SELECT id, serialized_graph FROM published_graphs "
            "WHERE serialized_graph::text LIKE '%%relationshipConcept%%'"
        )
        for row_id, serialized in cursor.fetchall():
            if isinstance(serialized, str):
                serialized = json.loads(serialized)
            original = json.loads(json.dumps(serialized))
            changed = False
            for node in serialized.get("nodes", []):
                node_changed, _ = _remap_config(node.get("config"), mapping)
                changed = changed or node_changed
            if not changed:
                continue
            cursor.execute(
                "INSERT INTO _bak_relconcept_published (id, serialized_graph) "
                "VALUES (%s, %s::jsonb) ON CONFLICT (id) DO NOTHING",
                [row_id, json.dumps(original)],
            )
            cursor.execute(
                "UPDATE published_graphs SET serialized_graph = %s::jsonb WHERE id = %s",
                [json.dumps(serialized), row_id],
            )
            updated_published += 1

    logger.info(
        "Remapped relationship ids on %d node(s) and %d published graph row(s).",
        updated_nodes,
        updated_published,
    )


def _reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('_bak_relconcept_nodes'), to_regclass('_bak_relconcept_published')"
        )
        nodes_bak, published_bak = cursor.fetchone()
        if nodes_bak:
            cursor.execute(
                "UPDATE nodes n SET config = b.config FROM _bak_relconcept_nodes b "
                "WHERE n.nodeid = b.nodeid"
            )
            cursor.execute("DROP TABLE _bak_relconcept_nodes")
        if published_bak:
            cursor.execute(
                "UPDATE published_graphs p SET serialized_graph = b.serialized_graph "
                "FROM _bak_relconcept_published b WHERE p.id = b.id"
            )
            cursor.execute("DROP TABLE _bak_relconcept_published")


class Migration(migrations.Migration):

    dependencies = [
        ("catalina", "0005_dedupe_same_slot_controlled_list_items"),
        ("arches_controlled_lists", "0009_reconfigure_migration_for_polyhierarchies"),
    ]

    operations = [
        migrations.RunPython(_forward, _reverse),
    ]
