import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Box, ChevronRight, Search } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { NavigationBar } from "@/components/NavigationBar";
import { PageHeader, PageShell } from "@/components/DashboardLayout";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useSystemDocument } from "@/features/catalogue/useSystemDocument";
import type { SystemDocument } from "@/features/catalogue/systemTypes";
import "./entities.css";

function directoryEntries(document: SystemDocument) {
  const brokers = new Map(document.connections.map((broker) => [broker.id, broker.label]));
  const readings = new Map<string, { count: number; topics: Set<string>; brokers: Set<string> }>();
  for (const stream of document.streams) {
    if (!stream.device_id) continue;
    let entry = readings.get(stream.device_id);
    if (!entry) { entry = { count: 0, topics: new Set(), brokers: new Set() }; readings.set(stream.device_id, entry); }
    entry.count++; entry.topics.add(JSON.stringify([stream.connection_id, stream.topic])); entry.brokers.add(stream.connection_id);
  }
  const order = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  return document.devices.map((entity) => {
    const entry = readings.get(entity.id);
    const connectionIds = new Set(entry?.brokers ?? []);
    if (entity.connection_id) connectionIds.add(entity.connection_id);
    const brokerNames = [...connectionIds].flatMap((id) => brokers.get(id) ?? []);
    return { entity, brokerNames, count: entry?.count ?? 0, topics: entry?.topics.size ?? 0,
      search: `${entity.label} ${entity.id} ${entity.kind} ${brokerNames.join(" ")}`.toLocaleLowerCase() };
  }).sort((a, b) => order.compare(a.entity.label, b.entity.label));
}

export default function Entities() {
  const { isAuthenticated, userId } = useAuth();
  const system = useSystemDocument({ isAuthenticated, accountKey: userId });
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const entries = useMemo(() => system.document ? directoryEntries(system.document) : [], [system.document]);
  const rows = useMemo(() => {
    const terms = deferred.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
    return terms.length ? entries.filter((entry) => terms.every((term) => entry.search.includes(term))) : entries;
  }, [entries, deferred]);
  const viewport = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({ count: rows.length, getScrollElement: () => viewport.current,
    estimateSize: () => 76, overscan: 6, getItemKey: (index) => rows[index]!.entity.id });
  useEffect(() => { virtualizer.scrollToOffset(0); }, [deferred, virtualizer]);
  return <>
    <NavigationBar />
    <PageShell>
      <PageHeader title="Entities" />
      {system.error && <p role="alert" className="directory-error">{system.error}<Button variant="ghost" onClick={() => void system.refresh()}>Retry</Button></p>}
      <div className="directory-toolbar">
        <label className="directory-search"><Search size={16} aria-hidden="true" /><Input type="search" aria-label="Search entities" placeholder="Search entities…" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        {system.document && <span className="directory-count" role="status">{rows.length.toLocaleString()} {rows.length === 1 ? "entity" : "entities"}</span>}
      </div>
      {system.status === "loading" ? <p className="directory-empty" role="status">Loading catalogue…</p>
        : !rows.length ? !system.error && <p className="directory-empty">{query ? "No matching entities" : "No entities"}</p>
          : <div className="directory-list" ref={viewport}>
            <ul aria-label="Entities" style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
              {virtualizer.getVirtualItems().map((item) => {
                const row = rows[item.index]!;
                return <li key={item.key} data-index={item.index} ref={virtualizer.measureElement} style={{ position: "absolute", width: "100%", transform: `translateY(${item.start}px)` }}>
                  <Link className="directory-row" to={`/?${new URLSearchParams({ entity: row.entity.id })}`} aria-label={`Open ${row.entity.label}`}>
                    <Box size={17} strokeWidth={1.6} aria-hidden="true" />
                    <div className="directory-identity"><strong title={row.entity.label}>{row.entity.label}</strong><span title={row.entity.id}>{row.entity.kind}</span></div>
                    <span className="directory-broker" title={row.brokerNames.join(", ")}>{row.brokerNames.join(", ") || "Unassigned"}</span>
                    <span className="directory-readings">{row.count.toLocaleString()} {row.count === 1 ? "reading" : "readings"}<span>{row.topics.toLocaleString()} {row.topics === 1 ? "topic" : "topics"}</span></span>
                    <ChevronRight size={15} aria-hidden="true" />
                  </Link>
                </li>;
              })}
            </ul>
          </div>}
    </PageShell>
  </>;
}
