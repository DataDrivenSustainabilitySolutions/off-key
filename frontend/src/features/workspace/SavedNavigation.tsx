import { useId, useMemo, type ReactNode } from "react";
import { ChevronRight, Cpu, Folder, Star } from "lucide-react";
import type { ExplorerNode } from "@/domain/system/navigationIndex";
import { catalogueLocation } from "./catalogue-tree";
import { useCatalogue } from "./catalogue-context";
import type { SidebarSection } from "./preferences";

/** A sidebar category whose items fold away under its heading. */
function Category({ section, title, count, children }: { section: SidebarSection; title: string; count: number; children: ReactNode }) {
  const { sectionOpen, setSectionOpen } = useCatalogue();
  const body = useId();
  const open = sectionOpen(section);
  return <section className="app-sidebar-category" aria-label={title}>
    <button type="button" className="app-sidebar-category-toggle" aria-expanded={open} aria-controls={body}
      onClick={() => setSectionOpen(section, !open)}>
      <span className="app-sidebar-heading">{title}</span>
      <span className="app-sidebar-count" aria-label={`${count} ${count === 1 ? "item" : "items"}`}>{count}</span>
      <ChevronRight className="app-sidebar-chevron" size={14} aria-hidden="true" />
    </button>
    <ul id={body} className="app-sidebar-items" hidden={!open}>{children}</ul>
  </section>;
}

/**
 * Favourites and shared collections. A favourite shows its source, as a catalogue
 * row does. A collection narrows the catalogue tree to its members and changes
 * nothing on the page.
 */
export function SavedNavigation({ onNavigate }: { onNavigate?: () => void }) {
  const { document, index, favourites, selected, selectSource, collection, showCollection, setQuery } = useCatalogue();
  const streams = useMemo(() => new Map(document.readings.map(stream => [stream.id, stream])), [document.readings]);
  const starred = favourites.flatMap(item => {
    if (item.kind === "monitor") return [];
    const node = index.nodes.get(index.objectKeys.get(item.id)?.[0] ?? "");
    if (!node || (item.kind === "reading") !== (node.entityKind === "stream")) return [];
    return [{ item, node, label: item.kind === "reading" ? streams.get(item.id)?.label ?? node.label : node.label }];
  });
  const open = (node: ExplorerNode) => { selectSource(node); onNavigate?.(); };
  return <>
    {starred.length > 0 && <Category section="favourites" title="Favourites" count={starred.length}>
      {starred.map(({ item, node, label }) => <li key={`${item.kind}:${item.id}`}>
        <button type="button" className="app-sidebar-item" aria-current={selected?.key === node.key ? "true" : undefined}
          title={[label, catalogueLocation(index, node)].filter(Boolean).join(" — ")} onClick={() => open(node)}>
          {item.kind === "device" ? <Cpu size={16} strokeWidth={1.6} aria-hidden="true" /> : <Star size={16} strokeWidth={1.6} aria-hidden="true" />}
          <span>{label}</span>
        </button>
      </li>)}
    </Category>}
    {document.groups.length > 0 && <Category section="collections" title="Collections" count={document.groups.length}>
      {document.groups.map(group => <li key={group.id}>
        <button type="button" className="app-sidebar-item" aria-pressed={collection?.id === group.id}
          aria-label={`Show collection ${group.label}`} title={`${group.label}: show its ${group.member_ids.length} sources in the catalogue`}
          onClick={() => { setQuery(""); showCollection(collection?.id === group.id ? null : group.id); }}>
          <Folder size={16} strokeWidth={1.6} aria-hidden="true" style={group.color ? { color: group.color } : undefined} />
          <span>{group.label}</span><small aria-hidden="true">{group.member_ids.length}</small>
        </button>
      </li>)}
    </Category>}
  </>;
}
