import request from './request';
import type { DashboardData } from '../types';

export const getDashboardData = (): Promise<DashboardData> => {
  return request.get('/dashboard');
};

export const getTrends = (days: number = 30): Promise<{ trends: Array<{ date: string; leads: number }> }> => {
  return request.get('/analytics/trends', { params: { days } });
};

export const getPlatformAnalytics = (): Promise<{
  platform_distribution: Array<{ platform: string; count: number }>;
  avg_scores: Record<string, number>;
}> => {
  return request.get('/analytics/platform');
};

export const getFunnelData = (): Promise<{ funnel: Array<{ status: string; count: number }> }> => {
  return request.get('/analytics/funnel');
};
