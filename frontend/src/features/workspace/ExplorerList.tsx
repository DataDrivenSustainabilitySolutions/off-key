import { useNow } from "@/hooks/use-now";
import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type KeyboardEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronRight } from "lucide-react";
import { SourceIcon } from "@/components/source-icons/SourceIcon";
import type { ExplorerNode } from "@/domain/system/navigationIndex";
import { isReadingLeaf, readingActivity, type ReadingActivitySource } from "@/domain/system/readingActivity";
import type { CatalogueRow } from "./catalogue-tree";

export type ListPosition = { offset: number };
type Props = {
  rows: CatalogueRow[];
  /** Identifies what the list shows (the tree, a collection, a search); each keeps its own scroll position. */
  viewKey: string;
  positions: Map<string, ListPosition>;
  /** The source the page shows, which is not necessarily the focused or expanded row. */
  selectedKey: string | null;
  onOpen: (node: ExplorerNode) => void;
  /** Shows or hides a row's children. Expanding never changes the selected source. */
  onToggle?: (row: CatalogueRow) => void;
  activity?: ReadingActivitySource;
  emptyMessage?: string;
  emptyAction?: { label: string; onClick: () => void };
};

const TREE_ROW = 32;
const SEARCH_ROW = 48;
const subscribeNothing = () => () => {};
const noStatus = () => undefined;

/**
 * The sidebar's catalogue rows, virtualized for large catalogues. Rows are a
 * list of buttons with one tab stop; arrow keys move between them and open or
 * close branches like a file tree, while Enter shows the row's source.
 */
export function ExplorerList({ rows, viewKey, positions, selectedKey, onOpen, onToggle, activity, emptyMessage = "No items here.", emptyAction }: Props) {
  const scroll = useRef<HTMLDivElement>(null);
  const activityId = useId();
  const liveStatus = useSyncExternalStore(activity?.telemetry.subscribeUpdates ?? subscribeNothing, activity?.telemetry.getStatus ?? noStatus);
  const search = viewKey.startsWith("search:");
  const [activeKey, setActiveKey] = useState<string | null>(null);
  // Keep this imperative viewport adapter outside React Compiler memoization.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length, getScrollElement: () => scroll.current,
    estimateSize: () => search ? SEARCH_ROW : TREE_ROW, overscan: 8, initialOffset: positions.get(viewKey)?.offset ?? 0,
    getItemKey: (index) => rows[index]!.node.key,
  });
  const items = virtualizer.getVirtualItems();
  const hasIndicators = !!activity && items.some(item => isReadingLeaf(rows[item.index]!.node));
  const now = useNow(1000, hasIndicators);

  // Each view returns to where it was left: clearing a search restores the tree
  // as it was, unless the search chose a source, which the tree then reveals.
  const previousKey = useRef(viewKey);
  const frame = useRef(0);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
  useLayoutEffect(() => {
    if (previousKey.current === viewKey) return;
    const fromSearch = previousKey.current.startsWith("search:");
    previousKey.current = viewKey;
    cancelAnimationFrame(frame.current);
    const offset = positions.get(viewKey)?.offset ?? 0;
    const revealIndex = fromSearch ? rows.findIndex(row => row.node.key === selectedKey) : -1;
    frame.current = requestAnimationFrame(() => {
      virtualizer.scrollToOffset(offset);
      if (revealIndex >= 0) virtualizer.scrollToIndex(revealIndex, { align: "auto" });
    });
  }, [viewKey, virtualizer, positions, rows, selectedKey]);

  // A source chosen elsewhere (a deep link, the page, a favourite) is revealed
  // once its branch is open, without moving focus.
  const revealed = useRef<string | null>(null);
  useEffect(() => {
    if (!selectedKey || revealed.current === selectedKey) return;
    const index = rows.findIndex(row => row.node.key === selectedKey);
    if (index < 0) return;
    revealed.current = selectedKey;
    virtualizer.scrollToIndex(index, { align: "auto" });
  }, [selectedKey, rows, virtualizer]);

  const focusRow = (index: number) => {
    const bounded = Math.max(0, Math.min(rows.length - 1, index));
    virtualizer.scrollToIndex(bounded, { align: "auto" });
    setActiveKey(rows[bounded]?.node.key ?? null);
    requestAnimationFrame(() => scroll.current?.querySelector<HTMLButtonElement>(`[data-row="${bounded}"]`)?.focus());
  };
  const keyboard = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const row = rows[index]!;
    const movements: Record<string, number> = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: rows.length - 1 };
    if (event.key in movements) {
      event.preventDefault(); focusRow(movements[event.key]!);
    } else if (event.key === "ArrowRight" && row.expandable) {
      event.preventDefault();
      if (row.expanded) focusRow(index + 1);
      else onToggle?.(row);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      if (row.expanded) { onToggle?.(row); return; }
      for (let parent = index - 1; parent >= 0; parent -= 1) {
        if (rows[parent]!.depth < row.depth) { focusRow(parent); return; }
      }
    }
  };
  // One tab stop: the row last focused, else the selected row, else the first one shown.
  const shown = items.map(item => rows[item.index]!.node.key);
  const tabbable = [activeKey, selectedKey].find(key => key && shown.includes(key)) ?? shown[0];

  return <div className="ex-list-scroll" ref={scroll} onScroll={(event) => {
    if (positions.size > 256 && !positions.has(viewKey)) positions.delete(positions.keys().next().value!);
    positions.set(viewKey, { offset: event.currentTarget.scrollTop });
  }}>
    <ul key={viewKey} className={`ex-list${search ? " is-search" : ""}`} aria-label={search ? "Search results" : "Catalogue items"}
      style={{ height: virtualizer.getTotalSize() }}>
      {items.map((item) => {
        const row = rows[item.index]!;
        const node = row.node;
        const indicator = isReadingLeaf(node) ? readingActivity(node, activity, liveStatus, now) : undefined;
        const descriptionId = `${activityId}-${item.index}`;
        const selected = selectedKey === node.key;
        return <li key={item.key} data-index={item.index} ref={virtualizer.measureElement} aria-level={row.depth + 1}
          style={{ position: "absolute", width: "100%", transform: `translateY(${item.start}px)` }}>
          <div className={`ex-row-container${selected ? " is-selected" : ""}`} style={{ "--ex-depth": row.depth } as CSSProperties}>
            {row.expandable && onToggle
              ? <button type="button" className="ex-disclosure" tabIndex={-1} aria-expanded={row.expanded}
                aria-label={`${row.expanded ? "Collapse" : "Expand"} ${row.label}`} onClick={() => onToggle(row)}>
                <ChevronRight size={14} aria-hidden="true" />
              </button>
              : <span className="ex-disclosure" aria-hidden="true" />}
            <button type="button" className={`ex-row${selected ? " is-selected" : ""}`} data-row={item.index}
              tabIndex={node.key === tabbable ? 0 : -1}
              aria-current={selected ? "true" : undefined}
              aria-expanded={row.expandable && onToggle ? row.expanded : undefined}
              aria-label={`${row.label}${node.children.length ? ", open" : ", preview"}`}
              aria-describedby={indicator ? descriptionId : undefined}
              title={row.path} onClick={() => { setActiveKey(node.key); onOpen(node); }} onKeyDown={(event) => keyboard(event, item.index)}
              onFocus={() => setActiveKey(node.key)}>
              <span className="ex-row-icon" title={indicator?.label}>
                <SourceIcon kind={node.entityKind ?? node.kind} appearance={node.appearance} color={row.color ?? node.color} />
                {indicator && <><span className={`source-activity-dot${indicator.receiving ? " is-receiving" : ""}`} aria-hidden="true" />
                  <span id={descriptionId} className="ex-sr-only">{indicator.label}</span></>}
              </span>
              <span className="ex-row-text"><span className="ex-row-label">{row.label}</span>
                {row.detail && <span className="ex-row-detail">{row.detail}</span>}
              </span>
            </button>
          </div>
        </li>;
      })}
    </ul>
    {!rows.length && <div className="ex-list-empty"><p>{emptyMessage}</p>
      {emptyAction && <button type="button" className="ex-empty-action" onClick={emptyAction.onClick}>{emptyAction.label}</button>}
    </div>}
  </div>;
}
