import { useEffect, useRef } from "react";
import * as Popover from "@radix-ui/react-popover";
import { ArrowLeft, ChevronDown, Folder, Home, Info, Layers, Search, Settings2, Star, X } from "lucide-react";
import { ExplorerList, type ExplorerRow, type ListPosition } from "./ExplorerList";
import { navigationTrail, type ExplorerNode, type NavigationIndex } from "./navigationIndex";
import type { SystemGroup } from "../catalogue/systemTypes";

type Props = {
  index: NavigationIndex; scopeKey: string; rows: ExplorerRow[]; title: string;
  catalogueGroups: SystemGroup[]; query: string; resultsQuery?: string;
  selectedKey: string | null; positions: Map<string, ListPosition>; loading: boolean;
  onQuery: (value: string) => void; onScope: (key: string) => void;
  onBrowse?: (node: ExplorerNode) => void;
  onOpen: (node: ExplorerNode) => void; onBack: () => void; onInspect: () => void;
  onSettings: () => void; onWorkspace: () => void; onDismiss?: () => void;
  favourites?: Array<{ kind: "service" | "reading"; id: string; label: string }>;
  onFavourite?: (kind: "service" | "reading", id: string) => void;
};

export function ExplorerSidebar(props: Props) {
  const { index, scopeKey, rows, title, catalogueGroups, query, selectedKey, positions } = props;
  const resultsQuery = props.resultsQuery ?? query;
  const search = useRef<HTMLInputElement>(null);
  const trail = navigationTrail(index, scopeKey);
  const current = index.nodes.get(scopeKey);
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
  return <nav id="system-explorer" className="ex-sidebar" aria-label="System explorer">
    <div className="ex-sidebar-top">
      <button className="ex-workspace-link" onClick={props.onWorkspace}><Home size={16} strokeWidth={1.6} /><span>Monitoring</span></button>
      {props.onDismiss && <button className="ex-icon-button" aria-label="Close explorer" onClick={props.onDismiss}><X size={18} /></button>}
    </div>
    <div className="ex-search"><Search size={15} aria-hidden="true" />
      <input ref={search} type="search" aria-label="Search catalogue" placeholder="Search everything…" value={query}
        onChange={(event) => props.onQuery(event.target.value)} onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault(); search.current?.closest("nav")?.querySelector<HTMLButtonElement>("[data-row]")?.focus();
          }
          if (event.key === "Escape" && query) { event.preventDefault(); event.stopPropagation(); props.onQuery(""); }
        }} />
      {!query && <kbd aria-hidden="true">⌘ K</kbd>}
    </div>
    {!!props.favourites?.length && <section className="mn-sidebar-favourites" aria-label="Favourites"><span>Favourites</span>
      {props.favourites.map(item => <button key={`${item.kind}:${item.id}`} title={item.label} onClick={() => props.onFavourite?.(item.kind, item.id)}><Star size={13} /><span>{item.label}</span></button>)}
    </section>}
    <div className="ex-sidebar-section">
      <button onClick={() => props.onScope(index.rootKey)} className={scopeKey === index.rootKey && !query ? "is-current" : ""}>Catalogue</button>
      {catalogueGroups.length > 0 && <Popover.Root><Popover.Trigger asChild><button className="ex-group-trigger" aria-label="Browse catalogue groups"><Layers size={13} /><span>Catalogue groups</span></button></Popover.Trigger>
        <Popover.Portal><Popover.Content className="ex-popover ex-group-menu" side="bottom" align="end" sideOffset={8}>
          <strong>Catalogue groups</strong>{catalogueGroups.map((item) => <Popover.Close asChild key={item.id}>
            <button aria-label={`Show catalogue group ${item.label}`} onClick={() => props.onScope(`catalogue:${item.id}`)}><Folder size={14} /><span>{item.label}</span><small aria-hidden="true">{item.member_ids.length}</small></button>
          </Popover.Close>)}
        </Popover.Content></Popover.Portal>
      </Popover.Root>}
    </div>
    <div className="ex-level-heading">
      {(scopeKey !== index.rootKey || query) && <button className="ex-back ex-icon-button" aria-label={query ? "Close search" : "Back one level"}
        onClick={props.onBack}><ArrowLeft size={16} /></button>}
      <div className="ex-level-title">
        {query ? <strong>Search results</strong> : <Popover.Root key={scopeKey}>
          <Popover.Trigger className="ex-ancestor-trigger"><span>{title}</span><ChevronDown size={13} /></Popover.Trigger>
          <Popover.Portal><Popover.Content className="ex-popover ex-ancestor-menu" align="start" sideOffset={8}>
            <strong>Current path</strong>
            {(trail.length ? trail : [index.nodes.get(index.rootKey)!]).map((ancestor) => <Popover.Close asChild key={ancestor.key}>
              <button aria-current={ancestor.key === scopeKey ? "location" : undefined} onClick={() => props.onScope(ancestor.key)}>{ancestor.label}</button>
            </Popover.Close>)}
          </Popover.Content></Popover.Portal>
        </Popover.Root>}
        <span title={owner?.label}>{query ? `${rows.length === 100 ? "First " : ""}${rows.length} ${rows.length === 1 ? "match" : "matches"}`
          : current?.kind === "root" ? `${index.counts.connections} ${index.counts.connections === 1 ? "broker" : "brokers"}${rows.some((row) => row.node.kind === "unassigned") ? " · unassigned entities" : ""}`
            : `${rows.length} ${rows.length === 1 ? "item" : "items"}${owner ? ` · ${owner.label}` : ""}`}</span>
      </div>
      {current?.entityKind && !query && <button className="ex-icon-button" aria-label="Inspect current item" onClick={props.onInspect}><Info size={16} /></button>}
    </div>
    {props.loading ? <div className="ex-list-empty" role="status">Loading catalogue…</div>
      : <ExplorerList rows={rows} viewKey={resultsQuery.trim() ? `search:${resultsQuery}` : scopeKey} positions={positions}
        selectedKey={selectedKey} onOpen={props.onOpen} onBack={props.onBack} onBrowse={props.onBrowse} />}
    {query && rows.length === 100 && <p className="ex-search-hint">Refine your search to see more matches.</p>}
    <div className="ex-sidebar-footer"><button onClick={props.onSettings}><Settings2 size={15} /><span>Catalogue settings</span></button>
      <span>{index.counts.readings.toLocaleString()} {index.counts.readings === 1 ? "reading" : "readings"}</span>
    </div>
  </nav>;
}
