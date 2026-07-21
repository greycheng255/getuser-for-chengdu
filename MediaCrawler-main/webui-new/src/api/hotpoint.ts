import request from './request';

export interface HotItem {
  rank: number;
  title: string;
  url: string;
  hot: string;
  author: string;
  published_at: number;
  extra: Record<string, unknown>;
}

export interface PlatformMeta {
  id: string;
  name: string;
  region: 'china' | 'global';
  color: string;
  home: string;
}

export interface PlatformData {
  name: string;
  color: string;
  home: string;
  items: HotItem[];
}

export interface HotpointList {
  china: Record<string, PlatformData>;
  global: Record<string, PlatformData>;
}

// 注意: request 实例的 baseURL 已为 '/api'，此处路径无需再加 /api 前缀
export async function getPlatforms(): Promise<{ platforms: PlatformMeta[] }> {
  return request.get('/hotpoint/platforms');
}

export async function getHotpointList(forceRefresh = false): Promise<HotpointList> {
  return request.get('/hotpoint/list', { params: { force_refresh: forceRefresh } });
}

export async function getPlatformHotpoint(platform: string, forceRefresh = false): Promise<{
  success: boolean;
  platform: string;
  name: string;
  color: string;
  home: string;
  region: string;
  count: number;
  items: HotItem[];
}> {
  return request.get(`/hotpoint/${platform}`, { params: { force_refresh: forceRefresh } });
}

export async function refreshAllHotpoints(): Promise<{ success: boolean; message: string; counts: Record<string, number> }> {
  return request.post('/hotpoint/refresh');
}
