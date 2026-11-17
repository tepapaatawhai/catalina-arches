"""Fall back to the default language for resource names and descriptions.

Resource data is only entered in the default language, but Arches computes and
stores the name, description and map popup descriptors once per UI language.
For any other language (e.g. ``mi``) the string datatype finds no value, the
descriptor template resolves to nothing and Arches stores a placeholder, the
translation of "Undefined" in that language (for ``mi`` that is
"Kāore i tautuhitia"). The report and editor headers then show the
placeholder instead of the resource name. Some resources have no stored
descriptors at all, which shows as "None".

The replacement reads the descriptor as before. If it is missing, empty or one
of those placeholders it tries, in order: the stored default-language value,
then a value computed on the fly from the tile data for the active language
and for the default language. Nothing is written, and nothing needs
reindexing.

Remove this if Arches adds a default-language fallback for descriptors.
"""

import logging

logger = logging.getLogger(__name__)

_placeholders = None


def _get_placeholders():
    """Every spelling of "Undefined" Arches may have stored, in any language."""
    global _placeholders
    if _placeholders is None:
        from django.conf import settings
        from django.utils import translation

        values = {None, "", "Undefined", "undefined"}
        for code, _name in settings.LANGUAGES:
            with translation.override(code):
                values.add(str(translation.gettext("Undefined")))
        _placeholders = values
    return _placeholders


def _is_empty(value):
    return value in _get_placeholders()


def _compute_live(resource, descriptor, language):
    """Compute a descriptor from the tile data without storing it."""
    from arches.app.models import models

    try:
        function_x_graph = (
            models.FunctionXGraph.objects.filter(
                graph_id=resource.graph_id,
                function__functiontype="primarydescriptors",
            )
            .select_related("function")
            .first()
        )
        if function_x_graph is None:
            return None
        module = function_x_graph.function.get_class_module()()
        return module.get_primary_descriptor_from_nodes(
            resource,
            function_x_graph.config["descriptor_types"][descriptor],
            {"language": language},
            descriptor,
        )
    except Exception:
        logger.debug("Could not compute %s live", descriptor, exc_info=True)
        return None


def apply():
    from arches.app.models.resource import Resource
    from django.conf import settings
    from django.utils.translation import get_language

    if getattr(Resource, "_catalina_descriptor_fallback_patched", False):
        return

    original = Resource.get_descriptor

    def get_descriptor(self, descriptor, context):
        result = original(self, descriptor, context)
        if not _is_empty(result):
            return result

        language = (context or {}).get("language", get_language())
        default_language = settings.LANGUAGE_CODE

        if language != default_language:
            stored = original(
                self, descriptor, dict(context or {}, language=default_language)
            )
            if not _is_empty(stored):
                return stored

        for code in dict.fromkeys((language, default_language)):
            live = _compute_live(self, descriptor, code)
            if not _is_empty(live):
                return live

        return result

    Resource.get_descriptor = get_descriptor
    Resource._catalina_descriptor_fallback_patched = True
    logger.debug("Applied descriptor language fallback patch")
