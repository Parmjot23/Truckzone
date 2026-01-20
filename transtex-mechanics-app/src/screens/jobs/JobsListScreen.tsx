import * as React from 'react';
import { View, FlatList, RefreshControl } from 'react-native';
import { Text, List, ActivityIndicator, Searchbar, useTheme, Badge, Chip } from 'react-native-paper';
import { useQuery } from '@tanstack/react-query';
import { getJobs, Job } from '@/services/jobsService';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';

async function fetchJobs(search: string) {
  return getJobs({ search });
}

export function JobsListScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<RouteProp<Record<string, { filter?: string }>, string>>();
  const [search, setSearch] = React.useState('');
  const theme = useTheme();

  // Get filter from navigation params (from dashboard)
  const statusFilter = route.params?.filter;

  const { data, refetch, isFetching, isLoading } = useQuery({
    queryKey: ['jobs', search, statusFilter],
    queryFn: () => fetchJobs(search),
    refetchInterval: 30000,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  });

  // Filter jobs based on status if filter is provided
  const filteredJobs = React.useMemo(() => {
    if (!data) return [];

    if (!statusFilter || statusFilter === 'all') {
      return data;
    }

    // Map dashboard filter to job status
    const statusMap: Record<string, string> = {
      'pending': 'pending',
      'completed': 'completed',
    };

    const mappedStatus = statusMap[statusFilter] || statusFilter;
    return data.filter(job => job.status === mappedStatus);
  }, [data, statusFilter]);

  const getFilterTitle = () => {
    if (!statusFilter || statusFilter === 'all') return 'Assigned Work Orders';
    return `Work Orders - ${statusFilter.charAt(0).toUpperCase() + statusFilter.slice(1)}`;
  };

  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.background }}>
      <View style={{ padding: 16 }}>
        <Text variant="headlineSmall" style={{ marginBottom: 12 }}>{getFilterTitle()}</Text>
        <Searchbar placeholder="Search jobs" value={search} onChangeText={setSearch} style={{ marginBottom: 8 }} />
      </View>
      {isLoading ? (
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
          <ActivityIndicator />
        </View>
      ) : (
        <FlatList
          data={filteredJobs}
          keyExtractor={(item) => item.id}
          refreshControl={<RefreshControl refreshing={isFetching} onRefresh={refetch} />}
          renderItem={({ item }) => (
            <List.Item
              title={item.title}
              description={() => (
                <View>
                  <Text style={{ color: theme.colors.onSurfaceVariant }}>
                    {item.customer_name} • {item.address}
                  </Text>
                  {item.collaborators && item.collaborators.length > 0 && (
                    <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 4 }}>
                      {item.collaborators.map(collab => (
                        <Chip
                          key={`${item.id}-${collab.assignment_id}`}
                          compact
                          style={{ marginRight: 4, marginBottom: 4, backgroundColor: '#eef2ff' }}
                          textStyle={{ color: '#312e81', fontSize: 12 }}
                        >
                          {collab.name}{collab.submitted ? ' ✓' : ''}
                        </Chip>
                      ))}
                    </View>
                  )}
                </View>
              )}
              right={() => (
                (() => {
                  const s = (item.status || '').toLowerCase();
                  const bg = s === 'pending' ? '#ffeb3b' : s === 'completed' ? '#4caf50' : '#90caf9';
                  const color = s === 'pending' ? '#795548' : '#fff';
                  return (
                    <Badge style={{ alignSelf: 'center', marginRight: 12, backgroundColor: bg, color }} size={22}>
                      {item.status}
                    </Badge>
                  );
                })()
              )}
              onPress={() => navigation.navigate('JobDetail', { id: item.id })}
              style={{ backgroundColor: theme.colors.surface, marginHorizontal: 8, marginVertical: 4, borderRadius: 12 }}
            />
          )}
          ListEmptyComponent={
            <View style={{ padding: 32, alignItems: 'center' }}>
              <Text variant="bodyLarge" style={{ color: theme.colors.onSurfaceVariant }}>
                {statusFilter && statusFilter !== 'all' ? `No ${statusFilter} work orders found` : 'No work orders assigned'}
              </Text>
            </View>
          }
        />
      )}
    </View>
  );
}