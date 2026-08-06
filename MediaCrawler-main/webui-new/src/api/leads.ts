import request from './request';
import type { LeadListResponse, LeadStats, Lead, LeadReply } from '../types';

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
  role_tag?: string;
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

/** A6 过滤无关线索: 将命中规则的线索标记为 ignored */
export const filterIrrelevantLeads = (data: {
  task_id: string;
  lead_ids?: number[];
  rules?: string[];  // 默认 ["low_score", "neutral_role"]
}): Promise<{ success: boolean; filtered_count: number; message: string }> => {
  return request.post('/leads/filter-irrelevant', data);
};

/** A6 一键去重: 按 content_hash 合并同任务下重复线索 */
export const dedupeLeads = (data: {
  task_id: string;
  dry_run?: boolean;
}): Promise<{ success: boolean; deduped_count: number; kept_count: number; message: string }> => {
  return request.post('/leads/dedupe', data);
};

// ==================== 联系方式采集 + 评论回复监测 ====================

/** 采集单条线索的用户主页联系方式(手机号/微信号/简介) */
export const collectLeadContact = (
  leadId: number
): Promise<{ success: boolean; data?: { phone: string; wechat: string; bio: string; status: string }; message?: string }> => {
  return request.post(`/leads/${leadId}/collect-contact`);
};

/** 批量采集联系方式(支持 lead_ids 直选 或 按 task_id+筛选条件) */
export const collectContactsBatch = (data: {
  lead_ids?: number[];
  task_id?: string;
  platform?: string;
  role_tag?: string;
  ip_location?: string;
  status?: string;
  level?: 'high' | 'medium' | 'low';
  start_ts?: number;
  end_ts?: number;
  limit?: number;
}): Promise<{ success: boolean; message: string; job_id?: string; total?: number }> => {
  return request.post('/leads/collect-contacts-batch', data);
};

/** 手动触发单条线索的评论回复监测 */
export const monitorLeadReplies = (
  leadId: number
): Promise<{ success: boolean; message: string; added?: number }> => {
  return request.post(`/leads/${leadId}/monitor-replies`);
};

/** 手动触发整个任务的评论回复监测(支持与列表一致的筛选条件) */
export const monitorTaskReplies = (
  taskId: string,
  filters?: {
    platform?: string;
    role_tag?: string;
    ip_location?: string;
    status?: string;
    level?: 'high' | 'medium' | 'low';
    start_ts?: number;
    end_ts?: number;
    limit?: number;
  }
): Promise<{ success: boolean; message: string; job_id?: string; total?: number }> => {
  return request.post(`/leads/task/${taskId}/monitor-replies`, filters || {});
};

/** 批量任务状态(供前端轮询进度) */
export interface BatchJobStatus {
  job_id: string;
  task_id: string;
  kind: 'contact_collect' | 'reply_monitor';
  status: 'running' | 'completed' | 'failed';
  total: number;
  completed: number;
  success: number;
  failed: number;
  message: string;
  created_at: number;
  updated_at: number;
}

/** 查询批量任务状态(轮询进度) */
export const getBatchJobStatus = (jobId: string): Promise<BatchJobStatus> => {
  return request.get(`/leads/batch-jobs/${jobId}`);
};

/** 查看某条线索监测到的评论回复列表 */
export const getLeadReplies = (
  leadId: number,
  params: { limit?: number; offset?: number } = {}
): Promise<{ items: LeadReply[]; total: number }> => {
  return request.get(`/leads/${leadId}/replies`, { params });
};

/** 将某条线索的评论回复标记为已读 */
export const markLeadRepliesRead = (
  leadId: number
): Promise<{ success: boolean; message: string }> => {
  return request.post(`/leads/${leadId}/replies/mark-read`);
};
