import { Layers, LockKeyhole, Trash2, UnlockKeyhole } from "lucide-react";
import type { SpatialGroup, SpatialWorkspace } from "./types";

type Props = {
  group: SpatialGroup;
  workspace: SpatialWorkspace;
  onChange: (workspace: SpatialWorkspace) => void;
  memberCount?: number;
  rate?: number;
};

export function CollectionInspector({
  group,
  workspace,
  onChange,
  memberCount,
  rate,
}: Props) {
  const update = (changes: Partial<SpatialGroup>) =>
    onChange({
      ...workspace,
      groups: workspace.groups.map((item) =>
        item.id === group.id ? { ...item, ...changes } : item,
      ),
    });
  const canDelete =
    group.id.startsWith("custom-") &&
    memberCount === 0 &&
    workspace.groups.length > 1;

  return (
    <div className="sp-preferences">
      <span className="sp-object-glyph" style={{ color: group.color }}>
        <Layers size={24} />
      </span>
      <h2>{group.name}</h2>
      {(memberCount !== undefined || rate !== undefined) && (
        <div className="sp-inspector-metrics">
          <div>
            <span>Objects</span>
            <strong>{memberCount ?? "—"}</strong>
          </div>
          <div>
            <span>Stream arrivals</span>
            <strong>
              {rate === undefined
                ? "—"
                : new Intl.NumberFormat("en", {
                    maximumFractionDigits: 1,
                  }).format(rate)}
              <small> msg/s</small>
            </strong>
          </div>
        </div>
      )}
      <label>
        Collection name
        <input
          aria-label="Collection name"
          value={group.name}
          maxLength={40}
          onChange={(event) => update({ name: event.target.value })}
          onBlur={() => {
            if (!group.name.trim()) update({ name: "Untitled collection" });
          }}
        />
      </label>
      <label className="sp-color-field">
        Collection colour
        <input
          aria-label="Collection colour"
          type="color"
          value={group.color}
          onChange={(event) => update({ color: event.target.value })}
        />
      </label>
      <p>
        Colour identifies a collection. Freshness and detection state remain
        separate.
      </p>
      <button
        className="sp-wide-button"
        aria-pressed={group.locked}
        onClick={() => update({ locked: !group.locked })}
      >
        {group.locked ? <UnlockKeyhole size={15} /> : <LockKeyhole size={15} />}
        {group.locked ? "Unlock collection" : "Lock collection"}
      </button>
      <button
        className="sp-wide-button"
        aria-expanded={!group.collapsed}
        onClick={() => update({ collapsed: !group.collapsed })}
      >
        {group.collapsed ? "Expand collection" : "Collapse collection"}
      </button>
      <p>
        Drag the collection tile in Arrange mode to move it. Individually pinned
        members stay in place.
      </p>
      {canDelete && (
        <button
          className="sp-wide-button"
          onClick={() =>
            onChange({
              ...workspace,
              groups: workspace.groups.filter((item) => item.id !== group.id),
              memberships: Object.fromEntries(
                Object.entries(workspace.memberships).filter(
                  ([, groupId]) => groupId !== group.id,
                ),
              ),
            })
          }
        >
          <Trash2 size={15} />
          Delete empty collection
        </button>
      )}
    </div>
  );
}
