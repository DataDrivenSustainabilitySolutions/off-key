import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { connectAsync, type MqttClient } from "mqtt";
import type { CatalogSnapshot } from "../src/types/collection";
import { effectivePolicy } from "../src/types/collection";
import { addTestCharger, removeTestCharger } from "./helpers/collection";

test("selects only temperature on mobile and collects only that measurement", async ({
  page,
  playwright,
}) => {
  const chargerId = randomUUID();
  const localId = `ui-${randomUUID()}`;
  const keys = ["temperature", "current", "voltage"];
  const api = await playwright.request.newContext({
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
    timeout: 120_000,
  });
  let token: string | null = null;
  let publisher: MqttClient | undefined;
  try {
    await page.goto("/");
    token = await page.evaluate(() => localStorage.getItem("auth_token"));
    expect(token).toBeTruthy();
    const headers = { Authorization: `Bearer ${token}` };
    await addTestCharger(api, token!, chargerId, localId, keys);
    const response = await api.get("/api/v1/sources", { headers });
    expect(response.ok(), await response.text()).toBeTruthy();
    const snapshot = (await response.json()) as CatalogSnapshot;
    const charger = snapshot.catalog.sources
      .flatMap((source) => source.chargers)
      .find((item) => item.id === chargerId)!;
    charger.label = `UI test ${chargerId}`;
    charger.sensors.forEach((sensor, index) => {
      sensor.category = ["Temperature", "Current", "Voltage"][index]!;
    });
    const configured = await api.put("/api/v1/sources", {
      headers,
      data: { expected_revision: snapshot.revision, catalog: snapshot.catalog },
    });
    expect(configured.ok(), await configured.text()).toBeTruthy();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/sources");
    await page
      .getByRole("searchbox", { name: "Search catalog" })
      .fill(charger.label);
    const broker = snapshot.catalog.sources.find((source) =>
      source.chargers.some((item) => item.id === chargerId),
    )!;
    await page
      .getByRole("button", {
        name: `Show chargers for ${broker.label}`,
        exact: true,
      })
      .click();
    await page
      .getByRole("button", {
        name: `Show measurements for ${charger.label}`,
        exact: true,
      })
      .click();
    for (const key of ["current", "voltage"]) {
      await page
        .getByLabel(`Collection for ${charger.label} · ${key}`, { exact: true })
        .selectOption("off");
    }
    await page
      .getByLabel(`Collection for ${charger.label} · temperature`, {
        exact: true,
      })
      .selectOption("sample");
    await page
      .getByLabel(
        `Collection for ${charger.label} · temperature interval in seconds`,
        { exact: true },
      )
      .fill("1");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    // Updating the draft must not write the catalog yet.
    const stillSaved = (await (
      await api.get("/api/v1/sources", { headers })
    ).json()) as CatalogSnapshot;
    expect(stillSaved.revision).toBe(snapshot.revision + 1);
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("unsaved changes");
      await dialog.dismiss();
    });
    await page.getByRole("button", { name: "User menu", exact: true }).click();
    await page.getByRole("menuitem", { name: "Account", exact: true }).click();
    await expect(page).toHaveURL(/\/sources$/);
    await expect(
      page.getByLabel(
        `Collection for ${charger.label} · temperature interval in seconds`,
        { exact: true },
      ),
    ).toHaveValue("1");
    await page
      .getByRole("button", { name: "Save changes", exact: true })
      .click();
    await expect(
      page.getByText("Changes saved", { exact: true }),
    ).toBeVisible();

    const applied = (await (
      await api.get("/api/v1/sources", { headers })
    ).json()) as CatalogSnapshot;
    const savedCharger = applied.catalog.sources
      .flatMap((source) => source.chargers)
      .find((item) => item.id === chargerId)!;
    expect(
      savedCharger.sensors.map(
        (sensor) => effectivePolicy(applied.catalog, savedCharger, sensor).mode,
      ),
    ).toEqual(["sample", "off", "off"]);
    await expect
      .poll(
        async () => {
          const status = (await (
            await api.get("/api/v1/sources/status", { headers })
          ).json()) as CatalogSnapshot;
          return (
            status.collection.revision === applied.revision &&
            status.collection.status === "applied" &&
            status.ingress.revision === applied.revision
          );
        },
        { timeout: 120_000 },
      )
      .toBe(true);
    publisher = await connectAsync(
      process.env.MQTT_SOURCE_URL ?? "mqtt://127.0.0.1:1884",
      { clientId: `ui-${chargerId}` },
    );
    for (const key of ["current", "voltage", "temperature"]) {
      await publisher.publishAsync(`device/evCharger/${localId}/${key}`, "25", {
        qos: 1,
      });
    }
    await expect
      .poll(async () => {
        const response = await api.get(`/api/v1/telemetry/${chargerId}/type`, {
          headers,
        });
        return response.ok() ? await response.json() : [];
      })
      .toEqual(["temperature"]);
    // Let a second sampled observation reach storage before checking that
    // deselected streams stayed absent throughout processing.
    for (const key of ["current", "voltage", "temperature"]) {
      await publisher.publishAsync(`device/evCharger/${localId}/${key}`, "26", {
        qos: 1,
      });
    }
    await expect
      .poll(async () => {
        const response = await api.get(`/api/v1/sources/state/${chargerId}`, {
          headers,
        });
        const states = (await response.json()) as Array<{
          sensor_key: string;
          value: unknown;
        }>;
        return states.map(({ sensor_key, value }) => ({ sensor_key, value }));
      })
      .toEqual([{ sensor_key: "temperature", value: 26 }]);
    const types = await api.get(`/api/v1/telemetry/${chargerId}/type`, {
      headers,
    });
    expect(await types.json()).toEqual(["temperature"]);
  } finally {
    await publisher?.endAsync();
    if (token) await removeTestCharger(api, token, chargerId);
    await api.dispose();
  }
});
