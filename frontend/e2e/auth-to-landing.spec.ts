import { expect, test } from "@playwright/test";

import { registerVerifyAndLogin } from "./helpers/auth";

test.describe("auth to landing smoke", () => {
  test("registers, verifies, logs in, and renders the landing shell", async ({
    page,
  }) => {
    await registerVerifyAndLogin(page);

    await expect(page.getByPlaceholder(/search by charger id/i)).toBeVisible();
    await expect(page.getByLabel(/all/i)).toBeVisible();
    await expect(page.getByLabel(/online/i)).toBeVisible();
    await expect(page.getByLabel(/offline/i)).toBeVisible();
    await expect(page.getByRole("switch")).toBeVisible();
    await expect(page.getByRole("link", { name: /off\/key/i })).toBeVisible();
    await expect
      .poll(async () => page.getByText(/loading data/i).count())
      .toBe(0);

    const storageState = await page.evaluate(() => ({
      localAuthToken: localStorage.getItem("auth_token"),
      storageType: localStorage.getItem("token_storage_type"),
      sessionAuthToken: sessionStorage.getItem("auth_token"),
    }));

    expect(storageState.localAuthToken).toBeNull();
    expect(storageState.storageType).toBe("sessionStorage");
    expect(storageState.sessionAuthToken).toBeTruthy();
  });
});
