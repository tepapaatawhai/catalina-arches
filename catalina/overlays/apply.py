"""Write the overlay registry (catalina/overlays/registry.py) to the database.

Runs after every migrate (see catalina/apps.py), so each deploy applies the
current registry, and on demand via `manage.py apply_overlays`.
"""

import logging

from django.db import IntegrityError, transaction

from catalina.overlays.registry import overlays

logger = logging.getLogger(__name__)


def apply_overlays():
    """Create or rewrite each available overlay; delete each unavailable one.

    Returns (applied, removed, failed) lists of slugs. An overlay that can't
    be written, e.g. because a layer made elsewhere already has its name
    (MapLayer.name is unique), is logged and skipped rather than raised, so a
    deploy isn't blocked by one overlay.
    """
    from arches.app.models.models import MapLayer, MapSource

    applied, removed, failed = [], [], []
    for overlay in overlays():
        if not overlay.available:
            deleted, _ = MapLayer.objects.filter(maplayerid=overlay.layer_id).delete()
            deleted += MapSource.objects.filter(name=overlay.slug).delete()[0]
            if deleted:
                removed.append(overlay.slug)
            continue

        try:
            with transaction.atomic():
                MapSource.objects.update_or_create(
                    name=overlay.slug, defaults={"source": overlay.source}
                )
                MapLayer.objects.update_or_create(
                    maplayerid=overlay.layer_id,
                    defaults={
                        "name": overlay.name,
                        "layerdefinitions": overlay.layers,
                        "isoverlay": True,
                        "activated": True,
                        "addtomap": False,
                        # Any logged-in user sees every overlay; the portal
                        # data itself sits behind the login-gated proxy.
                        "ispublic": True,
                        "sortorder": overlay.sortorder,
                        "icon": overlay.icon,
                        "legend": overlay.legend,
                    },
                )
        except IntegrityError as error:
            logger.error("Overlay %s not applied: %s", overlay.slug, error)
            failed.append(overlay.slug)
        else:
            applied.append(overlay.slug)

    logger.info(
        "Overlays applied: %s; removed: %s; failed: %s",
        ", ".join(applied) or "none",
        ", ".join(removed) or "none",
        ", ".join(failed) or "none",
    )
    return applied, removed, failed
