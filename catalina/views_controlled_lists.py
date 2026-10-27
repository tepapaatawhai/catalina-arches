"""Controlled list views that replace arches_controlled_lists ones.

FilteredListView backs the list manager's "Find" box when nothing in the
already-loaded tree matches. Upstream has two problems here:

* It serializes the list in nested mode unless ?flat=true is passed, and the
  frontend never passes it, so only root items reach the term filter and
  anything below a root can never be found.
* Even in flat mode it serializes every item of the list (thousands for the FISH
  thesauri) just to keep the few that match.

This version finds the matching items in SQL, walks up their ancestors a level
at a time, and serializes only the matches. The frontend reads just the item ids
and their ancestor ids, which are returned in the same shape as upstream.

The frontend also asks one list at a time, in sequence, which is hundreds of
round trips. FilteredListsView answers for every list in one request; the
project's api.ts override uses it. Remove both once upstream does it itself.
"""

from collections import defaultdict
from http import HTTPStatus

from arches.app.utils.response import JSONErrorResponse, JSONResponse
from arches.app.views.api import APIBase
from arches_controlled_lists.models import List, ListItem
from arches_controlled_lists.views import FilteredListView as UpstreamFilteredListView


def _pref_label(item, lang):
    labels = [
        value
        for value in item.list_item_values.all()
        if value.valuetype_id == "prefLabel"
    ]
    for label in labels:
        if label.language_id == lang:
            return label.value
    return labels[0].value if labels else ""


def _list_data(lst, items):
    return {
        "id": str(lst.id),
        "name": lst.name,
        "dynamic": lst.dynamic,
        "searchable": lst.searchable,
        "items": items,
    }


def _search_items(term, lang, list_id=None):
    """Return {list_id: [serialized matching items]} for items whose prefLabel
    contains term, hierarchically ordered, restricted to one list if given."""
    matches_query = ListItem.objects.filter(
        list_item_values__valuetype_id="prefLabel",
        list_item_values__value__icontains=term,
    )
    if list_id is not None:
        matches_query = matches_query.filter(list_id=list_id)
    matches = list(
        matches_query.exclude(guide=True)
        .distinct()
        .prefetch_related("list_item_values", "list_item_images")
    )

    by_id = {item.pk: item for item in matches}
    frontier = {item.parent_id for item in matches if item.parent_id}
    while frontier := frontier - by_id.keys():
        ancestors = ListItem.objects.filter(pk__in=frontier).prefetch_related(
            "list_item_values"
        )
        by_id.update({ancestor.pk: ancestor for ancestor in ancestors})
        frontier = {a.parent_id for a in ancestors if a.parent_id}

    def ancestor_chain(item):
        """Ancestors ordered root to immediate parent."""
        chain = []
        seen = {item.pk}
        parent = by_id.get(item.parent_id)
        while parent is not None and parent.pk not in seen:
            chain.append(parent)
            seen.add(parent.pk)
            parent = by_id.get(parent.parent_id)
        return chain[::-1]

    rows = defaultdict(list)
    for item in matches:
        chain = ancestor_chain(item)
        serialized = item.serialize(flat=True)
        serialized["depth"] = len(chain)
        serialized["parent_path"] = " > ".join(
            _pref_label(ancestor, lang) for ancestor in chain
        )
        serialized["parent_ids"] = [str(ancestor.pk) for ancestor in chain]
        sort_key = tuple(node.sortorder for node in [*chain, item])
        rows[item.list_id].append((sort_key, serialized))

    return {
        list_pk: [serialized for _, serialized in sorted(list_rows, key=lambda r: r[0])]
        for list_pk, list_rows in rows.items()
    }


class FilteredListView(UpstreamFilteredListView):
    def get(self, request, list_id):
        term = request.GET.get("term", "").strip()
        if not term:
            return super().get(request, list_id)

        try:
            lst = List.objects.get(pk=list_id)
        except List.DoesNotExist:
            return JSONErrorResponse(status=HTTPStatus.NOT_FOUND)

        items = _search_items(term, request.LANGUAGE_CODE, list_id=list_id)
        return JSONResponse(_list_data(lst, items.get(lst.pk, [])))


class FilteredListsView(APIBase):
    def get(self, request):
        """Same per-list payload as FilteredListView, for every list with a
        match, keyed by list id: {"lists": {list_id: {..., "items": [...]}}}."""
        term = request.GET.get("term", "").strip()
        if not term:
            return JSONResponse({"lists": {}})

        items = _search_items(term, request.LANGUAGE_CODE)
        lists = List.objects.filter(pk__in=items.keys())
        return JSONResponse(
            {"lists": {str(lst.pk): _list_data(lst, items[lst.pk]) for lst in lists}}
        )
