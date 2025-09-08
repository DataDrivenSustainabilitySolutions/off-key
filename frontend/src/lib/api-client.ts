/**
 * Centralized API client with interceptors and error handling
 */

import axios, { AxiosInstance, AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { API_CONFIG, DEFAULT_REQUEST_CONFIG } from './api-config';

// Types for API responses
export interface ApiError {
  detail: string;
  status: number;
}

export interface ApiResponse<T = any> {
  data: T;
  status: number;
  message?: string;
}

// Token management
const TOKEN_KEY = 'auth_token';
const STORAGE_TYPE_KEY = 'token_storage_type';

export const tokenManager = {
  getToken(): string | null {
    const storageType = localStorage.getItem(STORAGE_TYPE_KEY);
    if (storageType === 'localStorage') {
      return localStorage.getItem(TOKEN_KEY);
    }
    return sessionStorage.getItem(TOKEN_KEY);
  },

  setToken(token: string, rememberMe: boolean = false): void {
    // Clear both storages first
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    
    if (rememberMe) {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(STORAGE_TYPE_KEY, 'localStorage');
    } else {
      sessionStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(STORAGE_TYPE_KEY, 'sessionStorage');
    }
  },

  removeToken(): void {
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(STORAGE_TYPE_KEY);
  },

  isTokenExpired(token: string): boolean {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      const currentTime = Date.now() / 1000;
      return payload.exp < currentTime;
    } catch {
      return true; // If we can't parse it, consider it expired
    }
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
    (config: InternalAxiosRequestConfig) => {
      const token = tokenManager.getToken();
      
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
    (error: AxiosError<ApiError>) => {
      // Handle 401 Unauthorized
      if (error.response?.status === 401) {
        tokenManager.removeToken();
        // Redirect to login page
        window.location.href = '/login';
        return Promise.reject(new Error('Session expired. Please login again.'));
      }

      // Handle other common errors
      if (error.response?.data?.detail) {
        return Promise.reject(new Error(error.response.data.detail));
      }

      // Network errors
      if (!error.response) {
        return Promise.reject(new Error('Network error. Please check your connection.'));
      }

      // Generic error
      return Promise.reject(new Error(`Request failed with status ${error.response.status}`));
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
  async get<T>(endpoint: string, params?: Record<string, any>): Promise<T> {
    const response = await apiClient.get<T>(endpoint, { params });
    return response.data;
  },

  /**
   * Generic POST request
   */
  async post<T>(endpoint: string, data?: any): Promise<T> {
    const response = await apiClient.post<T>(endpoint, data);
    return response.data;
  },

  /**
   * Generic PUT request
   */
  async put<T>(endpoint: string, data?: any): Promise<T> {
    const response = await apiClient.put<T>(endpoint, data);
    return response.data;
  },

  /**
   * Generic DELETE request
   */
  async delete<T>(endpoint: string, data?: any): Promise<T> {
    const config = data ? { data } : undefined;
    const response = await apiClient.delete<T>(endpoint, config);
    return response.data;
  }
};