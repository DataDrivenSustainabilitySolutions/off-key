import { expect, test, type Page, type Route } from "@playwright/test";
import { installSidebarMockApi } from "./helpers/sidebarMockApi";

test.use({ storageState: { cookies: [], origins: [] } });

async function signIn(page: Page) {
  await page.getByLabel("Email", { exact: true }).fill("operator@example.test");
  await page.getByLabel("Password", { exact: true }).fill("BrowserTestPassword!");
  await page.getByLabel("Password", { exact: true }).press("Enter");
}

test("sign-in resumes a protected link through a reload and an expired session", async ({ page }) => {
  await installSidebarMockApi(page, { authenticated: false });
  await page.route("**/api/v1/auth/login", route => {
    const payload = Buffer.from(JSON.stringify({ sub: "1", user_id: 1, exp: 4_102_444_800 })).toString("base64");
    return route.fulfill({ json: { access_token: `e2e.${payload}.signature`, token_type: "bearer" } });
  });
  const destination = "/sources?reading=air-temperature#history";
  await page.goto(destination);
  await expect(page).toHaveURL(url => url.pathname === "/login" && url.searchParams.get("returnTo") === destination);
  await page.reload();
  await expect(page.getByRole("main", { name: "Sign in", exact: true })).toBeVisible();
  await signIn(page);
  await expect(page).toHaveURL(url => `${url.pathname}${url.search}${url.hash}` === destination);
  await expect(page.getByRole("main", { name: "Sources workspace" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Reading preview" }).getByRole("button", { name: "Rename reading" })).toHaveText("Air temperature");

  const expire = (route: Route) => route.fulfill({ status: 401, json: { detail: "Session expired" } });
  await page.route("**/api/v1/catalogue", expire);
  await page.reload();
  await expect(page).toHaveURL(url => url.pathname === "/login" && url.searchParams.get("returnTo") === destination);
  await page.unroute("**/api/v1/catalogue", expire);
  await signIn(page);
  await expect(page).toHaveURL(url => `${url.pathname}${url.search}${url.hash}` === destination);
  await expect(page.getByRole("main", { name: "Sources workspace" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Reading preview" }).getByRole("button", { name: "Rename reading" })).toHaveText("Air temperature");
});

test("a demo visitor can complete browser verification after admin logout and return", async ({ page }) => {
  await installSidebarMockApi(page, { authenticated: false });
  const payload = Buffer.from(JSON.stringify({ sub: "1", user_id: 1, exp: 4_102_444_800 })).toString("base64");
  await page.route("**/api/v1/auth/login", route => route.fulfill({
    json: { access_token: `e2e.${payload}.signature`, token_type: "bearer" },
  }));
  let challenged = false;
  await page.route("**/api/v1/demo", route => challenged
    ? route.fulfill({ status: 403, contentType: "text/html", headers: { "cf-mitigated": "challenge" }, body: "<html>Verify browser</html>" })
    : route.fulfill({ json: { enabled: true, sources: [] } }));
  await page.route("**/api/v1/auth/logout", route => {
    challenged = true;
    return route.fulfill({ status: 204 });
  });
  const destination = "/sources?reading=air-temperature#history";
  await page.goto(`/login?returnTo=${encodeURIComponent(destination)}`);
  await signIn(page);
  await expect(page.getByRole("main", { name: "Sources workspace" })).toBeVisible();
  await page.getByRole("button", { name: "Account menu", exact: true }).first().click();
  await page.getByRole("menuitem", { name: "Log out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto(destination);
  await expect(page.getByRole("alert")).toContainText("Cloudflare needs to verify your browser");
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toHaveCount(0);

  // Only a document navigation can complete Cloudflare's challenge; repeating
  // the background fetch must not make this test pass.
  const navigation = page.waitForRequest(request => request.isNavigationRequest()
    && new URL(request.url()).pathname === "/sources");
  page.on("request", request => {
    if (request.isNavigationRequest()) challenged = false;
  });
  await page.getByRole("button", { name: "Verify browser", exact: true }).click();
  await navigation;
  await expect(page).toHaveURL(url => `${url.pathname}${url.search}${url.hash}` === destination);
  await expect(page.getByRole("main", { name: "Sources workspace" })).toBeVisible();
  await page.getByRole("button", { name: "Demo menu", exact: true }).first().click();
  await expect(page.getByText("Demo visitor · Read only", { exact: true })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Admin sign in", exact: true })).toBeVisible();
});
