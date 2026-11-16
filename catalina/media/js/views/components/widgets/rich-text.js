import $ from 'jquery';
import ko from 'knockout';
import koMapping from 'knockout-mapping';
import _ from 'underscore';
import WidgetViewModel from 'viewmodels/widget';
import arches from 'arches';
import richTextWidgetTemplate from 'templates/views/components/widgets/rich-text.htm';
import 'bindings/ckeditor';
import 'bindings/chosen';


/**
* registers a rich-text-widget component for use in forms
* @function external:"ko.components".rich-text-widget
* @param {object} params
* @param {string} params.value - the value being managed
* @param {function} params.config - observable containing config object
*/

// Catalina: data is not translatable, so these widgets always start on (and
// save to) the default language, whatever language the UI is in. The language
// selector still works for anyone who opens it.
const DATA_LANGUAGE = 'en';

const viewModel = function(params) {
    params.configKeys = ['placeholder', 'displayfullvalue'];
    const self = this;
    self.card = params.card;

    WidgetViewModel.apply(self, [params]);
    const initialCurrent = {};
    self.showi18nOptions = ko.observable(false);
    initialCurrent[DATA_LANGUAGE] = {value: '', direction: 'ltr'};
    const currentLanguage = {"code": DATA_LANGUAGE};
    let currentValue = koMapping.toJS(self.value) || initialCurrent;
    self.currentLanguage = ko.observable(currentLanguage);
    self.currentPlaceholder = ko.observable();
    let updating = false;

    if(self.form){
        self.form.on('tile-reset', (x) => {
            if (ko.unwrap(self.value)) {
                currentValue = koMapping.toJS(self.value);
                self.currentText(currentValue[self.currentLanguage().code]?.value);
                self.currentDirection(currentValue[self.currentLanguage().code]?.direction);
            }
        });
    }

    const languages = arches.languages;
    self.languages =  ko.observableArray(languages);
    self.currentLanguage(languages.find(element => element.code == DATA_LANGUAGE));

    if(!currentValue?.[currentLanguage.code]){
        self.currentText = ko.observable('');
        self.currentDirection = ko.observable('ltr');
        currentValue[currentLanguage.code] = {value: '', direction: 'ltr'};
    } else {
        self.currentText = ko.observable(currentValue?.[currentLanguage.code]?.value);
        self.currentDirection = ko.observable(ko.unwrap(currentValue?.[currentLanguage.code]?.direction));
    }

    if (ko.unwrap(self.placeholder)) {
        if (typeof ko.unwrap(self.placeholder) === 'string') {
            self.placeholder({
                [self.currentLanguage().code]: ko.unwrap(self.placeholder),
            });
        }
        self.currentPlaceholder(self.placeholder()[self.currentLanguage().code]);
    }

    // Catalina: when the active language has no text, expose the fallback
    // language's text so the report can show it and the editor can use it as a
    // placeholder (never as the saved value).
    const FALLBACK_LANGUAGE = 'en';
    self.fallbackLanguage = FALLBACK_LANGUAGE;
    self.fallbackText = ko.pureComputed(() => {
        const code = self.currentLanguage()?.code;
        if (!code || code === FALLBACK_LANGUAGE || self.currentText()) { return ''; }
        return koMapping.toJS(self.value)?.[FALLBACK_LANGUAGE]?.value || '';
    });
    self.fallbackPlaceholder = ko.pureComputed(() => {
        const div = document.createElement('div');
        div.innerHTML = self.fallbackText();
        return (div.textContent || '').trim();
    });

    self.defaultText = ko.observable();
    self.defaultText.subscribe(newValue => {
        const config = self.config();
        config.placeholder = newValue;
        self.config(config);
    });

    // Catalina patch: when the active language (e.g. mi) has no entry in a
    // per-language value object, the fallback is a plain object, not an
    // observable. Only subscribe to real observables.
    const valueLeaf = self.value?.[DATA_LANGUAGE]?.value || self.value;
    ko.isObservable(valueLeaf) && valueLeaf.subscribe(newValue => {
        const currentLanguage = self.currentLanguage();
        if(!currentLanguage) { return; }

        if(!updating && (JSON.stringify(currentValue) != JSON.stringify(ko.toJS(ko.unwrap(self.value))))){
            // Don't attempt to update currentText if we are in the middle of another update.
            // currentValue will already be correct, and self.value has not yet finished updating.
            // https://github.com/archesproject/arches/issues/10468
            self.currentText(newValue?.[currentLanguage.code]?.value || newValue);
        }
    });

    self.currentText.subscribe(newValue => {
        const currentLanguage = self.currentLanguage();
        if(!currentLanguage) { return; }

        updating = true;
        if(!currentValue?.[currentLanguage.code]){
            currentValue[currentLanguage.code] = {};
        }
        currentValue[currentLanguage.code].value = newValue?.[currentLanguage.code] ? newValue[currentLanguage.code]?.value : newValue;
        if (ko.isObservable(self.value)) {
            self.value(currentValue);
        } else if (ko.isObservable(self.value?.[currentLanguage.code]?.value)) {
            self.value[currentLanguage.code].value(newValue);
        }
        updating = false;
    });
    self.currentDirection.subscribe(newValue => {
        const currentLanguage = self.currentLanguage();
        if(!currentLanguage) { return; }

        updating = true;
        if(!currentValue?.[currentLanguage.code]){
            currentValue[currentLanguage.code] = {};
        }
        currentValue[currentLanguage.code].direction = newValue;

        if (ko.isObservable(self.value)) {
            self.value(currentValue);
        } else if (ko.isObservable(self.value?.[currentLanguage.code]?.direction)) {
            self.value[currentLanguage.code].direction(newValue);
        }
        updating = false;
    });

    self.currentLanguage.subscribe(() => {
        if(!self.currentLanguage()){ return; }

        const currentLanguage = self.currentLanguage();

        self.currentText(koMapping.toJS(self.value)[currentLanguage.code]?.value);
        self.currentDirection(koMapping.toJS(self.value)[currentLanguage.code]?.direction);
        self.currentPlaceholder(koMapping.toJS(self.placeholder)[currentLanguage.code]);
    });

    self.currentPlaceholder.subscribe(newValue => {
        if(!self.currentLanguage()){ return; }
        const currentLanguage = self.currentLanguage();

        if (self.card && ko.isObservable(self.placeholder)) {
            const patchedPlaceholder = self.placeholder();
            patchedPlaceholder[currentLanguage.code] = newValue;
            self.placeholder(patchedPlaceholder);
            self.card._card.valueHasMutated();
        }
    });

    this.displayfullvalue(params.displayfullvalue);
};

export default ko.components.register('rich-text-widget', {
    viewModel: viewModel,
    template: richTextWidgetTemplate,
});
