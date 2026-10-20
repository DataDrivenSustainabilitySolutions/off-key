import { getUserIdFromToken, isTokenExpired, parseNumericUserId } from './token';
import { API_CONFIG, getApiUrl } from '@/lib/api-config';

const TOKEN_KEY = 'auth_token';
const STORAGE_TYPE_KEY = 'token_storage_type';
const REMEMBERED = 'remembered';
// Non-secret marker that tells other tabs a different member signed in.
const MEMBER_KEY = 'session_member';
const SESSION_CHANGED = 'off-key-session-changed';
let generation = 0;
// Remembered sessions keep the bearer token in memory only; each tab restores
// it from the HttpOnly cookie, so injected scripts cannot lift it from storage.
let rememberedToken: string | null = null;

const readStorageType = (): string | null => {
  try {
    return localStorage.getItem(STORAGE_TYPE_KEY);
  } catch {
    return null;
  }
};

// Releases before this one persisted remembered tokens in localStorage.
try {
  if (readStorageType() === 'localStorage') {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.setItem(STORAGE_TYPE_KEY, REMEMBERED);
  }
} catch {
  // Storage can be unavailable; the in-memory session still works.
}
let renewal: Promise<string | null> | null = null;
let logoutRequest: Promise<void> | null = null;

export class SessionRequestError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'SessionRequestError';
  }
}

export const tokenManager = {
  getMemberId(): number | null {
    try { return parseNumericUserId(localStorage.getItem(MEMBER_KEY)); }
    catch { return null; }
  },
  getToken(): string | null {
    return this.isRemembered()
      ? rememberedToken
      : sessionStorage.getItem(TOKEN_KEY);
  },

  isRemembered(): boolean {
    return readStorageType() === REMEMBERED;
  },

  setToken(token: string, rememberMe = false): void {
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    rememberedToken = rememberMe ? token : null;
    if (!rememberMe) sessionStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(STORAGE_TYPE_KEY, rememberMe ? REMEMBERED : 'sessionStorage');
    localStorage.setItem(MEMBER_KEY, String(getUserIdFromToken(token) ?? ''));
    generation += 1;
    window.dispatchEvent(new Event(SESSION_CHANGED));
  },

  removeToken(): void {
    rememberedToken = null;
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(STORAGE_TYPE_KEY);
    localStorage.removeItem(MEMBER_KEY);
    generation += 1;
    window.dispatchEvent(new Event(SESSION_CHANGED));
  },

  isTokenExpired,
};

export const subscribeToSession = (onChange: () => void): (() => void) => {
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === TOKEN_KEY || event.key === STORAGE_TYPE_KEY || event.key === MEMBER_KEY) {
      // Another tab signed out or switched accounts; drop this tab's copy so
      // it restores the current member from the shared cookie.
      if (!tokenManager.isRemembered() || event.key === MEMBER_KEY || event.key === null) rememberedToken = null;
      onChange();
    }
  };
  window.addEventListener(SESSION_CHANGED, onChange);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(SESSION_CHANGED, onChange);
    window.removeEventListener('storage', onStorage);
  };
};

const sessionRequest = (endpoint: string) => fetch(getApiUrl(endpoint), {
  method: 'POST',
  credentials: 'include',
  headers: { 'X-Off-Key-Session': '1' },
  signal: AbortSignal.timeout(API_CONFIG.TIMEOUT),
});

/** Share one renewal across simultaneous requests; logout wins over late replies. */
export const refreshSession = (): Promise<string | null> => {
  if (!tokenManager.isRemembered()) return Promise.resolve(null);
  if (renewal) return renewal;
  const startedGeneration = generation;
  const previousToken = tokenManager.getToken();
  renewal = (async () => {
    const response = await sessionRequest(API_CONFIG.ENDPOINTS.AUTH.REFRESH);
    if (startedGeneration !== generation || !tokenManager.isRemembered()) return tokenManager.getToken();
    const currentToken = tokenManager.getToken();
    if (currentToken !== previousToken && currentToken && !isTokenExpired(currentToken)) return currentToken;
    if (!response.ok) {
      if (response.status === 401) tokenManager.removeToken();
      throw new SessionRequestError(
        response.status === 401 ? 'Please sign in again.' : 'Unable to renew your session. Please retry.',
        response.status,
      );
    }
    const data: { access_token?: string } = await response.json();
    // Another tab may have renewed or signed out while this request was running.
    if (startedGeneration !== generation || !tokenManager.isRemembered()) return tokenManager.getToken();
    if (typeof data.access_token !== 'string' || isTokenExpired(data.access_token)) {
      throw new SessionRequestError('The session service returned an invalid response.', 502);
    }
    tokenManager.setToken(data.access_token, true);
    return data.access_token;
  })().finally(() => { renewal = null; });
  return renewal;
};

export const endSession = (): Promise<void> => {
  tokenManager.removeToken();
  logoutRequest ??= sessionRequest(API_CONFIG.ENDPOINTS.AUTH.LOGOUT)
    .then(() => undefined)
    .finally(() => { logoutRequest = null; });
  return logoutRequest;
};

/** Finish the old cookie deletion before a new login can set its cookie. */
export const waitForLogout = async (): Promise<void> => {
  await logoutRequest?.catch(() => undefined);
};
