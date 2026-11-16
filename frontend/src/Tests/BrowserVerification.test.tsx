import { AxiosError } from "axios";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../lib/api-client";
import { BrowserVerificationError, isBrowserVerificationRequired } from "../lib/browser-verification";
import { BrowserVerificationNotice } from "../components/BrowserVerificationNotice";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ browserVerificationRequired: false }) }));

const original = apiClient.defaults.adapter;
const reload = vi.fn();
const challenge = vi.fn(async (config) => {
  throw new AxiosError("Forbidden", "403", config, undefined, {
    status: 403, statusText: "Forbidden", headers: { "cf-mitigated": "challenge" }, config, data: "<html>Just a moment</html>",
  });
});

const userActivation = (isActive: boolean) =>
  Object.defineProperty(navigator, "userActivation", { configurable: true, value: { isActive, hasBeenActive: isActive } });

describe("Cloudflare challenge on an open page", () => {
  afterEach(() => {
    apiClient.defaults.adapter = original;
    vi.unstubAllGlobals();
    reload.mockReset();
    challenge.mockClear();
    Reflect.deleteProperty(navigator, "userActivation");
  });

  const challenged = async () => {
    vi.stubGlobal("location", { ...window.location, reload });
    apiClient.defaults.adapter = challenge;
    await expect(apiClient.get("/v1/monitoring")).rejects.toBeInstanceOf(BrowserVerificationError);
    expect(isBrowserVerificationRequired()).toBe(true);
  };

  it("stops background polls from hitting the challenge again", async () => {
    await challenged();
    userActivation(false);
    await expect(apiClient.get("/v1/monitoring")).rejects.toBeInstanceOf(BrowserVerificationError);
    expect(challenge).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
  });

  it("turns a Retry click into the page reload that completes the check", async () => {
    await challenged();
    userActivation(true);
    await expect(apiClient.get("/v1/monitoring")).rejects.toBeInstanceOf(BrowserVerificationError);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("offers a page reload once any request was challenged", async () => {
    render(<BrowserVerificationNotice />);
    expect(screen.queryByRole("alert")).toBeNull();
    await challenged();
    fireEvent.click(await screen.findByRole("button", { name: "Reload page" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
