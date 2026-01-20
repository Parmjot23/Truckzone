import { apiClient } from '@/services/apiClient';

export async function uploadJobPhoto(jobId: string, uri: string) {
  const form = new FormData();
  form.append('file', {
    uri,
    name: `photo-${Date.now()}.jpg`,
    type: 'image/jpeg',
  } as any);
  const { data } = await apiClient.post(`/jobs/${jobId}/attachments/`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}