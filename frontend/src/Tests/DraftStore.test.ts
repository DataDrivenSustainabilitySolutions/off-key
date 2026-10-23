import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearNavigationDrafts, createDraftStore, readStoredDraft, storeDraft } from "@/lib/navigation-draft";

beforeEach(() => { clearNavigationDrafts(); });

describe("createDraftStore", () => {
  it("restores the stored copy and persists each write", () => {
    storeDraft("draft", { count: 2 });
    const store = createDraftStore("draft", (stored) => stored as { count: number }, (next) => next);
    const listener = vi.fn();
    store.subscribe(listener);

    store.update({ count: 3 });

    expect(store.getSnapshot()).toEqual({ count: 3 });
    expect(readStoredDraft("draft")).toEqual({ count: 3 });
    expect(listener).toHaveBeenCalledOnce();
  });

  it("removes the stored copy when persist returns undefined", () => {
    storeDraft("draft", { count: 2 });
    const store = createDraftStore("draft", () => ({ count: 0 }), () => undefined);
    store.update({ count: 1 });
    expect(readStoredDraft("draft")).toBeUndefined();
  });

  it("ignores writes from before the drafts were cleared", () => {
    const store = createDraftStore("draft", () => ({ count: 0 }), (next) => next);
    const listener = vi.fn();
    store.subscribe(listener);
    clearNavigationDrafts();

    store.update({ count: 1 });

    expect(store.getSnapshot()).toEqual({ count: 0 });
    expect(readStoredDraft("draft")).toBeUndefined();
    expect(listener).not.toHaveBeenCalled();
  });

  it("keeps a keyless store in memory only", () => {
    const persist = vi.fn((next: { count: number }) => next);
    const store = createDraftStore(undefined, (stored) => ({ count: stored === undefined ? 0 : -1 }), persist);
    store.update({ count: 1 });
    expect(store.getSnapshot()).toEqual({ count: 1 });
    expect(persist).not.toHaveBeenCalled();
  });
});
