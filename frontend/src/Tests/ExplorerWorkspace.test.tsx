import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, apiClient, apiUtils } from "@/lib/api-client";
import MonitoringWorkspace from "@/pages/MonitoringWorkspace";
import { buildNavigationIndex } from "@/features/explorer/navigationIndex";
import { createDefaultExplorerPreferences, loadExplorerPreferences, saveExplorerPreferences } from "@/features/explorer/preferences";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import type { ActiveService } from "@/types/monitoring";
import type { SystemDocument, SystemSnapshot } from "@/features/spatial/systemTypes";

const auth = vi.hoisted(() => ({ userId: 1 as number | null, isAuthenticated: true }));
vi.mock("@/auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));
vi.mock("@/components/EChart", () => ({ EChart: () => <div role="img" aria-label="Received values" /> }));
vi.mock("@/lib/api-client", async (original) => {
  const actual = await original<typeof import("@/lib/api-client")>();
  return { ...actual, apiUtils: { ...actual.apiUtils, get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() }, apiClient: { ...actual.apiClient, put: vi.fn() } };
});
// jsdom has no viewport measurements; preserve row rendering and component keyboard handlers.
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 72,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 72, size: 72 })),
    measureElement: vi.fn(), scrollToOffset: vi.fn(), scrollToIndex: vi.fn(),
  }),
}));

const fixture = (): SystemDocument => ({
  ...createEmptySystem(), label: "North building",
  connections: [{ id: "broker", label: "Building broker", protocol: "mqtt", host: "broker.example.test", port: 1883, transport: "tcp", tls: false }],
  devices: [{ id: "station", label: "Room station", kind: "sensor", connection_id: "broker" }],
  streams: ["temperature", "humidity"].map((id) => ({ id, label: id === "temperature" ? "Air temperature" : "Relative humidity", connection_id: "broker", device_id: "station", topic: `weather/${id}`, value_type: "number", category: "Environment" })),
  groups: [{ id: "roof", label: "Roof", member_ids: ["station", "temperature"] }],
});
const snapshot = (document = fixture(), revision = 7, canEdit = true): SystemSnapshot => ({
  document, revision, can_edit: canEdit, storage_origin: "saved",
  runtime: { mode: "configured_only", legacy_collection_revision: 0, message: "Configuration only", collection_revision: 1, collection: { revision: 1, status: "applied" },
    bindings: Object.fromEntries(["temperature", "humidity"].map(id => [id, { connection_id: "broker", entity_id: "room-input", telemetry_key: id,
      accepted_topic: `device/evCharger/room-input/${id}`, policy: { mode: "off", interval_seconds: 10 } }])) },
});
function Location() { return <output data-testid="location">{useLocation().search}</output>; }
const mount = (path = "/") => render(<MemoryRouter initialEntries={[path]}><MonitoringWorkspace /><Location /></MemoryRouter>);
async function loaded() {
  await screen.findByRole("button", { name: "Building broker, open" });
}
async function enterReadings() {
  await loaded();
  fireEvent.click(screen.getByRole("button", { name: "Building broker, open" }));
  fireEvent.click(screen.getByRole("button", { name: "Room station, open" }));
  fireEvent.click(screen.getByRole("button", { name: "weather, open" }));
}
async function selectTemperature() {
  await enterReadings();
  fireEvent.click(screen.getByRole("button", { name: "temperature, preview" }));
  return screen.findByRole("region", { name: "Reading preview" }, { timeout: 5000 });
}
function fileFor(document: SystemDocument) {
  const file = new File([], "system.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: async () => JSON.stringify(document) });
  return file;
}

beforeEach(() => {
  auth.userId = 1; auth.isAuthenticated = true;
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(apiUtils.get).mockImplementation(async endpoint => endpoint === "/v1/system" ? snapshot() : []);
  vi.mocked(apiClient.put).mockImplementation(async (_endpoint, payload) => ({ data: snapshot((payload as { document: SystemDocument }).document, 8) }));
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => window.setTimeout(callback, 0));
  vi.stubGlobal("cancelAnimationFrame", (handle: number) => window.clearTimeout(handle));
});
afterEach(() => {
  cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

const service = (id = "service-one", name = "Room climate"): ActiveService => ({ id, container_id: `workload-${id}`, container_name: `monitor-${id}`, display_name: name,
  mqtt_topics: ["device/evCharger/room-input/temperature"], status: true, monitoring_strategy: "adaptive_stream", model_type: "aberrant_knn",
  operational_status: { stage: "operational", is_stale: false, message_count: 120, processed_message_count: 118, updated_at: "2026-10-11T10:00:00Z" } });
function withServices(services: ActiveService[]) {
  vi.mocked(apiUtils.get).mockImplementation(async endpoint => endpoint === "/v1/system" ? snapshot()
    : endpoint.startsWith("/v1/monitors/all") ? [...services] : endpoint.startsWith("/v1/monitors?") ? { configuration: { monitoring: {}, performance_config: {} } } : []);
}

describe("service-centred monitoring workspace", () => {
  it("opens a recorded reading without requiring Connect or creating a preview lease", async () => {
    const saved = snapshot();
    saved.runtime.bindings!.temperature!.policy = { mode: "sample", interval_seconds: 10 };
    saved.runtime.ingress = { sources: { broker: { state: "connected" } } };
    vi.mocked(apiUtils.get).mockImplementation(async endpoint => endpoint === "/v1/system" ? saved : []);
    mount();
    const preview = await selectTemperature();
    expect(within(preview).getByRole("status").textContent).toContain("Recording");
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
    expect(vi.mocked(apiUtils.post).mock.calls.some(([endpoint]) => endpoint === "/v1/system/live/leases")).toBe(false);
  });
  it("shows monitors by default without starting telemetry or enabling collection, and keeps service selection in the URL", async () => {
    withServices([service()]); mount();
    fireEvent.click(await screen.findByRole("link", { name: "Room climate" }));
    expect(await screen.findByRole("region", { name: "Monitoring service details" }, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByTestId("location").textContent).toBe("?service=service-one");
    expect(apiUtils.get).toHaveBeenCalledWith("/v1/monitors?container_name=monitor-service-one", expect.anything());
    expect(vi.mocked(apiUtils.get).mock.calls.some(([path]) => path.includes("/data?") || path.includes("/evidence/"))).toBe(false);
    expect(apiUtils.post).not.toHaveBeenCalled(); expect(apiClient.put).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
  });

  it("searches service inputs, scopes rows to a catalogue branch, and returns home without losing the sidebar position", async () => {
    withServices([service(), { ...service("other", "Other service"), mqtt_topics: ["unmapped/input"] }]); mount();
    await screen.findByRole("link", { name: "Other service" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search monitoring services" }), { target: { value: "temperature" } });
    expect(screen.getByRole("link", { name: "Room climate" })).toBeTruthy(); expect(screen.queryByRole("link", { name: "Other service" })).toBeNull();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search monitoring services" }), { target: { value: "" } });
    await enterReadings(); expect(screen.queryByRole("link", { name: "Other service" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Monitoring" }));
    expect(await screen.findByRole("link", { name: "Other service" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "humidity, preview" })).toBeTruthy();
  });

  it("persists service favourites and quietly saves display names without changing workload identifiers", async () => {
    const saved = [service()]; withServices(saved);
    vi.mocked(apiUtils.patch).mockImplementation(async (_path, payload) => { saved[0] = { ...saved[0]!, ...(payload as { display_name: string }) }; return {}; });
    const view = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Add Room climate to favourites" }));
    await waitFor(() => expect(loadExplorerPreferences(1).favourites).toEqual([{ kind: "service", id: "service-one" }]));
    fireEvent.click(within(screen.getByRole("region", { name: "Favourites" })).getByRole("button", { name: "Room climate" }));
    const details = await screen.findByRole("region", { name: "Monitoring service details" }, { timeout: 5000 });
    fireEvent.click(within(details).getByRole("button", { name: "Rename service" }));
    fireEvent.change(within(details).getByRole("textbox", { name: "Rename service" }), { target: { value: "Climate monitor" } });
    fireEvent.blur(within(details).getByRole("textbox", { name: "Rename service" }));
    await waitFor(() => expect(within(details).getByRole("button", { name: "Rename service" }).textContent).toBe("Climate monitor"));
    expect(apiUtils.patch).toHaveBeenCalledExactlyOnceWith("/v1/monitors/service-one/label", { display_name: "Climate monitor" });
    expect(screen.queryByText("Name saved.")).toBeNull(); expect(saved[0]?.container_name).toBe("monitor-service-one");
    view.unmount(); mount();
    expect(await screen.findByRole("link", { name: "Climate monitor" })).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Favourites" })).getByRole("button", { name: "Climate monitor" })).toBeTruthy();
  });

  it("opens input setup from a stable reading ID but keeps collection off until explicitly applied", async () => {
    withServices([]); mount("/?create=monitoring&reading=temperature");
    const setup = await screen.findByRole("region", { name: "Create monitoring service" }, { timeout: 5000 });
    expect(within(setup).getByRole("button", { name: "Choose monitoring inputs" }).textContent).toContain("Room station");
    expect(within(setup).getByText("Enable collection for the readings this service will monitor.")).toBeTruthy();
    expect(within(setup).queryByRole("button", { name: "Start monitoring" })).toBeNull();
    expect(apiUtils.post).not.toHaveBeenCalled(); expect(apiClient.put).not.toHaveBeenCalled();
  });
});

describe("hierarchical explorer workspace", () => {
  it("remembers sidebar width across reloads while keeping the selected reading and catalogue intact", async () => {
    const first = mount();
    const preview = await selectTemperature();
    fireEvent.keyDown(screen.getByRole("separator", { name: "Resize explorer sidebar" }), { key: "ArrowRight", shiftKey: true });
    expect(screen.getByRole("region", { name: "Reading preview" })).toBe(preview);
    await waitFor(() => expect(loadExplorerPreferences(1).sidebarWidth).toBe(352));
    expect(vi.mocked(apiUtils.get).mock.calls.filter(([endpoint]) => endpoint === "/v1/system")).toHaveLength(1);
    expect(apiClient.put).not.toHaveBeenCalled();
    first.unmount();
    mount();
    await screen.findByRole("button", { name: "temperature, preview" });
    const edge = screen.getByRole("separator", { name: "Resize explorer sidebar" });
    expect(edge.getAttribute("aria-valuenow")).toBe("352");
    fireEvent.click(screen.getByRole("button", { name: "Toggle explorer" }));
    expect(screen.queryByRole("separator")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Toggle explorer" }));
    fireEvent.doubleClick(screen.getByRole("separator", { name: "Resize explorer sidebar" }));
    await waitFor(() => expect(loadExplorerPreferences(1).sidebarWidth).toBe(288));
  });

  it("opens a generic entity from its stable-ID directory link and clears the link when selecting a reading", async () => {
    mount("/?entity=station");
    expect(await screen.findByRole("region", { name: "Entity preview" })).toBeTruthy();
    expect(screen.getByText("Entity ID").nextElementSibling?.textContent).toBe("station");
    expect(screen.getByTestId("location").textContent).toBe("?entity=station");
    fireEvent.click(screen.getByRole("button", { name: "weather, open" }));
    fireEvent.click(screen.getByRole("button", { name: "temperature, preview" }));
    expect(await screen.findByRole("region", { name: "Reading preview" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Entity preview" })).toBeNull();
    expect(screen.getByTestId("location").textContent).toBe("");
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("closes a linked entity without reopening it and reports missing stable IDs honestly", async () => {
    const view = mount("/?entity=station");
    await screen.findByRole("region", { name: "Entity preview" });
    fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
    expect(screen.getByTestId("location").textContent).toBe("");
    expect(screen.queryByRole("region", { name: "Entity preview" })).toBeNull();
    view.unmount();
    mount("/?entity=missing");
    expect(await screen.findByText("Entity not found.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Entity preview" })).toBeNull();
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("provides application and account navigation without leaving catalogue changes or starting telemetry", async () => {
    mount(); await loaded();
    expect(screen.queryByRole("link", { name: /Dashboard/ })).toBeNull();
    fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
    for (const [label, path] of [["Monitoring", "/"], ["Sources", "/sources"], ["Anomalies", "/anomalies"], ["Entities", "/entities"], ["Account", "/account"], ["Settings", "/account/settings"]]) {
      expect(screen.getByRole("menuitem", { name: label }).getAttribute("href")).toBe(path);
    }
    expect(screen.getByRole("menuitem", { name: "Monitoring" }).getAttribute("aria-current")).toBe("page");
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("loads the saved system and keeps the monitoring safe zone while entering hierarchy levels", async () => {
    mount();
    expect(screen.getByText("Loading catalogue…")).toBeTruthy();
    await enterReadings();
    expect(await screen.findByRole("heading", { name: "No monitoring services" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Reading preview" })).toBeNull();
    expect(screen.getByRole("button", { name: "humidity, preview" })).toBeTruthy();
    expect(vi.mocked(apiUtils.get).mock.calls.filter(([path]) => path === "/v1/system")).toHaveLength(1);
    expect(apiUtils.get).toHaveBeenCalledWith("/v1/monitors/all?active_only=false", expect.objectContaining({ redirectOnUnauthorized: false }));
    expect(apiClient.put).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "temperature, preview" }));
    expect(await screen.findByRole("region", { name: "Reading preview" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back one level" }));
    expect(screen.getByRole("button", { name: "weather, open" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Reading preview" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Monitoring" }));
    expect(screen.queryByRole("region", { name: "Reading preview" })).toBeNull();
    expect(await screen.findByRole("heading", { name: "No monitoring services" })).toBeTruthy();
  });

  it("searches collapsed branches, reveals the canonical parent, and renames through the revisioned API", async () => {
    mount(); await loaded();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search catalogue" }), { target: { value: "Air temperature" } });
    fireEvent.click(await screen.findByRole("button", { name: "Air temperature, preview" }));
    const preview = await screen.findByRole("region", { name: "Reading preview" });
    expect(screen.getByRole("searchbox", { name: "Search catalogue" }).getAttribute("value")).toBe("");
    expect(screen.getByRole("button", { name: "humidity, preview" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Catalogue" }));
    expect(screen.getByRole("button", { name: "Building broker, open" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Reading preview" })).toBe(preview);
    fireEvent.click(within(preview).getByRole("button", { name: "Rename reading" }));
    const input = within(preview).getByRole("textbox", { name: "Rename reading" });
    fireEvent.change(input, { target: { value: "Room temperature" } });
    fireEvent.blur(input);
    await waitFor(() => expect(within(preview).getByRole("button", { name: "Rename reading" }).textContent).toBe("Room temperature"));
    expect(apiClient.put).toHaveBeenCalledOnce();
    const request = vi.mocked(apiClient.put).mock.calls[0]!;
    expect(request[0]).toBe("/v1/system");
    expect(request[1]).toMatchObject({ expected_revision: 7 });
    expect((request[1] as { document: SystemDocument }).document.streams.find((stream) => stream.id === "temperature"))
      .toMatchObject({ id: "temperature", label: "Room temperature", topic: "weather/temperature" });
    expect((request[1] as { document: SystemDocument }).document.groups).toEqual(fixture().groups);
  });

  it("returns an archived personal scope to the catalogue without changing its saved groups", async () => {
    const groups = [{ id: "watch", name: "Favorites", color: "#6589b3", memberIds: ["broker", "temperature", "deleted-reading"] }];
    saveExplorerPreferences(1, { ...createDefaultExplorerPreferences(), scopeKey: "personal:watch", groups });
    mount(); await loaded();
    expect(screen.queryByText("Favorites")).toBeNull();
    expect(screen.getByRole("button", { name: "Building broker, open" }).querySelector<HTMLElement>(".ex-row-icon")?.style.color).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Browse catalogue groups" }));
    expect(screen.queryByText("Personal groups")).toBeNull();
    expect(screen.queryByRole("button", { name: "Manage personal groups" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show catalogue group Roof" }));
    expect(screen.getByRole("button", { name: "Air temperature, preview" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Air temperature, preview" }));
    const preview = await screen.findByRole("region", { name: "Reading preview" });
    expect(within(preview).queryByText("Personal groups")).toBeNull();
    expect(within(preview).queryByRole("button", { name: "Create personal group" })).toBeNull();
    expect(screen.getByRole("button", { name: "humidity, preview" })).toBeTruthy();
    await waitFor(() => expect(loadExplorerPreferences(1).scopeKey).not.toBe("personal:watch"));
    expect(loadExplorerPreferences(1).groups).toEqual(groups);
    expect(apiClient.put).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Catalogue settings" }));
    const dialog = await screen.findByRole("dialog", { name: "Catalogue settings" });
    expect(within(dialog).queryByRole("button", { name: "Export workspace" })).toBeNull();
    const contents = JSON.stringify({ format: "aberration-explorer-workspace", schema_version: 1,
      system: fixture(), preferences: { groups: [] } });
    const file = new File([], "previous-workspace.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => contents });
    fireEvent.change(await screen.findByLabelText("Catalogue or workspace file"), { target: { files: [file] } });
    fireEvent.click(await screen.findByRole("button", { name: "Replace saved catalogue" }));
    await screen.findByText("Catalogue imported and saved.");
    await waitFor(() => expect(loadExplorerPreferences(1).scopeKey).toBe(buildNavigationIndex(fixture()).rootKey));
    expect(loadExplorerPreferences(1).groups).toEqual(groups);
    expect(apiClient.put).toHaveBeenCalledOnce();
  });

  it("restores navigation after reload and isolates it and personal groups when the account changes", async () => {
    const first = mount(); await enterReadings();
    const topic = Array.from(buildNavigationIndex(fixture()).nodes.values()).find((node) => node.topic === "weather")!;
    await waitFor(() => expect(loadExplorerPreferences(1).scopeKey).toBe(topic.key));
    first.unmount();
    const second = mount();
    expect(await screen.findByRole("button", { name: "temperature, preview" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Building broker, open" })).toBeNull();
    expect(await screen.findByRole("heading", { name: "No monitoring services" })).toBeTruthy();
    auth.userId = 2;
    vi.mocked(apiUtils.get).mockImplementation(async endpoint => endpoint === "/v1/system" ? snapshot({ ...fixture(), label: "Other account" }) : []);
    second.rerender(<MemoryRouter><MonitoringWorkspace /></MemoryRouter>);
    expect(await screen.findByRole("button", { name: "Building broker, open" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "temperature, preview" })).toBeNull();
    expect(loadExplorerPreferences(1).scopeKey).toBe(topic.key);
    expect(loadExplorerPreferences(2).groups).toEqual([]);
  });

  it("shows an honest signed-out state and does not fetch or enable catalogue changes", async () => {
    auth.userId = null; auth.isAuthenticated = false;
    mount();
    expect(screen.getByText(/Sign in to load the catalogue/)).toBeTruthy();
    expect(apiUtils.get).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Catalogue settings" }));
    const dialog = await screen.findByRole("dialog", { name: "Catalogue settings" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Add broker" })).toBeTruthy());
    expect((within(dialog).getByRole("button", { name: "Add broker" }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(dialog).getByRole("button", { name: "Import file" }) as HTMLButtonElement).disabled).toBe(true);
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("lets read-only users inspect signals while disabling structural mutation", async () => {
    vi.mocked(apiUtils.get).mockImplementation(async endpoint => endpoint === "/v1/system" ? snapshot(fixture(), 7, false) : []);
    mount();
    const preview = await selectTemperature();
    expect((within(preview).getByRole("button", { name: "Rename reading" }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(preview).getByRole("button", { name: "Edit structure" }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(preview).queryByText("Personal groups")).toBeNull();
    expect((screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement).disabled).toBe(false);
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("uses a mobile drawer, preserves its hierarchy when selecting a topic, and restores trigger focus", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    mount();
    expect(screen.queryByRole("separator")).toBeNull();
    expect(screen.queryByRole("navigation", { name: "System explorer" })).toBeNull();
    const trigger = screen.getByRole("button", { name: "Open explorer" });
    fireEvent.click(trigger);
    await enterReadings();
    expect(screen.getByRole("dialog", { name: "System explorer" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "temperature, preview" }));
    expect(await screen.findByRole("region", { name: "Reading preview" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "System explorer" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    fireEvent.click(trigger);
    expect(await screen.findByRole("button", { name: "humidity, preview" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "temperature, preview" }).getAttribute("aria-current")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Close explorer" }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("retains keyboard focus when entering and returning through hierarchy levels", async () => {
    mount(); await loaded();
    const broker = screen.getByRole("button", { name: "Building broker, open" });
    broker.focus();
    fireEvent.keyDown(broker, { key: "ArrowRight" });
    const station = screen.getByRole("button", { name: "Room station, open" });
    await waitFor(() => expect(document.activeElement).toBe(station));
    fireEvent.keyDown(station, { key: "ArrowRight" });
    const branch = screen.getByRole("button", { name: "weather, open" });
    await waitFor(() => expect(document.activeElement).toBe(branch));
    fireEvent.keyDown(branch, { key: "ArrowRight" });
    const reading = screen.getByRole("button", { name: "humidity, preview" });
    await waitFor(() => expect(document.activeElement).toBe(reading));
    fireEvent.keyDown(reading, { key: "ArrowLeft" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "weather, open" })));
    const search = screen.getByRole("searchbox", { name: "Search catalogue" });
    search.focus();
    fireEvent.change(search, { target: { value: "Air temperature" } });
    await screen.findByRole("button", { name: "Air temperature, preview" });
    expect(document.activeElement).toBe(search);
  });

  it("opens and focuses global search when the desktop explorer is hidden", async () => {
    mount(); await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Toggle explorer" }));
    expect(screen.queryByRole("navigation", { name: "System explorer" })).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const search = await screen.findByRole("searchbox", { name: "Search catalogue" });
    await waitFor(() => expect(document.activeElement).toBe(search));
    fireEvent.change(search, { target: { value: "Relative humidity" } });
    expect(await screen.findByRole("button", { name: "Relative humidity, preview" })).toBeTruthy();
  });

  it("opens and focuses search in a closed mobile drawer with the global shortcut", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    mount();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const search = await screen.findByRole("searchbox", { name: "Search catalogue" });
    await waitFor(() => expect(document.activeElement).toBe(search));
    expect(screen.getByRole("dialog", { name: "System explorer" })).toBeTruthy();
  });

  it("imports a reviewed definition with its selected revision and resets navigation after acknowledgement", async () => {
    mount(); await enterReadings();
    fireEvent.click(screen.getByRole("button", { name: "Catalogue settings" }));
    const imported = { ...fixture(), label: "Imported building" };
    fireEvent.change(await screen.findByLabelText("Catalogue or workspace file"), { target: { files: [fileFor(imported)] } });
    fireEvent.click(await screen.findByRole("button", { name: "Replace saved catalogue" }));
    await screen.findByText("Catalogue imported and saved.");
    expect(apiClient.put).toHaveBeenCalledExactlyOnceWith("/v1/system", { expected_revision: 7, document: imported }, expect.objectContaining({ redirectOnUnauthorized: false }));
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    expect(await screen.findByRole("button", { name: "Building broker, open" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "temperature, preview" })).toBeNull();
    expect(screen.getAllByText("Imported building").length).toBeGreaterThan(0);
  });

  it("keeps a conflicted import unsaved and rejects retry against its obsolete baseline", async () => {
    mount(); await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Catalogue settings" }));
    fireEvent.change(await screen.findByLabelText("Catalogue or workspace file"), { target: { files: [fileFor({ ...fixture(), label: "My draft" })] } });
    vi.mocked(apiClient.put).mockRejectedValueOnce(new ApiRequestError("Conflict", 409));
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot({ ...fixture(), label: "Another editor's system" }, 8));
    fireEvent.click(await screen.findByRole("button", { name: "Replace saved catalogue" }));
    await screen.findByText(/The catalogue was not imported/);
    fireEvent.click(screen.getByRole("button", { name: "Replace saved catalogue" }));
    await waitFor(() => expect(apiClient.put).toHaveBeenCalledOnce());
    expect(screen.queryByText("Catalogue imported and saved.")).toBeNull();
    expect(screen.getAllByText("Another editor's system").length).toBeGreaterThan(0);
    expect(screen.getByText("My draft")).toBeTruthy();
  });
});
