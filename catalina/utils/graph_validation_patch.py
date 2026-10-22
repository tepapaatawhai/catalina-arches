"""Speed up saving large graphs in the Graph Designer.

Graph.save() runs Graph.validate(), which calls Graph._validate_widget_count()
once per node. Each call runs Graph.get_widgets(), which serializes every
widget in the graph again. For a graph with a few hundred nodes this took over
20 seconds of CPU on each save (O(nodes x widgets)).

The widgets do not change during a validation, so this patch computes
get_widgets() once per validate() call and reuses the result.

Graph._validate_node_name() also calls Graph.get_sibling_nodes() once per node,
and each call scans every edge twice (O(nodes x edges), about 0.4s of a 470 node
graph's save). The edges do not change during a validation either, so the patch
indexes them once per validate() call and answers from the index.

Finally, validate() checks every edge with
`self.ontology.ontologyclasses.get(source=...)`, one query (and one decode of a
large JSON column) per edge: 471 queries, about 0.7s locally and much more
against a remote database. While a validation runs, the ontology's classes are
loaded once and `get(source=...)` is answered from that.

Behaviour outside validate() is untouched, and anything the caches cannot answer
falls back to the original code. Remove it once Arches stops recomputing
these for every node.
"""

import logging

logger = logging.getLogger(__name__)

_CACHE_ATTR = "_validate_widgets_cache"
_EDGE_INDEX_KEY = "edge_index"
_ONTOLOGY_CLASSES_ATTR = "_validate_ontology_classes"


class _ValidationOntologyClasses:
    """Stands in for `ontology.ontologyclasses` while a graph validates.

    get(source=...) is answered from one query; everything else goes to the
    real related manager.
    """

    def __init__(self, manager):
        self._manager = manager
        self._by_source = None

    def get(self, *args, **kwargs):
        if args or set(kwargs) != {"source"}:
            return self._manager.get(*args, **kwargs)
        if self._by_source is None:
            self._by_source = {}
            for ontology_class in self._manager.all():
                self._by_source.setdefault(ontology_class.source, []).append(
                    ontology_class
                )
        matches = self._by_source.get(kwargs["source"], [])
        if not matches:
            raise self._manager.model.DoesNotExist(
                "%s matching query does not exist."
                % self._manager.model._meta.object_name
            )
        if len(matches) > 1:
            raise self._manager.model.MultipleObjectsReturned(
                "get() returned more than one %s -- it returned %d!"
                % (self._manager.model._meta.object_name, len(matches))
            )
        return matches[0]

    def __getattr__(self, name):
        return getattr(self._manager, name)


class _OntologyClassesDescriptor:
    """Wraps Ontology.ontologyclasses, adding the validation-time lookup."""

    def __init__(self, original):
        self._original = original

    def __get__(self, instance, owner=None):
        manager = self._original.__get__(instance, owner)
        if instance is None:
            return manager
        shim = instance.__dict__.get(_ONTOLOGY_CLASSES_ATTR)
        if shim is None:
            return manager
        if shim.get("shim") is None:
            shim["shim"] = _ValidationOntologyClasses(manager)
        return shim["shim"]

    def __set__(self, instance, value):
        self._original.__set__(instance, value)

    def __getattr__(self, name):
        return getattr(self._original, name)


def apply():
    from arches.app.models.graph import Graph
    from arches.app.models.models import Ontology

    if getattr(Graph, "_catalina_widgets_cache_patched", False):
        return

    original_validate = Graph.validate
    original_get_widgets = Graph.get_widgets
    original_get_sibling_nodes = Graph.get_sibling_nodes

    def validate(self, *args, **kwargs):
        self.__dict__[_CACHE_ATTR] = {}
        ontology = self.ontology
        if ontology is not None:
            ontology.__dict__[_ONTOLOGY_CLASSES_ATTR] = {}
        try:
            return original_validate(self, *args, **kwargs)
        finally:
            self.__dict__.pop(_CACHE_ATTR, None)
            if ontology is not None:
                ontology.__dict__.pop(_ONTOLOGY_CLASSES_ATTR, None)

    def get_widgets(self, *args, **kwargs):
        cache = self.__dict__.get(_CACHE_ATTR)
        if cache is None:
            return original_get_widgets(self, *args, **kwargs)
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = original_get_widgets(self, *args, **kwargs)
        return cache[key]

    def get_sibling_nodes(self, node):
        cache = self.__dict__.get(_CACHE_ATTR)
        if cache is None or node.istopnode is not False:
            return original_get_sibling_nodes(self, node)

        index = cache.get(_EDGE_INDEX_KEY)
        if index is None:
            incoming = {}
            outgoing = {}
            for edge in self.edges.values():
                incoming.setdefault(edge.rangenode_id, edge)
                outgoing.setdefault(edge.domainnode_id, []).append(edge)
            index = cache[_EDGE_INDEX_KEY] = (incoming, outgoing)
        incoming, outgoing = index

        incoming_edge = incoming.get(node.nodeid)
        if incoming_edge is None:
            return original_get_sibling_nodes(self, node)
        return [
            edge.rangenode
            for edge in outgoing[incoming_edge.domainnode_id]
            if edge.rangenode.nodeid != node.nodeid
        ]

    Graph.validate = validate
    Graph.get_widgets = get_widgets
    Graph.get_sibling_nodes = get_sibling_nodes
    if not isinstance(Ontology.__dict__["ontologyclasses"], _OntologyClassesDescriptor):
        Ontology.ontologyclasses = _OntologyClassesDescriptor(
            Ontology.__dict__["ontologyclasses"]
        )
    Graph._catalina_widgets_cache_patched = True
    logger.debug("Applied Graph.validate widget, sibling and ontology class patch")
