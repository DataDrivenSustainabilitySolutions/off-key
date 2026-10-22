// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { getTokenPayload, getUserIdFromToken, isTokenExpired } from "@/auth/token";

const encodeBase64Url = (value: unknown): string =>
  btoa(JSON.stringify(value))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");

const tokenWith = (payload: unknown): string =>
  [encodeBase64Url({ alg: "none", typ: "JWT" }), encodeBase64Url(payload), ""].join(".");

describe("getTokenPayload", () => {
  it("decodes the payload from a three-segment token", () => {
    expect(getTokenPayload(tokenWith({ sub: "user@example.com" }))).toEqual({
      sub: "user@example.com",
    });
  });

  it.each([
    "not-a-token",
    "header.payload",
    "header..signature",
    "header.%%%.signature",
    tokenWith([1, 2]),
    tokenWith("subject"),
    tokenWith(null),
  ])("rejects malformed token %s", (token) => {
    expect(getTokenPayload(token)).toBeNull();
  });
});

describe("getUserIdFromToken", () => {
  it.each([
    [{ sub: "user@example.com", user_id: 42 }, 42],
    [{ sub: "42" }, 42],
    [{ sub: "user@example.com" }, null],
    [{ user_id: 0 }, null],
    [{ sub: "-1" }, null],
    [{ user_id: 4.5 }, null],
  ])("reads %j as user id %s", (payload, expected) => {
    expect(getUserIdFromToken(tokenWith(payload))).toBe(expected);
  });

  it("returns null for unreadable tokens", () => {
    expect(getUserIdFromToken("not-a-token")).toBeNull();
  });
});

describe("isTokenExpired", () => {

  it("compares the exp claim with the current time in seconds", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    const now = Date.now() / 1000;

    expect(isTokenExpired(tokenWith({ exp: now + 60 }))).toBe(false);
    expect(isTokenExpired(tokenWith({ exp: now }))).toBe(true);
    expect(isTokenExpired(tokenWith({ exp: now - 60 }))).toBe(true);
  });

  it.each([{}, { exp: "tomorrow" }, { exp: null }])(
    "treats a token without a numeric exp %j as expired",
    (payload) => {
      expect(isTokenExpired(tokenWith(payload))).toBe(true);
    },
  );

  it("treats unreadable tokens as expired", () => {
    expect(isTokenExpired("not-a-token")).toBe(true);
  });
});
