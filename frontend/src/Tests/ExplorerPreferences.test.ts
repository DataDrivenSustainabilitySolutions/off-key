import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createDefaultExplorerPreferences,
  createGroup,
  deleteGroup,
  GROUP_COLORS,
  loadExplorerPreferences,
  MAX_EXPLORER_PREFERENCE_BYTES,
  MAX_PERSONAL_GROUP_MEMBERS,
  MAX_PERSONAL_GROUPS,
  MAX_PERSONAL_MEMBERSHIPS,
  parsePersonalGroups,
  PERSONAL_GROUP_COLORS,
  reconcileExplorerPreferences,
  saveExplorerPreferences,
  toggleExplorerFavourite,
  toggleGroupMember,
  updateGroup,
  type ExplorerPreferences,
  type PersonalGroup,
} from "@/features/explorer/preferences";

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
  scopeKey: 'topic:["broker:one","device/evCharger/0"]',
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

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

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

    const local = createGroup(createDefaultExplorerPreferences(), "Local only");
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

describe("personal group validation and editing", () => {
  it("copies only validated fields and accepts actual stable catalogue identifiers", () => {
    const source = group("personal:own", ["ambibox:broker:abc", "ambibox:sensor:abc:lineVoltage", "topic:device/evCharger/0.power"]);
    const parsed = parsePersonalGroups([{ ...source, name: "  Watchlist  ", endpoint: "private" }])!;
    expect(parsed).toEqual([source]);
    expect(parsed[0]).not.toBe(source);
    expect(parsed[0]!.memberIds).not.toBe(source.memberIds);
    expect(parsePersonalGroups([group("personal:own", ["a".repeat(280)])])).toBeDefined();
    expect(parsePersonalGroups([group("personal:own", ["a".repeat(281)])])).toBeUndefined();
    expect(GROUP_COLORS.map(({ value }) => value)).toEqual(PERSONAL_GROUP_COLORS);
    expect(new Set(PERSONAL_GROUP_COLORS).size).toBe(6);
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

  it("creates, renames, recolours and deletes groups without mutating source data", () => {
    const initial = createDefaultExplorerPreferences();
    const created = createGroup(initial, "  Critical assets  ", "device:one");
    const id = created.groups[0]!.id;
    expect(initial.groups).toEqual([]);
    expect(created.groups[0]).toMatchObject({ name: "Critical assets", memberIds: ["device:one"] });
    const renamed = updateGroup(created, id, { name: "  West building  ", color: "#4499aa" });
    expect(renamed.groups[0]).toMatchObject({ name: "West building", color: "#4499aa" });
    expect(created.groups[0]!.name).toBe("Critical assets");
    expect(deleteGroup(renamed, id).groups).toEqual([]);
    expect(renamed.groups).toHaveLength(1);
  });

  it("allows overlapping groups while retaining the object's original identity", () => {
    const one = createGroup(createDefaultExplorerPreferences(), "Watchlist", "device:one");
    const two = createGroup(one, "Maintenance", "device:one");
    const first = two.groups[0]!.id;
    const second = two.groups[1]!.id;
    const added = toggleGroupMember(two, first, "stream:temperature");
    expect(added.groups[0]!.memberIds).toEqual(["device:one", "stream:temperature"]);
    expect(added.groups[1]!.memberIds).toEqual(["device:one"]);
    const removed = toggleGroupMember(added, first, "device:one");
    expect(removed.groups[0]!.memberIds).toEqual(["stream:temperature"]);
    expect(removed.groups[1]!.id).toBe(second);
    expect(removed.groups[1]!.memberIds).toEqual(["device:one"]);
    expect(Object.keys(removed).sort()).toEqual(["groups", "scopeKey", "sidebarOpen", "version"]);
  });

  it("returns the same preferences for invalid or unchanged edits", () => {
    const saved = preferences();
    const id = saved.groups[0]!.id;
    expect(createGroup(saved, " ")).toBe(saved);
    expect(createGroup(saved, "Valid", "bad id")).toBe(saved);
    expect(updateGroup(saved, id, { name: "n".repeat(121) })).toBe(saved);
    expect(updateGroup(saved, id, { color: "red" })).toBe(saved);
    expect(updateGroup(saved, id, { name: " Watchlist " })).toBe(saved);
    expect(updateGroup(saved, "missing", { name: "Valid" })).toBe(saved);
    expect(deleteGroup(saved, "missing")).toBe(saved);
    expect(toggleGroupMember(saved, id, "bad id")).toBe(saved);
    expect(toggleGroupMember(saved, "missing", "device:one")).toBe(saved);
  });

  it("limits additions while still allowing removals and empty group creation", () => {
    const groupLimit = preferences(Array.from({ length: MAX_PERSONAL_GROUPS }, (_, index) => group(`personal:${index}`, [])));
    expect(createGroup(groupLimit, "One more")).toBe(groupLimit);

    const memberLimit = preferences(membershipGroups(MAX_PERSONAL_MEMBERSHIPS));
    expect(toggleGroupMember(memberLimit, "personal:0", "stream:new")).toBe(memberLimit);
    expect(toggleGroupMember(memberLimit, "personal:3", "stream:new")).toBe(memberLimit);
    expect(createGroup(memberLimit, "Cannot add member", "stream:new")).toBe(memberLimit);
    expect(createGroup(memberLimit, "Empty is allowed").groups).toHaveLength(memberLimit.groups.length + 1);
    const removed = toggleGroupMember(memberLimit, "personal:0", "stream:0:0");
    expect(removed.groups[0]!.memberIds).toHaveLength(MAX_PERSONAL_GROUP_MEMBERS - 1);
    const addedBack = toggleGroupMember(removed, "personal:3", "stream:new");
    expect(addedBack.groups[3]!.memberIds).toContain("stream:new");
  });
});

describe("reconciling a loaded catalogue", () => {
  it("keeps saved references untouched until reconciliation is explicitly requested", () => {
    const saved = preferences([group("personal:own", ["device:one", "stream:missing"])]);
    saveExplorerPreferences("alice", saved);
    expect(loadExplorerPreferences("alice").groups[0]!.memberIds).toEqual(saved.groups[0]!.memberIds);
    const reconciled = reconcileExplorerPreferences(saved, new Set(["device:one"]), new Set(["system"]));
    expect(reconciled.groups[0]!.memberIds).toEqual(["device:one"]);
    expect(reconciled.scopeKey).toBe("system");
    expect(reconciled.sidebarOpen).toBe(false);
    expect(saved.groups[0]!.memberIds).toEqual(["device:one", "stream:missing"]);
  });

  it("preserves empty personal groups and stable references when the catalogue is unchanged", () => {
    const saved = preferences([group(), group("personal:empty", [])]);
    const same = reconcileExplorerPreferences(saved, new Set(["device:one"]), new Set([saved.scopeKey]));
    expect(same).toBe(saved);
    const changed = reconcileExplorerPreferences(saved, new Set(), new Set([saved.scopeKey]));
    expect(changed.groups).toHaveLength(2);
    expect(changed.groups[0]!.memberIds).toEqual([]);
    expect(changed.groups[1]).toBe(saved.groups[1]);
    expect(changed.scopeKey).toBe(saved.scopeKey);
  });
});
