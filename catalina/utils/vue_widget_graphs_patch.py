"""Hide inactive graphs from the "Create a new X" rows of the Vue widgets.

The arches_vue_components Resource Instance (multi)select widgets render one
"Create a new X" row for every graph in the node's ``config.graphs``, as served
by the card-x-node-x-widget API, without checking GraphModel.is_active. An
inactive graph therefore stays offered (and unclickable in the Add menu, but not
here).

Both API views build their payload with serialize_card_x_node_x_widget(), so
this wraps it and drops inactive graphs from ``node.config.graphs`` of the
payload. Only the served copy changes; the node config stored in the database
is untouched, so reactivating a graph brings its row back. Remove this once
arches_vue_components filters inactive graphs itself.
"""

import logging

logger = logging.getLogger(__name__)


def filter_inactive_graphs(serialized_widget):
    """Drop inactive graphs from the node config of a serialized widget."""
    from arches.app.models.models import GraphModel

    config = (serialized_widget.get("node") or {}).get("config")
    graphs = config.get("graphs") if isinstance(config, dict) else None
    if not graphs:
        return serialized_widget

    graph_ids = [graph.get("graphid") for graph in graphs if isinstance(graph, dict)]
    active = {
        str(pk)
        for pk in GraphModel.objects.filter(
            pk__in=graph_ids, is_active=True
        ).values_list("pk", flat=True)
    }
    config["graphs"] = [
        graph
        for graph in graphs
        if not isinstance(graph, dict) or str(graph.get("graphid")) in active
    ]
    return serialized_widget


def apply():
    from arches_vue_components.views.api import card_x_node_x_widget

    if getattr(card_x_node_x_widget, "_catalina_inactive_graphs_patched", False):
        return

    original = card_x_node_x_widget.serialize_card_x_node_x_widget

    def serialize_card_x_node_x_widget(*args, **kwargs):
        return filter_inactive_graphs(original(*args, **kwargs))

    card_x_node_x_widget.serialize_card_x_node_x_widget = serialize_card_x_node_x_widget
    card_x_node_x_widget._catalina_inactive_graphs_patched = True
    logger.debug("Applied Vue widget inactive graphs patch")
