import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Default from "@/pages/Default";
import Login from "@/pages/Login";
import Details from "./pages/Details";
import Registration from "@/pages/Registration";
import Verification from "@/pages/Verification";
import "@/App.css";
import { NavigationBar } from "./components/NavigationBar";
import List from "@/pages/List";
import { ThemeProvider } from "./components/theme-provider";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";

const App: React.FC = () => {
  return (
    <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
      <AuthProvider>
        <BrowserRouter>
          <NavigationBar></NavigationBar>
          <Routes>
            <Route path="/" element={<Default />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Registration />} />
            <Route path="/verify" element={<Verification />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />

            {/* GESCHÜTZTE ROUTE */}
            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <div>Dashboard Inhalt</div>
                </ProtectedRoute>
              }
            />
            <Route
              path="/list"
              element={
                <ProtectedRoute>
                  <List />
                </ProtectedRoute>
              }
            />
            <Route
              path="/details/:charger_id"
              element={
                <ProtectedRoute>
                  <Details />
                </ProtectedRoute>
              }
            />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
};
export default App;
