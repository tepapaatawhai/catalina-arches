import $ from 'jquery';
import _ from 'underscore';
import ko from 'knockout';
import arches from 'arches';
import mapFilterTemplate from 'templates/views/components/search/map-filter.htm';
import BaseFilter from 'views/components/search/base-filter';
import MapComponentViewModel from 'views/components/map';
import binFeatureCollection from 'views/components/widgets/map/bin-feature-collection';
import mapStyles from 'views/components/widgets/map/map-styles';
import * as turf from 'turf';
import geohash from 'geohash';
import geojsonExtent from 'geojson-extent';
import uuid from 'uuid';
import geojsonhint from 'geojsonhint';
import mapbox from 'mapbox-gl';
import mbdraw from 'mapbox-gl-draw';


// ─────────────────────────────────────────────────────────────────────────────
// CATALINA OVERRIDE of arches-core views/components/search/map-filter.js (Arches 8.1.0)
//
// This file is a verbatim copy of the core component with ONE behavioural change:
// antimeridian-aware normalisation of the bounds passed to `mapFitBounds`
// (see the two `CATALINA:` markers below). On an Arches upgrade, re-copy the core
// file and re-apply those two hunks.
//
// Problem: result sets straddling 180°E yield a bbox measured "the long way round"
// — Elasticsearch geo_bounds with wrap_longitude=false, and/or a LngLatBounds whose
// west > east. Fed straight to fitBounds, the map zooms out to (nearly) the whole
// globe. We detect the wrap, rebuild the short crossing box, and optionally clamp
// it to a configured maximum extent.
//
// NB: the `east - west > 180` test is a HEURISTIC — geo_bounds cannot tell which way
// data wraps, so a genuine non-crossing dataset spanning >180° of longitude would be
// mis-corrected. For a NZ-centred instance that assumption is safe. For full
// correctness, also pass wrap_longitude=True to GeoBoundsAgg on the backend
// (search_results.py); ES then returns west>east for crossing sets, which the
// `west > east` branch handles precisely without the heuristic.
// ─────────────────────────────────────────────────────────────────────────────

// Clamp result framing to this maximum extent, as an *unwrapped* bbox
// [west, south, east, north]. Express the eastern edge as > 180 for dateline-
// crossing regions (NZ + Chatham Is.: 170°W == 190). Set ENFORCE_MAX_EXTENT = false
// to only correct the antimeridian wrap without clamping.
// Off by default: clamping hides out-of-region results (usually bad data), and
// letting the map zoom out to them makes the problem visible to users.
const ENFORCE_MAX_EXTENT = false;
const MAX_EXTENT = [160, -55, 195, -25];  // tune to your instance's region

// Wrap a longitude into [anchor, anchor + 360).
function catalinaWrapLng(lng, anchor) {
    while (lng < anchor) { lng += 360; }
    while (lng >= anchor + 360) { lng -= 360; }
    return lng;
}

// Given a result bbox (mapbox LngLatBounds OR [[w,s],[e,n]] array) return an
// antimeridian-safe [[w,s],[e,n]] array for map.fitBounds. `east` may be > 180 by
// design — mapbox-gl renders that across the dateline correctly.
function catalinaNormalizeResultsBounds(bounds) {
    if (!bounds) { return bounds; }

    let west, south, east, north;
    if (typeof bounds.getWest === 'function') {                 // LngLatBounds
        west = bounds.getWest(); east = bounds.getEast();
        south = bounds.getSouth(); north = bounds.getNorth();
    } else if (Array.isArray(bounds) && bounds.length === 2) {  // [[w,s],[e,n]]
        west = bounds[0][0]; south = bounds[0][1];
        east = bounds[1][0]; north = bounds[1][1];
    } else {
        return bounds;  // unknown shape — leave untouched
    }
    if ([west, south, east, north].some(function(v){ return typeof v !== 'number' || isNaN(v); })) {
        return bounds;
    }

    // Antimeridian correction: a span > 180° means we were handed the inverted
    // (long-way-round) box. The intended short box crosses the dateline: start at
    // the eastern edge and unwrap the western edge past 180.
    if (east - west > 180) {
        var unwrappedWest = east;
        east = west + 360;
        west = unwrappedWest;
    } else if (west > east) {
        // Already a crossing LngLatBounds (sw.lng > ne.lng): unwrap the east edge.
        east += 360;
    }

    // Optional clamp to the configured maximum extent. Bring the result box into
    // the extent's longitudinal frame first so comparisons hold across the dateline.
    if (ENFORCE_MAX_EXTENT && MAX_EXTENT) {
        var mWest = MAX_EXTENT[0], mSouth = MAX_EXTENT[1], mEast = MAX_EXTENT[2], mNorth = MAX_EXTENT[3];
        west = catalinaWrapLng(west, mWest);
        east = catalinaWrapLng(east, mWest);
        if (east < west) { east += 360; }  // keep ordering after wrapping

        var cWest = Math.max(west, mWest);
        var cEast = Math.min(east, mEast);
        var cSouth = Math.max(south, mSouth);
        var cNorth = Math.min(north, mNorth);

        // If clamping inverts the box (results fall outside the max extent), fall
        // back to the max extent itself rather than a broken box. Use strict `<`:
        // a zero-size box (a single point: 1 result, or the drawn marker when there
        // are 0 results) is valid and must pass through so mapbox zooms to it, as
        // upstream Arches does.
        if (cEast < cWest || cNorth < cSouth) {
            cWest = mWest; cEast = mEast; cSouth = mSouth; cNorth = mNorth;
        }
        west = cWest; east = cEast; south = cSouth; north = cNorth;
    }

    return [[west, south], [east, north]];
}


var componentName = 'map-filter';
const viewModel = BaseFilter.extend({
    initialize: function(options) {
        var self = this;
            
        this.dependenciesLoaded = ko.observable(false);
        this.resultsAutoZoomEnabled = ko.observable(arches.mapFilterAutoZoom);
        this.mapFitBounds = function(bounds, options, force){
            bounds = catalinaNormalizeResultsBounds(bounds);  // CATALINA: antimeridian + max-extent
            this.lastResultsBounds = bounds;
            if(this.resultsAutoZoomEnabled() || force){
                this.map().fitBounds(bounds, options);
            }
        }

        self.mapboxgl = mapbox;
        self.MapboxDraw = mbdraw;
        self.dependenciesLoaded(true);

        options.name = "Map Filter";
        BaseFilter.prototype.initialize.call(this, options);

        options.sources = {
            "geojson-search-buffer-data": {
                "type": "geojson",
                "generateId": true,
                "data": {
                    "type": "FeatureCollection",
                    "features": []
                }
            }
        };

        options.layers = ko.observable(
            [
                {
                    "id": "geojson-search-buffer-outline-base",
                    "source": "geojson-search-buffer-data",
                    "type": "line",
                    "filter": [
                        "==", "$type", "Polygon"
                    ],
                    "layout": {
                        "line-cap": "round",
                        "line-join": "round"
                    },
                    "paint": {
                        "line-color": "#fff",
                        "line-width": 4
                    }
                },
                {
                    "id": "geojson-search-buffer-outline",
                    "source": "geojson-search-buffer-data",
                    "type": "line",
                    "filter": [
                        "==", "$type", "Polygon"
                    ],
                    "layout": {
                        "line-cap": "round",
                        "line-join": "round"
                    },
                    "paint": {
                        "line-color": "#3bb2d0",
                        "line-width": 2
                    }
                },
                {
                    "id": "geojson-search-buffer",
                    "type": "fill",
                    "layout": {
                        "visibility": "visible"
                    },
                    "paint": {
                        "fill-color": "#3bb2d0",
                        "fill-outline-color": "#3bb2d0",
                        "fill-opacity": 0.2
                    },
                    "source": "geojson-search-buffer-data"
                }
            ]
        );

        options.search = true;

        MapComponentViewModel.apply(this, [options]);

        this.updateLayers = function(layers) {
            var map = self.map();
            var style = map.getStyle();
            style.layers = self.draw ? layers.concat(self.draw.options.styles) : layers;
            map.setStyle(style);
        };

        this.searchGeometries = ko.observableArray(null);
        this.searchAggregations = ko.observable();
        this.selectedTool = ko.observable();
        this.geoJSONString = ko.observable(undefined);
        this.geoJSONErrors = ko.observableArray();
        this.pageLoaded = false;
        this.maxBuffer = 100000;
        this.maxBufferUnits = 'm';
        this.maxZoom = arches.mapDefaultMaxZoom;
        this.filter.feature_collection = ko.observable({
            "type": "FeatureCollection",
            "features": []
        });

        this.bufferUnits = [{
            name: 'meters',
            val: 'm'
        },{
            name: 'feet',
            val: 'ft'
        }];

        this.mapLinkData.subscribe(function(data) {
            this.zoomToGeoJSON(data);
        },this);

        var bins = binFeatureCollection(this.searchAggregations);

        this.geoJSONString.subscribe(function(geoJSONString) {
            this.geoJSONErrors(this.getGeoJSONErrors(geoJSONString));
            if(this.geoJSONErrors().length === 0){
                var geoJSON = JSON.parse(geoJSONString);
                // remove any extra geometries as only one geometry is allowed for search
                geoJSON.features = geoJSON.features.slice(0, 1);
                if(geoJSON.features.length > 0){
                    var extent = geojsonExtent(geoJSON);
                    var bounds = new this.mapboxgl.LngLatBounds(extent);
                    this.mapFitBounds(bounds, {
                        padding: parseInt(this.buffer(), 10)
                    });
                }
                this.searchGeometries(geoJSON.features);
                this.draw.set(geoJSON);
            }
        }, this);

        this.getGeoJSONErrors = function(geoJSONString) {
            var hint = geojsonhint.hint(geoJSONString);
            var errors = [];
            try{
                var geoJSON = JSON.parse(geoJSONString);
                if (geoJSON.features.length > 1){
                    hint.push({
                        "level": 'warning',
                        "message": 'Only one feature is allowed for search filtering.  Ignorning all all but the first feature.'
                    });
                }
                var feature = geoJSON.features[0];
                let bufferWidth;
                if (!!feature.properties && !!feature.properties.buffer){
                    var buffer = feature.properties.buffer;
                    try{
                        bufferWidth = parseInt(buffer.width, 10);
                        if(bufferWidth < 0 || bufferWidth > this.maxBuffer){
                            throw new Error('Whoops!');
                        }
                    }
                    catch {
                        hint.push({
                            "level": 'warning',
                            "message": 'Buffer must be an integer between 0 and ' + this.maxBuffer
                        });
                    }

                    try{
                        var bufferUnit = buffer.unit;
                        if(bufferUnit !== 'ft' && bufferUnit !== 'm'){
                            throw new Error('Whoops!');
                        }
                    }
                    catch {
                        hint.push({
                            "level": 'warning',
                            "message": 'Buffer unit must be either "ft" of "m"'
                        });
                    }
                }

                if (!!feature.properties && !!feature.properties.inverted){
                    var inverted = feature.properties.inverted;
                    try{
                        bufferWidth = parseInt(buffer.width, 10);
                        if(inverted !== true && inverted !== false){
                            throw new Error('Whoops!');
                        }
                    }
                    catch {
                        hint.push({
                            "level": 'warning',
                            "message": 'Property "inverted" must be the boolean "true" or "false" (no quotes)'
                        });
                    }
                }
            }finally{
                hint.forEach(function(item) {
                    if (item.level !== 'message') {
                        errors.push(item);
                    }
                });
                return errors; // eslint-disable-line no-unsafe-finally
            }
        };

        this.spatialFilterTypes = [{
            name: 'Point',
            title: 'Draw a Marker',
            class: 'leaflet-draw-draw-marker',
            icon: 'ion-location',
            drawMode: 'draw_point',
            active: ko.observable(false)
        }, {
            name: 'Line',
            title: 'Draw a Polyline',
            icon: 'ion-steam',
            class: 'leaflet-draw-draw-polyline',
            drawMode: 'draw_line_string',
            active: ko.observable(false)
        }, {
            name: 'Polygon',
            title: 'Draw a Polygon',
            icon: 'fa fa-pencil-square-o',
            class: 'leaflet-draw-draw-polygon',
            drawMode: 'draw_polygon',
            active: ko.observable(false)
        }, {
            name: 'Extent',
            title: 'Search by Map Extent',
            icon: 'fa fa-pencil-square-o',
            class: 'leaflet-draw-draw-polygon',
            drawMode: 'extent',
            active: ko.observable(false)
        }];

        this.drawModes = _.pluck(this.spatialFilterTypes, 'drawMode');

        this.selectedTool.subscribe(function(selectedDrawTool){
            if(!!selectedDrawTool){
                if(selectedDrawTool === 'extent'){
                    this.searchByExtent();
                } else {
                    this.draw.changeMode(selectedDrawTool);
                    self.map().draw_mode = selectedDrawTool;
                }
            }
        }, this);

        this.searchResults.timestamp.subscribe(function(timestamp) {
            if(this.pageLoaded) {
                this.updateResults();
            }
        }, this);

        this.filterByFeatureGeom = function(feature) {
            if (feature.geometry.type == 'Point' && this.buffer() == 0) { this.buffer(25); }
            self.searchGeometries.removeAll();
            this.draw.deleteAll();
            this.draw.set({
                "type": "FeatureCollection",
                "features": [feature]
            });
            self.searchGeometries([feature]);
            self.updateFilter();
        };

        var updateSearchResultPointLayer = function() {
            var pointSource = self.map().getSource('search-results-points');
            var agg = ko.unwrap(self.searchAggregations);
            var features = [];
            var mouseoverInstanceId = self.mouseoverInstanceId();

            if (agg) {
                _.each(agg.results, function(result) {
                    _.each(result._source.points, function(point) {
                        var feature = turf.point([point.point.lon, point.point.lat], _.extend(result._source, {
                            resourceinstanceid: result._id,
                            highlight: result._id === mouseoverInstanceId
                        }));
                        features.push(feature);
                    });
                });
            }

            var pointsFC = turf.featureCollection(features);
            pointSource.setData(pointsFC);
        };

        this.updateSearchResultsLayers = function() {
            if (self.filter.feature_collection() && self.filter.feature_collection()['features'].length > 0) {
                var geojsonFC = self.filter.feature_collection();
                var extent = geojsonExtent(geojsonFC);
                var bounds = new this.mapboxgl.LngLatBounds(extent);
                self.mapFitBounds(bounds, {
                    padding: self.buffer()
                });
            } else {
                self.fitToAggregationBounds();
            }
            var features = [];
            var agg = ko.unwrap(self.searchAggregations);
            _.each(agg.geo_aggs.grid.buckets, function(cell) {
                var pt = geohash.decode(cell.key);
                var feature = turf.point([pt.lon, pt.lat], {
                    doc_count: cell.doc_count
                });
                features.push(feature);
            });
            var pointsFC = turf.featureCollection(features);

            var aggregated = turf.collect(ko.unwrap(bins), pointsFC, 'doc_count', 'doc_count');
            _.each(aggregated.features, function(feature) {
                feature.properties.doc_count = _.reduce(feature.properties.doc_count, function(i, ii) {
                    return i + ii;
                }, 0);
            });

            var aggData = {
                points: pointsFC,
                agg: aggregated
            };

            var aggSource = self.map().getSource('search-results-hex');
            var hashSource = self.map().getSource('search-results-hashes');
            aggSource.setData(aggData.agg);
            hashSource.setData(aggData.points);
            updateSearchResultPointLayer();
        };

        this.searchFilterVms[componentName](this);
        this.map.subscribe(function(){
            this.setupDraw();
            this.restoreState();

            var filterUpdated = ko.computed(function() {
                return JSON.stringify(ko.toJS(this.filter.feature_collection())) + this.filter.inverted();
            }, this);
            filterUpdated.subscribe(function() {
                this.updateQuery();
            }, this);

            this.buffer.subscribe(function(val) {
                this.updateFilter();
            }, this);

            this.bufferUnit.subscribe(function(val) {
                this.updateFilter();
            }, this);

            this.searchAggregations.subscribe(this.updateSearchResultsLayers, this);
            if (ko.isObservable(bins)) {
                bins.subscribe(this.updateSearchResultsLayers, this);
            }
            if (this.searchAggregations()) {
                this.updateSearchResultsLayers();
            }
            this.mouseoverInstanceId.subscribe(updateSearchResultPointLayer);
        }, this);
    },

    setupDraw: function() {
        if(!this.map() || !this.dependenciesLoaded()){
            return;
        }
        var self = this;
        var modes = this.MapboxDraw.modes;
        modes.static = {
            toDisplayFeatures: function(state, geojson, display) {
                display(geojson);
            }
        };
        this.draw = new this.MapboxDraw({
            displayControlsDefault: false,
            modes: modes
        });
        this.map().addControl(this.draw);
        this.map().on('draw.create', function(e) {
            self.draw.getAll().features.forEach(function(feature){
                if(feature.id !== e.features[0].id){
                    self.draw.delete(feature.id);
                }
            });
            self.searchGeometries(e.features);
            self.updateFilter();
            self.selectedTool(undefined);
        });
        this.map().on('draw.update', function(e) {
            self.searchGeometries(e.features);
            self.updateFilter();
        });
        this.map().on("draw.modechange", function(e) {
            self.map().draw_mode = e.mode;
        });
    },

    searchByExtent: function() {
        if (_.contains(this.drawModes, this.selectedTool())) {
            this.draw.deleteAll();
        }
        var bounds = this.map().getBounds();
        var ll = bounds.getSouthWest().toArray();
        var ul = bounds.getNorthWest().toArray();
        var ur = bounds.getNorthEast().toArray();
        var lr = bounds.getSouthEast().toArray();
        var coordinates = [ll, ul, ur, lr, ll];
        var boundsFeature = {
            "type": "Feature",
            "properties": {},
            "id": uuid.generate(),
            "geometry": {
                "type": "Polygon",
                "coordinates": [coordinates]
            }
        };
        this.draw.set({
            "type": "FeatureCollection",
            "features": [boundsFeature]
        });
        this.searchGeometries([boundsFeature]);
        this.updateFilter();
        this.selectedTool(undefined);
    },

    useMaxBuffer: function(unit, buffer, maxBuffer) {
        let res = false;
        if (unit === 'ft') {
            res = (buffer * 0.3048) > maxBuffer;
        } else {
            res = buffer > maxBuffer;
        }
        return res;
    },

    updateFilter: function(){
        if (this.buffer() < 0) {
            this.buffer(0);
        }

        var useMaxBuffer = this.useMaxBuffer(this.bufferUnit(), this.buffer(), this.maxBuffer);
        if (useMaxBuffer) {
            const max = this.bufferUnit() === 'ft' ? 328084 : this.maxBuffer;
            this.buffer(max);
        }

        this.searchGeometries().forEach(function(feature){
            if(!feature.properties){
                feature.properties = {};
            }
            feature.properties.buffer = {
                "width": this.buffer(),
                "unit": this.bufferUnit()
            };
            feature.properties.inverted = this.filter.inverted();
        }, this);
        this.filter.feature_collection({
            "type": "FeatureCollection",
            "features": this.searchGeometries()
        });
    },

    editGeoJSON: function(feature) {
        var geoJSON = feature();
        var geoJSONString = JSON.stringify(geoJSON, null, 4);
        this.geoJSONString(geoJSONString);
    },

    updateGeoJSON: function() {
        if (this.geoJSONErrors().length === 0) {
            var geoJSON = JSON.parse(this.geoJSONString());
            this.draw.set(geoJSON);
            this.searchGeometries(geoJSON.features);
            geoJSON.features.forEach(function(feature){
                if(!!feature.properties && !!feature.properties.buffer){
                    this.buffer(parseInt(feature.properties.buffer.width, 10));
                    this.bufferUnit(feature.properties.buffer.unit);
                }
                if(!!feature.properties && Object.prototype.hasOwnProperty.call(feature.properties, 'inverted')){
                    this.filter.inverted(feature.properties.inverted);
                }
            }, this);
            this.selectedTool(undefined);
            this.geoJSONString(undefined);
        }
    },

    zoomToGeoJSON: function(data) {
        var mapData = data.properties.geometries.reduce(function(fc1, fc2) {
            fc1.geom.features = fc1.geom.features.concat(fc2.geom.features);
            return fc1;
        }, {
            "geom": {
                "type": "FeatureCollection",
                "features": []
            }
        });
        var bounds = new this.mapboxgl.LngLatBounds(geojsonExtent(mapData.geom));
        var maxZoom = ko.unwrap(this.maxZoom);
        this.mapFitBounds(bounds, {
            maxZoom: maxZoom > 17 ? 17 : maxZoom
        }, true);
    },

    updateQuery: function() {
        var self = this;
        var queryObj = this.query();
        if (this.filter.feature_collection().features.length > 0) {
            if (this.getFilterByType('term-filter-type').hasTag(this.type) === false) {
                this.getFilterByType('term-filter-type').addTag('Map Filter Enabled', this.name, this.filter.inverted);
            }
            this.filter.feature_collection().features[0].properties['inverted'] = this.filter.inverted();
            queryObj[componentName] = ko.toJSON(this.filter.feature_collection());
        } else {
            delete queryObj[componentName];
        }
        this.query(queryObj);
    },

    restoreState: function() {
        var query = this.query();
        var buffer = 10;
        var bufferUnit = 'm';
        var inverted = false;
        var hasSpatialFilter = false;
        if (componentName in query) {
            var mapQuery = JSON.parse(query[componentName]);
            if (mapQuery.features.length > 0) {
                hasSpatialFilter = true;
                var properties = mapQuery.features[0].properties;
                inverted = properties.inverted;
                this.filter.feature_collection(mapQuery);
                buffer = properties.buffer.width;
                bufferUnit = properties.buffer.unit;
                this.draw.set({
                    "type": "FeatureCollection",
                    "features": mapQuery.features
                });
            }
        }
        // we need to add these observables here AFTER initial values have been discovered
        // because of the race nature of these variables' subscriptions
        this.buffer = ko.observable(buffer).extend({ deferred: true });
        this.bufferUnit = ko.observable(bufferUnit).extend({ deferred: true });
        this.filter.inverted = ko.observable(inverted).extend({ deferred: true });
        if (hasSpatialFilter) {
            this.getFilterByType('term-filter-type').addTag('Map Filter Enabled', this.name, this.filter.inverted);
        }
        this.updateResults();
        this.pageLoaded = true;
    },

    updateResults: function() {
        if (!!this.searchResults.results){
            this.searchAggregations({
                results: this.searchResults.results.hits.hits,
                geo_aggs: this.searchResults.results.aggregations.geo_aggs.inner.buckets[0]
            });
            this.fitToAggregationBounds();
        }
        if(!!this.searchResults[componentName]) {
            var buffer = this.searchResults[componentName].search_buffer;
            this.map().getSource('geojson-search-buffer-data').setData(buffer);
        }
    },

    clear: function(reset_features) {
        this.filter.feature_collection({
            "type": "FeatureCollection",
            "features": []
        });
        if (this.map()) {
            this.map().getSource('geojson-search-buffer-data').setData({
                "type": "FeatureCollection",
                "features": []
            });
            this.getFilterByType('term-filter-type').removeTag('Map Filter Enabled');
            this.draw.deleteAll();
            this.searchGeometries([]);
        }
    },

    zoomToAllFeaturesHandler: function(){
        this.fitToAggregationBounds(true);
    },

    fitToAggregationBounds: function(forceFitBounds) {
        var agg = this.searchAggregations();
        var aggBounds;
        if (agg && agg.geo_aggs.bounds.bounds && this.map()) {
            aggBounds = agg.geo_aggs.bounds.bounds;
            var bounds = [
                [
                    aggBounds.top_left.lon,
                    aggBounds.bottom_right.lat
                ],
                [
                    aggBounds.bottom_right.lon,
                    aggBounds.top_left.lat
                ]
            ];
            var maxZoom = ko.unwrap(this.maxZoom);
            maxZoom = maxZoom > 17 ? 17 : maxZoom;
            forceFitBounds = forceFitBounds == undefined ? !this.pageLoaded : forceFitBounds == true;
            this.mapFitBounds(bounds, {
                padding: 45,
                maxZoom: maxZoom
            }, forceFitBounds);
        }
    },  
});

export default ko.components.register(componentName, {
    viewModel: viewModel,
    template: mapFilterTemplate,
});
