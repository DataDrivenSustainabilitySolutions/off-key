import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import { pipelinesApi } from "@/features/pipelines/api";
import { normalizeCatalog, normalizeDefinition, normalizeLayout, type PipelineProposal } from "@/features/pipelines/contracts";
import { PipelineProposalList, PipelineProposalNotice } from "@/features/pipelines/PipelineProposals";
import PipelineWorkspace from "@/features/pipelines/PipelineWorkspace";
import { proposalOutcome, useOpenProposals } from "@/features/pipelines/proposals";
import { ApiRequestError } from "@/lib/api-client";
import { clearNavigationDrafts } from "@/lib/navigation-draft";
import type { ActiveService } from "@/types/monitoring";
import type { PipelineProposalSummary } from "@/types/pipelines.generated";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1, can: () => false }) }));
vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));
vi.mock("@/features/pipelines/api", () => ({
  pipelinesApi: {
    proposals: vi.fn(), proposal: vi.fn(), decideProposal: vi.fn(), catalog: vi.fn(), validate: vi.fn(), apply: vi.fn(),
    activation: vi.fn(), cancel: vi.fn(), service: vi.fn(), blocks: vi.fn(), list: vi.fn(),
  },
}));
const telemetry = new SystemLiveTelemetry();
vi.mock("@/features/workspace/catalogue-context", () => ({ useCatalogue: () => ({
  system: { snapshot: { runtime: { collection: { status: "applied" } } } }, document: undefined, telemetry, liveStreamIds: [], previewStreamIds: [] }) }));

const component = (id: string, kind: string, input: string | null, output: string, extra: object = {}) =>
  ({ id, kind, group: kind === "source" ? "input" : kind, label: id, description: "", input_type: input, output_type: output, ...extra });
const catalog = normalizeCatalog({
  catalog_id: "catalog", authoring_enabled: true, templates: [],
  components: [
    component("source.aligned", "source", null, "features"),
    component("detector:test", "detector", "features", "scores", { learning: "online" }),
    component("calibrate.fixed_split", "calibration", "scores", "p_values", { family: "conformal", coverage: "exchangeable" }),
    component("policy.quantile", "policy", "p_values", "decisions"),
    component("output.evidence", "output", "decisions", "evidence"),
  ],
} as unknown as Parameters<typeof normalizeCatalog>[0]);
const definition = normalizeDefinition({
  input_slots: [{ id: "value", label: "Value" }],
  nodes: [
    { id: "input", kind: "source", component: "source.aligned" },
    { id: "detector", kind: "detector", component: "detector:test", label: "Bearing watch" },
    { id: "calibrate", kind: "calibration", component: "calibrate.fixed_split" },
    { id: "policy", kind: "policy", component: "policy.quantile" },
    { id: "output", kind: "output", component: "output.evidence" },
  ],
  edges: [
    { source: "input", target: "detector" }, { source: "detector", target: "calibrate" },
    { source: "calibrate", target: "policy" }, { source: "policy", target: "output" },
  ],
});
const target: MonitoringTarget = { id: "room", label: "Room", inputs: [
  { path: "Room", stream: { id: "current", label: "Current", unit: "A", category: "Electrical", value_type: "number", topic: "fixture/current", broker_id: "broker" },
    binding: { policy: { mode: "original", interval_seconds: 10 } } },
] };
const index = { targets: [target], inputs: new Map(), byStream: new Map<string, Set<string>>() };

const summary = (change: Partial<PipelineProposalSummary> = {}): PipelineProposalSummary => ({
  id: "p1", name: "Pump vibration", reason: "The bearing ran hot twice in October and nothing watched it.",
  author: "Night shift agent", author_kind: "agent", status: "open", test_run_id: null, replace_monitor_id: null,
  decided_by: null, decided_at: null, decision_note: null, created_at: "2026-11-12T08:00:00Z", ...change,
});
const proposal = (change: Partial<PipelineProposalSummary> = {}): PipelineProposal =>
  ({ ...summary(change), definition, layout: normalizeLayout(), bindings: { value: "current" } });
const declined = summary({ id: "p2", name: "Fan current", status: "declined", decided_by: "admin@example.com",
  decided_at: "2026-11-12T09:00:00Z", decision_note: "Alarms too often at night" });
const activation = { id: "activation", phase: "requested" as const, monitor_id: "service", run_id: "run", predecessor_monitor_id: null,
  error: null, created_at: "2026-11-12T10:00:00Z", updated_at: "2026-11-12T10:00:00Z" };

beforeEach(() => {
  vi.resetAllMocks(); clearNavigationDrafts();
  vi.mocked(pipelinesApi.catalog).mockResolvedValue(catalog);
  vi.mocked(pipelinesApi.blocks).mockResolvedValue([]);
  vi.mocked(pipelinesApi.list).mockResolvedValue({ items: [], next_offset: null });
  vi.mocked(pipelinesApi.validate).mockImplementation(async (sent) => ({ valid: true, definition: normalizeDefinition(sent), issues: [], features: {}, provenance_complete: true }));
  vi.mocked(pipelinesApi.proposals).mockImplementation(async (status) => status === "open" ? [summary()] : [summary(), declined]);
  vi.mocked(pipelinesApi.proposal).mockResolvedValue(proposal());
  vi.mocked(pipelinesApi.apply).mockResolvedValue(activation);
  vi.mocked(pipelinesApi.activation).mockResolvedValue(activation);
  vi.mocked(pipelinesApi.decideProposal).mockImplementation(async (id, decision) =>
    summary({ id, status: decision.status, decided_by: "admin@example.com", decided_at: "2026-11-12T10:00:00Z", decision_note: decision.note ?? null }));
});

function Where() { return <output aria-label="Address">{useLocation().search}</output>; }
const workspace = (address: string, services: ActiveService[] = [], canEdit = true) => render(<MemoryRouter initialEntries={[address]}>
  <PipelineWorkspace services={services} index={index} canEdit={canEdit} onBack={() => {}} onStarted={() => {}} /><Where />
</MemoryRouter>);
const address = () => screen.getByRole("status", { name: "Address" }).textContent;

describe("proposals", () => {
  it("says what became of a proposal", () => {
    expect(proposalOutcome(summary())).toBe("");
    expect(proposalOutcome(declined)).toBe("Declined by admin@example.com: Alarms too often at night");
    expect(proposalOutcome(summary({ status: "accepted", decided_by: "admin@example.com" }))).toBe("Accepted by admin@example.com");
    expect(proposalOutcome(summary({ status: "withdrawn" }))).toBe("Withdrawn by its author");
  });

  it("counts the proposals that wait, for a member who is signed in", async () => {
    const waiting = renderHook(({ enabled }) => useOpenProposals(enabled), { initialProps: { enabled: true } });
    await waitFor(() => expect(waiting.result.current).toBe(1));
    expect(pipelinesApi.proposals).toHaveBeenCalledWith("open", expect.any(AbortSignal));
    waiting.rerender({ enabled: false });
    expect(waiting.result.current).toBe(0);
    // A count that cannot be read is no error of the page.
    vi.mocked(pipelinesApi.proposals).mockRejectedValue(new Error("offline"));
    expect(renderHook(() => useOpenProposals(true)).result.current).toBe(0);
  });

  it("lists the proposals that wait and, when asked, the decided ones", async () => {
    const onReview = vi.fn();
    render(<PipelineProposalList onReview={onReview} onBack={() => {}} />);
    const open = await screen.findByRole("button", { name: "Review Pump vibration" });
    expect(open.textContent).toContain("The bearing ran hot twice in October and nothing watched it.");
    expect(open.textContent).toContain("Proposed by Night shift agent");
    expect(screen.queryByRole("button", { name: "Review Fan current" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Show decided proposals" }));
    const decided = await screen.findByRole("button", { name: "Review Fan current" });
    expect(decided.textContent).toContain("Declined by admin@example.com: Alarms too often at night");
    expect(vi.mocked(pipelinesApi.proposals).mock.calls.map((call) => call[0])).toEqual(["open", undefined]);
    fireEvent.click(screen.getByRole("button", { name: "Review Pump vibration" }));
    expect(onReview).toHaveBeenCalledExactlyOnceWith(summary());
  });

  it("says when none waits, and offers to read the list again when it cannot be read", async () => {
    vi.mocked(pipelinesApi.proposals).mockResolvedValueOnce([]);
    const view = render(<PipelineProposalList onReview={() => {}} onBack={() => {}} />);
    expect(await screen.findByText("No proposal waits for a decision.")).toBeTruthy();
    view.unmount();
    vi.mocked(pipelinesApi.proposals).mockRejectedValueOnce(new Error("The list could not be read"));
    render(<PipelineProposalList onReview={() => {}} onBack={() => {}} />);
    expect((await screen.findByRole("alert")).textContent).toContain("The list could not be read");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "Review Pump vibration" })).toBeTruthy();
  });

  it("declines with a word for the author", async () => {
    const onDeclined = vi.fn();
    render(<PipelineProposalNotice proposal={summary()} canDecide onDeclined={onDeclined} />);
    const notice = screen.getByRole("group", { name: "Proposal by Night shift agent" });
    expect(notice.textContent).toContain("Starting the service accepts the proposal.");
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Why you decline" }), { target: { value: "  Alarms too often at night " } });
    vi.mocked(pipelinesApi.decideProposal).mockRejectedValueOnce(new ApiRequestError("This proposal is already accepted", 409));
    fireEvent.click(screen.getByRole("button", { name: "Decline proposal" }));
    expect((await screen.findByRole("alert")).textContent).toBe("This proposal is already accepted");
    expect(onDeclined).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Decline proposal" }));
    await waitFor(() => expect(onDeclined).toHaveBeenCalledOnce());
    expect(pipelinesApi.decideProposal).toHaveBeenLastCalledWith("p1", { status: "declined", note: "Alarms too often at night" });
  });

  it("leaves the decision to a member who manages monitors, and shows one that was made", () => {
    const view = render(<PipelineProposalNotice proposal={summary()} canDecide={false} onDeclined={() => {}} />);
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull();
    expect(screen.getByText("It waits for a member who manages monitors.")).toBeTruthy();
    view.rerender(<PipelineProposalNotice proposal={declined} canDecide onDeclined={() => {}} />);
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull();
    expect(screen.getByText("Declined by admin@example.com: Alarms too often at night.")).toBeTruthy();
  });

  it("opens a proposal from the list in the setup", async () => {
    workspace("/?view=proposals");
    fireEvent.click(await screen.findByRole("button", { name: "Review Pump vibration" }));
    expect(address()).toBe("?create=monitoring&proposal=p1");
    expect((await screen.findByRole("textbox", { name: "Service name" }) as HTMLInputElement).value).toBe("Pump vibration");
    expect(screen.getByRole("group", { name: "Proposal by Night shift agent" })).toBeTruthy();
    // The design on the canvas is the proposed one, and it names the reading it was made for.
    expect(screen.getByRole("button", { name: "Input: Room, 1 of 1 readings" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
    expect(address()).toBe("?view=proposals");
  });

  it("accepts the proposal when the member starts the service", async () => {
    workspace("/?create=monitoring&proposal=p1");
    fireEvent.click(await screen.findByRole("button", { name: "Start monitoring" }));
    await waitFor(() => expect(pipelinesApi.decideProposal).toHaveBeenCalledExactlyOnceWith("p1", { status: "accepted" }));
    const request = vi.mocked(pipelinesApi.apply).mock.calls[0]![0];
    expect(request).toMatchObject({ display_name: "Pump vibration", bindings: { value: "current" }, replace_monitor_id: null });
    expect(request.definition.nodes!.find((node) => node.id === "detector")!.label).toBe("Bearing watch");
    expect(await screen.findByText("Accepted by admin@example.com.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull();
  });

  it("decides nothing when the start is refused", async () => {
    vi.mocked(pipelinesApi.apply).mockRejectedValue(new ApiRequestError("The reading is already monitored", 409));
    workspace("/?create=monitoring&proposal=p1");
    fireEvent.click(await screen.findByRole("button", { name: "Start monitoring" }));
    await waitFor(() => expect(pipelinesApi.apply).toHaveBeenCalledOnce());
    expect(await screen.findByText(/The reading is already monitored/)).toBeTruthy();
    expect(pipelinesApi.decideProposal).not.toHaveBeenCalled();
  });

  it("declines from the setup and returns to the list", async () => {
    workspace("/?create=monitoring&proposal=p1");
    fireEvent.click(await screen.findByRole("button", { name: "Decline" }));
    fireEvent.click(screen.getByRole("button", { name: "Decline proposal" }));
    await waitFor(() => expect(address()).toBe("?view=proposals"));
    expect(pipelinesApi.decideProposal).toHaveBeenCalledExactlyOnceWith("p1", { status: "declined", note: null });
  });

  it("opens a proposal that replaces a service as an update of it", async () => {
    vi.mocked(pipelinesApi.proposals).mockResolvedValue([summary({ replace_monitor_id: "old" })]);
    vi.mocked(pipelinesApi.proposal).mockResolvedValue(proposal({ replace_monitor_id: "old" }));
    vi.mocked(pipelinesApi.service).mockRejectedValue(new Error("gone"));
    workspace("/?view=proposals");
    const row = await screen.findByRole("button", { name: "Review Pump vibration" });
    expect(row.textContent).toContain("Replaces a running service");
    fireEvent.click(row);
    expect(address()).toBe("?create=monitoring&proposal=p1&replace=old");
  });

  it("says when a proposal cannot be opened", async () => {
    vi.mocked(pipelinesApi.proposal).mockRejectedValueOnce(new ApiRequestError("Proposal not found", 404));
    workspace("/?create=monitoring&proposal=gone");
    expect((await screen.findByRole("alert")).textContent).toContain("Proposal not found");
  });
});
