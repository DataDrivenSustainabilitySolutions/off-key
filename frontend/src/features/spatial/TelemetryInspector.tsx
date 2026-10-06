import { useMemo, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  LockKeyhole,
  Radio,
  UnlockKeyhole,
} from "lucide-react";
import { EChart } from "@/components/EChart";
import type { TelemetryChartOption } from "@/lib/telemetry-chart";
import type { NodeTelemetry, SpatialGroup, SpatialNode } from "./types";

type Props = {
  node: SpatialNode;
  group: SpatialGroup | undefined;
  groups: SpatialGroup[];
  snapshot: NodeTelemetry | undefined;
  now: number;
  editMode: boolean;
  isDemo: boolean;
  onGroup: (groupId: string) => void;
  onLock: () => void;
  onPosition: (axis: "x" | "z", value: number) => void;
  onRate: (value: number) => void;
  onFocus: () => void;
};

const number = (value: number) =>
  new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value);

export function TelemetryInspector({
  node,
  group,
  groups,
  snapshot,
  now,
  editMode,
  isDemo,
  onGroup,
  onLock,
  onPosition,
  onRate,
  onFocus,
}: Props) {
  const samples = snapshot?.samples;
  const [viewport, setViewport] = useState<{
    startValue: number;
    endValue: number;
  } | null>(null);
  const start = samples?.[0]?.timestamp;
  const end = samples?.[samples.length - 1]?.timestamp;
  const option = useMemo<TelemetryChartOption>(
    () => ({
      backgroundColor: "#ffffff",
      animation: false,
      grid: { left: 45, right: 14, top: 20, bottom: 55 },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: "#ffffff",
        borderColor: "#e5e7eb",
        textStyle: { color: "#27313a" },
      },
      xAxis: {
        type: "time",
        min: start,
        max: end,
        axisLine: { lineStyle: { color: "#dce2e6" } },
        axisLabel: { color: "#7a838d", fontSize: 10 },
        splitNumber: 3,
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: "#7a838d", fontSize: 10 },
        splitLine: { lineStyle: { color: "#eff2f4" } },
        splitNumber: 3,
      },
      dataZoom: [
        {
          type: "inside",
          filterMode: "none",
          ...(viewport ?? { start: 0, end: 100 }),
        },
        {
          type: "slider",
          ...(viewport ?? { start: 0, end: 100 }),
          height: 15,
          bottom: 9,
          borderColor: "transparent",
          showDetail: false,
          fillerColor: "#0e817410",
          dataBackground: {
            lineStyle: { color: "#c4cdd3" },
            areaStyle: { color: "#f3f5f6" },
          },
        },
      ],
      series: [
        {
          type: "line",
          name: node.metric,
          data: (samples ?? []).map((sample) => [
            sample.timestamp,
            sample.value,
          ]),
          showSymbol: false,
          connectNulls: false,
          sampling: "lttb",
          lineStyle: { width: 2, color: group?.color ?? "#0e8174" },
          areaStyle: { color: group?.color ?? "#0e8174", opacity: 0.055 },
        },
      ],
    }),
    [samples, start, end, viewport, group?.color, node.metric],
  );
  const age = snapshot?.lastSeen
    ? Math.max(0, Math.floor((now - snapshot.lastSeen) / 1000))
    : null;
  const pinned = node.locked || !!group?.locked;

  return (
    <div className="sp-inspector-content">
      <div className="sp-inspector-identity">
        <span className="sp-object-glyph" style={{ color: group?.color }}>
          <Radio size={22} />
        </span>
        <div>
          <span className="sp-overline">
            {node.kind === "broker"
              ? "MQTT broker"
              : node.kind === "group"
                ? "Collection"
                : "Sensor stream"}
          </span>
          <h2>{node.label}</h2>
        </div>
      </div>
      <div className="sp-inspector-actions">
        <button onClick={onFocus}>
          <ArrowUpRight size={14} /> Focus
        </button>
        {node.kind !== "group" && (
          <button onClick={onLock} aria-pressed={node.locked}>
            {node.locked ? (
              <LockKeyhole size={14} />
            ) : (
              <UnlockKeyhole size={14} />
            )}
            {node.locked ? "Pinned" : "Pin object"}
          </button>
        )}
      </div>
      <section className="sp-reading">
        <div>
          <span className="sp-overline">{node.metric}</span>
          <p>
            {snapshot
              ? number(node.kind === "broker" ? snapshot.rate : snapshot.value)
              : "—"}
            <span>{node.unit}</span>
          </p>
        </div>
        <span className="sp-freshness">
          <i className={age !== null && age < 10 ? "active" : ""} />
          {age === null
            ? "Waiting for data"
            : age === 0
              ? "Just received"
              : `${age}s ago`}
        </span>
      </section>
      <div className="sp-inspector-metrics">
        <div>
          <span>Arrival rate</span>
          <strong>
            {snapshot ? number(snapshot.rate) : "0"}
            <small> msg/s</small>
          </strong>
        </div>
        <div>
          <span>Received</span>
          <strong>{number(snapshot?.received ?? 0)}</strong>
        </div>
      </div>
      <section className="sp-chart-section">
        <div className="sp-section-title">
          <h3>Signal history</h3>
          <span>
            {isDemo ? "Simulated · 360 samples max" : "Latest 360 samples"}
          </span>
        </div>
        <EChart
          onViewportChange={(startValue, endValue) =>
            setViewport({ startValue, endValue })
          }
          option={option}
          resolvedTheme="light"
          accessibleDescription={`${node.label} ${node.metric} in ${node.unit} over time. Scroll to zoom the chart.`}
          className="sp-inspector-chart"
        />
        <div className="sp-chart-hint">
          {viewport ? (
            <button onClick={() => setViewport(null)}>
              Return to live range ↗
            </button>
          ) : (
            "Scroll to zoom · drag the range below"
          )}
        </div>
      </section>
      {isDemo && node.kind === "sensor" && (
        <section className="sp-cadence">
          <label htmlFor="sp-cadence">
            Publish cadence <span>{number(node.baseRate)} msg/s</span>
          </label>
          <input
            id="sp-cadence"
            type="range"
            min="0"
            max="10"
            step="0.25"
            value={node.baseRate}
            onChange={(event) => onRate(Number(event.target.value))}
          />
          <p>
            Change the simulator and watch the connection respond. Zero makes
            this stream quiet.
          </p>
        </section>
      )}
      <section className="sp-placement">
        <h3>Placement</h3>
        <label htmlFor="sp-node-group">Collection</label>
        <select
          id="sp-node-group"
          value={node.groupId}
          onChange={(event) => onGroup(event.target.value)}
          disabled={node.kind === "group"}
        >
          {groups.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <div className="sp-coordinate-fields">
          {(["x", "z"] as const).map((axis) => (
            <label key={axis}>
              {axis.toUpperCase()}
              <input
                aria-label={`${axis.toUpperCase()} position`}
                type="number"
                step="0.5"
                value={Number(node.position[axis].toFixed(1))}
                disabled={!editMode || pinned || node.kind === "group"}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (
                    event.target.value &&
                    Number.isFinite(value) &&
                    Math.abs(value) <= 1000
                  )
                    onPosition(axis, value);
                }}
              />
            </label>
          ))}
        </div>
        <p>
          {group?.locked
            ? "This collection is locked. Unlock it to arrange members."
            : pinned
              ? "Pinned objects keep their position when arranging a collection."
              : editMode
                ? "Drag this object on the plane, or use arrow keys after selecting it."
                : "Enable Arrange to move objects. Inspection stays available."}
        </p>
      </section>
      <p className="sp-draft-note">
        <Activity size={14} />
        This draft previews telemetry and layout. Detection evidence will use
        the application's existing charts when connected.
      </p>
    </div>
  );
}
