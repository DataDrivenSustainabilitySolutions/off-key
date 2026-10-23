import { useDeferredValue, useEffect, useMemo, useRef } from "react";
import { useNavigationDraft } from "@/lib/navigation-draft";
import { Link } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Search, Star } from "lucide-react";
import type { ActiveService } from "@/types/monitoring";
import { RelativeTime } from "@/components/RelativeTime";
import { modelName, serviceName, serviceState, strategyName, type MonitoringIndex } from "@/domain/monitoring/serviceModel";

type Props = {
  draftKey?: string; services: ActiveService[]; index: MonitoringIndex; ready: boolean; error: string;
  favourites: Set<string>; onFavourite: (id: string) => void; onOpen: (id: string) => void; onRetry: () => void;
  serviceHref?: (id: string) => string;
};

export function MonitoringServiceList({ draftKey, services, index, ready, error, favourites, onFavourite, onOpen, onRetry, serviceHref }: Props) {
  const [query, setQuery] = useNavigationDraft(draftKey && `${draftKey}:query`, "");
  const deferred = useDeferredValue(query);
  const [filter, setFilter] = useNavigationDraft(draftKey && `${draftKey}:filter`, "all");
  const [offset, setOffset] = useNavigationDraft(draftKey && `${draftKey}:offset`, 0);
  const restored = useRef(false);
  const scroll = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => services.map(service => {
    const inputs = index.inputs.get(service.id) ?? [];
    const name = serviceName(service, inputs);
    const paths = [...new Set(inputs.map(input => input.path))];
    const scope = paths.join(" · ") || `${service.mqtt_topics.length} ${service.mqtt_topics.length === 1 ? "input" : "inputs"}`;
    const state = serviceState(service);
    // Problems first, then favourites, then everything else by name.
    const rank = state.category === "attention" ? 0 : favourites.has(service.id) ? 1 : 2;
    return { service, name, scope, state, rank, search: `${name} ${scope} ${service.model_type ?? ""} ${inputs.map(input => input.stream.label).join(" ")} ${service.mqtt_topics.join(" ")}`.toLocaleLowerCase() };
  }).sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name) || a.service.id.localeCompare(b.service.id)), [services, index, favourites]);
  const matching = useMemo(() => rows.filter(row => !deferred || row.search.includes(deferred.toLocaleLowerCase())), [rows, deferred]);
  const shown = useMemo(() => matching.filter(row => filter === "all" || (filter === "favourites" ? favourites.has(row.service.id) : row.state.category === filter)),
    [matching, filter, favourites]);
  const count = (id: string) => id === "all" ? matching.length
    : matching.filter(row => id === "favourites" ? favourites.has(row.service.id) : row.state.category === id).length;
  // Keep this imperative viewport adapter outside React Compiler memoization.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtual = useVirtualizer({ count: shown.length, getScrollElement: () => scroll.current, estimateSize: () => 76,
    getItemKey: position => shown[position]!.service.id, overscan: 6 });
  useEffect(() => {
    if (ready && scroll.current && !restored.current) { scroll.current.scrollTop = offset; restored.current = true; }
  }, [ready, offset]);
  const filters = [{ id: "all", label: "All" }, { id: "monitoring", label: "Active" }, { id: "preparing", label: "Preparing" }, { id: "stopped", label: "Stopped" },
    ...(filter === "attention" || rows.some(row => row.state.category === "attention") ? [{ id: "attention", label: "Attention" }] : []),
    ...(filter === "favourites" || favourites.size ? [{ id: "favourites", label: "Favourites" }] : [])];
  return <section className="mn-services" aria-label="Monitoring services">
    {error && <p className="ex-banner ex-error" role="alert">{error}<button onClick={onRetry}>Retry</button></p>}
    {!ready && !error ? <p className="mn-loading" role="status">Loading services…</p> : ready && !services.length ?
      <div className="mn-empty"><h2>No monitoring services</h2><p>Create a service to monitor readings from the catalogue.</p></div> : ready && <>
      <div className="mn-list-tools"><div className="mn-filters" aria-label="Filter services">
        {filters.map(item => {
          const total = count(item.id);
          return <button key={item.id} aria-pressed={filter === item.id} onClick={() => { setFilter(item.id); scroll.current?.scrollTo?.(0, 0); }}>
            {item.label} <span className={`mn-filter-count${item.id === "attention" && total > 0 ? " is-alert" : ""}`}>{total.toLocaleString()}</span></button>;
        })}
      </div><label className="mn-search"><Search size={15} aria-hidden="true" /><input type="search" aria-label="Search monitoring services" placeholder="Find a service…" value={query}
        onChange={event => { setQuery(event.target.value); scroll.current?.scrollTo?.(0, 0); }} /></label></div>
      <div role="table" aria-label="Monitoring service list" aria-rowcount={shown.length + 1} aria-colcount={5}>
        <div className="mn-row mn-table-head" role="row"><span role="columnheader">Service</span><span role="columnheader">Inputs</span><span role="columnheader">State</span><span role="columnheader">Last update</span><span role="columnheader" className="ex-sr-only">Favourite</span></div>
        <div className="mn-table-scroll" ref={scroll} onScroll={event => setOffset(event.currentTarget.scrollTop)} role="rowgroup" style={{ height: `min(${Math.max(76, virtual.getTotalSize())}px, max(320px, calc(100dvh - 260px)))` }}>
          <div className="mn-virtual-rows" style={{ height: virtual.getTotalSize() }}>
            {virtual.getVirtualItems().map(item => {
              const row = shown[item.index]!; const service = row.service; const progress = service.operational_status.progress;
              return <div role="row" aria-rowindex={item.index + 2} className="mn-row mn-service-row" key={service.id} data-index={item.index} ref={virtual.measureElement} style={{ transform: `translateY(${item.start}px)` }}>
                <div role="cell" className="mn-service-identity"><Link title={row.name} data-service-index={item.index} to={serviceHref?.(service.id) ?? `/?service=${encodeURIComponent(service.id)}`} onKeyDown={event => {
                  if (event.metaKey || event.ctrlKey || event.altKey || !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
                  event.preventDefault();
                  const next = event.key === "Home" ? 0 : event.key === "End" ? shown.length - 1 : Math.max(0, Math.min(shown.length - 1, item.index + (event.key === "ArrowDown" ? 1 : -1)));
                  virtual.scrollToIndex(next, { align: "auto" });
                  requestAnimationFrame(() => requestAnimationFrame(() => scroll.current?.querySelector<HTMLAnchorElement>(`[data-service-index="${next}"]`)?.focus()));
                }} onClick={event => {
                  if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                  event.preventDefault(); onOpen(service.id);
                }}>{row.name}</Link><small>{strategyName(service)}{service.model_type ? ` · ${modelName(service.model_type)}` : ""}</small>
                  <small className="mn-mobile-scope" title={row.scope}>{row.scope}</small></div>
                <div role="cell" className="mn-service-inputs" title={row.scope}><span>{row.scope}</span><small>{service.mqtt_topics.length} {service.mqtt_topics.length === 1 ? "reading" : "readings"}</small></div>
                <div role="cell" className="mn-service-state"><span className={`mn-state mn-state--${row.state.tone}`}>{row.state.label}</span>
                  {progress && <small>{progress.current.toLocaleString()} / {progress.target.toLocaleString()} samples</small>}</div>
                <div role="cell" className="mn-service-time"><RelativeTime value={service.operational_status.updated_at} fallback="Awaiting update" />
                  <small>{service.operational_status.processed_message_count.toLocaleString()} processed</small></div>
                <div role="cell"><button className="mn-favourite ex-icon-button" aria-pressed={favourites.has(service.id)} aria-label={`${favourites.has(service.id) ? "Remove" : "Add"} ${row.name} ${favourites.has(service.id) ? "from" : "to"} favourites`}
                  onClick={() => onFavourite(service.id)}><Star size={15} aria-hidden="true" /></button></div>
              </div>;
            })}
          </div>
          {!shown.length && <p className="mn-no-matches" role="status">No matching services.</p>}
        </div>
      </div><p className="mn-result-count" role="status">{shown.length.toLocaleString()} {shown.length === 1 ? "service" : "services"}</p>
    </>}
  </section>;
}
