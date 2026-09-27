import { describe, expect, it } from "vitest";
import { catalogChanges } from "../lib/catalog-changes";
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

describe("readable catalog changes", () => {
  it("explains inherited interval changes while respecting sensor overrides", () => {
    const before = catalog();
    const after = catalog();
    after.default_policy.interval_seconds = 60;
    const changes = catalogChanges(before, after);
    expect(changes).toEqual([
      {
        title: "Fleet default",
        details: ["Collection: Latest every 10s → Latest every 60s"],
      },
      {
        title: "Yard / Charger",
        details: [
          "temperature (temperature) · Collection: Latest every 10s → Latest every 60s",
        ],
      },
    ]);
    expect(catalogChanges(before, catalog())).toEqual([]);
  });

  it("includes routing, additions, removals, and an override with unchanged effective collection", () => {
    const before = catalog();
    const after = catalog();
    const source = after.sources[0]!;
    const charger = source.chargers[0]!;
    source.host = "new-yard.ts.net";
    source.verified = false;
    charger.local_id = "1";
    charger.sensors = [
      {
        ...charger.sensors[0]!,
        upstream_topic: "device/evCharger/1/temperature",
        policy: { mode: "sample", interval_seconds: 10 },
      },
      {
        ...charger.sensors[0]!,
        key: "voltage",
        label: "Voltage",
        upstream_topic: "device/evCharger/1/voltage",
        policy: { mode: "off", interval_seconds: 10 },
      },
    ];
    const details = catalogChanges(before, after)
      .flatMap((group) => group.details)
      .join("\n");
    expect(details).toContain(
      "Endpoint: yard.ts.net:1883 → new-yard.ts.net:1883",
    );
    expect(details).toContain("Evidence: Observed broker → Candidate host");
    expect(details).toContain("Local charger ID: 0 → 1");
    expect(details).toContain("Override: Use default → Latest every 10s");
    expect(details).toContain(
      "Topic: device/evCharger/0/temperature → device/evCharger/1/temperature",
    );
    expect(details).toContain("power (power): Remove sensor");
    expect(details).toContain("Voltage (voltage): Add sensor · Paused");
    expect(catalogChanges(before, { ...after, sources: [] })).toEqual([
      { title: "Yard", details: ["Remove broker and its 1 chargers"] },
    ]);
  });
});
