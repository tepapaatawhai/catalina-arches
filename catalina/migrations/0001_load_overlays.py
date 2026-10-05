"""Superseded: overlays are now defined in catalina/overlays/registry.py.

The registry is applied after every migrate and rewrites these rows by the same
fixed ids, so what this migration writes on a fresh database is short-lived.
Kept as applied history.
"""

import logging
import uuid

from django.conf import settings
from django.db import migrations

logger = logging.getLogger(__name__)


# Fixed UUIDs let re-runs target the same MapLayer rows even if the human-
# readable name changes.
NZAA_LAYER_ID = uuid.UUID("a7d0e8b1-3000-4001-8000-000000000001")
CONS_LAND_LAYER_ID = uuid.UUID("a7d0e8b1-3000-4001-8000-000000000002")
OPS_REGIONS_LAYER_ID = uuid.UUID("a7d0e8b1-3000-4001-8000-000000000003")
OPS_DISTRICTS_LAYER_ID = uuid.UUID("a7d0e8b1-3000-4001-8000-000000000004")
LINZ_AERIAL_LAYER_ID = uuid.UUID("a7d0e8b1-3000-4001-8000-000000000005")
LINZ_TOPO_LAYER_ID = uuid.UUID("a7d0e8b1-3000-4001-8000-000000000006")

OVERLAY_LAYER_IDS = [
    NZAA_LAYER_ID,
    CONS_LAND_LAYER_ID,
    OPS_REGIONS_LAYER_ID,
    OPS_DISTRICTS_LAYER_ID,
    LINZ_AERIAL_LAYER_ID,
    LINZ_TOPO_LAYER_ID,
]

OVERLAY_SLUGS = [
    "nzaa",
    "cons_land",
    "ops_regions",
    "ops_districts",
    "aerial",
    "topo",
]


def _portal_geojson_url(slug, layer_index=0):
    # ArcGIS FeatureServer "?f=geojson&where=1=1" returns at most the service's
    # maxRecordCount features. Layers past that (nzaa, cons_land) are fetched
    # per view in the registry (catalina/media/js/utils/map-configurator.js).
    return f"/overlays/{slug}/{layer_index}/query?where=1%3D1&outFields=*&f=geojson"


# Vector overlays carry click/hover popup config as Mapbox layer
# `metadata["arches:popup"]` ({"title": <prop>, "fields": [[label, prop], ...]}),
# read client-side by the project map popup provider
# (catalina/media/js/utils/map-popup-provider.js).
# Hover highlight requires a stable, globally-unique feature id (so feature-state
# is keyed consistently across the tiles a feature spans) plus the feature-state
# paint cases. The source sets "promoteId": "objectid" to use the FeatureServer's
# unique key as that id.
def load_overlays(apps, schema_editor):
    MapLayer = apps.get_model("models", "MapLayer")
    MapSource = apps.get_model("models", "MapSource")

    def upsert(*, slug, layer_id, label, sortorder, source, layers, **layer_attrs):
        MapSource.objects.update_or_create(
            name=slug,
            defaults={"source": source},
        )
        MapLayer.objects.update_or_create(
            maplayerid=layer_id,
            defaults={
                "name": label,
                "layerdefinitions": layers,
                "isoverlay": True,
                "sortorder": sortorder,
                **layer_attrs,
            },
        )

    portal_configured = bool(
        settings.ARCGIS_PORTAL_URL
        and settings.ARCGIS_PORTAL_USERNAME
        and settings.ARCGIS_PORTAL_PASSWORD
    )
    if not portal_configured:
        logger.warning(
            "ArcGIS portal env (ARCGIS_PORTAL_URL/USERNAME/PASSWORD) is "
            "incomplete; skipping all portal-backed overlays."
        )

    # Only register portal-backed overlays this env declares available
    # (PORTAL_OVERLAYS_AVAILABLE). DOC reshuffles services between envs, so
    # each env's values.yaml lists what its portal actually has.
    portal_available = (
        settings.PORTAL_OVERLAYS_AVAILABLE if portal_configured else set()
    )

    # NZAA archaeological sites (~80k features). The slug's service is set in
    # settings.ARCGIS_PORTAL_SERVICES; the registry fetches it per view.
    if "nzaa" in portal_available:
        upsert(
            slug="nzaa",
            layer_id=NZAA_LAYER_ID,
            label="NZAA Archaeological Sites",
            sortorder=10,
            activated=True,
            addtomap=False,
            ispublic=False,
            icon="fa fa-monument",
            source={
                "type": "geojson",
                "promoteId": "objectid",
                "data": _portal_geojson_url("nzaa"),
            },
            layers=[
                {
                    "id": "nzaa-fill",
                    "source": "nzaa",
                    "type": "fill",
                    "metadata": {
                        "arches:popup": {
                            "title": "name",
                            "fields": [
                                ["Site", "name"],
                                ["NZAA ID", "nzaa_id"],
                                ["Features", "sitefeatures"],
                                ["Period", "period"],
                            ],
                        }
                    },
                    "paint": {
                        "fill-color": "#7c3aed",
                        "fill-opacity": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            0.5,
                            0.3,
                        ],
                    },
                },
                {
                    "id": "nzaa-outline",
                    "source": "nzaa",
                    "type": "line",
                    "paint": {
                        "line-color": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            "#2e1065",
                            "#5b21b6",
                        ],
                        "line-width": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            2,
                            1,
                        ],
                    },
                },
            ],
        )

    # Conservation Land (~11k features, maxRecordCount 1000); the registry
    # fetches it per view.
    if "cons_land" in portal_available:
        upsert(
            slug="cons_land",
            layer_id=CONS_LAND_LAYER_ID,
            label="Public Conservation Land",
            sortorder=20,
            activated=True,
            addtomap=False,
            ispublic=False,
            icon="fa fa-tree",
            source={
                "type": "geojson",
                "promoteId": "objectid",
                "data": _portal_geojson_url("cons_land"),
            },
            layers=[
                {
                    "id": "cons_land-fill",
                    "source": "cons_land",
                    "type": "fill",
                    "metadata": {
                        "arches:popup": {
                            "title": "name",
                            "fields": [
                                ["Type", "type"],
                                ["NaPALIS ID", "napalis_id"],
                                ["Name", "name"],
                                ["Recorded Area (ha)", "recorded_area"],
                            ],
                        }
                    },
                    "paint": {
                        "fill-color": "#22c55e",
                        "fill-opacity": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            0.5,
                            0.25,
                        ],
                    },
                },
                {
                    "id": "cons_land-outline",
                    "source": "cons_land",
                    "type": "line",
                    "paint": {
                        "line-color": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            "#052e16",
                            "#15803d",
                        ],
                        "line-width": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            2,
                            0.5,
                        ],
                    },
                },
            ],
        )

    # DOC Operations Regions (11 features; one request).
    if "ops_regions" in portal_available:
        upsert(
            slug="ops_regions",
            layer_id=OPS_REGIONS_LAYER_ID,
            label="DOC Operations Regions",
            sortorder=30,
            activated=True,
            addtomap=False,
            ispublic=False,
            icon="fa fa-map",
            source={
                "type": "geojson",
                "promoteId": "objectid",
                "data": _portal_geojson_url("ops_regions"),
            },
            layers=[
                {
                    "id": "ops_regions-fill",
                    "source": "ops_regions",
                    "type": "fill",
                    # "region" is the DOC_WebsiteRegions/FeatureServer field
                    # name. The registry switches this popup to the regionname /
                    # regioncode fields of DOC_OperationsRegions_HFLr/FeatureServer.
                    "metadata": {
                        "arches:popup": {
                            "title": "region",
                            "fields": [["Region", "region"]],
                        }
                    },
                    "paint": {
                        "fill-color": "#3b82f6",
                        "fill-opacity": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            0.35,
                            0.15,
                        ],
                    },
                },
                {
                    "id": "ops_regions-outline",
                    "source": "ops_regions",
                    "type": "line",
                    "paint": {
                        "line-color": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            "#172554",
                            "#1d4ed8",
                        ],
                        "line-width": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            2.4,
                            1.2,
                        ],
                    },
                },
            ],
        )

    # DOC Operations Districts (46 features; one request).
    if "ops_districts" in portal_available:
        upsert(
            slug="ops_districts",
            layer_id=OPS_DISTRICTS_LAYER_ID,
            label="DOC Operations Districts",
            sortorder=40,
            activated=True,
            addtomap=False,
            ispublic=False,
            icon="fa fa-map-signs",
            source={
                "type": "geojson",
                "promoteId": "objectid",
                "data": _portal_geojson_url("ops_districts"),
            },
            layers=[
                {
                    "id": "ops_districts-fill",
                    "source": "ops_districts",
                    "type": "fill",
                    "metadata": {
                        "arches:popup": {
                            "title": "districtname",
                            "fields": [
                                ["District Name", "districtname"],
                                ["District Code", "districtcode"],
                                ["Region Name", "regionname"],
                                ["Region Code", "regioncode"],
                            ],
                        }
                    },
                    "paint": {
                        "fill-color": "#f97316",
                        "fill-opacity": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            0.35,
                            0.15,
                        ],
                    },
                },
                {
                    "id": "ops_districts-outline",
                    "source": "ops_districts",
                    "type": "line",
                    "paint": {
                        "line-color": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            "#7c2d12",
                            "#c2410c",
                        ],
                        "line-width": [
                            "case",
                            ["boolean", ["feature-state", "hover"], False],
                            2,
                            0.7,
                        ],
                    },
                },
            ],
        )

    if not settings.LINZ_BASEMAPS_API_KEY:
        logger.warning(
            "LINZ_BASEMAPS_API_KEY is not set; skipping LINZ overlays (aerial, topo)."
        )
        return

    # LINZ Basemaps aerial — public XYZ raster, referer-restricted API key.
    aerial_tile_url = (
        "https://basemaps.linz.govt.nz/v1/tiles/aerial/EPSG:3857/"
        f"{{z}}/{{x}}/{{y}}.webp?api={settings.LINZ_BASEMAPS_API_KEY}"
    )
    upsert(
        slug="aerial",
        layer_id=LINZ_AERIAL_LAYER_ID,
        label="Aerial Photos (LINZ)",
        sortorder=50,
        activated=True,
        addtomap=False,
        ispublic=True,
        icon="fa fa-camera",
        source={"type": "raster", "tiles": [aerial_tile_url], "tileSize": 256},
        layers=[{"id": "aerial", "source": "aerial", "type": "raster"}],
    )

    # LINZ Topo — LINZ Basemaps topo-raster-gridded style. Same hosting, key,
    # and referer-restriction story as the aerial overlay. Switched from the
    # Eagle-hosted ArcGIS MapServer because that service publishes in
    # NZTM2000 (wkid 2193), which Mapbox GL can't render.
    # LINZ's `topographic` style is vector-only; `topo-raster-gridded` is the
    # raster equivalent. `WebMercatorQuad` is LINZ's name for the standard
    # EPSG:3857 tile matrix.
    topo_tile_url = (
        "https://basemaps.linz.govt.nz/v1/tiles/topo-raster-gridded/WebMercatorQuad/"
        f"{{z}}/{{x}}/{{y}}.webp?api={settings.LINZ_BASEMAPS_API_KEY}"
    )
    upsert(
        slug="topo",
        layer_id=LINZ_TOPO_LAYER_ID,
        label="LINZ Topo",
        sortorder=60,
        activated=True,
        addtomap=False,
        ispublic=True,
        icon="fa fa-mountain",
        source={"type": "raster", "tiles": [topo_tile_url], "tileSize": 256},
        layers=[{"id": "topo", "source": "topo", "type": "raster"}],
    )


def unload_overlays(apps, schema_editor):
    MapLayer = apps.get_model("models", "MapLayer")
    MapSource = apps.get_model("models", "MapSource")
    MapLayer.objects.filter(maplayerid__in=OVERLAY_LAYER_IDS).delete()
    MapSource.objects.filter(name__in=OVERLAY_SLUGS).delete()


class Migration(migrations.Migration):
    # Overlays only touch core MapLayer/MapSource, not any her graph nodes, so
    # this depends on core models rather than the removed package-load migration.
    # Spatial views moved to catalina/pkg/post_sql/add_spatial_views.sql.
    dependencies = [
        ("models", "12586_tile_cardinality_check"),
    ]

    operations = [
        migrations.RunPython(load_overlays, unload_overlays),
    ]
