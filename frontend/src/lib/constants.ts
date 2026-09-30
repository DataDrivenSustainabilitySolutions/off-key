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
  REAL_TIME_UPDATE: 60 * 1000, // 60 seconds for real-time data
  POLLING: 1000, // 1 second for file watching
  ANOMALY_ZONE_GAP: 5 * 60 * 1000, // 5 minutes max gap between anomaly clusters
} as const;
