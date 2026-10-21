"""Hide inactive graphs from the "Add new resource" menu.

Arches builds the menu from permission_backend.get_createable_resource_models(),
which delegates to get_createable_resource_types(user) and does not look at
GraphModel.is_active. Inactive graphs therefore appear in the menu, greyed out
and unclickable.

get_createable_resource_models() resolves get_createable_resource_types through
its own module globals, so wrapping the latter here works regardless of whether
the view modules have already imported the former. Remove this once Arches
filters inactive graphs itself.
"""

import logging

logger = logging.getLogger(__name__)


def apply():
    from arches.app.models.models import GraphModel
    from arches.app.utils import permission_backend

    if getattr(permission_backend, "_catalina_createable_patched", False):
        return

    original = permission_backend.get_createable_resource_types

    def get_createable_resource_types(user, *args, **kwargs):
        types = list(original(user, *args, **kwargs))
        active = {
            str(pk)
            for pk in GraphModel.objects.filter(
                pk__in=types, is_active=True
            ).values_list("pk", flat=True)
        }
        return [graphid for graphid in types if str(graphid) in active]

    permission_backend.get_createable_resource_types = get_createable_resource_types
    permission_backend._catalina_createable_patched = True
    logger.debug("Applied createable resource types is_active patch")
