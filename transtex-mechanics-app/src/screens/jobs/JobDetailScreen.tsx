import * as React from 'react';
import { View, ScrollView, Alert, Image, TouchableOpacity, Modal } from 'react-native';
import { Text, Button, Divider, List, useTheme, Badge, TextInput, Card, Chip, ActivityIndicator, IconButton } from 'react-native-paper';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getJob, setJobCauseCorrection, controlJobTimer, pauseJobWithReason, arrivedAtJobsite, mechanicComplete } from '@/services/jobsService';
import { RouteProp, useRoute } from '@react-navigation/native';
import { useNavigation } from '@react-navigation/native';
import { apiClient } from '@/services/apiClient';
import { Picker } from '@react-native-picker/picker';
import { MaterialIcons } from '@expo/vector-icons';
import VehicleHistoryModal from '@/components/VehicleHistoryModal';

async function fetchJob(id: string) {
  return getJob(id);
}

const getStatusColor = (status: string) => {
	switch (status) {
		case 'in_progress':
			return '#22a06b'; // green
		case 'paused':
			return '#6c757d'; // gray
		case 'travel':
			return '#2f63d1'; // blue
		case 'marked_complete':
			return '#8e44ad'; // purple
		case 'not_started':
			return '#6c757d';
		case 'completed':
			return '#22a06b'; // green
		default:
			return '#6c757d'; // gray
	}
};

export function JobDetailScreen() {
	const theme = useTheme();
  const route = useRoute<RouteProp<Record<string, { id: string }>, string>>();
  const queryClient = useQueryClient();
  const navigation = useNavigation<any>();
  const id = (route.params as any)?.id as string;

  const { data, isLoading, error } = useQuery({
    queryKey: ['job', id],
    queryFn: () => fetchJob(id),
    retry: 3,
    retryDelay: 1000,
    enabled: !!id // Only run if we have an ID
  });

  // Debug logging
  React.useEffect(() => {
    console.log('JobDetailScreen - ID:', id);
    console.log('JobDetailScreen - Loading:', isLoading);
    console.log('JobDetailScreen - Error:', error);
    console.log('JobDetailScreen - Data:', data);
  }, [id, isLoading, error, data]);

	const [cause, setCause] = React.useState('');
	const [correction, setCorrection] = React.useState('');
	const [statusLocal, setStatusLocal] = React.useState<string>('');
	const [vehicleId, setVehicleId] = React.useState<string | null>(null);
	const [vehicles, setVehicles] = React.useState<{ id: string; label: string }[]>([]);
	const [showAddVehicle, setShowAddVehicle] = React.useState(false);
	const [newVehicle, setNewVehicle] = React.useState({ vin_number: '', unit_number: '', make_model: '' });
	const [vehicleVin, setVehicleVin] = React.useState('');
	const [vehicleMileage, setVehicleMileage] = React.useState('');
	const [vehicleUnitNo, setVehicleUnitNo] = React.useState('');
	const [vehicleMakeModel, setVehicleMakeModel] = React.useState('');
  const [products, setProducts] = React.useState<any[]>([]);
  const [productSearch, setProductSearch] = React.useState('');
  const [selectedProducts, setSelectedProducts] = React.useState<{ id: string; qty: number; name: string }[]>([]);
  const [assignedVehicle, setAssignedVehicle] = React.useState<{ id: string; label: string } | null>(null);
  const [previewImage, setPreviewImage] = React.useState<string | null>(null);
  const collaborators = ((data as any)?.collaborators as any[]) || [];
  const [pauseModalVisible, setPauseModalVisible] = React.useState(false);
  const [selectedPauseKey, setSelectedPauseKey] = React.useState<'travel' | 'lunch' | 'other_job' | 'other'>('travel');
  const [customPauseText, setCustomPauseText] = React.useState('');
  const [vehicleHistoryVisible, setVehicleHistoryVisible] = React.useState(false);

  // Hook-safe derived values declared before any early returns to keep hook order stable
  const isReadOnly = Boolean((data as any)?.is_read_only || (data as any)?.status === 'completed');
  // Use numeric timestamps instead of Date objects to avoid identity changes each render
  const startedAtMs = (data as any)?.mechanic_started_at ? Date.parse((data as any).mechanic_started_at) : null;

  // Debug logging for start button visibility
  React.useEffect(() => {
    const mechanicStatus = (data as any)?.mechanic_status;
    const shouldShowStartButton = !startedAtMs && !isReadOnly;
    console.log('🔍 Start Button Debug:', {
      mechanicStatus,
      startedAt: startedAtMs ? new Date(startedAtMs).toISOString() : undefined,
      isReadOnly,
      shouldShowStartButton,
      jobId: id
    });
  }, [startedAtMs, isReadOnly, data, id]);

  // Debug logging for timer status (trimmed to avoid heavy deps that can cause rerenders)
  React.useEffect(() => {
    if (!startedAtMs) return;
    const currentStatus = statusLocal || (data as any)?.mechanic_status;
    console.log('⏱️ Timer Status:', { status: currentStatus, startedAtMs });
  }, [startedAtMs, statusLocal, data]);

  const endedAtMs = (data as any)?.mechanic_ended_at ? Date.parse((data as any).mechanic_ended_at) : null;
  const pausedSeconds = Number((data as any)?.mechanic_total_paused_seconds || 0);
  const [nowTick, setNowTick] = React.useState<number>(() => Date.now());
  const [lastActiveTime, setLastActiveTime] = React.useState<number>(() => Date.now());

  React.useEffect(() => {
    if (!startedAtMs || isReadOnly) return;

    // Only update timer if job is actively running (not paused, but travel counts as active time)
    const currentStatus = statusLocal || (data as any)?.mechanic_status;
    const isActive = currentStatus === 'in_progress' || currentStatus === 'travel';

    if (!isActive) return;

    const t = setInterval(() => {
      setNowTick(Date.now());
      setLastActiveTime(Date.now());
    }, 1000);
    return () => clearInterval(t);
  }, [startedAtMs, isReadOnly, statusLocal, data]);
  // Calculate total time including paused periods
  const totalTimeSeconds = React.useMemo(() => {
    if (!startedAtMs) return 0;
    const currentStatus = statusLocal || (data as any)?.mechanic_status;
    const isActive = currentStatus === 'in_progress' || currentStatus === 'travel';
    const endTime = endedAtMs ?? (isActive ? nowTick : lastActiveTime);
    return Math.max(0, Math.floor((endTime - startedAtMs) / 1000));
  }, [startedAtMs, endedAtMs, nowTick, lastActiveTime, statusLocal, data]);

  const totalActiveSeconds = React.useMemo(() => {
    if (!startedAtMs) return 0;
    const currentStatus = statusLocal || (data as any)?.mechanic_status;
    const isActive = currentStatus === 'in_progress' || currentStatus === 'travel';
    const endTime = endedAtMs ?? (isActive ? nowTick : lastActiveTime);
    const elapsed = Math.max(0, Math.floor((endTime - startedAtMs) / 1000));
    // For travel time, we don't subtract paused seconds as travel is billable time
    const shouldSubtractPaused = currentStatus !== 'travel';
    return Math.max(0, elapsed - (shouldSubtractPaused ? pausedSeconds : 0));
  }, [startedAtMs, endedAtMs, nowTick, lastActiveTime, pausedSeconds, statusLocal, data]);

  // Calculate total paused time from pause log
  const totalPausedFromLog = React.useMemo(() => {
    const pauseLog = (data as any)?.mechanic_pause_log || [];
    let totalPaused = 0;

    for (const pause of pauseLog) {
      if (pause.start && pause.end) {
        // Both start and end timestamps exist
        const startTime = new Date(pause.start).getTime();
        const endTime = new Date(pause.end).getTime();
        totalPaused += Math.max(0, Math.floor((endTime - startTime) / 1000));
      } else if (pause.start && !pause.end) {
        // Currently paused - calculate from start to now
        const startTime = new Date(pause.start).getTime();
        const currentTime = endedAtMs ?? nowTick;
        totalPaused += Math.max(0, Math.floor((currentTime - startTime) / 1000));
      }
    }

    return totalPaused;
  }, [data, endedAtMs, nowTick]);

  // Travel timer derived values
  const travelStartedAtMs = (data as any)?.mechanic_travel_started_at ? Date.parse((data as any).mechanic_travel_started_at) : null;
  const travelAccumulated = Number((data as any)?.mechanic_total_travel_seconds || 0);
  const totalTravelSeconds = React.useMemo(() => {
    if (travelStartedAtMs && !isReadOnly && (statusLocal || (data as any).mechanic_status) === 'travel') {
      const currentStatus = statusLocal || (data as any)?.mechanic_status;
      const isTraveling = currentStatus === 'travel';
      const travelEndTime = isTraveling ? nowTick : lastActiveTime;
      const elapsed = Math.max(0, Math.floor((travelEndTime - travelStartedAtMs) / 1000));
      return travelAccumulated + elapsed;
    }
    return travelAccumulated;
  }, [travelStartedAtMs, travelAccumulated, nowTick, lastActiveTime, isReadOnly, statusLocal, data]);

  // Debounced auto-save of cause/correction to update business immediately
  React.useEffect(() => {
    if (!data || isReadOnly) return;
    const handler = setTimeout(() => {
      setJobCauseCorrection(id, { cause, correction }).catch(() => {});
    }, 700);
    return () => clearTimeout(handler);
  }, [cause, correction, isReadOnly, id, data]);

  // Debounced auto-save of vehicle details
  React.useEffect(() => {
    if (!data || isReadOnly) return;
    const handler = setTimeout(() => {
      const mileageNum = vehicleMileage ? parseFloat(vehicleMileage) : null;
      setJobCauseCorrection(id, { 
        vehicle_vin: vehicleVin, 
        mileage: mileageNum, 
        unit_no: vehicleUnitNo, 
        make_model: vehicleMakeModel 
      }).catch(() => {});
    }, 700);
    return () => clearTimeout(handler);
  }, [vehicleVin, vehicleMileage, vehicleUnitNo, vehicleMakeModel, isReadOnly, id, data]);

  // Immediately persist vehicle selection changes so they aren't lost if the user navigates away quickly
  const lastSyncedVehicleIdRef = React.useRef<string | null | undefined>(undefined);
  React.useEffect(() => {
    if (!data || isReadOnly) return;

    const vehicleIdFromData = (data as any)?.vehicle_id ? String((data as any)?.vehicle_id) : null;

    if (lastSyncedVehicleIdRef.current === undefined) {
      lastSyncedVehicleIdRef.current = vehicleIdFromData;
    }

    if (vehicleId === lastSyncedVehicleIdRef.current) {
      return;
    }

    if (!vehicleId) {
      lastSyncedVehicleIdRef.current = vehicleId;
      return;
    }

    setJobCauseCorrection(id, { vehicleId })
      .then(() => {
        lastSyncedVehicleIdRef.current = vehicleId;
      })
      .catch(() => {});
  }, [vehicleId, data, isReadOnly, id]);

  const setStatus = async (status: string) => {
		if (status === 'completed') {
			return handleMechanicComplete();
			return;
		}
		if (status === 'in_progress') {
			await controlJobTimer(id, 'start');
			// persist current details so inputs don't reset
			try { await setJobCauseCorrection(id, { cause, correction, vehicleId }); } catch (e) {}
		}
		if (status === 'paused') {
			let reason: string | undefined = undefined;
			Alert.prompt?.('Pause Job', 'Please enter a reason for pausing:', [
				{ text: 'Cancel', style: 'cancel' },
				{ text: 'OK', onPress: async (text?: string) => {
					reason = text || '';
					await pauseJobWithReason(id, reason || '');
					try { await setJobCauseCorrection(id, { cause, correction, vehicleId }); } catch (e) {}
					setStatusLocal('paused');
				}},
			], 'plain-text');
			// If Alert.prompt is not available (Android), fall back to simple pause without reason
			if (!('prompt' in Alert)) {
				await pauseJobWithReason(id, '');
			}
			return;
		}
		if (status === 'on_site' || status === 'en_route') {
			// status only
		}
		if (status === 'in_progress') {
			await controlJobTimer(id, 'resume');
			try { await setJobCauseCorrection(id, { cause, correction, vehicleId }); } catch (e) {}
		}
		setStatusLocal(status);
	};

	React.useEffect(() => {
		if (data) {
			setCause((data as any).cause || '');
			setCorrection((data as any).correction || '');
			setStatusLocal((data as any).mechanic_status || (data as any).status || 'not_started');
			const vehicleIdFromData = (data as any).vehicle_id ? String((data as any).vehicle_id) : null;
			setVehicleId(vehicleIdFromData);
			setVehicleVin((data as any).vehicle_vin || '');
			setVehicleMileage((data as any).mileage ? String((data as any).mileage) : '');
			setVehicleUnitNo((data as any).unit_no || '');
			setVehicleMakeModel((data as any).make_model || '');
		}
	}, [data]);

	React.useEffect(() => {
		let active = true;
		(async () => {
			const q = (productSearch || '').trim();
			if (!q) { if (active) setProducts([]); return; }
			const res = await apiClient.get('/parts/', { params: { search: q } });
			if (!active) return;
			setProducts(res.data || []);
		})();
		return () => { active = false; };
	}, [productSearch]);

	// Store full vehicle data for auto-fill
	const [vehiclesFullData, setVehiclesFullData] = React.useState<any[]>([]);

	React.useEffect(() => {
		let active = true;
		(async () => {
			const customerId = (data as any)?.customer_id;
			if (!customerId) return;
			const res = await apiClient.get(`/customers/${customerId}/vehicles/`);
			if (!active) return;
			const vehiclesData = res.data?.vehicles || [];
			setVehiclesFullData(vehiclesData); // Store full data
			const opts = vehiclesData.map((v: any) => ({
				id: String(v.id),
				label: `${v.unit_number || ''} ${v.make_model || ''} ${v.vin_number || ''}`.trim()
			}));
			setVehicles(opts);

			// After loading vehicles, check if we need to load the assigned vehicle details
			const workOrderVehicleId = (data as any)?.vehicle_id;
			if (workOrderVehicleId && !opts.find((v: any) => v.id === String(workOrderVehicleId))) {
				// The work order has a vehicle that's not in the customer's vehicle list
				// This might happen if the vehicle was deleted or belongs to a different customer
				// For now, create a placeholder entry
				setAssignedVehicle({
					id: String(workOrderVehicleId),
					label: `Assigned Vehicle (ID: ${workOrderVehicleId})`
				});
			}
		})();
		return () => { active = false; };
	}, [data]);

	// Auto-fill vehicle detail fields when a vehicle is selected
	React.useEffect(() => {
		if (!vehicleId || isReadOnly) return;
		
		const selectedVehicleData = vehiclesFullData.find((v: any) => String(v.id) === vehicleId);
		if (selectedVehicleData) {
			// Auto-fill vehicle details from selected vehicle
			setVehicleVin(selectedVehicleData.vin_number || selectedVehicleData.vin || '');
			setVehicleMileage(selectedVehicleData.current_mileage ? String(selectedVehicleData.current_mileage) : '');
			setVehicleUnitNo(selectedVehicleData.unit_number || '');
			setVehicleMakeModel(selectedVehicleData.make_model || '');
		}
	}, [vehicleId, vehiclesFullData, isReadOnly]);

	const addProduct = async (p: any) => {
		setSelectedProducts((prev) => {
			const existing = prev.find((x) => x.id === p.id);
			if (existing) return prev.map((x) => x.id === p.id ? { ...x, qty: x.qty + 1 } : x);
			return [...prev, { id: p.id, qty: 1, name: p.name }];
		});
		try {
			const { data } = await apiClient.post(`/jobs/${id}/parts/`, { partId: p.id, quantity: 1 });
			// Sync qty from server response if provided
			if (data?.qty !== undefined) {
				setSelectedProducts((prev) => prev.map((x) => x.id === p.id ? { ...x, qty: data.qty } : x));
			}
		} catch (e) {}
	};

	const decreaseProduct = async (pId: string, clear: boolean = false) => {
		// Optimistically update UI
		setSelectedProducts((prev) => {
			const existing = prev.find((x) => x.id === pId);
			if (!existing) return prev;
			if (clear) return prev.filter((x) => x.id !== pId); // Remove completely
			if (existing.qty <= 1) return prev.filter((x) => x.id !== pId); // Remove when qty reaches 0
			return prev.map((x) => x.id === pId ? { ...x, qty: x.qty - 1 } : x);
		});
		try {
			const { data } = await apiClient.post(`/jobs/${id}/parts/remove/`, { partId: pId, clear });
			// If server deleted the record, ensure it's removed from local state
			if (data?.deleted || data?.qty === 0) {
				setSelectedProducts((prev) => prev.filter((x) => x.id !== pId));
			} else if (data?.qty !== undefined) {
				// Update with server quantity if still exists
				setSelectedProducts((prev) => prev.map((x) => x.id === pId ? { ...x, qty: data.qty } : x));
			}
		} catch (e) {
			// On error, refetch to get accurate state
			console.error('Failed to remove product:', e);
		}
	};

	const submitSelectedProducts = async () => {};

  const handleStartJob = async () => {
    try {
      console.log('🚀 Starting job:', id);
      const result = await controlJobTimer(id, 'start');
      console.log('✅ Job start API result:', result);

      try {
        await setJobCauseCorrection(id, { cause, correction, vehicleId });
      } catch (e) {
        console.warn('⚠️  Failed to save cause/correction:', e);
      }

      setStatusLocal('in_progress');
      queryClient.invalidateQueries({ queryKey: ['job', id] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });

      console.log('✅ Job started successfully');
    } catch (error) {
      console.error('❌ Failed to start job:', error);
      Alert.alert('Error', 'Failed to start job. Please try again.');
    }
  };

  const handlePauseConfirm = async () => {
    const reason = selectedPauseKey === 'travel'
      ? 'Traveling to jobsite'
      : selectedPauseKey === 'lunch'
      ? 'Lunch'
      : selectedPauseKey === 'other_job'
      ? 'Working on other job'
      : (customPauseText || 'Other');
    await pauseJobWithReason(id, reason);
    try { await setJobCauseCorrection(id, { cause, correction, vehicleId }); } catch (e) {}
    setStatusLocal(selectedPauseKey === 'travel' ? 'travel' : 'paused');
    setPauseModalVisible(false);
    queryClient.invalidateQueries({ queryKey: ['job', id] });
  };

  const handleArrived = async () => {
    await arrivedAtJobsite(id);
    setStatusLocal('in_progress');
    queryClient.invalidateQueries({ queryKey: ['job', id] });
  };

  const handleResume = async () => {
    await controlJobTimer(id, 'resume');
    setStatusLocal('in_progress');
    queryClient.invalidateQueries({ queryKey: ['job', id] });
  };

  const handleMechanicComplete = async () => {
    if (!cause.trim() || !correction.trim()) {
      Alert.alert('Required Fields', 'Please enter both cause and correction before marking complete.');
      return;
    }
    Alert.alert(
      'Confirm Completion',
      'Are you sure? This will lock the form for the mechanic and notify the business.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Mark Complete',
          style: 'destructive',
          onPress: async () => {
            try {
              await setJobCauseCorrection(id, { cause: cause.trim(), correction: correction.trim(), vehicleId });
              await mechanicComplete(id);
              Alert.alert('Success', 'Marked complete for review by business.');
      queryClient.invalidateQueries({ queryKey: ['job', id] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
            } catch (error) {
              Alert.alert('Error', 'Failed to mark complete. Please try again.');
            }
          }
        }
      ]
    );
  };

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.background }}>
        <ActivityIndicator size="large" />
        <Text variant="bodyLarge" style={{ marginTop: 16 }}>Loading work order...</Text>
      </View>
    );
  }

  if (error) {
  return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.background, padding: 20 }}>
        <Text variant="headlineSmall" style={{ marginBottom: 16, textAlign: 'center' }}>Unable to Load Work Order</Text>
        <Text variant="bodyLarge" style={{ marginBottom: 20, textAlign: 'center', color: theme.colors.onSurfaceVariant }}>
          There was an error loading this assignment. Please try again.
        </Text>
        <Button mode="contained" onPress={() => navigation.goBack()}>
          Go Back
        </Button>
      </View>
    );
  }

  if (!data) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.background, padding: 20 }}>
        <Text variant="headlineSmall" style={{ marginBottom: 16, textAlign: 'center' }}>Work Order Not Found</Text>
        <Text variant="bodyLarge" style={{ marginBottom: 20, textAlign: 'center', color: theme.colors.onSurfaceVariant }}>
          This work order could not be found or you don't have access to it.
        </Text>
        <Button mode="contained" onPress={() => navigation.goBack()}>
          Go Back to Jobs
          </Button>
      </View>
    );
  }

  const selectedVehicle = vehicles.find(v => v.id === vehicleId) || assignedVehicle;

  const jobVehicle = (data as any)?.vehicle || (data as any)?.vehicle_details || {};

  const toStringOrEmpty = (value: any) => {
    if (value === undefined || value === null) return '';
    const str = String(value).trim();
    return str;
  };

  const pmVehicleDetails = {
    id: selectedVehicle?.id || ((data as any)?.vehicle_id ? String((data as any)?.vehicle_id) : ''),
    label: selectedVehicle?.label || jobVehicle?.label || '',
    unitNumber: toStringOrEmpty(jobVehicle?.unit_number ?? (data as any)?.unit_number),
    vin: toStringOrEmpty(jobVehicle?.vin_number ?? jobVehicle?.vin ?? (data as any)?.vin_number),
    makeModel: toStringOrEmpty(jobVehicle?.make_model ?? (data as any)?.make_model),
    licensePlate: toStringOrEmpty(jobVehicle?.license_plate ?? (data as any)?.license_plate),
    mileage: toStringOrEmpty(jobVehicle?.mileage ?? jobVehicle?.current_mileage ?? (data as any)?.mileage),
    year: toStringOrEmpty(jobVehicle?.year ?? jobVehicle?.model_year ?? (data as any)?.year),
  };

  const vehicleHistoryId = React.useMemo(() => {
    if (selectedVehicle?.id) {
      return selectedVehicle.id;
    }
    const fallbackId = (data as any)?.vehicle_id;
    return fallbackId ? String(fallbackId) : null;
  }, [selectedVehicle, data]);

  const vehicleHistoryLabel = React.useMemo(() => {
    if (selectedVehicle?.label) {
      return selectedVehicle.label;
    }
    if (pmVehicleDetails.label) {
      return pmVehicleDetails.label;
    }
    const summaryParts = [pmVehicleDetails.unitNumber, pmVehicleDetails.vin].filter(Boolean);
    if (summaryParts.length > 0) {
      return summaryParts.join(' • ');
    }
    return 'Vehicle';
  }, [selectedVehicle, pmVehicleDetails]);

  const pmBusinessInfo = {
    name: (data as any)?.business_name || undefined,
    address: (data as any)?.business_address || undefined,
    phone: (data as any)?.business_phone || undefined,
    email: (data as any)?.business_email || undefined,
    website: (data as any)?.business_website || undefined,
  };

  const workOrderDisplay = (data as any)?.work_order_number || (data as any)?.id;

	const formatHMS = (secs: number) => {
		const h = Math.floor(secs / 3600);
		const m = Math.floor((secs % 3600) / 60);
		const s = secs % 60;
		return `${h}:${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')}`;
	};

  return (
		<ScrollView contentContainerStyle={{ paddingTop: 50, paddingHorizontal: 16, paddingBottom: 24, backgroundColor: theme.colors.background }}>
			{/* Job Header Section */}
			<Card style={{ marginBottom: 16, elevation: 4 }}>
				<Card.Content>
					<View style={{ marginBottom: 16 }}>
						<Text variant="headlineMedium" style={{ fontWeight: 'bold', color: theme.colors.primary, marginBottom: 8 }}>
                                                        Work Order #{workOrderDisplay ?? '—'}
						</Text>
						<View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
							<Badge size={24} style={{ backgroundColor: getStatusColor((data as any)?.status || 'not_started') }}>
								{(data as any)?.status?.replace('_',' ').toUpperCase() || 'NOT STARTED'}
							</Badge>
						</View>
						<View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
							<View style={{ flex: 1, minWidth: 0 }}>
								<Text variant="bodyLarge" style={{ fontWeight: 'bold', marginBottom: 4 }} numberOfLines={2} ellipsizeMode="tail">
									Customer: {(data as any)?.customer_name || 'Unknown'}
								</Text>
								{(data as any)?.address && (
									<Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }} numberOfLines={2} ellipsizeMode="tail">
										📍 {(data as any).address}
									</Text>
								)}
							</View>
							{(data as any)?.scheduled_at && (
								<View style={{ alignItems: 'flex-end', flexShrink: 0 }}>
									<Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>Scheduled</Text>
									<Text variant="bodyMedium" style={{ fontWeight: 'bold' }}>
										{new Date((data as any).scheduled_at).toLocaleDateString()}
									</Text>
								</View>
							)}
						</View>
					</View>
                        </Card.Content>
                </Card>

                        {collaborators.length > 0 && (
                                <Card style={{ marginBottom: 16, elevation: 2 }}>
                                        <Card.Content>
                                                <Text variant="titleMedium" style={{ marginBottom: 4, color: theme.colors.primary }}>
                                                        Your team on this job
                                                </Text>
                                                <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant, marginBottom: 8 }}>
                                                        These mechanics are also assigned to collaborate on this work order.
                                                </Text>
                                                <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
                                                        {collaborators.map(collab => (
                                                                <Chip
                                                                        key={`collab-${collab.assignment_id}`}
                                                                        mode={collab.submitted ? 'outlined' : 'flat'}
                                                                        icon={collab.submitted ? 'check-circle' : undefined}
                                                                        style={{ marginRight: 6, marginBottom: 6 }}
                                                                        textStyle={{ fontSize: 13 }}
                                                                >
                                                                        {collab.name}{collab.submitted ? ' • submitted' : ''}
                                                                </Chip>
                                                        ))}
                                                </View>
                                        </Card.Content>
                                </Card>
                        )}

                        {/* Job Timer Header Card */}
                        <Card style={{ marginBottom: 16, elevation: 4 }}>
                                <Card.Content>
					<View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                        <Badge size={28} style={{ backgroundColor: getStatusColor(statusLocal || (data as any).mechanic_status || 'not_started'), paddingHorizontal: 12, height: 34, justifyContent: 'center' }}>
                            {(statusLocal || (data as any).mechanic_status || 'not_started').replace('_',' ').toUpperCase()}
                        </Badge>
                        <Text variant="titleLarge" style={{ color: theme.colors.onSurfaceVariant, fontWeight: 'bold' }}>
                            {startedAtMs ? `Active: ${formatHMS(totalActiveSeconds)}` : 'Not started'}
                        </Text>
                    </View>
                    {isReadOnly ? (
                        <View style={{ padding: 8, backgroundColor: theme.colors.surface, borderRadius: 8 }}>
                            <Text variant="bodySmall" style={{ textAlign: 'center', color: theme.colors.onSurfaceVariant }}>
                                ✓ This work order is read-only for the mechanic
                            </Text>
                        </View>
                    ) : (
                        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
                            {!startedAtMs && (
                                <Button mode="contained" onPress={handleStartJob} style={{ paddingVertical: 6, borderRadius: 10 }} labelStyle={{ fontSize: 16 }}>Start Job</Button>
                            )}
                            {(statusLocal || (data as any).mechanic_status) === 'in_progress' && (
                                <Button mode="outlined" onPress={() => setPauseModalVisible(true)} style={{ paddingVertical: 6, borderRadius: 10 }} labelStyle={{ fontSize: 16 }}>Pause</Button>
                            )}
                            {(statusLocal || (data as any).mechanic_status) === 'travel' && (
                                <Button mode="contained" onPress={handleArrived} style={{ paddingVertical: 6, borderRadius: 10 }} labelStyle={{ fontSize: 16 }}>Arrived</Button>
                            )}
                            {(statusLocal || (data as any).mechanic_status) === 'paused' && (
                                <Button mode="contained" onPress={handleResume} style={{ paddingVertical: 6, borderRadius: 10 }} labelStyle={{ fontSize: 16 }}>Resume</Button>
                            )}
                        </View>
                    )}
				</Card.Content>
			</Card>

			{/* Travel timer info */}
			{totalTravelSeconds > 0 && (
				<Card style={{ marginTop: -8, marginBottom: 16, elevation: 1 }}>
					<Card.Content>
						<Text variant="titleMedium" style={{ color: theme.colors.onSurfaceVariant, fontWeight: 'bold' }}>
							Travel: {formatHMS(totalTravelSeconds)}
						</Text>
					</Card.Content>
				</Card>
			)}

			{/* Owner's Description */}
			<Card style={{ marginBottom: 16, elevation: 2 }}>
				<Card.Content>
					<Text variant="titleMedium" style={{ marginBottom: 8, color: theme.colors.primary }}>Owner's Description</Text>
					<Text style={{ lineHeight: 20 }}>{(data as any).description || (data as any).title}</Text>
				</Card.Content>
			</Card>

			{/* Vehicle Section */}
                        <Card style={{ marginBottom: 16, elevation: 2 }}>
                                <Card.Content>
                                        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                                                <Text variant="titleMedium" style={{ color: theme.colors.primary }}>Vehicle Information</Text>
                                                <Button
                                                        icon="history"
                                                        mode="outlined"
                                                        compact
                                                        onPress={() => setVehicleHistoryVisible(true)}
                                                        disabled={!vehicleHistoryId}
                                                >
                                                        View History
                                                </Button>
                                        </View>

                                        {isReadOnly ? (
				// Read-only vehicle display
				<>
				{selectedVehicle ? (
					<View style={{ backgroundColor: theme.colors.surface, padding: 12, borderRadius: 8, marginBottom: 12 }}>
						<Text variant="bodyLarge" style={{ fontWeight: 'bold', color: theme.colors.primary }}>
							Vehicle Worked On
						</Text>
						<Text variant="bodyMedium" style={{ marginTop: 4 }}>
							{selectedVehicle.label}
						</Text>
					</View>
				) : (
					<View style={{ backgroundColor: theme.colors.surface, padding: 12, borderRadius: 8, marginBottom: 12 }}>
						<Text variant="bodyLarge" style={{ fontWeight: 'bold', color: theme.colors.primary }}>
							Vehicle Worked On
						</Text>
						<Text variant="bodyMedium" style={{ marginTop: 4, color: theme.colors.onSurfaceVariant }}>
							No vehicle selected
						</Text>
					</View>
				)}
				{(vehicleVin || vehicleMileage || vehicleUnitNo || vehicleMakeModel) && (
					<View style={{ backgroundColor: theme.colors.surface, padding: 12, borderRadius: 8, marginBottom: 8 }}>
						<Text variant="bodySmall" style={{ color: theme.colors.primary, marginBottom: 4, fontWeight: 'bold' }}>Vehicle Details:</Text>
						{vehicleVin && <Text variant="bodySmall">VIN: {vehicleVin}</Text>}
						{vehicleMileage && <Text variant="bodySmall">Mileage: {vehicleMileage}</Text>}
						{vehicleUnitNo && <Text variant="bodySmall">Unit No: {vehicleUnitNo}</Text>}
						{vehicleMakeModel && <Text variant="bodySmall">Make/Model: {vehicleMakeModel}</Text>}
					</View>
				)}
				</>
			) : (
				// Editable vehicle selection
				selectedVehicle ? (
					<View style={{ backgroundColor: theme.colors.surface, padding: 12, borderRadius: 8, marginBottom: 12 }}>
						<Text variant="bodyLarge" style={{ fontWeight: 'bold' }}>{selectedVehicle.label}</Text>
						<Button mode="text" onPress={() => setVehicleId(null)} style={{ alignSelf: 'flex-start', marginTop: 4 }}>
							Change Vehicle
          </Button>
					</View>
				) : (
					<>
						{vehicles.length > 0 ? (
							<Picker
								enabled={!isReadOnly}
								selectedValue={vehicleId || ''}
								onValueChange={(val) => setVehicleId(val || null)}
								style={{ marginBottom: 12, backgroundColor: theme.colors.surface, opacity: isReadOnly ? 0.6 : 1 }}
							>
								<Picker.Item label="— Select vehicle —" value="" />
								{vehicles.map((v) => (
									<Picker.Item key={v.id} label={v.label} value={v.id} />
								))}
							</Picker>
						) : (
							<Text style={{ marginBottom: 12, color: theme.colors.onSurfaceVariant }}>No vehicles available</Text>
						)}

						{!showAddVehicle ? (
							<Button mode="outlined" onPress={() => setShowAddVehicle(true)} style={{ marginBottom: 8 }}>
								+ Add New Vehicle
							</Button>
						) : (
							<View>
								<TextInput
									label="VIN Number *"
									value={newVehicle.vin_number}
									onChangeText={(t) => setNewVehicle({ ...newVehicle, vin_number: t })}
									style={{ marginVertical: 6 }}
								/>
								<TextInput
									label="Unit Number"
									value={newVehicle.unit_number}
									onChangeText={(t) => setNewVehicle({ ...newVehicle, unit_number: t })}
									style={{ marginVertical: 6 }}
								/>
								<TextInput
									label="Make/Model"
									value={newVehicle.make_model}
									onChangeText={(t) => setNewVehicle({ ...newVehicle, make_model: t })}
									style={{ marginVertical: 6 }}
								/>
								<View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>
									<Button
										mode="contained"
										onPress={async () => {
											if (!newVehicle.vin_number.trim()) {
												Alert.alert('Error', 'VIN number is required');
												return;
											}
											try {
												const customerId = (data as any)?.customer_id;
												if (!customerId) return;
												const res = await apiClient.post(`/customers/${customerId}/vehicles/create/`, newVehicle);
												const newId = String(res.data.id);
												
												// Auto-fill vehicle detail fields from the newly created vehicle
												setVehicleVin(newVehicle.vin_number || '');
												setVehicleUnitNo(newVehicle.unit_number || '');
												setVehicleMakeModel(newVehicle.make_model || '');
												setVehicleMileage(''); // New vehicle has no mileage yet
												
												setVehicleId(newId);
												setShowAddVehicle(false);
												setNewVehicle({ vin_number: '', unit_number: '', make_model: '' });
												// refresh list
												const list = await apiClient.get(`/customers/${customerId}/vehicles/`);
												const vehiclesData = list.data?.vehicles || [];
												setVehiclesFullData(vehiclesData); // Update full data
												setVehicles(vehiclesData.map((v: any) => ({
													id: String(v.id),
													label: `${v.unit_number || ''} ${v.make_model || ''} ${v.vin_number || ''}`.trim()
												})));
											} catch (error) {
												Alert.alert('Error', 'Failed to save vehicle. Please try again.');
											}
										}}
										style={{ flex: 1 }}
									>
										Save Vehicle
									</Button>
									<Button mode="text" onPress={() => setShowAddVehicle(false)} style={{ flex: 1 }}>
										Cancel
									</Button>
								</View>
      </View>
						)}
					</>
				)
			)}

			{/* Additional Vehicle Details Fields */}
			{!isReadOnly && (
				<View style={{ marginTop: 16 }}>
					<Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant, marginBottom: 8 }}>
						Optional: Add additional vehicle details
					</Text>
					<TextInput
						label="VIN (Optional)"
						value={vehicleVin}
						onChangeText={setVehicleVin}
						style={{ marginVertical: 6 }}
						placeholder="Enter 17-digit VIN"
						maxLength={17}
					/>
					<TextInput
						label="Mileage/Odometer (Optional)"
						value={vehicleMileage}
						onChangeText={setVehicleMileage}
						keyboardType="numeric"
						style={{ marginVertical: 6 }}
						placeholder="Enter current mileage"
					/>
					<TextInput
						label="Unit Number/License Plate (Optional)"
						value={vehicleUnitNo}
						onChangeText={setVehicleUnitNo}
						style={{ marginVertical: 6 }}
						placeholder="Enter unit # or license plate"
						maxLength={16}
					/>
					<TextInput
						label="Make & Model (Optional)"
						value={vehicleMakeModel}
						onChangeText={setVehicleMakeModel}
						style={{ marginVertical: 6 }}
						placeholder="Enter make and model"
						maxLength={50}
					/>
				</View>
			)}
				</Card.Content>
                        </Card>

                        {/* Preventive Maintenance Checklist */}
                        <Card style={{ marginBottom: 16, elevation: 2 }}>
                                <Card.Content>
                                        <Text variant="titleMedium" style={{ marginBottom: 8, color: theme.colors.primary }}>
                                                Preventive Maintenance Checklist
                                        </Text>
                                        <Text style={{ color: theme.colors.onSurfaceVariant, marginBottom: 12 }}>
                                                Mechanics can launch the PM inspection checklist to capture digital sign-off or
                                                print a blank copy before starting service.
                                        </Text>
                                        <Button
                                                icon="clipboard-check"
                                                mode="contained"
                                                onPress={() =>
                                                        navigation.navigate('PmChecklist', {
                                                                jobId: id,
                                                                workOrderNumber: workOrderDisplay,
                                                                customerName: (data as any)?.customer_name || undefined,
                                                                location: (data as any)?.address || undefined,
                                                                businessInfo: pmBusinessInfo,
                                                                vehicleDetails: pmVehicleDetails,
                                                        })
                                                }
                                                style={{ alignSelf: 'flex-start' }}
                                        >
                                                Open PM Checklist
                                        </Button>
                                </Card.Content>
                        </Card>

                        {/* Mechanic Notes */}
			<Card style={{ marginBottom: 16, elevation: 2 }}>
				<Card.Content>
					<Text variant="titleMedium" style={{ marginBottom: 12, color: theme.colors.primary }}>Mechanic Notes</Text>
					{isReadOnly ? (
						<>
							<View style={{ backgroundColor: theme.colors.surface, padding: 12, borderRadius: 8, marginVertical: 6 }}>
								<Text variant="bodySmall" style={{ color: theme.colors.primary, marginBottom: 4 }}>Cause Found:</Text>
								<Text style={{ color: theme.colors.onSurfaceVariant }}>{cause || 'Not specified'}</Text>
							</View>
							<View style={{ backgroundColor: theme.colors.surface, padding: 12, borderRadius: 8, marginVertical: 6 }}>
								<Text variant="bodySmall" style={{ color: theme.colors.primary, marginBottom: 4 }}>Corrections Made:</Text>
								<Text style={{ color: theme.colors.onSurfaceVariant }}>{correction || 'Not specified'}</Text>
							</View>
						</>
					) : (
						<>
							<TextInput
								label="Cause Found *"
								value={cause}
								onChangeText={setCause}
								multiline
								numberOfLines={6}
								style={{ marginVertical: 6, minHeight: 120 }}
								placeholder="Describe what was found to be the cause of the issue..."
							/>
							<TextInput
								label="Corrections Made *"
								value={correction}
								onChangeText={setCorrection}
								multiline
								numberOfLines={6}
								style={{ marginVertical: 6, minHeight: 120 }}
								placeholder="Describe the corrections and repairs performed..."
							/>
						</>
					)}
				</Card.Content>
			</Card>

			{/* Products Used */}
			<Card style={{ marginBottom: 16, elevation: 2 }}>
				<Card.Content>
					<Text variant="titleMedium" style={{ marginBottom: 12, color: theme.colors.primary }}>Products Used</Text>
					
					{/* Selected Products - Show at Top */}
					{selectedProducts.filter(sp => sp.qty > 0).length > 0 && (
						<View style={{ marginBottom: 16, backgroundColor: '#f0f9ff', padding: 12, borderRadius: 8, borderWidth: 1, borderColor: '#3b82f6' }}>
							<Text variant="titleSmall" style={{ marginBottom: 8, color: theme.colors.primary, fontWeight: 'bold' }}>
								✓ Added Products ({selectedProducts.filter(sp => sp.qty > 0).length})
							</Text>
							{selectedProducts.filter(sp => sp.qty > 0).map((sp) => (
								<View key={sp.id} style={{ backgroundColor: '#ffffff', padding: 12, borderRadius: 8, marginBottom: 8, borderWidth: 1, borderColor: '#e5e7eb' }}>
									<View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
										<View style={{ flex: 1 }}>
											<Text variant="bodyLarge" style={{ fontWeight: 'bold' }}>{sp.name}</Text>
											<Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant, marginTop: 4 }}>
												Quantity: {sp.qty}
											</Text>
										</View>
										{!isReadOnly && (
											<View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
												<IconButton icon="minus" size={20} onPress={() => decreaseProduct(sp.id)} mode="contained-tonal" />
												<Text variant="titleMedium" style={{ minWidth: 30, textAlign: 'center', fontWeight: 'bold' }}>{sp.qty}</Text>
												<IconButton icon="plus" size={20} onPress={() => addProduct({ id: sp.id, name: sp.name })} mode="contained" />
												<IconButton icon="delete" size={20} onPress={() => decreaseProduct(sp.id, true)} mode="outlined" iconColor={theme.colors.error} />
											</View>
										)}
									</View>
								</View>
							))}
						</View>
					)}

					{/* Search and Add Products */}
					{!isReadOnly && (
						<>
							<TextInput
								placeholder="Search parts by name or SKU..."
								value={productSearch}
								onChangeText={setProductSearch}
								style={{ marginVertical: 8 }}
								left={<TextInput.Icon icon="magnify" />}
								right={productSearch ? <TextInput.Icon icon="close" onPress={() => setProductSearch('')} /> : undefined}
							/>
							{(productSearch || '').trim().length > 0 && (products || []).slice(0, 10).map((p) => {
								const sel = selectedProducts.find((x) => x.id === p.id);
								const isAlreadyAdded = Boolean(sel && sel.qty > 0);
								return (
									<List.Item
										key={p.id}
										title={p.name}
										description={`SKU: ${p.sku || 'N/A'}`}
										left={() => (
											<View style={{ justifyContent: 'center', paddingLeft: 8 }}>
												<MaterialIcons 
													name={isAlreadyAdded ? "check-circle" : "add-circle-outline"} 
													size={24} 
													color={isAlreadyAdded ? theme.colors.primary : theme.colors.onSurfaceVariant} 
												/>
											</View>
										)}
										right={() => (
											<View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
												{(p.image_url || p.image) && (
													<Button 
														mode="text" 
														onPress={() => setPreviewImage((p.image_url || p.image || '').toString() || '')}
														compact
													>
														View
													</Button>
												)}
												<Button
													mode={isAlreadyAdded ? 'contained-tonal' : 'contained'}
													onPress={() => addProduct(p)}
													style={{ borderRadius: 20 }}
													compact
												>
													{isAlreadyAdded ? `Added (${sel?.qty})` : 'Add'}
												</Button>
											</View>
										)}
										style={{ 
											backgroundColor: isAlreadyAdded ? '#e8f4fd' : theme.colors.surface, 
											marginVertical: 4, 
											borderRadius: 8,
											borderWidth: 1,
											borderColor: isAlreadyAdded ? '#3b82f6' : '#e5e7eb'
										}}
									/>
								);
							})}
							{(productSearch || '').trim().length > 0 && (products || []).length === 0 && (
								<Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant, textAlign: 'center', marginVertical: 16 }}>
									No parts found. Try a different search term.
								</Text>
							)}
						</>
					)}
				</Card.Content>
			</Card>

			{/* Media & Actions */}
			<Card style={{ marginBottom: 16, elevation: 2 }}>
				<Card.Content>
					<Text variant="titleMedium" style={{ marginBottom: 12, color: theme.colors.primary }}>Media & Documentation</Text>

					{/* Mechanic Uploads Review Section */}
					{((data as any).media_files?.length > 0 || (data as any).signature_file) && (
						<View style={{ marginBottom: 16, padding: 12, backgroundColor: '#f8f9fa', borderRadius: 8 }}>
							<Text variant="titleSmall" style={{ marginBottom: 8, color: theme.colors.primary, fontWeight: 'bold' }}>
								📋 Your Uploads for Review:
							</Text>

							{/* Display uploaded photos as thumbnails */}
							{(data as any).media_files?.length > 0 && (
								<View style={{ marginBottom: 12 }}>
									<Text variant="bodyMedium" style={{ marginBottom: 8, fontWeight: 'bold' }}>📸 Photos ({(data as any).media_files.length}):</Text>
									<View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
										{(data as any).media_files.map((file: string, index: number) => (
											<TouchableOpacity key={index} onPress={() => setPreviewImage(`https://www.smart-invoices.com/media/${file}`)}>
												<Image source={{ uri: `https://www.smart-invoices.com/media/${file}` }} style={{ width: 96, height: 96, borderRadius: 8, margin: 4, backgroundColor: '#eaeaea' }} />
											</TouchableOpacity>
										))}
									</View>
								</View>
							)}

							{/* Display signature */}
							{(data as any).signature_file && (
								<View style={{ marginTop: 8 }}>
									<Text variant="bodyMedium" style={{ marginBottom: 8, fontWeight: 'bold' }}>✍️ Signature:</Text>
									<TouchableOpacity onPress={() => setPreviewImage((data as any).signature_file)}>
										<Image source={{ uri: (data as any).signature_file }} style={{ width: 200, height: 100, borderRadius: 6, backgroundColor: '#fff', borderWidth: 1, borderColor: '#eee' }} resizeMode="contain" />
									</TouchableOpacity>
								</View>
							)}
						</View>
					)}

					{/* Duplicate gallery/signature sections removed; see uploads review above */}

					{!isReadOnly && (
						<View style={{ flexDirection: 'row', gap: 12, marginBottom: 16 }}>
							<Button mode="contained" onPress={() => navigation.navigate('PhotoCapture', { jobId: (data as any).id })} style={{ flex: 1 }} icon="camera">Capture Photo</Button>
							<Button mode="contained" onPress={() => navigation.navigate('Signature', { jobId: (data as any).id })} style={{ flex: 1 }} icon="draw">Capture Signature</Button>
						</View>
					)}

					{!isReadOnly ? (
						<Button
							mode="contained"
							onPress={handleMechanicComplete}
							style={{ marginTop: 8 }}
							icon="check-circle"
						>
							Mark as Completed
						</Button>
					) : (
						<View style={{ padding: 12, backgroundColor: theme.colors.surface, borderRadius: 8 }}>
							<Text variant="bodyLarge" style={{ textAlign: 'center', color: theme.colors.primary }}>
								✓ Marked Complete by Mechanic
							</Text>
							<Text variant="bodySmall" style={{ textAlign: 'center', color: theme.colors.onSurfaceVariant, marginTop: 4 }}>
								Completed on {new Date((data as any).mechanic_completed_at || (data as any).mechanic_ended_at || (data as any).completed_at).toLocaleDateString()}
							</Text>

							{/* Show completion summary for completed jobs */}
							{((data as any).media_files?.length > 0 || (data as any).signature_file) && (
								<View style={{ marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: '#e0e0e0' }}>
									<Text variant="bodyMedium" style={{ marginBottom: 8, fontWeight: 'bold', textAlign: 'center' }}>
										📋 Completion Summary:
									</Text>
									{(data as any).media_files?.length > 0 && (
										<Text variant="bodySmall" style={{ textAlign: 'center', marginBottom: 4 }}>
											📸 Photos: {(data as any).media_files.length} uploaded
										</Text>
									)}
									{(data as any).signature_file && (
										<Text variant="bodySmall" style={{ textAlign: 'center' }}>
											✍️ Signature: Captured and saved
										</Text>
									)}
								</View>
							)}
						</View>
					)}
				</Card.Content>
			</Card>

			{/* Fullscreen preview modal */}
			<Modal visible={!!previewImage} transparent animationType="fade" onRequestClose={() => setPreviewImage(null)}>
				<View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.9)', alignItems: 'center', justifyContent: 'center' }}>
					{previewImage ? (
						<Image source={{ uri: previewImage }} style={{ width: '90%', height: '70%' }} resizeMode="contain" />
					) : null}
					<Button mode="contained" onPress={() => setPreviewImage(null)} style={{ marginTop: 16 }}>Close</Button>
				</View>
			</Modal>

			{/* Pause Reason Modal */}
                        <Modal visible={pauseModalVisible} transparent animationType="slide" onRequestClose={() => setPauseModalVisible(false)}>
                                <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
                                        <View style={{ width: '100%', maxWidth: 420, backgroundColor: '#fff', borderRadius: 8, padding: 16 }}>
                                                <Text variant="titleMedium" style={{ marginBottom: 12 }}>Pause Reason</Text>
                                                {/* Simple buttons used as a picker */}
						<View style={{ flexDirection: 'column', gap: 8 }}>
							<Button mode={selectedPauseKey==='travel'?'contained':'outlined'} onPress={() => setSelectedPauseKey('travel')}>Traveling to jobsite</Button>
							<Button mode={selectedPauseKey==='lunch'?'contained':'outlined'} onPress={() => setSelectedPauseKey('lunch')}>Lunch</Button>
							<Button mode={selectedPauseKey==='other_job'?'contained':'outlined'} onPress={() => setSelectedPauseKey('other_job')}>Working on other job</Button>
							<Button mode={selectedPauseKey==='other'?'contained':'outlined'} onPress={() => setSelectedPauseKey('other')}>Other</Button>
							{selectedPauseKey==='other' && (
								<TextInput placeholder="Enter reason" value={customPauseText} onChangeText={setCustomPauseText} style={{ marginTop: 8 }} />
							)}
						</View>
                                                <View style={{ flexDirection: 'row', justifyContent: 'flex-end', marginTop: 16 }}>
                                                        <Button onPress={() => setPauseModalVisible(false)} style={{ marginRight: 8 }}>Cancel</Button>
                                                        <Button mode="contained" onPress={handlePauseConfirm}>Pause</Button>
                                                </View>
                                        </View>
                                </View>
                        </Modal>

                        <VehicleHistoryModal
                                visible={vehicleHistoryVisible}
                                vehicleId={vehicleHistoryId}
                                vehicleLabel={vehicleHistoryLabel}
                                onDismiss={() => setVehicleHistoryVisible(false)}
                        />
    </ScrollView>
  );
}