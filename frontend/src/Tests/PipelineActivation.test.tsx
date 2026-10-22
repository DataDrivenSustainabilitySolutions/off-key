import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PipelineActivation } from "@/features/pipelines/PipelineActivation";
import { pipelinesApi } from "@/features/pipelines/api";
import { normalizeDefinition } from "@/features/pipelines/contracts";
import { ApiRequestError } from "@/lib/api-client";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import { clearNavigationDrafts } from "@/lib/navigation-draft";
import { SystemLiveTelemetry } from "@/features/catalogue/systemLiveTelemetry";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ userId: 1 }) }));
const catalogue = { document: { ...createEmptySystem(), streams: [] }, system: { snapshot: null }, telemetry: new SystemLiveTelemetry(), liveStreamIds: [] };
vi.mock("@/features/workspace/catalogue-context", () => ({
  useCatalogue: () => catalogue,
}));
vi.mock("@/features/pipelines/api", () => ({
  pipelinesApi: { activate: vi.fn(), activation: vi.fn(), cancel: vi.fn() },
}));
const definition = normalizeDefinition({
  strategy: "adaptive_stream",
  input_slots: [{ id: "temperature", label: "Temperature" }],
});
const props = () => ({
  revision: {
    id: "revision",
    pipeline_id: "pipeline",
    number: 1,
    definition,
    fingerprint: "hash",
    catalog_id: "catalog",
    created_at: "2026-10-16T12:00:00Z",
  },
  targets: [
    {
      id: "room",
      label: "Room",
      inputs: [
        {
          path: "Room",
          stream: {
            id: "reading",
            label: "Air temperature",
            connection_id: "connection",
            topic: "weather/temperature",
            value_type: "number" as const,
            category: "Environment",
          },
          binding: {
            entity_id: "room",
            telemetry_key: "temperature",
            accepted_topic: "telemetry/room/temperature",
            policy: { mode: "original" as const, interval_seconds: 10 },
          },
        },
      ],
    },
  ],
  services: [],
  byStream: new Map<string, Set<string>>(),
  initialTarget: "room",
  defaultName: "Room monitor",
  collectionReady: true,
  onClose: vi.fn(),
  onComplete: vi.fn(),
  onOperation: vi.fn(),
});
const operation = {
  id: "activation",
  phase: "succeeded" as const,
  service_id: "service",
  run_id: "run",
  predecessor_service_id: null,
  error: null,
  created_at: "2026-10-16T12:00:00Z",
  updated_at: "2026-10-16T12:00:00Z",
};
beforeEach(() => {
  clearNavigationDrafts();
});
const mount = (input = props()) =>
  render(
    <MemoryRouter>
      <PipelineActivation {...input} />
    </MemoryRouter>,
  );
async function submit() {
  fireEvent.change(
    screen.getByRole("combobox", { name: "Temperature · unit unspecified" }),
    { target: { value: "reading" } },
  );
  fireEvent.click(
    screen.getByRole("checkbox", { name: /I reviewed the input bindings/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start revision" }));
  await screen.findByRole("button", { name: "Recover activation request" });
}

describe("activation request recovery", () => {
  it("preserves tentative bindings and name across a source detour and requires renewed confirmation", () => {
    const first = mount();
    fireEvent.change(screen.getByRole("textbox", { name: "Service name" }), {
      target: { value: "Preserved monitor name" },
    });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Temperature · unit unspecified" }),
      { target: { value: "reading" } },
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed/ }));
    first.unmount();
    mount();
    expect(
      (
        screen.getByRole("textbox", {
          name: "Service name",
        }) as HTMLInputElement
      ).value,
    ).toBe("Preserved monitor name");
    expect(
      (
        screen.getByRole("combobox", {
          name: "Temperature · unit unspecified",
        }) as HTMLSelectElement
      ).value,
    ).toBe("reading");
    expect(
      (screen.getByRole("checkbox", { name: /I reviewed/ }) as HTMLInputElement)
        .checked,
    ).toBe(false);
    expect(pipelinesApi.activate).not.toHaveBeenCalled();
  });
  it("freezes an uncertain payload and retries its original idempotency key", async () => {
    vi.mocked(pipelinesApi.activate)
      .mockRejectedValueOnce(new ApiRequestError("Network error"))
      .mockResolvedValue(operation);
    const input = props();
    mount(input);
    await submit();
    expect(
      screen
        .getByRole("combobox", { name: "Temperature · unit unspecified" })
        .matches(":disabled"),
    ).toBe(true);
    const original = vi.mocked(pipelinesApi.activate).mock.calls[0]![0];
    fireEvent.click(
      screen.getByRole("button", { name: "Recover activation request" }),
    );
    await waitFor(() =>
      expect(input.onComplete).toHaveBeenCalledWith("service"),
    );
    expect(vi.mocked(pipelinesApi.activate).mock.calls[1]![0]).toEqual(
      original,
    );
    expect(
      sessionStorage.getItem("pipeline-activation:1:revision:new"),
    ).toBeNull();
  });

  it("retains uncertain requests through navigation and reload of the review", async () => {
    vi.mocked(pipelinesApi.activate)
      .mockRejectedValueOnce(new ApiRequestError("Request timed out", 504))
      .mockResolvedValue(operation);
    const first = mount();
    await submit();
    const original = vi.mocked(pipelinesApi.activate).mock.calls[0]![0];
    first.unmount();
    mount();
    fireEvent.click(
      screen.getByRole("button", { name: "Recover activation request" }),
    );
    await waitFor(() => expect(pipelinesApi.activate).toHaveBeenCalledTimes(2));
    expect(vi.mocked(pipelinesApi.activate).mock.calls[1]![0]).toEqual(
      original,
    );
  });
});
