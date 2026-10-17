import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test, type Locator } from "@playwright/test";
import type { SystemSnapshot } from "../src/features/catalogue/systemTypes";
import { setAppearance } from "./helpers/appearance";

async function expectDialogFits(dialog: Locator) {
  expect(await dialog.evaluate(element => {
    const box = element.getBoundingClientRect();
    return box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight
      && element.scrollWidth <= element.clientWidth;
  })).toBe(true);
}

test("reviews a real catalogue export before replacement", async ({ page }) => {
  await page.goto("/sources");
  await page.getByRole("button", { name: "Catalogue settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Catalogue settings", exact: true });
  await expect(dialog.getByRole("heading", { name: "Manage sources", exact: true })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Import & export", exact: true })).toBeVisible();
  const token = await page.evaluate(() => localStorage.getItem("auth_token"));
  const headers = { Authorization: `Bearer ${token}` };
  const beforeResponse = await page.request.get("/api/v1/system", { headers });
  expect(beforeResponse.ok(), await beforeResponse.text()).toBeTruthy();
  const before = await beforeResponse.json() as SystemSnapshot;
  const writes: string[] = [];
  page.on("request", request => {
    if (request.method() === "PUT" && new URL(request.url()).pathname === "/api/v1/system") writes.push(request.url());
  });
  const downloadReady = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Export catalogue", exact: true }).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe("aberration-system.json");
  const contents = await readFile((await download.path())!);
  expect(JSON.parse(contents.toString())).toEqual(before.document);

  await dialog.getByLabel("Catalogue file", { exact: true }).setInputFiles({
    name: "catalogue-copy.json", mimeType: "application/json", buffer: contents,
  });
  const preview = dialog.getByRole("region", { name: "Import preview", exact: true });
  await expect(preview).toBeVisible();
  await expect(preview).toContainText("catalogue-copy.json");
  await expect(preview).toContainText("This replaces your current catalogue.");
  expect(writes).toEqual([]);
  await preview.getByRole("button", { name: "Cancel import", exact: true }).click();
  await expect(preview).toHaveCount(0);
  expect(writes).toEqual([]);
  const afterResponse = await page.request.get("/api/v1/system", { headers });
  expect(afterResponse.ok()).toBeTruthy();
  expect((await afterResponse.json() as SystemSnapshot).revision).toBe(before.revision);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Catalogue settings", exact: true })).toBeFocused();
});

test("saves a source from settings and supports both themes and mobile entry points", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto("/sources");
  await page.getByRole("button", { name: "Catalogue settings", exact: true }).click();
  const token = await page.evaluate(() => localStorage.getItem("auth_token"));
  const headers = { Authorization: `Bearer ${token}` };
  const name = `Settings check ${randomUUID().slice(0, 8)}`;
  let createdId: string | undefined;
  let createdEntityId: string | undefined;
  try {
    await page.getByRole("button", { name: "Add broker", exact: true }).click();
    await page.getByRole("textbox", { name: "connection name", exact: true }).fill(name);
    await page.getByRole("textbox", { name: "Broker host", exact: true }).fill("source-broker");
    const savedResponse = page.waitForResponse(response => response.request().method() === "PUT" && new URL(response.url()).pathname === "/api/v1/system");
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    const saved = await savedResponse;
    expect(saved.ok(), await saved.text()).toBeTruthy();
    const snapshot = await saved.json() as SystemSnapshot;
    createdId = snapshot.document.connections.find(item => item.label === name)?.id;
    expect(createdId).toBeTruthy();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("button", { name: `${name}, preview`, exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Catalogue settings", exact: true }).click();
    await page.getByRole("button", { name: "Add entity", exact: true }).click();
    await page.getByRole("textbox", { name: "device name", exact: true }).fill(`${name} asset`);
    const entityResponse = page.waitForResponse(response => response.request().method() === "PUT" && new URL(response.url()).pathname === "/api/v1/system");
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    const entitySaved = await entityResponse;
    expect(entitySaved.ok(), await entitySaved.text()).toBeTruthy();
    createdEntityId = ((await entitySaved.json()) as SystemSnapshot).document.devices.find(item => item.label === `${name} asset`)?.id;
    expect(createdEntityId).toBeTruthy();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.getByRole("button", { name: "Catalogue settings", exact: true }).click();
    await page.getByRole("combobox", { name: "Edit entity", exact: true }).selectOption(createdEntityId!);
    await expect(page.getByRole("textbox", { name: "device name", exact: true })).toHaveValue(`${name} asset`);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    for (const theme of ["Dark", "Light"] as const) {
      await setAppearance(page, theme);
      await page.getByRole("button", { name: "Catalogue settings", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Catalogue settings", exact: true });
      await expect(dialog.getByRole("heading", { name: "Manage sources", exact: true })).toBeVisible();
      await expectDialogFits(dialog);
      await dialog.screenshot({ path: testInfo.outputPath(`settings-${theme.toLowerCase()}.png`) });
      await dialog.getByRole("button", { name: "Close settings", exact: true }).click();
    }

    for (const path of ["/sources", "/"]) {
      await page.setViewportSize({ width: 320, height: 844 });
      await page.goto(path);
      await page.getByRole("button", { name: "Show catalogue", exact: true }).click();
      await page.getByRole("button", { name: "Catalogue settings", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Catalogue settings", exact: true });
      await expect(dialog.getByRole("heading", { name: "Manage sources", exact: true })).toBeVisible();
      await expectDialogFits(dialog);
      await dialog.getByRole("button", { name: "Import file", exact: true }).scrollIntoViewIfNeeded();
      await expect(dialog.getByRole("button", { name: "Close settings", exact: true })).toBeInViewport();
      await dialog.screenshot({ path: testInfo.outputPath(path === "/" ? "settings-mobile-monitoring.png" : "settings-mobile-sources.png") });
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
    }
  } finally {
    if (createdId) {
      const response = await page.request.get("/api/v1/system", { headers });
      expect(response.ok()).toBeTruthy();
      const current = await response.json() as SystemSnapshot;
      current.document.devices = current.document.devices.filter(item => item.id !== createdEntityId);
      current.document.connections = current.document.connections.filter(item => item.id !== createdId);
      const cleanup = await page.request.put("/api/v1/system", { headers, data: { expected_revision: current.revision, document: current.document } });
      expect(cleanup.ok(), await cleanup.text()).toBeTruthy();
    }
  }
});
