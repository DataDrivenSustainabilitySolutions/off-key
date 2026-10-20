import { expect, type Page } from "@playwright/test";
import type { PipelineCatalog } from "../../src/types/pipelines.generated";
import { loginWithEmail, accessToken } from "./auth";

/** Each independent production invocation starts from real authentication. */
export async function loginPipelineWorkspace(page: Page) {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("token_storage_type");
    localStorage.removeItem("session_member");
    sessionStorage.removeItem("auth_token");
  });
  await page.context().clearCookies();
  await page.goto("/login");
  await loginWithEmail(
    page,
    process.env.SUPERUSER_MAIL ?? "admin@example.com",
    { rememberMe: true },
  );
  const token = await accessToken(page);
  expect(token).toBeTruthy();
  await expect
    .poll(
      async () => {
        try {
          const response = await page.request.get(
            "/api/v1/monitors/pipelines/catalog",
            {
              headers: { Authorization: `Bearer ${token}` },
              timeout: 5_000,
            },
          );
          if (!response.ok()) return `HTTP ${response.status()}`;
          const catalog = (await response.json()) as PipelineCatalog;
          return catalog.authoring_enabled ? "enabled" : "disabled";
        } catch {
          return "unavailable";
        }
      },
      {
        timeout: 30_000,
        intervals: [500, 1_000, 2_000],
        message: "Pipeline authoring catalog is ready after service startup",
      },
    )
    .toBe("enabled");
}
