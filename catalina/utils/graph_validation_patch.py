"""Speed up saving large graphs in the Graph Designer.

Graph.save() runs Graph.validate(), which calls Graph._validate_widget_count()
once per node. Each call runs Graph.get_widgets(), which serializes every
widget in the graph again. For a graph with a few hundred nodes this took over
20 seconds of CPU on each save (O(nodes x widgets)).

The widgets do not change during a validation, so this patch computes
get_widgets() once per validate() call and reuses the result. Behaviour outside
validate() is untouched. Remove it once Arches stops recomputing the widgets
for every node.
"""

import logging

logger = logging.getLogger(__name__)

_CACHE_ATTR = "_validate_widgets_cache"


def apply():
    from arches.app.models.graph import Graph

    if getattr(Graph, "_catalina_widgets_cache_patched", False):
        return

    original_validate = Graph.validate
    original_get_widgets = Graph.get_widgets

    def validate(self, *args, **kwargs):
        self.__dict__[_CACHE_ATTR] = {}
        try:
            return original_validate(self, *args, **kwargs)
        finally:
            self.__dict__.pop(_CACHE_ATTR, None)

    def get_widgets(self, *args, **kwargs):
        cache = self.__dict__.get(_CACHE_ATTR)
        if cache is None:
            return original_get_widgets(self, *args, **kwargs)
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = original_get_widgets(self, *args, **kwargs)
        return cache[key]

    Graph.validate = validate
    Graph.get_widgets = get_widgets
    Graph._catalina_widgets_cache_patched = True
    logger.debug("Applied Graph.validate widget cache patch")
