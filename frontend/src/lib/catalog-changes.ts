import type { Catalog, CollectionPolicy } from "@/types/collection";
import { effectivePolicy } from "@/types/collection";

export function policyLabel(policy: CollectionPolicy | null): string {
  if (!policy) return "Use default";
  if (policy.mode === "off") return "Paused";
  if (policy.mode === "original") return "Original rate";
  return `Latest every ${policy.interval_seconds}s`;
}

type ChangeGroup = { title: string; details: string[] };

export function catalogChanges(before: Catalog, after: Catalog): ChangeGroup[] {
  const groups: ChangeGroup[] = [];
  const fields = (changes: [string, string | null, string | null][]) =>
    changes
      .filter(([, oldValue, newValue]) => oldValue !== newValue)
      .map(
        ([label, oldValue, newValue]) =>
          `${label}: ${oldValue ?? "None"} → ${newValue ?? "None"}`,
      );
  const defaults = fields([
    [
      "Collection",
      policyLabel(before.default_policy),
      policyLabel(after.default_policy),
    ],
  ]);
  if (defaults.length)
    groups.push({ title: "Fleet default", details: defaults });

  const oldSources = new Map(
    before.sources.map((source) => [source.id, source]),
  );
  const newSources = new Map(
    after.sources.map((source) => [source.id, source]),
  );
  for (const id of new Set([...oldSources.keys(), ...newSources.keys()])) {
    const oldSource = oldSources.get(id);
    const source = newSources.get(id);
    if (!source) {
      groups.push({
        title: oldSource!.label,
        details: [
          `Remove broker and its ${oldSource!.chargers.length} chargers`,
        ],
      });
      continue;
    }
    const details = oldSource
      ? fields([
          ["Broker name", oldSource.label, source.label],
          [
            "Endpoint",
            `${oldSource.host}:${oldSource.port}`,
            `${source.host}:${source.port}`,
          ],
          [
            "Evidence",
            oldSource.verified ? "Observed broker" : "Candidate host",
            source.verified ? "Observed broker" : "Candidate host",
          ],
        ])
      : [
          `Add ${source.verified ? "observed broker" : "candidate host"} · ${source.host}:${source.port}`,
        ];
    if (details.length) groups.push({ title: source.label, details });

    const oldChargers = new Map(
      oldSource?.chargers.map((charger) => [charger.id, charger]) ?? [],
    );
    const newChargers = new Map(
      source.chargers.map((charger) => [charger.id, charger]),
    );
    for (const chargerId of new Set([
      ...oldChargers.keys(),
      ...newChargers.keys(),
    ])) {
      const oldCharger = oldChargers.get(chargerId);
      const charger = newChargers.get(chargerId);
      if (!charger) {
        groups.push({
          title: `${source.label} / ${oldCharger!.label}`,
          details: [
            `Remove charger and its ${oldCharger!.sensors.length} sensors`,
          ],
        });
        continue;
      }
      const chargerDetails = oldCharger
        ? fields([
            ["Charger name", oldCharger.label, charger.label],
            ["Local charger ID", oldCharger.local_id, charger.local_id],
            [
              "Charger default",
              policyLabel(oldCharger.policy),
              policyLabel(charger.policy),
            ],
          ])
        : [
            `Add charger · local ID ${charger.local_id} · ${policyLabel(charger.policy)}`,
          ];
      const oldSensors = new Map(
        oldCharger?.sensors.map((sensor) => [sensor.key, sensor]) ?? [],
      );
      const newSensors = new Map(
        charger.sensors.map((sensor) => [sensor.key, sensor]),
      );
      for (const key of new Set([...oldSensors.keys(), ...newSensors.keys()])) {
        const oldSensor = oldSensors.get(key);
        const sensor = newSensors.get(key);
        if (!sensor) {
          chargerDetails.push(`${oldSensor!.label} (${key}): Remove sensor`);
          continue;
        }
        const label = `${sensor.label} (${key})`;
        const effective = policyLabel(effectivePolicy(after, charger, sensor));
        if (!oldSensor || !oldCharger) {
          chargerDetails.push(
            `${label}: Add sensor · ${effective} · ${sensor.upstream_topic}`,
          );
          continue;
        }
        const sensorDetails = fields([
          [
            "Collection",
            policyLabel(effectivePolicy(before, oldCharger, oldSensor)),
            effective,
          ],
          [
            "Override",
            policyLabel(oldSensor.policy),
            policyLabel(sensor.policy),
          ],
          ["Name", oldSensor.label, sensor.label],
          ["Topic", oldSensor.upstream_topic, sensor.upstream_topic],
          ["Type", oldSensor.value_type, sensor.value_type],
          ["Category", oldSensor.category, sensor.category],
          ["Unit", oldSensor.unit, sensor.unit],
        ]);
        chargerDetails.push(
          ...sensorDetails.map((detail) => `${label} · ${detail}`),
        );
      }
      if (chargerDetails.length)
        groups.push({
          title: `${source.label} / ${charger.label}`,
          details: chargerDetails,
        });
    }
  }
  return groups;
}
