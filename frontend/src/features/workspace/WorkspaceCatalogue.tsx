import { useNow } from "@/hooks/use-now";
import { useDeferredValue, useMemo, useSyncExternalStore } from "react";
import { ExplorerSidebar } from "./ExplorerSidebar";
import { navigationRows, navigationTrail, searchNavigation } from "@/domain/system/navigationIndex";
import { onlineNavigationIndex } from "@/domain/system/onlineNavigation";
import { useCatalogue } from "./catalogue-context";

const subscribeNothing = () => () => {};

export function WorkspaceCatalogue({ onDismiss }: { onDismiss?: () => void }) {
  const { document, index, system, telemetry, previewStreamIds, selected, scopeKey, query, setQuery, positions,
    preferences, setPreferences, browse, back, selectSource, openSettings } = useCatalogue();
  const onlineOnly = preferences.onlineOnly ?? false;
  const now = useNow(1000, onlineOnly);
  const liveStatus = useSyncExternalStore(onlineOnly ? telemetry.subscribeUpdates : subscribeNothing, telemetry.getStatus);
  const activity = useMemo(() => ({ telemetry, liveStreamIds: previewStreamIds, runtime: system.snapshot?.runtime }), [telemetry, previewStreamIds, system.snapshot?.runtime]);
  const visibleIndex = useMemo(() => onlineOnly ? onlineNavigationIndex(index, activity, liveStatus, now) : index,
    [onlineOnly, index, activity, liveStatus, now]);
  const deferredQuery = useDeferredValue(query);
  const current = index.nodes.get(scopeKey);
  const group = document.groups.find(item => scopeKey === `catalogue:${item.id}`);
  const labels = useMemo(() => new Map(document.streams.map(stream => [stream.id, stream.label])), [document.streams]);
  const rows = useMemo(() => {
    if (deferredQuery.trim()) return searchNavigation(visibleIndex, deferredQuery).map(node => ({ node,
      label: node.entityKind === "stream" ? labels.get(node.objectId ?? "") ?? node.label : node.label,
      detail: navigationTrail(index, node.key).slice(1, -1).map(ancestor => ancestor.label).join(" / ") || "Catalogue" }));
    if (group) return group.member_ids.flatMap(id => {
      const key = visibleIndex.objectKeys.get(id)?.[0];
      const node = key ? visibleIndex.nodes.get(key) : undefined;
      return node ? [{ node, label: node.entityKind === "stream" ? labels.get(id) ?? node.label : node.label,
        detail: navigationTrail(index, node.key).slice(1, -1).map(ancestor => ancestor.label).join(" / "), color: group.color }] : [];
    });
    return navigationRows(visibleIndex, scopeKey).map(row => ({ ...row,
      detail: row.node.entityKind === "stream" ? labels.get(row.node.objectId ?? "") : undefined }));
  }, [index, visibleIndex, scopeKey, deferredQuery, group, labels]);
  const favourites = (preferences.favourites ?? []).flatMap(item => item.kind === "reading" && labels.has(item.id) && visibleIndex.objectKeys.has(item.id)
    ? [{ ...item, label: labels.get(item.id)! }] : []);
  const title = group?.label ?? (current?.kind === "topic"
    ? navigationTrail(index, scopeKey).filter(node => node.kind === "topic").map(node => node.label).join("/")
    : current?.label) ?? document.label;
  return <ExplorerSidebar index={index} scopeKey={scopeKey} title={title} catalogueGroups={document.groups}
    activity={activity} onlineOnly={onlineOnly} readingCount={visibleIndex.counts.readings}
    onOnlineOnlyChange={value => { setPreferences(previous => ({ ...previous, onlineOnly: value })); }}
    rows={rows} query={query} resultsQuery={deferredQuery} selectedKey={selected?.key ?? null} positions={positions} loading={system.status === "loading"}
    onQuery={setQuery} onScope={browse} onBack={back} onBrowse={node => browse(node.key)}
    onOpen={node => { selectSource(node); onDismiss?.(); }}
    onInspect={() => { if (current) { selectSource(current); onDismiss?.(); } }}
    onCatalogue={() => { browse(index.rootKey); selectSource(null); }}
    favourites={favourites} onFavourite={(_, id) => {
      const node = index.nodes.get(index.objectKeys.get(id)?.[0] ?? "");
      if (node) { selectSource(node); onDismiss?.(); }
    }}
    onSettings={() => { openSettings(); onDismiss?.(); }} onDismiss={onDismiss} />;
}
