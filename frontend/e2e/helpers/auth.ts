import { expect, type Locator, type Page } from "@playwright/test";

export const PASSWORD = "PlaywrightPass123!";

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
    await page.getByLabel(/remember this device/i).check();
  }

  // The gateway allows 10 logins per account a minute. Journeys that sign in
  // afresh can exceed that, so wait for the next window instead of failing.
  const retryUntil = Date.now() + 75_000;
  let loginResponse;
  for (;;) {
    const loginResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/v1/auth/login",
    );
    await page.getByRole("button", { name: /log in/i }).click();
    loginResponse = await loginResponsePromise;
    if (loginResponse.status() !== 429 || Date.now() > retryUntil) break;
    await page.waitForTimeout(5_000);
  }
  const loginBody = await loginResponse.text();
  expect(
    loginResponse.ok(),
    `Login failed (${loginResponse.status()}): ${loginBody}`,
  ).toBeTruthy();

  await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
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

/** Remembered access tokens live only in page memory; mint one from the session cookie. */
export const accessToken = async (page: Page): Promise<string | null> =>
  page.evaluate(async () => {
    const unchecked = sessionStorage.getItem("auth_token");
    if (unchecked) return unchecked;
    const response = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "include",
      headers: { "X-Off-Key-Session": "1" },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { access_token?: unknown };
    return typeof body.access_token === "string" ? body.access_token : null;
  });
