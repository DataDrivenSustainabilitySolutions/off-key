import React, { createContext, useContext, useEffect, useState } from "react";
import { tokenManager } from "@/lib/api-client";
import { getUserIdFromToken, parseNumericUserId } from "./token";

interface AuthContextType {
  isAuthenticated: boolean;
  token: string | null;
  userId: number | null;
  isLoading: boolean;
  login: (token: string, rememberMe?: boolean, userId?: unknown) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

type AuthState = {
  token: string | null;
  userId: number | null;
};

const getInitialAuthState = (): AuthState => {
  const savedToken = tokenManager.getToken();
  if (savedToken && !tokenManager.isTokenExpired(savedToken)) {
    return {
      token: savedToken,
      userId: getUserIdFromToken(savedToken),
    };
  }

  return { token: null, userId: null };
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [{ token, userId }, setAuthState] = useState(getInitialAuthState);

  useEffect(() => {
    const savedToken = tokenManager.getToken();
    if (savedToken && tokenManager.isTokenExpired(savedToken)) {
      tokenManager.removeToken();
    }
  }, []);

  /**
   * Login with token
   * @param newToken JWT token
   * @param rememberMe If true, persist in localStorage; otherwise sessionStorage
   */
  const login = (newToken: string, rememberMe = false, nextUserId?: unknown) => {
    tokenManager.setToken(newToken, rememberMe);
    setAuthState({
      token: newToken,
      userId: getUserIdFromToken(newToken) ?? parseNumericUserId(nextUserId),
    });
  };

  /**
   * Logout and clear all stored tokens
   */
  const logout = () => {
    tokenManager.removeToken();
    setAuthState({ token: null, userId: null });
  };

  const isAuthenticated = !!token && !tokenManager.isTokenExpired(token);
  const isLoading = false;

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
