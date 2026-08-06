import request from './request';
import type { CrawlerTask } from '../types';

export const getTasks = (): Promise<CrawlerTask[]> => {
  return request.get('/tasks');
};

export const createTask = (data: Partial<CrawlerTask>): Promise<{ success: boolean; task_id: string }> => {
  return request.post('/tasks', data);
};

export const startTask = (taskId: string): Promise<{ success: boolean; message?: string }> => {
  return request.post(`/tasks/${taskId}/start`);
};

export const pauseTask = (taskId: string): Promise<{ success: boolean }> => {
  return request.post(`/tasks/${taskId}/pause`);
};

export const deleteTask = (taskId: string): Promise<{ success: boolean }> => {
  return request.delete(`/tasks/${taskId}`);
};

export const deleteTaskComments = (taskId: string): Promise<{ success: boolean; deleted_count: number }> => {
  return request.delete(`/tasks/${taskId}/comments`);
};

export const getTaskDetail = (taskId: string, commentOffset: number = 0, commentLimit: number = 100): Promise<{ task: CrawlerTask; logs: any[]; log_count: number; data?: any[]; data_count?: number; comments?: any[]; comment_count?: number }> => {
  return request.get(`/tasks/${taskId}`, { params: { comment_offset: commentOffset, comment_limit: commentLimit } });
};

export const getTaskLogs = (taskId: string, limit?: number): Promise<{ task_id: string; logs: any[]; total: number }> => {
  return request.get(`/tasks/${taskId}/logs`, { params: { limit } });
};

// 扫描任务全部评论生成线索(按任务上下文评分,写入 CustomerLead 表)
export const scanTaskLeads = (taskId: string): Promise<{
  success: boolean;
  task_id: string;
  scanned: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  saved: number;
  message: string;
}> => {
  return request.post(`/tasks/${taskId}/scan-leads`);
};

// 获取任务的线索统计(从 CustomerLead 表查,不受评论分页限制)
export const getTaskLeadsSummary = (taskId: string): Promise<{
  task_id: string;
  total: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  supplier_count: number;  // 合作厂家(供方)
  consumer_count: number;  // 需求方
  neutral_count: number;   // 中性
  scanned: boolean;
}> => {
  return request.get(`/tasks/${taskId}/leads-summary`);
};

export const retryTask = (taskId: string): Promise<{ success: boolean; message?: string }> => {
  return request.post(`/tasks/${taskId}/retry`);
};

export const updateTaskPromo = (taskId: string, data: { promo_config: any }): Promise<{ success: boolean; message?: string }> => {
  return request.put(`/tasks/${taskId}/promo`, data);
};

// 需求分析
export const analyzeUserNeeds = (taskId: string, data: { user_ids?: string[]; max_users?: number }): Promise<{
  analyzed_count: number;
  results: any[];
}> => {
  return request.post(`/tasks/${taskId}/analyze-needs`, data);
};

// 生成广告文案
export const generateAdContent = (taskId: string, data: { user_ids: string[]; content_type?: string; tone?: string }): Promise<{
  generated_count: number;
  contents: any[];
}> => {
  return request.post(`/tasks/${taskId}/generate-content`, data);
};

// 创建触达任务
export const createOutreachTask = (taskId: string, data: {
  user_id: string;
  sec_uid: string;
  platform?: string;
  method?: string;
  content: string;
  nickname?: string;
  note_id?: string;
  comment_id?: string;
  require_confirm?: boolean;
}): Promise<{
  task_id: string;
  status: string;
  message: string;
  user_homepage: string;
}> => {
  return request.post(`/tasks/${taskId}/outreach`, data);
};

// 执行触达任务
export const executeOutreachTask = (taskId: string, outreachId: string): Promise<{
  task_id: string;
  status: string;
  user_homepage: string;
  content: string;
  message: string;
}> => {
  return request.post(`/tasks/${taskId}/outreach/${outreachId}/execute`);
};

// 查询触达任务状态
export const getOutreachStatus = (taskId: string, outreachId: string): Promise<{
  task_id: string;
  status: string;
  steps: {
    step: number;
    name: string;
    status: string;
    message: string;
    screenshot?: string;
  }[];
  result: any;
  error_message: string;
  created_at: number;
  updated_at: number;
}> => {
  return request.get(`/tasks/${taskId}/outreach/${outreachId}/status`);
};

// 一键自动获客
export const startAutoOutreach = (taskId: string, data: {
  intent_level?: string;
  max_users?: number;
  tone?: string;
  auto_send?: boolean;
  interval_seconds?: number;
  method?: string;
}): Promise<{
  job_id: string;
  status: string;
  message: string;
  total_targets: number;
  targets: any[];
}> => {
  return request.post(`/tasks/${taskId}/auto-outreach`, data);
};

// 查询自动获客任务状态
export const getAutoOutreachStatus = (taskId: string, jobId: string): Promise<{
  job_id: string;
  task_id: string;
  status: string;
  total: number;
  completed: number;
  success: number;
  failed: number;
  results: any[];
  created_at: number;
}> => {
  return request.get(`/tasks/${taskId}/auto-outreach/${jobId}/status`);
};

// 获取所有自动获客任务列表
export const listAutoOutreachJobs = (taskId: string, limit: number = 20, offset: number = 0): Promise<{
  total: number;
  jobs: any[];
  running_count: number;
}> => {
  return request.get('/tasks/auto-outreach/jobs', { params: { task_id: taskId, limit, offset } });
};

// 获取自动获客全局统计
export const getAutoOutreachStats = (): Promise<{
  total_jobs: number;
  total_success: number;
  total_failed: number;
  total_targets: number;
  success_rate: number;
  today_jobs: number;
  today_success: number;
  today_failed: number;
  daily_stats: { date: string; success: number; failed: number }[];
  running_count: number;
  cooldown_remaining: number;
}> => {
  return request.get('/tasks/auto-outreach/stats');
};

// 取消自动获客任务
export const cancelAutoOutreachJob = (taskId: string, jobId: string): Promise<{
  success: boolean;
  message: string;
}> => {
  return request.post(`/tasks/${taskId}/auto-outreach/${jobId}/cancel`);
};

export const retryAutoOutreachJob = (taskId: string, jobId: string): Promise<{
  success: boolean;
  message: string;
  retry_count: number;
}> => {
  return request.post(`/tasks/${taskId}/auto-outreach/${jobId}/retry`);
};

// 获取单个获客任务的详细执行日志
export const getOutreachTaskLogs = (outreachTaskId: string): Promise<{
  id: string;
  nickname: string;
  user_id: string;
  platform: string;
  status: string;
  error_message: string | null;
  steps: { step: number; name: string; status: string; message: string; screenshot?: string }[];
  logs: string[];
  created_at: number;
  updated_at: number | null;
}> => {
  return request.get(`/tasks/outreach-task/${outreachTaskId}/logs`);
};

// 更新任务精准获客配置(从 getuser-canrun 迁移)
// 后端端点: PUT /tasks/{task_id}/lead-config
export const updateTaskLeadConfig = (taskId: string, data: {
  business_intent?: string;
  intent_keywords?: string[];
  exclude_keywords?: string[];
  target_role?: string;
  target_regions?: string[];
}): Promise<{
  success: boolean;
  message: string;
  business_intent: string;
  intent_keywords: string[];
  exclude_keywords: string[];
  target_role: string;
  target_regions: string[];
}> => {
  return request.put(`/tasks/${taskId}/lead-config`, data);
};
