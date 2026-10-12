import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MonitoringServiceCreate } from "@/features/monitoring/MonitoringServiceCreate";
import { apiUtils } from "@/lib/api-client";
import type { MonitoringTarget } from "@/features/monitoring/serviceModel";
import type { ActiveService } from "@/types/monitoring";

vi.mock("@/lib/api-client", () => ({ apiUtils: { get: vi.fn(), post: vi.fn() } }));
vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: vi.fn() } }));
const target: MonitoringTarget = { id: "room", label: "Building / Room", inputs: [
  { path: "Building / Room", stream: { id: "temperature", label: "Room temperature", topic: "upstream/custom/path", value_type: "number", category: "Environment", connection_id: "broker" },
    binding: { entity_id: "room", telemetry_key: "temperature", accepted_topic: "telemetry/room/temperature", policy: { mode: "sample", interval_seconds: 10 } } },
] };
const models = {
  pyod_iforest: { strategy: "static_baseline", parameters: { properties: {} } },
  aberrant_online_isolation_forest: { strategy: "adaptive_stream", parameters: { properties: {} } },
};
beforeEach(() => { vi.resetAllMocks(); vi.mocked(apiUtils.get).mockResolvedValue(models); vi.mocked(apiUtils.post).mockResolvedValue({ service_id: "new-service" }); });
afterEach(cleanup);
function mount(ready = true, services: ActiveService[] = [], byStream = new Map<string, Set<string>>()) {
  const onStarted = vi.fn(async () => {});
  render(<MemoryRouter><MonitoringServiceCreate targets={[target]} services={services} byStream={byStream} initialTarget="room" initialReading="temperature"
    collectionReady={ready} collection={() => <p>Collection controls</p>} onStarted={onStarted} onBack={vi.fn()} /></MemoryRouter>);
  return onStarted;
}

describe("integrated monitor creation", () => {
  it.each(["adaptive", "static"])("starts %s monitoring with a saved name and the exact generic accepted input", async strategy => {
    const onStarted = mount();
    fireEvent.change(screen.getByRole("textbox", { name: "Service name" }), { target: { value: "Room climate monitor" } });
    if (strategy === "static") fireEvent.click(screen.getByRole("button", { name: "Static baseline" }));
    const start = await screen.findByRole("button", { name: strategy === "static" ? "Start monitoring" : "Start adaptive monitoring" });
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(start);
    await waitFor(() => expect(apiUtils.post).toHaveBeenCalledOnce());
    expect(apiUtils.post).toHaveBeenCalledWith("/v1/monitors/start", expect.objectContaining({ display_name: "Room climate monitor", mqtt_topics: ["telemetry/room/temperature"] }), expect.anything());
    expect(onStarted).toHaveBeenCalledWith("new-service");
  });

  it("keeps start disabled until the explicitly selected collection revision is applied", async () => {
    mount(false);
    const start = await screen.findByRole("button", { name: "Start adaptive monitoring" });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Waiting for collection to apply…")).toBeTruthy();
    fireEvent.click(start); expect(apiUtils.post).not.toHaveBeenCalled();
  });

  it("prevents a second active service from claiming an already owned generic input", async () => {
    const service: ActiveService = { id: "owner", container_id: "workload", container_name: "Existing monitor", mqtt_topics: ["telemetry/room/temperature"], status: true,
      operational_status: { stage: "operational", is_stale: false, message_count: 10, processed_message_count: 10 } };
    mount(true, [service], new Map([["temperature", new Set(["owner"])]]));
    const input = await screen.findByRole("checkbox", { name: /Room temperature/ });
    expect((input as HTMLInputElement).disabled).toBe(true);
    expect((input as HTMLInputElement).checked).toBe(false);
    fireEvent.click(await screen.findByRole("button", { name: "Start adaptive monitoring" }));
    expect(apiUtils.post).not.toHaveBeenCalled();
  });
});
