import { describe, expect, it } from "vitest";
import { catalogRemovals } from "../lib/catalog-changes";
import type { Catalog } from "../types/collection";

const catalog = (): Catalog => ({
  schema_version: 1,
  provider: "ambibox",
  default_policy: { mode: "sample", interval_seconds: 10 },
  sources: [
    {
      id: "broker",
      label: "Yard",
      host: "yard.ts.net",
      port: 1883,
      verified: true,
      forward_port: 20000,
      chargers: [
        {
          id: "charger",
          local_id: "0",
          label: "Charger",
          policy: null,
          sensors: ["temperature", "power"].map((key) => ({
            key,
            label: key,
            category: "Telemetry",
            value_type: "number",
            unit: null,
            upstream_topic: `device/evCharger/0/${key}`,
            policy:
              key === "power"
                ? { mode: "original", interval_seconds: 10 }
                : null,
          })),
        },
      ],
    },
  ],
});

describe("catalog removal confirmation", () => {
  it("does not treat metadata, rates or additions as removals", () => {
    const before = catalog();
    const after = catalog();
    after.default_policy.interval_seconds = 60;
    after.sources[0]!.host = "other.ts.net";
    after.sources[0]!.chargers[0]!.label = "Renamed";
    after.sources[0]!.chargers[0]!.sensors.push({
      ...after.sources[0]!.chargers[0]!.sensors[0]!,
      key: "voltage",
    });
    expect(catalogRemovals(before, after)).toEqual([]);
  });

  it("names removed parents once, and individual removed measurements", () => {
    const before = catalog();
    const after = catalog();
    after.sources[0]!.chargers[0]!.sensors.pop();
    expect(catalogRemovals(before, after)).toEqual(["Charger · power"]);
    after.sources[0]!.chargers = [];
    expect(catalogRemovals(before, after)).toEqual(["Charger Charger"]);
    after.sources = [];
    expect(catalogRemovals(before, after)).toEqual(["Broker Yard"]);
  });

  it("recognizes measurement key changes as removal of the old identity", () => {
    const before = catalog();
    const after = catalog();
    after.sources[0]!.chargers[0]!.sensors[0]!.key = "new-temperature";
    expect(catalogRemovals(before, after)).toEqual(["Charger · temperature"]);
  });

  it("does not mistake a charger moved between existing brokers for deletion", () => {
    const before = catalog();
    before.sources.push({ ...before.sources[0]!, id: "second", chargers: [] });
    const after = structuredClone(before);
    after.sources[1]!.chargers = after.sources[0]!.chargers;
    after.sources[0]!.chargers = [];
    expect(catalogRemovals(before, after)).toEqual([]);
  });
});
