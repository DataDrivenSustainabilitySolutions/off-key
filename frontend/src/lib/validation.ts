/**
 * Input validation utilities for security and data integrity
 */

import { VALIDATION_MESSAGES, AUTH_CONFIG } from './constants';

// Email validation regex
const EMAIL_REGEX = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

// Charger ID validation (alphanumeric with hyphens and underscores)
const CHARGER_ID_REGEX = /^[a-zA-Z0-9_-]+$/;

// Username validation (alphanumeric with underscores)
const USERNAME_REGEX = /^[a-zA-Z0-9_]{3,50}$/;

export interface ValidationResult {
  isValid: boolean;
  message?: string;
}

/**
 * Sanitize string input to prevent XSS
 */
export const sanitizeInput = (input: string): string => {
  return input
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;')
    .replace(/\//g, '&#x2F;')
    .trim();
};

/**
 * Validate email address
 */
export const validateEmail = (email: string): ValidationResult => {
  if (!email) {
    return { isValid: false, message: VALIDATION_MESSAGES.REQUIRED_FIELD };
  }

  const sanitized = sanitizeInput(email);
  if (!EMAIL_REGEX.test(sanitized)) {
    return { isValid: false, message: VALIDATION_MESSAGES.INVALID_EMAIL };
  }

  return { isValid: true };
};

/**
 * Validate password
 */
export const validatePassword = (password: string): ValidationResult => {
  if (!password) {
    return { isValid: false, message: VALIDATION_MESSAGES.REQUIRED_FIELD };
  }

  if (password.length < AUTH_CONFIG.PASSWORD_MIN_LENGTH) {
    return { isValid: false, message: VALIDATION_MESSAGES.PASSWORD_TOO_SHORT };
  }

  return { isValid: true };
};

/**
 * Validate password confirmation
 */
export const validatePasswordConfirmation = (
  password: string,
  confirmPassword: string
): ValidationResult => {
  if (!confirmPassword) {
    return { isValid: false, message: VALIDATION_MESSAGES.REQUIRED_FIELD };
  }

  if (password !== confirmPassword) {
    return { isValid: false, message: VALIDATION_MESSAGES.PASSWORDS_DONT_MATCH };
  }

  return { isValid: true };
};

/**
 * Validate charger ID
 */
export const validateChargerId = (chargerId: string): ValidationResult => {
  if (!chargerId) {
    return { isValid: false, message: 'Charger ID is required' };
  }

  const sanitized = sanitizeInput(chargerId);
  if (!CHARGER_ID_REGEX.test(sanitized)) {
    return { isValid: false, message: 'Charger ID must contain only letters, numbers, hyphens, and underscores' };
  }

  if (sanitized.length > 100) {
    return { isValid: false, message: 'Charger ID must be less than 100 characters' };
  }

  return { isValid: true };
};

/**
 * Validate user ID (number)
 */
export const validateUserId = (userId: number | string): ValidationResult => {
  const id = typeof userId === 'string' ? parseInt(userId) : userId;

  if (isNaN(id) || id <= 0) {
    return { isValid: false, message: 'Invalid user ID' };
  }

  return { isValid: true };
};

/**
 * Validate username
 */
export const validateUsername = (username: string): ValidationResult => {
  if (!username) {
    return { isValid: false, message: VALIDATION_MESSAGES.REQUIRED_FIELD };
  }

  const sanitized = sanitizeInput(username);
  if (!USERNAME_REGEX.test(sanitized)) {
    return { isValid: false, message: 'Username must be 3-50 characters and contain only letters, numbers, and underscores' };
  }

  return { isValid: true };
};

/**
 * Validate date input
 */
export const validateDate = (date: Date | string | null): ValidationResult => {
  if (!date) {
    return { isValid: true }; // Optional field
  }

  const dateObj = typeof date === 'string' ? new Date(date) : date;

  if (isNaN(dateObj.getTime())) {
    return { isValid: false, message: 'Invalid date format' };
  }

  // Check if date is not in the future (for most use cases)
  const now = new Date();
  if (dateObj > now) {
    return { isValid: false, message: 'Date cannot be in the future' };
  }

  // Check if date is not too far in the past (1 year)
  const oneYearAgo = new Date();
  oneYearAgo.setFullYear(now.getFullYear() - 1);
  if (dateObj < oneYearAgo) {
    return { isValid: false, message: 'Date cannot be more than one year in the past' };
  }

  return { isValid: true };
};

/**
 * Validate date range
 */
export const validateDateRange = (
  fromDate: Date | string | null,
  toDate: Date | string | null
): ValidationResult => {
  if (!fromDate || !toDate) {
    return { isValid: true }; // Optional fields
  }

  const from = typeof fromDate === 'string' ? new Date(fromDate) : fromDate;
  const to = typeof toDate === 'string' ? new Date(toDate) : toDate;

  if (isNaN(from.getTime()) || isNaN(to.getTime())) {
    return { isValid: false, message: 'Invalid date format' };
  }

  if (from >= to) {
    return { isValid: false, message: 'Start date must be before end date' };
  }

  // Check if range is not too large (e.g., more than 1 year)
  const oneYear = 365 * 24 * 60 * 60 * 1000; // milliseconds
  if (to.getTime() - from.getTime() > oneYear) {
    return { isValid: false, message: 'Date range cannot exceed one year' };
  }

  return { isValid: true };
};

/**
 * Validate anomaly algorithm selection
 */
export const validateAnomalyAlgorithm = (algorithm: string): ValidationResult => {
  if (!algorithm) {
    return { isValid: false, message: 'Please select an algorithm' };
  }

  const validAlgorithms = ['Algorithm A', 'Algorithm B'];
  if (!validAlgorithms.includes(algorithm)) {
    return { isValid: false, message: 'Invalid algorithm selection' };
  }

  return { isValid: true };
};

/**
 * Validate sensor selection (array of strings)
 */
export const validateSensorSelection = (sensors: string[]): ValidationResult => {
  if (!sensors || sensors.length === 0) {
    return { isValid: false, message: 'Please select at least one sensor' };
  }

  // Validate each sensor ID
  for (const sensor of sensors) {
    const sensorResult = validateChargerId(sensor); // Reuse charger ID validation
    if (!sensorResult.isValid) {
      return { isValid: false, message: `Invalid sensor ID: ${sensor}` };
    }
  }

  return { isValid: true };
};

/**
 * Validate numeric input with range
 */
export const validateNumeric = (
  value: number | string,
  min?: number,
  max?: number,
  fieldName = 'Value'
): ValidationResult => {
  const num = typeof value === 'string' ? parseFloat(value) : value;

  if (isNaN(num)) {
    return { isValid: false, message: `${fieldName} must be a number` };
  }

  if (min !== undefined && num < min) {
    return { isValid: false, message: `${fieldName} must be at least ${min}` };
  }

  if (max !== undefined && num > max) {
    return { isValid: false, message: `${fieldName} must be at most ${max}` };
  }

  return { isValid: true };
};

/**
 * Generic required field validation
 */
export const validateRequired = (value: unknown, fieldName = 'Field'): ValidationResult => {
  if (value === null || value === undefined || value === '') {
    return { isValid: false, message: `${fieldName} is required` };
  }

  return { isValid: true };
};

/**
 * Validate all form fields at once
 */
export const validateForm = <
  TFields extends Record<string, unknown>
>(
  fields: TFields,
  validators: Partial<{
    [K in keyof TFields]: (value: TFields[K]) => ValidationResult;
  }>
): Partial<Record<keyof TFields, ValidationResult>> => {
  const results: Partial<Record<keyof TFields, ValidationResult>> = {};

  for (const key of Object.keys(fields) as Array<keyof TFields>) {
    const validator = validators[key];
    if (validator) {
      results[key] = validator(fields[key]);
    }
  }

  return results;
};

/**
 * Check if all validation results are valid
 */
export const areAllValid = (results: Record<string, ValidationResult>): boolean => {
  return Object.values(results).every(result => result.isValid);
};
