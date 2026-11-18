export const parseNumericUserId = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isInteger(value) && value > 0) {
    return value;
  }
  if (typeof value === "string" && /^\d+$/.test(value.trim())) {
    const id = Number(value.trim());
    return id > 0 ? id : null;
  }
  return null;
};

export const getTokenPayload = (token: string): Record<string, unknown> | null => {
  try {
    const tokenParts = token.split(".");
    if (tokenParts.length !== 3) {
      return null;
    }
    const encodedPayload = tokenParts[1];
    if (!encodedPayload) {
      return null;
    }
    const base64Standard = encodedPayload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64Standard.padEnd(
      base64Standard.length + ((4 - (base64Standard.length % 4)) % 4),
      "="
    );
    const payload = JSON.parse(atob(padded));
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
};

export const getUserIdFromToken = (token: string): number | null => {
  const payload = getTokenPayload(token);
  return payload ? parseNumericUserId(payload.user_id) ?? parseNumericUserId(payload.sub) : null;
};

// Seconds the server's clock runs ahead of this browser's. Token expiry is
// judged on the server's clock, so a browser whose clock is off neither signs
// out early nor rejects every renewed token.
let serverClockOffset = 0;

/** Learn the server's clock from a token that was issued `expiresIn` seconds before its expiry. */
export const syncServerClock = (token: string, expiresIn: unknown): void => {
  const exp = getTokenPayload(token)?.exp;
  if (typeof exp !== "number" || typeof expiresIn !== "number" || !Number.isFinite(exp) || !(expiresIn > 0)) return;
  const offset = exp - expiresIn - Date.now() / 1000;
  // Ignore request latency; only a real clock difference matters.
  serverClockOffset = Math.abs(offset) < 5 ? 0 : offset;
};

/** Now, in seconds, on the server's clock. */
const serverNow = (): number => Date.now() / 1000 + serverClockOffset;

/** Milliseconds until the token expires (negative once it has). */
export const tokenRemainingMs = (token: string): number | null => {
  const exp = getTokenPayload(token)?.exp;
  return typeof exp === "number" && Number.isFinite(exp) ? (exp - serverNow()) * 1000 : null;
};

export const isTokenExpired = (token: string): boolean => {
  const remaining = tokenRemainingMs(token);
  return remaining === null || remaining <= 0;
};
