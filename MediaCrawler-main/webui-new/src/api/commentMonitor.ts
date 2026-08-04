import request from './request';

// ============ 类型定义 ============

export interface CommentMonitorTask {
  task_id: string;
  platform: string;
  monitor_type: 'account' | 'video';
  target_id: string;
  target_nickname: string;
  keywords: string;
  enable_auto_reply: boolean;
  enable_lead_extract: boolean;
  check_interval: number;
  max_comments_per_check: number;
  status: 'pending' | 'running' | 'paused' | 'stopped' | 'error';
  last_check_at: number;
  last_check_new_count: number;
  last_error: string;
  owner_user_id: string;
  created_at: number;
  updated_at: number;
  is_running?: boolean;
}

export interface CommentMonitorRecord {
  id: number;
  task_id: string;
  platform: string;
  comment_id: string;
  comment_text: string;
  author_id: string;
  author_nickname: string;
  author_sec_uid: string;
  author_avatar: string;
  source_post_id: string;
  source_post_url: string;
  parent_comment_id: string;
  like_count: number;
  intent_type: string;
  lead_score: number;
  matched_keywords: string;
  is_replied: boolean;
  reply_content: string;
  converted_to_lead: boolean;
  lead_id: number;
  captured_at: number;
  created_at: number;
}

export interface TaskStats {
  task_id: string;
  total_comments: number;
  total_leads: number;
  total_replied: number;
  avg_lead_score: number;
  max_lead_score: number;
}

export interface ListResponse<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface PlatformInfo {
  platforms: string[];
  monitor_types: Array<{ value: string; label: string }>;
}

// ============ API 调用 ============

export const getPlatforms = (): Promise<PlatformInfo> => {
  return request.get('/comment-monitor/platforms');
};

export const createTask = (data: {
  platform: string;
  monitor_type: 'account' | 'video';
  target_id: string;
  target_nickname?: string;
  keywords?: string;
  enable_auto_reply?: boolean;
  enable_lead_extract?: boolean;
  check_interval?: number;
  max_comments_per_check?: number;
}): Promise<CommentMonitorTask> => {
  return request.post('/comment-monitor/tasks', data);
};

export const listTasks = (params: {
  platform?: string;
  monitor_type?: string;
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<ListResponse<CommentMonitorTask>> => {
  return request.get('/comment-monitor/tasks', { params });
};

export const getTask = (taskId: string): Promise<CommentMonitorTask> => {
  return request.get(`/comment-monitor/tasks/${taskId}`);
};

export const updateTask = (
  taskId: string,
  data: Partial<Pick<CommentMonitorTask,
    'target_nickname' | 'keywords' | 'enable_auto_reply' |
    'enable_lead_extract' | 'check_interval' | 'max_comments_per_check' | 'status'>>
): Promise<void> => {
  return request.put(`/comment-monitor/tasks/${taskId}`, data);
};

export const deleteTask = (taskId: string): Promise<void> => {
  return request.delete(`/comment-monitor/tasks/${taskId}`);
};

export const startTask = (taskId: string): Promise<void> => {
  return request.post(`/comment-monitor/tasks/${taskId}/start`);
};

export const stopTask = (taskId: string): Promise<void> => {
  return request.post(`/comment-monitor/tasks/${taskId}/stop`);
};

export const checkNow = (taskId: string): Promise<void> => {
  return request.post(`/comment-monitor/tasks/${taskId}/check-now`);
};

export const listRecords = (
  taskId: string,
  params: {
    only_lead?: boolean;
    min_score?: number;
    page?: number;
    page_size?: number;
  }
): Promise<ListResponse<CommentMonitorRecord>> => {
  return request.get(`/comment-monitor/tasks/${taskId}/records`, { params });
};

export const getTaskStats = (taskId: string): Promise<TaskStats> => {
  return request.get(`/comment-monitor/tasks/${taskId}/stats`);
};
