import { useLayoutEffect, useRef, type KeyboardEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Box, ChevronRight, Cpu, Folder, Radio } from "lucide-react";
import type { ExplorerNode } from "./navigationIndex";

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
};

export function ExplorerList({ rows, viewKey, positions, selectedKey, onOpen, onBack, onBrowse }: Props) {
  const scroll = useRef<HTMLDivElement>(null);
  const position = positions.get(viewKey);
  // Keep this imperative viewport adapter outside React Compiler memoization.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length, getScrollElement: () => scroll.current,
    estimateSize: () => 72, overscan: 6, initialOffset: position?.offset ?? 0,
    getItemKey: (index) => rows[index]!.node.key,
  });
  const previousKey = useRef(viewKey);
  useLayoutEffect(() => {
    if (previousKey.current !== viewKey) {
      const reveal = previousKey.current.startsWith("search:") || previousKey.current.startsWith("catalogue:");
      const revealIndex = reveal ? rows.findIndex((row) => row.node.key === selectedKey) : -1;
      previousKey.current = viewKey;
      const saved = positions.get(viewKey);
      let focusFrame = 0;
      const frame = requestAnimationFrame(() => {
        if (revealIndex >= 0) virtualizer.scrollToIndex(revealIndex, { align: "auto" });
        else virtualizer.scrollToOffset(saved?.offset ?? 0);
        if (viewKey.startsWith("search:")) return;
        focusFrame = requestAnimationFrame(() => {
          const focusedIndex = revealIndex >= 0 ? revealIndex : rows.findIndex((row) => row.node.key === saved?.focused);
          const offset = scroll.current?.scrollTop ?? saved?.offset ?? 0;
          const visible = virtualizer.getVirtualItems().filter((item) => item.start + item.size > offset
            && item.start < offset + (scroll.current?.clientHeight || 360));
          const targetIndex = visible.some((item) => item.index === focusedIndex) ? focusedIndex : visible[0]?.index;
          const target = targetIndex !== undefined ? scroll.current?.querySelector<HTMLButtonElement>(`[data-row="${targetIndex}"]`) : null;
          target?.focus({ preventScroll: true });
        });
      });
      return () => { cancelAnimationFrame(frame); cancelAnimationFrame(focusFrame); };
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
      {virtualizer.getVirtualItems().map((item) => {
        const row = rows[item.index]!;
        const node = row.node;
        const Icon = node.kind === "connection" ? Box : node.kind === "device" ? Cpu : node.children.length ? Folder : Radio;
        return <li key={item.key} data-index={item.index} ref={virtualizer.measureElement}
          style={{ position: "absolute", width: "100%", transform: `translateY(${item.start}px)` }}>
          <div className="ex-row-container"><button className={`ex-row${selectedKey === node.key ? " is-selected" : ""}`} data-row={item.index}
            aria-current={selectedKey === node.key ? "true" : undefined}
            aria-label={`${row.label}${node.children.length ? ", open" : ", preview"}`}
            title={row.label} onClick={() => onOpen(node)} onKeyDown={(event) => keyboard(event, item.index)}
            onFocus={() => positions.set(viewKey, { offset: scroll.current?.scrollTop ?? 0, focused: node.key })}>
            <span className="ex-row-icon" style={row.color ? { color: row.color } : undefined}><Icon size={16} strokeWidth={1.6} /></span>
            <span className="ex-row-text"><span className="ex-row-label">{row.label}</span>
              <span className="ex-row-detail">{row.detail ?? (node.kind === "connection" ? `${node.streamIds.length} readings` : node.kind === "device" ? `${node.streamIds.length} readings` : node.children.length ? `${node.children.length} items` : "Reading")}</span>
            </span>
            {!onBrowse && node.children.length > 0 && <ChevronRight className="ex-row-arrow" size={14} />}
          </button>{onBrowse && node.children.length > 0 && <button className="ex-browse" aria-label={`Browse children of ${row.label}`} onClick={() => onBrowse(node)}><ChevronRight size={16} /></button>}</div>
        </li>;
      })}
    </ul>
    {!rows.length && <div className="ex-list-empty">No items here.</div>}
  </div>;
}
