import { mqttFiltersOverlap } from "@/lib/monitoring-services";
import type { ActiveService } from "@/types/monitoring";
import type { SystemDocument, SystemReadingBinding, SystemRuntime, SystemStream } from "../catalogue/systemTypes";

export type MonitoringInput = { stream: SystemStream; binding: SystemReadingBinding; path: string };
export type MonitoringTarget = { id: string; label: string; inputs: MonitoringInput[] };
export type ServiceState = { label: string; tone: "neutral" | "positive" | "warning" | "danger"; category: "monitoring" | "preparing" | "stopped" | "attention" };
export type MonitoringIndex = {
  targets: MonitoringTarget[];
  inputs: Map<string, MonitoringInput[]>;
  byStream: Map<string, Set<string>>;
};

export function serviceState(service: ActiveService): ServiceState {
  const stage = service.operational_status.stage;
  if (!service.status || stage === "stopped") return { label: "Stopped", tone: "neutral", category: "stopped" };
  if (stage === "failed") return { label: "Failed", tone: "danger", category: "attention" };
  if (service.operational_status.is_stale) return { label: "Status stale", tone: "warning", category: "attention" };
  if (service.operational_status.activity?.inputs_stalled) return { label: "Inputs stale", tone: "warning", category: "attention" };
  if (service.operational_status.activity?.inference_stalled) return { label: "Inference stalled", tone: "warning", category: "attention" };
  if (service.operational_status.activity?.persistence_stalled) return { label: "Persistence delayed", tone: "warning", category: "attention" };
  if (service.operational_status.coverage?.has_gaps) return { label: "Coverage gap", tone: "warning", category: "attention" };
  if (stage === "degraded") return { label: "Degraded", tone: "warning", category: "attention" };
  if (stage === "operational") return { label: "Monitoring", tone: "positive", category: "monitoring" };
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
  return paths.length === 1 ? `${paths[0]} · ${strategyName(service)}` : service.container_name;
}

/** Match stable accepted inputs, independent of display names and upstream topic conventions. */
export function buildMonitoringIndex(document: SystemDocument, runtime: SystemRuntime | undefined, services: ActiveService[]): MonitoringIndex {
  const connections = new Map(document.connections.map(item => [item.id, item.label]));
  const devices = new Map(document.devices.map(item => [item.id, item.label]));
  const accepted = new Map<string, MonitoringInput[]>();
  const targets = new Map<string, MonitoringTarget>();
  for (const stream of document.streams) {
    const binding = runtime?.bindings?.[stream.id];
    if (!binding || stream.value_type !== "number") continue;
    const broker = connections.get(stream.connection_id) ?? stream.connection_id;
    const entity = stream.device_id ? devices.get(stream.device_id) : undefined;
    const path = entity && entity !== broker ? `${broker} / ${entity}` : broker;
    const input = { stream, binding, path };
    const matches = accepted.get(binding.accepted_topic) ?? [];
    matches.push(input); accepted.set(binding.accepted_topic, matches);
    const target = targets.get(binding.entity_id) ?? { id: binding.entity_id, label: path, inputs: [] };
    target.inputs.push(input); targets.set(binding.entity_id, target);
  }
  const inputs = new Map<string, MonitoringInput[]>();
  const byStream = new Map<string, Set<string>>();
  for (const service of services) {
    const found = new Map<string, MonitoringInput>();
    for (const topic of service.mqtt_topics) {
      const matches = topic.includes("+") || topic.includes("#")
        ? [...accepted.entries()].filter(([concrete]) => mqttFiltersOverlap(topic, concrete)).flatMap(([, entries]) => entries)
        : accepted.get(topic) ?? [];
      for (const input of matches) found.set(input.stream.id, input);
    }
    const matched = [...found.values()]; inputs.set(service.id, matched);
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

export function formatServiceTime(value: string | null | undefined): string {
  if (!value) return "Awaiting update";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Awaiting update";
  const time = { hour: "2-digit", minute: "2-digit", second: "2-digit" } as const;
  // A bare time reads as today, so older updates also name their day.
  return date.toDateString() === new Date().toDateString() ? date.toLocaleTimeString(undefined, time)
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

export function modelName(modelType: string): string {
  return modelType.replace(/^aberrant_/, "").replace(/_/g, " ");
}
