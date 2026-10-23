import { useNow } from "@/hooks/use-now";
import { useEffect, useId, useLayoutEffect, useRef, useSyncExternalStore, type KeyboardEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Box, ChevronRight, Circle, Cpu, Folder } from "lucide-react";
import type { ExplorerNode } from "@/domain/system/navigationIndex";
import { isReadingLeaf, readingActivity, type ReadingActivitySource } from "@/domain/system/readingActivity";

export type ExplorerRow = { node: ExplorerNode; label: string; detail?: string; color?: string };
export type ListPosition = { offset: number; focused?: string };
type Props = {
  rows: ExplorerRow[];
  viewKey: string;
  positions: Map<string, ListPosition>;
  selectedKey: string | null;
  onOpen: (node: ExplorerNode) => void;
  onBack: () => void;
  onBrowse?: (node: ExplorerNode) => void;
  activity?: ReadingActivitySource;
  emptyMessage?: string;
  emptyAction?: { label: string; onClick: () => void };
};

const subscribeNothing = () => () => {};
const noStatus = () => undefined;
export function ExplorerList({ rows, viewKey, positions, selectedKey, onOpen, onBack, onBrowse, activity, emptyMessage = "No items here.", emptyAction }: Props) {
  const scroll = useRef<HTMLDivElement>(null);
  const activityId = useId();
  const liveStatus = useSyncExternalStore(activity?.telemetry.subscribeUpdates ?? subscribeNothing, activity?.telemetry.getStatus ?? noStatus);
  const position = positions.get(viewKey);
  // Keep this imperative viewport adapter outside React Compiler memoization.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length, getScrollElement: () => scroll.current,
    estimateSize: () => 72, overscan: 6, initialOffset: position?.offset ?? 0,
    getItemKey: (index) => rows[index]!.node.key,
  });
  const items = virtualizer.getVirtualItems();
  const hasIndicators = !!activity && items.some(item => isReadingLeaf(rows[item.index]!.node));
  const now = useNow(1000, hasIndicators);
  const previousKey = useRef(viewKey);
  // Pending restoration survives re-renders of the same view (new rows, a clock
  // tick) and is cancelled only by the next view change or unmount.
  const restoration = useRef<number[]>([]);
  useEffect(() => () => restoration.current.forEach(cancelAnimationFrame), []);
  useLayoutEffect(() => {
    if (previousKey.current !== viewKey) {
      restoration.current.forEach(cancelAnimationFrame);
      const reveal = previousKey.current.startsWith("search:") || previousKey.current.startsWith("catalogue:");
      const revealIndex = reveal ? rows.findIndex((row) => row.node.key === selectedKey) : -1;
      previousKey.current = viewKey;
      const saved = positions.get(viewKey);
      const focusOrigin = document.activeElement;
      restoration.current = [requestAnimationFrame(() => {
        if (revealIndex >= 0) virtualizer.scrollToIndex(revealIndex, { align: "auto" });
        else virtualizer.scrollToOffset(saved?.offset ?? 0);
        if (viewKey.startsWith("search:")) return;
        restoration.current = [requestAnimationFrame(() => {
          // A later focus choice takes precedence over deferred restoration.
          if (document.activeElement !== focusOrigin && document.activeElement !== document.body) return;
          const focusedIndex = revealIndex >= 0 ? revealIndex : rows.findIndex((row) => row.node.key === saved?.focused);
          const offset = scroll.current?.scrollTop ?? saved?.offset ?? 0;
          const visible = virtualizer.getVirtualItems().filter((item) => item.start + item.size > offset
            && item.start < offset + (scroll.current?.clientHeight || 360));
          const targetIndex = visible.some((item) => item.index === focusedIndex) ? focusedIndex : visible[0]?.index;
          const target = targetIndex !== undefined ? scroll.current?.querySelector<HTMLButtonElement>(`[data-row="${targetIndex}"]`) : null;
          target?.focus({ preventScroll: true });
        })];
      })];
    }
  }, [viewKey, virtualizer, positions, rows, selectedKey]);
  const focusRow = (index: number) => {
    const bounded = Math.max(0, Math.min(rows.length - 1, index));
    virtualizer.scrollToIndex(bounded, { align: "auto" });
    requestAnimationFrame(() => scroll.current?.querySelector<HTMLButtonElement>(`[data-row="${bounded}"]`)?.focus());
  };
  const keyboard = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const movements: Record<string, number> = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: rows.length - 1 };
    if (event.key in movements) {
      event.preventDefault(); focusRow(movements[event.key]!);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault(); onBack();
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      const node = rows[index]!.node;
      (onBrowse && node.children.length ? onBrowse : onOpen)(node);
    }
  };
  return <div className="ex-list-scroll" ref={scroll} onScroll={(event) => {
    if (positions.size > 256 && !positions.has(viewKey)) positions.delete(positions.keys().next().value!);
    positions.set(viewKey, { ...positions.get(viewKey), offset: event.currentTarget.scrollTop });
  }}>
    <ul key={viewKey} className={`ex-list${viewKey.startsWith("search:") ? " is-search" : ""}`} aria-label="Catalogue items" style={{ height: virtualizer.getTotalSize() }}>
      {items.map((item) => {
        const row = rows[item.index]!;
        const node = row.node;
        const Icon = node.kind === "connection" ? Box : node.kind === "device" ? Cpu : Folder;
        const indicator = isReadingLeaf(node) ? readingActivity(node, activity, liveStatus, now) : undefined;
        const descriptionId = `${activityId}-${item.index}`;
        return <li key={item.key} data-index={item.index} ref={virtualizer.measureElement}
          style={{ position: "absolute", width: "100%", transform: `translateY(${item.start}px)` }}>
          <div className="ex-row-container"><button className={`ex-row${selectedKey === node.key ? " is-selected" : ""}`} data-row={item.index}
            aria-current={selectedKey === node.key ? "true" : undefined}
            aria-label={`${row.label}${node.children.length ? ", open" : ", preview"}`}
            aria-describedby={indicator ? descriptionId : undefined}
            title={row.label} onClick={() => onOpen(node)} onKeyDown={(event) => keyboard(event, item.index)}
            onFocus={() => positions.set(viewKey, { offset: scroll.current?.scrollTop ?? 0, focused: node.key })}>
            <span className={`ex-row-icon${indicator ? " ex-reading-activity" : ""}`} title={indicator?.label}
              style={!indicator && row.color ? { color: row.color } : undefined}>
              {indicator ? <><Circle size={16} strokeWidth={1.6} fill={indicator.receiving ? "currentColor" : "none"} aria-hidden="true" />
                <span id={descriptionId} className="ex-sr-only">{indicator.label}</span></> : <Icon size={16} strokeWidth={1.6} />}
            </span>
            <span className="ex-row-text"><span className="ex-row-label">{row.label}</span>
              <span className="ex-row-detail">{row.detail ?? (node.kind === "connection" ? `${node.streamIds.length} readings` : node.kind === "device" ? `${node.streamIds.length} readings` : node.children.length ? `${node.children.length} items` : "Reading")}</span>
            </span>
            {!onBrowse && node.children.length > 0 && <ChevronRight className="ex-row-arrow" size={14} />}
          </button>{onBrowse && node.children.length > 0 && <button className="ex-browse" aria-label={`Browse children of ${row.label}`} onClick={() => onBrowse(node)}><ChevronRight size={16} /></button>}</div>
        </li>;
      })}
    </ul>
    {!rows.length && <div className="ex-list-empty"><p>{emptyMessage}</p>
      {emptyAction && <button type="button" className="ex-empty-action" onClick={emptyAction.onClick}>{emptyAction.label}</button>}
    </div>}
  </div>;
}
