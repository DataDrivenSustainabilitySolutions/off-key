import type { Page, Request } from "@playwright/test";
import { fulfillJson } from "./detailsMockApi";

const BROKER = { protocol: "mqtt", port: 1883, transport: "tcp", tls: false };
const reading = (id: string, label: string, broker_id: string, topic: string, extra: Record<string, unknown> = {}) =>
  ({ id, label, broker_id, topic, value_type: "number", category: "Measurement", ...extra });

/** A catalogue with devices, nested devices, broker-owned readings, collections and one long branch. */
function sidebarCatalogue(benches = 240) {
  return {
    format: "aberration-system", schema_version: 1, label: "Campus", default_policy: { mode: "off" },
    brokers: [
      { ...BROKER, id: "building", label: "Building broker", host: "building.example.invalid" },
      { ...BROKER, id: "lab", label: "Laboratory broker with a deliberately long name for truncation", host: "lab.example.invalid" },
    ],
    devices: [
      { id: "roof", label: "Roof weather station", broker_id: "building", kind: "station" },
      { id: "plant", label: "Basement plant room", broker_id: "building", kind: "room" },
      { id: "pump-2", label: "Circulation pump 2", broker_id: "building", parent_id: "plant", kind: "pump" },
    ],
    readings: [
      reading("air-temperature", "Air temperature", "building", "weather/roof/temperature", { device_id: "roof", unit: "°C" }),
      reading("humidity", "Relative humidity", "building", "weather/roof/humidity", { device_id: "roof", unit: "%" }),
      reading("wind-speed", "Wind speed", "building", "weather/roof/wind/speed", { device_id: "roof", unit: "m/s" }),
      reading("wind-direction", "Wind direction", "building", "weather/roof/wind/direction", { device_id: "roof", unit: "°" }),
      reading("flow", "Boiler flow temperature", "building", "plant/boiler/flow", { device_id: "plant", unit: "°C" }),
      reading("return", "Boiler return temperature", "building", "plant/boiler/return", { device_id: "plant", unit: "°C" }),
      reading("pump-speed", "Pump speed", "building", "plant/pumps/p2/speed", { device_id: "pump-2", unit: "rpm" }),
      reading("power", "Main meter active power", "building", "site/meters/main/power", { unit: "kW" }),
      reading("energy", "Main meter energy", "building", "site/meters/main/energy", { unit: "kWh" }),
      ...Array.from({ length: benches }, (_, position) => {
        const bench = String(position + 1).padStart(3, "0");
        return reading(`bench-${bench}`, `Bench ${bench} supply voltage`, "lab", `lab/benches/${bench}/supply/voltage`, { unit: "V" });
      }),
    ],
    groups: [
      { id: "building-a", label: "Building A", color: "#4f7cac", member_ids: ["roof", "power"] },
      { id: "lab-benches", label: "Lab benches", member_ids: ["lab"] },
    ],
  };
}

export type SidebarMock = {
  role?: "admin" | "viewer";
  dojo?: boolean;
  catalogue?: ReturnType<typeof sidebarCatalogue> | null;
  favourites?: Array<{ kind: string; id: string }>;
  theme?: "light" | "dark";
  /** Fails the catalogue request, as an unreachable backend would. */
  catalogueError?: boolean;
};

/**
 * Serves the signed-in workspace from fixtures, so sidebar journeys need no
 * running stack and change no stored data. Every request that is not a read is
 * recorded, so a journey can assert that browsing changed nothing.
 */
export async function installSidebarMockApi(page: Page, {
  role = "admin", dojo = true, catalogue = sidebarCatalogue(), favourites = [{ kind: "reading", id: "air-temperature" }, { kind: "device", id: "plant" }],
  theme = "light", catalogueError = false,
}: SidebarMock = {}) {
  const writes: string[] = [];
  await page.addInitScript((preferredTheme) => {
    const payload = btoa(JSON.stringify({ sub: "1", user_id: 1, exp: 4_102_444_800 }));
    sessionStorage.setItem("auth_token", `e2e.${payload}.signature`);
    localStorage.setItem("token_storage_type", "sessionStorage");
    localStorage.setItem("vite-ui-theme", preferredTheme);
  }, theme);
  const admin = role === "admin";
  await page.route("**/v1/**", async (route) => {
    const request: Request = route.request();
    const url = new URL(request.url());
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204 });
    const path = url.pathname.replace(/^\/api(?=\/v1\/)/u, "");
    // Reporting reads its alarm list through a query body.
    if (request.method() === "POST" && path === "/v1/alarms/query") return fulfillJson(route,
      { items: [], next: null, summary: { count: 0, devices: 0, latest: null }, readings: [], unknown_reading_ids: [] });
    if (request.method() !== "GET") {
      writes.push(`${request.method()} ${path}`);
      return route.fulfill({ status: 409, json: { detail: "Mocked API is read-only." } });
    }
    if (path === "/v1/me") return fulfillJson(route, {
      id: 1, email: admin ? "operator@example.test" : "viewer@example.test", role: admin ? "admin" : "viewer",
      permissions: admin ? ["manage_sources", "manage_monitors", "manage_alarms", "manage_members", ...(dojo ? ["use_dojo"] : [])] : [],
      is_active: true, is_verified: true, created_at: "2026-07-28T08:00:00.000Z",
    });
    if (path === "/v1/favorites") return fulfillJson(route, favourites);
    if (path === "/v1/catalogue") {
      if (catalogueError) return route.fulfill({ status: 503, json: { detail: "Catalogue service unavailable" } });
      return fulfillJson(route, {
        revision: 3, can_edit: admin, storage_origin: catalogue ? "saved" : "empty",
        document: catalogue ?? { ...sidebarCatalogue(0), brokers: [], devices: [], readings: [], groups: [] },
        runtime: { mode: "configured_only", message: "" },
      });
    }
    if (path === "/v1/monitors/overview") return fulfillJson(route, { monitors: [], services: [] });
    // Lists the pages read; none of them is needed for navigation.
    return fulfillJson(route, []);
  });
  return { writes };
}
