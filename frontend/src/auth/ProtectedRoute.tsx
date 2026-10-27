import { Link, Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { JSX, useEffect } from "react";
import { AuthBackdrop } from "@/components/AuthBackdrop";
import { Button } from "@/components/ui/button";

export const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  const { isAuthenticated, isLoading, authError, retryAuthentication, logout, hasSession, guestChecked, checkGuest } = useAuth();
  const askGuest = !isAuthenticated && !isLoading && !authError && !guestChecked;
  // A signed-out visit may be a guest of the public read-only demo.
  useEffect(() => { if (askGuest) checkGuest(); }, [askGuest, checkGuest]);

  if (authError) {
    return (
      <AuthBackdrop contentClassName="flex justify-center">
        <div role="alert" className="max-w-md space-y-4 rounded-xl border border-border bg-card p-6 text-foreground shadow-sm">
          <p>{authError}</p>
          <div className="flex gap-3">
            <Button onClick={retryAuthentication}>Retry</Button>
            {/* A signed-out visitor of an unavailable demo has nothing to sign out of. */}
            {hasSession
              ? <Button variant="outline" onClick={logout}>Sign out</Button>
              : <Button variant="outline" asChild><Link to="/login">Log in</Link></Button>}
          </div>
        </div>
      </AuthBackdrop>
    );
  }

  if (isLoading || askGuest) {
    return (
      <AuthBackdrop contentClassName="flex justify-center">
        <div className="flex items-center gap-3 rounded-full border border-border/70 bg-card/82 px-4 py-2 text-sm text-muted-foreground shadow-sm backdrop-blur-xl">
          <span className="h-2 w-2 rounded-full bg-primary live-pulse-ring" />
          Authentication is loading...
        </div>
      </AuthBackdrop>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
};
