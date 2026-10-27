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
    await expect(page.getByRole("button", { name: "Application menu", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "No monitoring services", exact: true })).toBeVisible();

    const sessionState = await page.evaluate(() => ({
      localAuthToken: localStorage.getItem("auth_token"),
      storageType: localStorage.getItem("token_storage_type"),
      sessionAuthToken: sessionStorage.getItem("auth_token"),
    }));

    expect(sessionState.localAuthToken).toBeNull();
    expect(sessionState.storageType).toBe("sessionStorage");
    expect(sessionState.sessionAuthToken).toBeTruthy();

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
    expect(
      (await page.context().cookies()).some(
        (cookie) => cookie.name === "off_key_remembered_session" && cookie.httpOnly,
      ),
    ).toBe(true);

    await mkdir(dirname(AUTH_STATE_FILE), { recursive: true });
    await page.context().storageState({ path: AUTH_STATE_FILE });
  },
);
