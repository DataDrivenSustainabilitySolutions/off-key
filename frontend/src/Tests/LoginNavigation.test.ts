import { describe, expect, it } from "vitest";
import { loginDestination, loginHref } from "@/auth/login-navigation";

describe("login destinations", () => {
  it.each([
    "/sources?reading=air-temperature#history",
    "/?create=monitoring&reading=temperature",
    "/details/roof?from=2026-11-01&to=2026-11-02",
  ])("preserves a workspace path, query and fragment: %s", destination => {
    expect(loginDestination(destination)).toBe(destination);
  });

  it.each([
    null, undefined, {}, "", "sources", "https://outside.example/", "//outside.example/",
    "/\\outside.example/", "/\n/outside.example/", "/login", "/login/?returnTo=/sources",
    "/sources/../login", "/%6cogin", "/LOGIN", "/reset-password%2f#token=private",
    "/register#token=private", "/verify", "/forgot-password", "/reset-password#token=private",
  ])("falls back to home for external or authentication destinations: %j", destination => {
    expect(loginDestination(destination)).toBe("/");
  });

  it("carries the full destination through a login-page reload", () => {
    const target = "/sources?reading=air-temperature#history";
    const href = loginHref({ pathname: "/sources", search: "?reading=air-temperature", hash: "#history" });
    const loginUrl = new URL(href, "https://dashboard.example");
    expect(loginUrl.pathname).toBe("/login");
    expect(loginDestination(loginUrl.searchParams.get("returnTo"))).toBe(target);
  });

  it("keeps normal sign-in simple and does not carry invitation tokens into the URL", () => {
    expect(loginHref({ pathname: "/", search: "", hash: "" })).toBe("/login");
    expect(loginHref({ pathname: "/register", search: "", hash: "#token=private" })).toBe("/login");
  });
});
