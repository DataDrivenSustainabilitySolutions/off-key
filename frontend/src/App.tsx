import { lazy, Suspense } from "react";
import {
  createBrowserRouter,
  createRoutesFromElements,
  Navigate,
  Outlet,
  Route,
  RouterProvider,
} from "react-router-dom";
import { Toaster } from "react-hot-toast";

import "@/App.css";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { FullPageLoading } from "@/components/LoadingStates";
import { ThemeProvider } from "@/components/theme-provider";

const Account = lazy(() => import("@/pages/Account"));
const Anomalies = lazy(() => import("@/pages/Anomalies"));
const Details = lazy(() => import("@/pages/Details"));
const DataSources = lazy(() => import("@/pages/SystemCatalogue"));
const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
const Entities = lazy(() => import("@/pages/Entities"));
const Login = lazy(() => import("@/pages/Login"));
const Monitoring = lazy(() => import("@/pages/Monitoring"));
const Registration = lazy(() => import("@/pages/Registration"));
const ResetPassword = lazy(() => import("@/pages/ResetPassword"));
const Settings = lazy(() => import("@/pages/Settings"));
const Verification = lazy(() => import("@/pages/Verification"));
const MonitoringWorkspace = lazy(() => import("@/pages/MonitoringWorkspace"));

const router = createBrowserRouter(
  createRoutesFromElements(
    <>
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
        <Route path="/explorer" element={<Navigate to="/" replace />} />
        <Route path="/spatial-lab" element={<Navigate to="/" replace />} />
        <Route path="/entities" element={<Entities />} />
        <Route path="/stations" element={<Navigate to="/entities" replace />} />
        <Route path="/details/:chargerId" element={<Details />} />
        <Route path="/monitoring/:chargerId" element={<Monitoring />} />
        <Route path="/services" element={<Navigate to="/" replace />} />
        <Route path="/sources" element={<DataSources />} />
        <Route path="/favourites" element={<Navigate to="/entities" replace />} />
        <Route path="/account" element={<Account />} />
        <Route path="/account/settings" element={<Settings />} />
        <Route path="/anomalies" element={<Anomalies />} />
      </Route>
    </>,
  ),
);

const App = () => (
  <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
    <AuthProvider>
      <Suspense fallback={<FullPageLoading message="Loading page..." />}>
        <RouterProvider router={router} />
      </Suspense>
    </AuthProvider>
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          color: "hsl(var(--foreground))",
          background: "hsl(var(--popover))",
          border: "1px solid hsl(var(--border))",
          borderRadius: "12px",
          boxShadow: "0 16px 40px hsl(220 20% 10% / 0.12)",
          fontSize: "14px",
        },
      }}
    />
  </ThemeProvider>
);

export default App;
