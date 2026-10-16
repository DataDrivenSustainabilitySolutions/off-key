import { constrainSidebarWidth } from "./sidebarSizing";

export interface PersonalGroup {
  id: string;
  name: string;
  color: string;
  memberIds: string[];
}

export interface ExplorerPreferences {
  version: 1;
  groups: PersonalGroup[];
  scopeKey: string;
  sidebarOpen: boolean;
  sidebarWidth?: number;
  onlineOnly?: boolean;
  favourites?: Array<{ kind: "service" | "reading"; id: string }>;
}

export const GROUP_COLORS = [
  { name: "Sage", value: "#398577" },
  { name: "Blue", value: "#6589b3" },
  { name: "Plum", value: "#aa80a6" },
  { name: "Amber", value: "#bb9657" },
  { name: "Slate", value: "#7c96a0" },
  { name: "Olive", value: "#9aab7d" },
] as const;
export const PERSONAL_GROUP_COLORS = GROUP_COLORS.map(({ value }) => value);
export const MAX_PERSONAL_GROUPS = 128;
export const MAX_PERSONAL_GROUP_MEMBERS = 10_000;
export const MAX_PERSONAL_MEMBERSHIPS = 32_768;
export const MAX_EXPLORER_PREFERENCE_BYTES = 1_048_576;

const INVALID_IDS = new Set(["__proto__", "constructor", "prototype"]);
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isId = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[A-Za-z0-9_:./-]{1,280}$/.test(value) &&
  !INVALID_IDS.has(value);
const isColor = (value: unknown): value is string =>
  typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value);
const isName = (value: unknown): value is string =>
  typeof value === "string" &&
  value.trim().length > 0 &&
  value.length <= 120 &&
  !/\p{Cc}/u.test(value);
const isScopeKey = (value: unknown): value is string =>
  typeof value === "string" &&
  value.trim().length > 0 &&
  value.length <= 4096 &&
  !/\p{Cc}/u.test(value);

export function createDefaultExplorerPreferences(): ExplorerPreferences {
  return { version: 1, groups: [], scopeKey: "system", sidebarOpen: true };
}

/** Validate and copy only names, colours, and references, including legacy groups. */
export function parsePersonalGroups(value: unknown): PersonalGroup[] | undefined {
  if (!Array.isArray(value) || value.length > MAX_PERSONAL_GROUPS) return;
  const groupIds = new Set<string>();
  let membershipCount = 0;
  const groups: PersonalGroup[] = [];
  for (const group of value) {
    if (
      !isRecord(group) ||
      !isId(group.id) ||
      groupIds.has(group.id) ||
      !isName(group.name) ||
      !isColor(group.color) ||
      !Array.isArray(group.memberIds) ||
      group.memberIds.length > MAX_PERSONAL_GROUP_MEMBERS
    )
      return;
    membershipCount += group.memberIds.length;
    if (membershipCount > MAX_PERSONAL_MEMBERSHIPS) return;
    const memberIds = new Set<string>();
    for (const memberId of group.memberIds) {
      if (!isId(memberId) || memberIds.has(memberId)) return;
      memberIds.add(memberId);
    }
    groupIds.add(group.id);
    groups.push({
      id: group.id,
      name: group.name.trim(),
      color: group.color,
      memberIds: [...memberIds],
    });
  }
  return groups;
}

function validatedPreferences(value: unknown): ExplorerPreferences | undefined {
  if (
    !isRecord(value) ||
    value.version !== 1 ||
    !isScopeKey(value.scopeKey) ||
    typeof value.sidebarOpen !== "boolean"
  )
    return;
  const groups = parsePersonalGroups(value.groups);
  if (!groups) return;
  return {
    version: 1,
    groups,
    scopeKey: value.scopeKey,
    sidebarOpen: value.sidebarOpen,
    ...(typeof value.onlineOnly === "boolean" ? { onlineOnly: value.onlineOnly } : {}),
    ...(typeof value.sidebarWidth === "number" && Number.isFinite(value.sidebarWidth)
      ? { sidebarWidth: constrainSidebarWidth(value.sidebarWidth) } : {}),
    ...(Array.isArray(value.favourites) && value.favourites.length <= 256 ? {
      favourites: value.favourites.filter((item): item is { kind: "service" | "reading"; id: string } => isRecord(item)
        && (item.kind === "service" || item.kind === "reading") && isId(item.id))
        .filter((item, index, items) => items.findIndex(other => other.kind === item.kind && other.id === item.id) === index)
        .map(item => ({ kind: item.kind, id: item.id })),
    } : {}),
  };
}

function storageKey(account: string | number | null): string {
  return `aberration:explorer:v1:${account ?? "local"}`;
}

export function toggleExplorerFavourite(prefs: ExplorerPreferences, kind: "service" | "reading", id: string): ExplorerPreferences {
  if (!isId(id)) return prefs;
  const favourites = prefs.favourites ?? [];
  const included = favourites.some(item => item.kind === kind && item.id === id);
  if (!included && favourites.length >= 256) return prefs;
  return { ...prefs, favourites: included ? favourites.filter(item => item.kind !== kind || item.id !== id) : [...favourites, { kind, id }] };
}

function fitsByteLimit(contents: string): boolean {
  // UTF-8 byte size, without allocating an encoded copy of oversized input.
  if (contents.length > MAX_EXPLORER_PREFERENCE_BYTES) return false;
  let bytes = 0;
  for (let index = 0; index < contents.length; index += 1) {
    const code = contents.charCodeAt(index);
    if (code < 0x80) bytes += 1;
    else if (code < 0x800) bytes += 2;
    else if (
      code >= 0xd800 &&
      code <= 0xdbff &&
      index + 1 < contents.length &&
      contents.charCodeAt(index + 1) >= 0xdc00 &&
      contents.charCodeAt(index + 1) <= 0xdfff
    ) {
      bytes += 4;
      index += 1;
    } else bytes += 3;
    if (bytes > MAX_EXPLORER_PREFERENCE_BYTES) return false;
  }
  return true;
}

function parseStoredValue(contents: string): unknown {
  if (!fitsByteLimit(contents)) return;
  return JSON.parse(contents) as unknown;
}

export function loadExplorerPreferences(
  account: string | number | null,
): ExplorerPreferences {
  const fallback = createDefaultExplorerPreferences();
  try {
    const saved = window.localStorage.getItem(storageKey(account));
    if (saved !== null)
      return validatedPreferences(parseStoredValue(saved)) ?? fallback;

    const legacy = window.localStorage.getItem(
      `aberration:spatial:system:v1:${account ?? "local"}`,
    );
    if (legacy === null) return fallback;
    const oldWorkspace = parseStoredValue(legacy);
    if (!isRecord(oldWorkspace) || oldWorkspace.version !== 1) return fallback;
    const groups = parsePersonalGroups(oldWorkspace.personalGroups);
    if (!groups) return fallback;
    const migrated = { ...fallback, groups };
    saveExplorerPreferences(account, migrated);
    return migrated;
  } catch {
    return fallback;
  }
}

/** False lets the UI report unavailable storage while retaining in-memory edits. */
export function saveExplorerPreferences(
  account: string | number | null,
  prefs: ExplorerPreferences,
): boolean {
  try {
    const safe = validatedPreferences(prefs);
    if (!safe) return false;
    const serialized = JSON.stringify(safe);
    if (!fitsByteLimit(serialized)) return false;
    window.localStorage.setItem(storageKey(account), serialized);
    return true;
  } catch {
    return false;
  }
}

/** Call only after a valid catalogue is loaded; temporary loading is not deletion. */
export function reconcileExplorerPreferences(
  prefs: ExplorerPreferences,
  validObjectIds: Set<string>,
  validScopeKeys: Set<string>,
): ExplorerPreferences {
  let groupsChanged = false;
  const groups = prefs.groups.map((group) => {
    const memberIds = group.memberIds.filter((id) => validObjectIds.has(id));
    if (memberIds.length === group.memberIds.length) return group;
    groupsChanged = true;
    return { ...group, memberIds };
  });
  const scopeKey = validScopeKeys.has(prefs.scopeKey) ? prefs.scopeKey : "system";
  if (!groupsChanged && scopeKey === prefs.scopeKey) return prefs;
  return { ...prefs, groups: groupsChanged ? groups : prefs.groups, scopeKey };
}

function membershipCount(prefs: ExplorerPreferences): number {
  return prefs.groups.reduce((total, group) => total + group.memberIds.length, 0);
}

let nextGroupId = 0;

function uniqueGroupId(groups: PersonalGroup[]): string {
  const existing = new Set(groups.map(({ id }) => id));
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid && !existing.has(`personal:${uuid}`)) return `personal:${uuid}`;
  let id: string;
  do {
    id = `personal:${Date.now().toString(36)}-${(++nextGroupId).toString(36)}`;
  } while (existing.has(id));
  return id;
}

export function createGroup(
  prefs: ExplorerPreferences,
  name: string,
  memberId?: string | null,
): ExplorerPreferences {
  const trimmed = name.trim();
  if (
    !isName(trimmed) ||
    prefs.groups.length >= MAX_PERSONAL_GROUPS ||
    (memberId != null &&
      (!isId(memberId) || membershipCount(prefs) >= MAX_PERSONAL_MEMBERSHIPS))
  )
    return prefs;
  const group: PersonalGroup = {
    id: uniqueGroupId(prefs.groups),
    name: trimmed,
    color: PERSONAL_GROUP_COLORS[prefs.groups.length % PERSONAL_GROUP_COLORS.length]!,
    memberIds: memberId != null ? [memberId] : [],
  };
  return { ...prefs, groups: [...prefs.groups, group] };
}

export function updateGroup(
  prefs: ExplorerPreferences,
  id: string,
  change: Partial<Pick<PersonalGroup, "name" | "color">>,
): ExplorerPreferences {
  const name = change.name?.trim();
  if (
    (name !== undefined && !isName(name)) ||
    (change.color !== undefined && !isColor(change.color))
  )
    return prefs;
  const target = prefs.groups.find((group) => group.id === id);
  if (
    !target ||
    ((name === undefined || target.name === name) &&
      (change.color === undefined || target.color === change.color))
  )
    return prefs;
  return {
    ...prefs,
    groups: prefs.groups.map((group) =>
      group.id === id
        ? {
            ...group,
            ...(name !== undefined ? { name } : {}),
            ...(change.color !== undefined ? { color: change.color } : {}),
          }
        : group,
    ),
  };
}

export function toggleGroupMember(
  prefs: ExplorerPreferences,
  id: string,
  memberId: string,
): ExplorerPreferences {
  if (!isId(memberId)) return prefs;
  const target = prefs.groups.find((group) => group.id === id);
  if (!target) return prefs;
  const included = target.memberIds.includes(memberId);
  if (
    !included &&
    (target.memberIds.length >= MAX_PERSONAL_GROUP_MEMBERS ||
      membershipCount(prefs) >= MAX_PERSONAL_MEMBERSHIPS)
  )
    return prefs;
  return {
    ...prefs,
    groups: prefs.groups.map((group) =>
      group.id !== id
        ? group
        : {
            ...group,
            memberIds: included
              ? group.memberIds.filter((member) => member !== memberId)
              : [...group.memberIds, memberId],
          },
    ),
  };
}

export function deleteGroup(
  prefs: ExplorerPreferences,
  id: string,
): ExplorerPreferences {
  if (!prefs.groups.some((group) => group.id === id)) return prefs;
  return { ...prefs, groups: prefs.groups.filter((group) => group.id !== id) };
}
