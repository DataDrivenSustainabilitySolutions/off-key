import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { clearNavigationDrafts, rememberNavigation } from "@/lib/navigation-draft";
import { SourcesWorkspace } from "@/features/catalogue/SourcesWorkspace";
import { ApplicationWorkspace } from "@/app/ApplicationWorkspace";
import { recordingScopeReadingIds, scopeForNode, scopeReadingIds } from "@/domain/system/collectionRules";
import { buildNavigationIndex } from "@/domain/system/navigationIndex";
import { createEmptySystem } from "@/domain/system/systemDocument";
import { apiUtils } from "@/lib/api-client";
import type { SystemSnapshot } from "@/types/system";
import { mqttConnection } from "./support/fixtures/system";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1, isAuthenticated: true, logout: vi.fn(), can: () => false }) }));
vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));
vi.mock("@/features/charts/EChart", () => ({ EChart: () => <div role="img" aria-label="Received values" /> }));
vi.mock("@/lib/api-client", async original => ({ ...await original<typeof import("@/lib/api-client")>(), apiUtils: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock("@tanstack/react-virtual", () => ({ useVirtualizer: ({ count }: { count: number }) => ({ getTotalSize: () => count * 72,
  getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 72, size: 72 })), measureElement: vi.fn(), scrollToOffset: vi.fn(), scrollToIndex: vi.fn() }) }));

function fixture(): SystemSnapshot {
  const document = { ...createEmptySystem(), label: "Workshop", brokers: [mqttConnection({ id: "broker", label: "Workshop broker", host: "localhost" })],
    devices: [{ id: "room", label: "Room station", kind: "sensor" }], readings: ["temperature", "power"].map(id => ({ id, label: id, topic: `building/floor1/${id}`, device_id: "room", broker_id: "broker", value_type: "number" as const, category: "Environment" })) };
  return { document, revision: 3, can_edit: true, storage_origin: "saved", runtime: { mode: "configured_only", message: "", collection_revision: 4, collection: { status: "applied", revision: 4 }, collection_rules: [],
    bindings: Object.fromEntries(document.readings.map(stream => [stream.id, { entity_id: "entity", telemetry_key: stream.id, accepted_topic: `telemetry/entity/${stream.id}`, broker_id: "broker", policy: { mode: "off", interval_seconds: 10 } }])) } };
}
let saved: SystemSnapshot;
beforeAll(async () => {
  // Exercise inspector behaviour without timing the initial module transform.
  await import("@/features/readings/ExplorerPreview");
});
beforeEach(() => {
  clearNavigationDrafts(); saved = fixture();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => setTimeout(callback, 0));
  vi.stubGlobal("cancelAnimationFrame", (handle: number) => clearTimeout(handle));
  vi.mocked(apiUtils.get).mockImplementation(async endpoint => endpoint === "/v1/catalogue" ? saved : []);
  vi.mocked(apiUtils.post).mockResolvedValue({ revision: 3, collection_revision: 4, selected_readings: 2, sampled_rows_per_day_ceiling: 0, original_rate_readings: 2, affected_monitors: [], changed_readings: 2, starting_readings: 2, stopping_readings: 0, rate_changed_readings: 0 });
  vi.mocked(apiUtils.put).mockImplementation(async () => {
    saved = { ...saved, revision: 4, runtime: { ...saved.runtime, collection_revision: 5, collection_rules: [{ scope: { kind: "broker", broker_id: "broker" }, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: false, admitted_before: 1 }] } };
    return saved;
  });
});
/** Catalogue settings open from the application menu. */
async function openCatalogueSettings() {
  fireEvent.keyDown(screen.getByRole("button", { name: "Application menu" }), { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Catalogue" }));
}

function mount(path = "/sources") {
  const router = createMemoryRouter([{ element: <ApplicationWorkspace />, children: [
    { path: "/sources", element: <SourcesWorkspace /> }, { path: "/", element: <h1>Monitoring home</h1> },
  ] }], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

describe("dedicated Sources configuration", () => {
  it("polls the shared catalogue across brokers and expires a superseded recording revision", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    saved.document.brokers.push({ ...saved.document.brokers[0]!, id: "remote", label: "Remote broker" });
    saved.document.readings.push({ ...saved.document.readings[0]!, id: "remote-value", label: "Remote reading", broker_id: "remote" });
    saved.runtime.mode = "collection";
    saved.runtime.bindings!["remote-value"] = { ...saved.runtime.bindings!.temperature!, broker_id: "remote", policy: { mode: "original", interval_seconds: 10 } };
    saved.runtime.ingress = { revision: 4, status: "applied", sources: { remote: { state: "connected" } },
      readings: { "remote-value": { fresh_received_at: new Date().toISOString() } } };
    let collectionRevision = 4;
    vi.mocked(apiUtils.post).mockImplementation(async endpoint => {
      expect(endpoint).toBe("/v1/recording/status");
      return { revision: saved.revision, runtime: { ...saved.runtime, collection_revision: collectionRevision,
        bindings: saved.runtime.bindings,
        ingress: { revision: collectionRevision, status: "applied",
          sources: collectionRevision === 4 ? saved.runtime.ingress?.sources : {},
          readings: collectionRevision === 4 ? saved.runtime.ingress?.readings : {} } } };
    });
    mount("/sources?broker=broker");
    await screen.findByRole("radiogroup", { name: "Recording" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search catalogue" }), { target: { value: "Remote reading" } });
    const row = await screen.findByRole("button", { name: "Remote reading, preview" });
    expect(row.querySelector("svg")?.getAttribute("fill")).toBe("currentColor");
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(apiUtils.post).toHaveBeenCalledWith("/v1/recording/status", { reading_ids: ["temperature", "power", "remote-value"] }, expect.anything());
    expect(row.querySelector("svg")?.getAttribute("fill")).toBe("currentColor");
    collectionRevision = 5;
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(row.querySelector("svg")?.getAttribute("fill")).toBe("none");
  });

  it("shows confirmed recording traffic in the sidebar without opening a preview subscription", async () => {
    saved.runtime.mode = "collection";
    saved.runtime.bindings!.temperature!.policy = { mode: "sample", interval_seconds: 3600 };
    saved.runtime.ingress = { revision: 4, status: "applied", sources: { broker: { state: "connected" } },
      readings: { temperature: { fresh_received_at: new Date().toISOString() } } };
    mount();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search catalogue" }), { target: { value: "temperature" } });
    const row = await screen.findByRole("button", { name: "temperature, preview" });
    expect(row.querySelector("svg")?.getAttribute("fill")).toBe("currentColor");
    expect(document.getElementById(row.getAttribute("aria-describedby")!)?.textContent).toBe("Receiving data (last 2 minutes)");
    expect(apiUtils.post).not.toHaveBeenCalled();
  });

  it("opens an overview without an automatic settings modal or MQTT connection", async () => {
    mount();
    await screen.findByRole("button", { name: "Workshop broker, open" });
    expect(screen.getByRole("heading", { name: "Sources" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiUtils.post).not.toHaveBeenCalled();
  });

  it("returns through the navbar to the previously inspected Monitoring URL", async () => {
    rememberNavigation("monitoring:1:url", "/?service=retained-service&tab=evidence&stream=temperature");
    const router = mount();
    await screen.findByRole("heading", { name: "Sources" });
    const link = within(screen.getByRole("group", { name: "Workspaces" })).getByRole("link", { name: "Monitoring" });
    fireEvent.click(link);
    await waitFor(() => expect(router.state.location.search).toBe("?service=retained-service&tab=evidence&stream=temperature"));
  });

  it("uses the explicit service setup return path from the upper-left Monitoring link", async () => {
    rememberNavigation("monitoring:1:url", "/?service=another-monitor");
    const returnTo = "/?create=monitoring&reading=temperature";
    const router = mount(`/sources?broker=broker&returnTo=${encodeURIComponent(returnTo)}`);
    await screen.findByRole("heading", { name: "Sources" });
    const monitoring = within(screen.getByRole("group", { name: "Workspaces" })).getByRole("link", { name: "Monitoring" });
    const target = new URL(monitoring.getAttribute("href")!, "https://workspace.invalid");
    expect(target.searchParams.get("create")).toBe("monitoring");
    expect(target.searchParams.get("reading")).toBe("temperature");
    expect(target.searchParams.has("source")).toBe(true);
    fireEvent.click(monitoring);
    await screen.findByRole("heading", { name: "Monitoring home" });
    expect(new URLSearchParams(router.state.location.search).get("reading")).toBe("temperature");
  });

  it("opens an existing entity definition in Sources without creating or saving anything", async () => {
    mount();
    await screen.findByRole("heading", { name: "Sources" });
    await openCatalogueSettings();
    const chooser = await screen.findByLabelText("Edit entity");
    fireEvent.change(chooser, { target: { value: "room" } });
    const name = await screen.findByLabelText("device name");
    expect((name as HTMLInputElement).value).toBe("Room station");
    expect(screen.getByRole("button", { name: "Remove device" })).toBeTruthy();
    expect(saved.document.devices[0]!.id).toBe("room");
    expect(apiUtils.put).not.toHaveBeenCalled();
    expect(apiUtils.post).not.toHaveBeenCalled();
  });

  it("keeps entity editing disabled for members without catalogue edit access", async () => {
    saved.can_edit = false;
    mount();
    await screen.findByRole("heading", { name: "Sources" });
    await openCatalogueSettings();
    expect((await screen.findByLabelText("Edit entity")).hasAttribute("disabled")).toBe(true);
    expect(apiUtils.put).not.toHaveBeenCalled();
  });

  it("saves a recording choice at once and undoes it", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Workshop broker, open" }));
    const choice = await screen.findByRole("radiogroup", { name: "Recording" });
    expect((within(choice).getByRole("radio", { name: "Off" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(choice).getByRole("radio", { name: "Every message" }));
    // The picked option shows as selected while it saves.
    expect((within(choice).getByRole("radio", { name: "Every message" }) as HTMLInputElement).checked).toBe(true);
    await waitFor(() => expect(apiUtils.put).toHaveBeenCalledOnce());
    expect(apiUtils.put).toHaveBeenCalledWith("/v1/recording", expect.objectContaining({ pause_affected_monitors: false,
      rule_changes: [{ scope: { kind: "broker", broker_id: "broker" }, operation: "set",
        policy: { mode: "original", interval_seconds: 10 }, include_future_readings: true }] }), expect.anything());
    expect(screen.queryByRole("button", { name: "Apply changes" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(apiUtils.put).toHaveBeenCalledTimes(2));
    expect(apiUtils.put).toHaveBeenLastCalledWith("/v1/recording", expect.objectContaining({ expected_collection_revision: 5,
      rule_changes: [expect.objectContaining({ operation: "restore", restore_rule: null })] }), expect.anything());
  });

  it("switches the rate of a recording broker without any extra step", async () => {
    const scope = { kind: "broker" as const, broker_id: "broker" };
    saved.runtime.collection_rules = [{ scope, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: true, admitted_before: 1 }];
    for (const binding of Object.values(saved.runtime.bindings!)) binding.policy = { mode: "original", interval_seconds: 10 };
    mount("/sources?broker=broker");
    const choice = await screen.findByRole("radiogroup", { name: "Recording" });
    expect(screen.getByText("2 of 2 enabled · Every message")).toBeTruthy();
    fireEvent.change(within(choice).getByLabelText("Seconds between samples"), { target: { value: "60" } });
    fireEvent.click(within(choice).getByRole("radio", { name: /At intervals/ }));
    await waitFor(() => expect(apiUtils.put).toHaveBeenCalledOnce());
    expect(apiUtils.put).toHaveBeenCalledWith("/v1/recording", expect.objectContaining({ rule_changes: [{ scope, operation: "set",
      policy: { mode: "sample", interval_seconds: 60 }, include_future_readings: true }] }), expect.anything());
  });

  it("opts single readings in and out of a broker's recording", async () => {
    const scope = { kind: "broker" as const, broker_id: "broker" };
    saved.runtime.collection_rules = [{ scope, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: true, admitted_before: 1 }];
    saved.runtime.bindings!.temperature!.policy = { mode: "original", interval_seconds: 10 };
    mount("/sources?broker=broker");
    const readings = await screen.findByRole("group", { name: /Readings/ });
    fireEvent.click(within(readings).getByRole("checkbox", { name: /temperature/ }));
    await waitFor(() => expect(apiUtils.put).toHaveBeenCalledOnce());
    expect(apiUtils.put).toHaveBeenLastCalledWith("/v1/recording", expect.objectContaining({ rule_changes: [{
      scope: { kind: "reading", broker_id: "broker", reading_id: "temperature" }, operation: "set", policy: { mode: "off", interval_seconds: 10 } }] }), expect.anything());
    fireEvent.click(await within(screen.getByRole("group", { name: /Readings/ })).findByRole("checkbox", { name: /power/ }));
    await waitFor(() => expect(apiUtils.put).toHaveBeenCalledTimes(2));
    // A broker that records takes the reading back at its own rate.
    expect(apiUtils.put).toHaveBeenLastCalledWith("/v1/recording", expect.objectContaining({ rule_changes: [{
      scope: { kind: "reading", broker_id: "broker", reading_id: "power" }, operation: "inherit" }] }), expect.anything());
  });

  it("records readings added after recording started with one click", async () => {
    const scope = { kind: "broker" as const, broker_id: "broker" };
    saved.runtime.collection_rules = [{ scope, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: false, admitted_before: 1 }];
    saved.runtime.bindings!.temperature!.policy = { mode: "original", interval_seconds: 10 };
    saved.runtime.bindings!.power!.policy_origin = { scope, inherited: true, needs_review: true };
    mount("/sources?broker=broker");
    fireEvent.click(await screen.findByRole("button", { name: "Record it too" }));
    await waitFor(() => expect(apiUtils.put).toHaveBeenCalledOnce());
    expect(apiUtils.put).toHaveBeenCalledWith("/v1/recording", expect.objectContaining({ rule_changes: [
      { scope: { kind: "reading", broker_id: "broker", reading_id: "power" }, operation: "inherit" }] }), expect.anything());
  });

  it("records and stops a broker from its overview row", async () => {
    mount();
    const overview = await screen.findByRole("region", { name: "Broker overview" });
    expect(within(overview).getByText("Recording off")).toBeTruthy();
    fireEvent.click(within(overview).getByRole("button", { name: "Record Workshop broker" }));
    await waitFor(() => expect(apiUtils.put).toHaveBeenCalledOnce());
    expect(apiUtils.put).toHaveBeenCalledWith("/v1/recording", expect.objectContaining({ rule_changes: [{
      scope: { kind: "broker", broker_id: "broker" }, operation: "set", policy: { mode: "original", interval_seconds: 10 }, include_future_readings: true }] }), expect.anything());
    saved = { ...saved, runtime: { ...saved.runtime, ingress: { revision: 5, status: "applied", sources: { broker: { state: "connected" } } } } };
    vi.mocked(apiUtils.post).mockImplementation(async endpoint => endpoint === "/v1/recording/status"
      ? { revision: saved.revision, runtime: saved.runtime }
      : { revision: 4, collection_revision: 5, selected_readings: 0, sampled_rows_per_day_ceiling: 0, original_rate_readings: 0, affected_monitors: [], changed_readings: 2, starting_readings: 0, stopping_readings: 2, rate_changed_readings: 0 });
    fireEvent.click(await within(overview).findByRole("button", { name: "Stop recording Workshop broker" }, { timeout: 7000 }));
    await waitFor(() => expect(apiUtils.put).toHaveBeenCalledTimes(2));
    expect(apiUtils.put).toHaveBeenLastCalledWith("/v1/recording", expect.objectContaining({ rule_changes: [
      { scope: { kind: "broker", broker_id: "broker" }, operation: "inherit" }] }), expect.anything());
  }, 15000);

  it("members inspect acknowledged policies without recording write controls", async () => {
    saved.can_edit = false;
    mount("/sources?broker=broker");
    await screen.findByRole("region", { name: "Recording configuration" });
    expect(screen.queryByRole("radiogroup", { name: "Recording" })).toBeNull();
    expect(screen.queryByText(/administrator can/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Add broker" })).toBeNull();
  });

  it("checks only idle brokers and marks each name with the result", async () => {
    saved.document.brokers.push({ ...saved.document.brokers[0]!, id: "old", label: "Old broker" },
      { ...saved.document.brokers[0]!, id: "used", label: "Used broker" });
    saved.runtime.ingress = { revision: 4, status: "applied", sources: { used: { state: "connected" } } };
    const now = new Date().toISOString();
    vi.mocked(apiUtils.post).mockImplementation(async (endpoint, body) => {
      expect(endpoint).toBe("/v1/brokers/check");
      const id = (body as { broker_id: string }).broker_id;
      return id === "broker" ? { broker_id: id, status: "reachable", message: null, latency_ms: 12, checked_at: now }
        : { broker_id: id, status: "unreachable", message: "Nothing accepts connections on this host and port.", latency_ms: null, checked_at: now };
    });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Check connections" }));
    const overview = await screen.findByRole("region", { name: "Broker overview" });
    expect(await within(overview).findByRole("img", { name: /^Reachable · Checked at/ })).toBeTruthy();
    expect(await within(overview).findByRole("img", { name: /^Unreachable · Checked at/ })).toBeTruthy();
    expect(within(overview).getByText("Recording")).toBeTruthy();
    expect(within(overview).getAllByText("Recording off")).toHaveLength(2);
    expect(within(overview).getAllByText("Nothing accepts connections on this host and port.")).toHaveLength(1);
    expect(within(overview).getByText("Used broker").closest(".source-broker")?.className).toContain("source-broker--positive");
    expect(within(overview).getByText("Workshop broker").closest(".source-broker")?.className).toContain("source-broker--neutral");
    expect(within(overview).getByText("Old broker").closest(".source-broker")?.className).toContain("source-broker--neutral");
    expect(vi.mocked(apiUtils.post).mock.calls.map(([, body]) => body)).toEqual([{ broker_id: "broker" }, { broker_id: "old" }]);
  });

  it("lets a broker that could not reconnect be checked and retried", async () => {
    const message = "Could not reach the broker within 60 seconds, so recording from it is paused.";
    saved.document.brokers.push({ ...saved.document.brokers[0]!, id: "used", label: "Used broker" });
    saved.runtime.ingress = { revision: 4, status: "applied", sources: { broker: { state: "error", message }, used: { state: "reconnecting" } } };
    const now = new Date().toISOString();
    vi.mocked(apiUtils.post).mockImplementation(async (endpoint, body) => {
      const reconnect = /^\/v1\/brokers\/([^/]+)\/reconnect$/.exec(endpoint);
      const id = reconnect ? decodeURIComponent(reconnect[1]!) : (body as { broker_id: string }).broker_id;
      if (reconnect) {
        saved = { ...saved, runtime: { ...saved.runtime, ingress: { ...saved.runtime.ingress!, sources: { ...saved.runtime.ingress!.sources, [id]: { state: "connecting" } } } } };
        return { broker_id: id };
      }
      return { broker_id: id, status: "reachable", message: null, latency_ms: 12, checked_at: now };
    });
    const router = mount();
    const overview = await screen.findByRole("region", { name: "Broker overview" });
    expect(within(overview).getByText("Unavailable")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check connections" }));
    expect(await within(overview).findByRole("img", { name: /^Reachable · Checked at/ })).toBeTruthy();
    // A broker still retrying reports its own state and is not checked.
    expect(vi.mocked(apiUtils.post).mock.calls.map(([, body]) => body)).toEqual([{ broker_id: "broker" }]);

    await act(() => router.navigate("/sources?broker=broker"));
    expect((await screen.findAllByText(message)).length).toBeGreaterThan(0);
    fireEvent.click(await screen.findByRole("button", { name: "Reconnect recording" }));
    await waitFor(() => expect(vi.mocked(apiUtils.post)).toHaveBeenCalledWith("/v1/brokers/broker/reconnect", undefined, undefined));
    await waitFor(() => expect(screen.queryByRole("button", { name: /^Reconnect/ })).toBeNull());
  });

  it("offers Reconnect and Stop on failed recordings and Record on the others, never a live connection", async () => {
    const message = "Could not reach the broker within 60 seconds, so recording from it is paused.";
    saved.document.brokers.push({ ...saved.document.brokers[0]!, id: "used", label: "Used broker" },
      { ...saved.document.brokers[0]!, id: "down", label: "Down broker" });
    saved.runtime.ingress = { revision: 4, status: "applied", sources: { used: { state: "error", message } } };
    const now = new Date().toISOString();
    vi.mocked(apiUtils.post).mockImplementation(async (endpoint, body) => {
      const reconnect = /^\/v1\/brokers\/([^/]+)\/reconnect$/.exec(endpoint);
      const id = reconnect ? decodeURIComponent(reconnect[1]!) : (body as { broker_id: string }).broker_id;
      if (reconnect) return { broker_id: id };
      return id === "down" ? { broker_id: id, status: "timeout", message: "The broker did not answer within 15 seconds.", latency_ms: null, checked_at: now }
        : { broker_id: id, status: "reachable", message: null, latency_ms: 12, checked_at: now };
    });
    const router = mount();
    const overview = await screen.findByRole("region", { name: "Broker overview" });
    expect(within(overview).getByText(message)).toBeTruthy();
    expect(within(overview).getByRole("button", { name: "Stop recording Used broker" })).toBeTruthy();
    fireEvent.click(within(overview).getByRole("button", { name: "Reconnect recording for Used broker" }));
    await waitFor(() => expect(apiUtils.post).toHaveBeenCalledWith("/v1/brokers/used/reconnect", undefined, undefined));
    fireEvent.click(screen.getByRole("button", { name: "Check connections" }));
    expect(await within(overview).findByRole("img", { name: /^No response · Checked at/ })).toBeTruthy();
    expect(within(overview).getByText("The broker did not answer within 15 seconds.")).toBeTruthy();
    expect(within(overview).getByRole("button", { name: "Record Workshop broker" })).toBeTruthy();
    expect(within(overview).queryByRole("button", { name: /^Connect/ })).toBeNull();
    expect(apiUtils.post).not.toHaveBeenCalledWith(expect.stringMatching(/\/leases$/), expect.anything(), expect.anything());

    await act(() => router.navigate("/sources?broker=down"));
    expect(await screen.findByText("Unreachable")).toBeTruthy();
    expect(screen.getByText("The broker did not answer within 15 seconds.")).toBeTruthy();
  });

  it("offers connection checks to catalogue editors only", async () => {
    saved.can_edit = false;
    mount("/sources?broker=broker");
    await screen.findByRole("region", { name: "Recording configuration" });
    expect(screen.queryByRole("button", { name: "Close preview" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show all sources" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sources" }));
    await screen.findByRole("region", { name: "Broker overview" });
    expect(screen.queryByRole("button", { name: "Check connections" })).toBeNull();
    expect(apiUtils.post).not.toHaveBeenCalledWith("/v1/brokers/check", expect.anything());
  });

  it("keeps entities in the shared hierarchy while topic recording rules cover the entire broker", () => {
    const document = fixture().document;
    document.devices.push({ id: "other", label: "Other station", kind: "sensor" });
    document.readings.push({ ...document.readings[0]!, id: "field", device_id: "other", payload_pointer: "/other" });
    const index = buildNavigationIndex(document);
    const branch = [...index.nodes.values()].find(node => node.topic === "building/floor1" && node.kind === "topic" && node.deviceId === "room")!;
    expect(scopeReadingIds(index, branch).sort()).toEqual(["power", "temperature"]);
    expect(recordingScopeReadingIds(document, branch).sort()).toEqual(["field", "power", "temperature"]);
    expect([...index.nodes.values()].some(node => node.kind === "device")).toBe(true);
    const reading = index.nodes.get(index.objectKeys.get("field")![0]!)!;
    expect(scopeForNode(reading)).toMatchObject({ kind: "reading", reading_id: "field" });
  });
});
