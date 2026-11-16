import { useSyncExternalStore } from "react";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/button";
import {
  isBrowserVerificationRequired,
  subscribeToBrowserVerification,
  verifyBrowser,
} from "@/lib/browser-verification";

/**
 * Cloudflare's clearance can lapse while a page stays open, for example on an
 * idle monitoring view. Its polls then fail on every page at once, so offer the
 * one action that helps, a page reload, in a single place above them.
 */
export function BrowserVerificationNotice() {
  const required = useSyncExternalStore(subscribeToBrowserVerification, isBrowserVerificationRequired);
  // Sign-in checks show their own full-page prompt with the same action.
  const { browserVerificationRequired: shownBySignIn } = useAuth();
  if (!required || shownBySignIn) return null;
  return (
    <div
      role="alert"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto flex max-w-lg flex-wrap items-center gap-3 rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-lg sm:flex-nowrap"
    >
      <p className="min-w-0 flex-1">Cloudflare needs to verify your browser before this page can update again.</p>
      <Button onClick={verifyBrowser}>Reload page</Button>
    </div>
  );
}
