import { API_CONFIG, getApiUrl } from '@/lib/api-config';

// Signed-out visitors of a public demo installation browse read-only; the
// gateway answers their calls as its viewer member, so they carry no token.
let guest = false;

export const isDemoGuest = (): boolean => guest;

export const setDemoGuest = (value: boolean): void => {
  guest = value;
};

/** Whether this installation lets signed-out visitors browse; false when unreachable. */
export const fetchDemoEnabled = async (): Promise<boolean> => {
  try {
    const response = await fetch(getApiUrl(API_CONFIG.ENDPOINTS.DEMO), {
      signal: AbortSignal.timeout(API_CONFIG.TIMEOUT),
    });
    if (!response.ok) return false;
    const data: { enabled?: unknown } = await response.json();
    return data.enabled === true;
  } catch {
    return false;
  }
};
