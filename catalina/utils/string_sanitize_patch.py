"""Sanitise string-node HTML on save (pentest finding WA05, stored XSS).

Arches stores whatever a user types into a string node verbatim and several
screens later render it as HTML (rich-text report sections, and resource names
in the resource editor's drop-downs), so ``<img src=x onerror=...>`` saved by
one user runs in the browser of everyone who views it.

``StringDataType.clean`` runs on every tile before it is saved, so it is
wrapped here:

* nodes using the rich text (CKEditor) widget keep a small allow-list of
  formatting tags; scripts, event handlers, ``javascript:`` links and the rest
  are removed.
* every other string node is plain text, so all tags are stripped.

Remove this if Arches sanitises string values itself.

Data saved before this patch is not touched; see the
``sanitize_string_tiles`` management command.
"""

import logging

logger = logging.getLogger(__name__)

RICH_TEXT_WIDGET = "rich-text-widget"

RICH_TEXT_TAGS = {
    "a", "b", "blockquote", "br", "caption", "code", "div", "em", "h1", "h2",
    "h3", "h4", "h5", "h6", "hr", "i", "li", "ol", "p", "pre", "s", "span",
    "strike", "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th",
    "thead", "tr", "u", "ul",
}  # fmt: skip
RICH_TEXT_ATTRIBUTES = {
    "a": {"href", "title", "target"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "*": {"class"},
}
URL_SCHEMES = {"http", "https", "mailto", "tel"}


def sanitize_rich_text(value):
    import nh3

    return nh3.clean(
        value,
        tags=RICH_TEXT_TAGS,
        attributes=RICH_TEXT_ATTRIBUTES,
        url_schemes=URL_SCHEMES,
    )


def sanitize_plain_text(value):
    """Strip every tag. nh3 escapes ``&``, which plain-text nodes must keep."""
    import nh3

    return nh3.clean(value, tags=set(), attributes={}).replace("&amp;", "&")


_rich_node_cache = {}


def is_rich_text_node(nodeid):
    nodeid = str(nodeid)
    if nodeid not in _rich_node_cache:
        from arches.app.models.models import CardXNodeXWidget

        _rich_node_cache[nodeid] = CardXNodeXWidget.objects.filter(
            node_id=nodeid, widget__name=RICH_TEXT_WIDGET
        ).exists()
    return _rich_node_cache[nodeid]


def sanitize_node_value(value, rich):
    """Sanitise an i18n string value: ``{"en": {"value": "...", ...}, ...}``."""
    if not isinstance(value, dict):
        return value
    clean = sanitize_rich_text if rich else sanitize_plain_text
    for language_value in value.values():
        if isinstance(language_value, dict) and isinstance(
            language_value.get("value"), str
        ):
            language_value["value"] = clean(language_value["value"])
    return value


def apply():
    from arches.app.datatypes.datatypes import StringDataType

    if getattr(StringDataType, "_catalina_sanitize_patched", False):
        return

    original_clean = StringDataType.clean

    def clean(self, tile, nodeid):
        value = tile.data.get(nodeid)
        if isinstance(value, dict):
            sanitize_node_value(value, is_rich_text_node(nodeid))
        original_clean(self, tile, nodeid)

    StringDataType.clean = clean
    StringDataType._catalina_sanitize_patched = True
    logger.debug("Applied string sanitise patch")
