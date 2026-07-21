import request from './request';
import type { LeadListResponse, LeadStats, Lead } from '../types';

export const getLeads = (params: {
  page?: number;
  page_size?: number;
  platform?: string;
  intent_type?: string;
  status?: string;
  min_score?: number;
  max_score?: number;
  level?: 'high' | 'medium' | 'low';
  keyword?: string;
  ip_location?: string;
  task_id?: string;
  start_ts?: number;
  end_ts?: number;
}): Promise<LeadListResponse> => {
  return request.get('/leads/list', { params });
};

/**
 * 导出获客线索为 Excel
 * 后端返回二进制流,前端用 blob 触发下载
 * 文件名由后端根据筛选条件生成(任务名_意向_地域_条数_时间.xlsx)
 */
export const exportLeads = (params: {
  task_id?: string;
  platform?: string;
  intent_type?: string;
  status?: string;
  min_score?: number;
  max_score?: number;
  level?: 'high' | 'medium' | 'low';
  keyword?: string;
  ip_location?: string;
  start_ts?: number;
  end_ts?: number;
}): Promise<Blob> => {
  return request.get('/leads/export', {
    params,
    responseType: 'blob',
  }) as unknown as Promise<Blob>;
};

/** 获取线索的 IP 属地分布 Top N(用于地域快捷标签) */
export const getLeadRegions = (params: {
  task_id?: string;
  level?: string;
  limit?: number;
}): Promise<Array<{ ip_location: string; count: number }>> => {
  return request.get('/leads/regions', { params });
};

export const getLeadStats = (params?: {
  task_id?: string;
  keyword?: string;
  level?: string;
  ip_location?: string;
  platform?: string;
}): Promise<LeadStats> => {
  return request.get('/leads/stats', { params });
};

export const getLeadDetail = (leadId: number): Promise<Lead> => {
  return request.get(`/leads/${leadId}`);
};

export const updateLeadStatus = (
  leadId: number,
  status: string,
  notes?: string
): Promise<{ success: boolean; message: string }> => {
  return request.post(`/leads/${leadId}/status`, { status, notes });
};

export const batchUpdateLeads = (data: {
  ids: number[];
  action: string;
  status?: string;
}): Promise<{ success: boolean; affected_count: number }> => {
  return request.post('/leads/batch', data);
};

export const deleteLead = (leadId: number): Promise<{ success: boolean; message: string }> => {
  return request.delete(`/leads/${leadId}`);
};

export const batchDeleteLeads = (ids: number[]): Promise<{ success: boolean; deleted_count: number }> => {
  return request.post('/leads/batch-delete', { ids });
};

export const deleteLeadsByTask = (taskId: string): Promise<{ success: boolean; deleted_count: number }> => {
  return request.delete(`/leads/task/${taskId}`);
};
