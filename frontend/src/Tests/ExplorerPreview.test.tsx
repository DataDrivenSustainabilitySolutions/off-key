import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EChart } from "@/components/EChart";
import { ExplorerHistoryChart } from "@/features/explorer/ExplorerHistoryChart";
import ExplorerPreview from "@/features/explorer/ExplorerPreview";
import { useReadingMonitoring } from "@/features/explorer/useReadingMonitoring";
import { EMPTY_READING_HISTORY, ReadingHistoryCache, readingHistoryKey } from "@/features/explorer/readingHistoryCache";
import { buildNavigationIndex, type ExplorerNode } from "@/features/explorer/navigationIndex";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import { SystemLiveTelemetry } from "@/features/catalogue/systemLiveTelemetry";
import type { LiveBatch, LiveValue } from "@/features/catalogue/systemLiveTypes";
import type { SystemDocument, SystemRuntime } from "@/features/catalogue/systemTypes";
import type { ActiveService, MonitoringChartEvidence } from "@/types/monitoring";

vi.mock("@/components/theme-provider", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("@/features/explorer/useReadingMonitoring", () => ({ useReadingMonitoring: vi.fn() }));
vi.mock("@/components/EChart", () => ({
  EChart: vi.fn(({ accessibleDescription, resolvedTheme }: { accessibleDescription: string; resolvedTheme: string }) =>
    <div role="img" aria-label={accessibleDescription} data-theme={resolvedTheme} />),
}));

const NOW = Date.parse("2026-10-10T12:00:00Z");
const lastChartProps = () => {
  const calls = vi.mocked(EChart).mock.calls;
  return calls[calls.length - 1]![0];
};
const system: SystemDocument = {
  ...createEmptySystem(), label: "Test system",
  connections: [{ id: "broker", label: "North building", protocol: "mqtt", host: "broker.test", port: 1883, tls: false, transport: "tcp" }],
  devices: [{ id: "device", label: "Room sensor", kind: "sensor", connection_id: "broker" }],
  streams: [
    { id: "temperature", label: "Air temperature", topic: "site/room/temperature", value_type: "number", unit: "°C" },
    { id: "switch", label: "Window state", topic: "site/room/window", value_type: "boolean" },
    { id: "identifier", label: "Meter identity", topic: "site/room/identity", value_type: "identifier" },
  ].map((stream) => ({ ...stream, value_type: stream.value_type as "number" | "boolean" | "identifier", connection_id: "broker", device_id: "device", category: "Environment" })),
};
const index = buildNavigationIndex(system);
const node = (id: string) => index.nodes.get(index.objectKeys.get(id)![0]!)!;
const batch = (id = "temperature", value: LiveValue = 22): LiveBatch => ({
  mode: "live", revision: 3, sequence: 1, reset: false,
  connections: [{ connection_id: "broker", state: "connected", message: "Connected", received_messages: 1, fresh_count: 1, retained_count: 0, fresh_received_at: new Date(NOW).toISOString(), rate_hz: 1 }],
  streams: [{ stream_id: id, value, received_at: new Date(NOW).toISOString(), is_retained: false, received_count: 1, fresh_count: 1, retained_count: 0, decode_errors: 0, fresh_received_at: new Date(NOW).toISOString(), rate_hz: 1, sequence: 1 }],
  samples: value === null ? [] : [{ sequence: 1, stream_id: id, received_at: new Date(NOW).toISOString(), value, is_retained: false }],
  limits: { max_samples: 8192, history_seconds: 7200, sample_interval_seconds: 1, lease_seconds: 45 },
});
function fixture(selected: ExplorerNode = node("temperature")) {
  const telemetry = new SystemLiveTelemetry();
  telemetry.configure(system, 3, "test-user", true);
  const onRename = vi.fn().mockResolvedValue(undefined);
  const onEdit = vi.fn();
  const onClose = vi.fn();
  const props = { node: selected, index, document: system, telemetry, canEdit: true, saving: false, error: "", onRename, onEdit, onClose };
  return { telemetry, props };
}
const initialClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(NOW);
  vi.mocked(EChart).mockClear();
  vi.mocked(useReadingMonitoring).mockReturnValue({ telemetry: [], evidence: [], anomalies: [], services: [], error: "" });
});

function receive(telemetry: SystemLiveTelemetry, time: number, value: number, sequence: number) {
  const next = batch("temperature", value);
  next.sequence = sequence;
  next.samples[0]!.sequence = sequence;
  next.samples[0]!.received_at = new Date(time).toISOString();
  next.streams[0]!.sequence = sequence;
  next.streams[0]!.received_at = new Date(time).toISOString();
  telemetry.accept(next, false);
}

describe("workspace chart navigation and monitoring", () => {
  it("shows and updates the latest persisted numeric value without a preview connection", () => {
    const { props } = fixture();
    const reading = system.streams[0]!;
    const historyCache = new ReadingHistoryCache("test-user");
    const key = readingHistoryKey(system.connections[0], reading)!;
    historyCache.update(key, () => ({ data: { ...EMPTY_READING_HISTORY, loading: false,
      telemetry: [{ timestamp: new Date(NOW - 1000).toISOString(), value: 24 }],
    } }));
    const view = render(<ExplorerPreview {...props} historyCache={historyCache} />);
    expect(view.container.querySelector(".ex-preview-value strong")?.textContent).toBe("24 °C");
    expect(screen.queryByText("No value received yet")).toBeNull();
    expect(screen.getByText(/Observed at/)).toBeTruthy();
    act(() => historyCache.update(key, entry => ({ ...entry, data: { ...entry.data,
      telemetry: [...entry.data.telemetry, { timestamp: new Date(NOW).toISOString(), value: 25 }],
    } })));
    expect(view.container.querySelector(".ex-preview-value strong")?.textContent).toBe("25 °C");
    view.rerender(<ExplorerPreview {...props} node={node("switch")} historyCache={historyCache} />);
    expect(view.container.querySelector(".ex-preview-value strong")?.textContent).toBe("—");
  });
  it("fits the actual data span, renders a single point, and provides an overview", () => {
    const { telemetry, props } = fixture();
    receive(telemetry, NOW - 30_000, 20, 1);
    render(<ExplorerPreview {...props} />);
    expect(lastChartProps().option.xAxis).toMatchObject([{ min: NOW - 30_500, max: NOW - 29_500 }]);
    expect(lastChartProps().option.series).toMatchObject([{ showSymbol: true, itemStyle: { color: expect.any(String) }, emphasis: { disabled: true } }]);
    act(() => receive(telemetry, NOW, 22, 2));
    expect(lastChartProps().option.xAxis).toMatchObject([{ min: NOW - 30_000, max: NOW }]);
    expect(lastChartProps().option.dataZoom).toMatchObject([
      { type: "inside", zoomOnMouseWheel: "ctrl", moveOnMouseMove: true },
      { type: "slider", startValue: NOW - 30_000, endValue: NOW },
    ]);
  });

  it("holds a manually inspected range while new readings arrive, then resumes the full live span", () => {
    const { telemetry, props } = fixture();
    receive(telemetry, NOW - 30_000, 20, 1);
    receive(telemetry, NOW, 22, 2);
    render(<ExplorerPreview {...props} />);
    act(() => lastChartProps().onViewportChange?.(NOW - 20_000, NOW - 10_000));
    act(() => receive(telemetry, NOW + 1_000, 23, 3));
    expect(lastChartProps().option.dataZoom).toMatchObject([
      { startValue: NOW - 20_000, endValue: NOW - 10_000, rangeMode: ["value", "value"] },
      { startValue: NOW - 20_000, endValue: NOW - 10_000 },
    ]);
    expect(screen.getByRole("button", { name: "Full range" }).hasAttribute("disabled")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Full range" }));
    expect(lastChartProps().option.dataZoom).toMatchObject([
      { startValue: NOW - 30_000, endValue: NOW + 1_000 },
      { startValue: NOW - 30_000, endValue: NOW + 1_000 },
    ]);
    expect(screen.getByRole("button", { name: "Full range" }).hasAttribute("disabled")).toBe(true);
    act(() => receive(telemetry, NOW + 2_000, 24, 4));
    expect(lastChartProps().option.xAxis).toMatchObject([{ max: NOW + 2_000 }]);
  });

  it("supports keyboard navigation and resets inspection when the time window changes", () => {
    const { telemetry, props } = fixture();
    receive(telemetry, NOW - 10 * 60_000, 20, 1);
    receive(telemetry, NOW - 30_000, 21, 2);
    receive(telemetry, NOW, 22, 3);
    render(<ExplorerPreview {...props} />);
    const navigation = screen.getByRole("group", { name: "Chart navigation" });
    fireEvent.keyDown(navigation, { key: "+" });
    expect(lastChartProps().option.dataZoom).toEqual(expect.arrayContaining([expect.objectContaining({ startValue: NOW - 450_000, endValue: NOW - 150_000 })]));
    fireEvent.keyDown(navigation, { key: "ArrowRight" });
    expect(lastChartProps().option.dataZoom).toEqual(expect.arrayContaining([expect.objectContaining({ startValue: NOW - 390_000, endValue: NOW - 90_000 })]));
    fireEvent.keyDown(navigation, { key: "Home" });
    expect(screen.getByRole("button", { name: "Full range" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Live chart time range" }), { target: { value: "5" } });
    expect(screen.getByRole("button", { name: "Full range" }).hasAttribute("disabled")).toBe(true);
    expect(lastChartProps().option.xAxis).toMatchObject([{ min: NOW - 30_000, max: NOW }]);
    expect(lastChartProps().option.series).toMatchObject([{ data: [[NOW - 30_000, 21], [NOW, 22]] }]);
  });

  it("keeps inspection through renaming and resets it when the reading's input changes", () => {
    const { telemetry, props } = fixture();
    receive(telemetry, NOW - 30_000, 20, 1);
    receive(telemetry, NOW, 22, 2);
    const view = render(<ExplorerPreview {...props} />);
    act(() => lastChartProps().onViewportChange?.(NOW - 20_000, NOW - 10_000));
    const renamed = { ...system, streams: system.streams.map((stream) => stream.id === "temperature"
      ? { ...stream, label: "New name" } : stream) };
    view.rerender(<ExplorerPreview {...props} document={renamed} />);
    expect(screen.getByRole("button", { name: "Full range" }).hasAttribute("disabled")).toBe(false);
    const changedInput = { ...renamed, streams: renamed.streams.map((stream) => stream.id === "temperature"
      ? { ...stream, topic: "site/other/temperature" } : stream) };
    view.rerender(<ExplorerPreview {...props} document={changedInput} />);
    expect(screen.getByRole("button", { name: "Full range" }).hasAttribute("disabled")).toBe(true);
  });

  it("isolates evidence and corroborated alarm events to the selected service, even when the reading has a newer owner", () => {
    const time = new Date(NOW).toISOString();
    const otherTime = new Date(NOW - 1000).toISOString();
    const evidence = (id: string, timestamp: string): MonitoringChartEvidence => ({ service_id: id, created: timestamp, timestamp, sequence_number: 1,
      input_timestamps: { temperature: timestamp }, sensor_set: ["temperature"], strategy: "adaptive_stream", anomaly_score: 4, threshold: 3, alarm: true, restarted_martingale: null });
    vi.mocked(useReadingMonitoring).mockReturnValue({ binding: { entityId: "entity-id", telemetryType: "temperature" }, error: "", services: [],
      telemetry: [{ timestamp: time, value: 22 }, { timestamp: otherTime, value: 21 }], evidence: [evidence("selected", time), evidence("other", otherTime)],
      anomalies: [time, otherTime].map((timestamp, index) => ({ anomaly_id: `event-${index}`, charger_id: "entity-id", telemetry_type: "temperature", timestamp,
        anomaly_type: "ml_tailprob_univariate", anomaly_value: .01, value_type: "tail_pvalue" })),
    });
    render(<ExplorerHistoryChart stream={system.streams[0]!} connection={system.connections[0]} serviceId="selected" />);
    const option = lastChartProps().option;
    const series = option.series as Array<{ id?: string; markPoint?: { data: unknown[] } }>;
    expect(series[0]).toMatchObject({ data: [[NOW - 1000, 21], [NOW, 22]] });
    expect(series.some(item => item.id === "adaptive-score:selected")).toBe(true);
    expect(series.some(item => item.id === "adaptive-score:other")).toBe(false);
    expect(series[0]?.markPoint?.data).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Full range" })).toBeTruthy();
  });

  it("adds aligned monitoring scores, changing thresholds, and pending scores without moving the viewport", () => {
    const { props } = fixture();
    const service: ActiveService = {
      id: "monitor", container_id: "test", container_name: "Test monitor", status: true,
      mqtt_topics: ["telemetry/entity-id/temperature"],
      operational_status: { stage: "operational", message_count: 3, processed_message_count: 3, is_stale: false },
    };
    const history = {
      binding: { entityId: "entity-id", telemetryType: "temperature" }, error: "", anomalies: [], services: [service], evidence: [] as MonitoringChartEvidence[],
      telemetry: [NOW - 20_000, NOW - 10_000, NOW].map((time, value) => ({ timestamp: new Date(time).toISOString(), value: 20 + value })),
    };
    vi.mocked(useReadingMonitoring).mockReturnValue(history);
    const view = render(<ExplorerPreview {...props} />);
    expect(screen.getByText("Awaiting first score")).toBeTruthy();
    expect(lastChartProps().option.grid).toHaveLength(1);
    act(() => lastChartProps().onViewportChange?.(NOW - 15_000, NOW - 5_000));
    const score = (time: number, value: number, threshold: number, sequence: number): MonitoringChartEvidence => ({
      service_id: "monitor", sequence_number: sequence, timestamp: new Date(time).toISOString(), created: new Date(time).toISOString(),
      sensor_set: ["temperature"], input_timestamps: { temperature: new Date(time).toISOString() },
      strategy: "adaptive_stream", anomaly_score: value, threshold, alarm: value > threshold, restarted_martingale: null,
    });
    vi.mocked(useReadingMonitoring).mockReturnValue({ ...history, evidence: [score(NOW - 20_000, 1, 2, 1), score(NOW - 10_000, 3, 2.5, 2)] });
    view.rerender(<ExplorerPreview {...props} />);
    expect(lastChartProps().option.grid).toHaveLength(2);
    expect(lastChartProps().option.series).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "adaptive-score:monitor", data: [
        expect.objectContaining({ value: [NOW - 20_000, 1], observation: expect.objectContaining({ threshold: 2, sequenceNumber: 1 }) }),
        expect.objectContaining({ value: [NOW - 10_000, 3], observation: expect.objectContaining({ threshold: 2.5, sequenceNumber: 2 }) }),
        { value: [NOW, null] },
      ],
        showSymbol: false, symbol: "none",
        markArea: expect.objectContaining({ itemStyle: expect.objectContaining({ borderWidth: 0 }), data: expect.arrayContaining([
          [{ xAxis: NOW - 20_000, yAxis: 2 }, { xAxis: NOW - 15_000, yAxis: expect.any(Number) }],
          [{ xAxis: NOW - 15_000, yAxis: 2.5 }, { xAxis: NOW - 5_000, yAxis: expect.any(Number) }],
        ]) }) }),
      expect.objectContaining({ id: "pending-telemetry", data: [[NOW, 22]] }),
    ]));
    expect(lastChartProps().option.series).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "adaptive-score:monitor", markLine: expect.anything() }),
    ]));
    expect(lastChartProps().option.dataZoom).toEqual(expect.arrayContaining([expect.objectContaining({ startValue: NOW - 15_000, endValue: NOW - 5_000 })]));
    expect(screen.getByText(/Threshold: 2.5/)).toBeTruthy();
    expect(screen.getByText(/1 awaiting score/)).toBeTruthy();
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  if (initialClipboard) Object.defineProperty(navigator, "clipboard", initialClipboard);
  else Reflect.deleteProperty(navigator, "clipboard");
});

describe("explorer selected-object preview", () => {
  it("shows broker connection metadata and generic entity definitions from the catalogue", () => {
    const broker = fixture(node("broker"));
    const view = render(<ExplorerPreview {...broker.props} />);
    expect(screen.getByText("broker.test:1883")).toBeTruthy();
    expect(screen.getByText("MQTT · TCP")).toBeTruthy();
    expect(screen.getByText("TLS").nextElementSibling?.textContent).toBe("Disabled");
    expect(screen.getByText("Broker ID").nextElementSibling?.textContent).toBe("broker");
    const entity = fixture(node("device"));
    view.rerender(<ExplorerPreview {...entity.props} />);
    expect(screen.getByText("Kind").nextElementSibling?.textContent).toBe("sensor");
    expect(screen.getByText("Brokers").nextElementSibling?.textContent).toBe("North building");
    expect(screen.getByText("Entity ID").nextElementSibling?.textContent).toBe("device");
    expect(screen.queryByText(/temporary preview/)).toBeNull();
  });

  it("shows the configured hierarchy and exact binding without fabricated values or history", () => {
    const { props } = fixture();
    render(<ExplorerPreview {...props} />);
    expect(screen.getByRole("status").textContent).toContain("Disconnected");
    expect(screen.getByText("No value received yet")).toBeTruthy();
    expect(screen.getByText("Waiting for live values")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("navigation", { name: "Catalogue ancestry" }).textContent).toContain("Test system / North building / Room sensor / site / room / temperature");
    expect(screen.getByText("site/room/temperature")).toBeTruthy();
    expect(screen.queryByText("broker.test")).toBeNull();
  });

  it("plots only received samples with the active dark theme and responds to telemetry updates", () => {
    const { telemetry, props } = fixture();
    telemetry.accept(batch(), false);
    render(<ExplorerPreview {...props} />);
    expect(screen.getByRole("img").getAttribute("data-theme")).toBe("dark");
    expect(screen.getByText("22")).toBeTruthy();
    const first = lastChartProps();
    expect(first.option.backgroundColor).toBe("transparent");
    expect(first.option.series).toMatchObject([{ data: [[NOW, 22]] }]);
    act(() => {
      const next = batch("temperature", 26);
      next.sequence = 2;
      next.streams[0]!.sequence = 2;
      next.streams[0]!.fresh_count = 2;
      next.samples[0]!.sequence = 2;
      telemetry.accept(next, false);
    });
    expect(screen.getByText("26")).toBeTruthy();
    expect(lastChartProps().option.series).toMatchObject([{ data: [[NOW, 26]] }]);
  });

  it("opens old recorded history with honest background status without a temporary live connection", () => {
    const { props } = fixture();
    const binding = { entity_id: "room", connection_id: "broker", telemetry_key: "temperature", accepted_topic: "telemetry/room/temperature",
      policy: { mode: "sample" as const, interval_seconds: 10 } };
    const runtime: SystemRuntime = { mode: "collection", message: "", bindings: { temperature: binding },
      collection: { status: "applied" }, ingress: { sources: { broker: { state: "connected" } } } };
    const historical = [{ timestamp: new Date(NOW - 3_600_000).toISOString(), value: 20 },
      { timestamp: new Date(NOW - 3_590_000).toISOString(), value: 22 }];
    vi.mocked(useReadingMonitoring).mockReturnValue({ telemetry: historical, evidence: [], anomalies: [], services: [], error: "" });
    const view = render(<ExplorerPreview {...props} runtime={runtime} />);
    expect(screen.getByRole("status").textContent).toContain("Recording");
    expect(screen.queryByText("No live connection")).toBeNull();
    expect(lastChartProps().option.series).toMatchObject([{ data: [[NOW - 3_600_000, 20], [NOW - 3_590_000, 22]] }]);
    view.rerender(<ExplorerPreview {...props} runtime={{ ...runtime, ingress: { sources: { broker: { state: "error", message: "Broker unavailable." } } } }} />);
    expect(screen.getByRole("status").textContent).toContain("Unavailable");
    expect(screen.getByRole("alert").textContent).toBe("Broker unavailable.");
    expect(lastChartProps().option.series).toMatchObject([{ data: [[NOW - 3_600_000, 20], [NOW - 3_590_000, 22]] }]);
  });

  it("uses a step chart for booleans and leaves identifiers as readable text", () => {
    const boolean = fixture(node("switch"));
    boolean.telemetry.accept(batch("switch", false), false);
    const view = render(<ExplorerPreview {...boolean.props} />);
    expect(screen.getByText("false")).toBeTruthy();
    expect(lastChartProps().option.series).toMatchObject([{ step: "end", data: [[NOW, 0]] }]);
    const text = fixture(node("identifier"));
    text.telemetry.accept(batch("identifier", "Meter north"), false);
    view.rerender(<ExplorerPreview {...text.props} />);
    expect(screen.getByText("Meter north")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("shows a selected broker's blocked reason and real catalogue counts", () => {
    const { telemetry, props } = fixture(node("broker"));
    const unavailable = batch();
    unavailable.connections[0]!.state = "blocked";
    unavailable.connections[0]!.message = "Broker access is not configured.";
    unavailable.streams = [];
    unavailable.samples = [];
    telemetry.accept(unavailable, false);
    render(<ExplorerPreview {...props} />);
    expect(screen.getByRole("status").textContent).toContain("Unavailable");
    expect(screen.getByRole("alert").textContent).toBe("Broker access is not configured.");
    expect(screen.getByText("Readings").previousElementSibling?.textContent).toBe("3");
    expect(screen.getByText("MQTT topics").previousElementSibling?.textContent).toBe("3");
  });

  it("replaces a stale reconnecting broker badge when its attempt times out", async () => {
    vi.useFakeTimers();
    const pending = batch();
    pending.connections[0]!.state = "reconnecting";
    pending.connections[0]!.message = "Retrying the broker connection.";
    const lease = { lease_id: "test-lease", expires_in_seconds: 45, telemetry: pending };
    const api = {
      create: vi.fn().mockResolvedValue(lease),
      renew: vi.fn().mockResolvedValue(lease),
      read: vi.fn().mockResolvedValue(pending),
      release: vi.fn().mockResolvedValue(undefined),
    };
    const telemetry = new SystemLiveTelemetry(api);
    telemetry.configure(system, 3, "test-user", true);
    const { props } = fixture(node("broker"));
    render(<ExplorerPreview {...props} telemetry={telemetry} />);
    await act(async () => {
      await telemetry.start();
    });
    expect(screen.getByRole("status").textContent).toContain("Reconnecting");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(screen.getByRole("status").textContent).toContain("Unavailable");
    expect(screen.getByRole("status").textContent).toContain("Live connection inactive");
    expect(screen.queryByText("Reconnecting")).toBeNull();
    expect(screen.getByRole("alert").textContent).toContain("network or VPN access");
    expect(api.release).toHaveBeenCalledWith("test-lease");
    act(() => telemetry.stop());
  });

  it("renames the actual stream on Enter or blur and routes structure edits to its stable identity", async () => {
    const { props } = fixture();
    render(<ExplorerPreview {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Rename reading" }));
    const input = screen.getByRole("textbox", { name: "Rename reading" });
    fireEvent.change(input, { target: { value: "  Room temperature  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(props.onRename).toHaveBeenCalledExactlyOnceWith("stream", "temperature", "Room temperature");
    fireEvent.click(screen.getByRole("button", { name: "Edit structure" }));
    expect(props.onEdit).toHaveBeenCalledExactlyOnceWith("stream", "temperature");
    fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
    expect(props.onClose).toHaveBeenCalledOnce();
  });

  it("keeps virtual path nodes read-only and exposes only their relative path", () => {
    const branch = Array.from(index.nodes.values()).find((item) => item.kind === "topic" && item.topic === "site")!;
    const { props } = fixture(branch);
    render(<ExplorerPreview {...props} />);
    expect(screen.queryByRole("button", { name: /Rename/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit structure" })).toBeNull();
    expect(screen.getByRole("button", { name: "Copy topic path" })).toBeTruthy();
  });

  it("reports clipboard failure and clears it after a successful retry", async () => {
    const writeText = vi.fn().mockRejectedValueOnce(new Error("Denied")).mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const { props } = fixture();
    render(<ExplorerPreview {...props} />);
    const copy = screen.getByRole("button", { name: "Copy mqtt topic" });
    fireEvent.click(copy);
    expect((await screen.findByRole("alert")).textContent).toContain("Could not copy");
    fireEvent.click(copy);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByText("Copied.")).toBeTruthy();
    expect(writeText).toHaveBeenLastCalledWith("site/room/temperature");
  });
});
