import { useCallback, useState, type SetStateAction } from "react";

const drafts = new Map<string, unknown>();
export function navigationDraft<T>(key: string, initial: () => T): T {
  if (!drafts.has(key)) drafts.set(key, initial());
  return drafts.get(key) as T;
}
export function rememberNavigation(key: string, value: unknown) { drafts.set(key, value); }
export const clearNavigationDrafts = () => {
  drafts.clear();
  try {
    for (const key of Object.keys(sessionStorage))
      if (key.startsWith(STORED_PREFIX)) sessionStorage.removeItem(key);
  } catch { /* Storage can be unavailable in private or embedded contexts. */ }
};

const STORED_PREFIX = "off-key:draft:";
/** Tab-scoped copy of a draft that should survive a reload; cleared with the in-memory drafts. */
export function readStoredDraft(key: string): unknown {
  try {
    const value = sessionStorage.getItem(STORED_PREFIX + key);
    return value === null ? undefined : JSON.parse(value);
  } catch {
    return undefined;
  }
}
export function storeDraft(key: string, value: unknown | undefined) {
  try {
    if (value === undefined) sessionStorage.removeItem(STORED_PREFIX + key);
    else sessionStorage.setItem(STORED_PREFIX + key, JSON.stringify(value));
  } catch { /* A full or unavailable store only loses reload recovery. */ }
}

/** Account-prefixed keys retain form state during a setup detour, in memory only. */
export function useNavigationDraft<T>(key: string | undefined, initial: T | (() => T)) {
  const [value, setValue] = useState<T>(() => key ? navigationDraft(key, () => typeof initial === "function" ? (initial as () => T)() : initial)
    : typeof initial === "function" ? (initial as () => T)() : initial);
  const update = useCallback((next: SetStateAction<T>) => {
    setValue(previous => {
      const result = typeof next === "function" ? (next as (current: T) => T)(previous) : next;
      if (key) drafts.set(key, result);
      return result;
    });
  }, [key]);
  return [value, update] as const;
}
