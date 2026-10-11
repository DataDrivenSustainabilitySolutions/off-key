import { useCallback, useEffect, useRef, useState } from "react";
import { API_CONFIG } from "@/lib/api-config";
import { ApiRequestError, apiUtils } from "@/lib/api-client";
import type { CatalogSnapshot } from "@/types/collection";
import { parseSpatialCatalog, type SpatialCatalogProjection } from "./catalog";
import { applyCatalogNames, buildCatalogNameIndex, catalogNameKey, catalogNameTarget, type CatalogNameIndex, type CatalogNameTarget } from "./catalogNames";

export type CatalogNameStatus = "disabled" | "sign-in-required" | "loading" | "ready" | "read-only" | "unmatched" | "unavailable";
type NameState = { status: CatalogNameStatus; canEdit: boolean; revision: number | null; labels: CatalogNameIndex; error: string };
type Options = {
  projection: SpatialCatalogProjection | undefined;
  isAuthenticated: boolean;
  accountKey?: number | string | null;
  onCanonicalNames: (projection: SpatialCatalogProjection) => void;
};
type SavedNames = Omit<CatalogSnapshot, "can_edit"> & { can_edit?: boolean };

const idleState = (projection: SpatialCatalogProjection | undefined, authenticated: boolean): NameState => ({
  status: !projection ? "disabled" : authenticated ? "loading" : "sign-in-required",
  canEdit: false, revision: null, labels: new Map(), error: "",
});
const messageFor = (error: unknown): string => error instanceof Error ? error.message : "Catalog names could not be saved.";

/** Explicit account action; return a stripped presentation, never backend endpoints. */
export async function fetchSavedSpatialCatalog(signal?: AbortSignal): Promise<SpatialCatalogProjection> {
  const snapshot = await apiUtils.get<CatalogSnapshot>(API_CONFIG.ENDPOINTS.SOURCES.GET, { signal });
  return parseSpatialCatalog(JSON.stringify(snapshot.catalog));
}

/** Optional, authenticated DB-backed titles for the imported read-only presentation. */
export function useCatalogNames({ projection, isAuthenticated, accountKey, onCanonicalNames }: Options) {
  const [state, setState] = useState(() => idleState(projection, isAuthenticated));
  const [saving, setSaving] = useState(false);
  const currentProjection = useRef(projection);
  const canonicalCallback = useRef(onCanonicalNames);
  const context = useRef(0);
  const loadSequence = useRef(0);
  const latestRevision = useRef(-1);
  const currentPermission = useRef(false);
  const readController = useRef<AbortController | undefined>(undefined);
  const saveController = useRef<AbortController | undefined>(undefined);
  const busy = useRef(false);
  const datasetKey = projection?.datasetKey;

  useEffect(() => {
    currentProjection.current = projection;
    canonicalCallback.current = onCanonicalNames;
  }, [projection, onCanonicalNames]);

  const accept = useCallback((snapshot: SavedNames, canEdit: boolean, generation: number) => {
    if (context.current !== generation) return false;
    if (!Number.isSafeInteger(snapshot.revision) || snapshot.revision < 0 || snapshot.catalog?.provider !== "ambibox")
      throw new Error("The backend returned an invalid catalog snapshot.");
    currentPermission.current = canEdit;
    if (snapshot.revision < latestRevision.current) {
      // Permission comes from the current authenticated read independently of
      // catalog revision. Never roll back names when network responses overlap.
      setState((current) => {
        const known = currentProjection.current?.topology.nodes.some((node) => {
          const target = catalogNameTarget(node);
          return target && current.labels.has(catalogNameKey(target));
        });
        return { ...current, canEdit: !!known && canEdit, status: !known ? "unmatched" : canEdit ? "ready" : "read-only", error: "" };
      });
      return true;
    }
    const labels = buildCatalogNameIndex(snapshot.catalog);
    const current = currentProjection.current;
    if (!current || current.datasetKey !== datasetKey) return false;
    const matched = current.topology.nodes.some((node) => {
      const target = catalogNameTarget(node);
      return target && labels.has(catalogNameKey(target));
    });
    latestRevision.current = snapshot.revision;
    setState({ status: !matched ? "unmatched" : canEdit ? "ready" : "read-only", canEdit: matched && canEdit, revision: snapshot.revision, labels, error: "" });
    canonicalCallback.current(applyCatalogNames(current, labels));
    return true;
  }, [datasetKey]);

  const refresh = useCallback(async (): Promise<boolean> => {
    if (!datasetKey || !isAuthenticated) return false;
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    const generation = context.current;
    const sequence = ++loadSequence.current;
    setState((current) => ({ ...current, status: "loading", canEdit: false, error: "" }));
    try {
      const snapshot = await apiUtils.get<CatalogSnapshot>(API_CONFIG.ENDPOINTS.SOURCES.GET, { signal: controller.signal, redirectOnUnauthorized: false });
      if (controller.signal.aborted || sequence !== loadSequence.current || generation !== context.current) return false;
      return accept(snapshot, snapshot.can_edit === true, generation);
    } catch (error) {
      if (controller.signal.aborted || generation !== context.current) return false;
      const unauthorized = error instanceof ApiRequestError && error.status === 401;
      currentPermission.current = false;
      setState((current) => ({ ...current, status: unauthorized ? "sign-in-required" : "unavailable", canEdit: false, error: messageFor(error) }));
      return false;
    }
  }, [accept, datasetKey, isAuthenticated]);

  useEffect(() => {
    const generation = ++context.current;
    latestRevision.current = -1;
    currentPermission.current = false;
    busy.current = false;
    setSaving(false);
    setState(idleState(currentProjection.current, isAuthenticated));
    if (datasetKey && isAuthenticated) void refresh();
    return () => {
      context.current = generation + 1;
      readController.current?.abort();
      saveController.current?.abort();
    };
  }, [accountKey, datasetKey, isAuthenticated, refresh]);

  const canRename = useCallback((target: CatalogNameTarget | undefined): boolean => !!target && isAuthenticated && state.canEdit && state.labels.has(catalogNameKey(target)), [isAuthenticated, state.canEdit, state.labels]);

  const rename = useCallback(async (target: CatalogNameTarget, proposed: string): Promise<boolean> => {
    if (busy.current) {
      setState((current) => ({ ...current, error: "Another name is being saved. Wait for it to finish." }));
      return false;
    }
    if (!canRename(target) || state.revision === null) {
      setState((current) => ({ ...current, error: isAuthenticated ? "This object is read-only until its saved catalog is available and editable." : "Sign in to rename saved catalog objects." }));
      return false;
    }
    const label = proposed.trim();
    const hasControl = Array.from(label).some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127);
    if (!label || label.length > 120 || hasControl) {
      setState((current) => ({ ...current, error: "Use a name of 1–120 characters without control characters." }));
      return false;
    }
    busy.current = true;
    setSaving(true);
    setState((current) => ({ ...current, error: "" }));
    const generation = context.current;
    const controller = new AbortController();
    saveController.current = controller;
    try {
      const saved = await apiUtils.patch<SavedNames>(API_CONFIG.ENDPOINTS.SOURCES.LABELS, { expected_revision: state.revision, ...target, label }, { signal: controller.signal, redirectOnUnauthorized: false });
      if (controller.signal.aborted || generation !== context.current) return false;
      return accept(saved, saved.can_edit ?? currentPermission.current, generation);
    } catch (error) {
      if (controller.signal.aborted || generation !== context.current) return false;
      if (error instanceof ApiRequestError && error.status === 409) {
        const refreshed = await refresh();
        if (generation === context.current) setState((current) => ({ ...current, error: refreshed ? "The catalog changed. Names were refreshed from the database; review the current name and try again." : "The catalog changed. Refresh its saved names before trying again." }));
      } else {
        const denied = error instanceof ApiRequestError && (error.status === 401 || error.status === 403);
        if (denied) currentPermission.current = false;
        setState((current) => ({ ...current, ...(denied ? { canEdit: false, status: error.status === 401 ? "sign-in-required" as const : "read-only" as const } : {}), error: messageFor(error) }));
      }
      return false;
    } finally {
      if (generation === context.current) {
        busy.current = false;
        setSaving(false);
      }
    }
  }, [accept, canRename, isAuthenticated, refresh, state.revision]);

  return { status: state.status, canEdit: state.canEdit, revision: state.revision, saving, error: state.error, canRename, rename, refresh };
}
