import arches from "arches";
import Cookies from "js-cookie";

import {
    makeParentMap,
    makeSortOrderMap,
} from "@/arches_controlled_lists/utils.ts";

import type {
    ControlledList,
    ControlledListItem,
    ControlledListItemImage,
    ControlledListItemImageMetadata,
    NewControlledListItem,
    NewOrExistingControlledListItemImageMetadata,
    NewValue,
    Value,
} from "@/arches_controlled_lists/types";

function getToken() {
    const token = Cookies.get("csrftoken");
    if (!token) {
        throw new Error("Missing csrftoken");
    }
    return token;
}

export const fetchLists = async () => {
    const response = await fetch(arches.urls.controlled_lists);
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const fetchListsShallow = async () => {
    const response = await fetch(
        `${arches.urls.controlled_lists}?shallow=true`,
    );
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const fetchListShallow = async (listId: string) => {
    const response = await fetch(
        `${arches.urls.controlled_list(listId)}?shallow=true`,
    );
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const fetchListEagerly = async (listId: string) => {
    const response = await fetch(arches.urls.controlled_list(listId));
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const fetchListItemChildren = async (itemId: string) => {
    const response = await fetch(
        arches.urls.controlled_list_item_children(itemId),
    );
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const fetchListItemAncestorPath = async (itemId: string) => {
    const response = await fetch(arches.urls.controlled_list_item_path(itemId));
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

// Catalina override of arches_controlled_lists/api.ts (this file shadows the
// upstream one through the "@" alias). The only change is fetchFilteredList:
// the list tree's "Find" fallback calls it once per list in sequence, which is
// hundreds of round trips. The first call for a term now fetches the matches
// for every list in one request, and the remaining calls are answered from
// that result. Falls back to the per-list request if the combined endpoint is
// unavailable. Compare with upstream when upgrading arches_controlled_lists.
const FILTERED_ALL_TTL_MS = 10000;
let filteredAll: {
    term: string;
    fetchedAt: number;
    lists: Promise<Record<string, unknown> | null>;
} | null = null;

const NIL_UUID = "00000000-0000-0000-0000-000000000000";

const fetchFilteredAll = async (term: string) => {
    try {
        // The combined route is the per-list route minus its trailing list id,
        // so it can be derived without registering a new arches.urls entry.
        const perListUrl: string =
            arches.urls.controlled_list_filtered(NIL_UUID);
        const url = new URL(
            perListUrl.replace(`/${NIL_UUID}`, ""),
            window.location.origin,
        );
        url.searchParams.set("term", term);
        const response = await fetch(url.toString());
        if (!response.ok) {
            throw new Error(`${response.status} ${response.statusText}`);
        }
        return ((await response.json()).lists ?? {}) as Record<string, unknown>;
    } catch (error) {
        console.warn(
            "Combined list search failed, searching list by list:",
            error,
        );
        return null;
    }
};

export const fetchFilteredList = async (listId: string, term: string) => {
    if (!term) {
        return fetchFilteredListOne(listId, term);
    }
    if (
        !filteredAll ||
        filteredAll.term !== term ||
        Date.now() - filteredAll.fetchedAt > FILTERED_ALL_TTL_MS
    ) {
        filteredAll = {
            term,
            fetchedAt: Date.now(),
            lists: fetchFilteredAll(term),
        };
    }
    const lists = await filteredAll.lists;
    if (!lists) {
        return fetchFilteredListOne(listId, term);
    }
    return lists[listId] ?? { id: listId, items: [] };
};

const fetchFilteredListOne = async (listId: string, term: string) => {
    const url = new URL(
        arches.urls.controlled_list_filtered(listId),
        window.location.origin,
    );
    if (term) {
        url.searchParams.set("term", term);
    }
    const response = await fetch(url.toString());
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const createList = async (name: string) => {
    const response = await fetch(arches.urls.controlled_list_add, {
        method: "POST",
        headers: { "X-CSRFToken": getToken() },
        body: JSON.stringify({ name }),
    });
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const importList = async (file: File, overwriteOption: string) => {
    const formData = new FormData();
    formData.append("skosfile", file);
    formData.append("overwrite_option", overwriteOption);
    const response = await fetch(arches.urls.controlled_list_add, {
        method: "POST",
        headers: { "X-CSRFToken": getToken() },
        body: formData,
    });
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const exportList = async (listIds: string[]) => {
    const response = await fetch(arches.urls.controlled_list_export, {
        method: "POST",
        headers: {
            "X-CSRFToken": getToken(),
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ list_ids: listIds }),
    });
    try {
        if (response.ok) {
            const blob = await response.blob();
            const disposition = response.headers.get("Content-Disposition");
            const filename = disposition
                ? disposition.split("filename=")[1].replace(/"/g, "")
                : "controlled_lists.xml";
            return { blob, filename };
        }
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const createItem = async (item: NewControlledListItem) => {
    const response = await fetch(arches.urls.controlled_list_item_add, {
        method: "POST",
        headers: { "X-CSRFToken": getToken() },
        body: JSON.stringify(item),
    });
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const patchItem = async (
    item: ControlledListItem,
    field: "uri" | "guide",
) => {
    const response = await fetch(arches.urls.controlled_list_item(item.id), {
        method: "PATCH",
        headers: { "X-CSRFToken": getToken() },
        body: JSON.stringify({ [field]: item[field] }),
    });
    if (response.ok) {
        return true;
    }
    try {
        const error = await response.json();
        throw new Error(error.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const copyItem = async (
    source_id: string,
    target_item_id: string | null,
    target_list_id: string,
    copy_children: boolean,
) => {
    const response = await fetch(
        arches.urls.controlled_list_item_copy(source_id),
        {
            method: "POST",
            headers: { "X-CSRFToken": getToken() },
            body: JSON.stringify({
                target_item_id,
                target_list_id,
                copy_children,
            }),
        },
    );
    if (response.ok) {
        return response.json();
    }
    try {
        const error = await response.json();
        throw new Error(error.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const patchList = async (
    list: ControlledList,
    field: "name" | "sortorder" | "children" | "searchable",
) => {
    let body = {};
    switch (field) {
        case "name":
            body = { name: list.name };
            break;
        case "sortorder":
            body = { sortorder_map: makeSortOrderMap(list) };
            break;
        case "children":
            // Parentage is adjusted on the children themselves.
            body = {
                parent_map: makeParentMap(list),
                sortorder_map: makeSortOrderMap(list),
            };
            break;
        case "searchable":
            body = { searchable: list.searchable };
            break;
    }

    const response = await fetch(arches.urls.controlled_list(list.id), {
        method: "PATCH",
        headers: { "X-CSRFToken": getToken() },
        body: JSON.stringify(body),
    });
    if (response.ok) {
        return true;
    }
    try {
        const error = await response.json();
        throw new Error(error.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const deleteLists = async (listIds: string[]) => {
    const promises = listIds.map((id) =>
        fetch(arches.urls.controlled_list(id), {
            method: "DELETE",
            headers: { "X-CSRFToken": getToken() },
        }),
    );
    const settled = await Promise.allSettled(promises);
    const errors = [];
    for (const fulfilled of settled.filter(
        (prom) => prom.status === "fulfilled",
    )) {
        const resp = fulfilled as PromiseFulfilledResult<Response>;
        if (!resp.value.ok) {
            const error = await resp.value.json();
            errors.push(error.message);
        }
    }
    if (errors.length) {
        throw new Error(errors.join("|"));
    }
    return true;
};

export const deleteItems = async (itemIds: string[]) => {
    const promises = itemIds.map((id) =>
        fetch(arches.urls.controlled_list_item(id), {
            method: "DELETE",
            headers: { "X-CSRFToken": getToken() },
        }),
    );
    const settled = await Promise.allSettled(promises);
    const errors = [];
    for (const fulfilled of settled.filter(
        (prom) => prom.status === "fulfilled",
    )) {
        const resp = fulfilled as PromiseFulfilledResult<Response>;
        if (!resp.value.ok) {
            const error = await resp.value.json();
            errors.push(error.message);
        }
    }
    if (errors.length) {
        throw new Error(errors.join("|"));
    }
    return true;
};

export const upsertValue = async (value: Value | NewValue) => {
    const url = value.id
        ? arches.urls.controlled_list_item_value(value.id)
        : arches.urls.controlled_list_item_value_add;
    const method = value.id ? "PUT" : "POST";
    const response = await fetch(url, {
        method,
        headers: { "X-CSRFToken": getToken() },
        body: JSON.stringify(value),
    });
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const deleteValue = async (value: Value) => {
    const response = await fetch(
        arches.urls.controlled_list_item_value(value.id),
        {
            method: "DELETE",
            headers: { "X-CSRFToken": getToken() },
        },
    );
    if (response.ok) {
        return true;
    }
    try {
        const error = await response.json();
        throw new Error(error.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const upsertMetadata = async (
    metadata: NewOrExistingControlledListItemImageMetadata,
) => {
    const url = metadata.id
        ? arches.urls.controlled_list_item_image_metadata(metadata.id)
        : arches.urls.controlled_list_item_image_metadata_add;
    const method = metadata.id ? "PUT" : "POST";
    const response = await fetch(url, {
        method,
        headers: { "X-CSRFToken": getToken() },
        body: JSON.stringify(metadata),
    });
    try {
        const parsed = await response.json();
        if (response.ok) {
            return parsed;
        }
        throw new Error(parsed.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const deleteMetadata = async (
    metadata: ControlledListItemImageMetadata,
) => {
    const response = await fetch(
        arches.urls.controlled_list_item_image_metadata(metadata.id),
        {
            method: "DELETE",
            headers: { "X-CSRFToken": getToken() },
        },
    );
    if (response.ok) {
        return true;
    }
    try {
        const error = await response.json();
        throw new Error(error.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};

export const deleteImage = async (image: ControlledListItemImage) => {
    const response = await fetch(
        arches.urls.controlled_list_item_image(image.id),
        {
            method: "DELETE",
            headers: { "X-CSRFToken": getToken() },
        },
    );
    if (response.ok) {
        return true;
    }
    try {
        const error = await response.json();
        throw new Error(error.message);
    } catch (error) {
        throw new Error((error as Error).message || response.statusText, {
            cause: error,
        });
    }
};
