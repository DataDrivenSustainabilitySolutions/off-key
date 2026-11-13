import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { navigationDraft, useNavigationDraft } from "@/lib/navigation-draft";
import { settingsHref, settingsSectionOf } from "@/lib/settings-navigation";
import { useSystemDocument } from "@/domain/system/useSystemDocument";
import { createEmptySystem } from "@/domain/system/systemDocument";
import { scopeReadingIds, safeServiceReturn } from "@/domain/system/collectionRules";
import { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import { ReadingHistoryCache } from "@/domain/readings/readingHistoryCache";
import { buildNavigationIndex } from "@/domain/system/navigationIndex";
import { loadExplorerPreferences, MAX_EXPANDED_NODES, saveExplorerPreferences } from "./preferences";
import { ancestorKeys } from "./catalogue-tree";
import { useFavourites } from "./favourites";
import type { ListPosition } from "./ExplorerList";
import { CatalogueContext, type CatalogueContextValue, type CatalogueDialog } from "./catalogue-context";
import { catalogueSelection, hasCatalogueSelection, isWorkspacePath, selectedSourceHref, withCatalogueSource } from "./catalogue-navigation";
import { monitoringNavigationKey } from "@/domain/monitoring/monitoringView";
import type { SystemRuntime, SystemStream } from "@/types/system";

const empty = createEmptySystem();
/** Readings that are not recorded reach the page only through the live preview. */
const liveOnly = (stream: SystemStream | undefined, runtime?: SystemRuntime) => !!stream
  && (stream.value_type !== "number" || (runtime?.bindings?.[stream.id]?.policy.mode ?? "off") === "off");

export function CatalogueProvider({ children }: { children: ReactNode }) {
  const { userId, isAuthenticated, isGuest } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const params = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const system = useSystemDocument({ isAuthenticated: isAuthenticated || isGuest, accountKey: isGuest ? "demo" : userId });
  const document = system.document ?? empty;
  const index = useMemo(() => buildNavigationIndex(document), [document]);
  const selected = useMemo(() => catalogueSelection(index, params), [index, params]);
  const selectionRequested = hasCatalogueSelection(params);
  const selectionMissing = !!system.document && selectionRequested && !selected;
  const streamIds = useMemo(() => selected ? [...new Set(scopeReadingIds(index, selected))]
    : selectionRequested ? [] : undefined, [index, selected, selectionRequested]);
  const streamsById = useMemo(() => new Map(document.readings.map(stream => [stream.id, stream])), [document.readings]);
  const liveStreamIds = useMemo(() => (streamIds ?? []).filter(id => liveOnly(streamsById.get(id), system.snapshot?.runtime)),
    [streamIds, streamsById, system.snapshot?.runtime]);
  // The live preview covers every broker of the selection, so choosing one topic
  // keeps its sibling topics streaming and shown as receiving.
  const previewStreamIds = useMemo(() => {
    const brokers = new Set((streamIds ?? []).flatMap(id => streamsById.get(id)?.broker_id ?? []));
    return document.readings.filter(stream => brokers.has(stream.broker_id) && liveOnly(stream, system.snapshot?.runtime)).map(stream => stream.id);
  }, [streamIds, streamsById, document.readings, system.snapshot?.runtime]);
  const [telemetry] = useState(() => new SystemLiveTelemetry());
  const history = useMemo(() => navigationDraft(`history:${userId}`, () => new ReadingHistoryCache(userId)), [userId]);
  const [preferences, setPreferences] = useState(() => loadExplorerPreferences(userId ?? null));
  const [stored, setStored] = useState(true);
  const dropLegacyFavourites = useCallback(() => setPreferences(previous => {
    const next = { ...previous };
    delete next.favourites;
    return next;
  }), []);
  const favourites = useFavourites(isAuthenticated ? userId ?? null : null, preferences.favourites, dropLegacyFavourites);
  const [query, setQuery] = useNavigationDraft(`catalogue:${userId}:query`, "");
  const [positions] = useNavigationDraft(`catalogue:${userId}:positions`, () => new Map<string, ListPosition>());
  const expanded = useMemo(() => new Set(preferences.expanded ?? []), [preferences.expanded]);
  const collection = document.groups.find(group => group.id === preferences.collection);
  const [editingLocked, setEditingLocked] = useState(false);
  const [dialog, setDialog] = useState<CatalogueDialog>(null);
  const dialogOrigin = useRef<HTMLElement | null>(null);

  /** Opens `keys` in the tree, keeping the most recently opened when the list is full. */
  const expand = useCallback((keys: string[]) => setPreferences(previous => {
    const current = previous.expanded ?? [];
    const added = keys.filter(key => !current.includes(key));
    return added.length ? { ...previous, expanded: [...current, ...added].slice(-MAX_EXPANDED_NODES) } : previous;
  }), []);

  // Reveal the selected source in the tree: on a deep link, on Back and Forward,
  // and when a row, page or favourite chooses it. An earlier sidebar's location is
  // revealed the same way once, then forgotten.
  const revealed = useRef<string | null>(null);
  const selectedKey = selected?.key;
  const legacyScope = preferences.scopeKey;
  useEffect(() => {
    if (!system.document) return;
    const reveal = selectedKey && revealed.current !== selectedKey ? selectedKey : undefined;
    if (!reveal && legacyScope === undefined) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      revealed.current = selectedKey ?? null;
      if (legacyScope !== undefined) {
        setPreferences(previous => {
          const next = { ...previous };
          delete next.scopeKey;
          return next;
        });
        if (index.nodes.has(legacyScope)) expand([...ancestorKeys(index, legacyScope), legacyScope]);
      }
      // A chosen branch opens too, so its contents are in view. Opening a branch
      // never chooses it.
      const node = reveal ? index.nodes.get(reveal) : undefined;
      if (node) expand([...ancestorKeys(index, node.key), ...(node.entityKind !== "stream" && node.children.length ? [node.key] : [])]);
    });
    return () => { active = false; };
  }, [system.document, index, selectedKey, legacyScope, expand]);

  useEffect(() => {
    if (!system.document) return;
    const persist = () => setStored(saveExplorerPreferences(userId ?? null, preferences));
    const timer = window.setTimeout(persist, 150);
    window.addEventListener("pagehide", persist);
    return () => { clearTimeout(timer); window.removeEventListener("pagehide", persist); };
  }, [preferences, userId, system.document]);
  useEffect(() => {
    telemetry.configure(document, system.revision ?? 0, isGuest ? "demo" : isAuthenticated ? String(userId ?? "signed-in") : "", system.canEdit);
  }, [telemetry, document, system.revision, isAuthenticated, isGuest, userId, system.canEdit]);
  useEffect(() => { telemetry.setScope(previewStreamIds); }, [telemetry, previewStreamIds]);
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

  const selectSource: CatalogueContextValue["selectSource"] = node => {
    const path = isWorkspacePath(location.pathname) ? location.pathname : "/sources";
    const returnTo = path === "/sources" ? safeServiceReturn(params.get("returnTo")) : "/";
    const href = selectedSourceHref(returnTo === "/" ? path : `${path}?returnTo=${encodeURIComponent(returnTo)}`, node);
    // A change made from the settings overlay, such as an import, keeps the overlay open.
    const section = settingsSectionOf(location.search);
    if (!section) return navigate(href);
    const url = new URL(href, "https://workspace.invalid");
    navigate(settingsHref(url, section), { replace: true, state: location.state });
  };
  const sectionHref = (path: string) => {
    let href = path;
    if (path === "/" && location.pathname !== "/") {
      const returnTo = safeServiceReturn(params.get("returnTo"));
      const remembered = navigationDraft(monitoringNavigationKey(userId), () => "/");
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
    liveStreamIds, previewStreamIds, telemetry, history, preferences, setPreferences, stored,
    expanded, collection,
    setExpanded: (key, open) => open ? expand([key])
      : setPreferences(previous => ({ ...previous, expanded: (previous.expanded ?? []).filter(other => other !== key) })),
    collapseAll: () => setPreferences(previous => ({ ...previous, expanded: [] })),
    showCollection: id => setPreferences(previous => {
      const next = { ...previous };
      if (id) next.collection = id;
      else delete next.collection;
      return next;
    }),
    sectionOpen: section => !preferences.collapsedSections?.includes(section),
    setSectionOpen: (section, open) => setPreferences(previous => ({ ...previous,
      collapsedSections: open ? (previous.collapsedSections ?? []).filter(other => other !== section)
        : [...new Set([...(previous.collapsedSections ?? []), section])] })),
    query, setQuery, positions,
    selectSource, sectionHref,
    favourites: favourites.favourites, toggleFavourite: favourites.toggle, favouritesError: favourites.error,
    editingLocked, setEditingLocked, dialog, dialogOrigin,
    openEditor, closeDialog: () => { if (!system.saving) setDialog(null); },
  }}>{children}</CatalogueContext.Provider>;
}
