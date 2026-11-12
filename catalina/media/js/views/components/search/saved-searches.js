import $ from 'jquery';
import ko from 'knockout';
import arches from 'arches';
import savedSearchesTemplate from 'templates/views/components/search/saved-searches.htm';
import 'bindings/smartresize';


const componentName = 'saved-searches';
const viewModel = function(params) {
    var self = this;
    self.searchFilterVms = params.searchFilterVms;

        
    self.urls = arches.urls;
    self.selectedPopup = params.selectedPopup;
    self.items = ko.observableArray([]);

    // Saved searches may lack a value for the active language (e.g. /mi/),
    // so fall back to the default language, then to any available value.
    const localizedValue = function(field) {
        if (!field) return "";
        const entry = field[arches.activeLanguage]
            || field[arches.defaultLanguage]
            || field[Object.keys(field).find(function(k) { return field[k] && field[k].value; })];
        return entry && entry.value ? entry.value : "";
    };
    $.ajax({
        type: "GET",
        url: arches.urls.api_search_component_data + componentName,
        context: this
    }).done(function(response) {
        response[componentName].forEach(function(search) {
            let searchImageUrl = arches.urls.url_subpath + ((search.IMAGE && search.IMAGE.length > 0) ? search.IMAGE[0].url : '');
            searchImageUrl = searchImageUrl.replace('//', '/');
            self.items.push({
                image: searchImageUrl,
                title: localizedValue(search.SEARCH_NAME),
                subtitle: localizedValue(search.SEARCH_DESCRIPTION),
                searchUrl: localizedValue(search.SEARCH_URL)
            });
        });
        self.searchFilterVms[componentName](self);
    });

    self.options = {
        itemSelector: '.ss-grid-item',
        masonry: {
            columnWidth: 500,
            gutterWidth: 25,
        }
    };
};

export default ko.components.register(componentName, {
    viewModel: viewModel,
    template: savedSearchesTemplate,
});
