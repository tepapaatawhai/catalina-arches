"""Let a group's model-level ``view_plugin`` permission show every plugin.

Arches decides whether a user may open a plugin (the controlled list manager,
the workflow builders and so on), and whether it appears in the manager menu,
with ``user.has_perm("view_plugin", plugin)``. For a Plugin that falls through
to django-guardian, which only honours per-plugin object rows and ignores the
group's model-level permission. A group ticked for "Can view plugin" therefore
saw no plugins at all.

This backend upgrades that one check: a user whose group holds ``view_plugin``
gets every plugin. It never removes access the other backends grant.
"""

from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import Permission

VIEW_PLUGIN = "view_plugin"


class PluginPermissionBackend(BaseBackend):
    def has_perm(self, user_obj, perm, obj=None):
        from arches.app.models.models import Plugin

        if not isinstance(obj, Plugin):
            return False
        if perm.split(".")[-1] != VIEW_PLUGIN:
            return False
        if not getattr(user_obj, "is_active", False):
            return False
        # The menu asks once per plugin, so remember the answer on the user.
        if not hasattr(user_obj, "_catalina_group_view_plugin"):
            user_obj._catalina_group_view_plugin = Permission.objects.filter(
                group__user=user_obj,
                codename=VIEW_PLUGIN,
                content_type__model="plugin",
            ).exists()
        return user_obj._catalina_group_view_plugin
