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
import { getErrorMessage } from "@/lib/errors";
import { memberInitials } from "@/lib/utils";
import { getMembers, inviteMember, updateMember, type Member } from "@/lib/member-api";

const selectClass = "app-settings-select";

export default function AccountSettings() {
  const { member, isAdmin, logout } = useAuth();
  const navigate = useNavigate();
  const [members, setMembers] = useState<Member[]>([]);
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
  const reload = async () => setMembers(await getMembers());

  useEffect(() => {
    if (!isAdmin) return;
    let active = true;
    getMembers().then((members) => {
      if (active) setMembers(members);
    }).catch((error) => {
      if (active) setError(getErrorMessage(error));
    });
    return () => { active = false; };
  }, [isAdmin]);

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
      <SettingsGroup title="Signed in" footer={isAdmin ? undefined : "Members can view organization data. An administrator manages access."}>
        <SettingsRow leading={<span className="app-avatar app-settings-avatar" aria-hidden="true">{memberInitials(member?.email)}</span>}
          label={<span className="break-all">{member?.email ?? "…"}</span>} detail={isAdmin ? "Administrator" : "Member"}>
          <Button variant="outline" size="sm" onClick={() => { logout(); navigate("/login", { replace: true }); }}>
            <LogOut aria-hidden="true" />Log out
          </Button>
        </SettingsRow>
      </SettingsGroup>
      {isAdmin && (
        <SettingsGroup title="Members" help="Members can view organization data. Administrators also manage member access, collection, and monitoring. Keep at least one active administrator. Disabling access revokes sessions immediately. Disabled members can be permanently removed; shared organization data is kept."
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
              <select id="member-role" className={selectClass} value={role} onChange={(event) => setRole(event.target.value as Member["role"])}>
                <option value="user">Member</option>
                <option value="admin">Administrator</option>
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
                  <select aria-label={`Role for ${target.email}`} className={selectClass} value={target.role} disabled={busy || target.id === member?.id} onChange={(event) => void change(target, { role: event.target.value as Member["role"] })}>
                    <option value="user">Member</option>
                    <option value="admin">Administrator</option>
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
      {confirmation}
      {removalTarget && <RemoveMemberDialog member={removalTarget}
        onClose={() => setRemovalTarget(null)}
        onRemoved={() => {
          setMembers((current) => current.filter((entry) => entry.id !== removalTarget.id));
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
