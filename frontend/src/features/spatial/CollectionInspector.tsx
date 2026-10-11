import { PlugZap, Layers, Trash2 } from "lucide-react";
import type { SpatialGroup, SpatialWorkspace, SpatialNode } from "./types";
import { InlineName } from "./InlineName";

type Props = {
  group: SpatialGroup;
  workspace: SpatialWorkspace;
  onChange: (workspace: SpatialWorkspace) => void;
  memberCount?: number;
  rate?: number;
  previewOnly?: boolean;
  members?: readonly SpatialNode[];
  onSelectMember?: (id: string) => void;
  onRename?: (name: string) => Promise<void>;
  nameEditable?: boolean;
  nameDisabledReason?: string;
  nameValue?: string;
  nameSaveError?: string;
};

export function CollectionInspector({
  group,
  workspace,
  onChange,
  memberCount,
  rate,
  previewOnly,
  members,
  onSelectMember,
  onRename,
  nameEditable,
  nameDisabledReason,
  nameValue,
  nameSaveError,
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
      <h2>
        {onRename ? (
          <InlineName
            value={nameValue ?? group.name}
            onSave={onRename}
            editable={nameEditable}
            disabledReason={nameDisabledReason}
            saveError={nameSaveError}
            ariaLabel="Rename charger"
          />
        ) : (
          group.name
        )}
      </h2>
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
      {previewOnly && (
        <>
          <p>Exact imported catalog. No live broker connection is open.</p>
          {members
            ?.filter((node) => node.kind === "charger")
            .map((node) => (
              <button
                key={node.id}
                className="sp-wide-button"
                onClick={() => onSelectMember?.(node.id)}
              >
                <PlugZap size={15} />
                Open charger ·{" "}
                {members.filter((item) => item.kind === "sensor").length} topics
              </button>
            ))}
        </>
      )}
      {!onRename && (
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
      )}
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
        aria-expanded={!group.collapsed}
        onClick={() => update({ collapsed: !group.collapsed })}
      >
        {group.collapsed ? "Expand collection" : "Collapse collection"}
      </button>
      <p>
        Object positions are automatic. Collections organize the view without
        changing data routes.
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
