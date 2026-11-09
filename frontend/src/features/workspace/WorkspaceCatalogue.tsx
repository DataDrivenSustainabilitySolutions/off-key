import { useNow } from "@/hooks/use-now";
import { useDeferredValue, useMemo, useSyncExternalStore, type Ref } from "react";
import { onlineNavigationIndex } from "@/domain/system/onlineNavigation";
import { useSettingsNavigation } from "@/lib/settings-navigation";
import { CatalogueBrowser } from "./CatalogueBrowser";
import { catalogueRoots, catalogueSearchRows, catalogueTreeRows } from "./catalogue-tree";
import { useCatalogue } from "./catalogue-context";

const subscribeNothing = () => () => {};

/** The catalogue category of the sidebar, bound to the shared catalogue state. */
export function WorkspaceCatalogue({ onDismiss, searchRef }: { onDismiss?: () => void; searchRef?: Ref<HTMLInputElement> }) {
  const { document, index, system, telemetry, previewStreamIds, selected, query, setQuery, positions,
    preferences, setPreferences, expanded, setExpanded, collapseAll, collection, showCollection, selectSource } = useCatalogue();
  const settings = useSettingsNavigation();
  const onlineOnly = preferences.onlineOnly ?? false;
  const now = useNow(1000, onlineOnly);
  const liveStatus = useSyncExternalStore(onlineOnly ? telemetry.subscribeUpdates : subscribeNothing, telemetry.getStatus);
  const activity = useMemo(() => ({ telemetry, liveStreamIds: previewStreamIds, runtime: system.snapshot?.runtime }), [telemetry, previewStreamIds, system.snapshot?.runtime]);
  const visibleIndex = useMemo(() => onlineOnly ? onlineNavigationIndex(index, activity, liveStatus, now) : index,
    [onlineOnly, index, activity, liveStatus, now]);
  const deferredQuery = useDeferredValue(query);
  const streams = useMemo(() => new Map(document.readings.map(stream => [stream.id, stream])), [document.readings]);
  const searching = !!deferredQuery.trim();
  const rows = useMemo(() => searching ? catalogueSearchRows(visibleIndex, deferredQuery, streams)
    : catalogueTreeRows(visibleIndex, catalogueRoots(visibleIndex, collection), expanded, streams),
  [searching, visibleIndex, deferredQuery, streams, collection, expanded]);
  const viewKey = searching ? `search:${JSON.stringify([deferredQuery, onlineOnly])}`
    : `tree:${JSON.stringify([collection?.id ?? null, onlineOnly])}`;
  const emptyCatalogue = !document.brokers.length && !document.readings.length && !document.devices.length;
  const loading = system.status === "loading" && !system.document;
  const error = !system.document && system.status === "unavailable" ? `The catalogue could not be loaded. ${system.error}`.trim() : undefined;
  return <CatalogueBrowser rows={rows} viewKey={viewKey} query={query} resultsQuery={deferredQuery} selectedKey={selected?.key ?? null}
    positions={positions} loading={loading} error={error} searchRef={searchRef}
    collection={collection ? { label: collection.label, onClear: () => showCollection(null) } : undefined}
    activity={activity} onlineOnly={onlineOnly}
    onOnlineOnlyChange={value => { setPreferences(previous => ({ ...previous, onlineOnly: value })); }}
    onQuery={setQuery}
    onOpen={node => { selectSource(node); onDismiss?.(); }}
    onToggle={row => setExpanded(row.node.key, !row.expanded)}
    onCollapseAll={collapseAll}
    emptyMessage={searching ? (onlineOnly ? "No recently active matches." : "No matches.")
      : onlineOnly ? "No recently active topics." : collection ? "This collection has no sources." : emptyCatalogue ? "No sources yet." : "No items here."}
    emptyAction={onlineOnly ? { label: "Show all topics", onClick: () => setPreferences(previous => ({ ...previous, onlineOnly: false })) }
      : emptyCatalogue && !collection && !searching ? { label: "Open catalogue settings", onClick: () => { onDismiss?.(); settings.open("catalogue"); } }
        : undefined} />;
}
