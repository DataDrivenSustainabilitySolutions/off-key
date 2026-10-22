// Authentication configuration
export const AUTH_CONFIG = {
  PASSWORD_MIN_LENGTH: 12,
} as const;

// Form validation messages
export const VALIDATION_MESSAGES = {
  REQUIRED_FIELD: 'This field is required',
  INVALID_EMAIL: 'Please enter a valid email address',
  PASSWORD_TOO_SHORT: `Password must be at least ${AUTH_CONFIG.PASSWORD_MIN_LENGTH} characters long`,
  PASSWORDS_DONT_MATCH: 'Passwords do not match',
} as const;

// Interval constants for various operations
export const INTERVALS = {
  DETAILS_UPDATE: 10 * 1000, // 10 seconds for details page live charts
} as const;

// Largest distance between an anomaly and the telemetry sample shown with it
export const ANOMALY_SAMPLE_TOLERANCE_MS = 5_000;
