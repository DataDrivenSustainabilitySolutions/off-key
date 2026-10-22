// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  bindingsReady, predecessorEntity, predecessorTarget, previousBindings, readingOwnedElsewhere, suggestBindings,
} from "@/features/pipelines/bindings";
import type { PipelineServiceView } from "@/features/pipelines/contracts";
import type { MonitoringTarget } from "@/domain/monitoring/serviceModel";
import type { ActiveService } from "@/types/monitoring";

const target = { inputs: [
  { stream: { id: "a", label: "Current", unit: "A" }, binding: { policy: { mode: "original" } } },
  { stream: { id: "b", label: "Backup current", unit: "A" }, binding: { policy: { mode: "original" } } },
  { stream: { id: "off", label: "Off", unit: "A" }, binding: { policy: { mode: "off" } } },
] } as MonitoringTarget;
describe("reading selection", () => {
  it("suggests exact labels but leaves ambiguous readings to the user", () => {
    expect(suggestBindings([{ id: "one", label: "Current", unit: "A" }, { id: "two", label: "Other", unit: "A" }], target))
      .toEqual({ one: "a", two: "b" });
    expect(suggestBindings([{ id: "one", label: "Other", unit: "A" }], target)).toEqual({});
  });
  it("rejects missing, duplicate, incompatible, disabled and already monitored readings", () => {
    const slots = [{ id: "one", label: "Current", unit: "A" }, { id: "two", label: "Backup current", unit: "A" }];
    expect(bindingsReady(slots, target, { one: "a", two: "b" }, () => false)).toBe(true);
    const invalid: Record<string, string>[] = [{}, { one: "a", two: "a" }, { one: "a", two: "off" }];
    for (const bindings of invalid)
      expect(bindingsReady(slots, target, bindings, () => false)).toBe(false);
    expect(bindingsReady(slots, target, { one: "a", two: "b" }, (id) => id === "b")).toBe(false);
    expect(bindingsReady([{ id: "one", label: "Voltage", unit: "V" }], target, { one: "a" }, () => false)).toBe(false);
  });
});

describe("replacement setup", () => {
  const predecessor = (bindings: { slot_id: string; reading_id: string; entity_id: string }[]) =>
    ({ run: { execution: { bindings } } }) as unknown as PipelineServiceView;
  const targets = [
    { id: "north", label: "North", inputs: [{ stream: { id: "a" } }] },
    { id: "south", label: "South", inputs: [{ stream: { id: "b" } }] },
  ] as unknown as MonitoringTarget[];

  it("reads the predecessor's bindings and starting target", () => {
    const old = predecessor([{ slot_id: "value", reading_id: "b", entity_id: "south" }]);
    expect(previousBindings(old)).toEqual({ value: "b" });
    expect(previousBindings(undefined)).toEqual({});
    expect(predecessorEntity(old)).toBe("south");
    expect(predecessorTarget(targets, old)).toBe("south");
    expect(predecessorTarget(targets, undefined)).toBeUndefined();
  });

  it("follows a reading that moved entity since the predecessor ran", () => {
    // The run recorded north, but reading a now belongs to south.
    const moved = predecessor([{ slot_id: "value", reading_id: "a", entity_id: "north" }]);
    const now = [{ ...targets[1]!, inputs: [{ stream: { id: "a" } }] }] as unknown as MonitoringTarget[];
    expect(predecessorEntity(moved)).toBe("north");
    expect(predecessorTarget(now, moved)).toBe("south");
  });

  it("counts only other active services as owners", () => {
    const services = [{ id: "old", status: true }, { id: "stopped", status: false }, { id: "other", status: true }] as ActiveService[];
    const byStream = new Map([["a", new Set(["old"])], ["b", new Set(["stopped"])], ["c", new Set(["other"])]]);
    const owned = readingOwnedElsewhere(services, byStream, "old");
    expect(["a", "b", "c", "d"].map(owned)).toEqual([false, false, true, false]);
  });
});

