import { expect, test, type Page } from "@playwright/test";

import { zoomChart } from "./helpers/chart";
import { setAppearance } from "./helpers/appearance";

const CHARGER_ID = "e2e-echarts";
const INITIAL_POINTS = [
  {
    timestamp: "2026-07-28T08:00:00.000Z",
    created: "2026-07-28T08:00:01.000Z",
    value: 229.8,
  },
  {
    timestamp: "2026-07-28T08:01:00.000Z",
    created: "2026-07-28T08:01:01.000Z",
    value: 230.4,
  },
  {
    timestamp: "2026-07-28T08:02:00.000Z",
    created: "2026-07-28T08:02:01.000Z",
    value: 231.1,
  },
  {
    timestamp: "2026-07-28T08:03:00.000Z",
    created: "2026-07-28T08:03:01.000Z",
    value: 230.7,
  },
];
const NEW_POINT = {
  timestamp: "2026-07-28T08:04:00.000Z",
  created: "2026-07-28T08:04:01.000Z",
  value: 232.2,
};
const ANOMALY = {
  anomaly_id: "anomaly-e2e-1",
  charger_id: CHARGER_ID,
  timestamp: "2026-07-28T08:02:00.000Z",
  telemetry_type: "systemVoltage",
  anomaly_type: "spike",
  anomaly_value: 0.01,
  value_type: "tail_pvalue",
  sensor_set: ["systemVoltage"],
};

/** Evidence for one voltage reading, scored half a minute after it arrived. */
const evidence = (
  timestamp: string,
  sequence: number,
  scores: Record<string, unknown>,
) => ({
  timestamp,
  created: new Date(Date.parse(timestamp) + 30_000).toISOString(),
  sequence_number: sequence,
  sensor_set: ["systemVoltage"],
  input_timestamps: { systemVoltage: timestamp },
  alarm: false,
  ...scores,
});
const STATIC_EVIDENCE = INITIAL_POINTS.slice(0, 3).map(({ timestamp }, index) =>
  evidence(timestamp, index + 1, {
    strategy: "static_baseline",
    service_id: "radar-service-e2e",
    restarted_martingale: 10 ** -index,
    threshold: 100,
  }),
);
const adaptiveEvidence = (timestamp: string, sequence: number) =>
  evidence(timestamp, sequence, {
    strategy: "adaptive_stream",
    service_id: "adaptive-delayed",
    anomaly_score: sequence,
    restarted_martingale: null,
    threshold: 5,
  });
const ADAPTIVE_SERVICE = {
  id: "adaptive-delayed",
  container_id: "container-delayed",
  container_name: "radar-delayed",
  mqtt_topics: [`telemetry/${CHARGER_ID}/systemVoltage`],
  status: true,
  monitoring_strategy: "adaptive_stream",
  operational_status: {
    stage: "operational",
    message_count: 2,
    processed_message_count: 2,
    is_stale: false,
  },
};

/** Serves a polled feed: its first page, then `later` once released. */
const routeFeed = async (
  page: Page,
  path: string,
  first: unknown[],
  later: unknown[],
) => {
  let released = false;
  await page.route(`**${path}*`, async (route) => {
    const isIncremental = new URL(route.request().url()).searchParams.has(
      "after_created",
    );
    await route.fulfill({ json: !isIncremental ? first : released ? later : [] });
  });
  return async () => {
    released = true;
    const response = page.waitForResponse(
      (candidate) =>
        candidate.url().includes(path) &&
        candidate.url().includes("after_created"),
    );
    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    await response;
  };
};

const installDetailsApi = async (
  page: Page,
  {
    telemetryTypes = ["systemVoltage"],
    telemetry = INITIAL_POINTS,
    anomalies = [ANOMALY],
    services = [] as unknown[],
    initialEvidence = STATIC_EVIDENCE,
    delayedEvidence = [] as unknown[],
  } = {},
) => {
  await page.route(`**/v1/telemetry/${CHARGER_ID}/type*`, async (route) => {
    await route.fulfill({ json: telemetryTypes });
  });
  await page.route(`**/v1/anomalies?charger_id=${CHARGER_ID}*`, async (route) => {
    await route.fulfill({ json: anomalies });
  });
  await page.route("**/v1/monitors/all?*", async (route) => {
    await route.fulfill({ json: services });
  });

  return {
    publishNewTelemetry: await routeFeed(
      page,
      `/v1/telemetry/${CHARGER_ID}/data`,
      telemetry,
      [NEW_POINT],
    ),
    releaseEvidence: await routeFeed(
      page,
      "/v1/monitors/evidence/chart",
      initialEvidence,
      delayedEvidence,
    ),
  };
};

test.describe("Details telemetry ECharts", () => {
  test.use({
    timezoneId: "UTC",
    colorScheme: "light",
    contextOptions: { reducedMotion: "reduce" },
    viewport: { width: 1440, height: 1000 },
  });

  test.beforeEach(async ({ page }) => {
    await page.route("**/v1/system", async (route) => {
      await route.fulfill({
        json: {
          document: { streams: [
            { id: "voltage", category: "Voltage" }, { id: "current", category: "Current" },
          ] },
          runtime: { bindings: {
            voltage: { entity_id: CHARGER_ID, telemetry_key: "systemVoltage" },
            current: { entity_id: CHARGER_ID, telemetry_key: "systemCurrent" },
          } },
        },
      });
    });
    await page.addInitScript(() => {
      localStorage.setItem("vite-ui-theme", "light");
    });
  });

  test("pins global navbar actions to the right edge on wide screens", async ({
    page,
  }) => {
    await installDetailsApi(page);
    await page.setViewportSize({ width: 1600, height: 900 });
    await page.goto(`/details/${CHARGER_ID}`);

    const navbar = page.getByTestId("application-header");
    const primaryLinks = page.getByRole("group", { name: "Workspaces", exact: true });
    const navbarActions = page.getByTestId("navbar-actions");
    await expect(navbarActions).toBeVisible();

    const [navbarBox, primaryLinksBox, navbarActionsBox] = await Promise.all([
      navbar.boundingBox(),
      primaryLinks.boundingBox(),
      navbarActions.boundingBox(),
    ]);
    expect(navbarBox).not.toBeNull();
    expect(primaryLinksBox).not.toBeNull();
    expect(navbarActionsBox).not.toBeNull();
    expect(primaryLinksBox!.x).toBeGreaterThanOrEqual(navbarBox!.x);
    expect(primaryLinksBox!.x + primaryLinksBox!.width).toBeLessThanOrEqual(navbarActionsBox!.x);
    expect(navbarActionsBox!.x).toBeGreaterThan(
      navbarBox!.x + navbarBox!.width / 2,
    );
    expect(
      navbarBox!.x + navbarBox!.width -
        (navbarActionsBox!.x + navbarActionsBox!.width),
    ).toBeLessThanOrEqual(40);
  });

  test("renders linked panes, themes, accessibility, and responsive Canvas", async ({
    page,
  }) => {
    await installDetailsApi(page);
    await page.goto(`/details/${CHARGER_ID}`);

    const chart = page.getByTestId("telemetry-echart");
    const card = page
      .locator('[data-slot="card"]')
      .filter({ hasText: "System Voltage" })
      .first();
    await expect(chart).toBeVisible();
    await expect(page.getByRole("heading", { name: "Voltage" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Voltage (1)" })).toBeVisible();
    const desktopChartBox = await chart.boundingBox();
    expect(desktopChartBox).not.toBeNull();
    expect(desktopChartBox?.height).toBeGreaterThanOrEqual(520);
    expect(desktopChartBox?.height).toBeLessThanOrEqual(522);
    await expect(chart.locator("canvas")).toHaveCount(1);
    await expect(chart).toHaveAttribute(
      "aria-label",
      /logarithmic static-evidence series.*UTC/u,
    );
    await expect(card.getByText(/Current System Voltage:/u)).toBeVisible();
    await expect(card.getByText(/Restarted e-process/u)).toBeVisible();
    await setAppearance(page, "Dark");
    await expect(page.locator("html")).toHaveClass(/dark/u);

    await page.setViewportSize({ width: 390, height: 844 });
    await card.scrollIntoViewIfNeeded();
    const chartBox = await chart.boundingBox();
    expect(chartBox?.width).toBeLessThanOrEqual(358);
    expect(chartBox?.height).toBeGreaterThanOrEqual(516);
    expect(chartBox?.height).toBeLessThanOrEqual(524);
    await page.locator("header").evaluate((header) => {
      header.style.visibility = "hidden";
    });
    await expect(chart.locator("canvas")).toBeVisible();
  });

  test("zooms, preserves inspection during polling, and returns to live", async ({
    page,
  }) => {
    const api = await installDetailsApi(page);
    await page.goto(`/details/${CHARGER_ID}`);

    const chart = page.getByTestId("telemetry-echart");
    const card = page.locator('[data-slot="card"]').filter({ has: chart });
    await expect(chart).toBeVisible();
    await zoomChart(page, card);

    await expect(page.getByRole("button", { name: "Return to live" })).toBeVisible();
    await api.publishNewTelemetry();
    await expect(page.getByText("New data available")).toBeVisible();

    await page.getByRole("button", { name: "Return to live" }).click();
    await expect(page.getByRole("button", { name: "Return to live" })).toBeHidden();

    await zoomChart(page, card);
    await expect(page.getByRole("button", { name: "Return to live" })).toBeVisible();
    await page.getByRole("button", { name: "Past hour" }).click();
    await expect(page.getByRole("button", { name: "Return to live" })).toBeHidden();
  });

  test("fills delayed evidence retroactively without moving the viewport", async ({
    page,
  }) => {
    const api = await installDetailsApi(page, {
      telemetry: INITIAL_POINTS.slice(0, 2),
      anomalies: [],
      services: [ADAPTIVE_SERVICE],
      initialEvidence: [adaptiveEvidence("2026-07-28T08:00:00.000Z", 1)],
      delayedEvidence: [adaptiveEvidence("2026-07-28T08:01:00.000Z", 2)],
    });
    await page.goto(`/details/${CHARGER_ID}`);

    const card = page
      .locator('[data-slot="card"]')
      .filter({ hasText: "System Voltage" })
      .first();
    await expect(card.getByText("1 awaiting score")).toBeVisible();
    await zoomChart(page, card);
    await expect(
      card.getByRole("button", { name: "Return to live" }),
    ).toBeVisible();

    await api.releaseEvidence();

    await expect(card.getByText("1 awaiting score")).toBeHidden();
    await expect(card.getByText(/Anomaly score:\s*2/u)).toBeVisible();
    await expect(
      card.getByRole("button", { name: "Return to live" }),
    ).toBeVisible();
  });

  test("optionally mirrors horizontal navigation across chart views", async ({
    page,
  }) => {
    await installDetailsApi(page, {
      telemetryTypes: ["systemVoltage", "systemCurrent"],
    });
    await page.goto(`/details/${CHARGER_ID}`);

    const voltageCard = page
      .locator('[data-slot="card"]')
      .filter({ hasText: "System Voltage" })
      .first();
    const currentCard = page
      .locator('[data-slot="card"]')
      .filter({ hasText: "System Current" })
      .first();
    await expect(voltageCard.getByTestId("telemetry-echart")).toBeVisible();
    await currentCard.scrollIntoViewIfNeeded();
    await expect(currentCard.getByTestId("telemetry-echart")).toBeVisible();

    await zoomChart(page, voltageCard);
    await page.getByRole("button", { name: "Current (1)" }).click();
    await expect(voltageCard).toHaveCount(0);
    await expect(page).toHaveURL(/category=Current/u);
    await page.getByRole("button", { name: "All categories (2)" }).click();
    await expect(voltageCard.getByRole("button", { name: "Return to live" })).toBeVisible();
    await voltageCard.getByRole("button", { name: "Return to live" }).click();

    const linkButton = page.getByRole("button", {
      name: "Link chart navigation",
    });
    await expect(linkButton).toHaveAttribute("aria-pressed", "false");

    await zoomChart(page, voltageCard);
    await expect(
      voltageCard.getByRole("button", { name: "Return to live" }),
    ).toBeVisible();
    await currentCard.scrollIntoViewIfNeeded();
    await expect(
      currentCard.getByRole("button", { name: "Return to live" }),
    ).toBeHidden();

    await linkButton.click();
    await expect(
      page.getByRole("button", { name: "Unlink chart navigation" }),
    ).toHaveAttribute("aria-pressed", "true");
    await currentCard.scrollIntoViewIfNeeded();
    await expect(
      currentCard.getByRole("button", { name: "Return to live" }),
    ).toBeVisible();

    await currentCard.getByRole("button", { name: "Return to live" }).click();
    await expect(
      page.getByRole("button", { name: "Return to live" }),
    ).toHaveCount(0);

    await page.getByRole("button", { name: "Unlink chart navigation" }).click();
    await zoomChart(page, voltageCard);
    await expect(
      voltageCard.getByRole("button", { name: "Return to live" }),
    ).toBeVisible();
    await currentCard.scrollIntoViewIfNeeded();
    await expect(
      currentCard.getByRole("button", { name: "Return to live" }),
    ).toBeHidden();
  });
});
