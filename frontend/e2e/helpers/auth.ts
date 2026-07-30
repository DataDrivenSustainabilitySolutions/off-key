import { expect, type Locator, type Page } from "@playwright/test";

import { waitForVerificationLink } from "./mailpit";

const PASSWORD = "PlaywrightPass123!";

type LoginOptions = {
  rememberMe?: boolean;
};

const fillAndVerifyFields = async (
  fields: ReadonlyArray<readonly [field: Locator, value: string]>,
): Promise<void> => {
  await expect(async () => {
    for (const [field, value] of fields) {
      await field.fill(value);
    }
    const actualValues = await Promise.all(
      fields.map(([field]) => field.inputValue()),
    );
    expect(actualValues).toEqual(fields.map(([, value]) => value));
  }).toPass({ timeout: 30_000 });
};

export const createRunScopedEmail = (): string => {
  const timestamp = Date.now();
  const randomSuffix = Math.random().toString(36).slice(2, 10);
  return `playwright-${timestamp}-${randomSuffix}@example.com`;
};

export const loginWithEmail = async (
  page: Page,
  email: string,
  options: LoginOptions = {}
): Promise<void> => {
  await fillAndVerifyFields([
    [page.locator("#email"), email],
    [page.locator("#password"), PASSWORD],
  ]);

  if (options.rememberMe) {
    await page.getByLabel(/stay logged in/i).check();
  }

  const loginResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/v1/auth/login"
  );
  await page.getByRole("button", { name: /log in/i }).click();

  const loginResponse = await loginResponsePromise;
  const loginBody = await loginResponse.text();
  expect(
    loginResponse.ok(),
    `Login failed (${loginResponse.status()}): ${loginBody}`
  ).toBeTruthy();

  await expect(page.getByPlaceholder(/search by charger id/i)).toBeVisible();
};

export const registerVerifyAndLogin = async (page: Page): Promise<string> => {
  const email = createRunScopedEmail();

  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: /login/i })).toBeVisible();

  await page.getByRole("link", { name: /register here/i }).click();
  await expect(page).toHaveURL(/\/register$/);

  // Vite may reload once after optimizing dependencies in a freshly rebuilt
  // Compose container. Refill and verify the complete controlled form as one
  // retryable operation so native validation cannot silently suppress submit.
  await fillAndVerifyFields([
    [page.locator("#email"), email],
    [page.locator("#password"), PASSWORD],
    [page.locator("#confirmPassword"), PASSWORD],
  ]);

  const registrationResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/v1/auth/register"
  );
  await page.getByRole("button", { name: /register/i }).click();

  const registrationResponse = await registrationResponsePromise;
  const registrationBody = await registrationResponse.text();
  expect(
    registrationResponse.ok(),
    `Registration failed (${registrationResponse.status()}): ${registrationBody}`
  ).toBeTruthy();

  await expect(page.getByText(/registration successful/i)).toBeVisible();

  const verificationLink = await waitForVerificationLink(email);
  await page.goto(verificationLink);
  await expect(page.getByText(/email verified successfully/i)).toBeVisible();

  await page.getByRole("button", { name: /go to login/i }).click();
  await expect(page).toHaveURL(/\/login$/);

  await loginWithEmail(page, email);

  return email;
};
