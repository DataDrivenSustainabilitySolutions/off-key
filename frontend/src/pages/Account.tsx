import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { NavigationBar } from "@/components/NavigationBar";
import { PageHeader, PageShell, SectionPanel } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getErrorMessage } from "@/lib/errors";
import { getMembers, inviteMember, updateMember, type Member } from "@/lib/member-api";

export default function AccountPage() {
  const { member, isAdmin } = useAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Member["role"]>("user");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
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
      <NavigationBar />
      <PageShell>
        <PageHeader
          eyebrow="Organization"
          title="Account"
          description="This installation is a shared workspace for one organization."
          actions={
            <Button variant="outline" asChild>
              <Link to="/account/settings">Settings</Link>
            </Button>
          }
        />
        <SectionPanel title="Your account" description="All active members can view the organization's data. Administrators manage members, collection, and monitoring.">
          <p className="text-sm">{member?.email} · {isAdmin ? "Administrator" : "Member"}</p>
        </SectionPanel>
        {isAdmin && (
          <SectionPanel title="Organization members" description="Invite colleagues or manage their access. At least one active administrator must remain.">
            <form className="mb-6 flex flex-wrap items-end gap-3" onSubmit={(event) => { event.preventDefault(); void invite(email, role); }}>
              <div className="grid gap-2">
                <Label htmlFor="member-email">Email</Label>
                <Input id="member-email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="member-role">Role</Label>
                <select id="member-role" className="h-10 rounded-md border bg-background px-3 text-sm" value={role} onChange={(event) => setRole(event.target.value as Member["role"])}>
                  <option value="user">Member</option>
                  <option value="admin">Administrator</option>
                </select>
              </div>
              <Button disabled={busy} type="submit">Send invitation</Button>
            </form>
            {error && <p role="alert" className="mb-4 text-sm text-destructive">{error}</p>}
            {notice && <p role="status" className="mb-4 text-sm">{notice}</p>}
            <ul className="divide-y">
              {members.map((target) => (
                <li key={target.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                  <div>
                    <p className="text-sm font-medium">{target.email}</p>
                    <p className="text-xs text-muted-foreground">{!target.is_active ? "Disabled" : target.is_verified ? "Active" : "Invitation pending"}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <select aria-label={`Role for ${target.email}`} className="h-9 rounded-md border bg-background px-2 text-sm" value={target.role} disabled={busy || target.id === member?.id} onChange={(event) => void change(target, { role: event.target.value as Member["role"] })}>
                      <option value="user">Member</option>
                      <option value="admin">Administrator</option>
                    </select>
                    {!target.is_verified && target.is_active && <Button variant="outline" disabled={busy} onClick={() => void invite(target.email, target.role)}>Resend invitation</Button>}
                    <Button variant="outline" disabled={busy || target.id === member?.id} onClick={() => {
                      if (target.is_active && !window.confirm(`Disable access for ${target.email}? Their sessions will stop working immediately.`)) return;
                      void change(target, { is_active: !target.is_active });
                    }}>{target.is_active ? "Disable" : "Enable"}</Button>
                  </div>
                </li>
              ))}
            </ul>
          </SectionPanel>
        )}
      </PageShell>
    </>
  );
}
