/** Cloudflare challenge HTML cannot be completed by an API request. */
export class BrowserVerificationError extends Error {
  readonly status = 403;

  constructor() {
    super('Cloudflare needs to verify your browser. Reload this page to continue.');
    this.name = 'BrowserVerificationError';
  }
}
