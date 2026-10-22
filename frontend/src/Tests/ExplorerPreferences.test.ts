import { describe, expect, it, vi } from "vitest";
import {
  createDefaultExplorerPreferences,
  loadExplorerPreferences,
  MAX_EXPLORER_PREFERENCE_BYTES,
  MAX_PERSONAL_GROUP_MEMBERS,
  MAX_PERSONAL_GROUPS,
  MAX_PERSONAL_MEMBERSHIPS,
  parsePersonalGroups,
  saveExplorerPreferences,
  toggleExplorerFavourite,
  type ExplorerPreferences,
  type PersonalGroup,
} from "@/features/workspace/preferences";

const key = (account: string | number | null = "alice") =>
  `aberration:explorer:v1:${account ?? "local"}`;
const legacyKey = (account: string | number | null = "alice") =>
  `aberration:spatial:system:v1:${account ?? "local"}`;
const group = (id = "personal:watchlist", memberIds = ["device:one"]): PersonalGroup => ({
  id,
  name: "Watchlist",
  color: "#6589b3",
  memberIds,
});
const preferences = (groups = [group()]): ExplorerPreferences => ({
  version: 1,
  groups,
  scopeKey: 'topic:["broker:one","telemetry/0"]',
  sidebarOpen: false,
});
const membershipGroups = (count: number): PersonalGroup[] =>
  Array.from({ length: Math.ceil(count / MAX_PERSONAL_GROUP_MEMBERS) }, (_, index) =>
    group(
      `personal:${index}`,
      Array.from(
        { length: Math.min(MAX_PERSONAL_GROUP_MEMBERS, count - index * MAX_PERSONAL_GROUP_MEMBERS) },
        (_, member) => `stream:${index}:${member}`,
      ),
    ),
  );


describe("explorer preference persistence", () => {
  it("persists service and reading favourites by stable identity without altering archived groups or another account", () => {
    const saved = toggleExplorerFavourite(toggleExplorerFavourite(preferences(), "service", "same-id"), "reading", "same-id");
    expect(saveExplorerPreferences("alice", saved)).toBe(true);
    expect(loadExplorerPreferences("alice")).toEqual(saved);
    expect(loadExplorerPreferences("bob").favourites).toBeUndefined();
    const removed = toggleExplorerFavourite(saved, "service", "same-id");
    expect(removed.favourites).toEqual([{ kind: "reading", id: "same-id" }]);
    expect(removed.groups).toEqual(saved.groups);
  });

  it("discards malformed favourite entries and copies only validated identities", () => {
    localStorage.setItem(key(), JSON.stringify({ ...preferences(), favourites: [
      { kind: "service", id: "valid", password: "private" }, { kind: "service", id: "valid" },
      { kind: "reading", id: "__proto__" }, { kind: "camera", id: "invalid" }, null,
    ] }));
    expect(loadExplorerPreferences("alice")).toEqual({ ...preferences(), favourites: [{ kind: "service", id: "valid" }] });
    expect(toggleExplorerFavourite(preferences(), "reading", "bad\nidentity")).toEqual(preferences());
  });

  it("persists sidebar width per account without replacing existing navigation or archived groups", () => {
    const saved = { ...preferences(), sidebarWidth: 416 };
    expect(saveExplorerPreferences("alice", saved)).toBe(true);
    expect(loadExplorerPreferences("alice")).toEqual(saved);
    expect(loadExplorerPreferences("bob").sidebarWidth).toBeUndefined();
    localStorage.setItem(key("bob"), JSON.stringify(preferences()));
    expect(loadExplorerPreferences("bob")).toEqual(preferences());
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

  it.each(["wide", null, {}, Infinity])("discards malformed widths while retaining saved navigation and groups", (sidebarWidth) => {
    localStorage.setItem(key(), JSON.stringify({ ...preferences(), sidebarWidth }));
    expect(loadExplorerPreferences("alice")).toEqual(preferences());
  });

  it("keeps groups and navigation scoped to the account", () => {
    const alice = preferences();
    expect(saveExplorerPreferences("alice", alice)).toBe(true);
    expect(loadExplorerPreferences("alice")).toEqual(alice);
    expect(loadExplorerPreferences("bob")).toEqual(createDefaultExplorerPreferences());
    expect(loadExplorerPreferences(null)).toEqual(createDefaultExplorerPreferences());

    const local = { ...createDefaultExplorerPreferences(), groups: [group("personal:local", [])] };
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
      groups: [{ ...clean.groups[0]!, payload: "private payload" }],
    };
    expect(saveExplorerPreferences("alice", unsafe)).toBe(true);
    const stored = JSON.parse(localStorage.getItem(key())!);
    expect(stored).toEqual(clean);
    expect(localStorage.getItem(key())).not.toContain("private");
  });

  it("migrates only validated personal groups without depending on the old camera", () => {
    const groups = [group("personal:watchlist", ["ambibox:charger:abc", "ambibox:sensor:abc:powerAc"])];
    localStorage.setItem(legacyKey(), JSON.stringify({
      version: 1,
      personalGroups: groups,
      camera: "obsolete or invalid camera",
      positions: { "device:one": { x: 2, z: 8 } },
      endpoint: "mqtt://private.example",
      telemetry: [42],
    }));
    const migrated = { ...createDefaultExplorerPreferences(), groups };
    expect(loadExplorerPreferences("alice")).toEqual(migrated);
    expect(JSON.parse(localStorage.getItem(key())!)).toEqual(migrated);
    expect(localStorage.getItem(key())).not.toContain("camera");
    expect(loadExplorerPreferences("bob").groups).toEqual([]);
    expect(localStorage.getItem(legacyKey())).not.toBeNull();
  });

  it("does not resurrect deleted groups from legacy storage", () => {
    localStorage.setItem(legacyKey(), JSON.stringify({ version: 1, personalGroups: [group()] }));
    const empty = createDefaultExplorerPreferences();
    saveExplorerPreferences("alice", empty);
    expect(loadExplorerPreferences("alice")).toEqual(empty);
    localStorage.setItem(key(), "corrupt new preferences");
    expect(loadExplorerPreferences("alice")).toEqual(empty);
  });

  it.each([
    "not json",
    "null",
    JSON.stringify({ ...preferences(), version: 2 }),
    JSON.stringify({ ...preferences(), sidebarOpen: "yes" }),
    JSON.stringify({ ...preferences(), scopeKey: "" }),
    JSON.stringify({ ...preferences(), scopeKey: "path\ncontrol" }),
    JSON.stringify({ ...preferences(), scopeKey: "x".repeat(4097) }),
    JSON.stringify({ ...preferences(), groups: [group(), group()] }),
    JSON.stringify({ ...preferences(), groups: [group("__proto__")] }),
    JSON.stringify({ ...preferences(), groups: [group("valid", ["topic with spaces"])] }),
  ])("recovers a usable default from invalid storage", (saved) => {
    localStorage.setItem(key(), saved);
    expect(loadExplorerPreferences("alice")).toEqual(createDefaultExplorerPreferences());
    expect(Object.prototype).not.toHaveProperty("memberIds");
  });

  it("rejects malformed legacy groups atomically", () => {
    localStorage.setItem(legacyKey(), JSON.stringify({
      version: 1,
      personalGroups: [group(), { ...group("other"), color: "red" }],
    }));
    expect(loadExplorerPreferences("alice").groups).toEqual([]);
    expect(localStorage.getItem(key())).toBeNull();
  });

  it("bounds reads by UTF-8 bytes before parsing either storage format", () => {
    localStorage.setItem(key(), " ".repeat(MAX_EXPLORER_PREFERENCE_BYTES + 1));
    expect(loadExplorerPreferences("alice")).toEqual(createDefaultExplorerPreferences());

    const wide = JSON.stringify({ ...preferences(), discarded: "界".repeat(400_000) });
    expect(wide.length).toBeLessThan(MAX_EXPLORER_PREFERENCE_BYTES);
    localStorage.setItem(key(), wide);
    expect(loadExplorerPreferences("alice")).toEqual(createDefaultExplorerPreferences());
    localStorage.removeItem(key());
    localStorage.setItem(legacyKey(), wide);
    expect(loadExplorerPreferences("alice")).toEqual(createDefaultExplorerPreferences());
  });

  it("does not overwrite good preferences when an oversized save is rejected", () => {
    const original = preferences();
    saveExplorerPreferences("alice", original);
    const huge = preferences(membershipGroups(MAX_PERSONAL_MEMBERSHIPS).map((entry) => ({
      ...entry,
      memberIds: entry.memberIds.map((id) => `${"x".repeat(240)}:${id}`),
    })));
    expect(saveExplorerPreferences("alice", huge)).toBe(false);
    expect(loadExplorerPreferences("alice")).toEqual(original);
  });

  it("retains in-memory migration when writing storage is unavailable", () => {
    localStorage.setItem(legacyKey(), JSON.stringify({ version: 1, personalGroups: [group()] }));
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    expect(loadExplorerPreferences("alice").groups).toEqual([group()]);
    expect(saveExplorerPreferences("alice", preferences())).toBe(false);
  });

  it("stays usable when reading storage is disabled", () => {
    vi.spyOn(localStorage, "getItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    expect(loadExplorerPreferences("alice")).toEqual(createDefaultExplorerPreferences());
  });
});

describe("personal group validation", () => {
  it("copies only validated fields and accepts actual stable catalogue identifiers", () => {
    const source = group("personal:own", ["ambibox:broker:abc", "ambibox:sensor:abc:lineVoltage", "topic:telemetry/0.power"]);
    const parsed = parsePersonalGroups([{ ...source, name: "  Watchlist  ", endpoint: "private" }])!;
    expect(parsed).toEqual([source]);
    expect(parsed[0]).not.toBe(source);
    expect(parsed[0]!.memberIds).not.toBe(source.memberIds);
    expect(parsePersonalGroups([group("personal:own", ["a".repeat(280)])])).toBeDefined();
    expect(parsePersonalGroups([group("personal:own", ["a".repeat(281)])])).toBeUndefined();
  });

  it.each([
    undefined,
    {},
    [group(), group()],
    [{ ...group(), name: " " }],
    [{ ...group(), name: "n".repeat(121) }],
    [{ ...group(), name: "Control\ncharacter" }],
    [{ ...group(), color: "#fff" }],
    [group("constructor")],
    [group("personal:own", ["device:one", "device:one"])],
    [group("personal:own", ["prototype"])],
  ])("rejects malformed groups instead of importing a partial selection", (value) => {
    expect(parsePersonalGroups(value)).toBeUndefined();
  });

  it("enforces group, per-group membership, and aggregate bounds", () => {
    const groups = Array.from({ length: MAX_PERSONAL_GROUPS }, (_, index) => group(`personal:${index}`, []));
    expect(parsePersonalGroups(groups)).toHaveLength(MAX_PERSONAL_GROUPS);
    expect(parsePersonalGroups([...groups, group("one-more", [])])).toBeUndefined();
    const members = Array.from({ length: MAX_PERSONAL_GROUP_MEMBERS }, (_, index) => `stream:${index}`);
    expect(parsePersonalGroups([group("personal:many", members)])).toBeDefined();
    expect(parsePersonalGroups([group("personal:many", [...members, "stream:one-more"])] )).toBeUndefined();
    expect(parsePersonalGroups(membershipGroups(MAX_PERSONAL_MEMBERSHIPS))).toBeDefined();
    expect(parsePersonalGroups(membershipGroups(MAX_PERSONAL_MEMBERSHIPS + 1))).toBeUndefined();
  });
});
