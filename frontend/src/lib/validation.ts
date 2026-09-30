/**
 * Input validation utilities for security and data integrity
 */

import { VALIDATION_MESSAGES, AUTH_CONFIG } from './constants';

// Email validation regex
const EMAIL_REGEX = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

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

  if ([...password].length < AUTH_CONFIG.PASSWORD_MIN_LENGTH) {
    return { isValid: false, message: VALIDATION_MESSAGES.PASSWORD_TOO_SHORT };
  }

  if (new TextEncoder().encode(password).length > 72) {
    return { isValid: false, message: "Password must be no more than 72 UTF-8 bytes." };
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
 * Validate user ID (number)
 */
export const validateUserId = (userId: number | string): ValidationResult => {
  const id =
    typeof userId === 'string'
      ? /^\d+$/.test(userId.trim())
        ? Number(userId.trim())
        : NaN
      : userId;

  if (!Number.isInteger(id) || id <= 0) {
    return { isValid: false, message: 'Invalid user ID' };
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
  const num =
    typeof value === 'string'
      ? value.trim() === ''
        ? NaN
        : Number(value.trim())
      : value;

  if (!Number.isFinite(num)) {
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
