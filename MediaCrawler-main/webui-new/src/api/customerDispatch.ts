import request from './request';

// ============ 类型定义（与后端 service 返回值对齐） ============

export interface AccountConfig {
  account_alias: string;
  cookie_id: string;
  batch_size: number;
}

export interface DispatchAccount {
  account_idx: number;
  account_alias: string;
  cookie_id: string;
  range_start: number;
  range_end: number;
  batch_size: number;
  total_assigned: number;
  total_sent: number;
  total_replied: number;
  status: string;
  created_at: number;
  updated_at: number;
}

export interface PlanProgress {
  total: number;
  pending: number;
  sent_unreplied: number;
  replied: number;
  active_accounts: number;
  coverage_pct: number;
  remaining: number;
}

export interface DispatchPlan {
  plan_id: string;
  name: string;
  platform: string;
  total_customers: number;
  total_accounts: number;
  filter_keywords: string;
  min_lead_score: number;
  status: string;
  owner_user_id: string;
  created_at: number;
  updated_at: number;
  // 合并自 get_plan_progress
  total?: number;
  pending?: number;
  sent_unreplied?: number;
  replied?: number;
  active_accounts?: number;
  coverage_pct?: number;
  remaining?: number;
  // 合并自 list_accounts
  accounts?: DispatchAccount[];
}

export interface DispatchCustomer {
  id: number;
  nickname: string;
  platform: string;
  content: string;
  url: string;
  lead_score: number;
  profile_url: string;
  comment_url: string;
  intent_type: string;
}

export interface NextBatchResponse {
  ok: boolean;
  plan_id: string;
  account_idx: number;
  batch_size?: number;
  customers: DispatchCustomer[];
  customer_lead_ids?: number[];
  seqs: number[];
  own_count?: number;
  leaked_count?: number;
  message?: string;
  reason?: string;
}

export interface DispatchRecord {
  id: number;
  plan_id: string;
  customer_lead_id: number;
  customer_seq: number;
  assigned_account_idx: number;
  status: 'pending' | 'sent' | 'replied' | 'skipped';
  sent_by_account: number | null;
  replied_by_account: number | null;
  sent_at: number;
  replied_at: number;
  contact_log: string;
  created_at: number;
  updated_at: number;
  customer_nickname: string;
  customer_platform: string;
  customer_content: string;
  customer_url: string;
  customer_lead_score: number;
  customer_profile_url: string;
  customer_comment_url: string;
  customer_intent_type: string;
}

export interface ListResponse<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

// ============ API 调用 ============

export const previewCustomers = (params: {
  platform?: string;
  filter_keywords?: string;
  min_lead_score?: number;
}): Promise<{ total: number; sample: unknown[] }> => {
  return request.get('/customer-dispatch/preview-customers', { params });
};

export const createPlan = (data: {
  name: string;
  platform: string;
  filter_keywords?: string;
  min_lead_score?: number;
  accounts: AccountConfig[];
  customer_lead_ids?: number[];
}): Promise<DispatchPlan> => {
  return request.post('/customer-dispatch/plans', data);
};

export const listPlans = (params: {
  page?: number;
  page_size?: number;
} = {}): Promise<ListResponse<DispatchPlan>> => {
  return request.get('/customer-dispatch/plans', { params });
};

export const getPlan = (planId: string): Promise<DispatchPlan> => {
  return request.get(`/customer-dispatch/plans/${planId}`);
};

export const deletePlan = (planId: string): Promise<void> => {
  return request.delete(`/customer-dispatch/plans/${planId}`);
};

export const listAccounts = (planId: string): Promise<DispatchAccount[]> => {
  return request.get(`/customer-dispatch/plans/${planId}/accounts`);
};

export const listRecords = (
  planId: string,
  params: {
    account_idx?: number;
    status?: string;
    page?: number;
    page_size?: number;
  } = {}
): Promise<ListResponse<DispatchRecord>> => {
  return request.get(`/customer-dispatch/plans/${planId}/records`, { params });
};

export const getNext = (
  planId: string,
  data: { account_idx: number; batch_size?: number }
): Promise<NextBatchResponse> => {
  return request.post(`/customer-dispatch/plans/${planId}/next`, data);
};

export const markReplied = (
  planId: string,
  data: { customer_lead_id: number; account_idx: number; contact_log?: string }
): Promise<{ success: boolean; message: string }> => {
  return request.post(`/customer-dispatch/plans/${planId}/mark-replied`, data);
};

export const batchMarkReplied = (
  planId: string,
  data: { customer_lead_ids: number[]; account_idx: number }
): Promise<{ success: number; total: number; failed: number }> => {
  return request.post(`/customer-dispatch/plans/${planId}/batch-mark`, data);
};

export const getProgress = (planId: string): Promise<PlanProgress> => {
  return request.get(`/customer-dispatch/plans/${planId}/progress`);
};
