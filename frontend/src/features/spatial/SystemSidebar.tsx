import { useMemo } from "react";
import { Box, Cpu, Plus, Radio, Search } from "lucide-react";
import { PersonalGroups } from "./PersonalGroupControls";
import type { SystemDocument, SystemEntityKind } from "./systemTypes";
import type { SpatialNode, SpatialWorkspace } from "./types";
export type SystemFilter = "overview" | "connection" | "device" | "stream";
type Props = {
  document: SystemDocument;
  workspace: SpatialWorkspace;
  nodes: SpatialNode[];
  query: string;
  filter: SystemFilter;
  selectedId: string | null;
  selectedGroup: string | null;
  personalGroupId?: string | null;
  canEdit: boolean;
  saved: boolean;
  onQuery: (query: string) => void;
  onFilter: (filter: SystemFilter) => void;
  onSelect: (id: string) => void;
  onGroup: (id: string) => void;
  onPersonalGroup?: (id: string | null) => void;
  onCreate: (kind: SystemEntityKind) => void;
  onLayout: (workspace: SpatialWorkspace) => void;
};
export function SystemSidebar({
  document,
  workspace,
  nodes,
  query,
  filter,
  selectedId,
  selectedGroup,
  personalGroupId = null,
  canEdit,
  saved,
  onQuery,
  onFilter,
  onSelect,
  onGroup,
  onPersonalGroup,
  onCreate,
  onLayout,
}: Props) {
  const defaultKind = document.devices.length ? "device" : "connection";
  const activeFilter = filter === "overview" ? defaultKind : filter;
  const needle = query.trim().toLowerCase();
  const devices = useMemo(
    () => new Map(document.devices.map((item) => [item.id, item.label])),
    [document.devices],
  );
  const groups = useMemo(
    () => new Map(document.groups.map((item) => [item.id, item])),
    [document.groups],
  );
  const connections = useMemo(
    () => new Map(document.connections.map((item) => [item.id, item.label])),
    [document.connections],
  );
  const sourceCounts = useMemo(() => {
    const counts = new Map<string, { topics: Set<string>; readings: number }>();
    for (const stream of document.streams) {
      for (const id of [stream.connection_id, stream.device_id]) {
        if (!id) continue;
        const count = counts.get(id) ?? {
          topics: new Set<string>(),
          readings: 0,
        };
        count.readings += 1;
        count.topics.add(JSON.stringify([stream.connection_id, stream.topic]));
        counts.set(id, count);
      }
    }
    return counts;
  }, [document.streams]);
  const ownerLabel = (node: SpatialNode) => {
    if (node.system?.kind !== "stream") return "";
    const device = node.system.deviceId
      ? devices.get(node.system.deviceId)
      : undefined;
    return (
      device ??
      (node.system.connectionId
        ? (connections.get(node.system.connectionId) ?? "")
        : "")
    );
  };
  const matches = nodes.filter((node) => {
    if (!needle) return node.system?.kind === activeFilter;
    const owner = ownerLabel(node);
    return [node.label, node.system?.topic, node.system?.category, owner].some(
      (value) => value?.toLowerCase().includes(needle),
    );
  });
  const counts = {
    connection: document.connections.length,
    device: document.devices.length,
    stream: document.streams.length,
  };
  const titles = {
    connection: "Connections",
    device: "Devices",
    stream: "Streams",
  };
  return (
    <aside className="sp-sidebar">
      <div className="sp-sidebar-heading">
        <span className="sp-overline">Workspace</span>
        <Box size={15} />
      </div>
      <h1>Your connected system.</h1>
      <p className="sp-sidebar-description">
        A place for every stream.
        <br />A clear view of your structure.
      </p>
      <label className="sp-search">
        <Search size={15} />
        <input
          aria-label="Find an object"
          placeholder="Find an object…"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
      </label>
      {onPersonalGroup && (
        <PersonalGroups
          workspace={workspace}
          selectedId={selectedId}
          selectedGroupId={personalGroupId}
          onChange={onLayout}
          onSelectGroup={onPersonalGroup}
        />
      )}
      <div className="sp-section-title">
        <h2>Catalog groups</h2>
        <button
          aria-label="Add catalog group"
          disabled={!canEdit}
          onClick={() => onCreate("group")}
        >
          <Plus size={16} />
        </button>
      </div>
      <div className="sp-groups">
        {workspace.groups
          .filter((group) => groups.has(group.id))
          .map((group) => (
            <div
              className={`sp-group-row ${selectedGroup === group.id ? "is-active" : ""}`}
              key={group.id}
            >
              <button
                className="sp-group-name"
                onClick={() => onGroup(group.id)}
              >
                <i style={{ background: group.color }} />
                <span>{group.name}</span>
                <small>{groups.get(group.id)?.member_ids.length ?? 0}</small>
              </button>
            </div>
          ))}
      </div>
      <div className="sp-system-filters">
        {(["connection", "device", "stream"] as const).map((kind) => (
          <button
            key={kind}
            aria-pressed={activeFilter === kind}
            onClick={() => {
              onFilter(kind);
              onQuery("");
            }}
          >
            {titles[kind]}
            <small>{counts[kind]}</small>
          </button>
        ))}
      </div>
      <div className="sp-section-title sp-object-heading">
        <h2>{needle ? "Results" : titles[activeFilter]}</h2>
        <button
          aria-label={`Add ${activeFilter}`}
          disabled={
            !canEdit ||
            (activeFilter === "stream" && !document.connections.length)
          }
          onClick={() => onCreate(activeFilter)}
        >
          <Plus size={16} />
        </button>
      </div>
      <div className="sp-object-list">
        {matches.slice(0, 40).map((node) => {
          const owner = ownerLabel(node);
          const count = sourceCounts.get(node.id);
          const context =
            owner ||
            (count
              ? `${count.topics.size} topics · ${count.readings} readings`
              : "");
          const title = owner ? `${node.label} · ${owner}` : node.label;
          return (
            <button
              className={`sp-object-row ${selectedId === node.id ? "is-active" : ""}`}
              key={node.id}
              aria-label={title}
              title={title}
              onClick={() => onSelect(node.id)}
            >
              {node.kind === "broker" ? (
                <Box size={15} />
              ) : node.kind === "device" ? (
                <Cpu size={15} />
              ) : (
                <Radio size={15} />
              )}
              <span>
                {node.label}
                {context && <small>{context}</small>}
              </span>
            </button>
          );
        })}
        {matches.length > 40 && (
          <p className="sp-list-limit">
            Showing 40 of {matches.length}. Search to find any object.
          </p>
        )}
        {!matches.length && (
          <p className="sp-list-limit">
            {needle ? "No matching objects." : "Add an object to begin."}
          </p>
        )}
      </div>
      <div className="sp-sidebar-bottom">
        <span className="sp-source-icon">
          <Box size={15} />
        </span>
        <div>
          <strong>{saved ? "Saved system" : "System definition"}</strong>
          <span>Saved structure · live preview</span>
        </div>
      </div>
    </aside>
  );
}
