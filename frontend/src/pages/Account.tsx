import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { PageHeader, PageShell, SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConfirm } from "@/hooks/use-confirm";
import { RemoveMemberDialog } from "@/features/account/RemoveMemberDialog";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { getErrorMessage } from "@/lib/errors";
import { getMembers, inviteMember, updateMember, type Member } from "@/lib/member-api";

export default function AccountPage() {
  const { member, isAdmin } = useAuth();
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
  useDocumentTitle("Account");

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
      <PageShell>
        <PageHeader title="Account" description={`Signed in as ${member?.email ?? "…"} · ${isAdmin ? "Administrator" : "Member"}${isAdmin ? "" : ". Members can view organization data; an administrator manages access."}`} />
        {isAdmin && (
          <SectionPanel title="Members" help="Members can view organization data. Administrators also manage member access, collection, and monitoring. Keep at least one active administrator. Disabling access revokes sessions immediately. Disabled members can be permanently removed; shared organization data is kept."
            actions={!inviting && <Button variant="outline" onClick={() => { setError(""); setNotice(""); setInviting(true); }}>Invite member</Button>}>
            {inviting && <form className="mb-6 grid gap-3 border-b pb-6 sm:flex sm:flex-wrap sm:items-end" aria-label="Invite member" onSubmit={(event) => { event.preventDefault(); void invite(email, role); }}>
              <div className="grid min-w-0 gap-2 sm:w-72">
                <Label htmlFor="member-email">Email</Label>
                <Input id="member-email" type="email" required autoFocus autoComplete="off" placeholder="name@company.com" value={email} onChange={(event) => setEmail(event.target.value)} />
              </div>
              <div className="grid gap-2 sm:w-44">
                <Label htmlFor="member-role">Role</Label>
                <select id="member-role" className="h-11 w-full rounded-md border border-input bg-card px-3 text-base outline-none transition-[color,border-color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-50 md:h-9 md:text-[13px]" value={role} onChange={(event) => setRole(event.target.value as Member["role"])}>
                  <option value="user">Member</option>
                  <option value="admin">Administrator</option>
                </select>
              </div>
              <Button disabled={busy} type="submit" className="sm:h-11 md:h-9">Send invitation</Button>
              <Button type="button" variant="ghost" disabled={busy} className="sm:h-11 md:h-9" onClick={() => { setInviting(false); setEmail(""); }}>Cancel</Button>
            </form>}
            {error && <p role="alert" className="mb-4 text-sm text-destructive">{error}</p>}
            {notice && <p role="status" className="mb-4 text-sm">{notice}</p>}
            <ul ref={memberList} aria-label="Members" tabIndex={-1} className="divide-y">
              {members.map((target) => (
                <li key={target.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                  <div className="min-w-0">
                    <p className="break-words text-sm font-medium">{target.email}</p>
                    <p className="text-xs text-muted-foreground">{!target.is_active ? "Disabled" : target.is_verified ? "Active" : "Invitation pending"}{target.id === member?.id && " · You"}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <select aria-label={`Role for ${target.email}`} className="h-11 rounded-md border border-input bg-card px-3 text-base outline-none transition-[color,border-color,box-shadow] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-50 sm:h-9 sm:text-[13px]" value={target.role} disabled={busy || target.id === member?.id} onChange={(event) => void change(target, { role: event.target.value as Member["role"] })}>
                      <option value="user">Member</option>
                      <option value="admin">Administrator</option>
                    </select>
                    {!target.is_verified && target.is_active && <Button variant="outline" disabled={busy} onClick={() => void invite(target.email, target.role)}>Resend invitation</Button>}
                    <Button variant="outline" disabled={busy || target.id === member?.id} onClick={async () => {
                      if (target.is_active && !await confirm({ title: "Disable access?", description: `${target.email} will be signed out and their sessions will stop working immediately.`,
                        confirmLabel: "Disable access", destructive: true })) return;
                      void change(target, { is_active: !target.is_active });
                    }}>{target.is_active ? "Disable" : "Enable"}</Button>
                    {!target.is_active && <Button variant="outline" className="text-destructive hover:text-destructive" disabled={busy || target.id === member?.id} onClick={(event) => {
                      removeTrigger.current = event.currentTarget;
                      setError("");
                      setNotice("");
                      setRemovalTarget(target);
                    }}>Remove</Button>}
                  </div>
                </li>
              ))}
            </ul>
          </SectionPanel>
        )}
      </PageShell>
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
