"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "@/lib/api/client";

// --- Types ---

interface User {
  user_id: number;
  email: string;
  balance: number; // cents
  role: "user" | "admin";
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  refetch: () => Promise<void>;
  logout: () => Promise<void>;
}

// --- Context ---

const AuthContext = createContext<AuthState | undefined>(undefined);

// --- Provider ---

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    try {
      const data = await apiClient<User>("/auth/me");
      setUser(data);
    } catch (err) {
      // Only clear user on auth errors (401); keep session on transient failures
      if (err instanceof ApiClientError && err.status === 401) {
        setUser(null);
      }
      // On network/server errors, keep current user state to avoid false logout
    }
  }, []);

  // Fetch current user on mount
  useEffect(() => {
    fetchUser().finally(() => setIsLoading(false));
  }, [fetchUser]);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    await fetchUser();
    setIsLoading(false);
  }, [fetchUser]);

  const logout = useCallback(async () => {
    try {
      await apiClient("/auth/logout", { method: "POST" });
    } catch {
      // Even if the API call fails, clear local state
    }
    setUser(null);
    // Clear all react-query caches
    queryClient.clear();
  }, [queryClient]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: user !== null,
        refetch,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// --- Hook ---

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an <AuthProvider>");
  }
  return ctx;
}
