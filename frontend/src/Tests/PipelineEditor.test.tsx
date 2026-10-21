import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { SystemLiveTelemetry } from "@/features/catalogue/systemLiveTelemetry";
import type { MonitoringTarget } from "@/features/monitoring/serviceModel";
import PipelineEditor from "@/features/pipelines/PipelineEditor";
import PipelineWorkspace from "@/features/pipelines/PipelineWorkspace";
import { PipelineCreate } from "@/features/pipelines/PipelineCreate";
import type { ActiveService } from "@/types/monitoring";
import {
  normalizeCatalog,
  normalizeDefinition,
  normalizeLayout,
  normalizeView,
} from "@/features/pipelines/contracts";
import { pipelinesApi } from "@/features/pipelines/api";
import { clearNavigationDrafts } from "@/lib/navigation-draft";
import { ApiRequestError } from "@/lib/api-client";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1 }) }));
vi.mock("@/components/theme-provider", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));
vi.mock("@/features/pipelines/api", () => ({
  pipelinesApi: {
    get: vi.fn(),
    save: vi.fn(),
    metadata: vi.fn(),
    validate: vi.fn(),
    publish: vi.fn(),
    create: vi.fn(),
    revision: vi.fn(),
    revisions: vi.fn(),
    revisionMetadata: vi.fn(), apply: vi.fn(), activation: vi.fn(), cancel: vi.fn(), list: vi.fn(), catalog: vi.fn(), service: vi.fn(),
  },
}));

const definition = normalizeDefinition({
  strategy: "adaptive_stream",
  input_slots: [{ id: "value", label: "Value" }],
  nodes: [
    { id: "input", kind: "source", component: "source.aligned" },
    { id: "detector", kind: "detector", component: "detector:test" },
    { id: "policy", kind: "policy", component: "policy.quantile" },
    { id: "output", kind: "output", component: "output.evidence" },
  ],
  edges: [
    { source: "input", target: "detector" },
    { source: "detector", target: "policy" },
    { source: "policy", target: "output" },
  ],
});
const catalog = normalizeCatalog({
  catalog_id: "catalog",
  authoring_enabled: true,
  templates: [],
  components: [
    {
      id: "source.aligned",
      kind: "source",
      label: "Inputs",
      description: "Aligned values",
      strategies: ["adaptive_stream"],
      input_type: null,
      output_type: "features",
    },
    {
      id: "detector:test",
      kind: "detector",
      label: "Detector",
      description: "Scores",
      strategies: ["adaptive_stream"],
      input_type: "features",
      output_type: "scores",
    },
    {
      id: "policy.quantile",
      kind: "policy",
      label: "Threshold",
      description: "Threshold",
      strategies: ["adaptive_stream"],
      input_type: "scores",
      output_type: "decisions",
    },
    {
      id: "output.evidence",
      kind: "output",
      label: "Evidence",
      description: "Evidence",
      strategies: ["adaptive_stream"],
      input_type: "decisions",
      output_type: "evidence",
    },
  ],
});
const pipeline = () =>
  normalizeView({
    id: "design",
    name: "Room pipeline",
    description: "",
    archived: false,
    version: 1,
    draft: definition,
    layout: normalizeLayout(),
    revisions: [
      {
        id: "revision",
        pipeline_id: "design",
        number: 1,
        fingerprint: "hash",
        catalog_id: "catalog",
        created_at: "2026-10-16T12:00:00Z",
      },
    ],
    created_at: "2026-10-16T12:00:00Z",
    updated_at: "2026-10-16T12:00:00Z",
  });
const props = () => ({
  id: "design",
  catalog,
  canEdit: true,
  targets: [target],
  initialTarget: "room",
  services: [],
  byStream: new Map<string, Set<string>>(),
  collectionReady: true,
  onBack: vi.fn(),
  onManage: vi.fn(),
  onRevision: vi.fn(),
  onOperation: vi.fn(),
  onStarted: vi.fn(),
});


const target: MonitoringTarget = { id: "room", label: "Room", inputs: [
  { path: "Room", stream: { id: "current", label: "Current", unit: "A", category: "Electrical", value_type: "number", topic: "fixture/current", connection_id: "broker" },
    binding: { entity_id: "room", telemetry_key: "current", accepted_topic: "telemetry/room/current", policy: { mode: "original", interval_seconds: 10 } } },
] };
const telemetry = new SystemLiveTelemetry();
vi.mock("@/features/workspace/catalogue-context", () => ({ useCatalogue: () => ({ system: { snapshot: null }, document: undefined, telemetry, liveStreamIds: [] }) }));
beforeEach(() => {
  vi.resetAllMocks(); clearNavigationDrafts();
  vi.mocked(pipelinesApi.get).mockResolvedValue(pipeline());
  vi.mocked(pipelinesApi.validate).mockImplementation(async (_id, definition) => ({ valid: true, definition: normalizeDefinition(definition), issues: [], features: {}, provenance_complete: true }));
  vi.mocked(pipelinesApi.list).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(pipelinesApi.revision).mockImplementation(async (_id, id) => {
    if (id !== "revision") throw new ApiRequestError("Published revision not found", 404);
    return { ...pipeline().revisions[0]!, definition };
  });
  vi.mocked(pipelinesApi.apply).mockResolvedValue({ id: "activation", phase: "requested", service_id: "service", run_id: "run", predecessor_service_id: null, error: null, created_at: "2026-10-20T10:00:00Z", updated_at: "2026-10-20T10:00:00Z" });
  vi.mocked(pipelinesApi.activation).mockResolvedValue({ id: "activation", phase: "requested", service_id: "service", run_id: "run", predecessor_service_id: null, error: null, created_at: "2026-10-20T10:00:00Z", updated_at: "2026-10-20T10:00:00Z" });
  vi.mocked(pipelinesApi.save).mockImplementation(async (_id, body) => ({ ...pipeline(), name: body.name!, description: body.description!, version: 2, draft: normalizeDefinition(body.definition), layout: normalizeLayout(body.layout) }));
});
afterEach(cleanup);
function mount(overrides: Partial<ReturnType<typeof props>> = {}) {
  const callbacks = { ...props(), ...overrides };
  const result = render(<MemoryRouter><PipelineEditor {...callbacks} /></MemoryRouter>);
  return { ...result, callbacks };
}
async function settings() { fireEvent.click(await screen.findByRole("button", { name: "Learning settings" })); }
async function saveDialog() { fireEvent.click(await screen.findByRole("button", { name: "Save template" })); return screen.findByRole("dialog"); }

describe("simple monitoring setup", () => {
  const phases: MonitoringTarget = { ...target, inputs: ["AC1", "AC2", "AC3"].map((label) => ({
    ...target.inputs[0]!, stream: { ...target.inputs[0]!.stream, id: label, label },
  })) };
  const standardCatalog = { ...catalog, templates: [{ id: "adaptive_stream", name: "Adaptive stream", definition, layout: normalizeLayout() }] };

  it("applies AC1 and AC3 directly, retaining the subset through navigation and undo", async () => {
    const ui = <MemoryRouter><PipelineCreate {...props()} catalog={standardCatalog} targets={[phases]} /></MemoryRouter>;
    const view = render(ui);
    fireEvent.change(screen.getByRole("textbox", { name: "Service name" }), { target: { value: "Two phases" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Monitor AC2" }));
    expect((screen.getByRole("checkbox", { name: "Monitor AC1" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("checkbox", { name: "Monitor AC2" }) as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Undo graph change" }));
    expect((screen.getByRole("checkbox", { name: "Monitor AC2" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Redo graph change" }));
    view.unmount(); render(ui);
    expect((screen.getByRole("checkbox", { name: "Monitor AC2" }) as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Apply monitoring" }));
    await waitFor(() => expect(pipelinesApi.apply).toHaveBeenCalledOnce());
    const request = vi.mocked(pipelinesApi.apply).mock.calls[0]![0];
    expect(request.definition.input_slots).toEqual([{ id: "value", label: "AC1", unit: "A" }, { id: "input_3", label: "AC3", unit: "A" }]);
    expect(request.bindings).toEqual({ value: "AC1", input_3: "AC3" });
    expect(pipelinesApi.save).not.toHaveBeenCalled(); expect(pipelinesApi.publish).not.toHaveBeenCalled();
  });

  it("blocks an empty selection and excludes collection-off readings from Select all available", () => {
    const unavailable = { ...phases, inputs: phases.inputs.map((input, index) => index === 1
      ? { ...input, binding: { ...input.binding, policy: { ...input.binding.policy, mode: "off" as const } } } : input) };
    render(<MemoryRouter><PipelineCreate {...props()} catalog={standardCatalog} targets={[unavailable]} /></MemoryRouter>);
    fireEvent.change(screen.getByRole("textbox", { name: "Service name" }), { target: { value: "Two phases" } });
    expect((screen.getByRole("checkbox", { name: "Monitor AC2" }) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply monitoring" }));
    expect(screen.getByText("Select at least one available reading to monitor.")).toBeTruthy();
    expect(pipelinesApi.apply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Select all available" }));
    expect(screen.getByText("2 readings selected")).toBeTruthy();
  });

  it("removes and restores a named template input directly on the setup page", async () => {
    const inputSlots = phases.inputs.map((input, index) => ({ id: `phase_${index + 1}`, label: input.stream.label, unit: "A" }));
    render(<MemoryRouter><PipelineCreate {...props()} targets={[phases]}
      initialDesign={{ ...pipeline(), draft: { ...definition, input_slots: inputSlots } }} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Remove reading for AC2" }));
    expect(screen.queryByRole("combobox", { name: "Reading for AC2" })).toBeNull();
    fireEvent.change(screen.getByRole("combobox", { name: "Add reading" }), { target: { value: "AC2" } });
    expect((screen.getByRole("combobox", { name: "Reading for AC2" }) as HTMLSelectElement).value).toBe("AC2");
    fireEvent.click(screen.getByRole("button", { name: "Undo graph change" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply monitoring" }));
    await waitFor(() => expect(pipelinesApi.apply).toHaveBeenCalledOnce());
    const request = vi.mocked(pipelinesApi.apply).mock.calls[0]![0];
    expect(request.definition.input_slots).toEqual([inputSlots[0], inputSlots[2]]);
    expect(request.bindings).toEqual({ phase_1: "AC1", phase_3: "AC3" });
  });

  it("tracks a replacement after its predecessor disappears from the active service list", async () => {
    const old: ActiveService = { id: "old", display_name: "Existing health", container_id: "worker", container_name: "worker", mqtt_topics: [], status: true,
      operational_status: { stage: "operational", is_stale: false, message_count: 10, processed_message_count: 10 } };
    const callbacks = props();
    const context = { id: "old", replace: true };
    const ui = (replaceService?: ActiveService) => <MemoryRouter><PipelineCreate {...callbacks} initialDesign={pipeline()}
      sourceService={context} replaceService={replaceService} activationBlocked={replaceService ? undefined : "Previous service retired"} /></MemoryRouter>;
    const view = render(ui(old));
    fireEvent.click(await screen.findByRole("button", { name: "Apply changes" }));
    await waitFor(() => expect(pipelinesApi.apply).toHaveBeenCalledOnce());
    expect(vi.mocked(pipelinesApi.apply).mock.calls[0]![0].replace_service_id).toBe("old");
    view.rerender(ui());
    expect((screen.getByRole("textbox", { name: "Service name" }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole("region", { name: "Monitoring setup progress" })).toBeTruthy();
    expect(screen.queryByText("Previous service retired")).toBeNull();
    vi.mocked(pipelinesApi.activation).mockResolvedValue({ id: "activation", phase: "succeeded", service_id: "service", run_id: "run",
      predecessor_service_id: "old", error: null, created_at: "2026-10-20T10:00:00Z", updated_at: "2026-10-20T10:00:00Z" });
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await waitFor(() => expect(callbacks.onStarted).toHaveBeenCalledWith("service"));
  });
  it("keeps a failed service load visible when the catalog arrives afterwards", async () => {
    let finishCatalog!: (value: typeof catalog) => void;
    vi.mocked(pipelinesApi.catalog).mockImplementation(() => new Promise((resolve) => { finishCatalog = resolve; }));
    vi.mocked(pipelinesApi.service).mockRejectedValue(new Error("Previous service unavailable"));
    render(<MemoryRouter initialEntries={["/?create=monitoring&replace=missing"]}>
      <PipelineWorkspace services={[]} index={{ targets: [], inputs: new Map(), byStream: new Map() }}
        canEdit onBack={() => {}} onStarted={() => {}} />
    </MemoryRouter>);
    await waitFor(() => expect(pipelinesApi.service).toHaveBeenCalled());
    await act(async () => { finishCatalog(catalog); });
    expect((await screen.findByRole("alert")).textContent).toContain("Previous service unavailable");
    expect(screen.queryByText("Loading service configuration…")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
  it("shows service details and applies the edited graph without saving or publishing a template", async () => {
    mount();
    const name = await screen.findByRole("textbox", { name: "Service name" });
    fireEvent.change(name, { target: { value: "Room health" } });
    expect((screen.getByRole("combobox", { name: "Reading for Value" }) as HTMLSelectElement).value).toBe("current");
    expect(screen.queryByRole("button", { name: /Publish revision|Save draft|Start revision/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Apply monitoring" }));
    await waitFor(() => expect(pipelinesApi.apply).toHaveBeenCalled());
    expect(vi.mocked(pipelinesApi.apply).mock.calls[0]![0]).toEqual(expect.objectContaining({ display_name: "Room health", definition, bindings: { value: "current" } }));
    expect(pipelinesApi.save).not.toHaveBeenCalled(); expect(pipelinesApi.publish).not.toHaveBeenCalled();
    expect((screen.getByRole("textbox", { name: "Service name" }) as HTMLInputElement).disabled).toBe(true);
  });
  it("focuses the missing name and retains the edited graph", async () => {
    mount();
    fireEvent.change(await screen.findByRole("textbox", { name: "Service name" }), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "Apply monitoring" }));
    expect(screen.getByText("Enter a service name.")).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Service name" }));
    expect(pipelinesApi.apply).not.toHaveBeenCalled();
  });
  it("blocks an invalid processing graph before reserving a start", async () => {
    vi.mocked(pipelinesApi.validate).mockImplementation(async (_id, definition) => ({ valid: false, definition: normalizeDefinition(definition), issues: [{ code: "disconnected", message: "Connect the detector" }], features: {}, provenance_complete: true }));
    mount(); fireEvent.click(await screen.findByRole("button", { name: "Apply monitoring" }));
    await screen.findByText("Resolve the highlighted processing issues before applying.");
    expect(pipelinesApi.apply).not.toHaveBeenCalled();
  });
  it("waits for collection before applying", async () => {
    mount({ collectionReady: false }); fireEvent.click(await screen.findByRole("button", { name: "Apply monitoring" }));
    expect(screen.getByText(/Enable collection in Sources/)).toBeTruthy(); expect(pipelinesApi.apply).not.toHaveBeenCalled();
  });
  it("saves a template under an independent name without starting a service", async () => {
    mount(); await saveDialog();
    fireEvent.change(screen.getByRole("textbox", { name: "Template name" }), { target: { value: "Reusable health" } });
    fireEvent.click(screen.getByRole("button", { name: "Update template" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(pipelinesApi.save).toHaveBeenCalledWith("design", expect.objectContaining({ name: "Reusable health", expected_version: 1 }));
    expect((screen.getByRole("textbox", { name: "Service name" }) as HTMLInputElement).value).toBe("Room pipeline");
    expect(pipelinesApi.apply).not.toHaveBeenCalled(); expect(pipelinesApi.publish).not.toHaveBeenCalled();
  });
  it("preserves a concurrent template conflict and allows saving a separate copy", async () => {
    vi.mocked(pipelinesApi.save).mockRejectedValueOnce(new ApiRequestError("The template changed", 409));
    vi.mocked(pipelinesApi.create).mockResolvedValue({ ...pipeline(), id: "copy" });
    mount(); await saveDialog(); fireEvent.click(screen.getByRole("button", { name: "Update template" }));
    await screen.findByText("The template changed");
    expect((screen.getByRole("button", { name: "Update template" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Save as new template" }));
    await waitFor(() => expect(pipelinesApi.create).toHaveBeenCalledOnce());
    expect(pipelinesApi.apply).not.toHaveBeenCalled();
  });
  it("retains unsaved names and learning settings across navigation", async () => {
    const first = mount(); fireEvent.change(await screen.findByRole("textbox", { name: "Service name" }), { target: { value: "Unsaved service" } });
    await settings(); fireEvent.change(screen.getByRole("spinbutton", { name: "Calibration observations" }), { target: { value: "123" } });
    first.unmount(); mount();
    expect((await screen.findByRole("textbox", { name: "Service name" }) as HTMLInputElement).value).toBe("Unsaved service");
    await settings(); expect((screen.getByRole("spinbutton", { name: "Calibration observations" }) as HTMLInputElement).value).toBe("123");
  });
  it("opens a historical configuration independently of unsaved template edits", async () => {
    const current = mount();
    await screen.findByRole("textbox", { name: "Service name" });
    await settings();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Calibration observations" }), { target: { value: "123" } });
    current.unmount();
    render(<MemoryRouter><PipelineEditor {...props()} revisionId="revision" /></MemoryRouter>);
    await screen.findByRole("textbox", { name: "Service name" });
    await settings();
    expect((screen.getByRole("spinbutton", { name: "Calibration observations" }) as HTMLInputElement).value).toBe("360");
  });
  it("fails closed when a historical revision cannot load", async () => {
    render(<MemoryRouter><PipelineEditor {...props()} revisionId="missing" /></MemoryRouter>);
    await screen.findByText(/Published revision not found/);
    expect(screen.queryByRole("button", { name: "Apply monitoring" })).toBeNull();
  });
  it("does not offer authoring when the operator disabled it", async () => {
    mount({ catalog: { ...catalog, authoring_enabled: false } });
    await screen.findByText("Monitoring configuration is disabled for this deployment.");
    expect(screen.queryByRole("button", { name: "Apply monitoring" })).toBeNull();
  });
});
