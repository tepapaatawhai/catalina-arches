<!--
Catalina override of arches_controlled_lists/components/tree/ListTree.vue (this
file shadows the upstream one through the "@" alias). Changes:
- a progress bar under the filter box while the lists load or the server-side
  search is running (isBusy);
- a "No results found." message when a finished search matches nothing
  (hasNoResults);
- the server-side search loads the ancestors of matches level by level, with
  parallel requests inside a level, instead of one request at a time;
- the selected row is scrolled into view when the filter is cleared and on the
  first load of an item or list URL (scrollSelectedRowIntoView).
Compare with upstream when upgrading arches_controlled_lists.
-->
<script setup lang="ts">
import {
    computed,
    inject,
    nextTick,
    onMounted,
    reactive,
    ref,
    watch,
} from "vue";
import { useRoute } from "vue-router";
import { useGettext } from "vue3-gettext";
import { useToast } from "primevue/usetoast";

import InputText from "primevue/inputtext";
import Message from "primevue/message";
import ProgressBar from "primevue/progressbar";
import Tree from "primevue/tree";

import {
    DEFAULT_ERROR_TOAST_LIFE,
    ERROR,
    displayedRowKey,
    selectedLanguageKey,
} from "@/arches_controlled_lists/constants.ts";
import { routeNames } from "@/arches_controlled_lists/routes.ts";
import {
    findNodeInTree,
    listAsNode,
    nodeIsList,
} from "@/arches_controlled_lists/utils.ts";
import {
    ancestorExpandedKeys,
    centerInScrollParent,
    groupParentIdsByDepth,
    runWithConcurrency,
} from "@/catalina/utils.ts";
import { useCappedTreeFilter } from "@/arches_controlled_lists/components/tree/utils/capped-filter.ts";
import { fetchFilteredList } from "@/arches_controlled_lists/api.ts";
import { useListStore } from "@/arches_controlled_lists/stores/useListStore.ts";
import ListTreeControls from "@/arches_controlled_lists/components/tree/ListTreeControls.vue";
import TreeRow from "@/arches_controlled_lists/components/tree/TreeRow.vue";

import type { ComponentPublicInstance, Ref } from "vue";
import type { RouteLocationNormalizedLoadedGeneric } from "vue-router";
import type { TreePassThroughMethodOptions } from "primevue/tree";
import type { TreeExpandedKeys, TreeSelectionKeys } from "primevue/tree";
import type { TreeNode } from "primevue/treenode";
import type {
    ControlledList,
    ControlledListItem,
    Language,
    RowSetter,
    Value,
} from "@/arches_controlled_lists/types";

const FILTER_DEBOUNCE_MS = 250;
const FILTER_RENDER_CAP = 2500;
const CHILD_LOAD_CONCURRENCY = 8;

const toast = useToast();
const { $gettext } = useGettext();

const moveLabels = Object.freeze({
    addChild: $gettext("Add child item"),
    moveUp: $gettext("Move item up"),
    moveDown: $gettext("Move item down"),
    changeParent: $gettext("Change item parent"),
});
const iconLabels = Object.freeze({
    list: $gettext("List"),
    item: $gettext("Item"),
});
const FILTER_PLACEHOLDER = $gettext("Find");
const LOADING_LABEL = $gettext("Loading");
const FILTER_CAPPED_MESSAGE = $gettext(
    "Too many matches to display. Please refine your query.",
);
const NO_RESULTS_MESSAGE = $gettext("No results found.");

const listStore = useListStore();
const selectedLanguage = inject(selectedLanguageKey) as Ref<Language>;

const selectedKeys: Ref<TreeSelectionKeys> = ref({});
const expandedKeys: Ref<TreeExpandedKeys> = ref({});
const movingItem: Ref<TreeNode | undefined> = ref();
const shouldCopyChildren = ref(true);
const isMultiSelecting = ref(false);
const filterValue = ref("");
const isSearching = ref(false);
const loadingNodeKeys = reactive(new Set<string>());
const expandingNodeKeys = reactive(new Set<string>());

const nextNewItem = ref<ControlledListItem>();
const newLabelFormValue = ref("");
const newListFormValue = ref("");
const nextNewList = ref();
const refetcher = ref(0);
const rerenderTree = ref(0);
const treeRef = ref<ComponentPublicInstance>();

const { setDisplayedRow } = inject<{ setDisplayedRow: RowSetter }>(
    displayedRowKey,
)!;

const route = useRoute();

const tree = computed<TreeNode[]>(() =>
    listStore.lists.map((list: ControlledList) =>
        listAsNode(
            list,
            selectedLanguage.value,
            iconLabels,
            listStore.hasLoadedChildren,
        ),
    ),
);

function getSearchableText(node: TreeNode): string {
    if (nodeIsList(node)) {
        return (node.data.name ?? "").toLowerCase();
    }
    const values = (node.data.values ?? []) as Value[];
    return values.map((v) => (v.value ?? "").toLowerCase()).join("\n");
}

const isBusy = computed(() => listStore.isLoading || isSearching.value);

const { debouncedFilterValue, filteredTree, isFilterCapped } =
    useCappedTreeFilter(
        tree,
        expandedKeys,
        filterValue,
        FILTER_DEBOUNCE_MS,
        FILTER_RENDER_CAP,
        getSearchableText,
    );

// Only once the debounce has settled and the server-side search has finished.
const hasNoResults = computed(
    () =>
        !!filterValue.value.trim() &&
        debouncedFilterValue.value === filterValue.value &&
        !isBusy.value &&
        !isFilterCapped.value &&
        filteredTree.value.length === 0,
);

onMounted(async () => {
    try {
        await listStore.initialize();
    } catch (error) {
        toast.add({
            severity: ERROR,
            life: DEFAULT_ERROR_TOAST_LIFE,
            summary: $gettext("Unable to fetch lists"),
            detail: error instanceof Error ? error.message : undefined,
        });
    }
});

async function onNodeExpand(node: TreeNode) {
    const nodeKey = node.key as string;

    expandingNodeKeys.add(nodeKey);
    requestAnimationFrame(() => {
        setTimeout(() => expandingNodeKeys.delete(nodeKey), 600);
    });

    if (nodeIsList(node)) {
        // Lists ship their root items eagerly; nothing to lazy-load.
        return;
    }
    const itemId = nodeKey;
    if (listStore.hasLoadedChildren(itemId)) {
        return;
    }
    loadingNodeKeys.add(itemId);
    try {
        await listStore.loadChildren(itemId);
    } catch (error) {
        toast.add({
            severity: ERROR,
            life: DEFAULT_ERROR_TOAST_LIFE,
            summary: $gettext("Unable to fetch children"),
            detail: error instanceof Error ? error.message : undefined,
        });
    } finally {
        loadingNodeKeys.delete(itemId);
    }
}

const updateSelectedAndExpanded = (node: TreeNode) => {
    if (isMultiSelecting.value || movingItem.value?.key) {
        return;
    }
    setDisplayedRow(node.data);

    if (!expandedKeys.value[node.key]) {
        expandingNodeKeys.add(node.key as string);
        requestAnimationFrame(() => {
            setTimeout(() => expandingNodeKeys.delete(node.key as string), 600);
        });
    }

    expandedKeys.value = {
        ...expandedKeys.value,
        [node.key]: true,
    };
};

watch(isMultiSelecting, async (active) => {
    if (!active) return;
    const displayedListId = inferListIdFromDisplayedRow();
    if (displayedListId) {
        try {
            await listStore.loadListEagerly(displayedListId);
        } catch (error) {
            toast.add({
                severity: ERROR,
                life: DEFAULT_ERROR_TOAST_LIFE,
                summary: $gettext("Unable to load list for multi-select"),
                detail: error instanceof Error ? error.message : undefined,
            });
        }
    }
});

watch(movingItem, async (next) => {
    if (!next?.data?.list_id) return;
    try {
        await listStore.loadListEagerly(next.data.list_id);
    } catch (error) {
        toast.add({
            severity: ERROR,
            life: DEFAULT_ERROR_TOAST_LIFE,
            summary: $gettext("Unable to load list for move"),
            detail: error instanceof Error ? error.message : undefined,
        });
    }
});

function inferListIdFromDisplayedRow(): string | null {
    const firstSelected = Object.keys(selectedKeys.value)[0];
    if (!firstSelected) return null;
    const item = listStore.findItem(firstSelected);
    if (item) return item.list_id;
    const list = listStore.findList(firstSelected);
    return list ? list.id : null;
}

async function revealItemInTree(itemId: string): Promise<TreeNode | null> {
    try {
        const { found } = findNodeInTree(tree.value, itemId);
        if (found) return found;
    } catch {
        // not in memory yet; fall through to ancestor load
    }
    try {
        await listStore.loadAncestorPath(itemId);
        const { found } = findNodeInTree(tree.value, itemId);
        return found ?? null;
    } catch {
        return null;
    }
}

let hasScrolledToRoute = false;

async function navigate(newRoute: RouteLocationNormalizedLoadedGeneric) {
    switch (newRoute.name) {
        case routeNames.splash:
            hasScrolledToRoute = true;
            setDisplayedRow(null);
            expandedKeys.value = {};
            selectedKeys.value = {};
            break;
        case routeNames.list: {
            if (!tree.value.length) return;
            const list = tree.value.find(
                (node) => node.data.id === newRoute.params.id,
            );
            if (list) {
                setDisplayedRow(list.data);
                expandedKeys.value = {
                    ...expandedKeys.value,
                    [list.data.id]: true,
                };
                selectedKeys.value = { [list.data.id]: true };
                if (!hasScrolledToRoute) {
                    hasScrolledToRoute = true;
                    await nextTick();
                    scrollSelectedRowIntoView();
                }
            } else {
                setDisplayedRow(null);
            }
            break;
        }
        case routeNames.item: {
            if (!tree.value.length) return;
            const itemId = newRoute.params.id as string;
            const found = await revealItemInTree(itemId);
            if (found) {
                setDisplayedRow(found.data);
                // Collect ancestor ids so we can expand them all at once.
                let ancestorId = (found.data as ControlledListItem).parent_id;
                const idsToExpand: string[] = [
                    (found.data as ControlledListItem).list_id,
                ];
                while (ancestorId) {
                    idsToExpand.push(ancestorId);
                    const ancestor = listStore.findItem(ancestorId);
                    ancestorId = ancestor?.parent_id ?? null;
                }
                expandedKeys.value = {
                    ...expandedKeys.value,
                    ...Object.fromEntries(idsToExpand.map((id) => [id, true])),
                };
                selectedKeys.value = { [found.data.id]: true };
                // Only on the first load of the page (a refresh or a pasted
                // link). Later route changes come from clicking a row that is
                // already on screen.
                if (!hasScrolledToRoute) {
                    hasScrolledToRoute = true;
                    await nextTick();
                    scrollSelectedRowIntoView();
                }
            } else {
                toast.add({
                    severity: ERROR,
                    life: DEFAULT_ERROR_TOAST_LIFE,
                    summary: $gettext(`List Item ${itemId} not found`),
                });
                setDisplayedRow(null);
            }
            break;
        }
    }
}

// React to route changes.
watch(
    [
        () => {
            return { ...route };
        },
    ],
    ([newRoute]) => {
        navigate(newRoute);
    },
);

watch(
    () => tree.value.length,
    (length) => {
        if (length > 0) {
            navigate(route);
        }
    },
);

// Clearing the filter swaps the tree back to the full list, restores the
// expanded keys from before the search (so the clicked item's ancestors may be
// collapsed) and resets the scroll to the top. Re-expand the path to the
// selected row and bring it back into view.
watch(debouncedFilterValue, async (next, previous) => {
    if (next || !previous) return;
    // Let the filter composable restore its expanded keys snapshot first.
    await nextTick();
    const selectedKey = Object.keys(selectedKeys.value)[0];
    const selectedItem = selectedKey
        ? listStore.findItem(selectedKey)
        : undefined;
    if (selectedItem) {
        const ancestorKeys = ancestorExpandedKeys(selectedItem, (id) =>
            listStore.findItem(id),
        );
        expandedKeys.value = { ...expandedKeys.value, ...ancestorKeys };
        await nextTick();
    }
    scrollSelectedRowIntoView();
});

function scrollSelectedRowIntoView() {
    const scrollToSelected = () => {
        const selectedRow = (
            treeRef.value?.$el as HTMLElement | undefined
        )?.querySelector<HTMLElement>('[data-p-selected="true"]');
        if (selectedRow) {
            centerInScrollParent(selectedRow);
        }
    };
    requestAnimationFrame(scrollToSelected);
    // Retry once the tree has finished re-rendering the full list.
    setTimeout(scrollToSelected, 300);
}

let serverFilterAbortToken = 0;
watch(debouncedFilterValue, async (next) => {
    if (!next || filteredTree.value.length > 0 || isFilterCapped.value) {
        // Supersede any search still running for an earlier term.
        serverFilterAbortToken++;
        isSearching.value = false;
        return;
    }
    const token = ++serverFilterAbortToken;
    isSearching.value = true;
    try {
        // fetchFilteredList answers every list from one cached request.
        const results = await Promise.all(
            listStore.lists.map(async (list: ControlledList) => {
                try {
                    return await fetchFilteredList(list.id, next);
                } catch (error) {
                    console.warn(
                        `Server-side search of list ${list.id} failed:`,
                        error,
                    );
                    return null;
                }
            }),
        );
        if (token !== serverFilterAbortToken) return;

        // parent_ids run root to immediate parent, so group them by depth.
        // loadChildren only attaches children to a parent already in the
        // store, so one level must finish before the next starts.
        const parentIdsByDepth = groupParentIdsByDepth(results);
        for (const parentIds of parentIdsByDepth) {
            const pending = parentIds.filter(
                (pid) => !listStore.hasLoadedChildren(pid),
            );
            await runWithConcurrency(pending, CHILD_LOAD_CONCURRENCY, (pid) =>
                listStore.loadChildren(pid).catch(() => {
                    /* a failed parent just leaves its matches out of the tree */
                }),
            );
            if (token !== serverFilterAbortToken) return;
        }
    } finally {
        if (token === serverFilterAbortToken) {
            isSearching.value = false;
        }
    }
});
</script>

<template>
    <ListTreeControls
        :key="refetcher"
        v-model:rerender-tree="rerenderTree"
        v-model:expanded-keys="expandedKeys"
        v-model:selected-keys="selectedKeys"
        v-model:moving-item="movingItem"
        v-model:is-multi-selecting="isMultiSelecting"
        v-model:should-copy-children="shouldCopyChildren"
        v-model:next-new-list="nextNewList"
        v-model:new-list-form-value="newListFormValue"
        :tree="tree"
    />
    <div class="filter-container">
        <InputText
            v-model="filterValue"
            class="tree-filter-input"
            type="text"
            :placeholder="FILTER_PLACEHOLDER"
            :aria-label="FILTER_PLACEHOLDER"
        />
        <Message
            v-if="isFilterCapped"
            severity="warn"
            :closable="false"
            class="filter-cap-message"
        >
            {{ FILTER_CAPPED_MESSAGE }}
        </Message>
        <Message
            v-if="hasNoResults"
            severity="info"
            :closable="false"
            class="filter-cap-message"
        >
            {{ NO_RESULTS_MESSAGE }}
        </Message>
        <ProgressBar
            v-if="isBusy"
            mode="indeterminate"
            class="loading-bar"
            :aria-label="LOADING_LABEL"
        />
    </div>
    <Tree
        v-if="filteredTree"
        ref="treeRef"
        :key="rerenderTree"
        v-model:selection-keys="selectedKeys"
        v-model:expanded-keys="expandedKeys"
        :value="filteredTree"
        :selection-mode="isMultiSelecting ? 'checkbox' : 'single'"
        :pt="{
            root: {
                style: {
                    flexGrow: 1,
                    overflowY: 'hidden',
                    paddingBottom: '5rem',
                    paddingRight: '0rem',
                },
            },
            wrapper: {
                style: {
                    overflowY: 'auto',
                    maxHeight: '100%',
                    paddingBottom: '1rem',
                },
            },
            container: { style: { fontSize: '1.4rem' } },
            nodeContent: ({ instance }: TreePassThroughMethodOptions) => {
                if (instance.$el && instance.node.key === movingItem?.key) {
                    instance.$el.classList.add('is-adjusting-parent');
                }
                return { style: { height: '4rem' } };
            },
            nodeIcon: ({ instance }: TreePassThroughMethodOptions) => {
                return { ariaLabel: instance.node.iconLabel };
            },
            nodeLabel: {
                style: {
                    textWrap: 'nowrap',
                    marginLeft: '0.5rem',
                    width: '100%',
                },
            },
            nodeToggleButton: ({ instance }: TreePassThroughMethodOptions) => ({
                class: {
                    'node-children-loading':
                        loadingNodeKeys.has(instance.node?.key as string) ||
                        expandingNodeKeys.has(instance.node?.key as string),
                },
            }),
        }"
        @node-select="updateSelectedAndExpanded"
        @node-expand="onNodeExpand"
    >
        <template #default="slotProps">
            <TreeRow
                v-model:expanded-keys="expandedKeys"
                v-model:selected-keys="selectedKeys"
                v-model:moving-item="movingItem"
                v-model:refetcher="refetcher"
                v-model:rerender-tree="rerenderTree"
                v-model:next-new-item="nextNewItem"
                v-model:new-label-form-value="newLabelFormValue"
                v-model:new-list-form-value="newListFormValue"
                v-model:filter-value="filterValue"
                :tree="tree"
                :icon-labels
                :move-labels
                :node="slotProps.node"
                :is-multi-selecting="isMultiSelecting"
                :should-copy-children="shouldCopyChildren"
            />
        </template>
    </Tree>
</template>

<style scoped>
:deep(.is-adjusting-parent) {
    border: dashed;
}

.filter-container {
    padding: 0.5rem 1rem;
    background: var(--p-content-hover-background);
    border-bottom: 1px solid var(--p-content-border-color);
}

.loading-bar {
    height: 0.4rem;
    margin-top: 0.5rem;
}

.tree-filter-input {
    width: 100%;
    height: 3.5rem;
    font-size: 1.4rem;
    border-radius: 2px;
}

.filter-cap-message {
    margin-top: 0.5rem;
    font-size: 1.2rem;
}

:deep(.p-tree-node) {
    margin-inline-end: 0.5rem;
}

/* Ensure smooth chevron rotation on expand/collapse */
:deep(.p-tree-node-toggle-button .p-tree-node-toggle-icon) {
    transition: transform 0.2s ease-in-out;
}

/* Spin the expand toggle icon while children are being fetched. */
:deep(.node-children-loading .p-tree-node-toggle-icon) {
    animation: tree-toggle-spin 0.6s linear infinite;
    pointer-events: none;
}

@keyframes tree-toggle-spin {
    from {
        transform: rotate(0deg);
    }
    to {
        transform: rotate(360deg);
    }
}
</style>
