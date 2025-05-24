// src/components/ProtectedRoute.tsx
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { JSX } from "react";

export const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  const { isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
};
