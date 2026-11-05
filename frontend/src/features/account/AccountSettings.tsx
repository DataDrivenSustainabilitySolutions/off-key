import { useEffect, useRef, useState } from "react";
import { LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { SettingsGroup, SettingsRow } from "@/components/SettingsGroup";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConfirm } from "@/hooks/use-confirm";
import { RemoveMemberDialog } from "@/features/account/RemoveMemberDialog";
import { RoleSettings } from "@/features/account/RoleSettings";
import { permissionSummary } from "@/features/account/permissions";
import { getErrorMessage } from "@/lib/errors";
import { memberInitials } from "@/lib/utils";
import { getMembers, getRoles, inviteMember, updateMember, type Member, type Role } from "@/lib/member-api";

const selectClass = "app-settings-select";

export default function AccountSettings() {
  const { member, can, logout, retryAuthentication } = useAuth();
  const manageMembers = can("manage_members");
  const navigate = useNavigate();
  const [members, setMembers] = useState<Member[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Member["role"]>("user");
  const [inviting, setInviting] = useState(false);
  const [confirm, confirmation] = useConfirm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [removalTarget, setRemovalTarget] = useState<Member | null>(null);
  const removeTrigger = useRef<HTMLButtonElement | null>(null);
  const memberList = useRef<HTMLUListElement>(null);
  const reload = async () => {
    const [members, roles] = await Promise.all([getMembers(), getRoles()]);
    setMembers(members);
    setRoles(roles);
  };
  const roleName = (id: string) => roles.find((entry) => entry.id === id)?.name ?? id;
  // Keep a member's current role selectable before the role list arrives.
  const roleOptions = (current: string) => [
    ...roles.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>),
    ...roles.some((entry) => entry.id === current) ? [] : [<option key={current} value={current}>{roleName(current)}</option>],
  ];

  useEffect(() => {
    let active = true;
    // Every member can read the roles; only member managers list the members.
    getRoles().then((roles) => {
      if (active) setRoles(roles);
    }).catch((error) => {
      if (active && manageMembers) setError(getErrorMessage(error));
    });
    if (manageMembers) getMembers().then((members) => {
      if (active) setMembers(members);
    }).catch((error) => {
      if (active) setError(getErrorMessage(error));
    });
    return () => { active = false; };
  }, [manageMembers]);

  const rolesChanged = async (role?: Role) => {
    await reload();
    // A change to your own role changes what you may do now.
    if (role?.id === member?.role) retryAuthentication();
  };

  const invite = async (email: string, role: Member["role"]) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await inviteMember(email, role);
      setNotice("Invitation sent. The link expires in 48 hours.");
      setEmail("");
      setInviting(false);
      await reload();
    } catch (error) {
      setError(getErrorMessage(error));
      // Failed delivery can still leave a pending invitation available to resend.
      await reload().catch(() => {});
    } finally {
      setBusy(false);
    }
  };

  const change = async (target: Member, changes: Partial<Pick<Member, "role" | "is_active">>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await updateMember(target, changes);
      await reload();
      setNotice("Member updated. Existing sessions have been revoked.");
    } catch (error) {
      setError(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SettingsGroup title="Signed in" footer={member && `Your role: view organization data${member.permissions.length ? `, ${permissionSummary(member.permissions).toLowerCase()}` : " only"}.`}>
        <SettingsRow leading={<span className="app-avatar app-settings-avatar" aria-hidden="true">{memberInitials(member?.email)}</span>}
          label={<span className="break-all">{member?.email ?? "…"}</span>} detail={member ? roleName(member.role) : undefined}>
          <Button variant="outline" size="sm" onClick={() => { logout(); navigate("/login", { replace: true }); }}>
            <LogOut aria-hidden="true" />Log out
          </Button>
        </SettingsRow>
      </SettingsGroup>
      {manageMembers && (
        <SettingsGroup title="Members" help="Members can view organization data; their role decides what they can change. Keep at least one active member who can manage members. Disabling access revokes sessions immediately. Disabled members can be permanently removed; shared organization data is kept."
          actions={!inviting && <Button variant="outline" size="sm" onClick={() => { setError(""); setNotice(""); setInviting(true); }}>Invite member</Button>}
          footer={<>
            {error && <p role="alert" className="text-destructive">{error}</p>}
            {notice && <p role="status">{notice}</p>}
          </>}>
          {inviting && <form className="app-settings-invite" aria-label="Invite member" onSubmit={(event) => { event.preventDefault(); void invite(email, role); }}>
            <div className="grid min-w-0 flex-1 gap-1.5">
              <Label htmlFor="member-email">Email</Label>
              <Input id="member-email" type="email" required autoFocus autoComplete="off" placeholder="name@company.com" value={email} onChange={(event) => setEmail(event.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="member-role">Role</Label>
              <select id="member-role" className={selectClass} value={role} onChange={(event) => setRole(event.target.value)}>
                {roleOptions(role)}
              </select>
            </div>
            <div className="flex gap-2">
              <Button disabled={busy} type="submit">Send invitation</Button>
              <Button type="button" variant="ghost" disabled={busy} onClick={() => { setInviting(false); setEmail(""); }}>Cancel</Button>
            </div>
          </form>}
          <ul ref={memberList} aria-label="Members" tabIndex={-1} className="app-settings-list">
            {members.map((target) => (
              <li key={target.id}>
                <SettingsRow className="is-wrapping"
                  leading={<span className="app-avatar app-settings-avatar is-small" aria-hidden="true">{memberInitials(target.email)}</span>}
                  label={<span className="break-all">{target.email}</span>}
                  detail={<>{!target.is_active ? "Disabled" : target.is_verified ? "Active" : "Invitation pending"}{target.id === member?.id && " · You"}</>}>
                  <select aria-label={`Role for ${target.email}`} className={selectClass} value={target.role} disabled={busy || target.id === member?.id} onChange={(event) => void change(target, { role: event.target.value })}>
                    {roleOptions(target.role)}
                  </select>
                  {!target.is_verified && target.is_active && <Button variant="outline" size="sm" disabled={busy} onClick={() => void invite(target.email, target.role)}>Resend invitation</Button>}
                  <Button variant="outline" size="sm" disabled={busy || target.id === member?.id} onClick={async () => {
                    if (target.is_active && !await confirm({ title: "Disable access?", description: `${target.email} will be signed out and their sessions will stop working immediately.`,
                      confirmLabel: "Disable access", destructive: true })) return;
                    void change(target, { is_active: !target.is_active });
                  }}>{target.is_active ? "Disable" : "Enable"}</Button>
                  {!target.is_active && <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" disabled={busy || target.id === member?.id} onClick={(event) => {
                    removeTrigger.current = event.currentTarget;
                    setError("");
                    setNotice("");
                    setRemovalTarget(target);
                  }}>Remove</Button>}
                </SettingsRow>
              </li>
            ))}
          </ul>
        </SettingsGroup>
      )}
      {manageMembers && <RoleSettings roles={roles} onChanged={rolesChanged} />}
      {confirmation}
      {removalTarget && <RemoveMemberDialog member={removalTarget}
        onClose={() => setRemovalTarget(null)}
        onRemoved={() => {
          setMembers((current) => current.filter((entry) => entry.id !== removalTarget.id));
          void getRoles().then(setRoles).catch(() => {});
          setNotice(`${removalTarget.email} has been removed.`);
          setRemovalTarget(null);
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (removeTrigger.current?.isConnected) removeTrigger.current.focus();
          else memberList.current?.focus();
        }} />}
    </>
  );
}
