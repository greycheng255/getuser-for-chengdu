import request from './request';

// ============ 类型定义 ============

export interface AmapPoi {
  poi_id: string;
  name: string;
  phone: string;
  address: string;
  province: string;
  city: string;
  district: string;
  business_hours: string;
  latitude: number;
  longitude: number;
  rating: number;
  category: string;
  typecode: string;
  photos: string[];
  extra?: Record<string, unknown>;
}

export interface SearchResult {
  configured: boolean;
  items: AmapPoi[];
  total: number;
  page: number;
  page_size: number;
  message?: string;
}

export interface LocalBusiness extends AmapPoi {
  business_id: string;
  rating_count: number;
  tags: string[];
  price_avg: number;
  source: string;
  owner_user_id: string;
  platform: string;
  platform_poi_id: string;
  created_at: number;
  updated_at: number;
}

export interface ListResponse<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface CityCount { city: string; count: number; }
export interface CategoryCount { category: string; count: number; }

// ============ API 调用 ============

export const getConfig = (): Promise<{ configured: boolean }> => {
  return request.get('/local-life/config');
};

export const getCities = (): Promise<CityCount[]> => {
  return request.get('/local-life/cities');
};

export const getCategories = (): Promise<CategoryCount[]> => {
  return request.get('/local-life/categories');
};

export const search = (params: {
  keyword: string;
  city?: string;
  page?: number;
  page_size?: number;
  types?: string;
}): Promise<SearchResult> => {
  return request.get('/local-life/search', { params });
};

export const searchDetail = (poi_id: string, source = 'amap'): Promise<{ detail: AmapPoi | null }> => {
  return request.get('/local-life/search/detail', { params: { poi_id, source } });
};

export const saveBusiness = (data: {
  platform?: string;
  poi_id: string;
  extra?: Record<string, unknown>;
}): Promise<{ saved: boolean; poi_id: string; reason?: string }> => {
  return request.post('/local-life/businesses/save', data);
};

export const batchSave = (data: {
  items: AmapPoi[];
  platform?: string;
}): Promise<{ saved: number; skipped: number; total: number }> => {
  return request.post('/local-life/businesses/batch-save', data);
};

export const listBusinesses = (params: {
  city?: string;
  category?: string;
  keyword?: string;
  min_rating?: number;
  page?: number;
  page_size?: number;
}): Promise<ListResponse<LocalBusiness>> => {
  return request.get('/local-life/businesses', { params });
};

export const getBusiness = (businessId: string): Promise<LocalBusiness> => {
  return request.get(`/local-life/businesses/${businessId}`);
};

export const updateBusiness = (
  businessId: string,
  data: Partial<Pick<LocalBusiness,
    'name' | 'phone' | 'address' | 'province' | 'city' | 'district' |
    'business_hours' | 'category' | 'tags' | 'photos' |
    'price_avg' | 'rating' | 'rating_count'>>
): Promise<void> => {
  return request.put(`/local-life/businesses/${businessId}`, data);
};

export const deleteBusiness = (businessId: string): Promise<void> => {
  return request.delete(`/local-life/businesses/${businessId}`);
};

export const exportBusinesses = (params: {
  city?: string;
  category?: string;
  keyword?: string;
  min_rating?: number;
}): Promise<Blob> => {
  return request.get('/local-life/businesses/export', {
    params,
    responseType: 'blob',
  }) as unknown as Promise<Blob>;
};
