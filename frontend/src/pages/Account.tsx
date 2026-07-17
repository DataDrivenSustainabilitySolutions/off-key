import { NavigationBar } from "@/components/NavigationBar";
import {
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/DashboardLayout";
import { ShieldCheck, UserRound } from "lucide-react";

export default function AccountPage() {
  return (
    <>
      <NavigationBar />
      <PageShell>
        <PageHeader
          eyebrow="Profile"
          title="Account"
          description="Review your account context and security status."
        />
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <SectionPanel title="Account preferences" description="Personal settings for this off/key account.">
            <div className="flex min-h-44 flex-col items-center justify-center rounded-xl border border-dashed border-border/70 bg-muted/20 px-6 text-center">
              <div className="mb-4 flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <UserRound className="size-5" />
              </div>
              <p className="text-sm font-medium">No configurable preferences yet</p>
              <p className="mt-1 max-w-sm text-sm leading-6 text-muted-foreground">
                Account-specific controls will appear here when they become available.
              </p>
            </div>
          </SectionPanel>
          <aside className="rounded-2xl border border-border/65 bg-card p-5">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="size-4 text-emerald-600" />
              Protected account
            </div>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              This page and the operational workspace require an authenticated session.
            </p>
          </aside>
        </div>
      </PageShell>
    </>
  );
}
