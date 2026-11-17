import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mutedAlarms, shadowSince } from "@/domain/monitoring/shadowReview";
import { ShadowReview } from "@/features/monitoring/ShadowReview";
import { RationaleCard } from "@/features/workspace/RationaleCard";
import { apiUtils } from "@/lib/api-client";
import type { ActiveService } from "@/types/monitoring";
import type { MonitorOrigin } from "@/types/pipelines.generated";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiUtils: { get: vi.fn(), post: vi.fn() },
}));

const rationale = { watches: "Pump vibration above its daily band.", why: "A moving distance on two readings.",
  evidence: "1 alarm in 9 scored hours.", limits: "First mornings alarm." };
const origin: MonitorOrigin = {
  author: "Designer", author_kind: "agent", rationale, test_run_id: "t1",
  history: [
    { event: "started", author: "Designer", author_kind: "agent", rationale, shadow: true, test_run_id: "t1", at: "2026-11-01T00:00:00Z" },
    { event: "stopped", author: "admin@example.com", author_kind: "member", note: "Paused for maintenance.", at: "2026-11-02T00:00:00Z" },
    { event: "started", author: "admin@example.com", author_kind: "member", shadow: true, at: "2026-11-03T00:00:00Z" },
  ],
};
const service = { id: "s1", reading_ids: ["vibration"], shadow: true, created_at: "2026-10-30T00:00:00Z", origin } as unknown as ActiveService;
const row = (sequence_number: number, timestamp: string, alarm = true) => ({ sequence_number, timestamp, alarm });

describe("a monitor's rationale", () => {
  it("says what it watches in one line and opens into the fields and each start and stop", () => {
    const { container } = render(<RationaleCard author={origin.author} authorKind={origin.author_kind} rationale={rationale} history={origin.history} />);
    const card = container.querySelector("details")!;
    expect(card.open).toBe(false);
    expect(card.querySelector("summary")!.textContent).toBe(`Watches ${rationale.watches}Agent · Designer`);
    expect(screen.getByText("Limits").nextElementSibling?.textContent).toBe(rationale.limits);
    const steps = screen.getAllByRole("listitem").map((item) => item.textContent);
    // Newest first.
    expect(steps[0]).toMatch(/^Started in shadow by admin@example.com/);
    expect(steps[1]).toContain("Paused for maintenance.");
    expect(steps[2]).toMatch(/^Started in shadow by the agent Designer.* · after a test$/);
  });

  it("names a member who started a monitor without one", () => {
    render(<RationaleCard author="admin@example.com" authorKind="member" />);
    expect(screen.getByText("No rationale recorded")).toBeTruthy();
    expect(screen.getByText("admin@example.com")).toBeTruthy();
  });
});

describe("a shadow run under review", () => {
  beforeEach(() => vi.mocked(apiUtils.get).mockReset());

  it("runs since its latest start and counts alarms in a row once", () => {
    expect(shadowSince(service)).toBe("2026-11-03T00:00:00Z");
    expect(shadowSince({ ...service, origin: null })).toBe("2026-10-30T00:00:00Z");
    const rows = [row(4, "2026-11-04T00:00:00Z"), row(5, "2026-11-04T00:00:01Z"), row(9, "2026-11-04T01:00:00Z"),
      row(1, "2026-11-01T00:00:00Z"), row(10, "2026-11-04T01:00:01Z", false)];
    expect(mutedAlarms(rows, "2026-11-03T00:00:00Z")).toEqual({ observations: 3, episodes: 2 });
  });

  it("shows the muted alarms beside what the test said, and stops on a member's word", async () => {
    vi.mocked(apiUtils.get).mockResolvedValue([row(4, "2026-11-04T00:00:00Z"), row(5, "2026-11-04T00:00:01Z")]);
    vi.mocked(apiUtils.post).mockResolvedValue({});
    const onTakeLive = vi.fn();
    const onStopped = vi.fn();
    render(<ShadowReview service={service} canEdit onTakeLive={onTakeLive} onStopped={onStopped} />);
    expect(vi.mocked(apiUtils.get).mock.calls[0]![0]).toBe("/v1/evidence/chart?reading_id=vibration&monitor_id=s1&alarm=true&limit=2000");
    expect((await screen.findByText(/^1 alarm over 2 observations$/))).toBeTruthy();
    expect(screen.getByText("The test said").nextElementSibling?.textContent).toBe(rationale.evidence);
    fireEvent.click(screen.getByRole("button", { name: "Take live" }));
    expect(onTakeLive).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    await waitFor(() => expect(onStopped).toHaveBeenCalledOnce());
    expect(vi.mocked(apiUtils.post).mock.calls[0]![0]).toBe("/v1/monitors/s1/stop");
  });

  it("offers no way out to a reader", () => {
    vi.mocked(apiUtils.get).mockResolvedValue([]);
    render(<ShadowReview service={service} canEdit={false} onTakeLive={() => {}} />);
    expect(screen.queryByRole("button", { name: "Take live" })).toBeNull();
  });
});
