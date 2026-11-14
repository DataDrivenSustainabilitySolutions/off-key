import { clearNavigationDrafts } from "@/lib/navigation-draft";
import React, { createContext, useContext, useEffect, useReducer, useState, useSyncExternalStore } from "react";
import { endSession, refreshSession, subscribeToSession, tokenManager } from "./session";
import { getTokenPayload, getUserIdFromToken } from "./token";
import { getCurrentMember, type Member, type Permission } from "@/lib/member-api";
import { loadDemoStatus, type DemoStatus } from "./demo";
import { BrowserVerificationError } from "@/lib/browser-verification";

interface AuthContextType {
  isAuthenticated: boolean;
  isGuest: boolean;
  demo: DemoStatus | null;
  userId: number | null;
  isLoading: boolean;
  authError: string | null;
  browserVerificationRequired: boolean;
  retryAuthentication: () => void;
  member: Member | null;
  /** Whether the signed-in member may make changes that need this permission. */
  can: (permission: Permission) => boolean;
  login: (token: string, rememberMe?: boolean) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);
const RENEW_FAILED = "We couldn’t renew your session. Your saved login is still available.";
const authenticationError = (error: unknown, fallback: string): Error =>
  error instanceof BrowserVerificationError ? error : new Error(fallback);

const getStoredToken = () => tokenManager.getToken();
const noServerToken = () => null;
const isRememberedSession = () => tokenManager.isRemembered();
const notRemembered = () => false;

type ProfileState = {
  token: string;
  attempt: number;
  member: Member | null;
  error: Error | null;
};

type AttemptFailure = { attempt: number; error: Error };

const reusableMember = (profile: ProfileState | null, token: string | null): Member | null => {
  if (!profile?.member || !token || tokenManager.isTokenExpired(token)) return null;
  const previous = getTokenPayload(profile.token);
  const next = getTokenPayload(token);
  return getUserIdFromToken(token) === profile.member.id
    && previous?.session_version === next?.session_version
    && previous?.sub === next?.sub ? profile.member : null;
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const token = useSyncExternalStore(subscribeToSession, getStoredToken, noServerToken);
  const [profile, setProfile] = useState<ProfileState | null>(null);
  const [attempt, retryAttempt] = useReducer((value: number) => value + 1, 0);
  const [restoreFailure, setRestoreFailure] = useState<AttemptFailure | null>(null);
  // Remembered access tokens are kept in memory; a new tab restores one from the cookie.
  const remembered = useSyncExternalStore(subscribeToSession, isRememberedSession, notRemembered);
  const restoring = !token && remembered;
  const [demo, setDemo] = useState<DemoStatus | null>(null);
  const [demoFailure, setDemoFailure] = useState<AttemptFailure | null>(null);
  useEffect(() => {
    if (token || restoring) return;
    const controller = new AbortController();
    loadDemoStatus(controller.signal).then(status => {
      if (controller.signal.aborted) return;
      setDemo(status);
      setDemoFailure(null);
    }).catch(error => {
      if (!controller.signal.aborted) setDemoFailure({ attempt, error: authenticationError(error, "We couldn’t check public access. Retry or sign in to continue.") });
    });
    return () => controller.abort();
  }, [token, restoring, attempt]);

  useEffect(() => {
    if (!restoring) return;
    let cancelled = false;
    refreshSession().catch((error: { status?: number }) => {
      if (!cancelled && error.status !== 401) setRestoreFailure({ attempt, error: authenticationError(error, RENEW_FAILED) });
    });
    return () => { cancelled = true; };
  }, [restoring, attempt]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    const resolveProfile = async () => {
      try {
        if (tokenManager.isTokenExpired(token)) {
          if (tokenManager.isRemembered()) await refreshSession();
          else tokenManager.removeToken();
          return;
        }
        const member = await getCurrentMember();
        if (!cancelled) setProfile({ token, attempt, member, error: null });
      } catch (error) {
        if (cancelled || tokenManager.getToken() !== token) return;
        const status = (error as { status?: number }).status;
        if (status === 401) {
          tokenManager.removeToken();
        } else {
          setProfile(previous => ({ token, attempt, member: reusableMember(previous, token), error: authenticationError(error, "We couldn’t connect to your account. Your saved login is still available.") }));
        }
      }
    };
    void resolveProfile();
    return () => { cancelled = true; };
  }, [token, attempt]);

  // Renew before expiry while open, and recheck when returning from sleep/offline.
  useEffect(() => {
    if (!token) return;
    const expires = getTokenPayload(token)?.exp;
    const remembered = tokenManager.isRemembered();
    let cancelled = false;
    const renew = () => {
      if (!remembered) {
        if (tokenManager.isTokenExpired(token)) tokenManager.removeToken();
        return;
      }
      void refreshSession().catch((error: { status?: number }) => {
        if (!cancelled && error.status !== 401) {
          setProfile(previous => ({ token, attempt, member: reusableMember(previous, token), error: authenticationError(error, RENEW_FAILED) }));
        }
      });
    };
    const onResume = () => {
      if (typeof expires === "number" && expires * 1000 <= Date.now() + 30_000) renew();
      if (profile?.error || tokenManager.isTokenExpired(token)) retryAttempt();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") onResume();
    };
    const delay = typeof expires === "number" ? expires * 1000 - Date.now() - (remembered ? 30_000 : 0) : 0;
    // Expired tokens are handled by the profile effect; avoid racing that path.
    const timer = !tokenManager.isTokenExpired(token)
      ? window.setTimeout(renew, Math.max(0, Math.min(delay, 2_147_483_647))) : undefined;
    window.addEventListener("online", onResume);
    window.addEventListener("focus", onResume);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.removeEventListener("online", onResume);
      window.removeEventListener("focus", onResume);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [token, attempt, profile?.error]);

  /**
   * Login with token
   * @param newToken JWT token
   * @param rememberMe If true, persist in localStorage; otherwise sessionStorage
   */
  const login = (newToken: string, rememberMe = false) => {
    if (getUserIdFromToken(newToken) !== getUserIdFromToken(tokenManager.getToken() ?? "")) clearNavigationDrafts();
    tokenManager.setToken(newToken, rememberMe);
  };

  /**
   * Logout and clear all stored tokens
   */
  const logout = () => {
    clearNavigationDrafts();
    // Clear browser state immediately, even if the server is temporarily offline.
    void endSession().catch(() => undefined);
  };

  const resolved = profile?.token === token && profile.attempt === attempt ? profile : null;
  const expired = !!token && tokenManager.isTokenExpired(token);
  const member = !expired ? resolved?.member ?? reusableMember(profile, token) : null;
  const restoreError = restoring && restoreFailure?.attempt === attempt ? restoreFailure.error : null;
  const demoError = !token && !restoring && demoFailure?.attempt === attempt ? demoFailure.error : null;
  const failure = member ? null : resolved?.error ?? restoreError ?? demoError;
  const authError = failure?.message ?? null;
  const browserVerificationRequired = failure instanceof BrowserVerificationError;
  const retryAuthentication = () => {
    // A top-level navigation lets Cloudflare complete the check; another fetch cannot.
    if (browserVerificationRequired) window.location.reload();
    else retryAttempt();
  };
  const isLoading = (restoring && !restoreError)
    || (!token && !restoring && !demo && !demoError)
    || (!!token && !member && (resolved === null || (expired && tokenManager.isRemembered() && !authError)));
  const isAuthenticated = !!token && !expired;
  const isGuest = !token && !restoring && demo?.enabled === true;
  const can = (permission: Permission) => !!member?.permissions?.includes(permission);
  const userId = token ? getUserIdFromToken(token) : null;

  useEffect(() => {
    // A remembered login restores its in-memory token after reload. Compare
    // against the saved member marker so this is not mistaken for an account switch.
    const previousUserId = userId ?? tokenManager.getMemberId();
    return subscribeToSession(() => {
      const nextToken = tokenManager.getToken();
      if (!nextToken || previousUserId !== null && getUserIdFromToken(nextToken) !== previousUserId)
        clearNavigationDrafts();
    });
  }, [userId]);

  return (
    <AuthContext.Provider
      value={{ isAuthenticated, isGuest, demo, userId, member, can, isLoading, authError, browserVerificationRequired, retryAuthentication, login, logout }}
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
