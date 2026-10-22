// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { drainForward } from "@/lib/forward-pages";

type Row = { id: number };
const cursorOf = (rows: Row[]) => rows[rows.length - 1]?.id;
const page = (start: number, size: number) =>
  Array.from({ length: size }, (_, index) => ({ id: start + index }));

describe("drainForward", () => {
  it("reads only the latest page without a cursor", async () => {
    const fetchPage = vi.fn(async () => page(1, 3));
    await expect(drainForward({ cursor: undefined, fetchPage, cursorOf, pageSize: 3 }))
      .resolves.toHaveLength(3);
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("advances through full pages and stops on a short page", async () => {
    const fetchPage = vi.fn(async (cursor?: number) =>
      cursor === 100 ? page(101, 3) : cursor === 103 ? page(104, 3) : page(107, 1));
    const rows = await drainForward({ cursor: 100 as number | undefined, fetchPage, cursorOf, pageSize: 3 });
    expect(rows.map(row => row.id)).toEqual([101, 102, 103, 104, 105, 106, 107]);
    expect(fetchPage.mock.calls.map(([cursor]) => cursor)).toEqual([100, 103, 106]);
  });

  it("stops when the cursor is missing or unchanged", async () => {
    const unchanged = vi.fn(async () => page(5, 2));
    await drainForward({ cursor: 6 as number | undefined, fetchPage: unchanged, cursorOf, pageSize: 2 });
    expect(unchanged).toHaveBeenCalledTimes(1);

    const missing = vi.fn(async () => page(1, 2));
    await drainForward({ cursor: 1, fetchPage: missing, cursorOf: () => undefined, pageSize: 2 });
    expect(missing).toHaveBeenCalledTimes(1);
  });

  it("compares object cursors by value", async () => {
    const fetchPage = vi.fn(async () => [{ created: "a", timestamp: "b" }]);
    await drainForward({
      cursor: { created: "a", timestamp: "b" } as { created: string; timestamp: string } | undefined,
      fetchPage,
      cursorOf: rows => ({ ...rows[0] }),
      pageSize: 1,
    });
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("caps the number of pages", async () => {
    let next = 0;
    const fetchPage = vi.fn(async () => page((next += 2), 2));
    await drainForward({ cursor: 1 as number | undefined, fetchPage, cursorOf, pageSize: 2, maxPages: 4 });
    expect(fetchPage).toHaveBeenCalledTimes(4);
  });

  it("rejects when a page fails", async () => {
    const fetchPage = vi.fn(async () => { throw new Error("offline"); });
    await expect(drainForward({ cursor: 1, fetchPage, cursorOf, pageSize: 2 })).rejects.toThrow("offline");
  });
});
