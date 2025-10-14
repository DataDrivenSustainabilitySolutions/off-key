/**
 * Application constants and configuration values
 * Centralized location for all magic numbers and thresholds
 */

// Telemetry thresholds for anomaly detection
export const TELEMETRY_THRESHOLDS = {
  CPU_USAGE: 7, // Percentage threshold for CPU usage alerts
  CPU_TEMPERATURE: 43, // Temperature threshold for CPU thermal alerts (°C)
} as const;

// Chart configuration
export const CHART_CONFIG = {
  TEMPERATURE: {
    Y_AXIS_DOMAIN: [30, 80], // Temperature range for Y-axis
    Y_AXIS_TICKS: [40, 50, 60, 70, 80], // Temperature tick marks
  },
  
  // Data refresh intervals
  REFRESH_INTERVALS: {
    TELEMETRY_SYNC: 60 * 1000, // 60 seconds
    REAL_TIME_UPDATE: 60 * 1000, // 60 seconds for real-time data
  },
  
  // Chart styling
  COLORS: {
    PRIMARY_LINE: '#8884d8',
    RED_ZONE_FILL: 'red',
    RED_ZONE_OPACITY: 0.1,
    ALERT_DOT: 'red',
    ALERT_DOT_RADIUS: 2,
  },
} as const;

// Authentication configuration
export const AUTH_CONFIG = {
  PASSWORD_MIN_LENGTH: 8,
  TOKEN_REFRESH_BUFFER: 5 * 60, // 5 minutes before expiration
  LOGIN_REDIRECT_DELAY: 2000, // 2 seconds delay after successful login
  REGISTRATION_REDIRECT_DELAY: 3000, // 3 seconds delay after successful registration
} as const;

// UI Configuration
export const UI_CONFIG = {
  // Date/time filters
  QUICK_FILTERS: {
    LAST_30_MINUTES: 30,
    LAST_HOUR: 60,
  },
  
  // Pagination
  DEFAULT_LIMIT: 1000, // Default telemetry data limit
  SHORT_SYNC_LIMIT: 100, // Short sync telemetry limit
  
  // Polling intervals for Docker environments
  POLLING_INTERVAL: 1000, // 1 second for file watching
} as const;

// Form validation messages
export const VALIDATION_MESSAGES = {
  REQUIRED_FIELD: 'This field is required',
  INVALID_EMAIL: 'Please enter a valid email address',
  PASSWORD_TOO_SHORT: `Password must be at least ${AUTH_CONFIG.PASSWORD_MIN_LENGTH} characters long`,
  PASSWORDS_DONT_MATCH: 'Passwords do not match',
  INVALID_CREDENTIALS: 'Invalid email or password',
  EMAIL_NOT_VERIFIED: 'Please verify your email before logging in',
  GENERIC_ERROR: 'An error occurred. Please try again.',
  NETWORK_ERROR: 'Network error. Please check your connection.',
} as const;

// HTTP status codes
export const HTTP_STATUS = {
  OK: 200,
  CREATED: 201,
  BAD_REQUEST: 400,
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  INTERNAL_SERVER_ERROR: 500,
} as const;

// Local storage keys
export const STORAGE_KEYS = {
  AUTH_TOKEN: 'auth_token',
  TOKEN_STORAGE_TYPE: 'token_storage_type',
  USER_PREFERENCES: 'user_preferences',
} as const;

// Anomaly detection algorithms
export const ANOMALY_ALGORITHMS = {
  ALGORITHM_A: 'Algorithm A',
  ALGORITHM_B: 'Algorithm B',
} as const;

// API rate limiting and retry configuration
export const API_CONFIG = {
  REQUEST_TIMEOUT: 10000, // 10 seconds
  RETRY_ATTEMPTS: 3,
  RETRY_DELAY: 1000, // 1 second
} as const;

// WebSocket configuration
export const WEBSOCKET_CONFIG = {
  HEARTBEAT_INTERVAL: 30 * 1000, // 30 seconds
  RECONNECT_DELAY: 5 * 1000, // 5 seconds
  MAX_RECONNECT_ATTEMPTS: 5,
} as const;

// Interval constants for various operations
export const INTERVALS = {
  TELEMETRY_SYNC: 60 * 1000, // 60 seconds
  REAL_TIME_UPDATE: 60 * 1000, // 60 seconds for real-time data
  WEBSOCKET_HEARTBEAT: 30 * 1000, // 30 seconds heartbeat
  WEBSOCKET_RECONNECT_DELAY: 5 * 1000, // 5 seconds reconnect delay
  POLLING: 1000, // 1 second for file watching
} as const;