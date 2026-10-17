import { useDeferredValue, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import * as Popover from "@radix-ui/react-popover";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, Search } from "lucide-react";
import { readingActivity } from "../explorer/readingActivity";
import { useCatalogue } from "../workspace/catalogue-context";
import type { MonitoringTarget } from "./serviceModel";

const subscribeNothing = () => () => {};

export function MonitoringTargetPicker({ targets, value, disabled, onChange }: { targets: MonitoringTarget[]; value?: string; disabled?: boolean; onChange: (id: string) => void }) {
  const { system, telemetry, liveStreamIds } = useCatalogue();
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const [focus, setFocus] = useState(-1);
  const scroll = useRef<HTMLDivElement>(null);
  const liveStatus = useSyncExternalStore(open ? telemetry.subscribeUpdates : subscribeNothing, telemetry.getStatus);
  const activity = useMemo(() => ({ telemetry, liveStreamIds, runtime: system.snapshot?.runtime }), [telemetry, liveStreamIds, system.snapshot?.runtime]);
  useEffect(() => {
    if (!open) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [open]);
  const searchRows = useMemo(() => targets.map(target => ({ target, search: `${target.label} ${target.inputs.map(input => input.stream.label).join(" ")}`.toLocaleLowerCase() })), [targets]);
  const filtered = useMemo(() => searchRows.filter(row => row.search.includes(deferred.toLocaleLowerCase())
    && row.target.inputs.some(input => readingActivity({ streamIds: [input.stream.id], connectionId: input.stream.connection_id }, activity, liveStatus, now).receiving))
    .map(row => row.target), [searchRows, deferred, activity, liveStatus, now]);
  // Keep this imperative viewport adapter outside React Compiler memoization.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtual = useVirtualizer({ count: filtered.length, getScrollElement: () => scroll.current, estimateSize: () => 60, overscan: 5, getItemKey: index => filtered[index]!.id });
  const choose = (id: string) => { onChange(id); setOpen(false); };
  return <Popover.Root open={open} onOpenChange={next => { setOpen(next); if (next) { setNow(Date.now()); setQuery(""); setFocus(-1); } }}>
    <Popover.Trigger className="mn-target-trigger" disabled={disabled} aria-label="Choose monitoring inputs"><span>{targets.find(target => target.id === value)?.label ?? "Select an entity"}</span><ChevronDown size={14} /></Popover.Trigger>
    <Popover.Portal><Popover.Content className="ex-popover mn-target-popover" align="start" sideOffset={6} aria-label="Choose monitoring inputs">
      <label className="mn-target-search"><Search size={15} aria-hidden="true" /><input type="search" aria-label="Search entities" placeholder="Search entities…" value={query}
        onChange={event => { setQuery(event.target.value); setFocus(-1); scroll.current?.scrollTo?.(0, 0); }} onKeyDown={event => {
          if ((event.key === "ArrowDown" || event.key === "ArrowUp") && filtered.length) {
            event.preventDefault(); const next = Math.max(0, Math.min(filtered.length - 1, focus + (event.key === "ArrowDown" ? 1 : -1)));
            setFocus(next); virtual.scrollToIndex(next);
          } else if (event.key === "Enter" && filtered[Math.max(0, focus)]) { event.preventDefault(); choose(filtered[Math.max(0, focus)]!.id); }
        }} /></label>
      <div className="mn-target-scroll" ref={scroll} style={{ height: Math.min(300, Math.max(60, filtered.length * 60)) }}>
        <div className="mn-target-rows" style={{ height: virtual.getTotalSize() }}>
          {virtual.getVirtualItems().map(row => { const target = filtered[row.index]!;
            return <button key={target.id} className={focus === row.index ? "is-focused" : ""} aria-pressed={target.id === value} data-index={row.index}
              ref={virtual.measureElement} onMouseEnter={() => setFocus(row.index)} onClick={() => choose(target.id)} style={{ transform: `translateY(${row.start}px)` }}>
              <span title={target.label}>{target.label}</span><small>{target.inputs.length} {target.inputs.length === 1 ? "reading" : "readings"}</small>
            </button>; })}
        </div>{!filtered.length && <p className="ex-muted">{deferred ? "No matching inputs receiving data." : "No inputs receiving data."}</p>}
      </div>
    </Popover.Content></Popover.Portal>
  </Popover.Root>;
}
