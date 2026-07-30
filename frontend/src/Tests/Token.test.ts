import { describe, expect, it } from "vitest";

import { getTokenPayload } from "../auth/token";

const encodeBase64Url = (value: object): string =>
  btoa(JSON.stringify(value))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");

describe("getTokenPayload", () => {
  it("decodes the payload from a three-segment token", () => {
    const token = `header.${encodeBase64Url({ sub: "user@example.com" })}.signature`;

    expect(getTokenPayload(token)).toEqual({ sub: "user@example.com" });
  });

  it.each(["not-a-token", "header.payload", "header..signature"])(
    "rejects malformed token %s",
    (token) => {
      expect(getTokenPayload(token)).toBeNull();
    }
  );
});
