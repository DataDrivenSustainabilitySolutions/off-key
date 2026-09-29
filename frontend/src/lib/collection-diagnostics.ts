import type { CollectionStatus, RuntimeState } from "@/types/collection";

export function diagnosticsFresh(state: RuntimeState, now = Date.now()) {
  const age = now - Date.parse(state.checked_at ?? "");
  return Number.isFinite(age) && age >= -5000 && age <= 15000;
}

export function collectionDiagnosis(snapshot: CollectionStatus, now = Date.now()): [string, string] {
  const { collection, ingress, revision } = snapshot;
  const data = collection.diagnostics;
  if (revision === 0)
    return [
      "Not configured",
      "Add a catalog and select sensors to start collecting.",
    ];
  if (!diagnosticsFresh(collection, now))
    return [
      "Worker not reporting",
      "Collection status is stale. Check the collector and database connection.",
    ];
  if (!data)
    return [
      "Waiting for measurements",
      "The worker has not reported diagnostics yet.",
    ];
  if (!data.mqtt_connected)
    return [
      "Disconnected",
      "The collector cannot reach the local MQTT broker.",
    ];
  if (collection.status === "error")
    return [
      "Collection error",
      collection.error ?? "Check the collector logs and database connection.",
    ];
  if (collection.revision !== revision)
    return [
      "Applying changes",
      "Wait for the workers to apply the saved catalog.",
    ];
  if (collection.selected_sensors === 0 && collection.status === "applied")
    return [
      "Paused",
      "No sensors are selected in the saved catalog. Enable sensors and apply the changes.",
    ];
  if (ingress.status === "disabled")
    return [
      "Ingress disabled",
      "The operator has disabled the AmbiBox connection.",
    ];
  if (!diagnosticsFresh(ingress, now))
    return [
      "Broker controller not reporting",
      "Route status is stale. Check TACTIC and its database connection.",
    ];
  if (ingress.revision === revision && ingress.status === "error")
    return [
      "Broker routes failed",
      ingress.error ?? Object.values(ingress.sources ?? {}).find((source) => source.error)?.error ??
        "Check the broker controller, vendor tailnet and endpoint configuration.",
    ];
  if (ingress.revision !== revision || ingress.status !== "applied")
    return [
      "Broker routes not ready",
      ingress.error ?? "The broker controller is applying the saved catalog.",
    ];
  if (collection.status !== "applied")
    return [
      "Applying changes",
      "Wait for the collector to activate the saved catalog.",
    ];
  if (Object.values(ingress.sources ?? {}).some((source) => !["connected", "paused"].includes(source.status)))
    return [
      "Broker disconnected",
      "At least one selected broker is unavailable. Check its endpoint, vendor tailnet and credentials.",
    ];
  if (data.database_retrying)
    return [
      "Database retrying",
      "Accepted measurements are waiting for the database. Queues are bounded; sustained pressure can drop new observations.",
    ];
  if ((data.rates.overload_dropped ?? 0) > 0)
    return [
      "Overloaded",
      "Recent traffic exceeded the original-rate queue. Increase sampling intervals or pause sensors.",
    ];
  if ((data.rates.invalid ?? 0) > 0)
    return [
      "Invalid payloads",
      "Some recent messages do not match their catalog types or ingress format. Check the sensor definitions.",
    ];
  if (data.rates.received === null)
    return [
      "Measuring traffic",
      "Waiting for the first rate measurement.",
    ];
  if (data.rates.received === 0)
    return [
      "Connected but quiet",
      "Connections are ready, but selected topics have no recent messages. Check the topics and whether the chargers are sending.",
    ];
  return [
    "Collecting",
    "Selected messages are arriving. Sampling keeps only the newest observation per interval.",
  ];
}
