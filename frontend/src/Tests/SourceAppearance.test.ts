// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildNavigationIndex, type ExplorerNode } from "@/domain/system/navigationIndex";
import { createEmptySystem, parseSystemDocument, serializeSystemDocument, validateSystemDocument, removeSystemEntity } from "@/domain/system/systemDocument";
import { setSourceAppearance } from "@/domain/system/sourceAppearance";
import { sourceIcon } from "@/components/source-icons/catalogue";
import { mqttConnection } from "./support/fixtures/system";
import type { SystemDocument } from "@/types/system";

const fixture = (): SystemDocument => ({
  ...createEmptySystem(),
  brokers: [mqttConnection({ id: "a", label: "A", host: "localhost" }), mqttConnection({ id: "b", label: "B", host: "localhost" })],
  devices: [{ id: "machine", label: "Machine", kind: "machine", broker_id: "a" }],
  readings: ["a", "b"].map(broker_id => ({ id: `value-${broker_id}`, broker_id, label: "Temperature", topic: "plant/line/temperature", category: "Other", value_type: "number" })),
  groups: [{ id: "line", label: "Line", member_ids: ["machine"] }],
});
const nodes = (document: SystemDocument) => [...buildNavigationIndex(document).nodes.values()];

describe("source appearance persistence", () => {
  it("roundtrips every entity kind and renders its saved identity in navigation", () => {
    let document = fixture();
    for (const id of ["a", "machine", "value-a"]) {
      const node = nodes(document).find(node => node.objectId === id)!;
      document = setSourceAppearance(document, node, { icon: "pump", color: "sage" });
    }
    document.groups[0]!.appearance = { icon: "valve", color: "teal" };
    const restored = parseSystemDocument(serializeSystemDocument(document));
    expect(restored).toEqual(document);
    for (const id of ["a", "machine", "value-a"]) {
      expect(nodes(restored).find(node => node.objectId === id)?.appearance).toEqual({ icon: "pump", color: "sage" });
    }
    expect(restored.readings[0]?.topic).toBe("plant/line/temperature");
    expect(restored.default_policy.mode).toBe("off");
  });

  it("scopes topic icons by broker and path, clears overrides, and removes them with a broker", () => {
    const document = fixture();
    const topic = nodes(document).find(node => node.topic === "plant/line" && node.connectionId === "a")!;
    const updated = setSourceAppearance(document, topic, { icon: "factory", color: "clay" });
    expect(nodes(updated).find(node => node.key === topic.key)?.appearance?.icon).toBe("factory");
    expect(nodes(updated).find(node => node.topic === topic.topic && node.connectionId === "b")?.appearance).toBeUndefined();
    expect(setSourceAppearance(updated, topic).topic_appearances).toEqual([]);
    expect(removeSystemEntity(updated, "connection", "a", true).topic_appearances).toEqual([]);
  });

  it("uses the same entity icon in every broker context and removes it on reset", () => {
    const document = fixture();
    document.readings.forEach(reading => { reading.device_id = "machine"; });
    const contexts = nodes(document).filter(node => node.objectId === "machine");
    expect(contexts).toHaveLength(2);
    const changed = setSourceAppearance(document, contexts[0]!, { icon: "motor", color: "blue" });
    expect(nodes(changed).filter(node => node.objectId === "machine").map(node => node.appearance?.icon)).toEqual(["motor", "motor"]);
    expect(setSourceAppearance(changed, contexts[1]!).devices[0]).not.toHaveProperty("appearance");
  });

  it.each([{ icon: "https://example.com/icon.svg" }, { icon: "<svg/>" }, { icon: "x".repeat(41) }, { color: "neon" }, { markup: "svg" }])("rejects invalid appearance metadata: %j", appearance => {
    const document = fixture();
    expect(() => validateSystemDocument({ ...document, brokers: [{ ...document.brokers[0], appearance }] })).toThrow();
  });

  it("accepts future icon names with a safe display fallback and nullable API fields", () => {
    const document = fixture();
    document.devices[0]!.appearance = { icon: "future-sensor", color: "teal" };
    expect(parseSystemDocument(serializeSystemDocument(document)).devices[0]?.appearance?.icon).toBe("future-sensor");
    expect(sourceIcon("device", "future-sensor").id).toBe("cpu");
    expect(sourceIcon("device", "constructor").id).toBe("cpu");
    expect(validateSystemDocument({ ...document, brokers: document.brokers.map(item => ({ ...item, appearance: { icon: null, color: null } })) }).brokers[0]).not.toHaveProperty("appearance");
  });

  it("rejects duplicate or orphaned topic overrides and missing edited entities", () => {
    const document = fixture();
    const entry = { broker_id: "a", topic: "plant", appearance: { color: "sage" } };
    expect(() => validateSystemDocument({ ...document, topic_appearances: [entry, entry] })).toThrow(/duplicate/);
    expect(() => validateSystemDocument({ ...document, topic_appearances: [{ ...entry, broker_id: "missing" }] })).toThrow(/broker/);
    expect(() => setSourceAppearance(document, { entityKind: "device", objectId: "missing" } as ExplorerNode, {})).toThrow(/no longer exists/);
  });
});
