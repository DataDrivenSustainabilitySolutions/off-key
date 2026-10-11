import { useRef, useState } from "react";
import { Check, Plus, Settings2, Trash2, X } from "lucide-react";
import { InlineName } from "./InlineName";
import {
  canAddPersonalMember,
  createPersonalGroup,
  deletePersonalGroup,
  MAX_PERSONAL_GROUPS,
  MAX_PERSONAL_GROUP_MEMBERS,
  togglePersonalGroupMember,
  updatePersonalGroup,
} from "./personalGroups";
import type { SpatialWorkspace } from "./types";
import "./personalGroups.css";

type LayoutProps = {
  workspace: SpatialWorkspace;
  onChange: (workspace: SpatialWorkspace) => void;
};

function NewGroup({
  onCreate,
  onCancel,
}: {
  onCreate: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const active = useRef(true);
  const save = () => {
    if (!active.current) return;
    active.current = false;
    if (name.trim()) onCreate(name.trim());
    else onCancel();
  };
  return (
    <input
      className="sp-personal-new"
      aria-label="New personal group name"
      autoFocus
      maxLength={120}
      value={name}
      placeholder="Group name…"
      onChange={(event) => setName(event.target.value)}
      onBlur={save}
      onKeyDown={(event) => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === "Enter") {
          event.preventDefault();
          event.stopPropagation();
          save();
        } else if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          active.current = false;
          onCancel();
        }
      }}
    />
  );
}

/** A personal overlay. This component never receives or edits SystemDocument. */
export function PersonalGroups({
  workspace,
  selectedId,
  selectedGroupId,
  onChange,
  onSelectGroup,
}: LayoutProps & {
  selectedId: string | null;
  selectedGroupId: string | null;
  onSelectGroup: (id: string | null) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const groups = workspace.personalGroups ?? [];
  const atLimit = groups.length >= MAX_PERSONAL_GROUPS;
  const canAddMember = canAddPersonalMember(workspace);
  const create = (name: string) => {
    const next = createPersonalGroup(workspace, name, selectedId);
    onChange(next);
    setCreating(false);
    const group = next.personalGroups?.[next.personalGroups.length - 1];
    if (group) {
      setEditingId(group.id);
      if (selectedId) onSelectGroup(group.id);
    }
  };
  return (
    <section className="sp-personal-groups" aria-label="My groups">
      <div className="sp-section-title">
        <h2>My groups</h2>
        <button
          aria-label="Create personal group"
          disabled={atLimit}
          title={
            atLimit
              ? "128 personal groups maximum"
              : selectedId
                ? "Create a group with the selected object"
                : "Create a personal group"
          }
          onClick={() => setCreating(true)}
        >
          <Plus size={16} />
        </button>
      </div>
      {creating && (
        <NewGroup onCreate={create} onCancel={() => setCreating(false)} />
      )}
      {!groups.length && !creating && (
        <p className="sp-personal-hint">Group any objects across brokers.</p>
      )}
      <div className="sp-personal-list">
        {groups.map((group) => {
          const contains = selectedId
            ? group.memberIds.includes(selectedId)
            : false;
          return (
            <div key={group.id}>
              <div
                className={`sp-personal-row ${selectedGroupId === group.id ? "is-active" : ""}`}
              >
                <button
                  className="sp-personal-select"
                  aria-label={`Show personal group ${group.name}`}
                  aria-pressed={selectedGroupId === group.id}
                  title={group.name}
                  onClick={() =>
                    onSelectGroup(
                      selectedGroupId === group.id ? null : group.id,
                    )
                  }
                >
                  <i style={{ background: group.color }} />
                  <span>{group.name}</span>
                  <small>{group.memberIds.length}</small>
                </button>
                {selectedId && (
                  <button
                    className="sp-personal-icon"
                    aria-label={`${contains ? "Remove selected object from" : "Add selected object to"} ${group.name}`}
                    aria-pressed={contains}
                    disabled={
                      !contains &&
                      (!canAddMember ||
                        group.memberIds.length >= MAX_PERSONAL_GROUP_MEMBERS)
                    }
                    onClick={() =>
                      onChange(
                        togglePersonalGroupMember(
                          workspace,
                          group.id,
                          selectedId,
                        ),
                      )
                    }
                  >
                    {contains ? <Check size={13} /> : <Plus size={13} />}
                  </button>
                )}
                <button
                  className="sp-personal-icon"
                  aria-label={`Edit personal group ${group.name}`}
                  aria-expanded={editingId === group.id}
                  onClick={() =>
                    setEditingId(editingId === group.id ? null : group.id)
                  }
                >
                  <Settings2 size={13} />
                </button>
              </div>
              {editingId === group.id && (
                <div className="sp-personal-edit">
                  <InlineName
                    value={group.name}
                    ariaLabel={`Rename personal group ${group.name}`}
                    onSave={async (name) =>
                      onChange(
                        updatePersonalGroup(workspace, group.id, { name }),
                      )
                    }
                  />
                  <div className="sp-personal-edit-actions">
                    <label>
                      Color
                      <input
                        type="color"
                        aria-label={`Color for ${group.name}`}
                        value={group.color}
                        onChange={(event) =>
                          onChange(
                            updatePersonalGroup(workspace, group.id, {
                              color: event.target.value,
                            }),
                          )
                        }
                      />
                    </label>
                    <button
                      aria-label={`Delete personal group ${group.name}`}
                      title="Delete group; keep its objects"
                      onClick={() => {
                        onChange(deletePersonalGroup(workspace, group.id));
                        if (selectedGroupId === group.id) onSelectGroup(null);
                        setEditingId(null);
                      }}
                    >
                      <Trash2 size={13} />
                      Delete group
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {selectedGroupId && (
        <button
          className="sp-personal-clear"
          onClick={() => onSelectGroup(null)}
        >
          <X size={12} />
          Show all objects
        </button>
      )}
      <p className="sp-personal-scope">
        Personal · saved in this browser and workspace exports.
      </p>
    </section>
  );
}

export function PersonalGroupMembership({
  workspace,
  nodeId,
  onChange,
}: LayoutProps & { nodeId: string }) {
  const [creating, setCreating] = useState(false);
  const groups = workspace.personalGroups ?? [];
  const canAddMember = canAddPersonalMember(workspace);
  return (
    <section
      className="sp-personal-membership"
      aria-label="Personal group membership"
    >
      <div className="sp-section-title">
        <h3>My groups</h3>
        <button
          aria-label="Create personal group for object"
          disabled={groups.length >= MAX_PERSONAL_GROUPS}
          onClick={() => setCreating(true)}
        >
          <Plus size={14} />
        </button>
      </div>
      <p className="sp-personal-hint">
        Personal organization; catalog structure stays intact.
      </p>
      {groups.map((group) => {
        const checked = group.memberIds.includes(nodeId);
        return (
          <label key={group.id} className="sp-personal-check">
            <input
              type="checkbox"
              checked={checked}
              disabled={
                !checked &&
                (!canAddMember ||
                  group.memberIds.length >= MAX_PERSONAL_GROUP_MEMBERS)
              }
              onChange={() =>
                onChange(togglePersonalGroupMember(workspace, group.id, nodeId))
              }
            />
            <i style={{ background: group.color }} />
            <span>{group.name}</span>
          </label>
        );
      })}
      {creating && (
        <NewGroup
          onCancel={() => setCreating(false)}
          onCreate={(name) => {
            onChange(createPersonalGroup(workspace, name, nodeId));
            setCreating(false);
          }}
        />
      )}
    </section>
  );
}
