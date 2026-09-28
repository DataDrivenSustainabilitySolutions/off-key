import { expect, type Locator, type Page } from "@playwright/test";

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

export const loginWithEmail = async (
  page: Page,
  email: string,
  options: LoginOptions = {},
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
      new URL(response.url()).pathname === "/api/v1/auth/login",
  );
  await page.getByRole("button", { name: /log in/i }).click();

  const loginResponse = await loginResponsePromise;
  const loginBody = await loginResponse.text();
  expect(
    loginResponse.ok(),
    `Login failed (${loginResponse.status()}): ${loginBody}`,
  ).toBeTruthy();

  await expect(page.getByPlaceholder(/search by charger id/i)).toBeVisible();
};

export const acceptInvitationAndLogin = async (page: Page, email: string): Promise<string> => {
  const link = process.env.E2E_BOOTSTRAP_URL;
  if (!link) throw new Error("Run the operator bootstrap command and set E2E_BOOTSTRAP_URL.");
  await page.goto(link);
  await fillAndVerifyFields([
    [page.locator("#password"), PASSWORD],
    [page.locator("#confirmPassword"), PASSWORD],
  ]);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page.getByRole("status")).toContainText("Your account is ready");
  await page.getByRole("link", { name: "Log in" }).click();
  await loginWithEmail(page, email);
  return email;
};
