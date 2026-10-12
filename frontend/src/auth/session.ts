import { isTokenExpired } from './token';
import { API_CONFIG, getApiUrl } from '@/lib/api-config';

const TOKEN_KEY = 'auth_token';
const STORAGE_TYPE_KEY = 'token_storage_type';
const SESSION_CHANGED = 'off-key-session-changed';
let generation = 0;
let renewal: Promise<string | null> | null = null;
let logoutRequest: Promise<void> | null = null;

export class SessionRequestError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'SessionRequestError';
  }
}

export const tokenManager = {
  getToken(): string | null {
    return this.isRemembered()
      ? localStorage.getItem(TOKEN_KEY)
      : sessionStorage.getItem(TOKEN_KEY);
  },

  isRemembered(): boolean {
    return localStorage.getItem(STORAGE_TYPE_KEY) === 'localStorage';
  },

  setToken(token: string, rememberMe = false): void {
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    (rememberMe ? localStorage : sessionStorage).setItem(TOKEN_KEY, token);
    localStorage.setItem(STORAGE_TYPE_KEY, rememberMe ? 'localStorage' : 'sessionStorage');
    generation += 1;
    window.dispatchEvent(new Event(SESSION_CHANGED));
  },

  removeToken(): void {
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(STORAGE_TYPE_KEY);
    generation += 1;
    window.dispatchEvent(new Event(SESSION_CHANGED));
  },

  isTokenExpired,
};

export const subscribeToSession = (onChange: () => void): (() => void) => {
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === TOKEN_KEY || event.key === STORAGE_TYPE_KEY) onChange();
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
