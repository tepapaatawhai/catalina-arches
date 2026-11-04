"""Make the ``has_group`` template filter honour role permissions.

The manager menu decides whether to show Graph Designer, the Reference Data
Manager and similar entries with ``request.user|has_group:"Graph Editor"``.
Arches implements that by querying ``user.groups`` by name, so it never reaches
the permission framework and ignores groups that hold the matching role
permission (see catalina.permissions.blanket_roles). The replacement asks the
framework instead, which still counts real group membership.

Remove this once Arches routes the filter through the permission framework.
"""

import logging

logger = logging.getLogger(__name__)


def has_group(user, group_names):
    from arches.app.utils.permission_backend import user_in_group_by_name

    if user.is_authenticated:
        if user.is_superuser or user_in_group_by_name(user, group_names.split(",")):
            return True
    return False


def apply():
    from arches.templatetags import template_tags

    if getattr(template_tags, "_catalina_has_group_patched", False):
        return

    template_tags.has_group = has_group
    template_tags.register.filters["has_group"] = has_group
    template_tags._catalina_has_group_patched = True
    logger.debug("Applied has_group patch")
