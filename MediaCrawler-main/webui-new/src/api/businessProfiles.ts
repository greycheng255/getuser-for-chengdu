import request from './request';

export interface BusinessProfile {
  id: string;
  name: string;
  business_intent: string;
  business_keywords: string[];
  intent_keywords: string[];
  exclude_keywords: string[];
  enabled: boolean;
  created_ts: number;
  updated_ts: number;
  preview: { discard_when: string; lead_when: string; fallback: string };
}

export const listBusinessProfiles = () => request.get<any, { items: BusinessProfile[] }>('/business-profiles');
export const createBusinessProfile = (data: Partial<BusinessProfile>) => request.post('/business-profiles', data);
export const updateBusinessProfile = (id: string, data: Partial<BusinessProfile>) => request.put(`/business-profiles/${id}`, data);
export const deleteBusinessProfile = (id: string) => request.delete(`/business-profiles/${id}`);
