import type { RuleChange } from "./collectionRules";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  apiClient,
  apiUtils,
  type ApiRequestOptions,
} from "@/lib/api-client";
import { renameSystemEntity, validateSystemDocument } from "./systemDocument";
import type {
  SystemDocument,
  SystemEntityKind,
  SystemSnapshot,
  SystemCollectionChange,
} from "./systemTypes";

export const SYSTEM_ENDPOINT = "/v1/system";
export type SystemDocumentStatus =
  "loading" | "ready" | "read-only" | "sign-in-required" | "unavailable";
type Options = {
  isAuthenticated: boolean;
  accountKey?: number | string | null;
  onDocument?: (document: SystemDocument) => void;
  runtimeConnectionId?: string;
};
type State = {
  owner: string;
  status: SystemDocumentStatus;
  snapshot: SystemSnapshot | null;
  error: string;
};
const messageFor = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "The configuration could not be saved.";

function validateSnapshot(value: SystemSnapshot): SystemSnapshot {
  if (
    !value ||
    !Number.isSafeInteger(value.revision) ||
    value.revision < 0 ||
    typeof value.can_edit !== "boolean" ||
    !["saved", "empty"].includes(value.storage_origin) ||
    !["configured_only", "collection"].includes(value.runtime?.mode)
  )
    throw new Error("The backend returned an invalid system snapshot.");
  return { ...value, document: validateSystemDocument(value.document) };
}

/** Database acknowledgement is the only source of saved configuration. */
export function useSystemDocument({
  isAuthenticated,
  accountKey,
  onDocument,
  runtimeConnectionId,
}: Options) {
  const owner = JSON.stringify([isAuthenticated, accountKey ?? null]);
  const [state, setState] = useState<State>(() => ({
    owner,
    status: isAuthenticated ? "loading" : "sign-in-required",
    snapshot: null,
    error: "",
  }));
  const [saving, setSaving] = useState(false);
  const generation = useRef(0);
  const readSequence = useRef(0);
  const latest = useRef<SystemSnapshot | null>(null);
  const permission = useRef(false);
  const busy = useRef(false);
  const readController = useRef<AbortController | undefined>(undefined);
  const saveController = useRef<AbortController | undefined>(undefined);
  const runtimeController = useRef<AbortController | undefined>(undefined);
  const callback = useRef(onDocument);

  useEffect(() => {
    callback.current = onDocument;
  }, [onDocument]);

  const accept = useCallback(
    (
      input: SystemSnapshot,
      context: number,
      fromSave = false,
    ): SystemDocument | undefined => {
      if (context !== generation.current) return undefined;
      const snapshot = validateSnapshot(input);
      const canEdit = snapshot.can_edit && (!fromSave || permission.current);
      permission.current = canEdit;
      if (latest.current && snapshot.revision < latest.current.revision) {
        const canonical = { ...latest.current, can_edit: canEdit };
        latest.current = canonical;
        setState({
          owner,
          snapshot: canonical,
          status: canEdit ? "ready" : "read-only",
          error: "",
        });
        return canonical.document;
      }
      const canonical = { ...snapshot, document: latest.current?.revision === snapshot.revision ? latest.current.document : snapshot.document, can_edit: canEdit };
      latest.current = canonical;
      setState({
        owner,
        snapshot: canonical,
        status: canEdit ? "ready" : "read-only",
        error: "",
      });
      callback.current?.(canonical.document);
      return canonical.document;
    },
    [owner],
  );

  const refresh = useCallback(async (): Promise<SystemDocument | undefined> => {
    if (!isAuthenticated) return undefined;
    runtimeController.current?.abort();
    runtimeController.current = undefined;
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    const context = generation.current;
    const sequence = ++readSequence.current;
    permission.current = false;
    setState((current) => ({
      ...current,
      owner,
      status: "loading",
      error: "",
    }));
    try {
      const snapshot = await apiUtils.get<SystemSnapshot>(SYSTEM_ENDPOINT, {
        signal: controller.signal,
        redirectOnUnauthorized: false,
      });
      if (
        controller.signal.aborted ||
        context !== generation.current ||
        sequence !== readSequence.current
      )
        return undefined;
      return accept(snapshot, context);
    } catch (error) {
      if (
        controller.signal.aborted ||
        context !== generation.current ||
        sequence !== readSequence.current
      )
        return undefined;
      permission.current = false;
      const unauthorized =
        error instanceof ApiRequestError && error.status === 401;
      setState((current) => ({
        ...current,
        owner,
        status: unauthorized ? "sign-in-required" : "unavailable",
        error: messageFor(error),
      }));
      return undefined;
    }
  }, [accept, isAuthenticated, owner]);

  const refreshRuntime = useCallback(async () => {
    if (!isAuthenticated || busy.current) return;
    runtimeController.current?.abort();
    const controller = new AbortController();
    runtimeController.current = controller;
    const context = generation.current;
    try {
      const snapshot = await apiUtils.get<SystemSnapshot>(SYSTEM_ENDPOINT, { signal: controller.signal, redirectOnUnauthorized: false });
      if (!controller.signal.aborted && context === generation.current && !busy.current) accept(snapshot, context);
    } catch { /* Keep the last acknowledged state; the controls can retry. */ }
    finally { if (runtimeController.current === controller) runtimeController.current = undefined; }
  }, [accept, isAuthenticated]);

  const updateRuntime = useCallback((value: { revision: number; runtime: SystemSnapshot["runtime"] }, connectionId?: string) => {
    const current = latest.current;
    if (!current || value.revision !== current.revision || busy.current
      || (value.runtime.collection_revision ?? 0) < (current.runtime.collection_revision ?? 0)) return;
    const sources = { ...current.runtime.ingress?.sources };
    if (connectionId) delete sources[connectionId];
    const runtime = { ...current.runtime, ...value.runtime,
      bindings: { ...current.runtime.bindings, ...value.runtime.bindings },
      latest_readings: { ...current.runtime.latest_readings, ...value.runtime.latest_readings },
      ingress: connectionId ? { ...value.runtime.ingress, sources: { ...sources, ...value.runtime.ingress?.sources } } : value.runtime.ingress,
    };
    const snapshot = { ...current, runtime };
    latest.current = snapshot;
    setState((previous) => ({ ...previous, snapshot }));
  }, []);

  useEffect(() => {
    const context = ++generation.current;
    latest.current = null;
    permission.current = false;
    busy.current = false;
    setSaving(false);
    setState({
      owner,
      snapshot: null,
      status: isAuthenticated ? "loading" : "sign-in-required",
      error: "",
    });
    if (isAuthenticated) void refresh();
    return () => {
      generation.current = context + 1;
      readController.current?.abort();
      saveController.current?.abort();
      runtimeController.current?.abort();
      runtimeController.current = undefined;
    };
  }, [isAuthenticated, owner, refresh]);

  const runtimeReady = state.owner === owner && (state.status === "ready" || state.status === "read-only");
  const pollInterval = state.snapshot?.runtime.collection?.status === "applying" ? 2000 : 5000;
  useEffect(() => {
    if (!runtimeReady) return;
    const context = generation.current;
    const poll = async () => {
      const current = latest.current;
      if (!current || document.hidden || busy.current || runtimeController.current) return;
      const controller = new AbortController();
      runtimeController.current = controller;
      let changedRevision = false;
      const streamIds = current.document.streams.filter(stream => !runtimeConnectionId || stream.connection_id === runtimeConnectionId).map(stream => stream.id);
      try {
        const next = await apiUtils.post<{ revision: number; runtime: SystemSnapshot["runtime"] }>(`${SYSTEM_ENDPOINT}/collection/status`,
          { stream_ids: streamIds }, { signal: controller.signal, redirectOnUnauthorized: false });
        if (controller.signal.aborted || context !== generation.current || busy.current) return;
        changedRevision = next.revision !== latest.current?.revision;
        if (!changedRevision) updateRuntime(next, runtimeConnectionId);
      } catch { /* Keep acknowledged settings through an outage. */ }
      finally { if (runtimeController.current === controller) runtimeController.current = undefined; }
      if (changedRevision) await refreshRuntime();
    };
    let timer: ReturnType<typeof setInterval> | undefined;
    const pause = () => {
      clearInterval(timer);
      timer = undefined;
      runtimeController.current?.abort();
      runtimeController.current = undefined;
    };
    const resume = () => {
      if (document.hidden) { pause(); return; }
      timer ??= setInterval(() => void poll(), pollInterval);
      void poll();
    };
    // The initial catalogue read already supplies runtime; poll immediately only on resume.
    if (!document.hidden) timer = setInterval(() => void poll(), pollInterval);
    document.addEventListener("visibilitychange", resume);
    return () => { pause(); document.removeEventListener("visibilitychange", resume); };
  }, [runtimeReady, runtimeConnectionId, pollInterval, owner, refreshRuntime, updateRuntime]);

  const save = useCallback(
    async (
      proposed: SystemDocument,
      expectedRevision?: number,
    ): Promise<boolean> => {
      const current = latest.current;
      const setError = (error: string) =>
        setState((previous) => ({ ...previous, error }));
      if (busy.current) {
        setError(
          "Another configuration change is being saved. Wait for it to finish.",
        );
        return false;
      }
      if (!isAuthenticated || !current || !permission.current) {
        setError(
          "Sign in as an administrator and load the saved system before making changes.",
        );
        return false;
      }
      const revision = expectedRevision ?? current.revision;
      if (revision !== current.revision) {
        setError(
          "The saved system changed. Review or reload your draft before saving again.",
        );
        return false;
      }
      let document: SystemDocument;
      try {
        document = validateSystemDocument(proposed);
      } catch (error) {
        setError(messageFor(error));
        return false;
      }
      busy.current = true;
      runtimeController.current?.abort();
      runtimeController.current = undefined;
      setSaving(true);
      setError("");
      const context = generation.current;
      const controller = new AbortController();
      saveController.current = controller;
      const options: ApiRequestOptions = {
        signal: controller.signal,
        redirectOnUnauthorized: false,
      };
      try {
        const response = await apiClient.put<SystemSnapshot>(
          SYSTEM_ENDPOINT,
          { expected_revision: revision, document },
          options,
        );
        if (controller.signal.aborted || context !== generation.current)
          return false;
        return !!accept(response.data, context, true);
      } catch (error) {
        if (controller.signal.aborted || context !== generation.current)
          return false;
        if (error instanceof ApiRequestError && error.status === 409) {
          await refresh();
          if (context === generation.current)
            setError(
              "The saved system changed. Your draft has not been saved; review the current configuration or reload your draft before trying again.",
            );
        } else {
          const denied =
            error instanceof ApiRequestError &&
            (error.status === 401 || error.status === 403);
          if (denied) {
            permission.current = false;
            setState((previous) => ({
              ...previous,
              status: error.status === 401 ? "sign-in-required" : "read-only",
              snapshot: previous.snapshot
                ? { ...previous.snapshot, can_edit: false }
                : null,
              error: messageFor(error),
            }));
          } else setError(messageFor(error));
        }
        return false;
      } finally {
        if (context === generation.current) {
          busy.current = false;
          setSaving(false);
        }
      }
    },
    [accept, isAuthenticated, refresh],
  );

  const rename = useCallback(
    async (
      kind: SystemEntityKind,
      id: string,
      label: string,
    ): Promise<boolean> => {
      const canonical = latest.current;
      if (!canonical) return false;
      try {
        return await save(
          renameSystemEntity(canonical.document, kind, id, label),
          canonical.revision,
        );
      } catch (error) {
        setState((previous) => ({ ...previous, error: messageFor(error) }));
        return false;
      }
    },
    [save],
  );

  const applyCollection = useCallback(async (change: SystemCollectionChange | RuleChange): Promise<boolean> => {
    if (busy.current || !permission.current || !latest.current) return false;
    busy.current = true;
    runtimeController.current?.abort();
    runtimeController.current = undefined;
    setSaving(true);
    const context = generation.current;
    const controller = new AbortController();
    saveController.current = controller;
    try {
      const options: ApiRequestOptions = { signal: controller.signal, redirectOnUnauthorized: false };
      const response = await apiClient.put<SystemSnapshot>(`${SYSTEM_ENDPOINT}/collection`, change,
        options);
      return !controller.signal.aborted && !!accept(response.data, context, true);
    } catch (error) {
      if (!controller.signal.aborted && context === generation.current) {
        if (error instanceof ApiRequestError && error.status === 409) await refresh();
        setState((previous) => ({ ...previous, error: messageFor(error) }));
      }
      return false;
    } finally {
      if (context === generation.current) { busy.current = false; setSaving(false); }
    }
  }, [accept, refresh]);

  // Do not expose the previous account's configuration while effects catch up.
  const visible =
    state.owner === owner
      ? state
      : {
          owner,
          snapshot: null,
          status: isAuthenticated
            ? ("loading" as const)
            : ("sign-in-required" as const),
          error: "",
        };
  return {
    document: visible.snapshot?.document ?? null,
    snapshot: visible.snapshot,
    revision: visible.snapshot?.revision ?? null,
    status: visible.status,
    error: visible.error,
    saving: state.owner === owner && saving,
    canEdit:
      isAuthenticated &&
      visible.status === "ready" &&
      visible.snapshot?.can_edit === true,
    refresh,
    refreshRuntime,
    updateRuntime,
    save,
    rename,
    applyCollection,
    applyRules: async (change: RuleChange) => await applyCollection(change) ? latest.current ?? undefined : undefined,
  };
}
