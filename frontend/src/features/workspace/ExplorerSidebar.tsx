import { useEffect, useRef } from "react";
import * as Popover from "@radix-ui/react-popover";
import { ArrowLeft, ChevronDown, Folder, FolderRoot, Info, ListFilter, Search, Settings2, Star } from "lucide-react";
import { CatalogueToggle } from "./CatalogueToggle";
import { ExplorerList, type ExplorerRow, type ListPosition } from "./ExplorerList";
import { navigationTrail, type ExplorerNode, type NavigationIndex } from "@/domain/system/navigationIndex";
import type { SystemGroup } from "@/types/system";
import type { ReadingActivitySource } from "@/domain/system/readingActivity";

const shortcutLabel = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌘K" : "Ctrl K";

type Props = {
  index: NavigationIndex; scopeKey: string; rows: ExplorerRow[]; title: string;
  catalogueGroups: SystemGroup[]; query: string; resultsQuery?: string;
  selectedKey: string | null; positions: Map<string, ListPosition>; loading: boolean;
  onQuery: (value: string) => void; onScope: (key: string) => void;
  onBrowse?: (node: ExplorerNode) => void;
  onOpen: (node: ExplorerNode) => void; onBack: () => void; onInspect: () => void;
  onSettings: () => void; onCatalogue?: () => void; onDismiss?: () => void;
  activity?: ReadingActivitySource;
  onlineOnly?: boolean;
  onOnlineOnlyChange?: (value: boolean) => void;
  readingCount?: number;
  favourites?: Array<{ kind: "service" | "reading"; id: string; label: string }>;
  onFavourite?: (kind: "service" | "reading", id: string) => void;
};

export function ExplorerSidebar(props: Props) {
  const { index, scopeKey, rows, title, catalogueGroups, query, selectedKey, positions } = props;
  const resultsQuery = props.resultsQuery ?? query;
  const search = useRef<HTMLInputElement>(null);
  const trail = navigationTrail(index, scopeKey);
  const current = index.nodes.get(scopeKey);
  const atRoot = scopeKey === index.rootKey && !query;
  const onlineOnly = props.onlineOnly ?? false;
  const readingCount = props.readingCount ?? index.counts.readings;
  const brokers = rows.filter(row => row.node.kind === "connection").length;
  const viewKey = resultsQuery.trim() ? `search:${JSON.stringify([resultsQuery, onlineOnly])}`
    : `${scopeKey.startsWith("catalogue:") ? "catalogue" : "scope"}:${JSON.stringify([scopeKey, onlineOnly])}`;
  const owner = trail.slice(0, -1).reverse().find((ancestor) => ancestor.kind === "device" || ancestor.kind === "connection");
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); search.current?.focus(); search.current?.select();
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  const returnToRoot = () => {
    positions.delete(`scope:${JSON.stringify([index.rootKey, onlineOnly])}`);
    if (atRoot && !resultsQuery.trim()) {
      search.current?.closest("nav")?.querySelector<HTMLDivElement>(".ex-list-scroll")?.scrollTo({ top: 0 });
    }
    if (props.onCatalogue) props.onCatalogue();
    else { props.onQuery(""); props.onScope(index.rootKey); }
  };
  return <nav id="system-explorer" className="ex-sidebar" aria-label="System explorer">
    <div className="ex-sidebar-top">
      <span className="workspace-catalogue-label">MQTT catalogue</span>
      {props.onDismiss && <CatalogueToggle open className="catalogue-drawer-toggle" onClick={props.onDismiss} />}
    </div>
    <div className="ex-search"><Search size={15} aria-hidden="true" />
      <input ref={search} type="search" aria-label="Search catalogue" placeholder="Search catalogue" value={query} aria-keyshortcuts="Control+K Meta+K"
        onChange={(event) => props.onQuery(event.target.value)} onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault(); search.current?.closest("nav")?.querySelector<HTMLButtonElement>("[data-row]")?.focus();
          }
          if (event.key === "Escape" && query) { event.preventDefault(); event.stopPropagation(); props.onQuery(""); }
        }} />
      {!query && <kbd className="ex-search-key" aria-hidden="true">{shortcutLabel}</kbd>}
    </div>
    {!!props.favourites?.length && <section className="mn-sidebar-favourites" aria-label="Favourites"><span>Favourites</span>
      {props.favourites.map(item => <button key={`${item.kind}:${item.id}`} title={item.label} onClick={() => props.onFavourite?.(item.kind, item.id)}><Star size={13} /><span>{item.label}</span></button>)}
    </section>}
    {catalogueGroups.length > 0 && <div className="ex-sidebar-section">
      <Popover.Root><Popover.Trigger asChild><button className="ex-group-trigger" aria-label="Browse collections"><span>Collections</span><ChevronDown size={13} aria-hidden="true" /></button></Popover.Trigger>
        <Popover.Portal><Popover.Content className="ex-popover ex-group-menu" side="bottom" align="start" sideOffset={8}>
          <strong>Collections</strong>{catalogueGroups.map((item) => <Popover.Close asChild key={item.id}>
            <button aria-label={`Show collection ${item.label}`} aria-current={scopeKey === `catalogue:${item.id}` ? "location" : undefined}
              onClick={() => props.onScope(`catalogue:${item.id}`)}><Folder size={14} /><span>{item.label}</span><small aria-hidden="true">{item.member_ids.length}</small></button>
          </Popover.Close>)}
        </Popover.Content></Popover.Portal>
      </Popover.Root>
    </div>}
    {/* The level is where the sidebar stands; it reads as selected only when it is also the shown source. */}
    <div className={`ex-level-heading${atRoot ? " is-root" : ""}${!atRoot && !query && selectedKey === scopeKey ? " is-selected" : ""}`}>
      {(scopeKey !== index.rootKey || query) && <button className="ex-back ex-icon-button" aria-label={query ? "Close search" : "Back one level"}
        onClick={props.onBack}><ArrowLeft size={16} /></button>}
      <div className="ex-level-title">
        {query ? <strong>Search results</strong> : !atRoot && <Popover.Root key={scopeKey}>
          <Popover.Trigger className="ex-ancestor-trigger"><span>{title}</span><ChevronDown size={13} /></Popover.Trigger>
          <Popover.Portal><Popover.Content className="ex-popover ex-ancestor-menu" align="start" sideOffset={8}>
            <strong>Current path</strong>
            {(trail.length ? trail : [index.nodes.get(index.rootKey)!]).map((ancestor) => <Popover.Close asChild key={ancestor.key}>
              <button aria-current={ancestor.key === scopeKey ? "location" : undefined} onClick={() => props.onScope(ancestor.key)}>{ancestor.kind === "root" ? "Catalogue" : ancestor.label}</button>
            </Popover.Close>)}
          </Popover.Content></Popover.Portal>
        </Popover.Root>}
        <span title={owner?.label}>{query ? `${rows.length === 100 ? "First " : ""}${rows.length} ${rows.length === 1 ? "match" : "matches"}`
          : current?.kind === "root" ? `${brokers} ${brokers === 1 ? "broker" : "brokers"}${rows.some((row) => row.node.kind === "unassigned") ? " · unassigned entities" : ""}`
            : `${rows.length} ${rows.length === 1 ? "item" : "items"}${owner ? ` · ${owner.label}` : ""}`}</span>
      </div>
      {current && current.kind !== "root" && !query && <button className="ex-icon-button" aria-label="Inspect current item" onClick={props.onInspect}><Info size={16} /></button>}
      {props.onOnlineOnlyChange && <button type="button" className="ex-icon-button ex-online-filter" aria-label="Online topics only"
        title="Online topics only · receiving data in the last 30 seconds" aria-pressed={onlineOnly} onClick={() => props.onOnlineOnlyChange?.(!onlineOnly)}>
        <ListFilter size={16} aria-hidden="true" />
      </button>}
      <button type="button" className="ex-icon-button ex-root-button" aria-label="Back to catalogue" title="Back to catalogue" onClick={returnToRoot}>
        <FolderRoot size={16} aria-hidden="true" />
      </button>
    </div>
    {props.loading ? <div className="ex-list-empty" role="status">Loading catalogue…</div>
      : <ExplorerList rows={rows} viewKey={viewKey} positions={positions}
        selectedKey={selectedKey} onOpen={props.onOpen} onBack={props.onBack} onBrowse={props.onBrowse} activity={props.activity}
        emptyMessage={onlineOnly ? "No active topics" : undefined}
        emptyAction={onlineOnly && props.onOnlineOnlyChange ? { label: "Show all topics", onClick: () => props.onOnlineOnlyChange?.(false) } : undefined} />}
    {query && rows.length === 100 && <p className="ex-search-hint">Refine your search to see more matches.</p>}
    <div className="ex-sidebar-footer"><button onClick={props.onSettings}><Settings2 size={15} /><span>Catalogue settings</span></button>
      <span>{readingCount.toLocaleString()} {onlineOnly ? "online " : ""}{readingCount === 1 ? "reading" : "readings"}</span>
    </div>
  </nav>;
}
