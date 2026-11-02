/**
 * Make a user-entered name safe to use as a download filename.
 *
 * Keeps letters, numbers, spaces, dots, underscores and hyphens, turns runs of
 * spaces into a single underscore and drops a trailing ".xml" so callers can
 * append their own extension. Returns an empty string if nothing usable is left.
 */
export function sanitizeFilename(name: string): string {
    return name
        .replace(/[^\p{L}\p{N} ._-]/gu, "")
        .trim()
        .replace(/^\.+/, "")
        .replace(/\.xml$/i, "")
        .replace(/ +/g, "_");
}

/**
 * Run an async function over values with at most `limit` calls in flight.
 * Resolves once every value has been processed.
 */
export async function runWithConcurrency<T>(
    values: T[],
    limit: number,
    run: (value: T) => Promise<unknown>,
): Promise<void> {
    let next = 0;
    const workers = Array.from(
        { length: Math.min(limit, values.length) },
        async () => {
            while (next < values.length) {
                await run(values[next++]);
            }
        },
    );
    await Promise.all(workers);
}

/**
 * Group the ancestor ids of search matches by depth. `parent_ids` run from the
 * root to the immediate parent, so index 0 holds every root-level ancestor,
 * index 1 the next level down, and so on. Each id appears once per level.
 */
export function groupParentIdsByDepth(
    results: Array<{ items?: Array<{ parent_ids?: string[] }> } | null>,
): string[][] {
    const byDepth: Set<string>[] = [];
    for (const data of results) {
        for (const item of data?.items ?? []) {
            (item.parent_ids ?? []).forEach((parentId, depth) => {
                (byDepth[depth] ??= new Set()).add(parentId);
            });
        }
    }
    return byDepth.map((parentIds) => [...parentIds]);
}

/**
 * Expanded-keys entries that open the path to an item: its list and every
 * ancestor. Stops if an ancestor cannot be found or the chain loops.
 */
export function ancestorExpandedKeys(
    item: { list_id: string; parent_id: string | null },
    findItem: (id: string) => { parent_id: string | null } | null | undefined,
): Record<string, boolean> {
    const keys: Record<string, boolean> = { [item.list_id]: true };
    let parentId = item.parent_id;
    while (parentId && !keys[parentId]) {
        keys[parentId] = true;
        parentId = findItem(parentId)?.parent_id ?? null;
    }
    return keys;
}

/**
 * Scroll the nearest scrolling ancestor so `element` sits in its vertical
 * middle. scrollIntoView also scrolls overflow:hidden containers and the page,
 * which shifts the layout, so only the nearest element that really scrolls is
 * moved. Does nothing if no ancestor scrolls.
 */
export function centerInScrollParent(element: HTMLElement): void {
    let parent = element.parentElement;
    while (parent) {
        const { overflowY } = getComputedStyle(parent);
        if (
            (overflowY === "auto" || overflowY === "scroll") &&
            parent.scrollHeight > parent.clientHeight
        ) {
            const rowRect = element.getBoundingClientRect();
            const parentRect = parent.getBoundingClientRect();
            parent.scrollTop +=
                rowRect.top -
                parentRect.top -
                (parent.clientHeight - rowRect.height) / 2;
            return;
        }
        parent = parent.parentElement;
    }
}
