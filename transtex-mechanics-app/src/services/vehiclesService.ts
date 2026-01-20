import { apiClient } from '@/services/apiClient';

export type VehicleHistoryJob = {
  id: number;
  jobDate: string | null;
  description: string;
  notes: string;
};

export type VehicleHistoryPart = {
  id: number;
  jobDate: string | null;
  description: string;
  quantity: string | null;
  sku: string | null;
};

export type VehicleHistoryVehicle = {
  id: number;
  unitNumber: string;
  vin: string;
  makeModel: string;
  currentMileage: number | null;
};

export type VehicleHistoryResponse = {
  vehicle: VehicleHistoryVehicle;
  jobs: VehicleHistoryJob[];
  parts: VehicleHistoryPart[];
};

export async function getVehicleHistory(vehicleId: string | number) {
  const { data } = await apiClient.get<VehicleHistoryResponse>(`/mechanic/vehicles/${vehicleId}/history/`);
  return data;
}
