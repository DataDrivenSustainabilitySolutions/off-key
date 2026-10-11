import { readFileSync } from "node:fs";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import { projectSystemDocument } from "@/features/spatial/systemProjection";
import { SystemLiveTelemetry } from "@/features/spatial/systemLiveTelemetry";
import { SystemLiveControls } from "@/features/spatial/SystemLiveControls";
import { SystemLiveReadings } from "@/features/spatial/SystemLiveReadings";
import type { LiveBatch } from "@/features/spatial/systemLiveTypes";
import type {
  SystemDocument,
  SystemStream,
} from "@/features/spatial/systemTypes";

vi.mock("@/components/EChart", () => ({
  EChart: ({ accessibleDescription }: { accessibleDescription: string }) => (
    <div role="img" aria-label={accessibleDescription} />
  ),
}));
const now = Date.parse("2026-10-07T12:00:00Z");
const iso = new Date(now).toISOString();
// jsdom cannot parse all modern scene CSS; load the actual overlay rules.
const liveOverlayStyles = [
  ["spatial.css", /\.sp-stage-heading \{[^}]+\}/],
  ["system.css", /\.sp-system-live-controls \{[^}]+\}/],
] as const;
const spatialStyles = liveOverlayStyles
  .map(([file, rule]) =>
    readFileSync(`src/features/spatial/${file}`, "utf8")
      .match(rule)![0],
  )
  .join("\n");
function fixture(
  valueType: SystemStream["value_type"] = "number",
  value: string | number | boolean = 21,
  retained = false,
) {
  const document: SystemDocument = {
    ...createEmptySystem(),
    connections: [
      {
        id: "broker",
        label: "Broker",
        host: "local",
        port: 1883,
        transport: "tcp",
        tls: false,
        protocol: "mqtt",
      },
    ],
    streams: [
      {
        id: "stream",
        label: "Room reading",
        connection_id: "broker",
        value_type: valueType,
        topic: "room/value",
        unit: "°C",
        category: "Other",
      },
    ],
  };
  const batch: LiveBatch = {
    mode: "live",
    revision: 1,
    sequence: 1,
    reset: true,
    connections: [
      {
        connection_id: "broker",
        state: "connected",
        message: "Connected",
        fresh_received_at: retained ? null : iso,
        received_messages: 7,
        fresh_count: retained ? 0 : 7,
        retained_count: retained ? 7 : 0,
        rate_hz: retained ? 0 : 1,
      },
    ],
    streams: [
      {
        stream_id: "stream",
        value,
        received_at: iso,
        is_retained: retained,
        received_count: 7,
        fresh_count: retained ? 0 : 7,
        retained_count: retained ? 7 : 0,
        decode_errors: 0,
        fresh_received_at: retained ? null : iso,
        rate_hz: retained ? 0 : 1,
        sequence: 1,
      },
    ],
    samples: [
      {
        sequence: 1,
        stream_id: "stream",
        received_at: iso,
        value,
        is_retained: retained,
      },
    ],
    limits: {
      max_samples: 8192,
      history_seconds: 7200,
      sample_interval_seconds: 1,
      lease_seconds: 45,
    },
  };
  const api = {
    create: vi
      .fn()
      .mockResolvedValue({
        lease_id: "lease",
        telemetry: batch,
        expires_in_seconds: 45,
      }),
    renew: vi.fn(),
    read: vi.fn().mockResolvedValue(batch),
    release: vi.fn().mockResolvedValue(undefined),
  };
  const source = new SystemLiveTelemetry(api);
  source.configure(document, 1, "user", true);
  source.accept(batch, false);
  return {
    source,
    api,
    node: projectSystemDocument(document).topology.nodes.find(
      (node) => node.id === "stream",
    )!,
  };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(now);
});
afterEach(() => {
  vi.useRealTimers();
});
describe("generic live inspector", () => {
  it("shows received numeric history, real counts, receipt time and retention limits", () => {
    const { source, node } = fixture();
    render(<SystemLiveReadings node={node} telemetry={source} />);
    expect(
      screen.getByRole("img", {
        name: /Live Room reading. 1 received samples/,
      }),
    ).not.toBeNull();
    expect(screen.getByText("7")).not.toBeNull();
    expect(screen.getByText("Just received")).not.toBeNull();
    expect(screen.getByText(/No database history is written/)).not.toBeNull();
    source.stop();
  });
  it("identifies retained boolean readings and does not call them fresh", () => {
    const { source, node } = fixture("boolean", true, true);
    render(<SystemLiveReadings node={node} telemetry={source} />);
    expect(screen.getByText("true")).not.toBeNull();
    expect(screen.getByText("Retained value")).not.toBeNull();
    expect(screen.queryByText("Just received")).toBeNull();
    expect(screen.getByText("Retained deliveries")).not.toBeNull();
    expect(screen.getByRole("img")).not.toBeNull();
    source.stop();
  });
  it("presents a text value without inventing numeric history", () => {
    const { source, node } = fixture("text", "Kitchen");
    render(<SystemLiveReadings node={node} telemetry={source} />);
    expect(screen.getByText("Kitchen")).not.toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    source.stop();
  });
  it("keeps live controls clickable over the canvas and updates connection status", async () => {
    const { source, api } = fixture();
    source.stop();
    const { container } = render(
      <>
        <style>{spatialStyles}</style>
        <div className="sp-stage-heading">
          <SystemLiveControls
            telemetry={source}
            canStart
            canView
            disabled={false}
          />
        </div>
      </>,
    );
    const heading = container.querySelector<HTMLElement>(".sp-stage-heading")!;
    const controls = container.querySelector<HTMLElement>(
      ".sp-system-live-controls",
    )!;
    expect(getComputedStyle(heading).pointerEvents).toBe("none");
    expect(getComputedStyle(controls).pointerEvents).toBe("auto");
    expect(api.create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(api.create).toHaveBeenCalledWith(1, undefined);
    expect(screen.getByRole("status").textContent).toBe("Connecting");
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("status").textContent).toBe("Connected");
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(api.release).toHaveBeenCalledWith("lease");
    expect(screen.getByRole("status").textContent).toBe("Disconnected");
  });
  it("shows a stopped connection with an explicit retry and its broker error", async () => {
    const { source, api } = fixture();
    source.stop();
    const pending = await api.create();
    pending.telemetry.connections[0] = {
      ...pending.telemetry.connections[0],
      state: "error",
      message: "Check network or VPN access, then retry.",
    };
    render(
      <SystemLiveControls
        telemetry={source}
        canStart
        canView
        disabled={false}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    });
    expect(screen.getByRole("status").textContent).toBe("Unavailable");
    expect(screen.getByRole("button", { name: "Retry" })).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull();
    expect(screen.getByText("Check network or VPN access, then retry.")).not.toBeNull();
    expect(api.release).toHaveBeenCalledWith("lease");
    source.stop();
  });
});
