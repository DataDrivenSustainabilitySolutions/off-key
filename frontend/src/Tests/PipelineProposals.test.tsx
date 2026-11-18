import { fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import { pipelinesApi } from "@/features/pipelines/api";
import { normalizeCatalog, normalizeDefinition, normalizeLayout, type PipelineProposal } from "@/features/pipelines/contracts";
import { DesignTestContext, type DesignTest } from "@/features/pipelines/designTest";
import { DeclineProposal, PipelineProposalBrief, PipelineProposalList } from "@/features/pipelines/PipelineProposals";
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
    proposals: vi.fn(), capacity: vi.fn(), proposal: vi.fn(), decideProposal: vi.fn(), catalog: vi.fn(), validate: vi.fn(), apply: vi.fn(),
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
  vi.mocked(pipelinesApi.capacity).mockResolvedValue({ running: 1, limit: 6 });
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
const card = (name: string) => screen.findByRole("article", { name });
const rationale = { watches: "Pump vibration above its daily band.", why: "A moving distance on two readings.",
  evidence: "1 alarm in 9 scored hours.", limits: "First mornings alarm." };

describe("proposals", () => {
  it("says what became of a proposal", () => {
    expect(proposalOutcome(summary())).toBe("");
    // The word that came with a decision reads on its own, under who decided.
    expect(proposalOutcome(declined)).toBe("Declined by admin@example.com");
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
    const open = await card("Pump vibration");
    // Without a rationale the reason is the case made; who handed it in, as what and how tested reads under the name.
    expect(within(open).getByText("Reason").nextElementSibling?.textContent).toBe("The bearing ran hot twice in October and nothing watched it.");
    expect(within(open).queryByRole("button", { name: "Evidence and limits" })).toBeNull();
    // An agent reads as an agent: the name of its key says nothing to the member who decides.
    expect(within(open).getAllByRole("listitem")[0]?.textContent).toMatch(/^Agent/);
    expect(open.textContent).not.toContain("Night shift agent");
    expect(within(open).getAllByRole("listitem").slice(1).map((item) => item.textContent)).toEqual(["New service", "Not tested"]);
    // A list of waiting proposals need not say of each that it waits.
    expect(within(open).queryByText("Waiting for a decision")).toBeNull();
    expect(screen.queryByRole("article", { name: "Fan current" })).toBeNull();
    expect(screen.getByRole("button", { name: "Waiting 1" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    const decided = await card("Fan current");
    expect(within(decided).getByText("Declined by admin@example.com")).toBeTruthy();
    expect(within(decided).getByText("Alarms too often at night")).toBeTruthy();
    // A decided proposal is looked at, not reviewed; among decided ones a waiting one says that it waits.
    expect(within(decided).getByRole("button", { name: "View design of Fan current" })).toBeTruthy();
    expect(within(await card("Pump vibration")).getByText("Waiting for a decision")).toBeTruthy();
    expect(vi.mocked(pipelinesApi.proposals).mock.calls.map((call) => call[0])).toEqual(["open", undefined]);
    fireEvent.click(screen.getByRole("button", { name: "Review Pump vibration" }));
    expect(onReview).toHaveBeenCalledExactlyOnceWith(summary());
    // The name opens it too.
    fireEvent.click(screen.getByRole("button", { name: "Pump vibration" }));
    expect(onReview).toHaveBeenCalledTimes(2);
  });

  it("lays a proposal with a rationale out under what it watches, the evidence and the limits", async () => {
    vi.mocked(pipelinesApi.proposals).mockResolvedValue([
      summary({ rationale, reason: "A longer word from the author.", test_run_id: "run-7", replace_monitor_id: "running" })]);
    render(<PipelineProposalList onReview={() => {}} onBack={() => {}} services={[{ id: "running", display_name: "Valve watch" } as ActiveService]} />);
    const open = await card("Pump vibration");
    for (const [label, text] of [["Watches", rationale.watches], ["Evidence", rationale.evidence], ["Limits", rationale.limits]] as const)
      expect(within(open).getByText(label).nextElementSibling?.textContent).toBe(text);
    // Why it is built this way and what else the author wrote wait in the review.
    expect(within(open).queryByText("Why this design")).toBeNull();
    expect(within(open).queryByText("A longer word from the author.")).toBeNull();
    expect(within(open).getAllByRole("listitem").slice(1).map((item) => item.textContent)).toEqual(["Replaces Valve watch", "Tested on history"]);
    // A phone shows what the design watches and folds the rest behind a button that names it.
    const more = within(open).getByRole("button", { name: "Evidence and limits" });
    expect([more.getAttribute("aria-expanded"), open.getAttribute("data-more")]).toEqual(["false", "false"]);
    fireEvent.click(more);
    expect([more.getAttribute("aria-expanded"), open.getAttribute("data-more")]).toEqual(["true", "true"]);
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

  it("declines from the list, and marks one whose readings are gone", async () => {
    vi.mocked(pipelinesApi.proposals).mockResolvedValue([summary({ missing_readings: ["demo-hamburg:30:occupancy"] })]);
    const view = render(<PipelineProposalList onReview={() => {}} onBack={() => {}} canDecide />);
    expect((await card("Pump vibration")).textContent).toContain("Its reading no longer exists: demo-hamburg:30:occupancy. It cannot start as proposed.");
    fireEvent.click(screen.getByRole("button", { name: "Decline Pump vibration" }));
    fireEvent.change(within(screen.getByRole("dialog", { name: "Decline Pump vibration" }))
      .getByRole("textbox", { name: "Note for the author (optional)" }), { target: { value: "Source removed" } });
    vi.mocked(pipelinesApi.proposals).mockResolvedValue([]);
    fireEvent.click(screen.getByRole("button", { name: "Decline proposal" }));
    expect(await screen.findByText("No proposal waits for a decision.")).toBeTruthy();
    expect(pipelinesApi.decideProposal).toHaveBeenLastCalledWith("p1", { status: "declined", note: "Source removed" });
    // Only a member who manages monitors declines; others review.
    view.unmount();
    vi.mocked(pipelinesApi.proposals).mockResolvedValue([summary()]);
    render(<PipelineProposalList onReview={() => {}} onBack={() => {}} />);
    await screen.findByRole("button", { name: "Review Pump vibration" });
    expect(screen.queryByRole("button", { name: "Decline Pump vibration" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Start Pump vibration" })).toBeNull();
    expect(screen.getByText("It waits for a member who manages monitors.")).toBeTruthy();
  });

  it("starts a proposal from the list, live or in shadow, and accepts it", async () => {
    const onStarted = vi.fn();
    render(<PipelineProposalList onReview={() => {}} onBack={() => {}} onStarted={onStarted} canDecide />);
    fireEvent.click(await screen.findByRole("button", { name: "Start Pump vibration" }));
    // Each way to start says what it does.
    expect(screen.getByRole("button", { name: "Start monitoring" }).getAttribute("aria-describedby")).toBeTruthy();
    expect(within(screen.getByRole("dialog", { name: "Start Pump vibration" })).getByText("Records the alarms it would raise and raises none.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start in shadow" }));
    await waitFor(() => expect(pipelinesApi.decideProposal).toHaveBeenCalledWith("p1", { status: "accepted" }));
    expect(pipelinesApi.apply).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      display_name: "Pump vibration", bindings: { value: "current" }, replace_monitor_id: null, shadow: true }));
    expect(screen.queryByRole("button", { name: "Decline Pump vibration" })).toBeNull();
    vi.mocked(pipelinesApi.activation).mockResolvedValue({ ...activation, phase: "succeeded" });
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith("service"), { timeout: 5000 });
  });

  it("starts nothing and decides nothing when the start is cancelled or refused", async () => {
    render(<PipelineProposalList onReview={() => {}} onBack={() => {}} canDecide />);
    fireEvent.click(await screen.findByRole("button", { name: "Start Pump vibration" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Decline Pump vibration" })).toBeTruthy();
    vi.mocked(pipelinesApi.apply).mockRejectedValue(new ApiRequestError("No monitor place is free.", 409));
    fireEvent.click(screen.getByRole("button", { name: "Start Pump vibration" }));
    fireEvent.click(screen.getByRole("button", { name: "Start monitoring" }));
    expect(await screen.findByText("No monitor place is free.")).toBeTruthy();
    expect(pipelinesApi.decideProposal).not.toHaveBeenCalled();
    // The card keeps its actions, with the reason, so the start can be tried again once there is room.
    vi.mocked(pipelinesApi.apply).mockResolvedValue(activation);
    fireEvent.click(screen.getByRole("button", { name: "Start Pump vibration" }));
    fireEvent.click(screen.getByRole("button", { name: "Start monitoring" }));
    await waitFor(() => expect(pipelinesApi.decideProposal).toHaveBeenCalledExactlyOnceWith("p1", { status: "accepted" }));
  });

  it("accepts the proposal when an interrupted start is recovered", async () => {
    vi.mocked(pipelinesApi.apply).mockRejectedValueOnce(new ApiRequestError("Gateway timeout", 504));
    render(<PipelineProposalList onReview={() => {}} onBack={() => {}} canDecide />);
    fireEvent.click(await screen.findByRole("button", { name: "Start Pump vibration" }));
    fireEvent.click(screen.getByRole("button", { name: "Start monitoring" }));
    fireEvent.click(await screen.findByRole("button", { name: "Recover start request" }));
    await waitFor(() => expect(pipelinesApi.decideProposal).toHaveBeenCalledExactlyOnceWith("p1", { status: "accepted" }));
    expect(pipelinesApi.apply).toHaveBeenCalledTimes(2);
  });

  it("says why a proposal cannot start from the list", async () => {
    vi.mocked(pipelinesApi.capacity).mockResolvedValue({ running: 2, limit: 2 });
    vi.mocked(pipelinesApi.proposals).mockResolvedValue([
      summary(), summary({ id: "p3", name: "Fan current", missing_readings: ["gone"] }),
      summary({ id: "p4", name: "Valve", replace_monitor_id: "running" }), summary({ id: "p5", name: "Pump", replace_monitor_id: "stopped" }),
    ]);
    const running = { id: "running", display_name: "Valve watch", shadow: true } as ActiveService;
    render(<PipelineProposalList onReview={() => {}} onBack={() => {}} canDecide services={[running]} />);
    const start = await screen.findByRole("button", { name: "Start Pump vibration" });
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(true));
    expect(start.getAttribute("aria-describedby") && document.getElementById(start.getAttribute("aria-describedby")!)?.textContent)
      .toBe("No monitor place is free.");
    expect((screen.getByRole("button", { name: "Start Fan current" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Review it to choose other readings.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Update with Pump" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("The service it replaces no longer runs. Review it to start it as a new one.")).toBeTruthy();
    // An update needs no free place, and keeps the service it replaces in shadow.
    vi.mocked(pipelinesApi.proposal).mockResolvedValue(proposal({ id: "p4", name: "Valve", replace_monitor_id: "running" }));
    fireEvent.click(screen.getByRole("button", { name: "Update with Valve" }));
    fireEvent.click(screen.getByRole("button", { name: "Update Valve watch" }));
    await waitFor(() => expect(pipelinesApi.apply).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ replace_monitor_id: "running", shadow: true })));
  });

  it("says how many monitor places are free, and warns when none is", async () => {
    const view = render(<PipelineProposalList onReview={() => {}} onBack={() => {}} canDecide />);
    expect(await screen.findByText("5 of 6 monitor places are free.")).toBeTruthy();
    view.unmount();
    vi.mocked(pipelinesApi.capacity).mockResolvedValue({ running: 2, limit: 2 });
    render(<PipelineProposalList onReview={() => {}} onBack={() => {}} canDecide />);
    expect((await screen.findByRole("alert")).textContent).toContain("All 2 monitor places are taken");
  });

  it("declines with a word for the author", async () => {
    const onDeclined = vi.fn();
    render(<DeclineProposal proposal={summary()} onDeclined={onDeclined} />);
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Note for the author (optional)" }), { target: { value: "  Alarms too often at night " } });
    vi.mocked(pipelinesApi.decideProposal).mockRejectedValueOnce(new ApiRequestError("This proposal is already accepted", 409));
    fireEvent.click(screen.getByRole("button", { name: "Decline proposal" }));
    expect((await screen.findByRole("alert")).textContent).toBe("This proposal is already accepted");
    expect(onDeclined).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Decline proposal" }));
    await waitFor(() => expect(onDeclined).toHaveBeenCalledOnce());
    expect(pipelinesApi.decideProposal).toHaveBeenLastCalledWith("p1", { status: "declined", note: "Alarms too often at night" });
    // Cancelling declines nothing.
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(pipelinesApi.decideProposal).toHaveBeenCalledTimes(2);
  });

  it("reads a proposal's rationale beside its design, each part under its name", () => {
    const view = render(<MemoryRouter><PipelineProposalBrief proposal={summary({ rationale, reason: rationale.watches })} canDecide={false} /></MemoryRouter>);
    const brief = screen.getByRole("group", { name: "Proposal by an agent" });
    expect(within(brief).getAllByRole("listitem")[0]?.textContent).toMatch(/^Agent/);
    expect(brief.textContent).not.toContain("Night shift agent");
    // Read alone, as on a phone, it opens with the name the design was handed in under.
    expect(brief.firstElementChild?.textContent).toBe("Pump vibration");
    for (const [label, text] of [["Watches", rationale.watches], ["Why this design", rationale.why], ["Evidence", rationale.evidence], ["Limits", rationale.limits]] as const)
      expect(screen.getByText(label).nextElementSibling?.textContent).toBe(text);
    // The reason it fell back to is not said twice.
    expect(screen.getAllByText(rationale.watches)).toHaveLength(1);
    expect(screen.queryByText("Author's note")).toBeNull();
    // What the author wrote beside the rationale reads under it, and is the whole case of a proposal without one.
    view.rerender(<MemoryRouter><PipelineProposalBrief proposal={summary({ rationale })} canDecide={false} /></MemoryRouter>);
    expect(screen.getByText("Author's note").nextElementSibling?.textContent).toBe("The bearing ran hot twice in October and nothing watched it.");
    view.rerender(<MemoryRouter><PipelineProposalBrief proposal={summary()} canDecide={false} /></MemoryRouter>);
    expect(screen.getByText("Reason").nextElementSibling?.textContent).toBe("The bearing ran hot twice in October and nothing watched it.");
  });

  it("leads from a proposal to the test it came with, beside the design and in the Dojo", () => {
    const onOpenTest = vi.fn();
    const view = render(<MemoryRouter><PipelineProposalBrief proposal={summary({ test_run_id: "run 7" })} canDecide={false}
      onOpenTest={onOpenTest} /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "See the run in the Dojo" }).getAttribute("href")).toBe("/dojo?run=run%207");
    expect(screen.getByText("Tested on history")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open the test" }));
    expect(onOpenTest).toHaveBeenCalledOnce();
    // A proposal that came without a test says so, and offers to run one where the setup can.
    view.rerender(<MemoryRouter><PipelineProposalBrief proposal={summary()} canDecide={false} onOpenTest={onOpenTest} /></MemoryRouter>);
    expect(screen.queryByRole("link", { name: "See the run in the Dojo" })).toBeNull();
    expect(screen.getByText("Not tested")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Test on history" }));
    expect(onOpenTest).toHaveBeenCalledTimes(2);
    // A member who may not use the Dojo is told of the test and is not led to a page that is closed to them.
    view.rerender(<MemoryRouter><PipelineProposalBrief proposal={summary({ test_run_id: "run 7" })} canDecide={false} /></MemoryRouter>);
    expect(screen.getByText("Tested on history")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "See the run in the Dojo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Open the test" })).toBeNull();
  });

  it("names a member who handed a proposal in, and an agent only as an agent", () => {
    const view = render(<MemoryRouter><PipelineProposalBrief proposal={summary({ author: "dana@example.com", author_kind: "member" })} canDecide={false} /></MemoryRouter>);
    const brief = screen.getByRole("group", { name: "Proposal by dana@example.com" });
    expect(within(brief).getAllByRole("listitem")[0]?.textContent).toMatch(/^dana@example\.com/);
    view.rerender(<MemoryRouter><PipelineProposalBrief proposal={summary()} canDecide={false} /></MemoryRouter>);
    expect(screen.getByRole("group", { name: "Proposal by an agent" }).textContent).not.toContain("Night shift agent");
  });

  it("says where a proposal stands, and leaves the decision to a member who manages monitors", () => {
    const view = render(<MemoryRouter><PipelineProposalBrief proposal={summary()} canDecide={false} /></MemoryRouter>);
    expect(screen.getByText("Waiting for a decision")).toBeTruthy();
    expect(screen.getByText("It waits for a member who manages monitors.")).toBeTruthy();
    view.rerender(<MemoryRouter><PipelineProposalBrief proposal={summary()} canDecide /></MemoryRouter>);
    expect(screen.getByText("Starting the service accepts the proposal. Change the design first if you wish.")).toBeTruthy();
    view.rerender(<MemoryRouter><PipelineProposalBrief proposal={declined} canDecide /></MemoryRouter>);
    expect(screen.getByText("Declined by admin@example.com")).toBeTruthy();
    expect(screen.getByText("Alarms too often at night")).toBeTruthy();
    expect(screen.queryByText(/Starting the service accepts/)).toBeNull();
  });

  it("opens a proposal from the list in the setup", async () => {
    workspace("/?view=proposals");
    fireEvent.click(await screen.findByRole("button", { name: "Review Pump vibration" }));
    expect(address()).toBe("?create=monitoring&proposal=p1");
    expect((await screen.findByRole("textbox", { name: "Service name" }) as HTMLInputElement).value).toBe("Pump vibration");
    // The proposal opens beside its design, under a button of its own, and leaves the canvas whole when closed.
    expect(screen.getByRole("group", { name: "Proposal by an agent" })).toBeTruthy();
    const panels = within(screen.getByLabelText("Settings panels"));
    expect(panels.getByRole("button", { name: "Proposal" }).getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Close proposal" }));
    expect(screen.queryByRole("group", { name: "Proposal by an agent" })).toBeNull();
    fireEvent.click(panels.getByRole("button", { name: "Proposal" }));
    expect(screen.getByRole("group", { name: "Proposal by an agent" })).toBeTruthy();
    // On a phone the proposal and the design take turns, and two tabs say which one shows.
    const tabs = within(screen.getByRole("group", { name: "Show" }));
    expect(tabs.getByRole("button", { name: "Proposal" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(tabs.getByRole("button", { name: "Design" }));
    expect(screen.queryByRole("group", { name: "Proposal by an agent" })).toBeNull();
    expect(tabs.getByRole("button", { name: "Design" }).getAttribute("aria-pressed")).toBe("true");
    // A panel of the design leaves the design's tab chosen.
    fireEvent.click(panels.getByRole("button", { name: "Step settings" }));
    expect(tabs.getByRole("button", { name: "Design" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(tabs.getByRole("button", { name: "Proposal" }));
    expect(screen.getByRole("group", { name: "Proposal by an agent" })).toBeTruthy();
    // The decision stands together, apart from the templates: Decline beside the way to start.
    expect(screen.getByRole("button", { name: "Decline" }).parentElement)
      .toBe(screen.getByRole("button", { name: "Start monitoring" }).parentElement);
    expect(screen.getByRole("button", { name: "Load template" }).parentElement)
      .not.toBe(screen.getByRole("button", { name: "Start monitoring" }).parentElement);
    // The design on the canvas is the proposed one, and it names the reading it was made for.
    expect(screen.getByRole("button", { name: "Input: Room, 1 of 1 readings" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Proposals" }));
    expect(address()).toBe("?view=proposals");
  });

  it("shows the design for what is left to do, where the proposal is read in place of it", async () => {
    vi.mocked(pipelinesApi.validate).mockImplementation(async (sent) => ({ valid: false, definition: normalizeDefinition(sent),
      issues: [{ code: "disconnected", message: "Connect the detector" }], features: {}, provenance_complete: true }));
    workspace("/?create=monitoring&proposal=p1");
    const start = await screen.findByRole("button", { name: "Start monitoring" });
    // Beside the design the proposal stays where it is while the list opens.
    fireEvent.click(start);
    expect(await screen.findByText("Connect the detector")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Proposal by an agent" })).toBeTruthy();
    // A phone's styles keep the canvas out of sight while the proposal is read.
    document.querySelector<HTMLElement>(".pl-stage-canvas")!.style.visibility = "hidden";
    fireEvent.click(start);
    await waitFor(() => expect(screen.queryByRole("group", { name: "Proposal by an agent" })).toBeNull());
    expect(screen.getByText("Connect the detector")).toBeTruthy();
    expect(pipelinesApi.apply).not.toHaveBeenCalled();
  });

  it("accepts the proposal when the member starts the service", async () => {
    workspace("/?create=monitoring&proposal=p1");
    fireEvent.click(await screen.findByRole("button", { name: "Start monitoring" }));
    await waitFor(() => expect(pipelinesApi.decideProposal).toHaveBeenCalledExactlyOnceWith("p1", { status: "accepted" }));
    const request = vi.mocked(pipelinesApi.apply).mock.calls[0]![0];
    expect(request).toMatchObject({ display_name: "Pump vibration", bindings: { value: "current" }, replace_monitor_id: null });
    expect(request.definition.nodes!.find((node) => node.id === "detector")!.label).toBe("Bearing watch");
    expect(await screen.findByText("Accepted by admin@example.com")).toBeTruthy();
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
    expect((await card("Pump vibration")).textContent).toContain("Replaces a running service");
    fireEvent.click(screen.getByRole("button", { name: "Review Pump vibration" }));
    expect(address()).toBe("?create=monitoring&proposal=p1&replace=old");
  });

  it("compares a proposal that replaces a service with what runs now", async () => {
    const old: ActiveService = { id: "old", display_name: "Pump watch", reading_ids: ["current"], active: true,
      operational_status: { stage: "operational", is_stale: false, message_count: 10, processed_message_count: 10 } };
    // The service runs the same steps; its detector goes by the name of its component.
    const runs = normalizeDefinition({ ...definition,
      nodes: definition.nodes.map((node) => node.id === "detector" ? { ...node, label: null } : node) });
    vi.mocked(pipelinesApi.proposal).mockResolvedValue(proposal({ replace_monitor_id: "old" }));
    vi.mocked(pipelinesApi.service).mockResolvedValue({ run: null, history: [], definition: runs, layout: normalizeLayout() });
    workspace("/?create=monitoring&proposal=p1&replace=old", [old]);
    expect(await screen.findByText("Compared with what runs now: 1 changed step.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Update monitoring" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Proposal by an agent" }).textContent).toContain("Replaces Pump watch");
    // A proposal for a service of its own has nothing to be compared with.
    vi.mocked(pipelinesApi.proposal).mockResolvedValue(proposal());
    workspace("/?create=monitoring&proposal=p1");
    await screen.findByRole("button", { name: "Start monitoring" });
    expect(screen.getAllByText(/Compared with what runs now/)).toHaveLength(1);
  });

  it("opens a proposal at its brief, with the test it came with one press away", async () => {
    // The screen that mounts the setup provides the test; here it only says what it is given.
    const test: DesignTest = {
      Panel: () => <p>The panel of the test</p>, Values: () => null,
      Status: ({ open, evidence }) => <>{evidence
        ? `Test ${evidence.run} by ${evidence.by}, ${evidence.definition.nodes.length} steps, ${open ? "open" : "closed"}` : "Test"}</>,
    };
    vi.mocked(pipelinesApi.proposal).mockResolvedValue(proposal({ test_run_id: "run-7" }));
    const view = render(<DesignTestContext.Provider value={test}><MemoryRouter initialEntries={["/?create=monitoring&proposal=p1"]}>
      <PipelineWorkspace services={[]} index={index} canEdit onBack={vi.fn()} onStarted={vi.fn()} />
    </MemoryRouter></DesignTestContext.Provider>);
    // The test is the design's own from the start; the proposal is read first.
    expect(await screen.findByRole("button", { name: "Test run-7 by Night shift agent, 5 steps, closed" })).toBeTruthy();
    expect(screen.queryByText("The panel of the test")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open the test" }));
    expect(screen.getByText("The panel of the test")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Test run-7 by Night shift agent, 5 steps, open" })).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Proposal by an agent" })).toBeNull();
    fireEvent.click(within(screen.getByLabelText("Settings panels")).getByRole("button", { name: "Proposal" }));
    expect(screen.getByRole("group", { name: "Proposal by an agent" })).toBeTruthy();
    view.unmount();
    // A proposal without a test offers to run one.
    vi.mocked(pipelinesApi.proposal).mockResolvedValue(proposal());
    render(<DesignTestContext.Provider value={test}><MemoryRouter initialEntries={["/?create=monitoring&proposal=p1"]}>
      <PipelineWorkspace services={[]} index={index} canEdit onBack={vi.fn()} onStarted={vi.fn()} />
    </MemoryRouter></DesignTestContext.Provider>);
    expect(await screen.findByRole("button", { name: "Test" })).toBeTruthy();
    expect(screen.queryByText("The panel of the test")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Test on history" }));
    expect(screen.getByText("The panel of the test")).toBeTruthy();
  });

  it("warns above the canvas when a proposal's readings are gone", async () => {
    vi.mocked(pipelinesApi.proposal).mockResolvedValue(proposal({ missing_readings: ["demo-hamburg:30:occupancy"] }));
    workspace("/?create=monitoring&proposal=p1");
    expect(await screen.findByText(
      "Its reading no longer exists: demo-hamburg:30:occupancy. It cannot start as proposed. Choose other readings at the Input step.")).toBeTruthy();
  });

  it("says when a proposal cannot be opened", async () => {
    vi.mocked(pipelinesApi.proposal).mockRejectedValueOnce(new ApiRequestError("Proposal not found", 404));
    workspace("/?create=monitoring&proposal=gone");
    expect((await screen.findByRole("alert")).textContent).toContain("Proposal not found");
  });
});
