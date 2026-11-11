const INTERNAL_ORIGIN = "https://app.invalid";
const AUTH_PATHS = new Set(["/login", "/register", "/verify", "/forgot-password", "/reset-password"]);

/** A login may resume an internal page, never another origin or an authentication loop. */
export function loginDestination(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/";
  try {
    const url = new URL(value, INTERNAL_ORIGIN);
    const pathname = decodeURIComponent(url.pathname).replace(/\/+$/u, "").toLowerCase();
    if (url.origin !== INTERNAL_ORIGIN || AUTH_PATHS.has(pathname)) return "/";
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/";
  }
}

export function loginHref(location: { pathname: string; search: string; hash: string }): string {
  const destination = loginDestination(`${location.pathname}${location.search}${location.hash}`);
  return destination === "/" ? "/login" : `/login?returnTo=${encodeURIComponent(destination)}`;
}
