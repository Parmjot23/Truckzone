import axios from 'axios';
import { getApiBaseUrl } from '@/config/environment';

const API_BASE_URL = getApiBaseUrl();
// Debug: log which API base URL the app is using at runtime
if (__DEV__) {
  // eslint-disable-next-line no-console
  console.log('API base URL:', API_BASE_URL);
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
});

let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

apiClient.interceptors.request.use((config) => {
  if (authToken) {
    const headers: Record<string, string> = { ...(config.headers as any) };
    headers['Authorization'] = `Token ${authToken}`;
    config.headers = headers as any;
  }
  return config;
});

apiClient.interceptors.response.use(
  (r) => r,
  async (error) => {
    console.log('API Error:', error?.response?.status, error?.response?.data, error?.message);
    // Basic error normalization
    const status = error?.response?.status;
    if (status === 401) {
      // Optionally, handle refresh flow here
    }
    return Promise.reject(error);
  }
);