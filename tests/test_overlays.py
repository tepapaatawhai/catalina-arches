"""Tests for the overlay registry (catalina/overlays/registry.py) and apply_overlays."""

import uuid

from arches.app.models.models import MapLayer, MapSource
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from guardian.core import ObjectPermissionChecker
from guardian.shortcuts import assign_perm

from catalina.overlays.apply import apply_overlays
from catalina.overlays.registry import (
    CONS_LAND_CLASSES,
    EMPTY_FEATURE_COLLECTION,
    overlays,
)

PORTAL_SLUGS = {"nzaa", "nzaa_buff", "cons_land", "ops_regions", "ops_districts"}

# Every overlay available: a configured portal listing every slug, plus a LINZ key.
ALL_AVAILABLE = override_settings(
    ARCGIS_PORTAL_URL="https://portal.example/hosting/rest/services/Hosted",
    ARCGIS_PORTAL_USERNAME="user",
    ARCGIS_PORTAL_PASSWORD="password",
    PORTAL_OVERLAYS_AVAILABLE=PORTAL_SLUGS,
    LINZ_BASEMAPS_API_KEY="key",
)


def _without(*slugs):
    return override_settings(PORTAL_OVERLAYS_AVAILABLE=PORTAL_SLUGS - set(slugs))


def _overlay(slug):
    return next(overlay for overlay in overlays() if overlay.slug == slug)


@ALL_AVAILABLE
class RegistryDefinitionTests(SimpleTestCase):
    """Checks on the definitions themselves, the mistakes an edit is likeliest to make."""

    def test_ids_slugs_and_names_are_unique(self):
        registry = overlays()
        for attribute in ("layer_id", "slug", "name"):
            values = [getattr(overlay, attribute) for overlay in registry]
            self.assertEqual(len(values), len(set(values)), attribute)

    def test_every_overlay_is_available_with_full_settings(self):
        self.assertTrue(all(overlay.available for overlay in overlays()))

    def test_layers_draw_from_their_own_source(self):
        for overlay in overlays():
            for layer in overlay.layers:
                self.assertEqual(layer["source"], overlay.slug, layer["id"])

    def test_bbox_fetched_sources_start_empty(self):
        for overlay in overlays():
            fetched = any(
                "arches:bbox-fetch" in layer.get("metadata", {})
                for layer in overlay.layers
            )
            if fetched:
                self.assertEqual(
                    overlay.source["data"], EMPTY_FEATURE_COLLECTION, overlay.slug
                )

    def test_popup_and_promote_id_fields_are_fetched(self):
        # A popup field left out of a trimmed outFields would show "—" for every
        # feature; a missing promoteId field breaks hover.
        for overlay in overlays():
            metadata = [layer.get("metadata", {}) for layer in overlay.layers]
            fetches = [
                m["arches:bbox-fetch"] for m in metadata if "arches:bbox-fetch" in m
            ]
            if not fetches or "outFields" not in fetches[0]:
                continue
            fetched = set(fetches[0]["outFields"].split(","))
            self.assertIn(overlay.source["promoteId"], fetched, overlay.slug)
            for popup in (m["arches:popup"] for m in metadata if "arches:popup" in m):
                wanted = {popup["title"]} | {prop for _label, prop in popup["fields"]}
                self.assertLessEqual(wanted, fetched, overlay.slug)

    def test_cons_land_classifies_each_section_once(self):
        sections = [s for _label, _colour, group in CONS_LAND_CLASSES for s in group]
        self.assertEqual(len(sections), len(set(sections)))

    def test_cons_land_legend_lists_every_class(self):
        legend = _overlay("cons_land").legend
        for label, colour, _sections in CONS_LAND_CLASSES:
            self.assertIn(label, legend)
            self.assertIn(colour, legend)


@ALL_AVAILABLE
class ApplyOverlaysTests(TestCase):
    def _owned_rows(self):
        registry = overlays()
        layers = MapLayer.objects.filter(
            maplayerid__in=[overlay.layer_id for overlay in registry]
        )
        sources = MapSource.objects.filter(
            name__in=[overlay.slug for overlay in registry]
        )
        return (
            sorted(
                layers.values_list("maplayerid", "name", "layerdefinitions", "legend")
            ),
            sorted(sources.values_list("name", "source")),
        )

    def test_writes_every_available_overlay(self):
        applied, removed, failed = apply_overlays()

        self.assertEqual(set(applied), {overlay.slug for overlay in overlays()})
        self.assertEqual(failed, [])
        for overlay in overlays():
            layer = MapLayer.objects.get(maplayerid=overlay.layer_id)
            self.assertEqual(layer.name, overlay.name)
            self.assertEqual(layer.layerdefinitions, overlay.layers)
            self.assertTrue(layer.ispublic)
            self.assertEqual(
                MapSource.objects.get(name=overlay.slug).source, overlay.source
            )

    def test_applying_twice_changes_nothing(self):
        apply_overlays()
        first = self._owned_rows()
        apply_overlays()
        self.assertEqual(self._owned_rows(), first)

    def test_rewrites_edits_to_owned_rows(self):
        apply_overlays()
        layer_id = _overlay("ops_regions").layer_id
        MapLayer.objects.filter(maplayerid=layer_id).update(
            layerdefinitions=[], legend="edited in the UI"
        )

        apply_overlays()

        layer = MapLayer.objects.get(maplayerid=layer_id)
        self.assertEqual(layer.layerdefinitions, _overlay("ops_regions").layers)
        self.assertIsNone(layer.legend)

    def test_leaves_layers_it_does_not_define_alone(self):
        other_source = MapSource.objects.create(
            name="other", source={"type": "geojson"}
        )
        other_layer = MapLayer.objects.create(
            maplayerid=uuid.uuid4(),
            name="Configured in the UI",
            layerdefinitions=[{"id": "other", "source": "other", "type": "fill"}],
            isoverlay=True,
            icon="fa fa-map",
            ispublic=False,
        )

        apply_overlays()

        other_layer.refresh_from_db()
        other_source.refresh_from_db()
        self.assertEqual(other_layer.name, "Configured in the UI")
        self.assertFalse(other_layer.ispublic)
        self.assertEqual(other_source.source, {"type": "geojson"})

    def test_removes_an_overlay_its_env_no_longer_lists(self):
        apply_overlays()

        with _without("nzaa"):
            applied, removed, failed = apply_overlays()

        self.assertEqual(removed, ["nzaa"])
        self.assertNotIn("nzaa", applied)
        self.assertFalse(
            MapLayer.objects.filter(maplayerid=_overlay("nzaa").layer_id).exists()
        )
        self.assertFalse(MapSource.objects.filter(name="nzaa").exists())
        self.assertTrue(MapSource.objects.filter(name="nzaa_buff").exists())

    def test_permissions_reattach_when_an_overlay_returns(self):
        apply_overlays()
        layer_id = _overlay("nzaa").layer_id
        user = User.objects.create(username="overlay-tester")
        assign_perm("read_maplayer", user, MapLayer.objects.get(maplayerid=layer_id))

        with _without("nzaa"):
            apply_overlays()
        apply_overlays()

        layer = MapLayer.objects.get(maplayerid=layer_id)
        self.assertIn("read_maplayer", ObjectPermissionChecker(user).get_perms(layer))

    def test_skips_an_overlay_whose_name_is_taken(self):
        with _without("nzaa"):
            apply_overlays()
        MapLayer.objects.create(
            maplayerid=uuid.uuid4(),
            name=_overlay("nzaa").name,
            layerdefinitions=[],
            isoverlay=True,
            icon="fa fa-map",
        )

        applied, removed, failed = apply_overlays()

        self.assertEqual(failed, ["nzaa"])
        self.assertIn("nzaa_buff", applied)
