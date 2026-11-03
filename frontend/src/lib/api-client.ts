/**
 * Centralized API client with interceptors and error handling
 */

import axios, {
  AxiosInstance,
  AxiosError,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios';
import { refreshSession, tokenManager } from '@/auth/session';
import { getUserIdFromToken } from '@/auth/token';
import { API_CONFIG, DEFAULT_REQUEST_CONFIG } from './api-config';


export interface ApiIssue {
  loc: (string | number)[];
  msg: string;
  type?: string;
}

interface ApiError {
  detail: string | ApiIssue[];
  status: number;
}

export interface ApiRequestOptions {
  params?: Record<string, unknown>;
  signal?: AbortSignal;
  timeout?: number;
  /** Optional views can show a sign-in state instead of navigating away. */
  redirectOnUnauthorized?: boolean;
}

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly issues: readonly ApiIssue[] = [],
    /** The server's correlation ID for this request; its logs carry the same ID. */
    readonly reference?: string,
  ) {
    super(message);
    this.name = 'ApiRequestError';
  }
}

// The gateway echoes one ID per request (LOG_CORRELATION_HEADER, by default
// X-Correlation-ID) and logs it on every line it writes for that request.
const CORRELATION_HEADER = 'x-correlation-id';
const REFERENCE_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;

const responseReference = (error: AxiosError): string | undefined => {
  const value = error.response?.headers?.[CORRELATION_HEADER];
  return typeof value === 'string' && REFERENCE_PATTERN.test(value) ? value : undefined;
};

/** A server failure names its reference, so a report leads to its log lines. */
const serverError = (message: string, status: number, issues: readonly ApiIssue[], reference?: string) =>
  new ApiRequestError(
    status >= 500 && reference ? `${message} (reference ${reference})` : message,
    status,
    issues,
    reference,
  );

const assertSameMember = (previousToken: string | null, nextToken: string | null) => {
  const previousId = previousToken ? getUserIdFromToken(previousToken) : null;
  if (previousId && nextToken && getUserIdFromToken(nextToken) !== previousId) {
    throw new ApiRequestError('The account changed. Please try the request again.', 401);
  }
};

// Create axios instance
const createApiClient = (): AxiosInstance => {
  const client = axios.create({
    baseURL: API_CONFIG.BASE_URL,
    ...DEFAULT_REQUEST_CONFIG,
  });

  // Request interceptor to add auth token
  client.interceptors.request.use(
    async (config: InternalAxiosRequestConfig) => {
      let token = tokenManager.getToken();
      const previousToken = token;
      // Remembered tokens live in memory, so a fresh tab restores one first.
      if ((!token || tokenManager.isTokenExpired(token)) && tokenManager.isRemembered()) {
        token = await refreshSession();
      }
      assertSameMember(previousToken, token);

      if (token && !tokenManager.isTokenExpired(token)) {
        config.headers.Authorization = `Bearer ${token}`;
      }

      return config;
    },
    (error) => Promise.reject(error)
  );

  // Response interceptor for error handling
  client.interceptors.response.use(
    (response: AxiosResponse) => response,
    async (error: AxiosError<ApiError>) => {
      if (axios.isCancel(error)) return Promise.reject(error);
      // Request-interceptor failures (including temporary renewal outages) must
      // keep their original status and leave the saved session intact.
      if (!axios.isAxiosError(error)) return Promise.reject(error);
      // Handle 401 Unauthorized
      if (error.response?.status === 401) {
        const options = error.config as (InternalAxiosRequestConfig & ApiRequestOptions & { sessionRetried?: boolean }) | undefined;
        if (options && !options.sessionRetried && tokenManager.isRemembered()) {
          options.sessionRetried = true;
          // A concurrent request may already have replaced this rejected token.
          const currentToken = tokenManager.getToken();
          const rejectedToken = options.headers.Authorization;
          const token = currentToken && rejectedToken !== `Bearer ${currentToken}` && !tokenManager.isTokenExpired(currentToken)
            ? currentToken : await refreshSession();
          if (token) {
            const authorization = options.headers.Authorization;
            const previousToken = typeof authorization === 'string' && authorization.startsWith('Bearer ')
              ? authorization.slice(7) : null;
            assertSameMember(previousToken, token);
            options.headers.Authorization = `Bearer ${token}`;
            return client.request(options);
          }
        }
        const activeToken = tokenManager.getToken();
        if (activeToken && !tokenManager.isTokenExpired(activeToken) && options?.headers.Authorization !== `Bearer ${activeToken}`) {
          return Promise.reject(new ApiRequestError('The previous session has ended.', 401));
        }
        tokenManager.removeToken();
        // Redirect to login page
        if (options?.redirectOnUnauthorized !== false) window.location.href = '/login';
        return Promise.reject(new ApiRequestError('Session expired. Please login again.', 401));
      }

      // Handle other common errors
      if (error.response?.data?.detail) {
        const detail = error.response.data.detail;
        const message = Array.isArray(detail)
          ? detail.map(issue => `${issue.loc.filter(part => part !== 'body').join('.')}: ${issue.msg}`).join('; ')
          : detail;
        return Promise.reject(serverError(message, error.response.status, Array.isArray(detail) ? detail : [], responseReference(error)));
      }

      // Network errors
      if (!error.response) {
        return Promise.reject(new ApiRequestError('Network error. Please check your connection.'));
      }

      // Generic error
      return Promise.reject(serverError(`Request failed with status ${error.response.status}`, error.response.status, [], responseReference(error)));
    }
  );

  return client;
};

// Export singleton instance
export const apiClient = createApiClient();

// Utility functions for common operations
export const apiUtils = {
  /**
   * Generic GET request
   */
  async get<T>(endpoint: string, options?: ApiRequestOptions): Promise<T> {
    const response = await apiClient.get<T>(endpoint, options);
    return response.data;
  },

  /**
   * Generic POST request
   */
  async post<T>(
    endpoint: string,
    data?: unknown,
    options?: ApiRequestOptions
  ): Promise<T> {
    const response = await apiClient.post<T>(endpoint, data, options);
    return response.data;
  },

  /**
   * Generic PUT request
   */
  async put<T>(
    endpoint: string,
    data?: unknown,
    options?: ApiRequestOptions
  ): Promise<T> {
    const response = await apiClient.put<T>(endpoint, data, options);
    return response.data;
  },

  async patch<T>(
    endpoint: string,
    data?: unknown,
    options?: ApiRequestOptions
  ): Promise<T> {
    const response = await apiClient.patch<T>(endpoint, data, options);
    return response.data;
  },

  /**
   * Generic DELETE request
   */
  async delete<T>(
    endpoint: string,
    data?: unknown,
    options?: ApiRequestOptions
  ): Promise<T> {
    const config = data === undefined ? options : { ...options, data };
    const response = await apiClient.delete<T>(endpoint, config);
    return response.data;
  }
};
