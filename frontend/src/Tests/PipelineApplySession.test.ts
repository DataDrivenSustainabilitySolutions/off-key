import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "@/lib/api-client";
import { clearNavigationDrafts, readStoredDraft } from "@/lib/navigation-draft";
import { pipelinesApi } from "@/features/pipelines/api";
import { createApplySession, usePipelineApply } from "@/features/pipelines/applySession";
import { bindingsReady, suggestBindings } from "@/features/pipelines/bindings";
import { normalizeDefinition, normalizeLayout } from "@/features/pipelines/contracts";
import type { MonitoringTarget } from "@/features/monitoring/serviceModel";
import type { PipelineActivationView } from "@/types/pipelines.generated";

vi.mock("@/features/pipelines/api", () => ({ pipelinesApi: { apply: vi.fn(), activation: vi.fn(), cancel: vi.fn() } }));
const request = () => ({ definition: normalizeDefinition({}), layout: normalizeLayout(), bindings: { value: "current" },
  display_name: "Health", idempotency_key: "one-immutable-request", replace_service_id: null });
const operation = (phase: PipelineActivationView["phase"] = "requested"): PipelineActivationView => ({
  id: "activation", phase, service_id: "service", run_id: "run", predecessor_service_id: null, error: null,
  created_at: "2026-10-20T12:00:00Z", updated_at: "2026-10-20T12:00:00Z",
});
beforeEach(() => { vi.resetAllMocks(); clearNavigationDrafts(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe("durable direct apply", () => {
  it("polls at a bounded interval, pauses while hidden and stops after failure", async () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    vi.mocked(pipelinesApi.apply).mockResolvedValue(operation());
    vi.mocked(pipelinesApi.activation).mockResolvedValue(operation("starting"));
    const hook = renderHook(() => usePipelineApply("polling", () => {}));
    await act(async () => { await hook.result.current.session.submit(request()); });
    expect(pipelinesApi.activation).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(2999); });
    expect(pipelinesApi.activation).toHaveBeenCalledTimes(1);
    hidden.mockReturnValue(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(6001); });
    expect(pipelinesApi.activation).toHaveBeenCalledTimes(1);
    hidden.mockReturnValue(false);
    vi.mocked(pipelinesApi.activation).mockResolvedValue(operation("failed"));
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(pipelinesApi.activation).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(pipelinesApi.activation).toHaveBeenCalledTimes(2);
  });
  it("persists the exact request before sending and prevents double submission", async () => {
    let acknowledge!: (value: PipelineActivationView) => void;
    vi.mocked(pipelinesApi.apply).mockImplementation(() => new Promise((resolve) => { acknowledge = resolve; }));
    const session = createApplySession("apply");
    const pending = session.submit(request());
    expect(readStoredDraft("apply")).toEqual({ request: request() });
    await session.submit({ ...request(), display_name: "Changed" });
    expect(pipelinesApi.apply).toHaveBeenCalledOnce();
    acknowledge(operation()); await pending;
    expect(session.getSnapshot().operation?.id).toBe("activation");
    expect(createApplySession("apply").getSnapshot().operation?.id).toBe("activation");
  });
  it.each([new Error("Disconnected"), new ApiRequestError("Server unavailable", 503)])("recovers an uncertain result after reload with the original request", async (failure) => {
    vi.mocked(pipelinesApi.apply).mockRejectedValueOnce(failure).mockResolvedValueOnce(operation());
    await createApplySession("apply").submit(request());
    const restored = createApplySession("apply");
    await restored.submit({ ...request(), display_name: "Later edit" });
    expect(pipelinesApi.apply).toHaveBeenNthCalledWith(2, request());
    expect(restored.getSnapshot().operation?.id).toBe("activation");
  });
  it("releases a rejected request so the user can correct the configuration", async () => {
    vi.mocked(pipelinesApi.apply).mockRejectedValueOnce(new ApiRequestError("Reading already monitored", 409));
    const session = createApplySession("apply"); await session.submit(request());
    expect(session.getSnapshot().request).toBeUndefined();
    expect(session.getSnapshot().error).toBe("Reading already monitored");
  });
  it("retains the operation through cancel and permits editing only after it is terminal", async () => {
    vi.mocked(pipelinesApi.apply).mockResolvedValue(operation());
    vi.mocked(pipelinesApi.cancel).mockResolvedValue(operation("cancelling"));
    vi.mocked(pipelinesApi.activation).mockResolvedValue(operation("cancelled"));
    const session = createApplySession("apply"); await session.submit(request()); session.reset();
    expect(session.getSnapshot().request).toBeTruthy();
    await session.cancel(); expect(session.getSnapshot().operation?.phase).toBe("cancelling");
    await session.refresh(new AbortController().signal); session.reset();
    expect(session.getSnapshot().request).toBeUndefined();
  });
  it("cannot restore an old account's state from a response arriving after logout", async () => {
    let acknowledge!: (value: PipelineActivationView) => void;
    vi.mocked(pipelinesApi.apply).mockImplementation(() => new Promise((resolve) => { acknowledge = resolve; }));
    const pending = createApplySession("apply").submit(request()); clearNavigationDrafts();
    acknowledge(operation()); await pending;
    expect(createApplySession("apply").getSnapshot().request).toBeUndefined();
  });
});

const target = { inputs: [
  { stream: { id: "a", label: "Current", unit: "A" }, binding: { policy: { mode: "original" } } },
  { stream: { id: "b", label: "Backup current", unit: "A" }, binding: { policy: { mode: "original" } } },
  { stream: { id: "off", label: "Off", unit: "A" }, binding: { policy: { mode: "off" } } },
] } as MonitoringTarget;
describe("reading selection", () => {
  it("suggests exact labels but leaves ambiguous readings to the user", () => {
    expect(suggestBindings([{ id: "one", label: "Current", unit: "A" }, { id: "two", label: "Other", unit: "A" }], target))
      .toEqual({ one: "a", two: "b" });
    expect(suggestBindings([{ id: "one", label: "Other", unit: "A" }], target)).toEqual({});
  });
  it("rejects missing, duplicate, incompatible, disabled and already monitored readings", () => {
    const slots = [{ id: "one", label: "Current", unit: "A" }, { id: "two", label: "Backup current", unit: "A" }];
    expect(bindingsReady(slots, target, { one: "a", two: "b" }, () => false)).toBe(true);
    const invalid: Record<string, string>[] = [{}, { one: "a", two: "a" }, { one: "a", two: "off" }];
    for (const bindings of invalid)
      expect(bindingsReady(slots, target, bindings, () => false)).toBe(false);
    expect(bindingsReady(slots, target, { one: "a", two: "b" }, (id) => id === "b")).toBe(false);
    expect(bindingsReady([{ id: "one", label: "Voltage", unit: "V" }], target, { one: "a" }, () => false)).toBe(false);
  });
});
