import { useDeferredValue, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Search, Star } from "lucide-react";
import type { ActiveService } from "@/types/monitoring";
import { formatServiceTime, serviceName, serviceState, strategyName, type MonitoringIndex } from "./serviceModel";

type Props = {
  services: ActiveService[]; index: MonitoringIndex; ready: boolean; error: string;
  favourites: Set<string>; onFavourite: (id: string) => void; onOpen: (id: string) => void; onRetry: () => void;
};

export function MonitoringServiceList({ services, index, ready, error, favourites, onFavourite, onOpen, onRetry }: Props) {
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const [filter, setFilter] = useState("all");
  const scroll = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => services.map(service => {
    const inputs = index.inputs.get(service.id) ?? [];
    const name = serviceName(service, inputs);
    const paths = [...new Set(inputs.map(input => input.path))];
    const scope = paths.join(" · ") || `${service.mqtt_topics.length} ${service.mqtt_topics.length === 1 ? "input" : "inputs"}`;
    return { service, name, scope, state: serviceState(service), search: `${name} ${scope} ${service.model_type ?? ""} ${inputs.map(input => input.stream.label).join(" ")} ${service.mqtt_topics.join(" ")}`.toLocaleLowerCase() };
  }).sort((a, b) => a.name.localeCompare(b.name) || a.service.id.localeCompare(b.service.id)), [services, index]);
  const shown = useMemo(() => rows.filter(row => (!deferred || row.search.includes(deferred.toLocaleLowerCase()))
    && (filter === "all" || (filter === "favourites" ? favourites.has(row.service.id) : row.state.category === filter))), [rows, deferred, filter, favourites]);
  // Keep this imperative viewport adapter outside React Compiler memoization.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtual = useVirtualizer({ count: shown.length, getScrollElement: () => scroll.current, estimateSize: () => 76,
    getItemKey: position => shown[position]!.service.id, overscan: 6 });
  const filters = [{ id: "all", label: "All" }, { id: "monitoring", label: "Monitoring" }, { id: "preparing", label: "Preparing" }, { id: "stopped", label: "Stopped" },
    ...(filter === "attention" || rows.some(row => row.state.category === "attention") ? [{ id: "attention", label: "Attention" }] : []),
    ...(filter === "favourites" || favourites.size ? [{ id: "favourites", label: "Favourites" }] : [])];
  return <section className="mn-services" aria-label="Monitoring services">
    {error && <p className="ex-banner ex-error" role="alert">{error}<button onClick={onRetry}>Retry</button></p>}
    {!ready && !error ? <p className="mn-loading" role="status">Loading services…</p> : ready && !services.length ?
      <div className="mn-empty"><h2>No monitoring services</h2><p>Create a service to monitor readings from the catalogue.</p></div> : ready && <>
      <div className="mn-list-tools"><div className="mn-filters" aria-label="Filter services">
        {filters.map(item => <button key={item.id} aria-pressed={filter === item.id} onClick={() => { setFilter(item.id); scroll.current?.scrollTo?.(0, 0); }}>{item.label}</button>)}
      </div><label className="mn-search"><Search size={15} aria-hidden="true" /><input type="search" aria-label="Search monitoring services" placeholder="Find a service…" value={query}
        onChange={event => { setQuery(event.target.value); scroll.current?.scrollTo?.(0, 0); }} /></label></div>
      <div role="table" aria-label="Monitoring service list" aria-rowcount={shown.length + 1} aria-colcount={5}>
        <div className="mn-row mn-table-head" role="row"><span role="columnheader">Service</span><span role="columnheader">Inputs</span><span role="columnheader">State</span><span role="columnheader">Last update</span><span role="columnheader" className="ex-sr-only">Favourite</span></div>
        <div className="mn-table-scroll" ref={scroll} role="rowgroup" style={{ height: `min(${Math.max(1, shown.length) * 76}px, max(320px, calc(100dvh - 260px)))` }}>
          <div className="mn-virtual-rows" style={{ height: virtual.getTotalSize() }}>
            {virtual.getVirtualItems().map(item => {
              const row = shown[item.index]!; const service = row.service; const progress = service.operational_status.progress;
              return <div role="row" aria-rowindex={item.index + 2} className="mn-row mn-service-row" key={service.id} data-index={item.index} ref={virtual.measureElement} style={{ transform: `translateY(${item.start}px)` }}>
                <div role="cell" className="mn-service-identity"><Link title={row.name} data-service-index={item.index} to={`/?service=${encodeURIComponent(service.id)}`} onKeyDown={event => {
                  if (event.metaKey || event.ctrlKey || event.altKey || !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
                  event.preventDefault();
                  const next = event.key === "Home" ? 0 : event.key === "End" ? shown.length - 1 : Math.max(0, Math.min(shown.length - 1, item.index + (event.key === "ArrowDown" ? 1 : -1)));
                  virtual.scrollToIndex(next, { align: "auto" });
                  requestAnimationFrame(() => requestAnimationFrame(() => scroll.current?.querySelector<HTMLAnchorElement>(`[data-service-index="${next}"]`)?.focus()));
                }} onClick={event => {
                  if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                  event.preventDefault(); onOpen(service.id);
                }}>{row.name}</Link><small>{strategyName(service)}{service.model_type ? ` · ${service.model_type.replace(/^aberrant_/, "").replace(/_/g, " ")}` : ""}</small>
                  <small className="mn-mobile-scope" title={row.scope}>{row.scope}</small></div>
                <div role="cell" className="mn-service-inputs" title={row.scope}><span>{row.scope}</span><small>{service.mqtt_topics.length} {service.mqtt_topics.length === 1 ? "reading" : "readings"}</small></div>
                <div role="cell" className="mn-service-state"><span className={`mn-state mn-state--${row.state.tone}`}>{row.state.label}</span>
                  {progress && <small>{progress.current.toLocaleString()} / {progress.target.toLocaleString()} samples</small>}</div>
                <div role="cell" className="mn-service-time"><time dateTime={service.operational_status.updated_at ?? undefined}>{formatServiceTime(service.operational_status.updated_at)}</time>
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
