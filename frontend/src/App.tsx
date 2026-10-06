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
const DataSources = lazy(() => import("@/pages/DataSources"));
const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
const LandingPage = lazy(() => import("@/pages/Landingpage"));
const Login = lazy(() => import("@/pages/Login"));
const Monitoring = lazy(() => import("@/pages/Monitoring"));
const Registration = lazy(() => import("@/pages/Registration"));
const ResetPassword = lazy(() => import("@/pages/ResetPassword"));
const Services = lazy(() => import("@/pages/Services"));
const Settings = lazy(() => import("@/pages/Settings"));
const Verification = lazy(() => import("@/pages/Verification"));
const SpatialLab = lazy(() => import("@/pages/SpatialLab"));

const router = createBrowserRouter(
  createRoutesFromElements(
    <>
      {import.meta.env.DEV && <Route path="/spatial-lab" element={<SpatialLab />} />}
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
        <Route path="/" element={<LandingPage />} />
        <Route path="/details/:chargerId" element={<Details />} />
        <Route path="/monitoring/:chargerId" element={<Monitoring />} />
        <Route path="/services" element={<Services />} />
        <Route path="/sources" element={<DataSources />} />
        <Route path="/favourites" element={<Navigate to="/?state=favorites" replace />} />
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
