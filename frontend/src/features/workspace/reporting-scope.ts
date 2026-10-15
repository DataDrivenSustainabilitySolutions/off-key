import type { Anomaly } from "@/types/charger";
import type { SystemRuntime } from "../catalogue/systemTypes";

/** Match recorded identities, independent of catalogue labels and MQTT topic names. */
export function filterSourceReports(reports: Anomaly[], ids: readonly string[] | undefined, runtime?: SystemRuntime) {
  if (!ids) return reports;
  const selected = new Set(ids);
  const entityKeys = new Map<string, Set<string>>();
  const entireEntity = new Map<string, boolean>();
  for (const [id, binding] of Object.entries(runtime?.bindings ?? {})) {
    entireEntity.set(binding.entity_id, (entireEntity.get(binding.entity_id) ?? true) && selected.has(id));
    if (!selected.has(id)) continue;
    const keys = entityKeys.get(binding.entity_id) ?? new Set<string>();
    keys.add(binding.telemetry_key);
    entityKeys.set(binding.entity_id, keys);
  }
  return reports.filter(report => {
    const keys = entityKeys.get(report.charger_id);
    if (!keys) return false;
    if (report.sensor_set?.length) return report.sensor_set.some(key => keys.has(key));
    if (report.telemetry_type === "__multivariate__") return entireEntity.get(report.charger_id) === true;
    return keys.has(report.telemetry_type);
  });
}
