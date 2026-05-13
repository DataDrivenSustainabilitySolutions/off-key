import { describe, expect, it } from "vitest";

import { getUserIdFromToken } from "@/auth/token";

const encodeBase64Url = (value: object): string =>
  btoa(JSON.stringify(value))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");

const createUnsignedToken = (payload: object): string =>
  [
    encodeBase64Url({ alg: "none", typ: "JWT" }),
    encodeBase64Url(payload),
    "",
  ].join(".");

describe("AuthContext token parsing", () => {
  it("extracts numeric user_id claim from login tokens", () => {
    const token = createUnsignedToken({
      sub: "user@example.com",
      user_id: 42,
    });

    expect(getUserIdFromToken(token)).toBe(42);
  });

  it("does not treat an email subject as a user id", () => {
    const token = createUnsignedToken({ sub: "user@example.com" });

    expect(getUserIdFromToken(token)).toBeNull();
  });

  it("keeps compatibility with old numeric subject tokens", () => {
    const token = createUnsignedToken({ sub: "42" });

    expect(getUserIdFromToken(token)).toBe(42);
  });
});
