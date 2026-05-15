import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { JSX } from "react";
import { AuthBackdrop } from "@/components/AuthBackdrop";

export const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  const { isAuthenticated, isLoading } = useAuth();

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
