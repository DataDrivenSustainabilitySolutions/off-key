import { lazy, Suspense } from "react";
import { BrowserRouter, Outlet, Route, Routes } from "react-router-dom";
import { Toaster } from "react-hot-toast";

import "@/App.css";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { FullPageLoading } from "@/components/LoadingStates";
import { ThemeProvider } from "@/components/theme-provider";

const Account = lazy(() => import("@/pages/Account"));
const Anomalies = lazy(() => import("@/pages/Anomalies"));
const Details = lazy(() => import("@/pages/Details"));
const Favourites = lazy(() => import("@/pages/Favourites"));
const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
const LandingPage = lazy(() => import("@/pages/Landingpage"));
const Login = lazy(() => import("@/pages/Login"));
const Monitoring = lazy(() => import("@/pages/Monitoring"));
const Registration = lazy(() => import("@/pages/Registration"));
const ResetPassword = lazy(() => import("@/pages/ResetPassword"));
const Services = lazy(() => import("@/pages/Services"));
const Verification = lazy(() => import("@/pages/Verification"));

const AppRoutes = () => (
  <Suspense fallback={<FullPageLoading message="Loading page..." />}>
    <Routes>
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
        <Route path="/favourites" element={<Favourites />} />
        <Route path="/account" element={<Account />} />
        <Route path="/anomalies" element={<Anomalies />} />
      </Route>
    </Routes>
  </Suspense>
);

const App = () => (
  <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
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
