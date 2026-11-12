import { expect, test, type Page } from "@playwright/test";
import { installSidebarMockApi } from "./helpers/sidebarMockApi";
import { setAppearance } from "./helpers/appearance";
import { expectNoHorizontalScroll } from "./helpers/layout";
import type { SystemSnapshot } from "../src/types/system";

test.use({ actionTimeout: 15_000 });

async function installEditableCatalogue(page: Page, canEdit = true) {
  const api = await installSidebarMockApi(page, { favourites: [{ kind: "reading", id: "temperature" }] });
  const snapshot: SystemSnapshot = { revision: 1, can_edit: canEdit, storage_origin: "saved", document: {
    format: "aberration-system", schema_version: 1, label: "Plant", default_policy: { mode: "off", interval_seconds: 10 },
    brokers: [{ id: "broker", label: "Plant broker", host: "localhost", protocol: "mqtt", port: 1883, transport: "tcp", tls: false }],
    devices: [{ id: "machine", label: "Cooling pump", kind: "pump", broker_id: "broker" }],
    readings: ["temperature", "humidity"].map(id => ({ id, label: id === "temperature" ? "Coolant temperature" : "Relative humidity",
      broker_id: "broker", device_id: "machine", topic: "plant/pump", payload_pointer: `/${id}`, category: "Environment", value_type: "number" })),
    groups: [{ id: "cooling", label: "Cooling circuit", member_ids: ["machine"] }],
  }, runtime: { mode: "configured_only", message: "", collection_revision: 1, collection: { revision: 1, status: "applied" },
    bindings: Object.fromEntries(["temperature", "humidity"].map(id => [id, { broker_id: "broker", policy: { mode: "off", interval_seconds: 10 } }])) } };
  const state = { snapshot, writes: 0, rejectNext: false, unexpected: api.writes };
  await page.route("**/api/v1/me", route => route.fulfill({ json: { id: 1, email: "designer@example.test", role: canEdit ? "admin" : "viewer",
    permissions: canEdit ? ["manage_sources"] : [], is_active: true } }));
  await page.route("**/api/v1/catalogue", route => {
    if (route.request().method() === "PUT") {
      if (state.rejectNext) { state.rejectNext = false; return route.fulfill({ status: 409, json: { detail: "The catalogue changed." } }); }
      const body = route.request().postDataJSON();
      if (!canEdit || body.expected_revision !== snapshot.revision) return route.fulfill({ status: 409 });
      snapshot.document = body.document;
      snapshot.revision++;
      state.writes++;
    }
    return route.fulfill({ json: snapshot });
  });
  await page.route("**/api/v1/recording/status", route => route.fulfill({ json: { revision: snapshot.revision, runtime: snapshot.runtime } }));
  await page.route("**/api/v1/readings/*/measurements/buckets*", route => route.fulfill({ json: [] }));
  return state;
}

test("broker, entity, topic and reading icons persist across surfaces and reloads", async ({ page }, info) => {
  const state = await installEditableCatalogue(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  const cases = [
    { query: "broker=broker", label: "Plant broker", icon: "Gateway", id: "router", color: "Blue" },
    { query: "entity=machine", label: "Cooling pump", icon: "Pump", id: "pump", color: "Sage" },
    { query: "broker=broker&topic=plant", label: "plant", icon: "Factory", id: "factory", color: "Clay" },
    { query: "reading=temperature", label: "Coolant temperature", icon: "Temperature", id: "temperature", color: "Teal" },
  ];
  for (const item of cases) {
    await page.goto(`/sources?${item.query}`);
    const trigger = page.getByRole("button", { name: `Change icon for ${item.label}`, exact: true });
    await setAppearance(page, "Follow system");
    await trigger.click();
    const picker = page.getByRole("dialog", { name: "Icon and color", exact: true });
    await expect(picker.getByRole("searchbox", { name: "Search icons" })).toBeFocused();
    await picker.getByRole("button", { name: `${item.color} color`, exact: true }).click();
    await picker.getByRole("button", { name: `${item.icon} icon`, exact: true }).click();
    if (item.id === "pump") {
      for (const colorScheme of ["light", "dark"] as const) {
        await page.emulateMedia({ colorScheme });
        await page.screenshot({ path: info.outputPath(`icon-picker-${colorScheme}.png`), animations: "disabled" });
        await picker.screenshot({ path: info.outputPath(`picker-detail-${colorScheme}.png`), animations: "disabled" });
      }
    }
    await picker.getByRole("button", { name: "Apply", exact: true }).click();
    await expect(picker).toBeHidden();
    await expect(trigger.locator(".source-icon")).toHaveAttribute("data-icon", item.id);
    await expect(trigger.locator(".source-icon")).toHaveAttribute("data-color", item.color.toLowerCase());
    await page.reload();
    await expect(trigger.locator(".source-icon")).toHaveAttribute("data-icon", item.id);
  }
  expect(state.writes).toBe(4);
  expect(state.snapshot.document.topic_appearances).toEqual([{ broker_id: "broker", topic: "plant", appearance: { icon: "factory", color: "clay" } }]);
  await page.goto("/sources");
  await expect(page.getByRole("button", { name: "Plant broker", exact: true }).locator(".source-icon")).toHaveAttribute("data-icon", "router");
  await page.getByRole("searchbox", { name: "Search catalogue", exact: true }).fill("Coolant temperature");
  const signal = page.getByRole("navigation", { name: "Catalogue", exact: true }).getByRole("button", { name: "Coolant temperature, preview", exact: true });
  await expect(signal.locator(".source-icon")).toHaveAttribute("data-icon", "temperature");
  await expect(signal.locator(".source-activity-dot")).toBeVisible();
  await page.screenshot({ path: info.outputPath("custom-source-icons.png"), animations: "disabled" });
  expect(state.unexpected).toEqual([]);
});

test("picker cancels, reports conflicts, resets, and fits a 320px screen", async ({ page }, info) => {
  const state = await installEditableCatalogue(page);
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/sources?entity=machine");
  const trigger = page.getByRole("button", { name: "Change icon for Cooling pump" });
  const picker = page.getByRole("dialog", { name: "Icon and color", exact: true });
  await trigger.click();
  await picker.getByRole("searchbox", { name: "Search icons" }).fill("hydraulic");
  await picker.getByRole("button", { name: "Pump icon", exact: true }).click();
  await picker.getByRole("button", { name: "Sage color", exact: true }).click();
  await expectNoHorizontalScroll(page);
  const box = (await picker.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(320);
  await page.screenshot({ path: info.outputPath("icon-picker-mobile.png"), animations: "disabled" });
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  expect(state.writes).toBe(0);
  await expect(trigger.locator(".source-icon")).toHaveAttribute("data-icon", "cpu");
  await trigger.click();
  await picker.getByRole("searchbox", { name: "Search icons" }).fill("pump");
  await picker.getByRole("button", { name: "Pump icon", exact: true }).click();
  state.rejectNext = true;
  await picker.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(picker.getByRole("alert")).toContainText("not saved");
  expect(state.writes).toBe(0);
  await expect(trigger.locator(".source-icon")).toHaveAttribute("data-icon", "cpu");
  await picker.getByRole("button", { name: "Cancel", exact: true }).click();
  await trigger.click();
  await picker.getByRole("searchbox", { name: "Search icons" }).fill("pump");
  await picker.getByRole("button", { name: "Pump icon", exact: true }).click();
  await picker.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(picker).toBeHidden();
  await trigger.click();
  await picker.getByRole("button", { name: "Reset icon and color" }).click();
  await picker.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(picker).toBeHidden();
  expect(state.snapshot.document.devices[0]?.appearance).toBeUndefined();
  expect(state.writes).toBe(2);
  expect(state.unexpected).toEqual([]);
});

test("appearance in the structure editor stays in the draft until Save changes", async ({ page }) => {
  const state = await installEditableCatalogue(page);
  await page.goto("/sources?entity=machine");
  await page.getByRole("button", { name: "Edit structure", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Edit catalogue", exact: true });
  const trigger = editor.getByRole("button", { name: "Change icon for Cooling pump", exact: true });
  await trigger.click();
  const picker = page.getByRole("dialog", { name: "Icon and color", exact: true });
  await page.keyboard.press("Escape");
  await expect(editor).toBeVisible();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await picker.getByRole("button", { name: "Motor icon", exact: true }).click();
  await picker.getByRole("button", { name: "Ochre color", exact: true }).click();
  await picker.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(picker).toBeHidden();
  expect(state.writes).toBe(0);
  await expect(editor.getByRole("button", { name: "Change icon for Cooling pump" }).locator(".source-icon")).toHaveAttribute("data-icon", "motor");
  await editor.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(editor).toBeHidden();
  expect(state.writes).toBe(1);
  expect(state.snapshot.document.devices[0]?.appearance).toEqual({ icon: "motor", color: "ochre" });
  expect(state.unexpected).toEqual([]);
});

test("viewers see saved icons without editing controls", async ({ page }) => {
  const state = await installEditableCatalogue(page, false);
  state.snapshot.document.devices[0]!.appearance = { icon: "pump", color: "sage" };
  await page.goto("/sources?entity=machine");
  await expect(page.locator(".ex-preview-icon .source-icon")).toHaveAttribute("data-icon", "pump");
  await expect(page.getByRole("button", { name: /^Change icon for/ })).toHaveCount(0);
  expect(state.writes).toBe(0);
});


test("collection appearance saves from its editor and renders in the sidebar", async ({ page }) => {
  const state = await installEditableCatalogue(page);
  await page.goto("/sources");
  await page.getByRole("button", { name: "Edit collection Cooling circuit", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Edit catalogue", exact: true });
  await editor.getByRole("button", { name: /^Change icon for/ }).click();
  const picker = page.getByRole("dialog", { name: "Icon and color", exact: true });
  await picker.getByRole("button", { name: "Valve icon", exact: true }).click();
  await picker.getByRole("button", { name: "Lavender color", exact: true }).click();
  await picker.getByRole("button", { name: "Apply", exact: true }).click();
  expect(state.writes).toBe(0);
  await editor.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(editor).toBeHidden();
  await page.reload();
  const collection = page.getByRole("button", { name: "Show collection Cooling circuit", exact: true });
  await expect(collection.locator(".source-icon")).toHaveAttribute("data-icon", "valve");
  await expect(collection.locator(".source-icon")).toHaveAttribute("data-color", "lavender");
  expect(state.snapshot.document.groups.find(group => group.label === "Cooling circuit")?.appearance).toEqual({ icon: "valve", color: "lavender" });
  expect(state.unexpected).toEqual([]);
});
