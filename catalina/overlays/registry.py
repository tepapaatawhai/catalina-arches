"""The project's map overlays, applied to MapSource/MapLayer on every migrate.

The registry owns exactly the rows it defines: each overlay's MapLayer (by its
fixed maplayerid) and MapSource (by its slug). apply_overlays() rewrites those
rows in full each time, so edits made to them in the Arches Map Layer Manager
don't survive a deploy. Every other map layer and source is left alone. An
overlay whose env isn't configured has its rows deleted; map layer permissions
are keyed on the fixed maplayerid, so they reattach if it comes back.

To change an overlay, edit it here and deploy (or `manage.py apply_overlays`).
See catalina/overlays/apply.py.

Layer definitions are Mapbox GL style layers, plus two project metadata keys
read by the frontend overrides in catalina/media/js/utils/:
    arches:popup      {"title": <prop>, "fields": [[label, prop], ...]}, read by
                      map-popup-provider.js; on one of an overlay's layers is
                      enough, as it's matched by source.
    arches:bbox-fetch {"url", "minzoom", "maxpages"?, "outFields"?}, read by
                      map-configurator.js, for sources past their service's
                      maxRecordCount: the source starts empty and is filled per
                      map view.
Hover highlight needs a stable, unique feature id for feature-state, so portal
sources set "promoteId": "objectid".
"""

import uuid
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class Overlay:
    slug: str
    layer_id: uuid.UUID
    name: str
    sortorder: int
    icon: str
    source: dict
    layers: list
    available: bool
    legend: str | None = None


HOVERED = ["boolean", ["feature-state", "hover"], False]
EMPTY_FEATURE_COLLECTION = {"type": "FeatureCollection", "features": []}


def _portal_available(slug):
    return bool(
        settings.ARCGIS_PORTAL_URL
        and settings.ARCGIS_PORTAL_USERNAME
        and settings.ARCGIS_PORTAL_PASSWORD
        and slug in settings.PORTAL_OVERLAYS_AVAILABLE
    )


def _hover(on, off):
    return ["case", HOVERED, on, off]


def _portal_source(slug, layer_index):
    """A source fetched whole, in one request: within the service's maxRecordCount."""
    return {
        "type": "geojson",
        "promoteId": "objectid",
        "data": (
            f"/overlays/{slug}/{layer_index}/query?where=1%3D1&outFields=*&f=geojson"
        ),
    }


def _bbox_fetch_source():
    return {
        "type": "geojson",
        "promoteId": "objectid",
        "data": EMPTY_FEATURE_COLLECTION,
    }


def _bbox_fetch(slug, layer_index, minzoom, maxpages=None, out_fields=None):
    config = {"url": f"/overlays/{slug}/{layer_index}/query", "minzoom": minzoom}
    if maxpages is not None:
        config["maxpages"] = maxpages
    if out_fields is not None:
        config["outFields"] = out_fields
    return {"arches:bbox-fetch": config}


def _popup(title, fields):
    return {"arches:popup": {"title": title, "fields": fields}}


def _polygon_layers(slug, fill_paint, line_paint, metadata):
    return [
        {
            "id": f"{slug}-fill",
            "source": slug,
            "type": "fill",
            "metadata": metadata,
            "paint": fill_paint,
        },
        {"id": f"{slug}-outline", "source": slug, "type": "line", "paint": line_paint},
    ]


def _linz_tiles(path):
    return (
        f"https://basemaps.linz.govt.nz/v1/tiles/{path}/"
        f"{{z}}/{{x}}/{{y}}.webp?api={settings.LINZ_BASEMAPS_API_KEY}"
    )


# --- NZAA ---------------------------------------------------------------------

NZAA_FIELDS = "objectid,name,nzaa_id,sitefeatures,period"
# name is often null, so the title uses the always-populated nzaa_id.
NZAA_POPUP = _popup(
    "nzaa_id",
    [
        ["Name", "name"],
        ["NZAA ID", "nzaa_id"],
        ["Features", "sitefeatures"],
        ["Period", "period"],
    ],
)


def _nzaa():
    # NZAA_ArchSites_HFLr layer 7: ~80k sites, mostly small squares, so
    # simplification barely helps but trimming outFields halves the payload. A
    # zoom-9 view of Auckland, the densest area, holds ~13k: 7 pages of 2000.
    return Overlay(
        slug="nzaa",
        layer_id=uuid.UUID("a7d0e8b1-3000-4001-8000-000000000001"),
        name="NZAA Archaeological Sites",
        sortorder=10,
        icon="fa fa-monument",
        available=_portal_available("nzaa"),
        source=_bbox_fetch_source(),
        layers=_polygon_layers(
            "nzaa",
            {"fill-color": "#7c3aed", "fill-opacity": _hover(0.5, 0.3)},
            {
                "line-color": _hover("#2e1065", "#5b21b6"),
                "line-width": _hover(2, 1),
            },
            {
                **NZAA_POPUP,
                **_bbox_fetch("nzaa", 7, minzoom=9, maxpages=8, out_fields=NZAA_FIELDS),
            },
        ),
    )


def _nzaa_buff():
    # NZAA_ArchSiteBuffer_HFLr layer 6: the same ~80k sites as 200m buffers.
    # Sized like nzaa; simplification flattens the buffers at low zoom.
    layers = _polygon_layers(
        "nzaa_buff",
        {"fill-color": "#be123c", "fill-opacity": _hover(0.6, 0.4)},
        {"line-color": _hover("#4c0519", "#9f1239"), "line-width": _hover(2, 1)},
        {
            **NZAA_POPUP,
            **_bbox_fetch(
                "nzaa_buff", 6, minzoom=9, maxpages=8, out_fields=NZAA_FIELDS
            ),
        },
    )
    return Overlay(
        slug="nzaa_buff",
        layer_id=uuid.UUID("a7d0e8b1-3000-4001-8000-000000000007"),
        name="NZAA Archaeological Buffered (200m)",
        sortorder=5,
        icon="fa fa-monument",
        available=_portal_available("nzaa_buff"),
        source=_bbox_fetch_source(),
        layers=layers,
    )


# --- Public Conservation Land ---------------------------------------------------

# DOC's own symbology for this layer, from the "Public Conservation Land" layer
# item (568e551c7ce94807821b097201015fbe) on the portal: a unique-value
# renderer on `section`, grouped into the classes its legend shows.
CONS_LAND_CLASSES = [
    (
        "National Park",
        "#ffff00",
        ["S4_NATIONAL_PARK", "S9_2_LAND_HELD_FOR_NATIONAL_PARK_PURPOSES"],
    ),
    ("Conservation Park", "#38a800", ["S19_CONSERVATION_PARK"]),
    (
        "Specially Protected Area",
        "#b2b2b2",
        [
            "S21_ECOLOGICAL_AREA",
            "S23A_AMENITY_AREA",
            "S22_SANCTUARY_AREA",
            "S14A_WILDLIFE_MANAGEMENT_RESERVE",
            "20_WILDERNESS_AREA",
        ],
    ),
    ("Conservation Area", "#eba554", ["S7_CONSERVATION_PURPOSES"]),
    (
        "Reserve",
        "#73b2ff",
        [
            "17_RECREATION_RESERVE",
            "S18_HISTORIC_RESERVE",
            "S19_1_B_SCENIC_RESERVE",
            "S21_SCIENTIFIC_RESERVE",
            "S20_NATURE_RESERVE",
            "S19_1_A_SCENIC_RESERVE",
            "S22_GOVERNMENT_PURPOSE_RESERVE",
            "S23_LOCAL_PURPOSE_RESERVE",
        ],
    ),
    ("Stewardship Area", "#55ff00", ["S25_STEWARDSHIP_AREA"]),
    (
        "Marginal Strip",
        "#895a44",
        ["S24_3_FIXED_MARGINAL_STRIP", "S24_1_2_MOVEABLE_MARGINAL_STRIP"],
    ),
    ("Wildlife Management Area", "#ff0000", ["S23B_WILDLIFE_MANAGEMENT_AREA"]),
    ("Waitangi Endowment Forest", "#aa66cd", ["S2_WAITANGI_ENDOWMENT_FOREST"]),
]
# Sections DOC adds later, which its renderer doesn't classify either.
CONS_LAND_UNCLASSIFIED = ("Other", "#ffffff")
CONS_LAND_OUTLINE = "#6e6e6e"


def _cons_land_fill_color():
    expression = ["match", ["get", "section"]]
    for _label, colour, sections in CONS_LAND_CLASSES:
        expression += [sections, colour]
    return expression + [CONS_LAND_UNCLASSIFIED[1]]


def _cons_land_legend():
    swatch = (
        '<div style="display: flex; align-items: center; gap: 6px; margin: 2px 0;">'
        '<span style="display: inline-block; width: 14px; height: 10px; '
        f'background: {{colour}}; border: 1px solid {CONS_LAND_OUTLINE};"></span>'
        "{label}</div>"
    )
    entries = [(label, colour) for label, colour, _sections in CONS_LAND_CLASSES]
    entries.append(CONS_LAND_UNCLASSIFIED)
    return "".join(
        swatch.format(label=label, colour=colour) for label, colour in entries
    )


def _cons_land():
    # NAPALIS_ProtectedArea_PublicConservationLand layer 0: ~11k features
    # against a maxRecordCount of 1000, with very dense geometry that
    # simplifies well. Simplified to zoom 6 the whole layer is ~10 MB, so 12
    # pages lets a national view load untruncated.
    fields = "objectid,type,section,napalis_id,name,recorded_area"
    return Overlay(
        slug="cons_land",
        layer_id=uuid.UUID("a7d0e8b1-3000-4001-8000-000000000002"),
        name="Public Conservation Land",
        sortorder=20,
        icon="fa fa-tree",
        available=_portal_available("cons_land"),
        source=_bbox_fetch_source(),
        layers=_polygon_layers(
            "cons_land",
            {
                "fill-color": _cons_land_fill_color(),
                # DOC's pale yellows and blues wash out much below 0.35.
                "fill-opacity": _hover(0.6, 0.35),
            },
            {
                "line-color": _hover("#1f2937", CONS_LAND_OUTLINE),
                "line-width": _hover(2, 1),
            },
            {
                **_popup(
                    "name",
                    [
                        ["Type", "type"],
                        ["Section", "section"],
                        ["NaPALIS ID", "napalis_id"],
                        ["Name", "name"],
                        ["Recorded Area (ha)", "recorded_area"],
                    ],
                ),
                **_bbox_fetch(
                    "cons_land", 0, minzoom=6, maxpages=12, out_fields=fields
                ),
            },
        ),
        legend=_cons_land_legend(),
    )


# --- DOC operations regions and districts -------------------------------------


def _ops_regions():
    # DOC_OperationsRegions_HFLr layer 0: 11 features, one request.
    return Overlay(
        slug="ops_regions",
        layer_id=uuid.UUID("a7d0e8b1-3000-4001-8000-000000000003"),
        name="DOC Operations Regions",
        sortorder=30,
        icon="fa fa-map",
        available=_portal_available("ops_regions"),
        source=_portal_source("ops_regions", 0),
        layers=_polygon_layers(
            "ops_regions",
            {"fill-color": "#3b82f6", "fill-opacity": _hover(0.35, 0.15)},
            {
                "line-color": _hover("#172554", "#1d4ed8"),
                "line-width": _hover(2.4, 1.2),
            },
            _popup("regionname", [["Region", "regionname"], ["Code", "regioncode"]]),
        ),
    )


def _ops_districts():
    # DOC_OperationsDistricts_HFLr layer 1: 46 features, one request.
    return Overlay(
        slug="ops_districts",
        layer_id=uuid.UUID("a7d0e8b1-3000-4001-8000-000000000004"),
        name="DOC Operations Districts",
        sortorder=40,
        icon="fa fa-map-signs",
        available=_portal_available("ops_districts"),
        source=_portal_source("ops_districts", 1),
        layers=_polygon_layers(
            "ops_districts",
            {"fill-color": "#f97316", "fill-opacity": _hover(0.35, 0.15)},
            {
                "line-color": _hover("#7c2d12", "#c2410c"),
                "line-width": _hover(2, 0.7),
            },
            _popup(
                "districtname",
                [
                    ["District Name", "districtname"],
                    ["District Code", "districtcode"],
                    ["Region Name", "regionname"],
                    ["Region Code", "regioncode"],
                ],
            ),
        ),
    )


# --- LINZ basemaps ------------------------------------------------------------
# Public XYZ rasters behind a referer-restricted API key.


def _aerial():
    return Overlay(
        slug="aerial",
        layer_id=uuid.UUID("a7d0e8b1-3000-4001-8000-000000000005"),
        name="Aerial Photos (LINZ)",
        sortorder=50,
        icon="fa fa-camera",
        available=bool(settings.LINZ_BASEMAPS_API_KEY),
        source={
            "type": "raster",
            "tiles": [_linz_tiles("aerial/EPSG:3857")],
            "tileSize": 256,
        },
        layers=[{"id": "aerial", "source": "aerial", "type": "raster"}],
    )


def _topo():
    # topo-raster-gridded is the raster form of LINZ's vector-only
    # `topographic` style; WebMercatorQuad is LINZ's name for EPSG:3857. Not
    # the Eagle-hosted ArcGIS MapServer: it publishes in NZTM2000 (wkid 2193),
    # which Mapbox GL can't render.
    return Overlay(
        slug="topo",
        layer_id=uuid.UUID("a7d0e8b1-3000-4001-8000-000000000006"),
        name="LINZ Topo",
        sortorder=60,
        icon="fa fa-mountain",
        available=bool(settings.LINZ_BASEMAPS_API_KEY),
        source={
            "type": "raster",
            "tiles": [_linz_tiles("topo-raster-gridded/WebMercatorQuad")],
            "tileSize": 256,
        },
        layers=[{"id": "topo", "source": "topo", "type": "raster"}],
    )


def overlays():
    """Every overlay, built from the current settings."""
    return [
        _nzaa(),
        _nzaa_buff(),
        _cons_land(),
        _ops_regions(),
        _ops_districts(),
        _aerial(),
        _topo(),
    ]
