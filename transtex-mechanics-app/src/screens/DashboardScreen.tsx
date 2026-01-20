import * as React from 'react';
import { View, ScrollView } from 'react-native';
import {
  Text,
  Card,
  Button,
  useTheme,
  ActivityIndicator,
  Badge,
  Divider,
  TouchableRipple,
} from 'react-native-paper';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/services/apiClient';
import { useNavigation } from '@react-navigation/native';
import { MaterialIcons } from '@expo/vector-icons';

type Summary = {
  stats: {
    total: number;
    in_progress: number;
    completed: number;
    pending: number;
    low_stock: number;
  };
  recent: { id: number; title: string; customer: string; status: string; date_assigned: string | null }[];
  mechanic: { name: string };
};

export function DashboardScreen() {
  const theme = useTheme();
  const navigation = useNavigation<any>();

  const { data, isLoading, refetch, isFetching, error } = useQuery<Summary>({
    queryKey: ['summary'],
    queryFn: async () => {
      console.log('Fetching mechanic summary...');
      try {
        const response = await apiClient.get('/mechanic/summary/');
        console.log('Summary response:', response);
        return response.data;
      } catch (error) {
        console.error('Summary error:', error);
        throw error;
      }
    },
    refetchInterval: 30000,
  });

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator />
      </View>
    );
  }

  if (error) {
    console.error('Dashboard error:', error);

    // Check for specific "not_a_mechanic" error
    const axiosError = error as { response?: { status?: number; data?: { error?: string } } };
    const isNotMechanicError = axiosError?.response?.status === 403 &&
      axiosError?.response?.data?.error === 'not_a_mechanic';

    if (isNotMechanicError) {
      return (
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <MaterialIcons name="engineering" size={64} color={theme.colors.primary} style={{ marginBottom: 16 }} />
          <Text variant="headlineSmall" style={{ marginBottom: 16, textAlign: 'center' }}>Access Restricted</Text>
          <Text variant="bodyLarge" style={{ marginBottom: 20, textAlign: 'center', color: theme.colors.onSurfaceVariant }}>
            Your account is not configured as a mechanic. Please contact a staff member to grant mechanic access.
          </Text>
          <Button mode="contained" onPress={() => refetch()}>
            Retry
          </Button>
        </View>
      );
    }

    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 20 }}>
        <Text variant="headlineSmall" style={{ marginBottom: 16, textAlign: 'center' }}>Connection Error</Text>
        <Text variant="bodyLarge" style={{ marginBottom: 20, textAlign: 'center', color: theme.colors.onSurfaceVariant }}>
          Unable to connect to the server. Please check your internet connection and try again.
        </Text>
        <Button mode="contained" onPress={() => refetch()}>
          Retry
        </Button>
      </View>
    );
  }

  const recentAssignments = React.useMemo(() => (data?.recent || []).slice(0, 5), [data?.recent]);

  return (
    <ScrollView style={{ flex: 1, backgroundColor: theme.colors.background }} contentContainerStyle={{ padding: 16 }}>
      <Card style={{ backgroundColor: theme.colors.secondary, marginBottom: 16 }}>
        <Card.Content>
          <Text variant="headlineSmall" style={{ color: '#fff' }}>Welcome{data?.mechanic?.name ? `, ${data.mechanic.name}` : ''}</Text>
          <Text style={{ color: '#e5e7eb' }}>Quick overview of your workload and stock.</Text>
          <View style={{ flexDirection: 'row', marginTop: 12, gap: 8 }}>
            <Button mode="contained" onPress={() => navigation.navigate('Jobs')} style={{ marginRight: 8 }}>View Jobs</Button>
          </View>
        </Card.Content>
      </Card>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
        <Card
          style={{
            flexBasis: '48%',
            flexGrow: 1,
            backgroundColor: '#e3f2fd',
            borderLeftWidth: 4,
            borderLeftColor: '#2196f3'
          }}
          onPress={() => navigation.navigate('Jobs', { filter: 'all' })}
        >
          <Card.Content style={{ alignItems: 'center' }}>
            <MaterialIcons name="assignment" size={32} color="#2196f3" style={{ marginBottom: 8 }} />
            <Text style={{ color: '#1565c0', fontWeight: 'bold' }}>Total Assigned</Text>
            <Text variant="headlineMedium" style={{ color: '#1565c0' }}>{data?.stats?.total ?? 0}</Text>
          </Card.Content>
        </Card>

        <Card
          style={{
            flexBasis: '48%',
            flexGrow: 1,
            backgroundColor: '#fff3e0',
            borderLeftWidth: 4,
            borderLeftColor: '#ff9800'
          }}
          onPress={() => navigation.navigate('Jobs', { filter: 'pending' })}
        >
          <Card.Content style={{ alignItems: 'center' }}>
            <MaterialIcons name="schedule" size={32} color="#ff9800" style={{ marginBottom: 8 }} />
            <Text style={{ color: '#e65100', fontWeight: 'bold' }}>Pending</Text>
            <Text variant="headlineMedium" style={{ color: '#e65100' }}>{data?.stats?.pending ?? 0}</Text>
          </Card.Content>
        </Card>

        <Card
          style={{
            flexBasis: '48%',
            flexGrow: 1,
            backgroundColor: '#e8f5e9',
            borderLeftWidth: 4,
            borderLeftColor: '#4caf50'
          }}
          onPress={() => navigation.navigate('Jobs', { filter: 'completed' })}
        >
          <Card.Content style={{ alignItems: 'center' }}>
            <MaterialIcons name="check-circle" size={32} color="#4caf50" style={{ marginBottom: 8 }} />
            <Text style={{ color: '#2e7d32', fontWeight: 'bold' }}>Completed</Text>
            <Text variant="headlineMedium" style={{ color: '#2e7d32' }}>{data?.stats?.completed ?? 0}</Text>
          </Card.Content>
        </Card>

        {/* Low Stock card removed as requested */}
      </View>

      <Card style={{ marginTop: 16 }}>
        <Card.Title
          title="Recent Work Orders"
          titleVariant="titleMedium"
          subtitle="Your latest assigned jobs"
        />
        <Divider style={{ marginHorizontal: 16 }} />
        <Card.Content style={{ paddingVertical: 12 }}>
          {recentAssignments.length === 0 ? (
            <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
              No recent activity to display.
            </Text>
          ) : (
            recentAssignments.map((r, index) => {
              const status = (r.status || '').toLowerCase();
              const badgeBackground = status === 'pending'
                ? '#ffeb3b'
                : status === 'completed'
                ? '#4caf50'
                : '#90caf9';
              const badgeColor = status === 'pending' ? '#795548' : '#fff';
              const showDivider = index !== recentAssignments.length - 1;

              return (
                <View key={r.id}>
                  <TouchableRipple
                    onPress={() => navigation.navigate('JobDetail', { id: String(r.id) })}
                    style={{
                      borderRadius: 12,
                      paddingVertical: 4,
                      marginBottom: showDivider ? 12 : 0,
                    }}
                    rippleColor={theme.colors.secondaryContainer}
                  >
                    <View style={{ flex: 1, paddingHorizontal: 4 }}>
                      <Text variant="titleMedium" style={{ marginBottom: 4 }}>
                        {r.title}
                      </Text>
                      <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                        {r.customer}
                      </Text>
                      <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 8 }}>
                        <Badge style={{ marginRight: 8, backgroundColor: badgeBackground, color: badgeColor }}>
                          {r.status}
                        </Badge>
                        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                          {r.date_assigned ? new Date(r.date_assigned).toLocaleString() : ''}
                        </Text>
                      </View>
                    </View>
                  </TouchableRipple>
                  {showDivider ? <Divider style={{ marginBottom: 12 }} /> : null}
                </View>
              );
            })
          )}
        </Card.Content>
      </Card>
    </ScrollView>
  );
}


