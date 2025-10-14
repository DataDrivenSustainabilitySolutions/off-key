import React, { createContext, useContext, useState, useEffect } from "react";

interface AuthContextType {
  isAuthenticated: boolean;
  token: string | null;
  userId: number | null;
  isLoading: boolean;
  login: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const getUserIdFromToken = (token: string): number | null => {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.sub ? parseInt(payload.sub) : null;
    } catch {
      return null;
    }
  };

  useEffect(() => {
    const savedToken = localStorage.getItem("token") || sessionStorage.getItem("token");
    if (savedToken) {
      setToken(savedToken);
      setUserId(getUserIdFromToken(savedToken));
    }
    setIsLoading(false);
  }, []);

    

  const login = (newToken: string) => {
    sessionStorage.setItem("token", newToken);
    setToken(newToken);
    setUserId(getUserIdFromToken(newToken));
  };

  const logout = () => {
    sessionStorage.removeItem("token");
    localStorage.removeItem("token");
    setToken(null);
    setUserId(null);
  };

  const isAuthenticated = !!token;

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
