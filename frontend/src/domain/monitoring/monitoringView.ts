/**
 * The monitoring workspace's URL contract. Every view transition lives here so
 * the keys one screen clears cannot drift from the keys another screen reads.
 * Each builder returns a new URLSearchParams and leaves its input untouched.
 */

/** Keys that describe the open view; a reset clears them all. */
const VIEW_KEYS = ["entity", "reading", "broker", "topic", "service", "create", "target", "tab", "stream",
  "inspect", "pipeline", "view", "revision", "activation", "replace", "from"] as const;

/** Remembered monitoring URL, restored when navigating back to the workspace. */
export const monitoringNavigationKey = (userId: string | number | null | undefined) => `monitoring:${userId}:url`;

const edit = (params: URLSearchParams, change: (next: URLSearchParams) => void) => {
  const next = new URLSearchParams(params);
  change(next);
  return next;
};
const drop = (next: URLSearchParams, keys: readonly string[]) => keys.forEach(key => next.delete(key));

/** Clear the open view, keep the catalogue selection, then apply `view`. */
export const resetView = (params: URLSearchParams, sourceKey?: string, view?: Record<string, string | undefined>) =>
  edit(params, next => {
    drop(next, VIEW_KEYS);
    if (sourceKey) next.set("source", sourceKey);
    Object.entries(view ?? {}).forEach(([key, value]) => { if (value) next.set(key, value); });
  });

/** Open a pipeline; from the template library this leaves service creation. */
export const openPipeline = (params: URLSearchParams, pipelineId: string, targetId?: string) =>
  edit(params, next => {
    next.set("pipeline", pipelineId);
    if (params.get("view") === "pipelines") next.delete("create");
    if (targetId) next.set("target", targetId);
    drop(next, ["revision", "activation", "view"]);
  });

export const createPipeline = (params: URLSearchParams) =>
  edit(params, next => {
    drop(next, ["pipeline", "revision", "activation", "view", "replace", "from"]);
    next.set("create", "monitoring");
  });

/** The template library keeps `from` and `create` so setup can resume. */
export const showLibrary = (params: URLSearchParams) =>
  edit(params, next => {
    drop(next, ["pipeline", "revision", "activation", "replace"]);
    next.set("view", "pipelines");
  });

export const setRevision = (params: URLSearchParams, revision?: string) =>
  edit(params, next => {
    if (revision) next.set("revision", revision);
    else next.delete("revision");
    next.delete("activation");
  });

export const setActivation = (params: URLSearchParams, activation: string) =>
  edit(params, next => next.set("activation", activation));

export const dropReplacement = (params: URLSearchParams) => edit(params, next => next.delete("replace"));

/** Edit a running service as a replacement, or as a copy when it cannot be replaced. */
export const editFromRun = (params: URLSearchParams, serviceId: string, replaceable: boolean) =>
  edit(params, next => {
    drop(next, ["service", "tab", "pipeline", "revision", "activation"]);
    next.set("create", "monitoring");
    next.set(replaceable ? "replace" : "from", serviceId);
  });

/** Evidence keeps its stream; other tabs only keep one they are given. */
export const chooseTab = (params: URLSearchParams, tab: string, streamId?: string) =>
  edit(params, next => {
    next.set("tab", tab);
    if (streamId) next.set("stream", streamId);
    else if (tab !== "evidence") next.delete("stream");
  });
