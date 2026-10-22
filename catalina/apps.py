from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _apply_overlays(sender, **kwargs):
    from catalina.overlays.apply import apply_overlays

    apply_overlays()


class CatalinaConfig(AppConfig):
    name = "catalina"
    is_arches_application = True

    def ready(self):
        from catalina.oauth_application import sync_gis_oauth_application
        from catalina.utils import (
            createable_resources_patch,
            graph_validation_patch,
            permitted_graphids_patch,
        )

        # Inactive graphs should not appear in the "Add new resource" menu.
        createable_resources_patch.apply()

        # Saving a large graph in the Graph Designer re-serialized every widget
        # once per node; see the module docstring.
        graph_validation_patch.apply()

        # Resolving permitted graph ids instantiated ~20k Node rows per search.
        permitted_graphids_patch.apply()

        # post_migrate is only sent for apps with a models module, which catalina
        # lacks, so each handler listens for the app whose table it writes to.
        post_migrate.connect(
            sync_gis_oauth_application,
            sender=self.apps.get_app_config("oauth2_provider"),
            dispatch_uid="catalina.sync_gis_oauth_application",
        )
        # Every migrate, including each deploy's, writes the overlay registry
        # (MapLayer/MapSource belong to Arches' core models app).
        post_migrate.connect(
            _apply_overlays,
            sender=self.apps.get_app_config("models"),
            dispatch_uid="catalina.apply_overlays",
        )
