import { afterEach, describe, expect, it, vi } from "vitest";

import {
    ancestorExpandedKeys,
    centerInScrollParent,
    groupParentIdsByDepth,
    runWithConcurrency,
    sanitizeFilename,
} from "@/catalina/utils.ts";

describe("sanitizeFilename", () => {
    it("keeps a plain name", () => {
        expect(sanitizeFilename("catalina_controlled_lists")).toBe(
            "catalina_controlled_lists",
        );
    });

    it("replaces spaces with underscores", () => {
        expect(sanitizeFilename("  my  lists ")).toBe("my_lists");
    });

    it("drops path separators and reserved characters", () => {
        expect(sanitizeFilename('../a/b\\c:d*e?"f<g>h|i')).toBe("abcdefghi");
    });

    it("keeps non-ASCII letters", () => {
        expect(sanitizeFilename("Māori lists")).toBe("Māori_lists");
    });

    it("drops a trailing .xml extension", () => {
        expect(sanitizeFilename("lists.XML")).toBe("lists");
    });

    it("returns an empty string when nothing is usable", () => {
        expect(sanitizeFilename("../*?")).toBe("");
    });
});

describe("runWithConcurrency", () => {
    it("processes every value", async () => {
        const seen: number[] = [];
        await runWithConcurrency([1, 2, 3, 4, 5], 2, async (value) => {
            seen.push(value);
        });
        expect(seen.sort()).toEqual([1, 2, 3, 4, 5]);
    });

    it("never runs more than the limit at once", async () => {
        let inFlight = 0;
        let peak = 0;
        await runWithConcurrency([1, 2, 3, 4, 5, 6], 3, async () => {
            inFlight++;
            peak = Math.max(peak, inFlight);
            await new Promise((resolve) => setTimeout(resolve, 5));
            inFlight--;
        });
        expect(peak).toBe(3);
    });

    it("does nothing for an empty list", async () => {
        const run = vi.fn();
        await runWithConcurrency([], 4, run);
        expect(run).not.toHaveBeenCalled();
    });
});

describe("groupParentIdsByDepth", () => {
    it("groups ancestor ids by depth without duplicates", () => {
        const grouped = groupParentIdsByDepth([
            {
                items: [
                    { parent_ids: ["a", "b"] },
                    { parent_ids: ["a", "c", "d"] },
                ],
            },
            { items: [{ parent_ids: ["e"] }] },
        ]);
        expect(grouped).toEqual([["a", "e"], ["b", "c"], ["d"]]);
    });

    it("ignores failed lists, root items and missing items", () => {
        expect(
            groupParentIdsByDepth([
                null,
                {},
                { items: [{}, { parent_ids: [] }] },
            ]),
        ).toEqual([]);
    });
});

describe("ancestorExpandedKeys", () => {
    const items: Record<string, { parent_id: string | null }> = {
        child: { parent_id: "root" },
        root: { parent_id: null },
    };
    const findItem = (id: string) => items[id];

    it("includes the list and every ancestor", () => {
        expect(
            ancestorExpandedKeys(
                { list_id: "list", parent_id: "child" },
                findItem,
            ),
        ).toEqual({ list: true, child: true, root: true });
    });

    it("only includes the list for a root item", () => {
        expect(
            ancestorExpandedKeys(
                { list_id: "list", parent_id: null },
                findItem,
            ),
        ).toEqual({ list: true });
    });

    it("stops at an ancestor that is not loaded", () => {
        expect(
            ancestorExpandedKeys(
                { list_id: "list", parent_id: "missing" },
                findItem,
            ),
        ).toEqual({ list: true, missing: true });
    });

    it("does not loop forever on a cyclic chain", () => {
        const cyclic: Record<string, { parent_id: string | null }> = {
            a: { parent_id: "b" },
            b: { parent_id: "a" },
        };
        expect(
            ancestorExpandedKeys(
                { list_id: "list", parent_id: "a" },
                (id) => cyclic[id],
            ),
        ).toEqual({ list: true, a: true, b: true });
    });
});

describe("centerInScrollParent", () => {
    afterEach(() => {
        document.body.innerHTML = "";
    });

    function setLayout(
        element: HTMLElement,
        { top, height }: { top: number; height: number },
    ) {
        element.getBoundingClientRect = () =>
            ({ top, height, bottom: top + height }) as DOMRect;
    }

    function setScroll(
        element: HTMLElement,
        {
            overflowY,
            scrollHeight,
            clientHeight,
        }: Record<string, string | number>,
    ) {
        element.style.overflowY = overflowY as string;
        Object.defineProperty(element, "scrollHeight", {
            configurable: true,
            value: scrollHeight,
        });
        Object.defineProperty(element, "clientHeight", {
            configurable: true,
            value: clientHeight,
        });
    }

    it("centers the element in the nearest scrolling ancestor", () => {
        const hidden = document.createElement("div");
        const scroller = document.createElement("div");
        const row = document.createElement("div");
        hidden.appendChild(scroller);
        scroller.appendChild(row);
        document.body.appendChild(hidden);

        setScroll(hidden, {
            overflowY: "hidden",
            scrollHeight: 5000,
            clientHeight: 400,
        });
        setScroll(scroller, {
            overflowY: "auto",
            scrollHeight: 5000,
            clientHeight: 400,
        });
        setLayout(scroller, { top: 100, height: 400 });
        setLayout(row, { top: 1100, height: 40 });

        centerInScrollParent(row);

        // 1100 - 100 - (400 - 40) / 2 = 820
        expect(scroller.scrollTop).toBe(820);
        expect(hidden.scrollTop).toBe(0);
    });

    it("skips ancestors that do not overflow", () => {
        const outer = document.createElement("div");
        const inner = document.createElement("div");
        const row = document.createElement("div");
        outer.appendChild(inner);
        inner.appendChild(row);
        document.body.appendChild(outer);

        setScroll(outer, {
            overflowY: "scroll",
            scrollHeight: 2000,
            clientHeight: 200,
        });
        setScroll(inner, {
            overflowY: "auto",
            scrollHeight: 100,
            clientHeight: 100,
        });
        setLayout(outer, { top: 0, height: 200 });
        setLayout(row, { top: 500, height: 20 });

        centerInScrollParent(row);

        expect(inner.scrollTop).toBe(0);
        expect(outer.scrollTop).toBe(500 - (200 - 20) / 2);
    });

    it("does nothing when no ancestor scrolls", () => {
        const parent = document.createElement("div");
        const row = document.createElement("div");
        parent.appendChild(row);
        document.body.appendChild(parent);

        expect(() => centerInScrollParent(row)).not.toThrow();
        expect(parent.scrollTop).toBe(0);
    });
});
