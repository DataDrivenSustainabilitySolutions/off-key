import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
// import Default from "@/pages/Default";
import Login from "@/pages/Login";
import Details from "./pages/Details";
import Registration from "@/pages/Registration";
import Verification from "@/pages/Verification";
import "@/App.css";
import { ThemeProvider } from "./components/theme-provider";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import Landingpage from "./pages/Landingpage";
import Favourites from "./pages/Favourites";
import Monitoring from "./pages/Monitoring";
import Account from "./pages/Account";
import Anomaly from "./pages/Anomalies";
import { FetchProvider } from "./dataFetch/FetchContext";

const App: React.FC = () => {
  return (
    <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
      <AuthProvider>
        <BrowserRouter>
          <FetchProvider>
            <Routes>
              {/* <Route path="/" element={<Default />} /> */}
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Registration />} />
              <Route path="/verify" element={<Verification />} />
              <Route path="/forgot-password" element={<ForgotPassword />} />
              <Route path="/reset-password" element={<ResetPassword />} />

              {/* Guarded Routes */}
              <Route
                path="/"
                element={
                  <ProtectedRoute>
                    <Landingpage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/details/:chargerId"
                element={
                  <ProtectedRoute>
                    <Details />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/monitoring/:chargerId"
                element={
                  <ProtectedRoute>
                    <Monitoring />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/favourites"
                element={
                  <ProtectedRoute>
                    <Favourites />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/account"
                element={
                  <ProtectedRoute>
                    <Account />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/anomalies"
                element={
                  <ProtectedRoute>
                    <Anomaly />
                  </ProtectedRoute>
                }
              />
            </Routes>
          </FetchProvider>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
};
export default App;
