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
