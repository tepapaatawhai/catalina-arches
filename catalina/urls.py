from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.urls import include, path, re_path

from . import views_azure
from .overlays.proxy import ArcGISPortalProxyView

urlpatterns = []

handler400 = "arches.app.views.main.custom_400"
handler403 = "arches.app.views.main.custom_403"
handler404 = "arches.app.views.main.custom_404"
handler500 = "arches.app.views.main.custom_500"

# Ensure Arches core urls are superseded by project-level urls
urlpatterns = [
    re_path(
        r"^overlays/(?P<slug>[\w-]+)/(?P<path>.*)$",
        ArcGISPortalProxyView.as_view(),
        name="arcgis_portal_proxy",
    ),
    path("", include("arches.urls")),
    path("azure_auth/callback", views_azure.azure_auth_callback),
    path("azure_auth/", include("azure_auth.urls")),
    path("", include("arches_controlled_lists.urls")),
    path("", include("arches_vue_components.urls")),
    path("", include("arches_her.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Only handle i18n routing in active project. This will still handle the routes provided by Arches core and Arches applications,
# but handling i18n routes in multiple places causes application errors.
if settings.ROOT_URLCONF == __name__:
    if settings.SHOW_LANGUAGE_SWITCH is True:
        urlpatterns = i18n_patterns(*urlpatterns)

    urlpatterns.append(path("i18n/", include("django.conf.urls.i18n")))

if settings.DEBUG:
    from django.contrib.staticfiles import views
    from django.urls import re_path

    urlpatterns += [
        re_path(r"^static/(?P<path>.*)$", views.serve),
    ]
