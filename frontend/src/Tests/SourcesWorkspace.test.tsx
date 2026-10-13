import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearNavigationDrafts, rememberNavigation } from "@/lib/navigation-draft";
import { SourcesWorkspace } from "@/features/catalogue/SourcesWorkspace";
import { buildSourcesIndex, scopeForNode, scopeReadingIds } from "@/features/catalogue/collectionRules";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import { apiClient, apiUtils } from "@/lib/api-client";
import type { SystemSnapshot } from "@/features/catalogue/systemTypes";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1, isAuthenticated: true, logout: vi.fn() }) }));
vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));
vi.mock("@/components/EChart", () => ({ EChart: () => <div role="img" aria-label="Received values" /> }));
vi.mock("@/lib/api-client", async original => ({ ...await original<typeof import("@/lib/api-client")>(), apiUtils: { get: vi.fn(), post: vi.fn() }, apiClient: { put: vi.fn() } }));
vi.mock("@tanstack/react-virtual", () => ({ useVirtualizer: ({ count }: { count: number }) => ({ getTotalSize: () => count * 72,
  getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 72, size: 72 })), measureElement: vi.fn(), scrollToOffset: vi.fn(), scrollToIndex: vi.fn() }) }));

function fixture(): SystemSnapshot {
  const document = { ...createEmptySystem(), label: "Workshop", connections: [{ id: "broker", label: "Workshop broker", host: "localhost", port: 1883, protocol: "mqtt" as const, transport: "tcp" as const, tls: false }],
    devices: [{ id: "room", label: "Room station", kind: "sensor" }], streams: ["temperature", "power"].map(id => ({ id, label: id, topic: `building/floor1/${id}`, device_id: "room", connection_id: "broker", value_type: "number" as const, category: "Environment" })) };
  return { document, revision: 3, can_edit: true, storage_origin: "saved", runtime: { mode: "configured_only", message: "", collection_revision: 4, collection: { status: "applied", revision: 4 }, collection_rules: [],
    bindings: Object.fromEntries(document.streams.map(stream => [stream.id, { entity_id: "entity", telemetry_key: stream.id, accepted_topic: `telemetry/entity/${stream.id}`, connection_id: "broker", policy: { mode: "off", interval_seconds: 10 } }])) } };
}
let saved: SystemSnapshot;
beforeEach(() => {
  localStorage.clear(); clearNavigationDrafts(); vi.clearAllMocks(); saved = fixture();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => setTimeout(callback, 0));
  vi.stubGlobal("cancelAnimationFrame", (handle: number) => clearTimeout(handle));
  vi.mocked(apiUtils.get).mockImplementation(async endpoint => endpoint === "/v1/system" ? saved : []);
  vi.mocked(apiUtils.post).mockResolvedValue({ revision: 3, collection_revision: 4, selected_readings: 2, sampled_rows_per_day_ceiling: 0, original_rate_readings: 2, affected_monitors: [], changed_readings: 2, starting_readings: 2, stopping_readings: 0, rate_changed_readings: 0 });
  vi.mocked(apiClient.put).mockImplementation(async () => {
    saved = { ...saved, revision: 4, runtime: { ...saved.runtime, collection_revision: 5, collection_rules: [{ scope: { kind: "broker", connection_id: "broker" }, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: false, admitted_before: 1 }] } };
    return { data: saved };
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount(path = "/sources") {
  const router = createMemoryRouter([{ path: "/sources", element: <SourcesWorkspace /> }, { path: "/", element: <h1>Monitoring home</h1> }], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

describe("dedicated Data sources configuration", () => {
  it("opens an overview without an automatic settings modal or MQTT connection", async () => {
    mount();
    await screen.findByRole("button", { name: "Workshop broker, open" });
    expect(screen.getByRole("heading", { name: "Data sources" })).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiUtils.post).not.toHaveBeenCalled();
  });

  it("returns through the menu to the previously inspected Monitoring URL", async () => {
    rememberNavigation("monitoring:1:url", "/?service=retained-service&tab=evidence&stream=temperature");
    const router = mount();
    await screen.findByRole("heading", { name: "Data sources" });
    fireEvent.pointerDown(screen.getByRole("button", { name: "Application menu" }), { button: 0, ctrlKey: false });
    const link = await screen.findByRole("menuitem", { name: "Monitoring" });
    fireEvent.click(link);
    await waitFor(() => expect(router.state.location.search).toBe("?service=retained-service&tab=evidence&stream=temperature"));
  });

  it("selects a broker directly, automatically previews a rule and applies once", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Workshop broker, open" }));
    await screen.findByLabelText("Recording policy");
    expect(screen.queryByRole("button", { name: "Review change" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Recording policy"), { target: { value: "original" } });
    await waitFor(() => expect(apiUtils.post).toHaveBeenCalledWith("/v1/system/collection/preview", expect.objectContaining({ rule_changes: [expect.objectContaining({ scope: { kind: "broker", connection_id: "broker" }, include_future_readings: false })] }), expect.anything()));
    expect(apiClient.put).not.toHaveBeenCalled();
    const apply = await screen.findByRole("button", { name: "Apply changes" });
    await waitFor(() => expect(apply.hasAttribute("disabled")).toBe(false));
    fireEvent.click(apply);
    await screen.findByRole("button", { name: "Undo last recording change" });
    expect(apiClient.put).toHaveBeenCalledOnce();
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
    expect(apiClient.put).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Recording policy") as HTMLSelectElement).value).toBe("inherit");
  });

  it("includes reviewed readings without replacing the chosen broker policy", async () => {
    const scope = { kind: "broker" as const, connection_id: "broker" };
    saved.runtime.collection_rules = [{ scope, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: false, admitted_before: 1 }];
    saved.runtime.bindings!.temperature!.policy = { mode: "original", interval_seconds: 10 };
    saved.runtime.bindings!.power!.policy_origin = { scope, inherited: true, needs_review: true };
    vi.mocked(apiClient.put).mockImplementation(async () => {
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
      return { data: saved };
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
    expect(apiClient.put).toHaveBeenCalledOnce();
    expect(apiClient.put).toHaveBeenCalledWith("/v1/system/collection", expect.objectContaining({
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
    fireEvent.click(screen.getByRole("button", { name: "Monitoring" }));
    const dialog = await screen.findByRole("dialog", { name: "Unsaved recording changes" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Stay" }));
    expect((screen.getByLabelText("Recording policy") as HTMLSelectElement).value).toBe("original");
    fireEvent.click(screen.getByRole("button", { name: "Monitoring" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Unsaved recording changes" })).getByRole("button", { name: "Discard and leave" }));
    await screen.findByRole("heading", { name: "Monitoring home" });
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("members inspect acknowledged policies without recording write controls", async () => {
    saved.can_edit = false;
    mount("/sources?broker=broker");
    await screen.findByText("An administrator can change recording settings.");
    expect(screen.queryByLabelText("Recording policy")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add broker" })).toBeNull();
  });

  it("merges topic hierarchy across devices and distinguishes whole topics from fields", () => {
    const document = fixture().document;
    document.devices.push({ id: "other", label: "Other station", kind: "sensor" });
    document.streams.push({ ...document.streams[0]!, id: "field", device_id: "other", payload_pointer: "/other" });
    const index = buildSourcesIndex(document);
    const branch = [...index.nodes.values()].find(node => node.topic === "building/floor1" && node.kind === "topic")!;
    expect(scopeReadingIds(index, branch).sort()).toEqual(["field", "power", "temperature"]);
    expect([...index.nodes.values()].some(node => node.kind === "device")).toBe(false);
    const topic = [...index.nodes.values()].find(node => node.topic === "building/floor1/temperature" && node.kind === "topic")!;
    expect(scopeForNode(topic)?.kind).toBe("topic");
    expect(topic.children).toHaveLength(2);
  });
});
