import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getErrorMessage } from "@/lib/errors";
import { createRole, getPermissions, updateRole, type Permission, type PermissionInfo, type Role } from "@/lib/member-api";
import { PERMISSION_LABELS } from "./permissions";

type Props = {
  role?: Role;
  onClose: () => void;
  onCloseAutoFocus: (event: Event) => void;
  onSaved: (role: Role) => void;
};

export function RoleEditor({ role, onClose, onCloseAutoFocus, onSaved }: Props) {
  const id = useId();
  const nameField = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(role?.name ?? "");
  const [granted, setGranted] = useState<Permission[]>(role?.permissions ?? []);
  const [permissions, setPermissions] = useState<PermissionInfo[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    let active = true;
    getPermissions().then(list => {
      if (active) setPermissions(list);
    }).catch(() => {
      if (active) setLoadFailed(true);
    });
    return () => { active = false; };
  }, [attempt]);

  const retry = () => {
    nameField.current?.focus();
    setLoadFailed(false);
    setAttempt(current => current + 1);
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!permissions || saving) return;
    const cleanName = name.trim();
    if (!cleanName) {
      setSaveError("Enter a role name.");
      nameField.current?.focus();
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      const saved = role
        ? await updateRole(role.id, { name: cleanName, permissions: granted })
        : await createRole(cleanName, granted);
      onSaved(saved);
    } catch (error) {
      setSaveError(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const toggle = (permission: Permission, checked: boolean) => setGranted(current =>
    checked ? [...current, permission] : current.filter(entry => entry !== permission));

  return <Dialog.Root open onOpenChange={open => { if (!open && !saving) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="ex-dialog-overlay" />
      <Dialog.Content className="ex-dialog account-role-editor" onCloseAutoFocus={onCloseAutoFocus}
        onPointerDownOutside={event => event.preventDefault()}
        onEscapeKeyDown={event => { if (saving) event.preventDefault(); }}>
        <form className="account-role-form" aria-label={role ? "Edit " + role.name : "New role"} onSubmit={event => void save(event)}>
          <header className="account-role-editor-header">
            <Dialog.Title>{role ? "Edit role" : "New role"}</Dialog.Title>
            <Dialog.Description>
              {role && role.members > 0 ? "Changes apply to members with this role on their next action." : "Choose what members with this role can change."}
            </Dialog.Description>
          </header>
          <div className="account-role-fields">
            <div className="account-role-name">
              <Label htmlFor={id + "-name"}>Name</Label>
              <Input ref={nameField} id={id + "-name"} required autoComplete="off" maxLength={60}
                placeholder="e.g. Monitoring operator" value={name} readOnly={saving}
                onChange={event => { setName(event.target.value); setSaveError(""); }} />
            </div>
            <fieldset className="app-settings-fieldset account-role-permissions" disabled={saving}>
              <legend>Permissions</legend>
              <p className="account-role-permissions-note">With no permissions selected, members can still view organization data.</p>
              {permissions ? <div className="account-role-options">
                {permissions.map(permission => {
                  const key = id + "-" + permission.id;
                  return <label key={permission.id} className="account-role-permission">
                    <input type="checkbox" checked={granted.includes(permission.id)} aria-labelledby={key} aria-describedby={key + "-description"}
                      onChange={event => toggle(permission.id, event.target.checked)} />
                    <span>
                      <span id={key} className="account-role-permission-name">{PERMISSION_LABELS[permission.id]}</span>
                      <span id={key + "-description"} className="account-role-permission-description">{permission.description}</span>
                    </span>
                  </label>;
                })}
              </div> : loadFailed ? <div className="account-role-load">
                <p role="alert">Couldn’t load permissions.</p>
                <Button variant="outline" size="sm" type="button" onClick={retry}>Retry</Button>
              </div> : <p role="status" className="account-role-load">Loading permissions…</p>}
            </fieldset>
          </div>
          <footer className="account-role-editor-footer">
            {saveError && <p role="alert" className="account-role-save-error">{saveError}</p>}
            <div className="account-role-editor-actions">
              <Button variant="outline" type="button" disabled={saving} onClick={onClose}>Cancel</Button>
              <Button type="submit" disabled={!permissions} aria-disabled={saving}>
                {saving ? (role ? "Saving…" : "Creating…") : role ? "Save role" : "Create role"}
              </Button>
            </div>
          </footer>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
