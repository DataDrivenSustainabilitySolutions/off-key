import React, { createContext, useState, useCallback, ReactNode, useContext } from "react";
import { apiUtils } from "@/lib/api-client";
import { API_CONFIG } from "@/lib/api-config";

export interface UserContextType {
  // Favorites functions
  getFavorites: (userId: number) => Promise<string[]>;
  toggleFavorite: (
    chargerId: string,
    userId: number,
    isCurrentlyFavorite: boolean
  ) => Promise<void>;
  addToFavorites: (chargerId: string, userId: number) => Promise<void>;
  removeFromFavorites: (chargerId: string, userId: number) => Promise<void>;

  // State management
  userFavorites: Record<number, string[]>;

  // Loading and error states
  loading: boolean;
  error: string | null;

  // Clear functions
  clearUserData: (userId?: number) => void;

  // Helper functions
  isFavorite: (chargerId: string, userId: number) => boolean;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export const UserProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [userFavorites, setUserFavorites] = useState<Record<number, string[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const getFavorites = useCallback(
    async (userId: number): Promise<string[]> => {
      if (!userId) throw new Error('User ID is required');

      try {
        setLoading(true);
        setError(null);

        const endpoint = API_CONFIG.ENDPOINTS.FAVORITES.GET(userId);
        const favorites = await apiUtils.get<string[]>(endpoint);

        setUserFavorites(prev => ({
          ...prev,
          [userId]: favorites,
        }));

        return favorites;
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to get favorites';
        setError(errorMessage);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const addToFavorites = useCallback(
    async (chargerId: string, userId: number) => {
      if (!chargerId || !userId) {
        throw new Error('Charger ID and User ID are required');
      }

      const endpoint = API_CONFIG.ENDPOINTS.FAVORITES.ADD;
      await apiUtils.post(endpoint, {
        charger_id: chargerId,
        user_id: userId,
      });

      // Update local state
      setUserFavorites(prev => ({
        ...prev,
        [userId]: [...(prev[userId] || []), chargerId],
      }));
    },
    []
  );

  const removeFromFavorites = useCallback(
    async (chargerId: string, userId: number) => {
      if (!chargerId || !userId) {
        throw new Error('Charger ID and User ID are required');
      }

      const endpoint = API_CONFIG.ENDPOINTS.FAVORITES.REMOVE;
      await apiUtils.delete(endpoint, {
        charger_id: chargerId,
        user_id: userId,
      });

      // Update local state
      setUserFavorites(prev => ({
        ...prev,
        [userId]: (prev[userId] || []).filter(id => id !== chargerId),
      }));
    },
    []
  );

  const toggleFavorite = useCallback(
    async (chargerId: string, userId: number, isCurrentlyFavorite: boolean) => {
      try {
        setLoading(true);
        setError(null);

        if (isCurrentlyFavorite) {
          await removeFromFavorites(chargerId, userId);
        } else {
          await addToFavorites(chargerId, userId);
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to toggle favorite';
        setError(errorMessage);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [addToFavorites, removeFromFavorites]
  );

  const isFavorite = useCallback(
    (chargerId: string, userId: number): boolean => {
      return userFavorites[userId]?.includes(chargerId) ?? false;
    },
    [userFavorites]
  );

  const clearUserData = useCallback((userId?: number) => {
    if (userId) {
      setUserFavorites(prev => {
        const rest = { ...prev };
        delete rest[userId];
        return rest;
      });
    } else {
      setUserFavorites({});
    }
  }, []);

  return (
    <UserContext.Provider
      value={{
        getFavorites,
        toggleFavorite,
        addToFavorites,
        removeFromFavorites,
        userFavorites,
        loading,
        error,
        clearUserData,
        isFavorite,
      }}
    >
      {children}
    </UserContext.Provider>
  );
};

export const useUser = (): UserContextType => {
  const context = useContext(UserContext);
  if (!context) {
    throw new Error("useUser must be used within a UserProvider");
  }
  return context;
};
