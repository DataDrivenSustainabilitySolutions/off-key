import React, { createContext, useContext, useState, useEffect } from "react";
import { tokenManager } from "@/lib/api-client";

interface AuthContextType {
  isAuthenticated: boolean;
  token: string | null;
  userId: number | null;
  isLoading: boolean;
  login: (token: string, rememberMe?: boolean) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * Extract user ID from JWT token payload
 */
const getUserIdFromToken = (token: string): number | null => {
  try {
    const base64 = token.split(".")[1];
    const base64Standard = base64.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64Standard.padEnd(
      base64Standard.length + ((4 - (base64Standard.length % 4)) % 4),
      "="
    );
    const payload = JSON.parse(atob(padded));
    return payload.sub ? parseInt(payload.sub, 10) : null;
  } catch {
    return null;
  }
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Initialize from stored token using centralized tokenManager
  useEffect(() => {
    const savedToken = tokenManager.getToken();
    if (savedToken && !tokenManager.isTokenExpired(savedToken)) {
      setToken(savedToken);
      setUserId(getUserIdFromToken(savedToken));
    } else if (savedToken) {
      // Token exists but is expired - clean up
      tokenManager.removeToken();
    }
    setIsLoading(false);
  }, []);

  /**
   * Login with token
   * @param newToken JWT token
   * @param rememberMe If true, persist in localStorage; otherwise sessionStorage
   */
  const login = (newToken: string, rememberMe = false) => {
    tokenManager.setToken(newToken, rememberMe);
    setToken(newToken);
    setUserId(getUserIdFromToken(newToken));
  };

  /**
   * Logout and clear all stored tokens
   */
  const logout = () => {
    tokenManager.removeToken();
    setToken(null);
    setUserId(null);
  };

  const isAuthenticated = !!token && !tokenManager.isTokenExpired(token);

  return (
    <AuthContext.Provider
      value={{ isAuthenticated, token, userId, isLoading, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
