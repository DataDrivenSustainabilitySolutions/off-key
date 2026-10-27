import { expect, type APIRequestContext, type Page } from "@playwright/test";
import type { PipelineCatalog, PipelineView } from "../../src/types/pipelines.generated";
import { accessToken } from "./auth";

/**
 * Opens the workspace with the operator's remembered session that auth-setup
 * saved, so a run signs in once however many journeys it holds.
 */
export async function openPipelineWorkspace(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
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

/**
 * Archives the designs a journey saved, each at its current version. Lenient
 * cleanup skips designs that were never saved and tolerates a failed archive.
 */
export async function archivePipelines(
  request: APIRequestContext,
  headers: Record<string, string>,
  urls: Iterable<string>,
  { lenient = false } = {},
) {
  for (const url of urls) {
    const response = await request.get(url, { headers });
    if (lenient && !response.ok()) continue;
    expect(response.ok(), await response.text()).toBe(true);
    const design = (await response.json()) as PipelineView;
    const archived = await request.patch(url, { headers, data: {
      expected_version: design.version, name: design.name, description: design.description, archived: true,
    } });
    if (!lenient) expect(archived.ok(), await archived.text()).toBe(true);
  }
}
