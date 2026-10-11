import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiUtils } from "@/lib/api-client";
import { ExplorerCollection } from "@/features/explorer/ExplorerCollection";
import type { SystemRuntime } from "@/features/spatial/systemTypes";

vi.mock("@/lib/api-client", () => ({ apiUtils: { post: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);
const runtime: SystemRuntime = {
  mode: "configured_only", message: "", legacy_collection_revision: 2, collection_revision: 4,
  collection: { status: "applied" }, bindings: Object.fromEntries(["one", "two"].map((id) => [id,
    { entity_id: "entity", telemetry_key: id, accepted_topic: `telemetry/entity/${id}`, policy: { mode: "off", interval_seconds: 10 } }]))
};
const preview = { revision: 6, collection_revision: 4, selected_readings: 2, sampled_rows_per_day_ceiling: 86400,
  original_rate_readings: 0, affected_monitors: [] as Array<{ id: string; name: string }> };
const props = () => ({ streamIds: ["one", "two"], runtime, revision: 6, canEdit: true, saving: false,
  onApply: vi.fn().mockResolvedValue(true), onRefresh: vi.fn().mockResolvedValue(undefined) });

describe("explicit workspace collection", () => {
  it("keeps browsing Off and requires review before a bulk opt-in", async () => {
    const input = props();
    vi.mocked(apiUtils.post).mockResolvedValue(preview);
    render(<MemoryRouter><ExplorerCollection {...input} /></MemoryRouter>);
    expect(apiUtils.post).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Collection mode") as HTMLSelectElement).value).toBe("off");
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Collection mode"), { target: { value: "sample" } });
    fireEvent.change(screen.getByLabelText("Collection interval"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Review change" }));
    await screen.findByRole("button", { name: "Apply" });
    expect(input.onApply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(input.onApply).toHaveBeenCalledWith({ expected_revision: 6, expected_collection_revision: 4, stream_ids: ["one", "two"],
      policy: { mode: "sample", interval_seconds: 2 }, pause_affected_monitors: false });
  });

  it("requires an explicit monitor pause when reviewed inputs change", async () => {
    const input = props();
    vi.mocked(apiUtils.post).mockResolvedValue({ ...preview, affected_monitors: [{ id: "monitor", name: "Temperature" }] });
    render(<MemoryRouter><ExplorerCollection {...input} /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Collection mode"), { target: { value: "off" } });
    fireEvent.click(screen.getByRole("button", { name: "Review change" }));
    const apply = await screen.findByRole("button", { name: "Apply" });
    expect(apply.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Pause 1 affected monitor" }));
    fireEvent.click(apply);
    expect(input.onApply).toHaveBeenCalledWith(expect.objectContaining({ pause_affected_monitors: true, policy: { mode: "off", interval_seconds: 10 } }));
  });

  it("members can see collection status and a monitoring link without write controls", () => {
    const input = props();
    const enabled = structuredClone(runtime);
    enabled.bindings!.one!.policy = { mode: "sample", interval_seconds: 10 };
    render(<MemoryRouter><ExplorerCollection {...input} runtime={enabled} streamIds={["one"]} canEdit={false} /></MemoryRouter>);
    expect(screen.getByText("Sample · 10s")).toBeTruthy();
    expect(screen.queryByLabelText("Collection mode")).toBeNull();
    expect(screen.getByRole("link", { name: "Configure monitoring" }).getAttribute("href")).toBe("/?create=monitoring&reading=one");
    expect(input.onApply).not.toHaveBeenCalled();
  });

  it("changing a reviewed policy requires another review", async () => {
    const input = props();
    vi.mocked(apiUtils.post).mockResolvedValue(preview);
    render(<MemoryRouter><ExplorerCollection {...input} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Review change" }));
    await screen.findByRole("button", { name: "Apply" });
    fireEvent.change(screen.getByLabelText("Collection mode"), { target: { value: "original" } });
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    expect(input.onApply).not.toHaveBeenCalled();
  });

  it("changing the selected readings invalidates the reviewed collection scope", async () => {
    const input = props();
    vi.mocked(apiUtils.post).mockResolvedValue(preview);
    const { rerender } = render(<MemoryRouter><ExplorerCollection {...input} /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Collection mode"), { target: { value: "sample" } });
    fireEvent.click(screen.getByRole("button", { name: "Review change" }));
    await screen.findByRole("button", { name: "Apply" });
    rerender(<MemoryRouter><ExplorerCollection {...input} streamIds={["one"]} /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    expect(input.onApply).not.toHaveBeenCalled();
  });

  it("shows persistent upstream failures for the selected broker only", () => {
    const enabled = structuredClone(runtime);
    enabled.bindings!.one = { ...enabled.bindings!.one!, connection_id: "broker-one", policy: { mode: "sample", interval_seconds: 10 } };
    enabled.ingress = { sources: { "broker-one": { state: "blocked", message: "Broker access is not configured by the operator." },
      "broker-two": { state: "error", message: "Unrelated error" } } };
    render(<MemoryRouter><ExplorerCollection {...props()} runtime={enabled} streamIds={["one"]} /></MemoryRouter>);
    expect(screen.getByText("Unavailable")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Broker access");
    expect(screen.queryByText("Unrelated error")).toBeNull();
  });

  it("shows an access failure without changing the acknowledged policy", async () => {
    const input = props();
    vi.mocked(apiUtils.post).mockRejectedValue(new Error("Broker access is not configured by the operator."));
    render(<MemoryRouter><ExplorerCollection {...input} /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Collection mode"), { target: { value: "sample" } });
    fireEvent.click(screen.getByRole("button", { name: "Review change" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Broker access"));
    expect(input.onApply).not.toHaveBeenCalled();
  });
});
