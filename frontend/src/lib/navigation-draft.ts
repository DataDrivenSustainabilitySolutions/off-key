import { useCallback, useState, type SetStateAction } from "react";

const drafts = new Map<string, unknown>();
export function navigationDraft<T>(key: string, initial: () => T): T {
  if (!drafts.has(key)) drafts.set(key, initial());
  return drafts.get(key) as T;
}
export function rememberNavigation(key: string, value: unknown) { drafts.set(key, value); }
export const clearNavigationDrafts = () => drafts.clear();

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
