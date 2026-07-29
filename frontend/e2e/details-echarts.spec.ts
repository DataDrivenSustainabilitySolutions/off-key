import { expect, test, type Page } from "@playwright/test";

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

const installDetailsApi = async (page: Page) => {
  let includeNewTelemetry = false;

  await page.route(`**/v1/telemetry/${CHARGER_ID}/type*`, async (route) => {
    await route.fulfill({ json: ["systemVoltage"] });
  });
  await page.route(`**/v1/telemetry/${CHARGER_ID}/data*`, async (route) => {
    const isIncremental = new URL(route.request().url()).searchParams.has(
      "after_created",
    );
    await route.fulfill({
      json: isIncremental
        ? includeNewTelemetry
          ? [NEW_POINT]
          : []
        : INITIAL_POINTS,
    });
  });
  await page.route("**/v1/anomalies/count*", async (route) => {
    await route.fulfill({ json: 1 });
  });
  await page.route(`**/v1/anomalies?charger_id=${CHARGER_ID}*`, async (route) => {
    await route.fulfill({
      json: [
        {
          anomaly_id: "anomaly-e2e-1",
          charger_id: CHARGER_ID,
          timestamp: "2026-07-28T08:02:00.000Z",
          telemetry_type: "systemVoltage",
          anomaly_type: "spike",
          anomaly_value: 0.01,
          value_type: "tail_pvalue",
          sensor_set: ["systemVoltage"],
        },
      ],
    });
  });
  await page.route("**/v1/monitors/evidence/chart?*", async (route) => {
    const isIncremental = new URL(route.request().url()).searchParams.has(
      "after_created",
    );
    await route.fulfill({
      json: isIncremental
        ? []
        : [
            {
              service_id: "radar-service-e2e",
              timestamp: "2026-07-28T08:00:00.000Z",
              created: "2026-07-28T08:00:31.000Z",
              sequence_number: 1,
              sensor_set: ["systemVoltage"],
              restarted_martingale: 1,
              threshold: 100,
              alarm: false,
            },
            {
              service_id: "radar-service-e2e",
              timestamp: "2026-07-28T08:01:00.000Z",
              created: "2026-07-28T08:01:31.000Z",
              sequence_number: 2,
              sensor_set: ["systemVoltage"],
              restarted_martingale: 0.1,
              threshold: 100,
              alarm: false,
            },
            {
              service_id: "radar-service-e2e",
              timestamp: "2026-07-28T08:02:00.000Z",
              created: "2026-07-28T08:02:31.000Z",
              sequence_number: 3,
              sensor_set: ["systemVoltage"],
              restarted_martingale: 0.01,
              threshold: 100,
              alarm: false,
            },
          ],
    });
  });

  return {
    publishNewTelemetry: async () => {
      includeNewTelemetry = true;
      const response = page.waitForResponse(
        (candidate) =>
          candidate.url().includes(`/v1/telemetry/${CHARGER_ID}/data`) &&
          candidate.url().includes("after_created"),
      );
      await page.evaluate(() =>
        document.dispatchEvent(new Event("visibilitychange")),
      );
      await response;
    },
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
    await page.addInitScript(() => {
      localStorage.setItem("vite-ui-theme", "light");
    });
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
    await expect(chart.locator("canvas")).toHaveCount(1);
    await expect(chart).toHaveAttribute(
      "aria-label",
      /sequential-evidence series in a linked lower pane.*UTC/u,
    );
    await expect(card.getByText(/Current System Voltage:/u)).toBeVisible();
    await expect(card.getByText(/Restarted e-process radar-se/u)).toBeVisible();
    await expect(chart).toHaveScreenshot("telemetry-card-light.png", {
      animations: "disabled",
      maxDiffPixelRatio: 0.005,
    });

    await page.getByRole("button", { name: "Toggle theme" }).click();
    await page.getByRole("menuitem", { name: "Dark" }).click();
    await expect(page.locator("html")).toHaveClass(/dark/u);
    await expect(chart).toHaveScreenshot("telemetry-card-dark.png", {
      animations: "disabled",
      maxDiffPixelRatio: 0.005,
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await card.scrollIntoViewIfNeeded();
    const chartBox = await chart.boundingBox();
    expect(chartBox?.width).toBeLessThanOrEqual(358);
    expect(chartBox?.height).toBe(420);
    await page.locator("header").evaluate((header) => {
      header.style.visibility = "hidden";
    });
    await expect(card).toHaveScreenshot("telemetry-card-mobile.png", {
      animations: "disabled",
      maxDiffPixelRatio: 0.01,
    });
  });

  test("zooms, preserves inspection during polling, and returns to live", async ({
    page,
  }) => {
    const api = await installDetailsApi(page);
    await page.goto(`/details/${CHARGER_ID}`);

    const chart = page.getByTestId("telemetry-echart");
    await expect(chart).toBeVisible();
    await page.getByRole("button", { name: "Zoom in" }).click();

    await expect(page.getByRole("button", { name: "Return to live" })).toBeVisible();
    await api.publishNewTelemetry();
    await expect(page.getByText("New data available")).toBeVisible();

    await page.getByRole("button", { name: "Return to live" }).click();
    await expect(page.getByRole("button", { name: "Return to live" })).toBeHidden();

    await page.getByRole("button", { name: "Zoom in" }).click();
    await expect(page.getByRole("button", { name: "Return to live" })).toBeVisible();
    await page.getByRole("button", { name: "Past hour" }).click();
    await expect(page.getByRole("button", { name: "Return to live" })).toBeHidden();
  });
});
