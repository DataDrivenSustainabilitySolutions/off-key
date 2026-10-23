import { describe, expect, it, vi } from "vitest";
import {
  createDefaultExplorerPreferences,
  loadExplorerPreferences,
  MAX_EXPLORER_PREFERENCE_BYTES,
  saveExplorerPreferences,
  toggleExplorerFavourite,
  type ExplorerPreferences,
} from "@/features/workspace/preferences";

const key = (account: string | number | null = "alice") =>
  `aberration:explorer:v1:${account ?? "local"}`;
const preferences = (): ExplorerPreferences => ({
  version: 1,
  scopeKey: 'topic:["broker:one","telemetry/0"]',
  sidebarOpen: false,
});
describe("explorer preference persistence", () => {
  it("persists service and reading favourites by stable identity without altering another account", () => {
    const saved = toggleExplorerFavourite(toggleExplorerFavourite(preferences(), "service", "same-id"), "reading", "same-id");
    expect(saveExplorerPreferences("alice", saved)).toBe(true);
    expect(loadExplorerPreferences("alice")).toEqual(saved);
    expect(loadExplorerPreferences("bob").favourites).toBeUndefined();
    const removed = toggleExplorerFavourite(saved, "service", "same-id");
    expect(removed.favourites).toEqual([{ kind: "reading", id: "same-id" }]);
  });

  it("discards malformed favourite entries and copies only validated identities", () => {
    localStorage.setItem(key(), JSON.stringify({ ...preferences(), favourites: [
      { kind: "service", id: "valid", password: "private" }, { kind: "service", id: "valid" },
      { kind: "reading", id: "__proto__" }, { kind: "camera", id: "invalid" }, null,
    ] }));
    expect(loadExplorerPreferences("alice")).toEqual({ ...preferences(), favourites: [{ kind: "service", id: "valid" }] });
    expect(toggleExplorerFavourite(preferences(), "reading", "bad\nidentity")).toEqual(preferences());
  });

  it("persists sidebar width per account without replacing existing navigation", () => {
    const saved = { ...preferences(), sidebarWidth: 416 };
    expect(saveExplorerPreferences("alice", saved)).toBe(true);
    expect(loadExplorerPreferences("alice")).toEqual(saved);
    expect(loadExplorerPreferences("bob").sidebarWidth).toBeUndefined();
    localStorage.setItem(key("bob"), JSON.stringify(preferences()));
    expect(loadExplorerPreferences("bob")).toEqual(preferences());
  });

  it("loads saved navigation and drops the retired personal groups", () => {
    localStorage.setItem(key(), JSON.stringify({ ...preferences(), groups: [{ id: "watch", name: "Watch", color: "#6589b3", memberIds: [] }] }));
    expect(loadExplorerPreferences("alice")).toEqual(preferences());
  });

  it.each([true, false])("persists the online topic filter (%s) for its account", onlineOnly => {
    const saved = { ...preferences(), onlineOnly };
    expect(saveExplorerPreferences("alice", saved)).toBe(true);
    expect(loadExplorerPreferences("alice")).toEqual(saved);
    expect(loadExplorerPreferences("bob").onlineOnly).toBeUndefined();
  });

  it("ignores a malformed online topic preference and retains existing navigation", () => {
    localStorage.setItem(key(), JSON.stringify({ ...preferences(), onlineOnly: "true" }));
    expect(loadExplorerPreferences("alice")).toEqual(preferences());
  });

  it.each([[20, 240], [900, 480], [333.4, 333]])("bounds stored sidebar widths without losing the rest of the preferences", (width, expected) => {
    localStorage.setItem(key(), JSON.stringify({ ...preferences(), sidebarWidth: width }));
    expect(loadExplorerPreferences("alice")).toEqual({ ...preferences(), sidebarWidth: expected });
  });

  it.each(["wide", null, {}, Infinity])("discards malformed widths while retaining saved navigation", (sidebarWidth) => {
    localStorage.setItem(key(), JSON.stringify({ ...preferences(), sidebarWidth }));
    expect(loadExplorerPreferences("alice")).toEqual(preferences());
  });

  it("keeps navigation scoped to the account", () => {
    const alice = preferences();
    expect(saveExplorerPreferences("alice", alice)).toBe(true);
    expect(loadExplorerPreferences("alice")).toEqual(alice);
    expect(loadExplorerPreferences("bob")).toEqual(createDefaultExplorerPreferences());
    expect(loadExplorerPreferences(null)).toEqual(createDefaultExplorerPreferences());

    const local = { ...createDefaultExplorerPreferences(), scopeKey: "local-scope" };
    expect(saveExplorerPreferences(null, local)).toBe(true);
    expect(localStorage.getItem(key(null))).not.toBeNull();
    expect(loadExplorerPreferences("alice")).toEqual(alice);
    expect(saveExplorerPreferences(42, alice)).toBe(true);
    expect(loadExplorerPreferences(42)).toEqual(alice);
  });

  it("persists only presentation preferences, never credentials or live data", () => {
    const clean = preferences();
    const unsafe = {
      ...clean,
      endpoint: "mqtt://private.example",
      password: "not-to-be-saved",
      telemetry: [1, 2, 3],
      groups: [{ id: "personal:watchlist", name: "private group", memberIds: ["device:one"] }],
    };
    expect(saveExplorerPreferences("alice", unsafe)).toBe(true);
    const stored = JSON.parse(localStorage.getItem(key())!);
    expect(stored).toEqual(clean);
    expect(localStorage.getItem(key())).not.toContain("private");
  });

  it.each([
    "not json",
    "null",
    JSON.stringify({ ...preferences(), version: 2 }),
    JSON.stringify({ ...preferences(), sidebarOpen: "yes" }),
    JSON.stringify({ ...preferences(), scopeKey: "" }),
    JSON.stringify({ ...preferences(), scopeKey: "path\ncontrol" }),
    JSON.stringify({ ...preferences(), scopeKey: "x".repeat(4097) }),
  ])("recovers a usable default from invalid storage", (saved) => {
    localStorage.setItem(key(), saved);
    expect(loadExplorerPreferences("alice")).toEqual(createDefaultExplorerPreferences());
  });

  it("bounds reads by UTF-8 bytes before parsing", () => {
    localStorage.setItem(key(), " ".repeat(MAX_EXPLORER_PREFERENCE_BYTES + 1));
    expect(loadExplorerPreferences("alice")).toEqual(createDefaultExplorerPreferences());

    const wide = JSON.stringify({ ...preferences(), discarded: "界".repeat(400_000) });
    expect(wide.length).toBeLessThan(MAX_EXPLORER_PREFERENCE_BYTES);
    localStorage.setItem(key(), wide);
    expect(loadExplorerPreferences("alice")).toEqual(createDefaultExplorerPreferences());
  });

  it("does not overwrite good preferences when an invalid save is rejected", () => {
    const original = preferences();
    saveExplorerPreferences("alice", original);
    expect(saveExplorerPreferences("alice", { ...original, scopeKey: "" })).toBe(false);
    expect(loadExplorerPreferences("alice")).toEqual(original);
  });

  it("reports a failed save when writing storage is unavailable", () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    expect(saveExplorerPreferences("alice", preferences())).toBe(false);
  });

  it("stays usable when reading storage is disabled", () => {
    vi.spyOn(localStorage, "getItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    expect(loadExplorerPreferences("alice")).toEqual(createDefaultExplorerPreferences());
  });
});
