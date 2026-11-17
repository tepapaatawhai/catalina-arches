/*
 * Catalina override of arches/app/media/js/views/components/language-switcher.js
 * (Arches 8.2.0a8). The core form posts an empty "next" (redirect_to is never
 * set), so Django redirects via the Referer and translate_url(), which resolves
 * the path using the language from the django_language cookie. When the cookie
 * and the URL prefix disagree (e.g. after following a /mi/ link while the
 * cookie says en) the match fails and the user lands back on the same language.
 * This version sends an explicit "next": the current page with its language
 * prefix swapped for the chosen language.
 */
import ko from 'knockout';
import arches from 'arches';
import languageSwitcherTemplate from 'templates/views/components/language-switcher.htm';
import Cookies from 'js-cookie';
import 'bindings/select2-query';

/**
 * Current location with the leading language segment replaced by `languageCode`.
 * A path without a known language prefix is returned unchanged.
 */
export function buildNextUrl(location, languageCode, knownCodes) {
    const segments = location.pathname.split('/');
    const known = knownCodes.map((code) => code.toLowerCase());
    if (known.includes((segments[1] || '').toLowerCase())) {
        segments[1] = languageCode;
    }
    return segments.join('/') + location.search + location.hash;
}

export default ko.components.register('views/components/language-switcher', {
    viewModel: function(params) {
        this.formid = Math.random();
        this.value = ko.observable(params.current_language);
        this.csrfToken = Cookies.get('csrftoken');
        this.value.subscribe(function(val){
            if (val) {
                const form = document.getElementById(this.formid);
                const next = form.querySelector('input[name="next"]');
                if (next) {
                    const codes = (arches.languages || []).map((language) => language.code);
                    next.value = buildNextUrl(window.location, val, codes);
                }
                form.submit();
            }
        }, this);
    },
    template: languageSwitcherTemplate,
});
