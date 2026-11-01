import { useLocation, useNavigate } from "react-router-dom";

/**
 * Settings open as an overlay above the current page. The open section lives in
 * the URL (`?settings=account`) so the overlay can be linked to, survives a reload
 * and closes with the browser's Back button, while the page underneath keeps its
 * own path, query and state.
 */
const SETTINGS_PARAM = "settings";
const SETTINGS_SECTIONS = ["account", "preferences", "catalogue", "status"] as const;
export type SettingsSection = typeof SETTINGS_SECTIONS[number];

/** Marks history entries that the overlay pushed itself, so closing can step back. */
const OPENED = "settingsOverlay";

export function settingsSectionOf(search: string): SettingsSection | null {
  const value = new URLSearchParams(search).get(SETTINGS_PARAM);
  return SETTINGS_SECTIONS.find(section => section === value) ?? null;
}

/** The current URL with the overlay at `section`, or without the overlay for null. */
export function settingsHref({ pathname, search, hash }: { pathname: string; search: string; hash?: string }, section: SettingsSection | null) {
  const params = new URLSearchParams(search);
  if (section) params.set(SETTINGS_PARAM, section);
  else params.delete(SETTINGS_PARAM);
  const query = params.toString();
  return `${pathname}${query ? `?${query}` : ""}${hash ?? ""}`;
}

// The element to focus once the overlay closes. Menu items unmount as the overlay
// opens, so the opener names a lasting element instead.
let returnFocus: HTMLElement | null = null;
export const settingsReturnFocus = () => returnFocus?.isConnected ? returnFocus : null;

export function useSettingsNavigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const section = settingsSectionOf(location.search);
  const state = (location.state ?? null) as Record<string, unknown> | null;
  return {
    section,
    /** Opens the overlay at `section` above the current page. */
    open: (next: SettingsSection, focusOnClose?: HTMLElement | null) => {
      returnFocus = focusOnClose ?? null;
      if (section) navigate(settingsHref(location, next), { replace: true, state });
      else navigate(settingsHref(location, next), { state: { ...state, [OPENED]: true } });
    },
    /** Switches sections without adding history, so one Back still closes the overlay. */
    select: (next: SettingsSection) => navigate(settingsHref(location, next), { replace: true, state }),
    close: () => {
      if (state?.[OPENED]) navigate(-1);
      else navigate(settingsHref(location, null), { replace: true, state });
    },
  };
}
