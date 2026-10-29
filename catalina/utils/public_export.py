import ast
import json
import logging
import os
import re

from django.db.models import Q

from arches.app.models.models import Node, ResourceXResource, TileModel
from arches.app.utils.betterJSONSerializer import JSONSerializer
from arches.app.utils.data_management.resource_graphs.exporter import (
    get_graphs_for_export,
)
from arches.app.utils.data_management.resources.formats.archesfile import (
    ArchesFileWriter,
)
from arches_controlled_lists.models import List, ListItem
from arches_controlled_lists.utils.skos import SKOSWriter

logger = logging.getLogger(__name__)

HERITAGE_ITEM_GRAPH_ID = "076f9381-7b00-11e9-8d6b-80000b44d1d9"
PERSON_GRAPH_ID = "22477f01-1a44-11e9-b0a9-000d3ab1e588"
PERIOD_GRAPH_ID = "f9045867-8861-11ea-b06f-f875a44e0e11"
SYSTEM_SETTINGS_GRAPH_ID = "ff623370-fa12-11e6-b98b-6c4008b05c4c"
ASSOCIATED_ACTORS_NODEGROUP_ID = "9682621d-0262-11eb-ab33-f875a44e0e11"
ACTOR_NODE_ID = "96826221-0262-11eb-8bc5-f875a44e0e11"

# Graphs whose resources are always exported, whatever their lifecycle state.
# They are written to their own reference files rather than as primary resources.
ALWAYS_VISIBLE_GRAPH_IDS = {
    PERIOD_GRAPH_ID,
}


def get_exportable_resource_ids(states=None):
    """Return IDs of resources to export as primary resources.

    ``states`` is an optional list of lifecycle state names (e.g. ["Active"]).
    When omitted every resource is included, whatever its state.

    Graphs in ALWAYS_VISIBLE_GRAPH_IDS are excluded (they are exported in full to
    their own reference files) and so are System Settings resources.
    """
    from arches.app.models.models import ResourceInstance

    qs = ResourceInstance.objects.exclude(
        graph_id__in=ALWAYS_VISIBLE_GRAPH_IDS | {SYSTEM_SETTINGS_GRAPH_ID}
    )
    if states:
        qs = qs.filter(resource_instance_lifecycle_state__name__in=states)
    return list(qs.values_list("resourceinstanceid", flat=True))


def get_exportable_graph_ids():
    """Return IDs of all resource models and branches to export (structure).

    The System Settings resource model is excluded. Branches (isresource=False)
    are included so the package carries every graph a model is built from.
    """
    from arches.app.models.models import GraphModel

    return set(
        str(gid)
        for gid in GraphModel.objects.filter(
            source_identifier__isnull=True,
        )
        .exclude(graphid=SYSTEM_SETTINGS_GRAPH_ID)
        .values_list("graphid", flat=True)
    )


def get_user_filtered_nodegroups(resource_ids, user):
    """Nodegroups present in the given resources' tiles that ``user`` cannot
    read — i.e. those the export writer dropped due to nodegroup permissions.

    The writer (Writer.get_tiles) keeps only tiles whose nodegroup is in
    ``get_nodegroups_by_perm(user, "models.read_nodegroup")``. This reports the
    complement for the resources being exported, so the effect of an --as-user
    whitelist is visible at a glance.

    Returns a list of {"nodegroup_id", "alias", "graph_name"} dicts, sorted by
    graph then alias. Empty when nothing was filtered (or user is None).
    """
    if user is None:
        return []

    from arches.app.utils.permission_backend import get_nodegroups_by_perm

    permitted = {
        str(ng) for ng in get_nodegroups_by_perm(user, "models.read_nodegroup")
    }
    present = {
        str(ng)
        for ng in TileModel.objects.filter(resourceinstance_id__in=resource_ids)
        .values_list("nodegroup_id", flat=True)
        .distinct()
        if ng is not None
    }
    filtered_ids = present - permitted
    if not filtered_ids:
        return []

    # Label via the grouping node (nodeid == nodegroup_id).
    labels = {
        str(nodegroup_id): {"alias": alias, "graph_name": str(graph_name)}
        for nodegroup_id, alias, graph_name in Node.objects.filter(
            nodeid__in=filtered_ids,
            source_identifier__isnull=True,
        ).values_list("nodegroup_id", "alias", "graph__name")
    }
    return sorted(
        (
            {
                "nodegroup_id": ng_id,
                "alias": labels.get(ng_id, {}).get("alias"),
                "graph_name": labels.get(ng_id, {}).get("graph_name"),
            }
            for ng_id in filtered_ids
        ),
        key=lambda d: (d["graph_name"] or "", d["alias"] or "", d["nodegroup_id"]),
    )


def get_referenced_person_ids(states=None):
    """Return the IDs of Person resources, optionally only those in ``states``.

    Persons are written to their own t_person.json file rather than
    into the main resource file.

    Returns a set of Person resource instance IDs.
    """
    from arches.app.models.models import ResourceInstance

    qs = ResourceInstance.objects.filter(graph_id=PERSON_GRAPH_ID)
    if states:
        qs = qs.filter(resource_instance_lifecycle_state__name__in=states)
    return set(qs.values_list("resourceinstanceid", flat=True))


def filter_ids_by_state(resource_ids, states):
    """Return the subset of ``resource_ids`` (as strings) whose lifecycle state is in ``states``."""
    from arches.app.models.models import ResourceInstance

    return {
        str(rid)
        for rid in ResourceInstance.objects.filter(
            resourceinstanceid__in=resource_ids,
            resource_instance_lifecycle_state__name__in=states,
        ).values_list("resourceinstanceid", flat=True)
    }


def get_all_period_ids():
    """Return all Period resource instance IDs."""
    from arches.app.models.models import ResourceInstance

    return set(
        ResourceInstance.objects.filter(
            graph_id=PERIOD_GRAPH_ID,
        ).values_list("resourceinstanceid", flat=True)
    )


def get_outbound_relations(resource_ids, permitted_nodegroups=None):
    """Get tile-backed outbound relations from the given resources.

    Targets are returned whatever their lifecycle state; the caller drops the
    ones that are not being exported.

    Args:
        resource_ids: list of source resource instance IDs
        permitted_nodegroups: optional set of nodegroup UUIDs to filter source tiles

    Returns:
        tuple: (relations list, diagnostics dict, set of related target
                resource IDs, suitable for exporting as full resources)
    """
    filters = {
        "from_resource_id__in": resource_ids,
        "tile__isnull": False,
    }
    if permitted_nodegroups is not None:
        filters["tile__nodegroup_id__in"] = permitted_nodegroups

    candidate_relations = ResourceXResource.objects.filter(**filters).only(
        "resourcexid",
        "from_resource_id",
        "from_resource_graph_id",
        "to_resource_id",
        "to_resource_graph_id",
        "relationshiptype",
        "inverserelationshiptype",
        "node_id",
        "tile_id",
        "notes",
    )

    target_ids = set()
    relations = []
    for rel in candidate_relations.iterator():
        target_ids.add(rel.to_resource_id)
        relations.append(
            {
                "resourcexid": str(rel.resourcexid),
                "from_resource": str(rel.from_resource_id),
                "from_resource_graph": str(rel.from_resource_graph_id),
                "to_resource": str(rel.to_resource_id),
                "to_resource_graph": str(rel.to_resource_graph_id),
                "relationshiptype": rel.relationshiptype,
                "inverserelationshiptype": rel.inverserelationshiptype,
                "nodeid": str(rel.node_id) if rel.node_id else None,
                "tileid": str(rel.tile_id) if rel.tile_id else None,
                "notes": rel.notes or "",
            }
        )

    diagnostics = {
        "candidate_relations": len(relations),
        "target_resources_total": len(target_ids),
    }
    return relations, diagnostics, target_ids


def get_controlled_list_ids_for_graphs(graph_ids):
    """Find all controlled list IDs referenced by reference-type nodes in the given graphs."""
    nodes = Node.objects.filter(
        graph_id__in=graph_ids,
        datatype="reference",
        config__controlledList__isnull=False,
    )
    list_ids = set()
    for node in nodes:
        cl_id = node.config.get("controlledList")
        if cl_id:
            list_ids.add(cl_id)
    return list_ids


def strip_unresolvable_actor_tiles(resource_data, exported_person_ids):
    """Remove associated_actor tiles that reference Persons not in the export.

    As a temporary measure, pending reconciliation of relationships,
    this ensures Heritage Items don't reference Person resources that
    weren't included in the Person export (which is filtered by name
    suffix). Tiles in the Associated Actors nodegroup whose Actor
    resource-instance-list entries all point to non-exported Persons
    are removed entirely.

    Mutates resource_data["tiles"] in place. Returns the count of tiles removed.
    """
    exported_set = {str(pid) for pid in exported_person_ids}
    tiles = resource_data.get("tiles", [])
    kept = []
    removed = 0
    for tile in tiles:
        if str(tile.get("nodegroup_id")) != ASSOCIATED_ACTORS_NODEGROUP_ID:
            kept.append(tile)
            continue

        actor_data = (tile.get("data") or {}).get(ACTOR_NODE_ID, [])
        if not isinstance(actor_data, list):
            actor_data = [actor_data] if actor_data else []

        # Keep tile only if at least one referenced Person is in the export
        has_exported_person = any(
            isinstance(entry, dict) and str(entry.get("resourceId", "")) in exported_set
            for entry in actor_data
        )
        if has_exported_person:
            kept.append(tile)
        else:
            removed += 1

    resource_data["tiles"] = kept
    return removed


def get_file_node_ids(graph_ids=None):
    """Node IDs of file-list datatype nodes (image / document uploads).

    These are the nodes that carry actual file attachments — Heritage Item
    ``images``, Digital Object ``file_content``, etc. Restrict to ``graph_ids``
    when given, otherwise return them across all graphs.
    """
    qs = Node.objects.filter(datatype="file-list", source_identifier__isnull=True)
    if graph_ids is not None:
        qs = qs.filter(graph_id__in=[str(g) for g in graph_ids])
    return {str(nid) for nid in qs.values_list("nodeid", flat=True)}


def extract_file_references(resources, file_node_ids=None):
    """Collect file references from exported resource tiles.

    Scans the already-exported business_data resources for file-list datatype
    nodes and returns the de-duplicated set of files they reference, so a
    downstream job can copy/publish exactly the media that ships with the
    package. Because it reads the exported tiles (not the DB directly), it
    honours the same permission filtering the export applied —
    only files on tiles that actually made it into the package are listed.

    Args:
        resources: list of resource dicts (export["business_data"]["resources"])
        file_node_ids: optional set of file-list nodeids; queried if omitted

    Returns:
        list of {"file_id", "name", "url", "resourceinstanceid", "nodeid"} dicts,
        de-duplicated by file_id (falling back to name), sorted by name.
    """
    if file_node_ids is None:
        file_node_ids = get_file_node_ids()

    seen = set()
    files = []
    for resource_data in resources:
        rid = resource_data.get("resourceinstance", {}).get("resourceinstanceid", "")
        for tile in resource_data.get("tiles", []):
            data = tile.get("data") or {}
            for node_id, value in data.items():
                if node_id not in file_node_ids or not isinstance(value, list):
                    continue
                for entry in value:
                    if not isinstance(entry, dict):
                        continue
                    file_id = entry.get("file_id")
                    name = entry.get("name")
                    key = file_id or name
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    files.append(
                        {
                            "file_id": file_id,
                            "name": name,
                            "url": entry.get("url"),
                            "resourceinstanceid": rid,
                            "nodeid": node_id,
                        }
                    )
    return sorted(files, key=lambda f: (f["name"] or "", f["file_id"] or ""))


def _resolve_i18n_name(name):
    """Extract a plain string from an i18n name (dict or string)."""
    if isinstance(name, dict):
        return name.get("en", next(iter(name.values()), "Unknown"))
    return str(name)


# Matches the slugs starches already serves, e.g. cat-rnzaf-devon-crash-si-0ce1ee
SLUG_PREFIX = "cat-"
SLUG_MAX_LENGTH = 20


def slugify_name(name):
    """Slugify like alizarin's ``slugify``: ASCII only, hyphen separated, cut to 20."""
    name = re.sub(r"[^a-z0-9\s_-]", "", str(name).lower())
    name = re.sub(r"[\s_-]+", "-", name).strip("-")
    return name[:SLUG_MAX_LENGTH].strip("-")


def add_resource_slug(resource_data):
    """Set ``resourceinstance.descriptors.slug`` as the builder would generate it.

    starches-builder takes this slug for the resource's own page and for every
    link to it, so storing it keeps the two in step. Without it, resources only
    preloaded as references have no slug and are shown as plain text.
    """
    ri = resource_data.get("resourceinstance") or {}
    rid = str(ri.get("resourceinstanceid") or "")
    descriptors = ri.get("descriptors")
    if not rid or not isinstance(descriptors, dict):
        return
    lang = "en" if isinstance(descriptors.get("en"), dict) else None
    if lang is None:
        lang = next((k for k, v in descriptors.items() if isinstance(v, dict)), None)
    name = (descriptors.get(lang) or {}).get("name") if lang else None
    name = name or ri.get("name") or ""
    descriptors["slug"] = (
        f"{SLUG_PREFIX}{slugify_name(_resolve_i18n_name(name))}-{rid[:6]}"
    )


def _restore_stringified_i18n(value):
    """Turn str(dict) i18n values (e.g. "{'en': ''}") back into real dicts.

    The graph exporter can emit node, card and graph descriptions as the Python
    repr of their i18n dict. Starches interpolates descriptions into its
    ``::Title{description}::`` markup, so a stringified dict breaks the parser
    and the rest of the asset page renders as raw text. Walks ``value`` in
    place and returns it.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            value[key] = _restore_stringified_i18n(item)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            value[i] = _restore_stringified_i18n(item)
    elif isinstance(value, str) and value.startswith("{'") and value.endswith("}"):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
        if isinstance(parsed, dict) and all(isinstance(k, str) for k in parsed):
            return parsed
    return value


def export_graphs_to_dir(graph_ids, dest_dir, indent=2, resource_files=None):
    """Export graph JSON files and write the graphs.json manifest.

    Resource models go to dest_dir/graphs/resource_models/ and branches to
    dest_dir/graphs/branches/. Only resource models are listed in the manifest,
    each with the business_data files in ``resource_files`` (graph id -> list of
    file names) that hold its resources.

    Returns list of exported graph names.
    """
    models_dir = os.path.join(dest_dir, "graphs", "resource_models")
    branches_dir = os.path.join(dest_dir, "graphs", "branches")
    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(branches_dir, exist_ok=True)

    graphs_data = get_graphs_for_export(graphids=[str(gid) for gid in graph_ids])
    exported = []
    manifest = {}
    for graph in graphs_data.get("graph", []):
        _restore_stringified_i18n(graph)
        graph_id = str(graph.get("graphid", ""))
        graph_name = _resolve_i18n_name(graph.get("name", "Unknown"))
        safe_name = graph_name.replace("/", "_")
        is_model = bool(graph.get("isresource"))
        graphs_dir = models_dir if is_model else branches_dir
        filepath = os.path.join(graphs_dir, f"{safe_name}.json")
        with open(filepath, "wb") as f:
            f.write(
                JSONSerializer()
                .serialize({"graph": [graph]}, indent=indent)
                .encode("utf-8")
            )
        exported.append(graph_name)
        if is_model:
            manifest[graph_id] = {
                "name": graph_name,
                "resources": sorted((resource_files or {}).get(graph_id, [])),
            }

    # Write graphs.json manifest at the prebuild root
    manifest_path = os.path.join(dest_dir, "graphs.json")
    with open(manifest_path, "w") as f:
        json.dump({"models": manifest}, f, indent=indent)

    return exported


PKG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pkg"
)
# Hand-maintained builder config copied verbatim from the package into the export
STATIC_PKG_ENTRIES = (
    "indexTemplates",
    "ontologies",
    "prebuild.json",
    "permissions.json",
)


# Layout the starches build expects at the package root, as in the notebook
# prebuild: empty folders (kept by a .gitkeep) and the root .gitignore.
SCAFFOLD_DIRS = (
    "fgb",
    "business_data/files",
    "business_data/relations",
    "business_data/resource_views",
)
PREBUILD_GITIGNORE = "*\n!.gitignore\n!graphs.json\n!permissions.json\n!prebuild.json\n"


def write_package_scaffold(dest_dir):
    """Write the empty folders and root .gitignore the starches build expects."""
    for rel in SCAFFOLD_DIRS:
        path = os.path.join(dest_dir, rel)
        os.makedirs(path, exist_ok=True)
        if rel != "fgb":
            open(os.path.join(path, ".gitkeep"), "w").close()
    with open(os.path.join(dest_dir, ".gitignore"), "w") as f:
        f.write(PREBUILD_GITIGNORE)


SITE_URL_ENV = "PREBUILD_STARCHES_URL"


def set_media_prefix(prebuild_path, site_url):
    """Point the ``files`` entries of a prebuild.json at ``site_url``'s media.

    The file URLs the builder writes must be absolute for the site that serves
    them, which differs per environment, so the packaged default is overridden.
    """
    with open(prebuild_path) as handle:
        config = json.load(handle)
    for entry in config.get("files", []):
        if match := entry.get("matchUrlPrefix"):
            entry["prefix"] = site_url.rstrip("/") + match
    with open(prebuild_path, "w") as handle:
        json.dump(config, handle, indent=4)
        handle.write("\n")


def copy_static_package_files(dest_dir):
    """Copy builder config (index templates, ontologies, prebuild.json, permissions.json)
    from catalina/pkg into the export, dotfiles like .gitkeep included.

    If $PREBUILD_STARCHES_URL is set, the media prefixes in prebuild.json are
    rewritten to that site (the packaged default is the dev site).

    Returns the list of entries copied; missing entries are logged and skipped.
    """
    import shutil

    copied = []
    for entry in STATIC_PKG_ENTRIES:
        src = os.path.join(PKG_DIR, entry)
        dst = os.path.join(dest_dir, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)
        else:
            logger.warning("Static package entry %s not found at %s", entry, src)
            continue
        copied.append(entry)
    site_url = os.environ.get(SITE_URL_ENV)
    if site_url and "prebuild.json" in copied:
        set_media_prefix(os.path.join(dest_dir, "prebuild.json"), site_url)
    return copied


def export_controlled_lists_to_dir(list_ids, dest_dir):
    """Export controlled lists as SKOS-RDF XML to dest_dir/reference_data/controlled_lists/.

    Returns list of exported list names.
    """
    cl_dir = os.path.join(dest_dir, "reference_data", "controlled_lists")
    os.makedirs(cl_dir, exist_ok=True)

    exported = []
    for list_id in list_ids:
        try:
            controlled_list = List.objects.get(pk=list_id)
        except List.DoesNotExist:
            logger.warning("Controlled list %s not found, skipping", list_id)
            continue

        list_items = ListItem.objects.filter(
            list=controlled_list,
        ).prefetch_related("list_item_values", "parent", "children")

        skos = SKOSWriter()
        skos_data = skos.write_controlled_lists(
            [controlled_list], list_items, format="pretty-xml"
        )

        # Named by list id, as in the notebook prebuild. Names are not unique
        # (or can be empty), so name-based files overwrote one another.
        filepath = os.path.join(cl_dir, f"{controlled_list.pk}.xml")
        if isinstance(skos_data, str):
            skos_data = skos_data.encode("utf-8")
        with open(filepath, "wb") as f:
            f.write(skos_data)
        exported.append(controlled_list.name)

    return exported


EXPORT_BATCH_SIZE = int(os.environ.get("QUARTZ_EXPORT_BATCH_SIZE", 200))


def _write_resources_batched(resource_ids, user=None, indent=None, label="Resources"):
    """Export resources in batches, yielding parsed resource dicts progressively.

    Avoids holding the entire serialized JSON for all resources in memory at
    once. Each batch is serialized, parsed, and its resource dicts yielded
    before the next batch starts. Prints a progress indicator to stderr.
    """
    import sys
    import time

    total = len(resource_ids)
    yielded = 0
    t0 = time.monotonic()

    for i in range(0, total, EXPORT_BATCH_SIZE):
        batch = resource_ids[i : i + EXPORT_BATCH_SIZE]
        end = min(i + EXPORT_BATCH_SIZE, total)

        elapsed = time.monotonic() - t0
        if yielded > 0:
            eta = elapsed / yielded * (total - yielded)
            eta_str = f" ETA {int(eta)}s"
        else:
            eta_str = ""

        sys.stderr.write(
            f"\r  {label}: {end}/{total} " f"({end * 100 // total}%){eta_str}   "
        )
        sys.stderr.flush()

        # Fresh writer per batch: ArchesFileWriter accumulates tiles in
        # self.resourceinstances across calls to write_resources(), so
        # reusing one writer leaks every previous batch's tile data.
        writer = ArchesFileWriter()
        results = writer.write_resources(
            resourceinstanceids=[str(rid) for rid in batch],
            user=user,
            indent=indent,
        )
        del writer
        if not results:
            yielded += len(batch)
            continue
        raw_json = results[0]["outputfile"].getvalue()
        del results
        batch_export = json.loads(raw_json)
        del raw_json
        returned_ids = set()
        for resource_data in batch_export.get("business_data", {}).get("resources", []):
            returned_ids.add(
                str(resource_data.get("resourceinstance", {}).get("resourceinstanceid"))
            )
            add_resource_slug(resource_data)
            yield resource_data
            yielded += 1
        # The writer builds resources from their tiles, so a resource with no
        # readable tile (none, or all in nodegroups ``user`` cannot read) is
        # silently absent from its output. Report those rather than lose them.
        dropped = [str(r) for r in batch if str(r) not in returned_ids]
        if dropped:
            yielded += len(dropped)
            sys.stderr.write(
                f"\n  WARNING {label}: {len(dropped)} resource(s) produced no "
                f"output (no readable tiles), e.g. {', '.join(dropped[:3])}\n"
            )

    elapsed = time.monotonic() - t0
    sys.stderr.write(f"\r  {label}: {total}/{total} (100%) done in {int(elapsed)}s\n")
    sys.stderr.flush()


def _write_reference_resources(
    resource_ids, output_path, user=None, indent=2, label="Resources"
):
    """Export resources to a standalone business_data JSON file.

    Used for reference resource types (Person, Period) that are exported as
    separate files for use as referenceSources in starches-builder.
    """
    resources = []
    for resource_data in _write_resources_batched(
        resource_ids,
        user=user,
        indent=indent,
        label=label,
    ):
        resources.append(resource_data)

    output = {"business_data": {"resources": resources}}
    with open(output_path, "w") as f:
        json.dump(output, f, indent=indent)
    logger.info("Wrote %d %s resources to %s", len(resources), label, output_path)


def business_data_filename(graph_name):
    """File name for a model's business data, e.g. "Digital Object" -> t_digital_object.json.

    The starches build only ETLs business_data/t_*.json, so every file carries
    the t_ prefix.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", graph_name.lower()).strip("_")
    return f"t_{slug}.json"


class _BusinessDataFiles:
    """Streams exported resources into one business_data file per resource model.

    Files are named after the model (e.g. Digital_Object.json) and each carries
    the relations whose source resource belongs to that model. Use as a context
    manager; set ``relations`` before it exits so they are written on close.
    """

    def __init__(self, bd_dir, indent):
        from arches.app.models.models import GraphModel

        self.bd_dir = bd_dir
        self.indent = indent
        self.relations = []
        self.names = {
            str(gid): _resolve_i18n_name(name)
            for gid, name in GraphModel.objects.values_list("graphid", "name")
        }
        self._open = {}  # graph_id -> [file, resource_count]
        self.filenames = {}  # graph_id -> file name

    def __enter__(self):
        return self

    def write(self, graph_id, resource_data):
        graph_id = str(graph_id)
        entry = self._open.get(graph_id)
        if entry is None:
            name = self.names.get(graph_id, graph_id)
            filename = business_data_filename(name)
            fh = open(os.path.join(self.bd_dir, filename), "w")
            fh.write('{"business_data": {"resources": [')
            entry = self._open[graph_id] = [fh, 0]
            self.filenames[graph_id] = filename
        fh = entry[0]
        if entry[1]:
            fh.write(",")
        json.dump(resource_data, fh, indent=self.indent)
        entry[1] += 1

    def __exit__(self, exc_type, exc, tb):
        by_graph = {}
        for rel in self.relations:
            by_graph.setdefault(rel.get("from_resource_graph"), []).append(rel)
        for graph_id, (fh, _count) in self._open.items():
            fh.write('], "relations": ')
            json.dump(by_graph.get(graph_id, []), fh, indent=self.indent)
            fh.write("}}")
            fh.close()
        return False


def export_resources(
    resource_ids,
    output_dir,
    user=None,
    indent=2,
    states=None,
):
    """Export resources as a pkg-style directory with business_data, graphs, and reference_data.

    Creates:
        output_dir/
            business_data/
                t_<model_name>.json (one per model: its resources + relations)
                t_person.json       (all Person resources)
                t_period.json       (all Period resources)
            graphs/
                resource_models/
                    <GraphName>.json  (for each graph referenced by exported resources)
            reference_data/
                controlled_lists/
                    <list_name>.xml  (SKOS-RDF for each controlled list used)

    Args:
        resource_ids: list of resource instance IDs to export
        output_dir: directory path to write the package to
        user: optional User for permission-based nodegroup filtering
        indent: JSON indentation level (None for compact)
        states: optional lifecycle state names. When given, Persons and related
            resources are limited to these states too, and relations to
            resources left out are dropped. Periods are always exported.

    resource_ids may be empty, in which case only the graphs, controlled lists
    and always-exported reference resources are written (a structure-only package).

    Returns:
        tuple: (output_dir, diagnostics dict) or (None, None)
    """
    # Mark every resource public (the downstream builder expects __scopes) and
    # collect in-scope nodegroups from the tiles that were actually exported.
    exported_nodegroups = set()

    def _scope_resource(resource_data):
        resource_data["__scopes"] = ["public"]
        for tile in resource_data.get("tiles", []):
            if ng := tile.get("nodegroup_id"):
                exported_nodegroups.add(ng)

    # Export resources in batches, streaming to disk to avoid holding all
    # resource dicts in memory at once.
    # Start clean: the archive is built from the whole directory, so output
    # left by an earlier run (e.g. a model that no longer has exported
    # resources) would otherwise be packaged and shipped.
    import shutil

    for stale in ("business_data", "graphs", "reference_data"):
        shutil.rmtree(os.path.join(output_dir, stale), ignore_errors=True)
    for stale in ("files.json", "graphs.json"):
        try:
            os.remove(os.path.join(output_dir, stale))
        except FileNotFoundError:
            pass

    bd_dir = os.path.join(output_dir, "business_data")
    os.makedirs(bd_dir, exist_ok=True)
    resource_count = 0
    graph_ids = set()
    file_refs = []
    file_node_ids = get_file_node_ids()
    with _BusinessDataFiles(bd_dir, indent) as bd:

        actor_tiles_filtered_count = 0

        # Pre-compute exported Person IDs so we can strip associated_actor
        # tiles that reference Persons not in the export.
        person_ids = get_referenced_person_ids(states)
        period_ids = get_all_period_ids()

        def _write_resource(resource_data):
            nonlocal resource_count, actor_tiles_filtered_count
            # Strip associated_actor tiles referencing non-exported Persons
            actor_tiles_filtered_count += strip_unresolvable_actor_tiles(
                resource_data,
                person_ids,
            )
            _scope_resource(resource_data)

            # Collect graph IDs
            ri = resource_data.get("resourceinstance", {})
            if gid := ri.get("graph_id"):
                graph_ids.add(gid)

            # Collect file references inline
            for tile in resource_data.get("tiles", []):
                data = tile.get("data") or {}
                for node_id, value in data.items():
                    if node_id not in file_node_ids or not isinstance(value, list):
                        continue
                    for entry in value:
                        if not isinstance(entry, dict) or "file_id" not in entry:
                            continue
                        file_refs.append(
                            {
                                "file_id": entry.get("file_id"),
                                "name": entry.get("path") or entry.get("name"),
                                "url": entry.get("url"),
                                "resourceinstanceid": ri.get("resourceinstanceid", ""),
                                "nodeid": node_id,
                            }
                        )

            # Write to the file for this resource's model
            bd.write(ri.get("graph_id"), resource_data)
            resource_count += 1

        # Primary resources. Persons are written to t_person.json below, so skip
        # them here to avoid exporting them twice.
        resource_ids = [r for r in resource_ids if r not in person_ids]
        for resource_data in _write_resources_batched(
            [str(rid) for rid in resource_ids],
            user=user,
            indent=indent,
            label="Resources",
        ):
            _write_resource(resource_data)

        if resource_count == 0:
            logger.warning("No resources to export, writing structure only")

        # Get outbound relations
        relations, diagnostics, target_ids = get_outbound_relations(
            resource_ids,
            permitted_nodegroups=exported_nodegroups or None,
        )

        # With a state filter, related resources must be in an allowed state too.
        # Drop the others and any relation that would point at them.
        if states:
            target_ids = filter_ids_by_state(target_ids, states)
            kept_ids = {
                *(str(r) for r in resource_ids),
                *(str(p) for p in person_ids),
                *(str(p) for p in period_ids),
                *target_ids,
            }
            relations = [rel for rel in relations if rel["to_resource"] in kept_ids]
            diagnostics["candidate_relations"] = len(relations)

        # Second pass: related resources (Digital Objects etc.)
        target_ids = {str(t) for t in target_ids} - {
            str(r) for r in (*resource_ids, *person_ids)
        }
        diagnostics["included_target_resources"] = 0
        if target_ids:
            target_count = 0
            for resource_data in _write_resources_batched(
                sorted(target_ids),
                user=user,
                indent=indent,
                label="Related resources",
            ):
                _write_resource(resource_data)
                target_count += 1
            diagnostics["included_target_resources"] = target_count

        # Relations are written into each model's file when ``bd`` closes
        bd.relations = relations

    # De-duplicate file refs
    seen = set()
    unique_file_refs = []
    for ref in file_refs:
        key = ref.get("file_id") or ref.get("name")
        if key and key not in seen:
            seen.add(key)
            unique_file_refs.append(ref)
    file_refs = sorted(
        unique_file_refs, key=lambda r: (r["name"] or "", r["file_id"] or "")
    )
    diagnostics["referenced_files"] = file_refs
    diagnostics["actor_tiles_filtered"] = actor_tiles_filtered_count

    # Export Person resources (already computed above for tile filtering)
    diagnostics["person_resources"] = len(person_ids)
    if person_ids:
        _write_reference_resources(
            sorted(str(pid) for pid in person_ids),
            os.path.join(bd_dir, business_data_filename("Person")),
            user=user,
            indent=indent,
            label="Person",
        )
        graph_ids.add(PERSON_GRAPH_ID)

    # Export all Period resources
    diagnostics["period_resources"] = len(period_ids)
    if period_ids:
        _write_reference_resources(
            sorted(str(pid) for pid in period_ids),
            os.path.join(bd_dir, business_data_filename("Period")),
            user=user,
            indent=indent,
            label="Period",
        )
        graph_ids.add(PERIOD_GRAPH_ID)

    # Include all resource model graphs so the package carries the full structure
    graph_ids.update(get_exportable_graph_ids())
    for rel in relations:
        if gid := rel.get("to_resource_graph"):
            graph_ids.add(gid)

    # 1b. Write the referenced-file manifest at the package root.
    files_path = os.path.join(output_dir, "files.json")
    with open(files_path, "w") as f:
        json.dump({"files": file_refs}, f, indent=indent)

    # 2. Export graphs
    resource_files = {gid: [fn] for gid, fn in bd.filenames.items()}
    if person_ids:
        resource_files.setdefault(PERSON_GRAPH_ID, []).append(
            business_data_filename("Person")
        )
    if period_ids:
        resource_files.setdefault(PERIOD_GRAPH_ID, []).append(
            business_data_filename("Period")
        )
    exported_graphs = export_graphs_to_dir(
        graph_ids, output_dir, indent=indent, resource_files=resource_files
    )
    diagnostics["exported_graphs"] = exported_graphs

    # 3. Export controlled lists referenced by those graphs
    list_ids = get_controlled_list_ids_for_graphs(graph_ids)
    exported_lists = export_controlled_lists_to_dir(list_ids, output_dir)
    diagnostics["exported_controlled_lists"] = exported_lists

    # 4. Copy builder config (index templates etc.) from the package
    diagnostics["copied_static_files"] = copy_static_package_files(output_dir)
    write_package_scaffold(output_dir)

    return output_dir, diagnostics


def package_export(output_dir, archive_name="prebuild.tar"):
    """Tar an exported package directory into a single artefact.

    The directory contents are placed under a top-level ``prebuild/`` folder, as
    the starches build expects: extracting into the build context yields
    prebuild/business_data/, prebuild/graphs/, prebuild/reference_data/.
    Names ending in .tgz or .tar.gz are gzipped; anything else (e.g. .tar) is
    written uncompressed.

    Returns the path to the created archive (in a temp directory).
    """
    import tarfile
    import tempfile

    # basename only: archive_name may be a key like "starches/prebuild/x.tar"
    # and the local temp file must not point at a non-existent subdirectory.
    archive_path = os.path.join(tempfile.gettempdir(), os.path.basename(archive_name))
    mode = "w:gz" if archive_name.endswith((".tgz", ".tar.gz")) else "w"
    with tarfile.open(archive_path, mode) as tar:
        tar.add(output_dir, arcname="prebuild")
    logger.info("Packaged export %s -> %s", output_dir, archive_path)
    return archive_path


def upload_artifact(archive_path, bucket=None, key=None):
    """Upload an artefact to the prebuild S3 bucket.

    ``bucket`` and ``key`` default to PREBUILD_S3_BUCKET and PREBUILD_S3_KEY.
    Credentials come from the default boto3 chain, which on EKS is the IRSA
    token for the pod's ServiceAccount (no static keys). Returns the s3:// URL.

    Raises RuntimeError if the bucket or key are not configured.
    """
    import boto3

    bucket = bucket or os.environ.get("PREBUILD_S3_BUCKET")
    key = key or os.environ.get("PREBUILD_S3_KEY")
    if not (bucket and key):
        raise RuntimeError(
            "Prebuild upload not configured (PREBUILD_S3_BUCKET / PREBUILD_S3_KEY)."
        )

    region = os.environ.get("AWS_S3_REGION_NAME") or os.environ.get("AWS_REGION")
    client = boto3.client("s3", region_name=region)
    client.upload_file(archive_path, bucket, key)
    logger.info("Uploaded %s to s3://%s/%s", archive_path, bucket, key)
    return f"s3://{bucket}/{key}"


def resolve_export_user(username=None, expected_group="Public Export"):
    """Resolve the user whose nodegroup read-permissions the export applies.

    Mirrors the management command's --as-user handling so the Celery task and
    the command behave identically:
      * falsy username -> the 'anonymous' user (public-visitor view); if there
        is no 'anonymous' user, returns None (no nodegroup filtering).
      * a superuser raises ValueError (superusers bypass nodegroup permissions,
        which would silently export everything).

    Returns (user_or_None, messages) where messages is a list of
    (level, text) tuples for the caller to log.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    messages = []

    if not username:
        try:
            user = User.objects.get(username="anonymous")
        except User.DoesNotExist:
            messages.append(
                (
                    "warning",
                    "No export user and no 'anonymous' user found: NO nodegroup "
                    "filtering applied (every nodegroup will be exported).",
                )
            )
            return None, messages
        messages.append(
            (
                "info",
                "Applying the 'anonymous' user's nodegroup permissions "
                "(public-visitor view).",
            )
        )
        return user, messages

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        raise ValueError(f"export user '{username}' does not exist")
    if user.is_superuser:
        raise ValueError(
            f"export user '{username}' is a superuser; superusers bypass "
            f"nodegroup permissions so the whitelist would not apply."
        )

    group_names = set(user.groups.values_list("name", flat=True))
    if expected_group not in group_names:
        messages.append(
            (
                "warning",
                f"'{username}' is not in the '{expected_group}' group, so the "
                f"public-export whitelist will not be applied.",
            )
        )
    extra = group_names - {expected_group}
    if extra:
        messages.append(
            (
                "warning",
                f"'{username}' also belongs to {sorted(extra)}; read_nodegroup "
                f"grants from those groups can re-expose denied nodegroups.",
            )
        )
    return user, messages


def run_export_pipeline(
    output_dir="public_export",
    indent=2,
    user=None,
    states=None,
):
    """Run the full public-export selection+write pipeline (no console IO).

    Selects every resource (or only those in ``states``) and writes the pkg-style export to
    ``output_dir`` via export_resources (honouring ``user`` nodegroup
    permissions). With ``states``, Persons and related resources are limited to
    those states as well. Graphs in ALWAYS_VISIBLE_GRAPH_IDS are always exported. With no
    matching resources the package contains graphs and reference data only.

    Returns a dict:
        {
          "result": <output_dir> or None,
          "diagnostics": {...} or None,
          "export_ids": [str, ...],
          "messages": [(level, text), ...],
        }
    """
    out = {
        "result": None,
        "diagnostics": None,
        "export_ids": [],
        "messages": [],
    }
    msg = out["messages"]

    export_ids = get_exportable_resource_ids(states)
    if not export_ids:
        msg.append(
            (
                "warning",
                "No matching resources found, exporting graphs and structure only.",
            )
        )
    out["export_ids"] = [str(r) for r in export_ids]

    result, diagnostics = export_resources(
        export_ids,
        output_dir=output_dir,
        user=user,
        indent=indent,
        states=states,
    )
    if not result:
        msg.append(("error", "Export produced no output."))
        return out

    out["result"] = result
    out["diagnostics"] = diagnostics
    return out
