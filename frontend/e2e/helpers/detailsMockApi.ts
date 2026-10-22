import type { Page, Route } from "@playwright/test";

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, content-type",
  "access-control-allow-methods": "GET, OPTIONS",
};
const CATEGORIES: Record<string, string> = { systemVoltage: "Voltage", systemCurrent: "Current" };

export const fulfillJson = (route: Route, json: unknown) => route.fulfill({ json, headers: CORS });

export type DetailsFeeds = {
  chargerId: string;
  sensors?: string[];
  /** First page of readings, then `laterTelemetry` once released. */
  telemetry: unknown[];
  laterTelemetry?: unknown[];
  /** First page of evidence, then `laterEvidence` once released. */
  evidence: unknown[];
  laterEvidence?: unknown[];
  anomalies?: unknown[];
  monitors?: unknown[];
  theme?: "light" | "dark";
};

/**
 * Serves the whole /details/:id page from fixtures behind a signed-in session,
 * so the chart journeys need no running stack. Unknown API paths fail the test.
 */
export async function installDetailsMockApi(page: Page, {
  chargerId, sensors = ["systemVoltage"], telemetry, laterTelemetry = [], evidence, laterEvidence = [],
  anomalies = [], monitors = [], theme = "light",
}: DetailsFeeds) {
  const released = { telemetry: false, evidence: false };
  await page.addInitScript((preferredTheme) => {
    const payload = btoa(JSON.stringify({ sub: "1", user_id: 1, exp: 4_102_444_800 }));
    // An unchecked session keeps its token in sessionStorage, so no refresh is mocked.
    sessionStorage.setItem("auth_token", `e2e.${payload}.signature`);
    localStorage.setItem("token_storage_type", "sessionStorage");
    localStorage.setItem("vite-ui-theme", preferredTheme);
  }, theme);

  await page.route("**/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const incremental = url.searchParams.has("after_created");
    switch (url.pathname.replace(/^\/api(?=\/v1\/)/u, "")) {
      case "/v1/members/me":
        return fulfillJson(route, {
          id: 1, email: "charts@example.test", role: "admin", is_active: true,
          is_verified: true, created_at: "2026-07-28T08:00:00.000Z",
        });
      case "/v1/system":
        return fulfillJson(route, {
          document: { streams: sensors.map(key => ({ id: key, category: CATEGORIES[key] ?? key })) },
          runtime: { bindings: Object.fromEntries(sensors.map(key => [key, { entity_id: chargerId, telemetry_key: key }])) },
        });
      case `/v1/telemetry/${chargerId}/type`:
        return fulfillJson(route, sensors);
      case `/v1/telemetry/${chargerId}/data`:
        return fulfillJson(route, !incremental ? telemetry : released.telemetry ? laterTelemetry : []);
      case "/v1/anomalies":
        return fulfillJson(route, anomalies);
      case "/v1/monitors/all":
        return fulfillJson(route, monitors);
      case "/v1/monitors/evidence/chart":
        return fulfillJson(route, !incremental ? evidence : released.evidence ? laterEvidence : []);
      default:
        throw new Error(`Unexpected mocked API request: ${url.pathname}`);
    }
  });

  /** Releases the later pages and waits for the next incremental read of `path`. */
  const release = async (feeds: (keyof typeof released)[], path: string) => {
    for (const feed of feeds) released[feed] = true;
    const response = page.waitForResponse((candidate) =>
      candidate.url().includes(path) && candidate.url().includes("after_created"));
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await response;
  };
  return {
    publish: () => release(["telemetry", "evidence"], `/telemetry/${chargerId}/data`),
    publishTelemetry: () => release(["telemetry"], `/telemetry/${chargerId}/data`),
    releaseEvidence: () => release(["evidence"], "/monitors/evidence/chart"),
  };
}
