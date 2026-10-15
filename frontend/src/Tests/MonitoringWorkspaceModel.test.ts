import { describe, expect, it } from "vitest";
import { buildMonitoringIndex, serviceName, serviceState, servicesForScope } from "@/features/monitoring/serviceModel";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import type { SystemDocument, SystemRuntime } from "@/features/catalogue/systemTypes";
import type { ActiveService, OperationalStage } from "@/types/monitoring";

const monitor = (id: string, topic: string, stage: OperationalStage = "operational"): ActiveService => ({
  id, container_id: id, container_name: `worker-${id}`, mqtt_topics: [topic], status: true,
  monitoring_strategy: "adaptive_stream", model_type: "aberrant_knn",
  operational_status: { stage, message_count: 40, processed_message_count: 35, is_stale: false },
});
function fixture(count = 2) {
  const document: SystemDocument = { ...createEmptySystem(),
    connections: Array.from({ length: count }, (_, index) => ({ id: `broker-${index}`, label: "Same broker label", protocol: "mqtt", host: `broker-${index}.test`, port: 1883, transport: "tcp", tls: false })),
    devices: Array.from({ length: count }, (_, index) => ({ id: `entity-${index}`, label: `Room ${index}`, connection_id: `broker-${index}`, kind: "generic" })),
    streams: Array.from({ length: count * 20 }, (_, index) => ({ id: `reading-${index}`, label: `Measurement ${index}`, topic: `arbitrary/room/value-${index}`,
      value_type: "number", category: "Environment", connection_id: `broker-${Math.floor(index / 20)}`, device_id: `entity-${Math.floor(index / 20)}` })),
  };
  const runtime: SystemRuntime = { mode: "configured_only", message: "Configured", bindings: Object.fromEntries(document.streams.map(stream => [stream.id, { entity_id: `internal-${stream.device_id}`, telemetry_key: stream.id,
      accepted_topic: `telemetry/internal-${stream.device_id}/${stream.id}`, policy: { mode: "off", interval_seconds: 10 } }])) };
  return { document, runtime };
}

describe("monitoring workspace identity and scale", () => {
  it("maps inputs using accepted topics when broker labels repeat and upstream paths differ", () => {
    const { document, runtime } = fixture();
    const services = [monitor("first", runtime.bindings!["reading-0"]!.accepted_topic), monitor("second", runtime.bindings!["reading-20"]!.accepted_topic)];
    const index = buildMonitoringIndex(document, runtime, services);
    expect(index.targets).toHaveLength(2);
    expect(index.inputs.get("first")?.map(input => input.stream.id)).toEqual(["reading-0"]);
    expect(servicesForScope(services, index, ["reading-20"])).toEqual([services[1]]);
    expect(servicesForScope(services, index)).toBe(services);
    expect(servicesForScope(services, index, [])).toEqual([]);
    document.connections[0]!.label = "Renamed broker";
    const renamed = buildMonitoringIndex(document, runtime, services);
    expect(renamed.byStream.get("reading-0")).toEqual(new Set(["first"]));
    expect(serviceName(services[0]!, renamed.inputs.get("first")!)).toBe("Renamed broker / Room 0 · Adaptive");
    expect(serviceName({ ...services[0]!, display_name: "Personal name" }, renamed.inputs.get("first")!)).toBe("Personal name");
  });

  it("keeps Off readings available to choose without claiming they are being collected", () => {
    const { document, runtime } = fixture(1);
    const index = buildMonitoringIndex(document, runtime, []);
    expect(index.targets[0]?.inputs).toHaveLength(20);
    expect(index.targets[0]?.inputs.every(input => input.binding.policy.mode === "off")).toBe(true);
    expect(buildMonitoringIndex(document, undefined, []).targets).toEqual([]);
  });

  it("resolves legacy wildcard inputs and leaves unmapped services visible globally", () => {
    const { document, runtime } = fixture();
    const services = [monitor("legacy", "telemetry/internal-entity-0/#"), monitor("unmapped", "telemetry/absent/value")];
    const index = buildMonitoringIndex(document, runtime, services);
    expect(index.inputs.get("legacy")).toHaveLength(20);
    expect(index.inputs.get("unmapped")).toEqual([]);
    expect(servicesForScope(services, index, ["reading-5"]).map(service => service.id)).toEqual(["legacy"]);
  });

  it("indexes 20,000 catalogue inputs and 1,000 services without expanding charts or losing scope", () => {
    const { document, runtime } = fixture(1000);
    const services = document.devices.map((device, index) => monitor(device.id, runtime.bindings![`reading-${index * 20}`]!.accepted_topic));
    const index = buildMonitoringIndex(document, runtime, services);
    expect(index.targets).toHaveLength(1000);
    expect(index.inputs.size).toBe(1000);
    expect(servicesForScope(services, index, ["reading-19980"])[0]?.id).toBe("entity-999");
  });

  it("distinguishes learning, stale status, failures and stopped services without anomaly counts", () => {
    const service = monitor("one", "input", "collecting_training");
    expect(serviceState(service)).toMatchObject({ label: "Learning", category: "preparing" });
    expect(serviceState({ ...service, operational_status: { ...service.operational_status, is_stale: true } })).toMatchObject({ label: "Status stale", category: "attention" });
    expect(serviceState({ ...service, operational_status: { ...service.operational_status, stage: "operational", coverage: {
      delivery: "best_effort", has_gaps: true, received_message_count: 1100,
      dropped_message_count: 100, dropped_by_reason: { rate_limit: 100 }, possible_gap_count: 0,
    } } })).toMatchObject({ label: "Coverage gap", category: "attention" });
    expect(serviceState({ ...service, operational_status: { ...service.operational_status, stage: "failed", is_stale: true } })).toMatchObject({ label: "Failed", tone: "danger" });
    expect(serviceState({ ...service, status: false })).toMatchObject({ label: "Stopped", category: "stopped" });
  });
});
