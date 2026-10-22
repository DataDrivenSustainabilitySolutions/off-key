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
