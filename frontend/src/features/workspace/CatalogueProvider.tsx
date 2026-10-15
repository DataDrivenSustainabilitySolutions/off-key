import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { navigationDraft, useNavigationDraft } from "@/lib/navigation-draft";
import { useSystemDocument } from "../catalogue/useSystemDocument";
import { createEmptySystem } from "../catalogue/systemDocument";
import { scopeReadingIds, safeServiceReturn } from "../catalogue/collectionRules";
import { SystemLiveTelemetry } from "../catalogue/systemLiveTelemetry";
import { ReadingHistoryCache } from "../explorer/readingHistoryCache";
import { buildNavigationIndex } from "../explorer/navigationIndex";
import { loadExplorerPreferences, saveExplorerPreferences, toggleExplorerFavourite } from "../explorer/preferences";
import type { ListPosition } from "../explorer/ExplorerList";
import { CatalogueContext, type CatalogueContextValue, type CatalogueDialog } from "./catalogue-context";
import { catalogueSelection, hasCatalogueSelection, isWorkspacePath, selectedSourceHref, withCatalogueSource } from "./catalogue-navigation";

const empty = createEmptySystem();

export function CatalogueProvider({ children }: { children: ReactNode }) {
  const { userId, isAuthenticated } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const params = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const system = useSystemDocument({ isAuthenticated, accountKey: userId });
  const document = system.document ?? empty;
  const index = useMemo(() => buildNavigationIndex(document), [document]);
  const selected = useMemo(() => catalogueSelection(index, params), [index, params]);
  const selectionRequested = hasCatalogueSelection(params);
  const selectionMissing = !!system.document && selectionRequested && !selected;
  const streamIds = useMemo(() => selected ? [...new Set(scopeReadingIds(index, selected))]
    : selectionRequested ? [] : undefined, [index, selected, selectionRequested]);
  const streamsById = useMemo(() => new Map(document.streams.map(stream => [stream.id, stream])), [document.streams]);
  const liveStreamIds = useMemo(() => (streamIds ?? []).filter(id => {
    const stream = streamsById.get(id);
    return stream?.value_type !== "number" || (system.snapshot?.runtime.bindings?.[id]?.policy.mode ?? "off") === "off";
  }), [streamIds, streamsById, system.snapshot?.runtime.bindings]);
  const [telemetry] = useState(() => new SystemLiveTelemetry());
  const history = useMemo(() => navigationDraft(`history:${userId}`, () => new ReadingHistoryCache(userId)), [userId]);
  const [rawPreferences, setPreferences] = useState(() => loadExplorerPreferences(userId ?? null));
  const preferences = useMemo(() => !system.document || index.nodes.has(rawPreferences.scopeKey)
    || document.groups.some(group => rawPreferences.scopeKey === `catalogue:${group.id}`)
    ? rawPreferences : { ...rawPreferences, scopeKey: index.rootKey }, [rawPreferences, system.document, index, document.groups]);
  const [stored, setStored] = useState(true);
  const [query, setQuery] = useNavigationDraft(`catalogue:${userId}:query`, "");
  const [positions] = useNavigationDraft(`catalogue:${userId}:positions`, () => new Map<string, ListPosition>());
  const browseHistory = useRef<string[]>([]);
  const scopeKey = index.nodes.has(preferences.scopeKey) || document.groups.some(group => preferences.scopeKey === `catalogue:${group.id}`)
    ? preferences.scopeKey : index.rootKey;
  const [editingLocked, setEditingLocked] = useState(false);
  const [dialog, setDialog] = useState<CatalogueDialog>(() => params.get("catalogue") === "settings" ? { kind: "settings" } : null);
  const dialogOrigin = useRef<HTMLElement | null>(null);
  const initialReveal = useRef(false);

  useEffect(() => {
    if (!system.document || initialReveal.current) return;
    initialReveal.current = true;
    if (!selected) return;
    let active = true;
    const scopeKey = selected.entityKind === "stream" ? selected.parentKey ?? index.rootKey : selected.key;
    queueMicrotask(() => { if (active) setPreferences(previous => ({ ...previous, scopeKey })); });
    return () => { active = false; };
  }, [system.document, selected, index]);

  useEffect(() => {
    if (!system.document) return;
    const persist = () => setStored(saveExplorerPreferences(userId ?? null, preferences));
    const timer = window.setTimeout(persist, 150);
    window.addEventListener("pagehide", persist);
    return () => { clearTimeout(timer); window.removeEventListener("pagehide", persist); };
  }, [preferences, userId, system.document]);
  useEffect(() => {
    telemetry.configure(document, system.revision ?? 0, isAuthenticated ? String(userId ?? "signed-in") : "", system.canEdit);
  }, [telemetry, document, system.revision, isAuthenticated, userId, system.canEdit]);
  useEffect(() => { telemetry.setScope(liveStreamIds); }, [telemetry, liveStreamIds]);
  useEffect(() => { telemetry.setPriority(selected?.objectId ?? null); }, [telemetry, selected?.objectId]);
  useEffect(() => {
    const visibility = () => window.document.hidden ? telemetry.pause() : telemetry.resume();
    const leave = () => telemetry.stop();
    window.document.addEventListener("visibilitychange", visibility);
    window.addEventListener("pagehide", leave);
    return () => {
      window.document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("pagehide", leave);
      telemetry.stop();
    };
  }, [telemetry]);

  const browse = (key: string, remember = true) => {
    if (remember && key !== scopeKey) {
      if (browseHistory.current.length >= 128) browseHistory.current.shift();
      browseHistory.current.push(scopeKey);
    }
    setPreferences(previous => ({ ...previous, scopeKey: key }));
    setQuery("");
  };
  const selectSource: CatalogueContextValue["selectSource"] = node => {
    const path = isWorkspacePath(location.pathname) ? location.pathname : "/sources";
    const returnTo = path === "/sources" ? safeServiceReturn(params.get("returnTo")) : "/";
    navigate(selectedSourceHref(returnTo === "/" ? path : `${path}?returnTo=${encodeURIComponent(returnTo)}`, node));
  };
  const sectionHref = (path: string) => {
    let href = path;
    if (path === "/" && location.pathname !== "/") {
      const returnTo = safeServiceReturn(params.get("returnTo"));
      const remembered = navigationDraft(`monitoring:${userId}:url`, () => "/");
      const oldSource = catalogueSelection(index, new URL(remembered, "https://workspace.invalid").searchParams);
      if (returnTo !== "/") href = returnTo;
      else if (oldSource?.key === selected?.key) href = remembered;
    }
    return withCatalogueSource(href, selected ?? params.get("source") ?? undefined);
  };
  const openEditor: CatalogueContextValue["openEditor"] = (kind, id) => {
    if (editingLocked || !system.canEdit) return;
    if (!dialog) dialogOrigin.current = window.document.activeElement as HTMLElement;
    setDialog({ kind: "editor", entityKind: kind, id, key: Date.now() });
  };

  return <CatalogueContext.Provider value={{
    system, document, index, selected, selectionRequested, selectionMissing, streamIds,
    liveStreamIds, telemetry, history, preferences, setPreferences, stored, scopeKey,
    query, setQuery, positions, browse,
    back: () => query ? setQuery("") : browse(browseHistory.current.pop() ?? index.nodes.get(scopeKey)?.parentKey ?? index.rootKey, false),
    selectSource, sectionHref,
    toggleFavourite: (kind, id) => setPreferences(previous => toggleExplorerFavourite(previous, kind, id)),
    editingLocked, setEditingLocked, dialog, dialogOrigin,
    openSettings: () => { dialogOrigin.current = window.document.activeElement as HTMLElement; setDialog({ kind: "settings" }); },
    openEditor, closeDialog: () => { if (!system.saving) setDialog(null); },
  }}>{children}</CatalogueContext.Provider>;
}
