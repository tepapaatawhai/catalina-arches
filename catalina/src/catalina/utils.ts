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
