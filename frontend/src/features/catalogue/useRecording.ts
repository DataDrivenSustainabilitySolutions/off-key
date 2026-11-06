import { useState } from "react";
import { systemApi } from "@/domain/system/systemApi";
import type { CollectionRule, RuleChange, RuleEdit } from "@/domain/system/collectionRules";
import { scopeKey } from "@/domain/system/collectionRules";
import type { SystemSnapshot } from "@/types/system";

type Pending = { edits: RuleEdit[]; monitors: { id: string; name?: string }[] };
type Undo = { broker: string; previous: CollectionRule[]; saved: SystemSnapshot };

/** Recording changes save as soon as they are chosen. Only stopping running monitors asks first. */
export function useRecording(snapshot: SystemSnapshot | null,
  applyRules: (change: RuleChange) => Promise<SystemSnapshot | undefined>) {
  const [saving, setSaving] = useState<string>();
  const [pending, setPending] = useState<Pending>();
  const [problem, setProblem] = useState("");
  const [undo, setUndo] = useState<Undo>();

  const save = async (edits: RuleEdit[], pause = false): Promise<boolean> => {
    if (!snapshot || saving || !edits.length) return false;
    const broker = edits[0]!.scope.broker_id;
    const change: RuleChange = {
      expected_revision: snapshot.revision,
      expected_collection_revision: snapshot.runtime.collection_revision ?? 0,
      rule_changes: edits,
    };
    setSaving(broker);
    setProblem("");
    try {
      if (!pause) {
        const preview = await systemApi.previewCollection(change, { redirectOnUnauthorized: false });
        if (preview.affected_monitors.length) {
          setPending({ edits, monitors: preview.affected_monitors });
          return false;
        }
      }
      setPending(undefined);
      const saved = await applyRules({ ...change, pause_affected_monitors: pause });
      if (!saved) { setProblem("The recording change was not saved."); return false; }
      setUndo({ broker, previous: snapshot.runtime.collection_rules ?? [], saved });
      return true;
    } catch (error) {
      setProblem(error instanceof Error && error.message ? error.message : "The recording change was not saved.");
      return false;
    } finally {
      setSaving(undefined);
    }
  };

  /** Restore the broker's rules as they were before the last change made here. */
  const restore = () => {
    if (!undo || !snapshot) return;
    if (snapshot.revision !== undo.saved.revision || snapshot.runtime.collection_revision !== undo.saved.runtime.collection_revision) {
      setUndo(undefined);
      setProblem("The configuration changed since then, so the last change can no longer be undone.");
      return;
    }
    const mine = (rules: CollectionRule[]) => new Map(rules.filter(rule => rule.scope.broker_id === undo.broker)
      .map(rule => [scopeKey(rule.scope), rule]));
    const before = mine(undo.previous);
    const after = mine(snapshot.runtime.collection_rules ?? []);
    const edits: RuleEdit[] = [];
    for (const key of new Set([...before.keys(), ...after.keys()])) {
      if (JSON.stringify(before.get(key)) === JSON.stringify(after.get(key))) continue;
      edits.push({ scope: (before.get(key) ?? after.get(key))!.scope, operation: "restore", restore_rule: before.get(key) ?? null });
    }
    setUndo(undefined);
    void save(edits);
  };

  return {
    saving, pending, problem, save,
    confirm: () => pending && void save(pending.edits, true),
    cancel: () => setPending(undefined),
    canUndo: (broker?: string) => !!broker && undo?.broker === broker && !saving,
    undo: restore,
  };
}

export type Recording = ReturnType<typeof useRecording>;
