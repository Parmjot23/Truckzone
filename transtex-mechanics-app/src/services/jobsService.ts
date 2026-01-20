import { apiClient } from '@/services/apiClient';

export type JobCollaborator = {
  assignment_id: number;
  mechanic_id: number;
  name: string;
  submitted: boolean;
};

export type JobAssignmentMeta = {
  id: number;
  token: string;
  submitted: boolean;
  timestamps?: Record<string, string | null>;
};

export type Job = {
  id: string;
  title: string;
  customer_name: string;
  address: string;
  scheduled_at: string;
  status: string;
  assignment?: JobAssignmentMeta;
  collaborators?: JobCollaborator[];
};

export type JobDetail = Job & {
  notes?: string;
  timestamps: Record<string, string | null>;
  customer_id?: number | null;
  vehicle_id?: number | null;
  description?: string;
  cause?: string;
  correction?: string;
  vehicle_vin?: string;
  mileage?: number | null;
  unit_no?: string;
  make_model?: string;
  has_signature?: boolean;
  signature_file?: string | null;
  media_files?: string[];
  mechanic_started_at?: string | null;
  mechanic_ended_at?: string | null;
  mechanic_paused_at?: string | null;
  mechanic_total_paused_seconds?: number;
  is_read_only?: boolean;
};

export async function getJobs(params: { search?: string }) {
  const { data } = await apiClient.get<Job[]>('/jobs/', { params });
  return data;
}

export async function getJob(id: string) {
  console.log('Fetching job with ID:', id);
  try {
    const { data } = await apiClient.get<JobDetail>(`/jobs/${id}/`);
    console.log('Job data received:', data);
    return data;
  } catch (error) {
    console.error('Error fetching job:', error);
    throw error;
  }
}

export async function setJobStatus(id: string, status: string) {
  const { data } = await apiClient.post(`/jobs/${id}/status/`, { status });
  return data;
}

export async function setJobCauseCorrection(id: string, payload: { 
  cause?: string; 
  correction?: string; 
  vehicleId?: string | null;
  vehicle_vin?: string;
  mileage?: number | null;
  unit_no?: string;
  make_model?: string;
}) {
  const { data } = await apiClient.post(`/jobs/${id}/details/`, payload);
  return data;
}

export async function controlJobTimer(id: string, action: 'start' | 'pause' | 'resume' | 'stop') {
  console.log(`⏰ Job Timer API Call: ${action} for job ${id}`);
  try {
    const { data } = await apiClient.post(`/jobs/${id}/timer/`, { action });
    console.log(`✅ Job Timer API Response:`, data);
    return data;
  } catch (error) {
    console.error(`❌ Job Timer API Error (${action}):`, error);
    throw error;
  }
}

export async function pauseJobWithReason(id: string, reason: string) {
  const { data } = await apiClient.post(`/jobs/${id}/timer/`, { action: 'pause', reason });
  return data;
}

export async function arrivedAtJobsite(id: string) {
  const { data } = await apiClient.post(`/jobs/${id}/timer/`, { action: 'arrived' });
  return data;
}

export async function mechanicComplete(id: string) {
  const { data } = await apiClient.post(`/jobs/${id}/timer/`, { action: 'complete' });
  return data;
}

export async function removeJobPart(id: string, partId: string, clear = false) {
  const { data } = await apiClient.post(`/jobs/${id}/parts/remove/`, { partId, clear });
  return data;
}