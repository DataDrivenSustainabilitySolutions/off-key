import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Default from "@/pages/Default";
import Login from '@/pages/Login';
import Registration from '@/pages/Registration';
import Verification from '@/pages/Verification';
import "@/App.css";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
// import {NavigationBar} from "./components/NavigationBar";

const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
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
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
};
export default App;


