import arches from 'arches';

/**
 * Project override of the core map configurator
 * (arches/app/media/js/utils/map-configurator.js), whose postConfig core's
 * map viewmodel calls at the end of every map's load handler.
 *
 * What it adds over core:
 *   - GeoJSON overlays too large for one request are fetched per map view:
 *     each moveend (and each overlay toggle) queries the ArcGIS proxy for the
 *     features intersecting the current bounds, simplified to the current
 *     pixel size, then setData()s the source.
 *
 * To trace fetches in the console:
 *     localStorage.setItem('catalina:overlay-debug', '1')
 *
 * Opt-in lives on one of the overlay's map layers as Mapbox
 * `metadata["arches:bbox-fetch"]`, set in catalina/overlays/registry.py, shape:
 *     { "url": "/overlays/<slug>/<layer index>/query",
 *       "minzoom": <below this the source is emptied and nothing is fetched>,
 *       "maxpages": <optional, pages of maxRecordCount to follow; default 5>,
 *       "outFields": <optional, comma-separated; default "*"> }
 * The source itself starts as an empty FeatureCollection so nothing downloads
 * until the overlay is switched on.
 */

const DEFAULT_MAXPAGES = 5;
const MAX_PARALLEL = 6;
const DEBOUNCE_MS = 250;
const EMPTY = { type: 'FeatureCollection', features: [] };
const DEBUG_KEY = 'catalina:overlay-debug';

function debugEnabled() {
    try {
        return window.localStorage.getItem(DEBUG_KEY) === '1';
    } catch (e) {
        return false;
    }
}

function debugLog(sourceId, ...args) {
    if (debugEnabled()) console.log(`[overlay ${sourceId}]`, ...args);
}

// Degrees of longitude per screen pixel at the map's zoom (512px tiles).
function pixelDegrees(map) {
    return Number((360 / (512 * Math.pow(2, map.getZoom()))).toPrecision(3));
}

// Map each source id to the bbox-fetch config of a layer currently in the
// style. Inactive overlays have no layers in the style, so they're skipped.
function activeFetchConfigs(map) {
    const style = map.getStyle();
    const configs = new Map();
    if (!style) return configs;
    for (const layer of style.layers) {
        const config = layer.metadata && layer.metadata['arches:bbox-fetch'];
        if (config && !configs.has(layer.source)) configs.set(layer.source, config);
    }
    return configs;
}

// Same root-relative URL handling core applies to source `data` strings.
function absoluteUrl(url) {
    return url.startsWith('/') ? arches.urls.root + url.substr(1) : url;
}

function boundsParam(map) {
    const bounds = map.getBounds();
    const clampLng = lng => Math.max(-180, Math.min(180, lng));
    return [
        clampLng(bounds.getWest()),
        bounds.getSouth(),
        clampLng(bounds.getEast()),
        bounds.getNorth(),
    ].map(value => value.toFixed(5)).join(',');
}

// ArcGIS caps each response at the service's maxRecordCount, so a busy view
// takes several resultOffset pages. The first page and the view's total count
// are requested together; the first page's length is the page size, and the
// remaining pages then go out in parallel, at most MAX_PARALLEL at a time to
// spare the portal.
async function fetchFeatures(config, bbox, idField, simplifyDegrees, signal, log) {
    const filter = {
        where: '1=1',
        geometry: bbox,
        geometryType: 'esriGeometryEnvelope',
        inSR: '4326',
        spatialRel: 'esriSpatialRelIntersects',
    };
    const pageParams = function(offset) {
        const params = new URLSearchParams({
            ...filter,
            outSR: '4326',
            outFields: config.outFields || '*',
            geometryPrecision: '6',
            // Drop vertices closer together than a screen pixel; polygon
            // payloads shrink many times over at low zooms.
            maxAllowableOffset: String(simplifyDegrees),
            resultOffset: String(offset),
            f: 'geojson',
        });
        // Stable ordering so pages don't overlap or skip.
        if (idField) params.set('orderByFields', idField);
        return params;
    };
    const fetchJson = async function(params, label) {
        const started = performance.now();
        const response = await fetch(`${absoluteUrl(config.url)}?${params}`, {
            credentials: 'same-origin',
            signal: signal,
        });
        if (!response.ok) throw new Error(`${response.status} from ${config.url}`);
        const text = await response.text();
        const body = JSON.parse(text);
        // ArcGIS reports most failures as HTTP 200 with an error body.
        if (body.error) throw new Error(`${config.url}: ${JSON.stringify(body.error)}`);
        const detail = body.features ? `${body.features.length} features` : `count ${body.count}`;
        log(
            `${label}: ${detail},`,
            `${Math.round(text.length / 1024)} KB, ${Math.round(performance.now() - started)} ms`
        );
        return body;
    };

    const [firstPage, countBody] = await Promise.all([
        fetchJson(pageParams(0), 'page 0'),
        fetchJson(new URLSearchParams({ ...filter, returnCountOnly: 'true', f: 'json' }), 'count'),
    ]);
    const features = firstPage.features || [];
    const pageSize = features.length;
    const count = countBody.count || 0;
    if (!pageSize || count <= pageSize) return { features, count, truncated: false };

    const maxpages = config.maxpages || DEFAULT_MAXPAGES;
    const pages = Math.min(maxpages, Math.ceil(count / pageSize));
    const offsets = [];
    for (let page = 1; page < pages; page++) offsets.push(page * pageSize);

    // A pool of workers, each taking the next offset until none are left.
    const bodies = new Array(offsets.length);
    let next = 0;
    const worker = async function() {
        while (next < offsets.length) {
            const index = next++;
            bodies[index] = await fetchJson(pageParams(offsets[index]), `page ${index + 1}`);
        }
    };
    await Promise.all(Array.from({ length: Math.min(MAX_PARALLEL, offsets.length) }, worker));
    bodies.forEach(body => features.push(...(body.features || [])));
    return { features, count, truncated: count > pages * pageSize };
}

function setupBboxFetch(map) {
    // Per source: the view last loaded into it, and the request in flight.
    const loadedView = new Map();
    const inFlight = new Map();
    let timer = null;

    const refresh = function() {
        const configs = activeFetchConfigs(map);
        const bbox = boundsParam(map);
        const zoom = map.getZoom();

        configs.forEach(function(config, sourceId) {
            const source = map.getSource(sourceId);
            if (!source) return;

            const log = (...args) => debugLog(sourceId, ...args);
            const view = zoom < config.minzoom ? 'below-minzoom' : bbox;
            if (loadedView.get(sourceId) === view) return;

            if (inFlight.has(sourceId)) {
                inFlight.get(sourceId).abort();
                log('cancelled the in-flight fetch for the previous view');
            }
            inFlight.delete(sourceId);

            if (view === 'below-minzoom') {
                source.setData(EMPTY);
                loadedView.set(sourceId, view);
                log(`zoom ${zoom.toFixed(2)} is below minzoom ${config.minzoom}; cleared`);
                return;
            }

            const controller = new AbortController();
            inFlight.set(sourceId, controller);
            const idField = map.getStyle().sources[sourceId].promoteId;
            const simplifyDegrees = pixelDegrees(map);
            const started = performance.now();
            log(`fetching at zoom ${zoom.toFixed(2)}, bbox ${bbox}, simplify ${simplifyDegrees}°`);

            fetchFeatures(config, bbox, idField, simplifyDegrees, controller.signal, log)
                .then(function(result) {
                    if (result.truncated) {
                        console.warn(
                            `Overlay ${sourceId}: view exceeds ${config.maxpages || DEFAULT_MAXPAGES} pages; showing a partial set.`
                        );
                    }
                    // Re-fetch the source: a style rebuild may have replaced it.
                    const current = map.getSource(sourceId);
                    if (current) current.setData({ type: 'FeatureCollection', features: result.features });
                    loadedView.set(sourceId, view);
                    log(
                        `done: ${result.features.length} of ${result.count} features in`,
                        `${Math.round(performance.now() - started)} ms${result.truncated ? ' (truncated)' : ''}`
                    );
                })
                .catch(function(error) {
                    if (error.name !== 'AbortError') console.error(`Overlay ${sourceId}:`, error);
                })
                .finally(function() {
                    if (inFlight.get(sourceId) === controller) inFlight.delete(sourceId);
                });
        });
    };

    const scheduleRefresh = function() {
        clearTimeout(timer);
        timer = setTimeout(refresh, DEBOUNCE_MS);
    };

    map.on('moveend', scheduleRefresh);
    // Toggling an overlay rebuilds the style (core's updateLayers), which is
    // when a newly activated overlay needs its first fetch.
    map.on('styledata', scheduleRefresh);
    scheduleRefresh();
}

const mapConfigurator = {
    preConfig: function(map) {
        // This can be used to configure the map at the beginning of the map.on('load') event
    },
    postConfig: function(map) {
        setupBboxFetch(map);
    },
};

export default mapConfigurator;
