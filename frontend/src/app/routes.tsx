import { lazy } from "react";
import { createRoutesFromElements, Navigate, Route } from "react-router-dom";

import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { RouteErrorBoundary, RouteErrorPage } from "./RouteErrorPage";
import { SettingsRedirect } from "./SettingsRedirect";

export function createAppRoutes() {
  const ApplicationWorkspace = lazy(() => import("./ApplicationWorkspace").then(module => ({ default: module.ApplicationWorkspace })));
  const Anomalies = lazy(() => import("@/pages/Anomalies"));
  const Details = lazy(() => import("@/pages/Details"));
  const Dojo = lazy(() => import("@/pages/Dojo"));
  const DataSources = lazy(() => import("@/pages/SystemCatalogue"));
  const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
  const Login = lazy(() => import("@/pages/Login"));
  const Registration = lazy(() => import("@/pages/Registration"));
  const ResetPassword = lazy(() => import("@/pages/ResetPassword"));
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
          {/* Account and status open as the settings overlay above Monitoring. */}
          <Route path="/account" element={<SettingsRedirect section="account" />} />
          <Route path="/system/status" element={<SettingsRedirect section="status" />} />
          <Route path="/account/settings" element={<SettingsRedirect section="status" />} />
          <Route path="/anomalies" element={<Anomalies />} />
          <Route path="/dojo" element={<Dojo />} />
        </Route>
      </Route>

      <Route path="*" element={<RouteErrorPage notFound />} />
    </Route>,
  );
}
