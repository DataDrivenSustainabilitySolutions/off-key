import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PipelineActivation } from "@/features/pipelines/PipelineActivation";
import { pipelinesApi } from "@/features/pipelines/api";
import { clearNavigationDrafts } from "@/lib/navigation-draft";
import type { PipelineActivationView } from "@/types/pipelines.generated";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1 }) }));
vi.mock("@/features/pipelines/api", () => ({
  pipelinesApi: { apply: vi.fn(), activation: vi.fn(), cancel: vi.fn() },
}));
const operation = (phase: PipelineActivationView["phase"] = "requested"): PipelineActivationView => ({
  id: "activation", phase, monitor_id: "service", run_id: "run", predecessor_monitor_id: null, error: null,
  created_at: "2026-10-16T12:00:00Z", updated_at: "2026-10-16T12:00:00Z",
});
const props = () => ({ operationId: "activation", onClose: vi.fn(), onComplete: vi.fn() });
beforeEach(() => { vi.resetAllMocks(); clearNavigationDrafts(); });

describe("existing activation links", () => {
  it("follows the existing operation without submitting another monitor", async () => {
    vi.mocked(pipelinesApi.activation).mockResolvedValue(operation());
    const input = props();
    render(<PipelineActivation {...input} />);
    await screen.findByRole("heading", { name: "Preparing your service…" });
    expect(pipelinesApi.activation).toHaveBeenCalledWith("activation", expect.any(AbortSignal));
    expect(pipelinesApi.apply).not.toHaveBeenCalled();
    expect(input.onComplete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(input.onClose).toHaveBeenCalledOnce();
  });

  it("uses the shared cancellation flow and returns to setup after failure", async () => {
    vi.mocked(pipelinesApi.activation).mockResolvedValue(operation());
    vi.mocked(pipelinesApi.cancel).mockResolvedValue(operation("failed"));
    const input = props();
    render(<PipelineActivation {...input} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel start" }));
    fireEvent.click(await screen.findByRole("button", { name: "Return to setup" }));
    expect(pipelinesApi.cancel).toHaveBeenCalledWith("activation");
    expect(input.onClose).toHaveBeenCalledOnce();
  });

  it("explains why a replacement that is already retiring cannot be cancelled", async () => {
    vi.mocked(pipelinesApi.activation).mockResolvedValue({ ...operation("retiring"), retirement_started: true });
    render(<PipelineActivation {...props()} />);
    await screen.findByText(/this replacement can no longer be cancelled/);
    expect(screen.queryByRole("button", { name: "Cancel start" })).toBeNull();
  });

  it("opens a successful monitor exactly once", async () => {
    vi.mocked(pipelinesApi.activation).mockResolvedValue(operation("succeeded"));
    const input = props();
    const view = render(<PipelineActivation {...input} />);
    await waitFor(() => expect(input.onComplete).toHaveBeenCalledExactlyOnceWith("service"));
    view.rerender(<PipelineActivation {...input} />);
    expect(input.onComplete).toHaveBeenCalledOnce();
    view.unmount();
    render(<PipelineActivation {...input} />);
    await waitFor(() => expect(input.onComplete).toHaveBeenCalledTimes(2));
  });

  it("ignores a previous operation's reply after following another link", async () => {
    let finishOld!: (value: PipelineActivationView) => void;
    vi.mocked(pipelinesApi.activation)
      .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }))
      .mockResolvedValue({ ...operation("failed"), id: "other" });
    const input = props();
    const view = render(<PipelineActivation {...input} />);
    view.rerender(<PipelineActivation {...input} operationId="other" />);
    await screen.findByRole("heading", { name: "Monitoring could not start" });
    await act(async () => { finishOld(operation("succeeded")); });
    expect(input.onComplete).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Monitoring could not start" })).toBeTruthy();
  });
});
