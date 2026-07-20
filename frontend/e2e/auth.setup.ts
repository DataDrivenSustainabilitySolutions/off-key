import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test as setup } from "@playwright/test";

import { loginWithEmail, registerVerifyAndLogin } from "./helpers/auth";

const AUTH_STATE_FILE = fileURLToPath(
  new URL("../test-results/.auth/user.json", import.meta.url)
);

setup("registers, verifies, logs in, and prepares authenticated state", async ({
  page,
}) => {
  const email = await registerVerifyAndLogin(page);

  await expect(page.getByPlaceholder(/search by charger id/i)).toBeVisible();
  await expect(page.getByLabel(/all/i)).toBeVisible();
  await expect(page.getByLabel(/online/i)).toBeVisible();
  await expect(page.getByLabel(/offline/i)).toBeVisible();
  await expect(page.getByRole("switch")).toBeVisible();
  await expect(page.getByRole("link", { name: /off\/key/i })).toBeVisible();
  await expect
    .poll(async () => page.getByText(/loading data/i).count())
    .toBe(0);

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

  expect(persistentState.localAuthToken).toBeTruthy();
  expect(persistentState.storageType).toBe("localStorage");
  expect(persistentState.sessionAuthToken).toBeNull();

  await mkdir(dirname(AUTH_STATE_FILE), { recursive: true });
  await page.context().storageState({ path: AUTH_STATE_FILE });
});
