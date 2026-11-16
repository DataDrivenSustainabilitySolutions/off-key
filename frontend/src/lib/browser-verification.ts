/** Cloudflare challenge HTML cannot be completed by an API request. */
export class BrowserVerificationError extends Error {
  readonly status = 403;

  constructor() {
    super('Cloudflare needs to verify your browser. Reload this page to continue.');
    this.name = 'BrowserVerificationError';
  }
}

// Cloudflare's clearance can lapse while a page sits open, so a background
// poll is the first to meet the challenge. Remember that for the whole page:
// only a document navigation can complete the check, never another fetch.
let required = false;
const listeners = new Set<() => void>();

export const isBrowserVerificationRequired = () => required;

/** Record a challenged response and return the error to reject with. */
export function browserVerificationRequired(): BrowserVerificationError {
  if (!required) {
    required = true;
    listeners.forEach(listener => listener());
  }
  return new BrowserVerificationError();
}

export function subscribeToBrowserVerification(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Reload the current page so Cloudflare can complete its check and return here. */
export const verifyBrowser = () => window.location.reload();

/** Whether the request being made follows a click or key press, such as a Retry button. */
export const followsUserAction = () =>
  typeof navigator !== 'undefined' && navigator.userActivation?.isActive === true;

/** Test hook: forget an earlier challenge. */
export const resetBrowserVerification = () => { required = false; };
