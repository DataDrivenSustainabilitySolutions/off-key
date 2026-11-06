import type { ActiveService } from "@/types/monitoring";
import type { SystemDocument, SystemReadingBinding, SystemRuntime, SystemStream } from "@/types/system";

export type MonitoringInput = { stream: SystemStream; binding: SystemReadingBinding; path: string };
/** The readings one monitor may watch: a device's, or a broker's readings without a device. */
export type MonitoringTarget = { id: string; label: string; inputs: MonitoringInput[] };

/** A target's id, `device:<id>` or `broker:<id>`, as setup links carry it. */
export const monitoringTargetId = (source: { kind: "device" | "broker"; id: string }) => `${source.kind}:${source.id}`;

/** The target a catalogue reading belongs to. */
export const readingTargetId = (stream: Pick<SystemStream, "device_id" | "broker_id">) =>
  monitoringTargetId(stream.device_id ? { kind: "device", id: stream.device_id } : { kind: "broker", id: stream.broker_id });
export type ServiceState = { label: string; tone: "neutral" | "positive" | "warning" | "danger"; category: "monitoring" | "preparing" | "stopped" | "attention" };
export type MonitoringIndex = {
  targets: MonitoringTarget[];
  inputs: Map<string, MonitoringInput[]>;
  byStream: Map<string, Set<string>>;
};

export function serviceState(service: ActiveService): ServiceState {
  const stage = service.operational_status.stage;
  if (!service.active || stage === "stopped") return { label: "Stopped", tone: "neutral", category: "stopped" };
  if (stage === "failed") return { label: "Failed", tone: "danger", category: "attention" };
  if (service.operational_status.is_stale) return { label: "No recent status", tone: "warning", category: "attention" };
  if (service.operational_status.activity?.inputs_stalled) return { label: "No recent inputs", tone: "warning", category: "attention" };
  if (service.operational_status.activity?.inference_stalled) return { label: "No recent evaluations", tone: "warning", category: "attention" };
  if (service.operational_status.activity?.persistence_stalled) return { label: "Persistence delayed", tone: "warning", category: "attention" };
  if (service.operational_status.coverage?.has_gaps) return { label: "Coverage gap", tone: "warning", category: "attention" };
  if (stage === "degraded") return { label: "Degraded", tone: "warning", category: "attention" };
  if (stage === "operational") return { label: "Active", tone: "positive", category: "monitoring" };
  const labels: Partial<Record<typeof stage, string>> = {
    starting: "Starting", waiting_for_data: "Waiting for data", collecting_training: "Learning",
    collecting_calibration: "Calibrating", training: "Training",
  };
  return { label: labels[stage] ?? "Starting", tone: "neutral", category: "preparing" };
}

export function strategyName(service: Pick<ActiveService, "monitoring_strategy">): string {
  return service.monitoring_strategy === "adaptive_stream" ? "Adaptive" : service.monitoring_strategy === "static_baseline" ? "Static" : "Monitoring";
}

export function serviceName(service: ActiveService, inputs: MonitoringInput[]): string {
  if (service.display_name) return service.display_name;
  const paths = [...new Set(inputs.map(({ path }) => path))];
  return paths.length === 1 ? `${paths[0]} · ${strategyName(service)}` : service.display_name ?? service.id;
}

/** Group catalogue readings by device or broker and by the monitors the server resolved for each. */
export function buildMonitoringIndex(document: SystemDocument, runtime: SystemRuntime | undefined, services: ActiveService[]): MonitoringIndex {
  const connections = new Map(document.brokers.map(item => [item.id, item.label]));
  const devices = new Map(document.devices.map(item => [item.id, item.label]));
  const byId = new Map<string, MonitoringInput>();
  const targets = new Map<string, MonitoringTarget>();
  for (const stream of document.readings) {
    const binding = runtime?.bindings?.[stream.id];
    if (!binding || stream.value_type !== "number") continue;
    const broker = connections.get(stream.broker_id) ?? stream.broker_id;
    const entity = stream.device_id ? devices.get(stream.device_id) : undefined;
    const path = entity && entity !== broker ? `${broker} / ${entity}` : broker;
    const input = { stream, binding, path };
    byId.set(stream.id, input);
    const id = readingTargetId(stream);
    const target = targets.get(id) ?? { id, label: path, inputs: [] };
    target.inputs.push(input); targets.set(id, target);
  }
  const inputs = new Map<string, MonitoringInput[]>();
  const byStream = new Map<string, Set<string>>();
  for (const service of services) {
    const matched = service.reading_ids.flatMap(id => byId.get(id) ?? []);
    inputs.set(service.id, matched);
    for (const { stream } of matched) {
      const ids = byStream.get(stream.id) ?? new Set<string>();
      ids.add(service.id); byStream.set(stream.id, ids);
    }
  }
  return { targets: [...targets.values()].sort((a, b) => a.label.localeCompare(b.label)), inputs, byStream };
}

export function servicesForScope(services: ActiveService[], index: MonitoringIndex, streamIds?: readonly string[]): ActiveService[] {
  if (!streamIds) return services;
  const ids = new Set(streamIds.flatMap(id => [...(index.byStream.get(id) ?? [])]));
  return services.filter(service => ids.has(service.id));
}

export function modelName(modelType: string): string {
  return modelType.replace(/^aberrant_/, "").replace(/_/g, " ");
}
