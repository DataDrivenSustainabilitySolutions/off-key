import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { apiUtils } from "@/lib/api-client";
import type { CollectionRule, RuleChange, RuleEdit, RuleScope } from "@/domain/system/collectionRules";
import { createEmptySystem } from "@/domain/system/systemDocument";
import type { SystemCollectionPreview, SystemSnapshot } from "@/types/system";
import { useRecording } from "@/features/catalogue/useRecording";
import { recordingEdit, startRecording, stopRecording } from "@/features/catalogue/recordingEdits";
import { mqttConnection } from "./support/fixtures/system";

vi.mock("@/lib/api-client", () => ({ apiUtils: { post: vi.fn() } }));

const broker: RuleScope = { kind: "broker", broker_id: "broker" };
const power: RuleScope = { kind: "reading", broker_id: "broker", reading_id: "power" };
const original: CollectionRule = {
  scope: broker, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: true, admitted_before: 1,
};
const sample: RuleEdit = { scope: broker, operation: "set", policy: { mode: "sample", interval_seconds: 60 }, include_future_readings: true };

function fixture(rules: CollectionRule[] = [original]): SystemSnapshot {
  const streams = ["temperature", "power"].map(id => ({
    id, label: id, broker_id: "broker", topic: `room/${id}`, value_type: "number" as const, category: "Environment",
  }));
  return {
    document: { ...createEmptySystem(), readings: streams, brokers: [mqttConnection({ id: "broker", label: "broker", host: "localhost" })] },
    revision: 3, can_edit: true, storage_origin: "saved",
    runtime: { mode: "collection", message: "", collection_revision: 4, collection_rules: rules, bindings: {} },
  };
}

function preview(snapshot: SystemSnapshot, monitors: SystemCollectionPreview["affected_monitors"] = []): SystemCollectionPreview {
  return {
    revision: snapshot.revision, collection_revision: snapshot.runtime.collection_revision ?? 0,
    selected_readings: 2, sampled_rows_per_day_ceiling: 0, original_rate_readings: 2,
    affected_monitors: monitors, starting_readings: 0, stopping_readings: 0, rate_changed_readings: 2,
    bindings: {}, rules: snapshot.runtime.collection_rules,
  };
}

describe("recording changes", () => {
  it("saves a choice at once and undoes it by restoring the previous rules", async () => {
    const before = fixture();
    const after = { ...fixture([{ ...original, policy: sample.policy }]), revision: 4,
      runtime: { ...fixture().runtime, collection_revision: 5, collection_rules: [{ ...original, policy: sample.policy }] } };
    vi.mocked(apiUtils.post).mockResolvedValue(preview(before));
    const applyRules = vi.fn().mockResolvedValue(after);
    const hook = renderHook(({ snapshot }) => useRecording(snapshot, applyRules), { initialProps: { snapshot: before } });

    await act(async () => { expect(await hook.result.current.save([sample])).toBe(true); });
    expect(applyRules).toHaveBeenCalledWith({
      expected_revision: 3, expected_collection_revision: 4, rule_changes: [sample], pause_affected_monitors: false,
    });
    hook.rerender({ snapshot: after });
    expect(hook.result.current.canUndo("broker")).toBe(true);

    applyRules.mockResolvedValue(before);
    await act(async () => { hook.result.current.undo(); });
    expect(applyRules.mock.lastCall![0] as RuleChange).toMatchObject({
      expected_revision: 4, expected_collection_revision: 5,
      rule_changes: [{ scope: broker, operation: "restore", restore_rule: original }],
    });
  });

  it("asks once before stopping running monitors and saves only after confirmation", async () => {
    const snapshot = fixture();
    vi.mocked(apiUtils.post).mockResolvedValue(preview(snapshot, [{ id: "m1", name: "Pump" }]));
    const applyRules = vi.fn().mockResolvedValue(snapshot);
    const hook = renderHook(() => useRecording(snapshot, applyRules));

    await act(async () => { expect(await hook.result.current.save([sample])).toBe(false); });
    expect(applyRules).not.toHaveBeenCalled();
    expect(hook.result.current.pending?.monitors).toHaveLength(1);

    await act(async () => { hook.result.current.confirm(); });
    expect(applyRules).toHaveBeenCalledWith(expect.objectContaining({ rule_changes: [sample], pause_affected_monitors: true }));
    expect(hook.result.current.pending).toBeUndefined();
  });

  it("keeps the draft-free state when a save fails", async () => {
    const snapshot = fixture();
    vi.mocked(apiUtils.post).mockRejectedValue(new Error("The catalogue changed."));
    const applyRules = vi.fn();
    const hook = renderHook(() => useRecording(snapshot, applyRules));
    await act(async () => { expect(await hook.result.current.save([sample])).toBe(false); });
    expect(hook.result.current.problem).toBe("The catalogue changed.");
    expect(applyRules).not.toHaveBeenCalled();
  });
});

describe("recording edits", () => {
  it("records a broker including later readings and turns it off by dropping its rule", () => {
    expect(startRecording("broker")).toEqual([{ scope: broker, operation: "set",
      policy: { mode: "original", interval_seconds: 10 }, include_future_readings: true }]);
    expect(recordingEdit(broker, "off", 10)).toEqual({ scope: broker, operation: "inherit" });
    expect(recordingEdit(power, "sample", 30)).toEqual({ scope: power, operation: "set", policy: { mode: "sample", interval_seconds: 30 } });
    expect(recordingEdit(power, "off", 10)).toEqual({ scope: power, operation: "set", policy: { mode: "off", interval_seconds: 10 } });
  });

  it("stops a broker together with readings that record on their own", () => {
    const own: CollectionRule = { scope: power, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: false, admitted_before: 0 };
    const off: CollectionRule = { ...own, scope: { ...power, reading_id: "temperature" }, policy: { mode: "off", interval_seconds: 10 } };
    expect(stopRecording("broker", fixture([original, own, off]).runtime)).toEqual([
      { scope: broker, operation: "inherit" }, { scope: power, operation: "inherit" },
    ]);
  });
});
