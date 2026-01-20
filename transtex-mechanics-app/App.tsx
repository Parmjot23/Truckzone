import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { persistQueryClient } from '@tanstack/react-query-persist-client';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { focusManager, onlineManager } from '@tanstack/react-query';
import * as Network from 'expo-network';
import Constants from 'expo-constants';
import * as React from 'react';
import { NavigationContainer, DefaultTheme, Theme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Provider as PaperProvider, MD3LightTheme, configureFonts } from 'react-native-paper';
import { StatusBar } from 'expo-status-bar';
import { Platform, AppState, AppStateStatus } from 'react-native';
import { MaterialIcons } from '@expo/vector-icons';

// Screens
import { LoginScreen } from './src/screens/auth/LoginScreen';
import { JobsListScreen } from './src/screens/jobs/JobsListScreen';
import { JobDetailScreen } from './src/screens/jobs/JobDetailScreen';
import { SettingsScreen } from './src/screens/settings/SettingsScreen';
import { DashboardScreen } from './src/screens/DashboardScreen';
import { PhotoCaptureScreen } from './src/screens/media/PhotoCaptureScreen';
import { SignatureScreen } from './src/screens/signature/SignatureScreen';
import { PmChecklistScreen } from './src/screens/jobs/PmChecklistScreen';

// Providers and utils
import { AuthProvider, useAuth } from './src/state/auth/AuthContext';
import { useOfflineQueueProcessor } from './src/state/offline/UploadQueue';
import { registerBackgroundSync } from './src/services/pollingService';
import { ErrorBoundary } from './src/components/ErrorBoundary';

const queryClient = new QueryClient();

const persister = createAsyncStoragePersister({ storage: AsyncStorage });

persistQueryClient({
  queryClient,
  persister,
  maxAge: 1000 * 60 * 60 * 24,
});

onlineManager.setEventListener((setOnline) => {
  const subscription = Network.addNetworkStateListener((state) => {
    setOnline(Boolean(state.isConnected));
  });
  return () => subscription.remove();
});

function onAppStateChange(status: AppStateStatus) {
  if (Platform.OS !== 'web' && status === 'active') {
    focusManager.setFocused(true);
  }
}

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

function AppTabs() {
  const insets = useSafeAreaInsets();
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        tabBarIcon: ({ focused, color, size }) => {
          let iconName: keyof typeof MaterialIcons.glyphMap;

          if (route.name === 'Dashboard') {
            iconName = 'dashboard';
          } else if (route.name === 'Jobs') {
            iconName = 'assignment';
          } else if (route.name === 'Settings') {
            iconName = 'settings';
          } else {
            iconName = 'help';
          }

          return <MaterialIcons name={iconName} size={size} color={color} />;
        },
        tabBarActiveTintColor: '#2f63d1',
        tabBarInactiveTintColor: 'gray',
        tabBarStyle: {
          backgroundColor: '#ffffff',
          borderTopColor: '#e5e7eb',
          borderTopWidth: 1,
          paddingTop: 6,
          paddingBottom: Math.max(insets.bottom, 10),
          height: 60 + insets.bottom,
        },
        tabBarHideOnKeyboard: true,
        headerStyle: {
          backgroundColor: '#2f63d1',
        },
        headerTintColor: '#fff',
        headerTitleStyle: {
          fontWeight: 'bold',
        },
      })}
    >
      <Tab.Screen
        name="Dashboard"
        component={DashboardScreen}
        options={{
          title: 'Dashboard',
          headerTitle: 'Mechanic Dashboard',
        }}
      />
      <Tab.Screen
        name="Jobs"
        component={JobsListScreen}
        options={{
          title: 'Work Orders',
          headerTitle: 'My Work Orders',
        }}
      />
      <Tab.Screen
        name="Settings"
        component={SettingsScreen}
        options={{
          title: 'Settings',
          headerTitle: 'Settings',
        }}
      />
    </Tab.Navigator>
  );
}

function RootNavigator() {
  const { isAuthenticated } = useAuth();
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      {isAuthenticated ? (
        <>
          <Stack.Screen name="Tabs" component={AppTabs} />
          <Stack.Screen
            name="JobDetail"
            component={JobDetailScreen}
            options={{
              headerShown: true,
              title: 'Work Order Details',
              headerStyle: { backgroundColor: '#2f63d1' },
              headerTintColor: '#fff',
              headerTitleStyle: { fontWeight: 'bold' },
            }}
          />
          <Stack.Screen
            name="PhotoCapture"
            component={PhotoCaptureScreen as React.ComponentType<any>}
            options={{
              headerShown: true,
              title: 'Capture Photo',
              headerStyle: { backgroundColor: '#2f63d1' },
              headerTintColor: '#fff',
              headerTitleStyle: { fontWeight: 'bold' },
            }}
          />
          <Stack.Screen
            name="Signature"
            component={SignatureScreen}
            options={{
              headerShown: true,
              title: 'Capture Signature',
              headerStyle: { backgroundColor: '#2f63d1' },
              headerTintColor: '#fff',
              headerTitleStyle: { fontWeight: 'bold' },
            }}
          />
          <Stack.Screen
            name="PmChecklist"
            component={PmChecklistScreen}
            options={{
              headerShown: true,
              title: 'PM Inspection Checklist',
              headerStyle: { backgroundColor: '#2f63d1' },
              headerTintColor: '#fff',
              headerTitleStyle: { fontWeight: 'bold' },
            }}
          />
        </>
      ) : (
        <Stack.Screen name="Login" component={LoginScreen} />
      )}
    </Stack.Navigator>
  );
}

export default function App() {
  React.useEffect(() => {
    const sub = AppState.addEventListener('change', onAppStateChange);
    registerBackgroundSync().catch(() => { });
    return () => sub.remove();
  }, []);

  // Theme inspired by mechanic dashboard (blue gradient header, white cards, subtle shadows)
  const theme = {
    ...MD3LightTheme,
    colors: {
      ...MD3LightTheme.colors,
      primary: '#2f63d1',
      secondary: '#2a5298',
      background: '#f5f7fb',
      surface: '#ffffff',
      onSurfaceVariant: '#6b7280',
      error: '#d32f2f',
    },
  } as typeof MD3LightTheme;

  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <PaperProvider theme={theme}>
          <QueryClientProvider client={queryClient}>
            <AuthProvider>
              <NavigationContainer theme={DefaultTheme as Theme}>
                <RootNavigator />
              </NavigationContainer>
              <StatusBar style="dark" />
            </AuthProvider>
            <QueueProcessor />
          </QueryClientProvider>
        </PaperProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}

function QueueProcessor() {
  useOfflineQueueProcessor();
  return null;
}
