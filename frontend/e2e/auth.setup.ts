import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test as setup } from "@playwright/test";

import { loginWithEmail, acceptInvitationAndLogin } from "./helpers/auth";

const AUTH_STATE_FILE = process.env.PLAYWRIGHT_AUTH_STATE_FILE ?? fileURLToPath(
  new URL("../playwright/.auth/user.json", import.meta.url),
);

setup(
  "accepts the operator invitation and prepares authenticated state",
  async ({ page }) => {
    const email = await acceptInvitationAndLogin(
      page,
      process.env.SUPERUSER_MAIL ?? "admin@example.com",
    );

    await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
    await expect(page.getByRole("searchbox", { name: "Search catalogue", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Account menu", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "No monitors", exact: true })).toBeVisible();

    const sessionState = await page.evaluate(() => ({
      localAuthToken: localStorage.getItem("auth_token"),
      storageType: localStorage.getItem("token_storage_type"),
      sessionAuthToken: sessionStorage.getItem("auth_token"),
    }));

    // Every sign-in renews from an HttpOnly cookie; unchecked, it ends with the browser.
    expect(sessionState.localAuthToken).toBeNull();
    expect(sessionState.storageType).toBe("remembered");
    expect(sessionState.sessionAuthToken).toBeNull();
    const browserCookie = (await page.context().cookies()).find(
      (cookie) => cookie.name === "off_key_remembered_session",
    );
    expect(browserCookie?.httpOnly).toBe(true);
    expect(browserCookie?.expires).toBe(-1);

    await page.goto("/login");
    await loginWithEmail(page, email, { rememberMe: true });

    const persistentState = await page.evaluate(() => ({
      localAuthToken: localStorage.getItem("auth_token"),
      storageType: localStorage.getItem("token_storage_type"),
      sessionAuthToken: sessionStorage.getItem("auth_token"),
    }));

    // The bearer token stays in page memory; only the HttpOnly cookie persists.
    expect(persistentState.localAuthToken).toBeNull();
    expect(persistentState.storageType).toBe("remembered");
    expect(persistentState.sessionAuthToken).toBeNull();
    const rememberedCookie = (await page.context().cookies()).find(
      (cookie) => cookie.name === "off_key_remembered_session",
    );
    expect(rememberedCookie?.httpOnly).toBe(true);
    // "Remember this device" keeps the cookie across browser restarts.
    expect(rememberedCookie?.expires).toBeGreaterThan(Date.now() / 1000 + 29 * 24 * 60 * 60);

    await mkdir(dirname(AUTH_STATE_FILE), { recursive: true });
    await page.context().storageState({ path: AUTH_STATE_FILE });
  },
);
