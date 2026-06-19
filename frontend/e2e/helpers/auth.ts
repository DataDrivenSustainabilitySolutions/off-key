import { expect, type Page } from "@playwright/test";

import { waitForVerificationLink } from "./mailpit";

const PASSWORD = "PlaywrightPass123!";

export const createRunScopedEmail = (): string => {
  const timestamp = Date.now();
  const randomSuffix = Math.random().toString(36).slice(2, 10);
  return `playwright-${timestamp}-${randomSuffix}@example.com`;
};

export const registerVerifyAndLogin = async (page: Page): Promise<string> => {
  const email = createRunScopedEmail();

  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: /login/i })).toBeVisible();

  await page.getByRole("link", { name: /register here/i }).click();
  await expect(page).toHaveURL(/\/register$/);

  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#confirmPassword").fill(PASSWORD);
  await page.getByRole("button", { name: /register/i }).click();

  await expect(page.getByText(/registration successful/i)).toBeVisible();

  const verificationLink = await waitForVerificationLink(email);
  await page.goto(verificationLink);
  await expect(page.getByText(/email verified successfully/i)).toBeVisible();

  await page.getByRole("button", { name: /go to login/i }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /log in/i }).click();

  await expect(page.getByPlaceholder(/search by charger id/i)).toBeVisible();

  return email;
};
