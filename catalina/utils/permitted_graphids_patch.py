"""Speed up get_permitted_graphids() in the Arches search components.

Arches resolves the permitted graph ids by instantiating every Node row in the
permitted nodegroups (about 20k rows, each going through the i18n field
converters) just to read graph_id, and it does so twice per search request
(resource type filter and search results). That was roughly half of the
server-side time of every search, which matters most for resource-instance
selects that search on each keystroke.

The replacement resolves the same set with one query and no model
instantiation. search_results imports the function by name, so both modules are
patched. Remove this once Arches does it itself.
"""

import logging

logger = logging.getLogger(__name__)


def get_permitted_graphids(permitted_nodegroups):
    from arches.app.models.models import GraphModel, Node

    graph_ids = Node.objects.filter(nodegroup__in=permitted_nodegroups).values(
        "graph_id"
    )
    return {
        str(graphid)
        for graphid in GraphModel.objects.filter(graphid__in=graph_ids)
        .exclude(is_active=False)
        .values_list("graphid", flat=True)
    }


def apply():
    from arches.app.search.components import resource_type_filter, search_results

    if getattr(resource_type_filter, "_catalina_permitted_graphids_patched", False):
        return

    resource_type_filter.get_permitted_graphids = get_permitted_graphids
    search_results.get_permitted_graphids = get_permitted_graphids
    resource_type_filter._catalina_permitted_graphids_patched = True
    logger.debug("Applied permitted graph ids patch")
