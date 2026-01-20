import * as React from 'react';
import * as SecureStore from 'expo-secure-store';
import { View, ActivityIndicator } from 'react-native';
import { apiClient, setAuthToken } from '@/services/apiClient';
import { getApiBaseUrl } from '@/config/environment';

export type AuthContextValue = {
  isAuthenticated: boolean;
  accessToken: string | null;
  login: (identifier: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = React.createContext<AuthContextValue | undefined>(undefined);

const ACCESS_TOKEN_KEY = 'ACCESS_TOKEN_V2';
const BASE_URL_KEY = 'API_BASE_URL_V1';

const getCurrentApiBaseUrl = getApiBaseUrl;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [accessToken, setAccessToken] = React.useState<string | null>(null);
  const [bootstrapped, setBootstrapped] = React.useState(false);

  React.useEffect(() => {
    (async () => {
      try {
        const [token, storedBaseUrl] = await Promise.all([
          SecureStore.getItemAsync(ACCESS_TOKEN_KEY),
          SecureStore.getItemAsync(BASE_URL_KEY),
        ]);
        const currentBaseUrl = getCurrentApiBaseUrl();

        // If API base URL changed (e.g., pointing to live backend), clear stale token
        if (storedBaseUrl && storedBaseUrl !== currentBaseUrl) {
          await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
          await SecureStore.setItemAsync(BASE_URL_KEY, currentBaseUrl);
          setAccessToken(null);
          setAuthToken(null);
        } else {
          if (token) {
            setAccessToken(token);
            setAuthToken(token);
          }
          if (!storedBaseUrl) {
            await SecureStore.setItemAsync(BASE_URL_KEY, currentBaseUrl);
          }
        }
      } finally {
        setBootstrapped(true);
      }
    })();
    // Attach a 401 interceptor to reset auth state on invalid/expired token
    const interceptorId = apiClient.interceptors.response.use(
      (r) => r,
      async (error) => {
        const status = error?.response?.status;
        if (status === 401) {
          try { await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY); } catch { }
          setAccessToken(null);
          setAuthToken(null);
        }
        return Promise.reject(error);
      }
    );
    return () => {
      apiClient.interceptors.response.eject(interceptorId);
    };
  }, []);

  const login = React.useCallback(async (identifier: string, password: string) => {
    const { data } = await apiClient.post('/auth/login/', { email: identifier, username: identifier, password });
    const token: string = data?.token || data?.access || data?.access_token;
    if (!token) throw new Error('Invalid login response');
    await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, token);
    await SecureStore.setItemAsync(BASE_URL_KEY, getCurrentApiBaseUrl());
    setAccessToken(token);
    setAuthToken(token);
  }, []);

  const logout = React.useCallback(async () => {
    try {
      await apiClient.post('/auth/logout/').catch(() => { });
    } finally {
      await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
      setAccessToken(null);
      setAuthToken(null);
    }
  }, []);

  const value: AuthContextValue = React.useMemo(() => ({
    isAuthenticated: Boolean(accessToken),
    accessToken,
    login,
    logout,
  }), [accessToken, login, logout]);

  if (!bootstrapped) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#fff' }}>
        <ActivityIndicator size="large" color="#2f63d1" />
      </View>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}