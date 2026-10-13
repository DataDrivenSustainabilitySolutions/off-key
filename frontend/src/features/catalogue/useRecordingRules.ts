import { useEffect, useMemo, useState } from "react";
import { apiUtils } from "@/lib/api-client";
import type { CollectionRule, RuleChange, RuleEdit, RuleScope } from "./collectionRules";
import { scopeKey } from "./collectionRules";
import type { SystemCollectionPreview, SystemSnapshot } from "./systemTypes";

type Draft = { broker: string; baseline: SystemSnapshot; edits: RuleEdit[] };
type Undo = { broker: string; previous: CollectionRule[]; acknowledged: SystemSnapshot };

export function useRecordingRules(snapshot: SystemSnapshot | null, broker: string | undefined,
  applyRules: (change: RuleChange) => Promise<SystemSnapshot | undefined>) {
  const [draft, setDraft] = useState<Draft>();
  const [review, setReview] = useState<{ key: string; preview: SystemCollectionPreview }>();
  const [problem, setProblem] = useState("");
  const [undo, setUndo] = useState<Undo>();
  const [saving, setSaving] = useState(false);
  const current = draft?.broker === broker ? draft : undefined;
  const dirty = !!current?.edits.length;
  const baseline = current?.baseline ?? snapshot;
  const request = useMemo<RuleChange | undefined>(() => dirty && baseline ? {
    expected_revision: baseline.revision,
    expected_collection_revision: baseline.runtime.collection_revision ?? 0,
    rule_changes: current!.edits,
  } : undefined, [dirty, baseline, current]);
  const requestKey = JSON.stringify(request ?? null);
  const preview = review?.key === requestKey ? review.preview : undefined;
  const rules = preview?.rules ?? baseline?.runtime.collection_rules ?? [];

  useEffect(() => {
    if (!request) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void apiUtils.post<SystemCollectionPreview>("/v1/system/collection/preview", JSON.parse(requestKey),
        { signal: controller.signal, redirectOnUnauthorized: false }).then(value => {
          if (!controller.signal.aborted) { setReview({ key: requestKey, preview: value }); setProblem(""); }
        }, error => {
          if (!controller.signal.aborted) { setReview(undefined); setProblem(error instanceof Error ? error.message : "Recording changes could not be reviewed."); }
        });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [requestKey, request]);

  const edit = (change: RuleEdit) => {
    if (!snapshot || !broker) return;
    setProblem("");
    setDraft(previous => {
      const active = previous?.broker === broker ? previous : { broker, baseline: snapshot, edits: [] };
      const edits = active.edits.filter(item => scopeKey(item.scope) !== scopeKey(change.scope));
      edits.push(change);
      return { ...active, edits };
    });
  };
  const ownRule = (scope: RuleScope) => {
    const change = current?.edits.find(item => scopeKey(item.scope) === scopeKey(scope));
    if (change?.operation === "set") return { scope, policy: change.policy!, include_future_readings: change.include_future_readings ?? false, admitted_before: 0 };
    if (change?.operation === "inherit") return undefined;
    return rules.find(rule => scopeKey(rule.scope) === scopeKey(scope));
  };
  const apply = async (pause = false) => {
    if (!request || !preview || saving) return false;
    setSaving(true);
    try {
      const acknowledged = await applyRules({ ...request, pause_affected_monitors: pause });
      if (!acknowledged) { setProblem("The changes were not saved. Your draft is still available."); return false; }
      setUndo({ broker: broker!, previous: baseline!.runtime.collection_rules ?? [], acknowledged });
      setDraft(undefined); setReview(undefined); setProblem("");
      return true;
    } finally { setSaving(false); }
  };
  const stageUndo = () => {
    if (!undo || !snapshot || undo.broker !== broker) return;
    if (snapshot.revision !== undo.acknowledged.revision || snapshot.runtime.collection_revision !== undo.acknowledged.runtime.collection_revision) {
      setProblem("The configuration changed after this save. Reload before restoring previous settings."); return;
    }
    const before = new Map(undo.previous.filter(rule => rule.scope.connection_id === broker).map(rule => [scopeKey(rule.scope), rule]));
    const after = new Map((snapshot.runtime.collection_rules ?? []).filter(rule => rule.scope.connection_id === broker).map(rule => [scopeKey(rule.scope), rule]));
    const edits: RuleEdit[] = [];
    for (const key of new Set([...before.keys(), ...after.keys()])) {
      if (JSON.stringify(before.get(key)) === JSON.stringify(after.get(key))) continue;
      edits.push({ scope: (before.get(key) ?? after.get(key))!.scope, operation: "restore", restore_rule: before.get(key) ?? null });
    }
    if (edits.length) { setDraft({ broker: broker!, baseline: snapshot, edits }); setUndo(undefined); }
  };
  return { dirty, preview, reviewing: dirty && !preview, problem, saving, edit, ownRule, apply,
    canUndo: undo?.broker === broker && !dirty, stageUndo,
    discard: () => { setDraft(undefined); setProblem(""); setReview(undefined); },
    rebase: () => { if (snapshot && current) { setDraft({ ...current, baseline: snapshot }); setProblem(""); } },
  };
}
