import ko from 'knockout';
import corePopupTemplate from 'templates/views/components/map-popup.htm';
import overlayPopupTemplate from 'templates/views/components/external-overlay-popup.htm';

/**
 * Project override of the core map popup provider
 * (arches/app/media/js/utils/map-popup-provider.js).
 *
 * Webpack resolves `utils/map-popup-provider` to this file because project
 * entry points override core ones at the same relative path
 * (see catalina/webpack/webpack.common.js). 
 *
 * What it adds over core:
 *   - external vector overlays become clickable + hover-highlightable, not just Arches
 *     resource features;
 *   - clicked overlay features render an attribute table instead of the
 *     resource summary/report/edit chrome.
 *
 * Per-overlay popup config is NOT hardcoded here. It lives on each map layer
 * as Mapbox `metadata["arches:popup"]`, set in the overlay-loading migration
 * (catalina/overlays/registry.py), shape:
 *     { "title": "<property name used as the popup heading>",
 *       "fields": [["<label>", "<property name>"], ...] }
 */

// Synchronous fetch, matching core's getPopupTemplate.
function fetchTemplate(url) {
    const request = new XMLHttpRequest();
    request.open('GET', url, false);
    request.send();
    return request.responseText;
}

// Return the `arches:popup` config for a feature, or null if the feature's
// source has none. Matched by source (not layer id) so the config can live on
// a single layer of the overlay (e.g. the fill) and still resolve when the
// click/hover lands on a sibling layer (e.g. the outline).
function popupConfigForFeature(maplibreMap, feature) {
    const style = maplibreMap && maplibreMap.getStyle();
    if (!style || !feature) return null;
    for (const layer of style.layers) {
        if (layer.source === feature.source && layer.metadata && layer.metadata['arches:popup']) {
            return layer.metadata['arches:popup'];
        }
    }
    return null;
}

// Mapbox GL stringifies non-primitive property values when it serialises
// GeoJSON in its worker, so a null attribute arrives here as the string "null".
function isEmptyValue(value) {
    return value === undefined || value === null || value === '' || value === 'null';
}

const provider = {
    isFeatureClickable: function(feature, map) {
        // core: disabled while a draw tool or feature selection is active
        const selectedFeatureIds = ko.unwrap(map.selectedFeatureIds);
        const selectedTool = ko.unwrap(map.selectedTool);
        if ((typeof selectedTool !== 'undefined' && selectedTool !== null) || selectedFeatureIds && selectedFeatureIds.length)
            return false;
        // core: Arches resource features
        if (feature.properties.resourceinstanceid) return true;
        // added: external overlays that declare popup config
        return !!popupConfigForFeature(map.map(), feature);
    },

    getPopupTemplate: function(features) {
        // Use the overlay template only when every hit feature is a non-resource
        // overlay; if a resource feature is in the stack, fall back to core so
        // its report/edit links are preserved.
        const allOverlay = features.length > 0
            && features.every(feature => !feature.properties.resourceinstanceid);
        return fetchTemplate(allOverlay ? overlayPopupTemplate : corePopupTemplate);
    },

    processData: function(popupData) {
        (popupData.popupFeatures || []).forEach(popupFeature => {
            // Leave Arches resource features to core's resourceLookup flow.
            if (ko.unwrap(popupFeature.resourceinstanceid)) return;

            const map = popupFeature.mapCard && popupFeature.mapCard.map();
            const config = popupConfigForFeature(map, popupFeature.feature);
            if (!config) return;

            const properties = popupFeature.feature.properties || {};
            const title = properties[config.title];
            popupFeature.displayname = ko.observable(isEmptyValue(title) ? '' : title);
            // Every configured field gets a row, with a dash when unpopulated, so
            // an empty value reads as missing data rather than a missing field.
            popupFeature.attributes = (config.fields || [])
                .map(([label, key]) => ({
                    label: label,
                    value: isEmptyValue(properties[key]) ? '—' : String(properties[key]),
                }));
        });
        return popupData;
    },

    // --- unchanged from core (map.js binds these unconditionally) ---

    sendFeatureToMapFilter: function(popupFeatureObject) {
        const foundFeature = this.findPopupFeatureById(popupFeatureObject);
        popupFeatureObject.mapCard.filterByFeatureGeom(foundFeature);
    },

    showFilterByFeature: function(popupFeatureObject) {
        const noFeatureId = popupFeatureObject.feature?.properties?.featureid === undefined;
        if (noFeatureId)
            return false;
        return this.findPopupFeatureById(popupFeatureObject) !== null;
    },

    findPopupFeatureById: function(popupFeatureObject) {
        let foundFeature = null;
        const strippedFeatureId = popupFeatureObject.feature.properties.featureid.replace(/-/g, "");
        for (let geometry of popupFeatureObject.geometries()) {
            if (geometry.geom && Array.isArray(geometry.geom.features)) {
                foundFeature = geometry.geom.features.find(feature => feature.id.replace(/-/g, "") === strippedFeatureId);
                if (foundFeature)
                    break;
            }
        }
        return foundFeature;
    },
};

export default provider;