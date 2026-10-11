import {
  Activity,
  Box,
  ChevronDown,
  ChevronRight,
  Plus,
  Radio,
  PlugZap,
  Search,
  Settings2,
} from "lucide-react";
import type { SpatialNode, SpatialWorkspace } from "./types";

type Props = {
  workspace: SpatialWorkspace;
  nodes: readonly SpatialNode[];
  query: string;
  groupEditor: string | null;
  selectedId: string | null;
  displayNodes: readonly SpatialNode[];
  matchCount: number;
  paused: boolean;
  status: string;
  source: "demo" | "hsl" | "ambibox";
  onQueryChange: (query: string) => void;
  onCreateCollection: () => void;
  onSelectGroup: (id: string) => void;
  onSelectNode: (id: string) => void;
  onChange: (workspace: SpatialWorkspace) => void;
};

export function SpatialSidebar({
  workspace,
  nodes,
  query,
  groupEditor,
  selectedId,
  displayNodes,
  matchCount,
  paused,
  status,
  source,
  onQueryChange,
  onCreateCollection,
  onSelectGroup,
  onSelectNode,
  onChange,
}: Props) {
  const fleetOverview = source === "ambibox" && !query.trim();
  const listedCount = fleetOverview
    ? nodes.filter((node) => node.kind === "charger").length
    : matchCount;
  const chargerLabels = new Map(
    nodes
      .filter((node) => node.kind === "charger")
      .map((node) => [node.catalog?.chargerId, node.label]),
  );
  return (
    <aside className="sp-sidebar">
      <div className="sp-sidebar-heading">
        <span className="sp-overline">Workspace</span>
        <Settings2 size={15} />
      </div>
      <h1>Your connected system.</h1>
      <p className="sp-sidebar-description">
        A place for every stream.
        <br />A clear view of what is moving.
      </p>
      <label className="sp-search">
        <Search size={15} />
        <input
          aria-label="Find an object"
          placeholder="Find an object…"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <span>⌕</span>
      </label>
      <div className="sp-section-title">
        <h2>Collections</h2>
        <button aria-label="Create collection" onClick={onCreateCollection}>
          <Plus size={16} />
        </button>
      </div>
      <div className="sp-groups">
        {workspace.groups.map((group) => {
          const members = nodes.filter(
            (node) =>
              (workspace.memberships[node.id] ?? node.groupId) === group.id,
          ).length;
          return (
            <div
              className={`sp-group-row ${groupEditor === group.id ? "is-active" : ""}`}
              key={group.id}
            >
              <button
                className="sp-collapse"
                aria-label={`${group.collapsed ? "Expand" : "Collapse"} ${group.name}`}
                onClick={() =>
                  onChange({
                    ...workspace,
                    groups: workspace.groups.map((item) =>
                      item.id === group.id
                        ? { ...item, collapsed: !item.collapsed }
                        : item,
                    ),
                  })
                }
              >
                {group.collapsed ? (
                  <ChevronRight size={13} />
                ) : (
                  <ChevronDown size={13} />
                )}
              </button>
              <button
                className="sp-group-name"
                onClick={() => onSelectGroup(group.id)}
              >
                <i style={{ background: group.color }} />
                <span>{group.name}</span>
                <small>{members}</small>
              </button>
            </div>
          );
        })}
      </div>
      <div className="sp-section-title sp-object-heading">
        <h2>{fleetOverview ? "Chargers" : query ? "Results" : "Objects"}</h2>
        <span>{listedCount}</span>
      </div>
      <div className="sp-object-list">
        {displayNodes.map((node) => {
          const owner =
            source === "ambibox" && !fleetOverview && node.kind === "sensor"
              ? chargerLabels.get(node.catalog?.chargerId)
              : undefined;
          return (
            <button
              className={`sp-object-row ${selectedId === node.id ? "is-active" : ""}`}
              key={node.id}
              aria-label={owner ? `${node.label} · ${owner}` : node.label}
              title={owner ? `${node.label} · ${owner}` : node.label}
              onClick={() => onSelectNode(node.id)}
            >
              {node.kind === "broker" ? (
                <Box size={15} />
              ) : node.kind === "charger" ? (
                <PlugZap size={15} />
              ) : (
                <Radio size={15} />
              )}
              <span>
                {node.label}
                {owner && <small>{owner}</small>}
              </span>
            </button>
          );
        })}
        {listedCount > displayNodes.length && (
          <p className="sp-list-limit">
            Showing {displayNodes.length} objects. Search to find any of the{" "}
            {listedCount}.
          </p>
        )}
        {!listedCount && <p className="sp-list-limit">No matching objects.</p>}
      </div>
      <div className="sp-sidebar-bottom">
        <span className="sp-source-icon">
          <Activity size={15} />
        </span>
        <div>
          <strong>{paused ? "Stream paused" : status}</strong>
          <span>
            {source === "ambibox"
              ? "Private catalog · no live connection"
              : source === "demo"
                ? "Local simulator · no backend required"
                : "HSL open data · CC BY 4.0"}
          </span>
        </div>
      </div>
    </aside>
  );
}
