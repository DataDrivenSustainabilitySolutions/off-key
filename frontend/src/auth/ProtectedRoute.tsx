import { Link, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { JSX } from "react";
import { AuthBackdrop } from "@/components/AuthBackdrop";
import { Button } from "@/components/ui/button";
import { loginHref } from "./login-navigation";

export const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  const location = useLocation();
  const { isAuthenticated, isGuest, isLoading, authError, browserVerificationRequired, retryAuthentication, logout } = useAuth();

  if (authError) {
    return (
      <AuthBackdrop contentClassName="flex justify-center">
        <div role="alert" className="max-w-md space-y-4 rounded-xl border border-border bg-card p-6 text-foreground shadow-sm">
          <p>{authError}</p>
          <div className="flex gap-3">
            <Button onClick={retryAuthentication}>{browserVerificationRequired ? 'Verify browser' : 'Retry'}</Button>
            {!browserVerificationRequired && <>
              <Button variant="outline" onClick={logout}>Sign out</Button>
              <Button variant="ghost" asChild><Link to={loginHref(location)}>Admin sign in</Link></Button>
            </>}
          </div>
        </div>
      </AuthBackdrop>
    );
  }

  if (isLoading) {
    return (
      <AuthBackdrop contentClassName="flex justify-center">
        <div className="flex items-center gap-3 rounded-full border border-border/70 bg-card/82 px-4 py-2 text-sm text-muted-foreground shadow-sm backdrop-blur-xl">
          <span className="h-2 w-2 rounded-full bg-primary live-pulse-ring" />
          Authentication is loading...
        </div>
      </AuthBackdrop>
    );
  }

  if (!isAuthenticated && !isGuest) {
    return <Navigate to={loginHref(location)} replace />;
  }

  return children;
};
