import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { loginHref } from "@/auth/login-navigation";
import { Button } from "@/components/ui/button";
import { useNow } from "@/hooks/use-now";
import { dateTimeFormat } from "@/lib/locale";

// Warn this long before a sign-in ends, so nobody is signed out mid-task.
const SESSION_WARNING_MS = 5 * 60_000;

const clockTime = (time: number) =>
  dateTimeFormat({ hour: "2-digit", minute: "2-digit" }).format(new Date(time));

/**
 * Says when the sign-in is about to end, or that renewal is retrying after an
 * outage. The page stays usable underneath, so no work is lost either way.
 */
export function SessionNotice() {
  const location = useLocation();
  const { reconnecting, sessionEndsAt, retryAuthentication } = useAuth();
  const now = useNow(15_000, sessionEndsAt !== null);
  const [dismissed, setDismissed] = useState<number | null>(null);
  const ending = sessionEndsAt !== null && sessionEndsAt - now <= SESSION_WARNING_MS && dismissed !== sessionEndsAt;

  if (!reconnecting && !ending) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto flex max-w-lg flex-wrap items-center gap-3 rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-lg sm:flex-nowrap"
    >
      {reconnecting ? (
        <>
          <p className="min-w-0 flex-1">We can’t reach your account right now and keep retrying. This page and your changes stay as they are.</p>
          <Button onClick={retryAuthentication}>Retry now</Button>
        </>
      ) : (
        <>
          <p className="min-w-0 flex-1">
            Your sign-in ends at {clockTime(sessionEndsAt!)}. Sign in again to keep working; your unsaved changes are kept.
          </p>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setDismissed(sessionEndsAt)}>Later</Button>
            <Button asChild><Link to={loginHref(location)}>Sign in again</Link></Button>
          </div>
        </>
      )}
    </div>
  );
}
