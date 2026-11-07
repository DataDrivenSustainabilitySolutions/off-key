/** Reload the pages the user has opened, retaining each identity once. */
export async function loadOffsetPages<T extends { id: string }>(
  fetchPage: (offset: number) => Promise<{ items: T[]; next_offset?: number | null }>,
  pages: number,
  signal: AbortSignal,
) {
  const items = new Map<string, T>();
  let offset = 0;
  let next: number | null = null;
  for (let page = 0; page < pages; page++) {
    signal.throwIfAborted();
    const result = await fetchPage(offset);
    signal.throwIfAborted();
    for (const item of result.items) items.set(item.id, item);
    next = result.next_offset ?? null;
    if (next === null) break;
    if (next <= offset) throw new Error("The next page did not advance. Please retry.");
    offset = next;
  }
  return { items: [...items.values()], next_offset: next };
}
