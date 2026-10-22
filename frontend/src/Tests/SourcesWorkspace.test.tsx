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

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1, isAuthenticated: true, logout: vi.fn() }) }));
vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));
vi.mock("@/features/charts/EChart", () => ({ EChart: () => <div role="img" aria-label="Received values" /> }));
vi.mock("@/lib/api-client", async original => ({ ...await original<typeof import("@/lib/api-client")>(), apiUtils: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock("@tanstack/react-virtual", () => ({ useVirtualizer: ({ count }: { count: number }) => ({ getTotalSize: () => count * 72,
  getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 72, size: 72 })), measureElement: vi.fn(), scrollToOffset: vi.fn(), scrollToIndex: vi.fn() }) }));

function fixture(): SystemSnapshot {
  const document = { ...createEmptySystem(), label: "Workshop", connections: [mqttConnection({ id: "broker", label: "Workshop broker", host: "localhost" })],
    devices: [{ id: "room", label: "Room station", kind: "sensor" }], streams: ["temperature", "power"].map(id => ({ id, label: id, topic: `building/floor1/${id}`, device_id: "room", connection_id: "broker", value_type: "number" as const, category: "Environment" })) };
  return { document, revision: 3, can_edit: true, storage_origin: "saved", runtime: { mode: "configured_only", message: "", collection_revision: 4, collection: { status: "applied", revision: 4 }, collection_rules: [],
    bindings: Object.fromEntries(document.streams.map(stream => [stream.id, { entity_id: "entity", telemetry_key: stream.id, accepted_topic: `telemetry/entity/${stream.id}`, connection_id: "broker", policy: { mode: "off", interval_seconds: 10 } }])) } };
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
  vi.mocked(apiUtils.get).mockImplementation(async endpoint => endpoint === "/v1/system" ? saved : []);
  vi.mocked(apiUtils.post).mockResolvedValue({ revision: 3, collection_revision: 4, selected_readings: 2, sampled_rows_per_day_ceiling: 0, original_rate_readings: 2, affected_monitors: [], changed_readings: 2, starting_readings: 2, stopping_readings: 0, rate_changed_readings: 0 });
  vi.mocked(apiUtils.put).mockImplementation(async () => {
    saved = { ...saved, revision: 4, runtime: { ...saved.runtime, collection_revision: 5, collection_rules: [{ scope: { kind: "broker", connection_id: "broker" }, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: false, admitted_before: 1 }] } };
    return saved;
  });
});
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
    saved.document.connections.push({ ...saved.document.connections[0]!, id: "remote", label: "Remote broker" });
    saved.document.streams.push({ ...saved.document.streams[0]!, id: "remote-value", label: "Remote reading", connection_id: "remote" });
    saved.runtime.mode = "collection";
    saved.runtime.bindings!["remote-value"] = { ...saved.runtime.bindings!.temperature!, connection_id: "remote", policy: { mode: "original", interval_seconds: 10 } };
    saved.runtime.ingress = { revision: 4, status: "applied", sources: { remote: { state: "connected" } },
      readings: { "remote-value": { fresh_received_at: new Date().toISOString() } } };
    let collectionRevision = 4;
    vi.mocked(apiUtils.post).mockImplementation(async endpoint => {
      expect(endpoint).toBe("/v1/system/collection/status");
      return { revision: saved.revision, runtime: { ...saved.runtime, collection_revision: collectionRevision,
        bindings: saved.runtime.bindings,
        ingress: { revision: collectionRevision, status: "applied",
          sources: collectionRevision === 4 ? saved.runtime.ingress?.sources : {},
          readings: collectionRevision === 4 ? saved.runtime.ingress?.readings : {} } } };
    });
    mount("/sources?broker=broker");
    await screen.findByLabelText("Recording policy");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search catalogue" }), { target: { value: "Remote reading" } });
    const row = await screen.findByRole("button", { name: "Remote reading, preview" });
    expect(row.querySelector("svg")?.getAttribute("fill")).toBe("currentColor");
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(apiUtils.post).toHaveBeenCalledWith("/v1/system/collection/status", { stream_ids: ["temperature", "power", "remote-value"] }, expect.anything());
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
    expect(document.getElementById(row.getAttribute("aria-describedby")!)?.textContent).toBe("Receiving data (last 30 seconds)");
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
    fireEvent.click(screen.getByRole("button", { name: "Catalogue settings" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Catalogue settings" }));
    expect((await screen.findByLabelText("Edit entity")).hasAttribute("disabled")).toBe(true);
    expect(apiUtils.put).not.toHaveBeenCalled();
  });

  it("selects a broker directly, automatically previews a rule and applies once", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Workshop broker, open" }));
    await screen.findByLabelText("Recording policy");
    expect(screen.queryByRole("button", { name: "Review change" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Recording policy"), { target: { value: "original" } });
    await waitFor(() => expect(apiUtils.post).toHaveBeenCalledWith("/v1/system/collection/preview", expect.objectContaining({ rule_changes: [expect.objectContaining({ scope: { kind: "broker", connection_id: "broker" }, include_future_readings: false })] }), expect.anything()));
    expect(apiUtils.put).not.toHaveBeenCalled();
    const apply = await screen.findByRole("button", { name: "Apply changes" });
    await waitFor(() => expect(apply.hasAttribute("disabled")).toBe(false));
    fireEvent.click(apply);
    await screen.findByRole("button", { name: "Undo last recording change" });
    expect(apiUtils.put).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Undo last recording change" }));
    await waitFor(() => expect(apiUtils.post).toHaveBeenLastCalledWith("/v1/system/collection/preview", expect.objectContaining({ expected_collection_revision: 5,
      rule_changes: [expect.objectContaining({ operation: "restore", restore_rule: null })] }), expect.anything()));
  });

  it("offers an explicit future-reading opt-in and keeps draft changes until applied", async () => {
    mount("/sources?broker=broker");
    const mode = await screen.findByLabelText("Recording policy");
    fireEvent.change(mode, { target: { value: "sample" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Include readings added later/ }));
    await waitFor(() => expect(apiUtils.post).toHaveBeenCalledWith("/v1/system/collection/preview", expect.objectContaining({ rule_changes: [expect.objectContaining({ include_future_readings: true, policy: { mode: "sample", interval_seconds: 10 } })] }), expect.anything()));
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(apiUtils.put).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Recording policy") as HTMLSelectElement).value).toBe("inherit");
  });

  it("includes reviewed readings without replacing the chosen broker policy", async () => {
    const scope = { kind: "broker" as const, connection_id: "broker" };
    saved.runtime.collection_rules = [{ scope, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: false, admitted_before: 1 }];
    saved.runtime.bindings!.temperature!.policy = { mode: "original", interval_seconds: 10 };
    saved.runtime.bindings!.power!.policy_origin = { scope, inherited: true, needs_review: true };
    vi.mocked(apiUtils.put).mockImplementation(async () => {
      const policy = { mode: "sample" as const, interval_seconds: 60 };
      saved = { ...saved, revision: 4, runtime: {
        ...saved.runtime, collection_revision: 5, collection_rules: [
          { scope, policy, include_future_readings: false, admitted_before: 1 },
          { scope: { kind: "reading", connection_id: "broker", reading_id: "power" }, policy: null, include_future_readings: false, admitted_before: 0 },
        ],
        bindings: Object.fromEntries(Object.entries(saved.runtime.bindings!).map(([id, binding]) => [id, {
          ...binding, policy, policy_origin: { scope, inherited: true, needs_review: false },
        }])),
      } };
      return saved;
    });
    mount("/sources?broker=broker");
    fireEvent.change(await screen.findByLabelText("Recording policy"), { target: { value: "sample" } });
    fireEvent.change(screen.getByLabelText("Recording interval"), { target: { value: "60" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply changes" }).hasAttribute("disabled")).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Include current readings" }));
    await waitFor(() => expect(apiUtils.post).toHaveBeenLastCalledWith("/v1/system/collection/preview", expect.objectContaining({
      rule_changes: [
        { scope, operation: "set", policy: { mode: "sample", interval_seconds: 60 }, include_future_readings: false },
        { scope: { kind: "reading", connection_id: "broker", reading_id: "power" }, operation: "inherit" },
      ],
    }), expect.anything()));
    expect((screen.getByLabelText("Recording policy") as HTMLSelectElement).value).toBe("sample");
    expect(screen.queryByRole("button", { name: "Include current readings" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Apply changes" }));
    await screen.findByRole("button", { name: "Undo last recording change" });
    expect(apiUtils.put).toHaveBeenCalledOnce();
    expect(apiUtils.put).toHaveBeenCalledWith("/v1/system/collection", expect.objectContaining({
      rule_changes: expect.arrayContaining([
        expect.objectContaining({ scope, operation: "set", policy: { mode: "sample", interval_seconds: 60 } }),
        { scope: { kind: "reading", connection_id: "broker", reading_id: "power" }, operation: "inherit" },
      ]),
    }), expect.anything());
    expect(screen.getByText(/2 of 2 enabled/)).toBeTruthy();
  });

  it("protects an unsaved broker draft when leaving for Monitoring", async () => {
    mount("/sources?broker=broker");
    fireEvent.change(await screen.findByLabelText("Recording policy"), { target: { value: "original" } });
    fireEvent.click(screen.getByRole("link", { name: "Monitoring" }));
    const dialog = await screen.findByRole("dialog", { name: "Unsaved recording changes" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Stay" }));
    expect((screen.getByLabelText("Recording policy") as HTMLSelectElement).value).toBe("original");
    fireEvent.click(screen.getByRole("link", { name: "Monitoring" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Unsaved recording changes" })).getByRole("button", { name: "Discard and leave" }));
    await screen.findByRole("heading", { name: "Monitoring home" });
    expect(apiUtils.put).not.toHaveBeenCalled();
  });

  it("members inspect acknowledged policies without recording write controls", async () => {
    saved.can_edit = false;
    mount("/sources?broker=broker");
    await screen.findByText("An administrator can change recording settings.");
    expect(screen.queryByLabelText("Recording policy")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add broker" })).toBeNull();
  });

  it("keeps entities in the shared hierarchy while topic recording rules cover the entire broker", () => {
    const document = fixture().document;
    document.devices.push({ id: "other", label: "Other station", kind: "sensor" });
    document.streams.push({ ...document.streams[0]!, id: "field", device_id: "other", payload_pointer: "/other" });
    const index = buildNavigationIndex(document);
    const branch = [...index.nodes.values()].find(node => node.topic === "building/floor1" && node.kind === "topic" && node.deviceId === "room")!;
    expect(scopeReadingIds(index, branch).sort()).toEqual(["power", "temperature"]);
    expect(recordingScopeReadingIds(document, branch).sort()).toEqual(["field", "power", "temperature"]);
    expect([...index.nodes.values()].some(node => node.kind === "device")).toBe(true);
    const reading = index.nodes.get(index.objectKeys.get("field")![0]!)!;
    expect(scopeForNode(reading)).toMatchObject({ kind: "reading", reading_id: "field" });
  });
});
