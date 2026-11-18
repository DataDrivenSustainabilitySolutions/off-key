import { claimNavigationDrafts, clearNavigationDrafts } from "@/lib/navigation-draft";
import React, { createContext, useContext, useEffect, useReducer, useRef, useState, useSyncExternalStore } from "react";
import { endSession, refreshSession, subscribeToSession, subscribeToSignOut, tokenManager, type SessionLifetimes } from "./session";
import { getTokenPayload, getUserIdFromToken, tokenRemainingMs } from "./token";
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
  /** The access token could not be renewed yet; the page stays while retries run. */
  reconnecting: boolean;
  /** When the sign-in ends and the member must enter their password again. */
  sessionEndsAt: number | null;
  login: (token: string, lifetimes?: SessionLifetimes) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);
const RENEW_FAILED = "We couldn’t renew your session. Your saved login is still available.";
const authenticationError = (error: unknown, fallback: string): Error =>
  error instanceof BrowserVerificationError ? error : new Error(fallback);

const getStoredToken = () => tokenManager.getToken();
const getSessionEndsAt = () => tokenManager.getSessionEndsAt();
const noServerToken = () => null;
// Renew two minutes before expiry, or a fifth of the way before for short tokens.
const renewalLead = (remainingMs: number) => Math.min(120_000, Math.max(5_000, remainingMs / 5));
// After a failed renewal, try again after these pauses, then every minute.
const RETRY_DELAYS = [5_000, 10_000, 20_000, 40_000, 60_000];
const MAX_TIMER = 2_147_483_647;
const isRememberedSession = () => tokenManager.isRemembered();
const notRemembered = () => false;

type ProfileState = {
  token: string;
  attempt: number;
  member: Member | null;
  error: Error | null;
};

type AttemptFailure = { attempt: number; error: Error };
type RenewalFailure = { token: string; error: Error };

/** The member a profile names, when the token is the same sign-in, expired or not. */
const knownMember = (profile: ProfileState | null, token: string | null): Member | null => {
  if (!profile?.member || !token) return null;
  const previous = getTokenPayload(profile.token);
  const next = getTokenPayload(token);
  return getUserIdFromToken(token) === profile.member.id
    && previous?.session_version === next?.session_version
    && previous?.sub === next?.sub ? profile.member : null;
};

const reusableMember = (profile: ProfileState | null, token: string | null): Member | null =>
  token && !tokenManager.isTokenExpired(token) ? knownMember(profile, token) : null;

/** Expired cookie-backed sign-ins keep their member while renewal is retried. */
const keptMember = (profile: ProfileState | null, token: string | null): Member | null =>
  tokenManager.isRemembered() ? knownMember(profile, token) : reusableMember(profile, token);

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
  const sessionEndsAt = useSyncExternalStore(subscribeToSession, getSessionEndsAt, noServerToken);
  const [renewalFailure, setRenewalFailure] = useState<RenewalFailure | null>(null);
  const profileError = useRef<Error | null>(null);
  profileError.current = profile?.error ?? null;
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
          setProfile(previous => ({ token, attempt, member: keptMember(previous, token), error: authenticationError(error, "We couldn’t connect to your account. Your saved login is still available.") }));
        }
      }
    };
    void resolveProfile();
    return () => { cancelled = true; };
  }, [token, attempt]);

  // Renew before expiry while open, retry with backoff through outages, and
  // recheck when returning from sleep or going back online. Renewal is shared
  // with the profile check and API requests, so they never race each other.
  useEffect(() => {
    if (!token) return;
    const current = token;
    const remembered = tokenManager.isRemembered();
    let cancelled = false;
    let timer: number | undefined;
    let failures = 0;
    const schedule = (delay: number) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(renew, Math.max(0, Math.min(delay, MAX_TIMER)));
    };
    function renew() {
      if (!remembered) {
        // Sign-ins from before every session had a cookie cannot renew.
        if (tokenManager.isTokenExpired(current)) tokenManager.removeToken();
        else schedule(tokenRemainingMs(current) ?? 0);
        return;
      }
      void refreshSession().catch((error: { status?: number }) => {
        // A 401 ended the sign-in; the session store has already signed out.
        if (cancelled || error.status === 401) return;
        setRenewalFailure({ token: current, error: authenticationError(error, RENEW_FAILED) });
        schedule(RETRY_DELAYS[Math.min(failures++, RETRY_DELAYS.length - 1)] ?? 60_000);
      });
    }
    const onResume = () => {
      const remaining = tokenRemainingMs(current);
      if (remaining === null || remaining <= renewalLead(remaining)) schedule(0);
      if (profileError.current || tokenManager.isTokenExpired(current)) retryAttempt();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") onResume();
    };
    const remaining = tokenRemainingMs(current) ?? 0;
    schedule(remembered ? remaining - renewalLead(remaining) : remaining);
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
  }, [token, attempt]);

  // Drafts outlive the end of a sign-in, so signing in again picks the work up.
  // They are dropped on purpose only by signing out, or when another member signs in.
  useEffect(() => {
    const claim = () => {
      const current = tokenManager.getToken();
      const id = current ? getUserIdFromToken(current) : null;
      if (id) claimNavigationDrafts(id);
    };
    claim();
    const stopSession = subscribeToSession(claim);
    const stopSignOut = subscribeToSignOut(clearNavigationDrafts);
    return () => { stopSession(); stopSignOut(); };
  }, []);

  /**
   * Start using a token from a sign-in. The session cookie set with it renews
   * the token; "Remember this device" only decides how long that cookie lasts.
   */
  const login = (newToken: string, lifetimes?: SessionLifetimes) => {
    const memberId = getUserIdFromToken(newToken);
    // Before the token is visible, so another member never sees these drafts.
    if (memberId) claimNavigationDrafts(memberId);
    tokenManager.setToken(newToken, true, lifetimes);
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
  // An expired cookie-backed sign-in keeps its page while renewal catches up,
  // so a slow or failed renewal never unmounts unsaved work.
  const member = !expired
    ? resolved?.member ?? reusableMember(profile, token)
    : remembered ? knownMember(profile, token) : null;
  const restoreError = restoring && restoreFailure?.attempt === attempt ? restoreFailure.error : null;
  const demoError = !token && !restoring && demoFailure?.attempt === attempt ? demoFailure.error : null;
  const failure = member ? null : resolved?.error ?? restoreError ?? demoError;
  const authError = failure?.message ?? null;
  const renewalError = member && renewalFailure?.token === token ? renewalFailure.error : null;
  const reconnecting = !!renewalError && !(renewalError instanceof BrowserVerificationError);
  // A challenged renewal shows the page-wide browser verification notice.
  const browserVerificationRequired = failure instanceof BrowserVerificationError;
  const retryAuthentication = () => {
    // A top-level navigation lets Cloudflare complete the check; another fetch cannot.
    if (browserVerificationRequired) window.location.reload();
    else retryAttempt();
  };
  const isLoading = (restoring && !restoreError)
    || (!token && !restoring && !demo && !demoError)
    || (!!token && !member && (resolved === null || (expired && tokenManager.isRemembered() && !authError)));
  const isAuthenticated = !!token && (!expired || !!member);
  const isGuest = !token && !restoring && demo?.enabled === true;
  const can = (permission: Permission) => !!member?.permissions?.includes(permission);
  const userId = token ? getUserIdFromToken(token) : null;

  return (
    <AuthContext.Provider
      value={{ isAuthenticated, isGuest, demo, userId, member, can, isLoading, authError, browserVerificationRequired, retryAuthentication, reconnecting, sessionEndsAt, login, logout }}
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
