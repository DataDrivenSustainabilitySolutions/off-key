import { useId, type Ref } from "react";
import { ChevronsDownUp, ListFilter, Search, X } from "lucide-react";
import type { ExplorerNode } from "@/domain/system/navigationIndex";
import type { ReadingActivitySource } from "@/domain/system/readingActivity";
import { ExplorerList, type ListPosition } from "./ExplorerList";
import type { CatalogueRow } from "./catalogue-tree";

const CATALOGUE_SEARCH_ID = "catalogue-search";
const shortcutLabel = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌘K" : "Ctrl K";
const SEARCH_LIMIT = 100;

type Props = {
  rows: CatalogueRow[];
  viewKey: string;
  query: string;
  /** The query the rows were found for; it trails `query` while typing. */
  resultsQuery?: string;
  selectedKey: string | null;
  positions: Map<string, ListPosition>;
  loading: boolean;
  /** Why the catalogue could not be loaded, if it could not. */
  error?: string;
  /** The collection the tree is narrowed to. */
  collection?: { label: string; onClear: () => void };
  onQuery: (value: string) => void;
  onOpen: (node: ExplorerNode) => void;
  onToggle: (row: CatalogueRow) => void;
  onCollapseAll: () => void;
  activity?: ReadingActivitySource;
  onlineOnly?: boolean;
  onOnlineOnlyChange?: (value: boolean) => void;
  emptyMessage?: string;
  emptyAction?: { label: string; onClick: () => void };
  searchRef?: Ref<HTMLInputElement>;
};

/** The sidebar's catalogue category: search, then brokers, devices, topics and readings as a tree. */
export function CatalogueBrowser({ searchRef, ...props }: Props) {
  const { rows, query, selectedKey, positions, onlineOnly = false } = props;
  const heading = useId();
  const resultsQuery = props.resultsQuery ?? query;
  const searching = !!resultsQuery.trim();
  return <nav id="catalogue-browser" className="ex-sidebar app-sidebar-catalogue" aria-labelledby={heading}>
    <div className="app-sidebar-heading-row">
      <h2 id={heading} className="app-sidebar-heading">Catalogue</h2>
      {props.onOnlineOnlyChange && <button type="button" className="app-sidebar-tool" aria-label="Recently active"
        title="Show topics that received data recently" aria-pressed={onlineOnly} onClick={() => props.onOnlineOnlyChange?.(!onlineOnly)}>
        <ListFilter size={14} aria-hidden="true" />
      </button>}
      <button type="button" className="app-sidebar-tool" aria-label="Collapse all" title="Collapse all" onClick={props.onCollapseAll}>
        <ChevronsDownUp size={14} aria-hidden="true" />
      </button>
    </div>
    <div className="ex-search"><Search size={14} aria-hidden="true" />
      <input ref={searchRef} id={CATALOGUE_SEARCH_ID} type="search" aria-label="Search catalogue" placeholder="Search catalogue"
        value={query} aria-keyshortcuts="Control+K Meta+K" autoComplete="off" spellCheck={false}
        onChange={(event) => props.onQuery(event.target.value)} onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            event.currentTarget.closest("nav")?.querySelector<HTMLButtonElement>("[data-row][tabindex='0']")?.focus();
          }
          if (event.key === "Escape" && query) { event.preventDefault(); event.stopPropagation(); props.onQuery(""); }
        }} />
      {!query && <kbd className="ex-search-key" aria-hidden="true">{shortcutLabel}</kbd>}
    </div>
    {props.collection && !searching && <div className="app-sidebar-filter">
      <span title={props.collection.label}>In {props.collection.label}</span>
      <button type="button" className="app-sidebar-tool" aria-label="Show every source" title="Show every source" onClick={props.collection.onClear}>
        <X size={14} aria-hidden="true" />
      </button>
    </div>}
    {searching && !props.loading && <p className="ex-search-summary" role="status">
      {rows.length === SEARCH_LIMIT ? "First " : ""}{rows.length} {rows.length === 1 ? "match" : "matches"}
    </p>}
    {props.loading ? <div className="ex-list-empty" role="status">Loading catalogue…</div>
      : props.error ? <div className="ex-list-empty" role="alert">{props.error}</div>
        : <ExplorerList rows={rows} viewKey={props.viewKey} positions={positions} selectedKey={selectedKey}
          onOpen={props.onOpen} onToggle={searching ? undefined : props.onToggle} activity={props.activity}
          emptyMessage={props.emptyMessage} emptyAction={props.emptyAction} />}
    {searching && rows.length === SEARCH_LIMIT && <p className="ex-search-hint">Refine your search to see more matches.</p>}
  </nav>;
}
