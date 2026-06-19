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
    const base64 = token.split(".")[1];
    const base64Standard = base64.replace(/-/g, "+").replace(/_/g, "/");
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
  try {
    const payload = getTokenPayload(token);
    if (!payload) {
      return null;
    }
    return parseNumericUserId(payload.user_id) ?? parseNumericUserId(payload.sub);
  } catch {
    return null;
  }
};

export const isTokenExpired = (token: string): boolean => {
  const payload = getTokenPayload(token);
  const exp = payload?.exp;

  if (typeof exp !== "number") {
    return true;
  }

  return exp < Date.now() / 1000;
};
