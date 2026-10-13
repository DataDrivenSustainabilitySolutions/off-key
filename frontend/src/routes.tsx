import { lazy } from "react";
import { createRoutesFromElements, Navigate, Outlet, Route } from "react-router-dom";

import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { ApplicationWorkspace } from "@/components/ApplicationWorkspace";
import { RouteErrorBoundary, RouteErrorPage } from "@/components/RouteErrorPage";

export function createAppRoutes() {
  const Account = lazy(() => import("@/pages/Account"));
  const Anomalies = lazy(() => import("@/pages/Anomalies"));
  const Details = lazy(() => import("@/pages/Details"));
  const DataSources = lazy(() => import("@/pages/SystemCatalogue"));
  const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
  const Login = lazy(() => import("@/pages/Login"));
  const Monitoring = lazy(() => import("@/pages/Monitoring"));
  const Registration = lazy(() => import("@/pages/Registration"));
  const ResetPassword = lazy(() => import("@/pages/ResetPassword"));
  const Settings = lazy(() => import("@/pages/Settings"));
  const Verification = lazy(() => import("@/pages/Verification"));
  const MonitoringWorkspace = lazy(() => import("@/pages/MonitoringWorkspace"));

  return createRoutesFromElements(
    <Route errorElement={<RouteErrorBoundary />}>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Registration />} />
      <Route path="/verify" element={<Verification />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />

      <Route
        element={
          <ProtectedRoute>
            <Outlet />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<MonitoringWorkspace />} />
        <Route path="/entities" element={<Navigate to="/sources" replace />} />
        <Route path="/services" element={<Navigate to="/" replace />} />
        <Route path="/sources" element={<DataSources />} />
        <Route element={<ApplicationWorkspace />}>
          <Route path="/details/:chargerId" element={<Details />} />
          <Route path="/monitoring/:chargerId" element={<Monitoring />} />
          <Route path="/account" element={<Account />} />
          <Route path="/account/settings" element={<Settings />} />
          <Route path="/anomalies" element={<Anomalies />} />
        </Route>
      </Route>

      <Route path="*" element={<RouteErrorPage notFound />} />
    </Route>,
  );
}
