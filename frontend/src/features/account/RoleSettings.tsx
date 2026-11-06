import { useEffect, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/SettingsGroup";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConfirm } from "@/hooks/use-confirm";
import { getErrorMessage } from "@/lib/errors";
import { createRole, deleteRole, getPermissions, updateRole, type Permission, type PermissionInfo, type Role } from "@/lib/member-api";
import { PERMISSION_LABELS, permissionSummary } from "./permissions";

type Draft = { role?: Role; name: string; permissions: Permission[] };

const holders = (count: number) => `${count} ${count === 1 ? "member" : "members"}`;

/** Roles bundle permissions; members who manage members define them here. */
export function RoleSettings({ roles, onChanged }: { roles: Role[]; onChanged: (role?: Role) => Promise<void> }) {
  const [permissions, setPermissions] = useState<PermissionInfo[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirm, confirmation] = useConfirm();

  useEffect(() => {
    let active = true;
    getPermissions().then(list => { if (active) setPermissions(list); })
      .catch(error => { if (active) setError(getErrorMessage(error)); });
    return () => { active = false; };
  }, []);

  const run = async (work: () => Promise<string>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      setNotice(await work());
    } catch (error) {
      setError(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const save = ({ role, name, permissions }: Draft) => run(async () => {
    const saved = role
      ? await updateRole(role.id, { name, permissions })
      : await createRole(name, permissions);
    setDraft(null);
    await onChanged(saved);
    return role ? `${saved.name} saved. Members holding it get the change on their next request.` : `${saved.name} created.`;
  });

  const remove = async (role: Role) => {
    if (!await confirm({ title: `Delete ${role.name}?`, description: "No member holds this role. Deleting it cannot be undone.",
      confirmLabel: "Delete role", destructive: true })) return;
    await run(async () => {
      await deleteRole(role.id);
      await onChanged();
      return `${role.name} deleted.`;
    });
  };

  const toggle = (permission: Permission, granted: boolean) => setDraft(current => current && ({
    ...current,
    permissions: granted ? [...current.permissions, permission] : current.permissions.filter(entry => entry !== permission),
  }));

  return <>
    <SettingsGroup title="Roles" help="Every member can view organization data. A role decides what its members can change. Administrator always holds every permission. Members holding a role get a change on their next request. Keep at least one active member who can manage members."
      actions={!draft && <Button variant="outline" size="sm" disabled={busy} onClick={() => { setError(""); setNotice(""); setDraft({ name: "", permissions: [] }); }}>New role</Button>}
      footer={<>
        {error && <p role="alert" className="text-destructive">{error}</p>}
        {notice && <p role="status">{notice}</p>}
      </>}>
      {draft && <form className="app-settings-invite app-settings-role-form" aria-label={draft.role ? `Edit ${draft.role.name}` : "New role"}
        onSubmit={(event) => { event.preventDefault(); void save(draft); }}>
        <div className="grid min-w-0 flex-1 gap-1.5">
          <Label htmlFor="role-name">Name</Label>
          <Input id="role-name" required autoFocus autoComplete="off" maxLength={60} placeholder="Operator" value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </div>
        <fieldset className="app-settings-fieldset app-settings-permissions">
          <legend>Can change</legend>
          {permissions.map(permission => <label key={permission.id} className="app-settings-permission">
            <input type="checkbox" checked={draft.permissions.includes(permission.id)} onChange={(event) => toggle(permission.id, event.target.checked)} />
            <span><span className="app-settings-permission-name">{PERMISSION_LABELS[permission.id]}</span>
              <span className="app-settings-row-detail">{permission.description}</span></span>
          </label>)}
        </fieldset>
        <div className="flex gap-2">
          <Button disabled={busy} type="submit">{draft.role ? "Save role" : "Create role"}</Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => setDraft(null)}>Cancel</Button>
        </div>
      </form>}
      <ul aria-label="Roles" className="app-settings-list">
        {roles.map(role => <li key={role.id}>
          <SettingsRow className="is-wrapping" label={role.name}
            detail={`${role.editable ? permissionSummary(role.permissions) : "Every permission, always"} · ${holders(role.members)}`}>
            {role.editable && <Button variant="outline" size="sm" disabled={busy}
              onClick={() => { setError(""); setNotice(""); setDraft({ role, name: role.name, permissions: role.permissions }); }}>Edit</Button>}
            {!role.built_in && <Button variant="outline" size="sm" className="text-destructive hover:text-destructive"
              disabled={busy || role.members > 0} title={role.members > 0 ? "Give its members another role first" : undefined}
              onClick={() => void remove(role)}>Delete</Button>}
          </SettingsRow>
        </li>)}
      </ul>
    </SettingsGroup>
    {confirmation}
  </>;
}
