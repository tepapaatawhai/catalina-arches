import uuid
from arches.app.functions.base import BaseFunction
from arches.app.models import models
from arches.app.models.tile import Tile
from arches.app.models.resource import Resource
from django.contrib.gis.geos import GEOSGeometry
import json
from datetime import datetime

details = {
    "name": "GeoJSON to BNG Point",
    "type": "node",
    "description": "Pushes the geometry from a GeoJSON node's centroid to a related BNG Point node",
    "defaultconfig": {
        "geojson_input_node": "",
        "bng_output_node": "",
        "geojson_input_nodegroup": "",
        "bng_output_nodegroup": "",
        "triggering_nodegroups": [],
    },
    "classname": "GeoJSONToBNGPoint",
    "component": "views/components/functions/geojson-to-bngpoint-function",
    "functionid": "d9a01773-6092-4cad-b331-ae725ae8fa88",
}


class GeoJSONToBNGPoint(BaseFunction):
    def get(self):
        raise NotImplementedError

    def save_bngpoint(self, tile, request, is_function_save_method=True):
        """Finds the NZTM value for the centroid of the envelope(extent) of the Geometry,
        and saves that value to the bng_output_nodegroup of the tile.

        Args:
            self: GeoJSONToBNGPoint object.

            tile: Tile to attach / amend bng_output_nodegroup of.

            request: WSGI Request used to varify call is result of user action. N.B. Function Returns if empty.

            is_function_save_method: a bool stating whether the function calling it is the save function.
        """

        # First let's check if this call is as a result of an inbound request (user action) or
        # as a result of the complementary BNGPointToGeoJSON function saving a new GeoJson.
        if request is None and is_function_save_method == True:
            return

        srid_LatLong = 4326
        srid_Nztm = 2193

        geojsonnode = self.config["geojson_input_node"]
        bngnode = self.config["bng_output_node"]

        geojsonValue = tile.data[geojsonnode]

        if geojsonValue != None:

            # Grab a copy of the Geometry collection.
            geoJsFeatures = geojsonValue["features"]

            # Get the first feature as a GeosGeometry.
            geosGeom_union = GEOSGeometry(json.dumps(geoJsFeatures[0]["geometry"]))

            # update list.
            geoJsFeatures = geoJsFeatures[1:]

            # loop through list of geoJsFeatures.
            for item in geoJsFeatures:
                # .union seems to generate 'GEOS_ERROR: IllegalArgumentException:'
                # exceptions, but they seem spurious and are automatically ignored.
                geosGeom_union = geosGeom_union.union(
                    GEOSGeometry(json.dumps(item["geometry"]))
                )

            # find the centroid of the envelope for the resultant Geometry Collection.
            centroidPoint = geosGeom_union.envelope.centroid

            # Explicitly declare the SRID for the current lat/long.
            centroidPoint = GEOSGeometry(centroidPoint, srid=srid_LatLong)

            # Transform to NZTM.
            centroidPoint.transform(srid_Nztm, False)

            # A location outside the NZTM extent (e.g. Great Britain) has no valid
            # reference, so skip it rather than blocking the save.
            if not (
                1000000 <= centroidPoint.coords[0] <= 2200000
                and 4700000 <= centroidPoint.coords[1] <= 6300000
            ):
                return

            # Stored as "easting,northing" in whole metres.
            gridref = "%d,%d" % (
                round(centroidPoint.coords[0]),
                round(centroidPoint.coords[1]),
            )

            if self.config["bng_output_nodegroup"] == str(tile.nodegroup_id):
                tile.data[bngnode] = gridref
            else:

                previously_saved_tiles = Tile.objects.filter(
                    nodegroup_id=self.config["bng_output_nodegroup"],
                    resourceinstance_id=tile.resourceinstance_id,
                )

                # Update pre-existing tiles, or Create new one.
                if len(previously_saved_tiles) > 0:
                    for p in previously_saved_tiles:
                        p.data[bngnode] = gridref
                        p.save()
                else:
                    new_bng_tile = Tile().get_blank_tile_from_nodegroup_id(
                        self.config["bng_output_nodegroup"],
                        resourceid=tile.resourceinstance_id,
                        parenttile=tile.parenttile,
                    )
                    new_bng_tile.data[bngnode] = gridref
                    new_bng_tile.save()

            return

        return

    def save(self, tile, request, context=None):

        self.save_bngpoint(tile=tile, request=request, is_function_save_method=True)
        return

    def post_save(self, *args, **kwargs):
        raise NotImplementedError

    def delete(self, tile, request):
        raise NotImplementedError

    def on_import(self, tile):
        self.save_bngpoint(tile=tile, request=None, is_function_save_method=False)
        return

    def after_function_save(self, tile, request):
        raise NotImplementedError
