import { constrainSidebarWidth } from "./sidebarSizing";

export interface ExplorerPreferences {
  version: 1;
  scopeKey: string;
  sidebarOpen: boolean;
  sidebarWidth?: number;
  onlineOnly?: boolean;
  favourites?: Array<{ kind: "service" | "reading"; id: string }>;
}

export const MAX_EXPLORER_PREFERENCE_BYTES = 1_048_576;

const INVALID_IDS = new Set(["__proto__", "constructor", "prototype"]);
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isId = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[A-Za-z0-9_:./-]{1,280}$/.test(value) &&
  !INVALID_IDS.has(value);
const isScopeKey = (value: unknown): value is string =>
  typeof value === "string" &&
  value.trim().length > 0 &&
  value.length <= 4096 &&
  !/\p{Cc}/u.test(value);

export function createDefaultExplorerPreferences(): ExplorerPreferences {
  return { version: 1, scopeKey: "system", sidebarOpen: true };
}

function validatedPreferences(value: unknown): ExplorerPreferences | undefined {
  if (
    !isRecord(value) ||
    value.version !== 1 ||
    !isScopeKey(value.scopeKey) ||
    typeof value.sidebarOpen !== "boolean"
  )
    return;
  return {
    version: 1,
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
    if (saved === null) return fallback;
    return validatedPreferences(parseStoredValue(saved)) ?? fallback;
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
    // Every copied field is bounded, so a valid copy is always small.
    const safe = validatedPreferences(prefs);
    if (!safe) return false;
    window.localStorage.setItem(storageKey(account), JSON.stringify(safe));
    return true;
  } catch {
    return false;
  }
}
