import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { setTimeout as delay } from "node:timers/promises";
import type { PipelineCatalog, PipelineView } from "../../src/types/pipelines.generated";
import { accessToken } from "./auth";

/**
 * The catalog with its templates cut to source, detector, calibration, policy
 * and output. The stream's template carries example steps, such as Lags, for
 * people to change or remove; these journeys build on the bare chain and add
 * what they test, with the source wired straight to the detector.
 */
export function bareCatalog(catalog: PipelineCatalog): PipelineCatalog {
  return {
    ...catalog,
    templates: catalog.templates.map((template) => {
      const nodes = template.definition.nodes ?? [];
      const steps = new Set(nodes.filter((node) => node.kind === "transform").map((node) => node.id));
      if (!steps.size) return template;
      const kept = nodes.filter((node) => !steps.has(node.id));
      const detector = kept.find((node) => node.kind === "detector")!.id;
      return {
        ...template,
        definition: {
          ...template.definition,
          nodes: kept,
          edges: (template.definition.edges ?? [])
            .filter((edge) => !steps.has(edge.source))
            .map((edge) => (edge.source === "input" ? { ...edge, target: detector } : edge)),
        },
        // As the catalog lays a template out: one column per card.
        layout: { ...template.layout, nodes: Object.fromEntries(kept.map((node, index) => [node.id, { x: index * 288, y: 100 }])) },
      };
    }),
  };
}

/**
 * Opens the workspace with the operator's remembered session that auth-setup
 * saved, so a run signs in once however many journeys it holds.
 */
export async function openPipelineWorkspace(page: Page) {
  await page.route(
    (url) => url.pathname.endsWith("/v1/pipeline-components"),
    async (route) => {
      const response = await route.fetch();
      if (!response.ok()) return route.fulfill({ response });
      await route.fulfill({ response, json: bareCatalog(await response.json() as PipelineCatalog) });
    },
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Monitoring", exact: true })).toBeVisible();
  const token = await accessToken(page);
  expect(token).toBeTruthy();
  await expect
    .poll(
      async () => {
        try {
          const response = await page.request.get(
            "/api/v1/pipeline-components",
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
    let response = await request.get(url, { headers });
    if (response.status() === 429) {
      // Cleanup reads share a one-minute member quota with workspace requests.
      await response.dispose();
      await delay(60_000);
      response = await request.get(url, { headers });
    }
    if (lenient && !response.ok()) continue;
    expect(response.ok(), await response.text()).toBe(true);
    const design = (await response.json()) as PipelineView;
    const archive = () => request.patch(url, { headers, data: {
      expected_version: design.version, name: design.name, description: design.description, archived: true,
    } });
    let archived = await archive();
    if (archived.status() === 429) {
      // Pipeline writes share a one-minute member quota across journeys.
      // A throttled write never reaches TACTIC, so the same archive is safe to retry.
      await archived.dispose();
      await delay(60_000);
      archived = await archive();
    }
    if (!lenient) expect(archived.ok(), await archived.text()).toBe(true);
  }
}
