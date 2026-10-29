import { describe, expect, it } from "vitest";

import { sanitizeFilename } from "@/catalina/utils.ts";

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
