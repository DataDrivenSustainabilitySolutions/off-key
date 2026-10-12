import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { JSX } from "react";
import { AuthBackdrop } from "@/components/AuthBackdrop";
import { Button } from "@/components/ui/button";

export const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  const { isAuthenticated, isLoading, authError, retryAuthentication, logout } = useAuth();

  if (authError) {
    return (
      <AuthBackdrop contentClassName="flex justify-center">
        <div role="alert" className="max-w-md space-y-4 rounded-xl border border-border bg-card p-6 text-foreground shadow-sm">
          <p>{authError}</p>
          <div className="flex gap-3">
            <Button onClick={retryAuthentication}>Retry</Button>
            <Button variant="outline" onClick={logout}>Sign out</Button>
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

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
};
