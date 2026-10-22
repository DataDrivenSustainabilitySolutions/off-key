// Page sizes the frontend requests explicitly, so short-page detection never
// depends on a server default.
export const TELEMETRY_PAGE_SIZE = 1000;
export const EVIDENCE_PAGE_SIZE = 2000;
export const MAX_FORWARD_PAGES = 10;

interface DrainForwardOptions<T, C> {
  /** Last cursor already seen; without one only the latest page is read. */
  cursor: C | undefined;
  fetchPage: (cursor: C | undefined) => Promise<T[]>;
  cursorOf: (rows: T[]) => C | undefined;
  pageSize: number;
  maxPages?: number;
}

const sameCursor = (left: unknown, right: unknown) =>
  JSON.stringify(left) === JSON.stringify(right);

/**
 * Read forward from a cursor until a short page, a missing or unchanged
 * cursor, or the page cap. Callers derive the next cursor from the result.
 */
export const drainForward = async <T, C>({
  cursor: initial,
  fetchPage,
  cursorOf,
  pageSize,
  maxPages = MAX_FORWARD_PAGES,
}: DrainForwardOptions<T, C>): Promise<T[]> => {
  const rows: T[] = [];
  let cursor = initial;
  for (let page = 0; page < maxPages; page += 1) {
    const incoming = await fetchPage(cursor);
    rows.push(...incoming);
    if (!initial || incoming.length < pageSize) break;
    const next = cursorOf(incoming);
    if (!next || sameCursor(next, cursor)) break;
    cursor = next;
  }
  return rows;
};
