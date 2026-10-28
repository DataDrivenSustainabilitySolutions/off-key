import { clearNavigationDrafts } from "@/lib/navigation-draft";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, createMemoryRouter, RouterProvider, Link } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MonitoringServiceCreate } from "@/features/monitoring/MonitoringServiceCreate";
import { apiUtils } from "@/lib/api-client";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import type { ActiveService } from "@/types/monitoring";
import { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";

vi.mock("@/lib/api-client", () => ({ apiUtils: { get: vi.fn(), post: vi.fn() } }));
vi.mock("react-hot-toast", () => ({ default: { success: vi.fn(), error: vi.fn() } }));
const catalogue = { system: { snapshot: null }, telemetry: new SystemLiveTelemetry(), liveStreamIds: [], previewStreamIds: [] };
vi.mock("@/features/workspace/catalogue-context", () => ({ useCatalogue: () => catalogue }));
const target: MonitoringTarget = { id: "room", label: "Building / Room", inputs: [
  { path: "Building / Room", stream: { id: "temperature", label: "Room temperature", topic: "upstream/custom/path", value_type: "number", category: "Environment", connection_id: "broker" },
    binding: { entity_id: "room", telemetry_key: "temperature", accepted_topic: "telemetry/room/temperature", policy: { mode: "sample", interval_seconds: 10 } } },
] };
const models = {
  pyod_iforest: { strategy: "static_baseline", parameters: { properties: {} } },
  aberrant_online_isolation_forest: { strategy: "adaptive_stream", parameters: { properties: {} } },
};
beforeEach(() => { vi.resetAllMocks(); clearNavigationDrafts();
  vi.mocked(apiUtils.get).mockImplementation(async (url: string) =>
    url.includes("pipeline-activations") ? { phase: "awaiting_heartbeat", service_id: "new-service" } : models);
  vi.mocked(apiUtils.post).mockResolvedValue({ service_id: "new-service", activation_id: "activation" });
});
function mount(ready = true, services: ActiveService[] = [], byStream = new Map<string, Set<string>>()) {
  const onStarted = vi.fn(async () => {});
  render(<MemoryRouter><MonitoringServiceCreate targets={[target]} services={services} byStream={byStream} initialTarget="room" initialReading="temperature"
    collectionReady={ready} onStarted={onStarted} onBack={vi.fn()} /></MemoryRouter>);
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
    expect(apiUtils.post).toHaveBeenCalledWith("/v1/monitors/start", expect.objectContaining({ display_name: "Room climate monitor", mqtt_topics: ["telemetry/room/temperature"] }));
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith("new-service"));
    expect(apiUtils.get).toHaveBeenCalledWith("/v1/monitors/pipeline-activations/activation", expect.anything());
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


it("restores the entire service draft after a Sources detour", async () => {
  const router = createMemoryRouter([
    { path: "/", element: <MonitoringServiceCreate targets={[target]} services={[]} byStream={new Map()} initialTarget="room" initialReading="temperature" collectionReady draftKey="test-detour" onStarted={vi.fn()} onBack={vi.fn()} /> },
    { path: "/sources", element: <Link to="/?create=monitoring&reading=temperature">Return to service setup</Link> },
  ], { initialEntries: ["/?create=monitoring&reading=temperature"] });
  render(<RouterProvider router={router} />);
  fireEvent.change(screen.getByRole("textbox", { name: "Service name" }), { target: { value: "Saved climate draft" } });
  fireEvent.change(await screen.findByLabelText("Warm-up samples"), { target: { value: "33" } });
  fireEvent.click(screen.getByRole("link", { name: "Configure in Sources" }));
  fireEvent.click(await screen.findByRole("link", { name: "Return to service setup" }));
  await waitFor(() => expect((screen.getByRole("textbox", { name: "Service name" }) as HTMLInputElement).value).toBe("Saved climate draft"));
  expect((await screen.findByLabelText("Warm-up samples") as HTMLInputElement).value).toBe("33");
});
