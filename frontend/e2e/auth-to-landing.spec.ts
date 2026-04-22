import { expect, test } from "@playwright/test";

import { waitForVerificationLink } from "./helpers/mailpit";

const PASSWORD = "PlaywrightPass123!";

const createRunScopedEmail = (): string => {
  const timestamp = Date.now();
  const randomSuffix = Math.random().toString(36).slice(2, 10);
  return `playwright-${timestamp}-${randomSuffix}@example.com`;
};

test.describe("auth to landing smoke", () => {
  test("registers, verifies, logs in, and renders the landing shell", async ({
    page,
  }) => {
    const email = createRunScopedEmail();

    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
    await expect(
      page.getByRole("heading", { name: /login/i })
    ).toBeVisible();

    await page.getByRole("link", { name: /register here/i }).click();
    await expect(page).toHaveURL(/\/register$/);

    await page.locator("#email").fill(email);
    await page.locator("#password").fill(PASSWORD);
    await page.locator("#confirmPassword").fill(PASSWORD);
    await page.getByRole("button", { name: /register/i }).click();

    await expect(page.getByText(/registration successful/i)).toBeVisible();

    const verificationLink = await waitForVerificationLink(email);
    await page.goto(verificationLink);
    await expect(
      page.getByText(/email verified successfully/i)
    ).toBeVisible();

    await page.getByRole("button", { name: /go to login/i }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.locator("#email").fill(email);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /log in/i }).click();

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
