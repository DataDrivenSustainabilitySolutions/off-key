import { describe, expect, it } from "vitest";

import {
  buildTelemetryChartModel,
  buildTelemetryChartOption,
  formatChartTime,
  formatTelemetryTooltip,
  getLocalTimeZone,
  type ChartThemeColors,
  type TelemetryChartModel,
  type TelemetryChartOption,
} from "@/lib/telemetry-chart";
import {
  getMonitoringEvidenceCursor,
  mergeMonitoringChartEvidence,
} from "@/lib/monitoring-chart";
import type {
  MartingaleTrackerResult,
  MonitoringChartEvidence,
} from "@/types/monitoring";

const evidence = (
  serviceId: string,
  timestamp: string,
  martingale: number | null,
  sequenceNumber = 1,
): MonitoringChartEvidence => ({
  service_id: serviceId,
  timestamp,
  sequence_number: sequenceNumber,
  sensor_set: ["L1"],
  input_timestamps: { L1: timestamp },
  restarted_martingale: martingale,
  threshold: 100,
  alarm: false,
  created: timestamp,
});

const adaptiveEvidence = (
  serviceId: string,
  timestamp: string,
  score: number,
  threshold = 2,
): MonitoringChartEvidence => ({
  service_id: serviceId,
  timestamp,
  sequence_number: 1,
  sensor_set: ["L1"],
  input_timestamps: { L1: timestamp },
  strategy: "adaptive_stream",
  model_type: "aberrant_online_isolation_forest",
  anomaly_score: score,
  restarted_martingale: null,
  threshold,
  alarm: score > threshold,
  created: timestamp,
});

const trackerResult = (
  trackerId: string,
  bettingFunction: MartingaleTrackerResult["betting_function"],
  alarmStatistic: MartingaleTrackerResult["alarm_statistic"],
  value: number,
  threshold: number,
): MartingaleTrackerResult => ({
  tracker_id: trackerId,
  betting_function: bettingFunction,
  betting_parameters: {},
  alarm_statistic: alarmStatistic,
  statistic_value: value,
  statistic_is_infinite: false,
  log_statistic_value: Math.log(value),
  statistics: {},
  e_value: 1,
  e_value_is_infinite: false,
  log_e_value: 0,
  threshold,
  alarm_fired: false,
  alarm_active: false,
  alarm_count: 0,
  tested_count: 1,
});

const colors: ChartThemeColors = {
  foreground: "#111111",
  mutedForeground: "#666666",
  border: "#dddddd",
  popover: "#ffffff",
  popoverForeground: "#111111",
  muted: "#eeeeee",
};

const buildModel = (
  overrides: Partial<Parameters<typeof buildTelemetryChartModel>[0]> = {},
): TelemetryChartModel =>
  buildTelemetryChartModel({
    telemetryName: "Voltage",
    telemetryUnit: "V",
    telemetryColor: "#2563eb",
    telemetry: [
      { timestamp: "2026-01-01T00:00:00Z", value: 12 },
      { timestamp: "2026-01-01T00:01:00Z", value: 13 },
    ],
    evidence: [],
    anomalyZones: [],
    anomalyMarkers: [],
    ...overrides,
    telemetryType: overrides.telemetryType ?? "L1",
  });

const buildOption = (
  model: TelemetryChartModel,
  timeZone = "UTC",
): TelemetryChartOption =>
  buildTelemetryChartOption({
    model,
    viewport: { mode: "live" },
    timeZone,
    colors,
    accessibleDescription: "Voltage telemetry chart",
    locale: "en-US",
  });

type InspectableOption = {
  aria: { enabled: boolean; description: string };
  grid: Array<{ left?: number | string; right?: number | string }>;
  xAxis: Array<{
    gridIndex: number;
    min?: number;
    max?: number;
    name?: string;
  }>;
  yAxis: Array<{ type: string; max?: number }>;
  axisPointer: { link: Array<{ xAxisIndex: string }> };
  dataZoom: Array<{ xAxisIndex: number[]; startValue?: number; endValue?: number }>;
  tooltip: { formatter: (params: unknown) => string; renderMode: string };
  series: Array<{
    id: string;
    smooth: boolean;
    step: boolean | string;
    data: Array<[number, number | null]>;
    markArea?: { data: unknown[] };
    markPoint?: { data: unknown[] };
    markLine?: { data: Array<{ yAxis: number }> };
  }>;
};

const inspect = (option: TelemetryChartOption): InspectableOption =>
  option as unknown as InspectableOption;

describe("telemetry chart model", () => {
  it("sorts telemetry, rejects invalid points, and retains the last duplicate", () => {
    const duplicateTime = "2026-01-01T00:01:00Z";
    const model = buildModel({
      telemetry: [
        { timestamp: duplicateTime, value: 10 },
        { timestamp: "invalid", value: 11 },
        { timestamp: "2026-01-01T00:00:00Z", value: 9 },
        { timestamp: duplicateTime, value: 12 },
        { timestamp: "2026-01-01T00:02:00Z", value: Number.NaN },
      ],
    });

    expect(model.telemetry.data).toEqual([
      [Date.parse("2026-01-01T00:00:00Z"), 9],
      [Date.parse(duplicateTime), 12],
    ]);
  });

  it("keeps secondary observations independent, ordered, and undeduplicated", () => {
    const timestamp = "2026-01-01T00:01:00Z";
    const model = buildModel({
      telemetry: [
        { timestamp: "2026-01-01T00:00:00Z", value: 12 },
        { timestamp, value: 13 },
        { timestamp: "2026-01-01T00:02:00Z", value: 14 },
      ],
      evidence: [
        evidence("service-a", timestamp, 0.25, 2),
        evidence("service-a", "2026-01-01T00:00:00Z", 1, 1),
        evidence("service-a", timestamp, 0.5, 3),
        evidence("service-b", "2026-01-01T00:02:00Z", 2),
        evidence("service-b", "invalid", 3),
        evidence("service-b", "2026-01-01T00:03:00Z", Number.POSITIVE_INFINITY),
      ],
    });

    expect(model.secondarySeries).toHaveLength(2);
    expect(model.secondarySeries[0]?.name).toContain("Restarted e-process");
    expect(model.secondarySeries[0]?.data).toEqual([
      [Date.parse("2026-01-01T00:00:00Z"), 1],
      [Date.parse(timestamp), 0.25],
      [Date.parse(timestamp), 0.5],
      [Date.parse("2026-01-01T00:02:00Z"), null],
    ]);
  });

  it("renders every configured tracker and ignores the legacy projection", () => {
    const row = evidence("service-a", "2026-01-01T00:00:00Z", 999);
    row.tracker_results = [
      trackerResult("mixture-cusum", "simple_mixture", "cusum", 3, 25),
      trackerResult(
        "jumper-sr",
        "simple_jumper",
        "shiryaev_roberts",
        4,
        40,
      ),
    ];

    const model = buildModel({ evidence: [row] });

    expect(model.secondarySeries).toHaveLength(2);
    expect(model.secondarySeries.map((series) => series.name)).toEqual([
      "CUSUM (Simple mixture · mixture-cusum) service-",
      "Shiryaev-Roberts (Simple jumper · jumper-sr) service-",
    ]);
    expect(model.secondarySeries.map((series) => series.threshold)).toEqual([
      25,
      40,
    ]);
  });
});

describe("telemetry ECharts option", () => {
  it("uses one full-height grid for telemetry alone", () => {
    const option = inspect(buildOption(buildModel()));

    expect(option.grid).toHaveLength(1);
    expect(option.xAxis).toHaveLength(1);
    expect(option.yAxis).toHaveLength(1);
    expect(option.series[0]).toMatchObject({
      id: "telemetry",
      smooth: false,
      step: false,
    });
  });

  it("links two grids and uses end-stepped restarted martingales", () => {
    const alignedTimestamp = "2026-01-01T00:01:00Z";
    const option = inspect(
      buildOption(
        buildModel({
          evidence: [evidence("service-a", alignedTimestamp, 0.5)],
        }),
      ),
    );

    expect(option.grid).toHaveLength(2);
    expect(option.grid.map(({ left, right }) => ({ left, right }))).toEqual([
      { left: 68, right: 34 },
      { left: 68, right: 34 },
    ]);
    expect(option.xAxis.map(({ gridIndex }) => gridIndex)).toEqual([0, 1]);
    expect(option.xAxis.map(({ min, max }) => ({ min, max }))).toEqual([
      {
        min: Date.parse("2026-01-01T00:00:00Z"),
        max: Date.parse(alignedTimestamp),
      },
      {
        min: Date.parse("2026-01-01T00:00:00Z"),
        max: Date.parse(alignedTimestamp),
      },
    ]);
    expect(option.yAxis.map(({ type }) => type)).toEqual(["value", "log"]);
    expect(option.yAxis[1]?.max).toBe(100);
    expect(option.axisPointer.link).toEqual([{ xAxisIndex: "all" }]);
    expect(option.dataZoom[0]?.xAxisIndex).toEqual([0, 1]);
    expect(option.dataZoom[1]?.xAxisIndex).toEqual([0, 1]);
    expect(option.series[0]?.data[1]?.[0]).toBe(
      option.series[1]?.data[1]?.[0],
    );
    expect(option.series[1]?.data[0]).toEqual([
      Date.parse("2026-01-01T00:00:00Z"),
      null,
    ]);
    expect(option.series[1]).toMatchObject({
      id: "restarted-martingale:service-a",
      smooth: false,
      step: "end",
      markLine: { data: [{ yAxis: 100 }] },
    });
  });

  it("renders adaptive score and per-point threshold on a linear pane", () => {
    const timestamp = "2026-01-01T00:01:00Z";
    const option = inspect(buildOption(buildModel({
      evidence: [adaptiveEvidence("adaptive-a", timestamp, 2.5, 2)],
    })));

    expect(option.yAxis.map(({ type }) => type)).toEqual(["value", "value"]);
    expect(option.series[1]).toMatchObject({
      id: "adaptive-score:adaptive-a",
      step: false,
      data: [
        [Date.parse("2026-01-01T00:00:00Z"), null],
        [Date.parse(timestamp), 2.5],
      ],
    });
    expect(option.series[2]).toMatchObject({
      id: "adaptive-threshold:adaptive-a",
      step: "end",
      data: [
        [Date.parse("2026-01-01T00:00:00Z"), null],
        [Date.parse(timestamp), 2],
      ],
    });
  });

  it("projects multivariate evidence onto the current sensor input", () => {
    const l1Time = "2026-01-01T00:00:00Z";
    const l2Time = "2026-01-01T00:00:01Z";
    const row = adaptiveEvidence("adaptive-a", l2Time, 2.5);
    row.sensor_set = ["L1", "L2"];
    row.input_timestamps = { L1: l1Time, L2: l2Time };

    const l1Model = buildModel({
      telemetryType: "L1",
      telemetry: [
        { timestamp: l1Time, value: 12 },
        { timestamp: l2Time, value: 13 },
      ],
      evidence: [row],
    });
    const l2Model = buildModel({
      telemetryType: "L2",
      telemetry: [
        { timestamp: l1Time, value: 22 },
        { timestamp: l2Time, value: 23 },
      ],
      evidence: [row],
    });

    const l1Score = l1Model.secondarySeries[0]?.data.find(
      ([, value]) => value !== null,
    );
    const l2Score = l2Model.secondarySeries[0]?.data.find(
      ([, value]) => value !== null,
    );
    expect(l1Score).toEqual([Date.parse(l1Time), 2.5]);
    expect(l2Score).toEqual([Date.parse(l2Time), 2.5]);
  });

  it("keeps exact evidence buffered until its telemetry input is loaded", () => {
    const row = adaptiveEvidence(
      "adaptive-a",
      "2026-01-01T00:00:02Z",
      2.5,
    );
    row.input_timestamps = { L1: "2026-01-01T00:00:02Z" };

    const model = buildModel({ evidence: [row] });

    expect(model.secondarySeries).toEqual([]);
  });

  it("does not fall back when the current sensor input reference is missing", () => {
    const timestamp = "2026-01-01T00:00:00Z";
    const row = adaptiveEvidence("adaptive-a", timestamp, 2.5);
    row.sensor_set = ["L1", "L2"];
    row.input_timestamps = { L2: timestamp };

    const model = buildModel({ evidence: [row] });

    expect(model.secondarySeries).toEqual([]);
  });

  it("breaks score lines at telemetry observations without evidence", () => {
    const model = buildModel({
      telemetry: [
        { timestamp: "2026-01-01T00:00:00Z", value: 1 },
        { timestamp: "2026-01-01T00:00:01Z", value: 2 },
        { timestamp: "2026-01-01T00:00:02Z", value: 3 },
      ],
      evidence: [
        adaptiveEvidence("adaptive-a", "2026-01-01T00:00:00Z", 1),
        adaptiveEvidence("adaptive-a", "2026-01-01T00:00:02Z", 3),
      ],
    });

    expect(model.secondarySeries[0]?.data).toEqual([
      [Date.parse("2026-01-01T00:00:00Z"), 1],
      [Date.parse("2026-01-01T00:00:01Z"), null],
      [Date.parse("2026-01-01T00:00:02Z"), 3],
    ]);
  });

  it("adds a hollow overlay for telemetry awaiting a score", () => {
    const pendingTime = Date.parse("2026-01-01T00:01:00Z");
    const option = inspect(buildOption(buildModel({
      pendingTelemetryTimestamps: [pendingTime],
    })));

    expect(option.series.find(({ id }) => id === "pending-telemetry")?.data)
      .toEqual([[pendingTime, 13]]);
  });

  it("separates mixed static and adaptive evidence into linked log and linear panes", () => {
    const timestamp = "2026-01-01T00:01:00Z";
    const option = inspect(buildOption(buildModel({
      evidence: [
        evidence("static-a", timestamp, 10),
        adaptiveEvidence("adaptive-a", timestamp, 1.5),
      ],
    })));

    expect(option.grid).toHaveLength(3);
    expect(option.yAxis.map(({ type }) => type)).toEqual(["value", "log", "value"]);
    expect(option.dataZoom[0]?.xAxisIndex).toEqual([0, 1, 2]);
  });

  it("uses numeric anomaly marks and disables raw HTML tooltips", () => {
    const timestamp = Date.parse("2026-01-01T00:00:00Z");
    const model = buildModel({
      anomalyZones: [
        { startMs: timestamp, endMs: timestamp + 1_000, anomalies: [] },
      ],
      anomalyMarkers: [
        {
          timestamp: "2026-01-01T00:00:00Z",
          time: timestamp,
          value: 12,
          anomaly: {
            anomaly_id: "anomaly-1",
            charger_id: "charger-1",
            timestamp: "2026-01-01T00:00:00Z",
            telemetry_type: "L1",
            anomaly_type: "spike",
            anomaly_value: 0.01,
            value_type: "tail_pvalue",
          },
          style: { color: "#ef4444", radius: 4, opacity: 0.9 },
        },
      ],
    });
    const option = inspect(buildOption(model));

    expect(option.series[0]?.markArea?.data).toHaveLength(1);
    expect(option.series[0]?.markPoint?.data).toHaveLength(1);
    expect(option.tooltip.renderMode).toBe("richText");
    expect(option.aria).toEqual({
      enabled: true,
      description: "Voltage telemetry chart",
    });
  });

  it("keeps an absolute viewport while new data changes the full extent", () => {
    const startMs = Date.parse("2026-01-01T00:00:10Z");
    const endMs = Date.parse("2026-01-01T00:00:50Z");
    const option = inspect(
      buildTelemetryChartOption({
        model: buildModel({
          telemetry: [
            { timestamp: "2026-01-01T00:00:00Z", value: 1 },
            { timestamp: "2026-01-01T00:02:00Z", value: 2 },
          ],
        }),
        viewport: { mode: "absolute", startMs, endMs },
        timeZone: "UTC",
        colors,
        accessibleDescription: "Telemetry",
      }),
    );

    expect(option.dataZoom[0]).toMatchObject({ startValue: startMs, endValue: endMs });
    expect(option.dataZoom[1]).toMatchObject({ startValue: startMs, endValue: endMs });
  });

  it("uses a shared timeline extent without changing the value axes", () => {
    const startMs = Date.parse("2025-12-31T23:55:00Z");
    const endMs = Date.parse("2026-01-01T00:05:00Z");
    const option = inspect(
      buildTelemetryChartOption({
        model: buildModel(),
        viewport: { mode: "live" },
        timelineExtent: [startMs, endMs],
        timeZone: "UTC",
        colors,
        accessibleDescription: "Telemetry",
      }),
    );

    expect(option.xAxis.map(({ min, max }) => ({ min, max }))).toEqual([
      { min: startMs, max: endMs },
    ]);
    expect(option.dataZoom[0]).toMatchObject({
      startValue: startMs,
      endValue: endMs,
    });
    expect(option.yAxis).toHaveLength(1);
  });
});

describe("chart time and tooltip formatting", () => {
  it("formats values with units and an explicit timezone using plain text", () => {
    const timestamp = Date.parse("2026-03-08T07:30:00Z");
    const result = formatTelemetryTooltip(
      [{ seriesName: "Voltage", value: [timestamp, 230.125] }],
      "America/New_York",
      new Map([["Voltage", "V"]]),
      "en-US",
    );

    expect(result).toContain("EDT");
    expect(result).toContain("Voltage: 230.125 V");
    expect(result).not.toContain("<");
  });

  it("handles the daylight-saving transition with epoch-based formatting", () => {
    const before = formatChartTime(
      Date.parse("2026-03-08T06:30:00Z"),
      "America/New_York",
      "tooltip",
      "en-US",
    );
    const after = formatChartTime(
      Date.parse("2026-03-08T07:30:00Z"),
      "America/New_York",
      "tooltip",
      "en-US",
    );

    expect(before).toContain("01:30");
    expect(before).toContain("EST");
    expect(after).toContain("03:30");
    expect(after).toContain("EDT");
    expect(getLocalTimeZone()).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  });
});

describe("monitoring polling utilities", () => {
  it("advances evidence cursors by ingestion order", () => {
    const olderEvent = {
      ...evidence("service-b", "2026-01-01T00:00:01Z", 2),
      created: "2026-01-01T00:01:00Z",
    };
    const newerEvent = {
      ...evidence("service-a", "2026-01-01T00:00:02Z", 3),
      created: "2026-01-01T00:00:30Z",
    };

    expect(getMonitoringEvidenceCursor([olderEvent, newerEvent])).toEqual({
      created: olderEvent.created,
      timestamp: olderEvent.timestamp,
      service_id: olderEvent.service_id,
      sequence_number: olderEvent.sequence_number,
    });
  });

  it.each(["created", "timestamp"] as const)(
    "skips evidence with an invalid %s cursor field",
    (field) => {
      const valid = evidence("service-a", "2026-01-01T00:00:01Z", 2);
      const invalid = { ...valid, [field]: "not-a-date" };

      expect(getMonitoringEvidenceCursor([invalid, valid])).toEqual({
        created: valid.created,
        timestamp: valid.timestamp,
        service_id: valid.service_id,
        sequence_number: valid.sequence_number,
      });
    },
  );

  it("merges incremental evidence by composite identity and caps the window", () => {
    const first = evidence("service-a", "2026-01-01T00:00:01Z", 1);
    const second = evidence("service-a", "2026-01-01T00:00:02Z", 2, 2);
    const duplicate = { ...second, restarted_martingale: 3 };

    const rows = mergeMonitoringChartEvidence([first, second], [duplicate], 2);

    expect(rows).toHaveLength(2);
    expect(rows[1]?.restarted_martingale).toBe(3);
    expect(mergeMonitoringChartEvidence(rows, [])).toBe(rows);
  });
});
