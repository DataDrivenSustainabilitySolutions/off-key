import { lazy } from "react";
import { createRoutesFromElements, Navigate, Route } from "react-router-dom";

import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { RouteErrorBoundary, RouteErrorPage } from "./RouteErrorPage";

export function createAppRoutes() {
  const ApplicationWorkspace = lazy(() => import("./ApplicationWorkspace").then(module => ({ default: module.ApplicationWorkspace })));
  const Account = lazy(() => import("@/pages/Account"));
  const Anomalies = lazy(() => import("@/pages/Anomalies"));
  const Details = lazy(() => import("@/pages/Details"));
  const DataSources = lazy(() => import("@/pages/SystemCatalogue"));
  const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
  const Login = lazy(() => import("@/pages/Login"));
  const Registration = lazy(() => import("@/pages/Registration"));
  const ResetPassword = lazy(() => import("@/pages/ResetPassword"));
  const SystemStatus = lazy(() => import("@/pages/SystemStatus"));
  const MonitoringWorkspace = lazy(() => import("@/pages/MonitoringWorkspace"));

  return createRoutesFromElements(
    <Route errorElement={<RouteErrorBoundary />}>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Registration />} />
      <Route path="/verify" element={<Navigate to="/login" replace />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />

      <Route
        element={
          <ProtectedRoute>
            <ApplicationWorkspace />
          </ProtectedRoute>
        }
      >
        <Route errorElement={<RouteErrorBoundary />}>
          <Route path="/" element={<MonitoringWorkspace />} />
          <Route path="/entities" element={<Navigate to="/sources" replace />} />
          <Route path="/services" element={<Navigate to="/" replace />} />
          <Route path="/sources" element={<DataSources />} />
          <Route path="/details/:chargerId" element={<Details />} />
          <Route path="/account" element={<Account />} />
          <Route path="/system/status" element={<SystemStatus />} />
          <Route path="/account/settings" element={<Navigate to="/system/status" replace />} />
          <Route path="/anomalies" element={<Anomalies />} />
        </Route>
      </Route>

      <Route path="*" element={<RouteErrorPage notFound />} />
    </Route>,
  );
}
