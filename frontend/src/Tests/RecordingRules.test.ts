import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiUtils } from "@/lib/api-client";
import type { CollectionRule, RuleChange, RuleEdit, RuleScope } from "@/features/catalogue/collectionRules";
import { scopeKey } from "@/features/catalogue/collectionRules";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import type { SystemCollectionPreview, SystemSnapshot } from "@/features/catalogue/systemTypes";
import { useRecordingRules } from "@/features/catalogue/useRecordingRules";

vi.mock("@/lib/api-client", () => ({ apiUtils: { post: vi.fn() } }));

const broker: RuleScope = { kind: "broker", connection_id: "broker" };
const power: RuleScope = { kind: "reading", connection_id: "broker", reading_id: "power" };
const original: CollectionRule = {
  scope: broker, policy: { mode: "original", interval_seconds: 10 }, include_future_readings: false, admitted_before: 1,
};
const sample: RuleEdit = { scope: broker, operation: "set", policy: { mode: "sample", interval_seconds: 60 } };

function fixture(): SystemSnapshot {
  const streams = ["temperature", "power", "other"].map(id => ({
    id, label: id, connection_id: id === "other" ? "other-broker" : "broker", topic: `room/${id}`,
    value_type: "number" as const, category: "Environment",
  }));
  return {
    document: { ...createEmptySystem(), streams, connections: ["broker", "other-broker"].map(id => ({
      id, label: id, host: "localhost", port: 1883, protocol: "mqtt" as const, transport: "tcp" as const, tls: false,
    })) }, revision: 3, can_edit: true, storage_origin: "saved",
    runtime: {
      mode: "configured_only", message: "", collection_revision: 4, collection_rules: [original],
      bindings: Object.fromEntries(streams.map(stream => [stream.id, {
        connection_id: stream.connection_id, entity_id: "entity", telemetry_key: stream.id,
        accepted_topic: `telemetry/entity/${stream.id}`,
        policy: { mode: stream.id === "temperature" ? "original" : "off", interval_seconds: 10 },
        policy_origin: { scope: broker, inherited: true, needs_review: stream.id !== "temperature" },
      }])),
    },
  };
}

function preview(snapshot: SystemSnapshot): SystemCollectionPreview {
  return {
    revision: snapshot.revision, collection_revision: snapshot.runtime.collection_revision ?? 0,
    selected_readings: 2, sampled_rows_per_day_ceiling: 2880, original_rate_readings: 0,
    affected_monitors: [], starting_readings: 1, stopping_readings: 0, rate_changed_readings: 1,
    bindings: snapshot.runtime.bindings, rules: snapshot.runtime.collection_rules,
  };
}

function lastChange(): RuleChange {
  return vi.mocked(apiUtils.post).mock.lastCall![1] as RuleChange;
}

beforeEach(() => { vi.clearAllMocks(); });
afterEach(cleanup);

describe("recording rule composition", () => {
  it.each(["policy first", "include first"])("preserves policy and admission through Apply and Undo: %s", async order => {
    const before = fixture();
    const after: SystemSnapshot = { ...before, revision: 4, runtime: {
      ...before.runtime, collection_revision: 5,
      collection_rules: [
        { ...original, policy: sample.policy },
        { scope: power, policy: null, include_future_readings: false, admitted_before: 0 },
      ],
      bindings: Object.fromEntries(Object.entries(before.runtime.bindings!).map(([id, binding]) => [id,
        id === "other" ? binding : { ...binding, policy: sample.policy,
          policy_origin: { scope: broker, inherited: true, needs_review: false } },
      ])),
    } };
    vi.mocked(apiUtils.post).mockResolvedValue(preview(before));
    const applyRules = vi.fn().mockResolvedValue(after);
    const hook = renderHook(({ snapshot }) => useRecordingRules(snapshot, "broker", applyRules), {
      initialProps: { snapshot: before },
    });
    const setPolicy = () => act(() => hook.result.current.edit(sample));
    const include = () => act(() => hook.result.current.includeReadings(["power"]));
    if (order === "policy first") setPolicy(); else include();
    await waitFor(() => expect(hook.result.current.preview).toBeDefined());
    if (order === "policy first") include(); else setPolicy();
    await waitFor(() => expect(hook.result.current.preview).toBeDefined());

    expect(lastChange().rule_changes).toEqual(expect.arrayContaining([
      sample, { scope: power, operation: "inherit" },
    ]));
    expect(new Set(lastChange().rule_changes.map(edit => scopeKey(edit.scope))).size).toBe(2);
    expect(lastChange().rule_changes).toHaveLength(2);
    expect(hook.result.current.ownRule(broker)?.policy).toEqual(sample.policy);
    expect(hook.result.current.pendingReadingIds(["power"])).toEqual([]);
    await act(async () => { expect(await hook.result.current.apply()).toBe(true); });
    expect(applyRules).toHaveBeenCalledWith({ ...lastChange(), pause_affected_monitors: false });
    hook.rerender({ snapshot: after });
    expect(hook.result.current.dirty).toBe(false);

    act(() => hook.result.current.stageUndo());
    await waitFor(() => expect(hook.result.current.preview).toBeDefined());
    expect(lastChange()).toMatchObject({ expected_revision: 4, expected_collection_revision: 5 });
    expect(lastChange().rule_changes).toEqual(expect.arrayContaining([
      { scope: broker, operation: "restore", restore_rule: original },
      { scope: power, operation: "restore", restore_rule: null },
    ]));
    expect(lastChange().rule_changes).toHaveLength(2);
    applyRules.mockResolvedValue(before);
    await act(async () => { expect(await hook.result.current.apply()).toBe(true); });
    expect(applyRules).toHaveBeenLastCalledWith({ ...lastChange(), pause_affected_monitors: false });
  });

  it("includes each excluded reading once and stays within the current broker", async () => {
    const snapshot = fixture();
    vi.mocked(apiUtils.post).mockResolvedValue(preview(snapshot));
    const hook = renderHook(() => useRecordingRules(snapshot, "broker", vi.fn()));
    const ids = ["power", "power", "temperature", "other", "missing"];
    expect(hook.result.current.pendingReadingIds(ids)).toEqual(["power"]);
    act(() => hook.result.current.includeReadings(ids));
    await waitFor(() => expect(hook.result.current.preview).toBeDefined());
    act(() => hook.result.current.includeReadings(ids));
    expect(lastChange().rule_changes).toEqual([{ scope: power, operation: "inherit" }]);
    expect(hook.result.current.pendingReadingIds(ids)).toEqual([]);
  });

  it.each<RuleEdit>([
    { scope: power, operation: "set", policy: { mode: "off", interval_seconds: 10 } },
    { scope: power, operation: "restore", restore_rule: null },
  ])("preserves a staged reading exception or restoration: $operation", async edit => {
    const snapshot = fixture();
    vi.mocked(apiUtils.post).mockResolvedValue(preview(snapshot));
    const hook = renderHook(() => useRecordingRules(snapshot, "broker", vi.fn()));
    act(() => {
      hook.result.current.edit(edit);
      hook.result.current.includeReadings(["power"]);
    });
    await waitFor(() => expect(hook.result.current.preview).toBeDefined());
    expect(lastChange().rule_changes).toEqual([edit]);
    expect(hook.result.current.pendingReadingIds(["power"])).toEqual([]);
  });

  it("uses reviewed admission status instead of the saved status after a parent change", async () => {
    const snapshot = fixture();
    const reviewed = preview(snapshot);
    reviewed.bindings = { power: {
      policy: sample.policy, policy_origin: { scope: broker, inherited: true, needs_review: false },
    } };
    vi.mocked(apiUtils.post).mockResolvedValue(reviewed);
    const hook = renderHook(() => useRecordingRules(snapshot, "broker", vi.fn()));
    const change = { ...sample, include_future_readings: true };
    act(() => hook.result.current.edit(change));
    await waitFor(() => expect(hook.result.current.preview).toBeDefined());
    expect(hook.result.current.pendingReadingIds(["power"])).toEqual([]);
    act(() => hook.result.current.includeReadings(["power"]));
    expect(lastChange().rule_changes).toEqual([change]);
  });
});
