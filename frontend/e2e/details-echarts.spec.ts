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

const installDetailsApi = async (
  page: Page,
  telemetryTypes: string[] = ["systemVoltage"],
) => {
  let includeNewTelemetry = false;

  await page.route(`**/v1/telemetry/${CHARGER_ID}/type*`, async (route) => {
    await route.fulfill({ json: telemetryTypes });
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
              strategy: "static_baseline",
              service_id: "radar-service-e2e",
              timestamp: "2026-07-28T08:00:00.000Z",
              created: "2026-07-28T08:00:31.000Z",
              sequence_number: 1,
              sensor_set: ["systemVoltage"],
              input_timestamps: {
                systemVoltage: "2026-07-28T08:00:00.000Z",
              },
              restarted_martingale: 1,
              threshold: 100,
              alarm: false,
            },
            {
              strategy: "static_baseline",
              service_id: "radar-service-e2e",
              timestamp: "2026-07-28T08:01:00.000Z",
              created: "2026-07-28T08:01:31.000Z",
              sequence_number: 2,
              sensor_set: ["systemVoltage"],
              input_timestamps: {
                systemVoltage: "2026-07-28T08:01:00.000Z",
              },
              restarted_martingale: 0.1,
              threshold: 100,
              alarm: false,
            },
            {
              strategy: "static_baseline",
              service_id: "radar-service-e2e",
              timestamp: "2026-07-28T08:02:00.000Z",
              created: "2026-07-28T08:02:31.000Z",
              sequence_number: 3,
              sensor_set: ["systemVoltage"],
              input_timestamps: {
                systemVoltage: "2026-07-28T08:02:00.000Z",
              },
              restarted_martingale: 0.01,
              threshold: 100,
              alarm: false,
            },
          ],
    });
  });
  await page.route("**/v1/monitors/all?*", async (route) => {
    await route.fulfill({ json: [] });
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

const installDelayedEvidenceApi = async (page: Page) => {
  const firstTimestamp = "2026-07-28T08:00:00.000Z";
  const secondTimestamp = "2026-07-28T08:01:00.000Z";
  let releaseDelayedEvidence = false;

  await page.route(`**/v1/telemetry/${CHARGER_ID}/type*`, async (route) => {
    await route.fulfill({ json: ["systemVoltage"] });
  });
  await page.route(`**/v1/telemetry/${CHARGER_ID}/data*`, async (route) => {
    const isIncremental = new URL(route.request().url()).searchParams.has(
      "after_created",
    );
    await route.fulfill({
      json: isIncremental
        ? []
        : [
            { ...INITIAL_POINTS[0], timestamp: firstTimestamp },
            { ...INITIAL_POINTS[1], timestamp: secondTimestamp },
          ],
    });
  });
  await page.route(`**/v1/anomalies?charger_id=${CHARGER_ID}*`, async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/v1/anomalies/count*", async (route) => {
    await route.fulfill({ json: 0 });
  });
  await page.route("**/v1/monitors/all?*", async (route) => {
    await route.fulfill({
      json: [
        {
          id: "adaptive-delayed",
          container_id: "container-delayed",
          container_name: "radar-delayed",
          mqtt_topics: [
            `charger/${CHARGER_ID}/live-telemetry/systemVoltage`,
          ],
          status: true,
          monitoring_strategy: "adaptive_stream",
          operational_status: {
            stage: "operational",
            message_count: 2,
            processed_message_count: 2,
            is_stale: false,
          },
        },
      ],
    });
  });
  await page.route("**/v1/monitors/evidence/chart?*", async (route) => {
    const isIncremental = new URL(route.request().url()).searchParams.has(
      "after_created",
    );
    const row = (timestamp: string, sequence: number) => ({
      service_id: "adaptive-delayed",
      timestamp,
      created: new Date(Date.parse(timestamp) + 30_000).toISOString(),
      sequence_number: sequence,
      sensor_set: ["systemVoltage"],
      input_timestamps: { systemVoltage: timestamp },
      strategy: "adaptive_stream",
      anomaly_score: sequence,
      restarted_martingale: null,
      threshold: 5,
      alarm: false,
    });
    await route.fulfill({
      json: isIncremental
        ? releaseDelayedEvidence
          ? [row(secondTimestamp, 2)]
          : []
        : [row(firstTimestamp, 1)],
    });
  });

  return {
    releaseEvidence: async () => {
      releaseDelayedEvidence = true;
      const response = page.waitForResponse(
        (candidate) =>
          candidate.url().includes("/v1/monitors/evidence/chart") &&
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

  test("pins global navbar actions to the right edge on wide screens", async ({
    page,
  }) => {
    await installDetailsApi(page);
    await page.setViewportSize({ width: 1600, height: 900 });
    await page.goto(`/details/${CHARGER_ID}`);

    const navbar = page.locator('[data-slot="navigation-menu"]');
    const primaryLinks = page.getByTestId("navbar-primary-links");
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
    expect(primaryLinksBox!.x).toBeLessThan(
      navbarBox!.x + navbarBox!.width / 2,
    );
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
    const chartContainer = page.getByTestId("telemetry-chart-container");
    const card = page
      .locator('[data-slot="card"]')
      .filter({ hasText: "System Voltage" })
      .first();
    await expect(chart).toBeVisible();
    await expect(chartContainer).toBeVisible();
    const desktopChartBox = await chart.boundingBox();
    expect(desktopChartBox).not.toBeNull();
    const desktopChartHeight = Number(
      (await chartContainer.getAttribute("data-chart-height-px")) ?? "",
    );
    await expect(desktopChartHeight).toBeGreaterThanOrEqual(1);
    expect(desktopChartBox?.height).toBe(desktopChartHeight);
    await expect(chart.locator("canvas")).toHaveCount(1);
    await expect(chart).toHaveAttribute(
      "aria-label",
      /logarithmic static-evidence series.*UTC/u,
    );
    await expect(card.getByText(/Current System Voltage:/u)).toBeVisible();
    await expect(card.getByText(/Restarted e-process/u)).toBeVisible();
    await page.getByRole("button", { name: "Toggle theme" }).click();
    await page.getByRole("menuitem", { name: "Dark" }).click();
    await expect(page.locator("html")).toHaveClass(/dark/u);

    await page.setViewportSize({ width: 390, height: 844 });
    await card.scrollIntoViewIfNeeded();
    const mobileChartPaneCount = Number(
      (await chartContainer.getAttribute("data-chart-pane-count")) ?? "",
    );
    const mobileChartHeight = Number(
      (await chartContainer.getAttribute("data-chart-height-px")) ?? "",
    );
    expect(mobileChartPaneCount).toBe(2);
    expect(mobileChartHeight).toBe(desktopChartHeight);
    const chartBox = await chartContainer.boundingBox();
    expect(chartBox?.width).toBeLessThanOrEqual(358);
    expect(chartBox?.height).toBe(mobileChartHeight);
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

  test("fills delayed evidence retroactively without moving the viewport", async ({
    page,
  }) => {
    const api = await installDelayedEvidenceApi(page);
    await page.goto(`/details/${CHARGER_ID}`);

    const card = page
      .locator('[data-slot="card"]')
      .filter({ hasText: "System Voltage" })
      .first();
    await expect(card.getByText("1 awaiting score")).toBeVisible();
    await card.getByRole("button", { name: "Zoom in" }).click();
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
    await installDetailsApi(page, ["systemVoltage", "systemCurrent"]);
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

    const linkButton = page.getByRole("button", {
      name: "Link chart navigation",
    });
    await expect(linkButton).toHaveAttribute("aria-pressed", "false");

    await voltageCard.getByRole("button", { name: "Zoom in" }).click();
    await expect(
      voltageCard.getByRole("button", { name: "Return to live" }),
    ).toBeVisible();
    await expect(
      currentCard.getByRole("button", { name: "Return to live" }),
    ).toBeHidden();

    await linkButton.click();
    await expect(
      page.getByRole("button", { name: "Unlink chart navigation" }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      currentCard.getByRole("button", { name: "Return to live" }),
    ).toBeVisible();

    await currentCard.getByRole("button", { name: "Return to live" }).click();
    await expect(
      page.getByRole("button", { name: "Return to live" }),
    ).toHaveCount(0);

    await page.getByRole("button", { name: "Unlink chart navigation" }).click();
    await voltageCard.getByRole("button", { name: "Zoom in" }).click();
    await expect(
      voltageCard.getByRole("button", { name: "Return to live" }),
    ).toBeVisible();
    await expect(
      currentCard.getByRole("button", { name: "Return to live" }),
    ).toBeHidden();
  });
});
