import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiUtils } from "@/lib/api-client";
import { useFavourites, type Favourite, type LegacyFavourite } from "@/features/workspace/favourites";

vi.mock("@/lib/api-client", () => ({
  apiUtils: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

/** A fake of the server's per-member list that applies each request. */
function server(initial: Record<number, Favourite[]> = {}) {
  const lists = new Map(Object.entries(initial).map(([account, items]) => [Number(account), [...items]]));
  let account = 1;
  const list = () => lists.get(account) ?? (lists.set(account, []), lists.get(account)!);
  vi.mocked(apiUtils.get).mockImplementation(async () => list().map(item => ({ ...item, created_at: "2026-11-05T00:00:00Z" })));
  vi.mocked(apiUtils.post).mockImplementation(async (_endpoint, body) => {
    const item = body as Favourite;
    if (!list().some(other => other.kind === item.kind && other.id === item.id)) list().push(item);
    return item;
  });
  vi.mocked(apiUtils.delete).mockImplementation(async endpoint => {
    const params = new URLSearchParams(endpoint.split("?")[1]);
    lists.set(account, list().filter(item => item.kind !== params.get("kind") || item.id !== params.get("id")));
    return undefined;
  });
  return { list, signIn: (next: number) => { account = next; } };
}

const mount = (account: number | null, legacy?: LegacyFavourite[], dropLegacy = vi.fn()) =>
  renderHook(({ account, legacy }) => useFavourites(account, legacy, dropLegacy), { initialProps: { account, legacy } });

beforeEach(() => { vi.mocked(apiUtils.get).mockReset(); vi.mocked(apiUtils.post).mockReset(); vi.mocked(apiUtils.delete).mockReset(); });

describe("favourites kept on the server", () => {
  it("loads the member's list and saves each star and unstar", async () => {
    const remote = server({ 1: [{ kind: "reading", id: "line/temperature" }] });
    const hook = mount(1);
    await waitFor(() => expect(hook.result.current.favourites).toEqual([{ kind: "reading", id: "line/temperature" }]));

    act(() => hook.result.current.toggle("monitor", "m1"));
    expect(hook.result.current.favourites).toContainEqual({ kind: "monitor", id: "m1" });
    await waitFor(() => expect(remote.list()).toContainEqual({ kind: "monitor", id: "m1" }));
    act(() => hook.result.current.toggle("reading", "line/temperature"));
    await waitFor(() => expect(remote.list()).toEqual([{ kind: "monitor", id: "m1" }]));
    expect(apiUtils.delete).toHaveBeenCalledWith("/v1/favorites?kind=reading&id=line%2Ftemperature");
    expect(hook.result.current.error).toBe("");
  });

  it("moves favourites this browser kept to the account once, as monitors and readings", async () => {
    const remote = server({ 1: [{ kind: "reading", id: "kept" }] });
    const dropLegacy = vi.fn();
    const hook = mount(1, [{ kind: "service", id: "m1" }, { kind: "reading", id: "kept" }], dropLegacy);

    await waitFor(() => expect(dropLegacy).toHaveBeenCalledOnce());
    expect(remote.list()).toEqual([{ kind: "reading", id: "kept" }, { kind: "monitor", id: "m1" }]);
    expect(apiUtils.post).toHaveBeenCalledExactlyOnceWith("/v1/favorites", { kind: "monitor", id: "m1" });
    expect(hook.result.current.favourites).toEqual(remote.list());
  });

  it("keeps browser favourites when the move fails, so the next sign-in retries", async () => {
    server();
    vi.mocked(apiUtils.post).mockRejectedValue(new Error("offline"));
    const dropLegacy = vi.fn();
    const hook = mount(1, [{ kind: "service", id: "m1" }], dropLegacy);

    await waitFor(() => expect(hook.result.current.error).toContain("could not be loaded"));
    expect(dropLegacy).not.toHaveBeenCalled();
  });

  it("undoes a star the server refused and says so", async () => {
    server();
    const hook = mount(1);
    await waitFor(() => expect(apiUtils.get).toHaveBeenCalledOnce());
    vi.mocked(apiUtils.post).mockRejectedValueOnce(new Error("A member keeps at most 256 favorites."));

    act(() => hook.result.current.toggle("monitor", "m1"));
    await waitFor(() => expect(hook.result.current.error).toBe("Your favourite could not be saved. Try again."));
    expect(hook.result.current.favourites).toEqual([]);
  });

  it("never shows one member's favourites to the next", async () => {
    const remote = server({ 1: [{ kind: "monitor", id: "mine" }], 2: [] });
    const hook = mount(1);
    await waitFor(() => expect(hook.result.current.favourites).toHaveLength(1));

    remote.signIn(2);
    hook.rerender({ account: 2, legacy: undefined });
    expect(hook.result.current.favourites).toEqual([]);
    await waitFor(() => expect(apiUtils.get).toHaveBeenCalledTimes(2));
    expect(hook.result.current.favourites).toEqual([]);
    hook.rerender({ account: null as unknown as number, legacy: undefined });
    expect(hook.result.current.favourites).toEqual([]);
  });
});
