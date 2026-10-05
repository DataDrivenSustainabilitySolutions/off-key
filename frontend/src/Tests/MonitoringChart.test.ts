import { describe, expect, it } from "vitest";

import {
  buildTelemetryChartModel,
  buildTelemetryChartOption,
  formatChartTime,
  formatTelemetryTooltip,
  getLocalTimeZone,
  getDefaultDetectorId,
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
  score: number | null,
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
  alarm: score !== null && score > threshold,
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
  primary: "hsl(173 80% 32%)",
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
  grid: Array<{ left?: number | string; right?: number | string; outerBoundsMode?: string }>;
  xAxis: Array<{
    gridIndex: number;
    min?: number;
    max?: number;
    name?: string;
  }>;
  yAxis: Array<{ type: string; min?: number; max?: number; name?: string }>;
  axisPointer: { link: Array<{ xAxisIndex: string }> };
  dataZoom: Array<{ xAxisIndex: number[]; startValue?: number; endValue?: number; bottom?: number; height?: number }>;
  tooltip: { formatter: (params: unknown) => string; renderMode: string };
  series: Array<{
    id: string;
    smooth: boolean;
    step: boolean | string;
    showSymbol?: boolean;
    symbolSize?: number;
    connectNulls?: boolean;
    data: Array<[number, number | null]>;
    lineStyle?: { width?: number; type?: string };
    markArea?: { data: Array<[{ xAxis: number; yAxis: number }, { xAxis: number; yAxis: number }]>; itemStyle?: { color?: string }; z?: number; silent?: boolean };
    markPoint?: { data: Array<{ coord?: [number, number]; symbol?: string; tooltip?: { formatter?: () => string } }> };
    markLine?: { data: unknown[] };
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

    expect(model.detectors).toHaveLength(2);
    expect(model.secondarySeries).toHaveLength(1);
    expect(model.secondarySeries[0]?.name).toContain("Restarted e-process");
    expect(model.secondarySeries[0]?.data).toEqual([
      [Date.parse("2026-01-01T00:00:00Z"), 1],
      [Date.parse(timestamp), 0.25],
      [Date.parse(timestamp), 0.5],
      [Date.parse("2026-01-01T00:02:00Z"), null],
    ]);
  });

  it("catalogs every tracker and plots only the selected tracker, ignoring the legacy projection", () => {
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

    const model = buildModel({ evidence: [row], selectedDetectorIds: { static: "martingale:service-a:mixture-cusum" } });

    expect(model.secondarySeries).toHaveLength(1);
    expect(model.detectors.map((series) => series.name).sort()).toEqual([
      "CUSUM (Simple mixture · mixture-cusum)",
      "Shiryaev-Roberts (Simple jumper · jumper-sr)",
    ]);
    expect(model.secondarySeries[0]?.threshold).toBe(25);
  });

  it("defaults to primary deterministically and does not replace an explicitly unavailable selection", () => {
    const row = evidence("service-a", "2026-01-01T00:00:00Z", 999);
    row.tracker_results = [
      trackerResult("aaa-cusum", "simple_mixture", "cusum", 3, 25),
      trackerResult("primary", "power", "restarted_martingale", 4, 40),
    ];
    const model = buildModel({ evidence: [row] });
    expect(getDefaultDetectorId(model.detectors, "static")).toBe("restarted-martingale:service-a");
    expect(model.secondarySeries[0]?.id).toBe("restarted-martingale:service-a");
    const selectedOutsideRange = buildModel({
      evidence: [row], selectedDetectorIds: { static: "martingale:service-a:missing" },
    });
    expect(selectedOutsideRange.detectors).toHaveLength(2);
    expect(selectedOutsideRange.secondarySeries).toEqual([]);
  });

  it("does not catalog buffered or wholly unscored detector observations", () => {
    const unmatched = adaptiveEvidence("buffered", "2026-01-01T00:03:00Z", 1);
    const unavailable = adaptiveEvidence("unavailable", "2026-01-01T00:00:00Z", null);
    const model = buildModel({ evidence: [unmatched, unavailable] });
    expect(model.detectors).toEqual([]);
    expect(model.secondarySeries).toEqual([]);
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

  it("links two grids and uses continuous restarted martingales", () => {
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
      { left: 68, right: 40 },
      { left: 68, right: 40 },
    ]);
    expect(option.grid.every((grid) => grid.outerBoundsMode === "none")).toBe(true);
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
    expect(option.yAxis[1]?.max).toBeGreaterThan(100);
    expect(option.yAxis[1]?.name).toBe("Sequential evidence (log)");
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
      step: false,
      showSymbol: true,
      symbolSize: 3,
      connectNulls: false,
      lineStyle: { width: 2.25, type: "solid" },
    });
    expect(option.series[1]?.markArea?.data).toEqual([[
      { xAxis: Date.parse("2026-01-01T00:00:30Z"), yAxis: 100 },
      { xAxis: Date.parse(alignedTimestamp), yAxis: option.yAxis[1]?.max },
    ]]);
  });

  it("renders the adaptive score with a shaded alarm region on a linear pane", () => {
    const timestamp = "2026-01-01T00:01:00Z";
    const option = inspect(buildOption(buildModel({
      evidence: [adaptiveEvidence("adaptive-a", timestamp, 2.5, 2)],
    })));

    expect(option.yAxis.map(({ type }) => type)).toEqual(["value", "value"]);
    expect(option.series[1]).toMatchObject({
      id: "adaptive-score:adaptive-a",
      step: false,
      showSymbol: true,
      symbolSize: 3,
      connectNulls: false,
      lineStyle: { width: 2.25, type: "solid" },
      data: [
        [Date.parse("2026-01-01T00:00:00Z"), null],
        [Date.parse(timestamp), 2.5],
      ],
    });
    expect(option.series).toHaveLength(2);
    expect(option.series[1]?.markArea?.data).toEqual([[
      { xAxis: Date.parse("2026-01-01T00:00:30Z"), yAxis: 2 },
      { xAxis: Date.parse(timestamp), yAxis: option.yAxis[1]?.max },
    ]]);
    expect(option.series[1]?.markArea).toMatchObject({
      silent: true, z: 0, itemStyle: { color: "rgba(220, 38, 38, 0.12)" },
    });
  });

  it("preserves changing threshold history and leaves missing or unevaluated cells unshaded", () => {
    const times = [0, 1, 2, 3, 4].map((second) => `2026-01-01T00:00:0${second}Z`);
    const model = buildModel({
      telemetry: times.map((timestamp, value) => ({ timestamp, value })),
      evidence: [
        adaptiveEvidence("adaptive-a", times[0]!, 1, 2),
        adaptiveEvidence("adaptive-a", times[1]!, 2, 4),
        adaptiveEvidence("adaptive-a", times[2]!, null, 5),
        adaptiveEvidence("adaptive-a", times[3]!, 2, 3),
      ],
    });
    const start = Date.parse(times[0]!);
    expect(model.secondarySeries[0]?.thresholdRegions).toEqual([
      { startMs: start, endMs: start + 500, threshold: 2 },
      { startMs: start + 500, endMs: start + 1500, threshold: 4 },
      { startMs: start + 2500, endMs: start + 3500, threshold: 3 },
    ]);
    expect(model.secondarySeries[0]?.data).toEqual([
      [start, 1], [start + 1000, 2], [start + 2000, null],
      [start + 3000, 2], [start + 4000, null],
    ]);
    expect(inspect(buildOption(model)).series[1]?.markArea?.data).toHaveLength(3);
  });

  it("keeps static threshold history separate from the latest threshold summary", () => {
    const first = evidence("static-a", "2026-01-01T00:00:00Z", 2);
    const second = { ...evidence("static-a", "2026-01-01T00:01:00Z", 3), threshold: 200 };
    const model = buildModel({ evidence: [first, second] });
    expect(model.secondarySeries[0]?.threshold).toBe(200);
    expect(model.secondarySeries[0]?.thresholdRegions.map(({ threshold }) => threshold)).toEqual([100, 200]);
    const option = inspect(buildOption(model));
    expect(option.yAxis[1]?.max).toBeGreaterThan(200);
    expect(option.series[1]?.markArea?.data.map(([start]) => start.yAxis)).toEqual([100, 200]);
  });

  it("gives a singleton a visible band even for an exact From/To range", () => {
    const timestamp = "2026-01-01T00:00:00Z";
    const time = Date.parse(timestamp);
    const model = buildModel({
      telemetry: [{ timestamp, value: 230 }],
      evidence: [adaptiveEvidence("adaptive-a", timestamp, 1, 2)],
      range: { fromMs: time, toMs: time },
    });
    const option = inspect(buildOption(model));
    expect(option.xAxis[0]).toMatchObject({ min: time - 500, max: time + 500 });
    expect(option.series[1]?.markArea?.data[0]).toEqual([
      { xAxis: time - 500, yAxis: 2 },
      { xAxis: time + 500, yAxis: option.yAxis[1]?.max },
    ]);
    expect(option.yAxis[1]?.max).toBeGreaterThan(2);
  });

  it("clips evaluated cells to From/To bounds without changing threshold values", () => {
    const first = "2026-01-01T00:00:00Z";
    const second = "2026-01-01T00:01:00Z";
    const start = Date.parse(first) + 10_000;
    const end = Date.parse(second) - 10_000;
    const model = buildModel({
      evidence: [adaptiveEvidence("adaptive-a", first, 1), adaptiveEvidence("adaptive-a", second, 1)],
      range: { fromMs: start, toMs: end },
    });
    const option = inspect(buildOption(model));
    expect(option.xAxis[1]).toMatchObject({ min: start, max: end });
    expect(option.series[1]?.markArea?.data).toEqual([[
      { xAxis: start, yAxis: 2 }, { xAxis: end, yAxis: option.yAxis[1]?.max },
    ]]);
  });

  it("retains explicit From/To bounds when the selected range is wider than loaded telemetry", () => {
    const first = "2026-01-01T00:00:00Z";
    const second = "2026-01-01T00:01:00Z";
    const start = Date.parse(first) - 20_000;
    const end = Date.parse(second) + 20_000;
    const model = buildModel({
      evidence: [adaptiveEvidence("adaptive-a", first, 1), adaptiveEvidence("adaptive-a", second, 1)],
      range: { fromMs: start, toMs: end },
    });
    const option = inspect(buildOption(model));
    expect(option.xAxis.map(({ min, max }) => ({ min, max }))).toEqual([
      { min: start, max: end }, { min: start, max: end },
    ]);
    expect(option.dataZoom[0]).toMatchObject({ startValue: start, endValue: end });
    expect(option.series[1]?.markArea?.data).toEqual([[
      { xAxis: Date.parse(first), yAxis: 2 },
      { xAxis: Date.parse(second), yAxis: option.yAxis[1]?.max },
    ]]);
  });

  it("retains overflow-only alarms as labelled edge markers with no invented finite scores", () => {
    const timestamp = "2026-01-01T00:00:00Z";
    const time = Date.parse(timestamp);
    const row = evidence("static-a", timestamp, null);
    row.tracker_results = [{
      ...trackerResult("primary", "power", "restarted_martingale", 1, 100),
      statistic_value: null, statistic_is_infinite: true,
      log_statistic_value: 750, alarm_active: true,
    }];
    const model = buildModel({ telemetry: [{ timestamp, value: 230 }], evidence: [row] });
    expect(model.detectors).toHaveLength(1);
    expect(model.secondarySeries[0]?.data).toEqual([[time, null]]);
    expect(model.secondarySeries[0]?.latestObservation).toMatchObject({ timeMs: time, value: null, isInfinite: true, alarmActive: true });
    const option = inspect(buildOption(model));
    expect(option.grid).toHaveLength(2);
    expect(option.yAxis[1]?.max).toBeGreaterThan(100);
    expect(option.series[1]?.markArea?.data).toHaveLength(1);
    const marker = option.series[1]?.markPoint?.data[0];
    expect(marker?.coord).toEqual([time, option.yAxis[1]?.max]);
    expect(marker?.tooltip?.formatter?.()).toContain("Beyond numeric range");
    expect(marker?.tooltip?.formatter?.()).toContain("Log evidence: 750");
    expect(marker?.tooltip?.formatter?.()).toContain("Alarm threshold: 100");
    expect(marker?.tooltip?.formatter?.()).toContain("Alarm: active");
  });

  it("does not shade an overflow observation with an unavailable threshold and reports that in inspection", () => {
    const timestamp = "2026-01-01T00:00:00Z";
    const row = evidence("static-a", timestamp, null);
    row.tracker_results = [{
      ...trackerResult("primary", "power", "restarted_martingale", 1, Number.NaN),
      statistic_value: null, statistic_is_infinite: true,
      log_statistic_value: null, alarm_active: true,
    }];
    const model = buildModel({ telemetry: [{ timestamp, value: 230 }], evidence: [row] });
    expect(model.secondarySeries[0]?.overflow[0]?.threshold).toBeNull();
    const option = inspect(buildOption(model));
    expect(option.series[1]?.markArea?.data).toEqual([]);
    expect(option.series[1]?.markLine?.data).toEqual([]);
    const tooltip = option.series[1]?.markPoint?.data[0]?.tooltip?.formatter?.();
    expect(tooltip).toContain("Beyond numeric range");
    expect(tooltip).toContain("Alarm threshold: unavailable");
    expect(tooltip).toContain("Alarm: active");
  });

  it("keeps finite log bounds for extreme evidence and shows the threshold used at the hovered observation", () => {
    const timestamp = "2026-01-01T00:00:00Z";
    const row = evidence("static-a", timestamp, 1e250);
    row.threshold = 1e200;
    const model = buildModel({ evidence: [row] });
    const option = inspect(buildOption(model));
    expect(Number.isFinite(option.yAxis[1]?.max)).toBe(true);
    expect(option.yAxis[1]?.max).toBeGreaterThan(1e250);
    expect((option.series[1]?.lineStyle as { color?: string })?.color).toBe(colors.primary);
    const text = option.tooltip.formatter([{
      seriesId: "restarted-martingale:static-a", seriesName: "Restarted e-process",
      value: [Date.parse(timestamp), 1e250],
    }]);
    expect(text).toContain("Alarm threshold: 1.00e+200");
    expect(text).toContain("Alarm: inactive");
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

  it("connects adjacent scored observations with subtle markers", () => {
    const firstTime = "2026-01-01T00:00:00Z";
    const secondTime = "2026-01-01T00:00:01Z";
    const thirdTime = "2026-01-01T00:00:02Z";
    const model = buildModel({
      telemetry: [
        { timestamp: firstTime, value: 1 },
        { timestamp: secondTime, value: 2 },
        { timestamp: thirdTime, value: 3 },
      ],
      evidence: [
        adaptiveEvidence("adaptive-a", firstTime, 1),
        adaptiveEvidence("adaptive-a", secondTime, 2),
      ],
    });
    const option = inspect(buildOption(model));
    const scoreSeries = option.series.find(
      ({ id }) => id === "adaptive-score:adaptive-a",
    );

    expect(scoreSeries).toMatchObject({
      step: false,
      showSymbol: true,
      symbolSize: 3,
      connectNulls: false,
      lineStyle: { width: 2.25, type: "solid" },
      data: [
        [Date.parse(firstTime), 1],
        [Date.parse(secondTime), 2],
        [Date.parse(thirdTime), null],
      ],
    });
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

    // Layout regression check: final grid bottom + nameGap leaves clear margin above slider
    const grid3 = option.grid[2] as { top: number; height: number };
    const grid3Bottom = grid3.top + grid3.height;
    const finalXAxis = option.xAxis[2] as unknown as { nameGap: number };
    const labelBottom = grid3Bottom + finalXAxis.nameGap;
    const slider = option.dataZoom[1] as { bottom: number; height: number };
    const sliderTop = 680 - slider.bottom - slider.height;

    expect(finalXAxis.nameGap).toBe(35);
    expect(sliderTop - labelBottom).toBeGreaterThanOrEqual(30);
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
          sample: { timestamp: "2026-01-01T00:00:00Z", time: timestamp, value: 12 },
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

    expect(option.series[0]?.markArea).toBeUndefined();
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
