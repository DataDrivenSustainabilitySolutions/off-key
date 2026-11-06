import { useRef, useState } from "react";
import { Plus } from "lucide-react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { SettingsGroup, SettingsRow } from "@/components/SettingsGroup";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";
import { deleteRole, type Role } from "@/lib/member-api";
import { permissionSummary } from "./permissions";
import { RoleEditor } from "./RoleEditor";
import "./roles.css";

type Props = {
  roles: Role[] | null;
  loadFailed: boolean;
  disabled: boolean;
  onRetry: () => void;
  onSaved: (role: Role) => void;
  onDeleted: (id: string) => void;
};

type Action = { kind: "create" } | { kind: "edit" | "delete"; role: Role };

const holders = (count: number) => count + (count === 1 ? " member" : " members");

export function RoleSettings({ roles, loadFailed, disabled, onRetry, onSaved, onDeleted }: Props) {
  const [action, setAction] = useState<Action | null>(null);
  const [notice, setNotice] = useState("");
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState("");
  const opener = useRef<HTMLButtonElement>(null);
  const createButton = useRef<HTMLButtonElement>(null);
  const listArea = useRef<HTMLDivElement>(null);

  const open = (next: Action, button: HTMLButtonElement) => {
    opener.current = button;
    setNotice("");
    setRemoveError("");
    setAction(next);
  };

  const returnFocus = (event: Event) => {
    event.preventDefault();
    (opener.current?.isConnected ? opener.current : createButton.current)?.focus();
  };

  const remove = async (role: Role) => {
    if (removing) return;
    setRemoving(true);
    setRemoveError("");
    try {
      await deleteRole(role.id);
      onDeleted(role.id);
      setNotice(role.name + " deleted.");
      setAction(null);
    } catch (error) {
      setRemoveError(getErrorMessage(error));
    } finally {
      setRemoving(false);
    }
  };

  return <>
    <SettingsGroup title="Roles" className="account-roles"
      actions={<Button ref={createButton} variant="outline" size="sm" disabled={!roles || disabled}
        onClick={event => open({ kind: "create" }, event.currentTarget)}><Plus aria-hidden="true" />New role</Button>}
      footer={notice && <p role="status">{notice}</p>}>
      <p className="account-roles-intro">Everyone can view organization data. Roles determine what members can change.</p>
      <div ref={listArea} tabIndex={-1} className="account-role-list-area">
        {roles ? <ul aria-label="Roles" className="app-settings-list">
          {roles.map(role => <li key={role.id}>
            <SettingsRow className="account-role-row"
              label={<div className="account-role-identity">
                <strong>{role.name}</strong>
                {role.built_in && <span className="account-role-badge">Built-in</span>}
              </div>}
              detail={<>
                <p>{role.editable ? permissionSummary(role.permissions) : "All permissions"}</p>
                <p>{holders(role.members)}{!role.built_in && role.members > 0 && " · Reassign members to delete"}</p>
              </>}>
              {role.editable && <Button variant="outline" size="sm" disabled={disabled} aria-label={"Edit " + role.name}
                onClick={event => open({ kind: "edit", role }, event.currentTarget)}>Edit</Button>}
              {!role.built_in && role.members === 0 && <Button variant="ghost" size="sm" aria-label={"Delete " + role.name}
                className="text-destructive hover:text-destructive" disabled={disabled}
                onClick={event => open({ kind: "delete", role }, event.currentTarget)}>Delete</Button>}
            </SettingsRow>
          </li>)}
        </ul> : <div className="account-role-load">
          {loadFailed ? <>
            <p role="alert">Couldn’t load roles.</p>
            <Button type="button" variant="outline" size="sm" onClick={() => { listArea.current?.focus(); onRetry(); }}>Retry</Button>
          </> : <p role="status">Loading roles…</p>}
        </div>}
      </div>
    </SettingsGroup>
    {action?.kind === "delete" && <ConfirmDialog open title={"Delete " + action.role.name + "?"}
      description="This role has no members. Deleting it is permanent."
      confirmLabel="Delete role" busyLabel="Deleting…" destructive busy={removing} error={removeError}
      onConfirm={() => void remove(action.role)} onCancel={() => setAction(null)} onCloseAutoFocus={returnFocus} />}
    {action && action.kind !== "delete" && <RoleEditor role={action.kind === "edit" ? action.role : undefined}
      onClose={() => setAction(null)} onCloseAutoFocus={returnFocus}
      onSaved={role => {
        onSaved(role);
        setNotice(role.name + (action.kind === "edit" ? " saved." : " created."));
        setAction(null);
      }} />}
  </>;
}
