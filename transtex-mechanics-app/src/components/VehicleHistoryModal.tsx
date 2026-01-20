import * as React from 'react';
import { Modal, View, ScrollView, StyleSheet } from 'react-native';
import { ActivityIndicator, Button, Card, Divider, IconButton, Text, useTheme } from 'react-native-paper';
import { useQuery } from '@tanstack/react-query';
import { getVehicleHistory } from '@/services/vehiclesService';
import type { VehicleHistoryJob, VehicleHistoryPart } from '@/services/vehiclesService';

type VehicleHistoryModalProps = {
  visible: boolean;
  vehicleId?: string | number | null;
  vehicleLabel?: string;
  onDismiss: () => void;
};

function formatDate(value: string | null) {
  if (!value) {
    return 'Unknown date';
  }
  try {
    return new Date(value).toLocaleDateString();
  } catch (error) {
    return value;
  }
}

function renderJobEntry(entry: VehicleHistoryJob) {
  return (
    <Card key={entry.id} style={styles.entryCard}>
      <Card.Content>
        <View style={styles.entryHeader}>
          <View style={{ flex: 1 }}>
            <Text variant="titleSmall" style={styles.entryTitle}>
              {formatDate(entry.jobDate)}
            </Text>
            <Text variant="bodyMedium" style={styles.entryDescription}>
              {entry.description || 'No description provided'}
            </Text>
          </View>
        </View>
        {entry.notes ? (
          <View style={styles.notesContainer}>
            <Text variant="labelSmall" style={styles.metaLabel}>
              Notes
            </Text>
            <Text variant="bodySmall">{entry.notes}</Text>
          </View>
        ) : null}
      </Card.Content>
    </Card>
  );
}

function renderPartEntry(entry: VehicleHistoryPart) {
  return (
    <Card key={`part-${entry.id}`} style={styles.entryCard}>
      <Card.Content>
        <View style={styles.entryHeader}>
          <View style={{ flex: 1 }}>
            <Text variant="titleSmall" style={styles.entryTitle}>
              {formatDate(entry.jobDate)}
            </Text>
            <Text variant="bodyMedium" style={styles.entryDescription}>
              {entry.description || 'Part'}
            </Text>
          </View>
        </View>
        <Divider style={{ marginVertical: 8 }} />
        <View style={styles.entryMetaRow}>
          <View style={styles.metaColumn}>
            <Text variant="labelSmall" style={styles.metaLabel}>Quantity</Text>
            <Text variant="bodySmall">{entry.quantity ?? '—'}</Text>
          </View>
          {entry.sku ? (
            <View style={styles.metaColumn}>
              <Text variant="labelSmall" style={styles.metaLabel}>SKU</Text>
              <Text variant="bodySmall">{entry.sku}</Text>
            </View>
          ) : null}
        </View>
      </Card.Content>
    </Card>
  );
}

export function VehicleHistoryModal({ visible, vehicleId, vehicleLabel, onDismiss }: VehicleHistoryModalProps) {
  const theme = useTheme();
  const query = useQuery({
    queryKey: ['vehicle-history', vehicleId],
    queryFn: () => getVehicleHistory(vehicleId as string | number),
    enabled: visible && !!vehicleId,
    staleTime: 1000 * 60 * 5,
  });

  const { data, isLoading, isError, refetch, isFetching } = query;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onDismiss}>
      <View style={styles.overlay}>
        <Card style={[styles.container, { backgroundColor: theme.colors.surface }]}>
          <Card.Title
            title="Vehicle History"
            subtitle={vehicleLabel || undefined}
            right={(props) => <IconButton {...props} icon="close" onPress={onDismiss} />}
          />
          <Card.Content style={{ flexGrow: 1 }}>
            {isLoading ? (
              <View style={styles.centered}>
                <ActivityIndicator animating size="large" />
                <Text style={{ marginTop: 12 }}>Loading history…</Text>
              </View>
            ) : isError ? (
              <View style={styles.centered}>
                <Text variant="bodyMedium" style={{ marginBottom: 12 }}>
                  Unable to load vehicle history.
                </Text>
                <Button mode="contained" onPress={() => refetch()} loading={isFetching}>
                  Try again
                </Button>
              </View>
            ) : data && (data.jobs.length > 0 || data.parts.length > 0) ? (
              <ScrollView contentContainerStyle={{ paddingBottom: 16 }}>
                <View style={styles.summaryCard}>
                  <View style={styles.summaryItem}>
                    <Text variant="labelSmall" style={styles.summaryLabel}>Job Entries</Text>
                    <Text variant="titleLarge" style={styles.summaryValue}>{data.jobs.length}</Text>
                  </View>
                  <View style={styles.summaryItem}>
                    <Text variant="labelSmall" style={styles.summaryLabel}>Parts Used</Text>
                    <Text variant="titleLarge" style={styles.summaryValue}>{data.parts.length}</Text>
                  </View>
                </View>

                {data.jobs.length > 0 ? (
                  <View style={styles.section}>
                    <Text variant="titleMedium" style={styles.sectionTitle}>Jobs</Text>
                    {data.jobs.map(renderJobEntry)}
                  </View>
                ) : null}

                {data.parts.length > 0 ? (
                  <View style={styles.section}>
                    <Text variant="titleMedium" style={styles.sectionTitle}>Parts Used</Text>
                    {data.parts.map(renderPartEntry)}
                  </View>
                ) : null}
              </ScrollView>
            ) : (
              <View style={styles.centered}>
                <Text variant="bodyMedium">No history recorded for this vehicle yet.</Text>
              </View>
            )}
          </Card.Content>
          <Card.Actions style={{ justifyContent: 'space-between' }}>
            <Button onPress={onDismiss}>Close</Button>
            <Button mode="outlined" onPress={() => refetch()} disabled={isFetching} loading={isFetching}>
              Refresh
            </Button>
          </Card.Actions>
        </Card>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'center',
    padding: 16,
  },
  container: {
    maxHeight: '90%',
  },
  centered: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 24,
  },
  summaryCard: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: '#eef2ff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  summaryItem: {
    flex: 1,
  },
  summaryLabel: {
    color: '#475569',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  summaryValue: {
    fontWeight: 'bold',
    color: '#1f2937',
  },
  entryCard: {
    marginBottom: 12,
    borderRadius: 12,
    elevation: 0,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#e2e8f0',
  },
  entryHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  entryTitle: {
    fontWeight: 'bold',
    color: '#1e293b',
  },
  entryDescription: {
    color: '#475569',
    marginTop: 4,
  },
  entryMetaRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  metaColumn: {
    flex: 1,
    marginRight: 12,
  },
  metaLabel: {
    color: '#64748b',
    textTransform: 'uppercase',
    fontSize: 11,
    marginBottom: 2,
  },
  notesContainer: {
    marginTop: 12,
    padding: 12,
    borderRadius: 8,
    backgroundColor: '#f8fafc',
  },
  section: {
    marginBottom: 16,
  },
  sectionTitle: {
    marginBottom: 8,
    fontWeight: 'bold',
    color: '#1e293b',
  },
});

export default VehicleHistoryModal;
