// 商业化API接口 - 线索分包销售、API对接、销售团队协作
import request from './request';

// ==================== 业务用户 ====================

export interface BusinessUser {
  id: string;
  username: string;
  nickname: string;
  role: string; // customer/sales/admin
  company_name: string;
  contact_phone: string;
  contact_email: string;
  balance: number; // 余额(分)
  total_spent: number; // 累计消费(分)
  status: string;
  sales_region: string;
  sales_quota: number;
  webhook_url: string;
  api_key: string;
  auto_push: boolean;
  assigned_leads_count: number;
  converted_leads_count: number;
  created_ts: number;
  last_login_ts: number;
}

export interface CreateBusinessUserParams {
  username: string;
  password: string;
  nickname: string;
  role?: string;
  company_name?: string;
  contact_phone?: string;
  contact_email?: string;
  sales_region?: string;
  sales_quota?: number;
  webhook_url?: string;
  auto_push?: boolean;
}

export interface UpdateBusinessUserParams {
  nickname?: string;
  company_name?: string;
  contact_phone?: string;
  contact_email?: string;
  sales_region?: string;
  sales_quota?: number;
  webhook_url?: string;
  auto_push?: boolean;
  status?: string;
}

// 创建业务用户
export const createBusinessUser = (data: CreateBusinessUserParams): Promise<BusinessUser> => {
  return request.post('/business/users', data);
};

// 获取业务用户列表
export const getBusinessUsers = (params?: {
  role?: string;
  status?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<{ total: number; items: BusinessUser[]; page: number; page_size: number }> => {
  return request.get('/business/users', { params });
};

// 获取业务用户详情
export const getBusinessUser = (userId: string): Promise<BusinessUser> => {
  return request.get(`/business/users/${userId}`);
};

// 更新业务用户
export const updateBusinessUser = (userId: string, data: UpdateBusinessUserParams): Promise<BusinessUser> => {
  return request.patch(`/business/users/${userId}`, data);
};

// 充值
export const rechargeUserBalance = (userId: string, amount: number): Promise<{ success: boolean; balance: number }> => {
  return request.post(`/business/users/${userId}/recharge`, null, { params: { amount } });
};

// 重置API密钥
export const resetUserApiKey = (userId: string): Promise<{ success: boolean; api_key: string }> => {
  return request.post(`/business/users/${userId}/reset-api-key`);
};

// ==================== 线索包 ====================

export interface LeadPackage {
  id: string;
  name: string;
  description: string;
  platform: string;
  task_id: string;
  min_score: number;
  max_score: number;
  level: string;
  ip_location: string;
  total_count: number;
  available_count: number;
  sold_count: number;
  price_per_lead: number; // 单价(分)
  total_price: number; // 总价(分)
  expire_days: number;
  status: string; // draft/active/sold_out/discontinued
  created_ts: number;
  publish_ts: number;
}

export interface CreateLeadPackageParams {
  name: string;
  description?: string;
  platform?: string;
  task_id?: string;
  min_score?: number;
  max_score?: number;
  level?: string;
  ip_location?: string;
  keyword?: string;
  price_per_lead: number;
  expire_days?: number;
}

export interface UpdateLeadPackageParams {
  name?: string;
  description?: string;
  price_per_lead?: number;
  expire_days?: number;
  status?: string;
}

// 创建线索包
export const createLeadPackage = (data: CreateLeadPackageParams): Promise<LeadPackage> => {
  return request.post('/business/packages', data);
};

// 更新线索包
export const updateLeadPackage = (packageId: string, data: Partial<CreateLeadPackageParams>): Promise<LeadPackage> => {
  return request.put(`/business/packages/${packageId}`, data);
};

// 获取线索包列表
export const getLeadPackages = (params?: {
  status?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<{ total: number; items: LeadPackage[]; page: number; page_size: number }> => {
  return request.get('/business/packages', { params });
};

// 发布线索包
export const publishLeadPackage = (packageId: string): Promise<{ success: boolean; status: string }> => {
  return request.post(`/business/packages/${packageId}/publish`);
};

// 下架线索包
export const discontinueLeadPackage = (packageId: string): Promise<{ success: boolean }> => {
  return request.post(`/business/packages/${packageId}/discontinue`);
};

// 删除线索包
export const deleteLeadPackage = (packageId: string): Promise<{ success: boolean }> => {
  return request.delete(`/business/packages/${packageId}`);
};

// ==================== 购买流程 ====================

export interface PurchaseParams {
  package_id: string;
  lead_count: number;
  payment_method?: string; // balance/offline
}

export interface PurchaseResult {
  success: boolean;
  order_id: string;
  assigned_count: number;
  total_price: number;
  expire_ts: number;
}

// 购买线索包
export const purchaseLeadPackage = (data: PurchaseParams): Promise<PurchaseResult> => {
  return request.post('/business/purchase', data);
};

// ==================== 线索分配 ====================

export interface AssignLeadsParams {
  lead_ids: number[];
  business_user_id: string;
  expire_days?: number;
}

export interface AssignedLead {
  assignment_id: number;
  lead_id: number;
  nickname: string;
  content: string;
  lead_score: number;
  ip_location: string;
  platform: string;
  status: string;
  assigned_ts: number;
  expire_ts: number;
  business_user_id: string;
}

// 手动分配线索
export const assignLeads = (data: AssignLeadsParams): Promise<{ success: boolean; assigned_count: number }> => {
  return request.post('/business/assign', data);
};

// 获取已分配线索列表
export const getAssignedLeads = (params?: {
  business_user_id?: string;
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<{ total: number; items: AssignedLead[]; page: number; page_size: number }> => {
  return request.get('/business/assigned-leads', { params });
};

// ==================== 跟进记录 ====================

export interface FollowUpRecord {
  id: number;
  lead_id: number;
  business_user_id: string;
  action_type: string; // call/message/visit/wechat
  action_ts: number;
  result: string; // pending/contacted/interested/not_interested/converted/failed
  notes: string;
  next_follow_ts: number;
  created_ts: number;
}

export interface CreateFollowUpParams {
  lead_id: number;
  action_type: string;
  result: string;
  notes?: string;
  next_follow_ts?: number;
}

// 创建跟进记录
export const createFollowUp = (data: CreateFollowUpParams): Promise<FollowUpRecord> => {
  return request.post('/business/follow-ups', data);
};

// 获取跟进记录列表
export const getFollowUps = (params?: {
  lead_id?: number;
  business_user_id?: string;
  page?: number;
  page_size?: number;
}): Promise<{ total: number; items: FollowUpRecord[]; page: number; page_size: number }> => {
  return request.get('/business/follow-ups', { params });
};

// ==================== API客户端 ====================

export interface ApiClient {
  id: string;
  name: string;
  business_user_id: string;
  api_key: string;
  webhook_url: string;
  callback_url: string;
  filters: Record<string, any>;
  push_mode: string; // batch/realtime
  push_interval: number;
  status: string;
  last_push_ts: number;
  total_pushed: number;
  created_ts: number;
}

export interface CreateApiClientParams {
  name: string;
  business_user_id?: string;
  webhook_url?: string;
  callback_url?: string;
  filters?: Record<string, any>;
  push_mode?: string;
  push_interval?: number;
}

// 创建API客户端
export const createApiClient = (data: CreateApiClientParams): Promise<ApiClient> => {
  return request.post('/business/api-clients', data);
};

// 更新API客户端
export const updateApiClient = (clientId: string, data: CreateApiClientParams): Promise<ApiClient> => {
  return request.put(`/business/api-clients/${clientId}`, data);
};

// 切换API客户端状态
export const toggleApiClientStatus = (clientId: string): Promise<{ success: boolean; status: string }> => {
  return request.post(`/business/api-clients/${clientId}/toggle`);
};

// 获取API客户端列表
export const getApiClients = (params?: {
  page?: number;
  page_size?: number;
}): Promise<{ total: number; items: ApiClient[]; page: number; page_size: number }> => {
  return request.get('/business/api-clients', { params });
};

// 手动触发推送
export const triggerPushToClient = (clientId: string, limit?: number): Promise<{
  success: boolean;
  pushed_count: number;
  message: string;
}> => {
  return request.post(`/business/api-clients/${clientId}/push`, null, { params: { limit } });
};

// ==================== 统计 ====================

export interface BusinessStats {
  total_customers: number;
  total_sales: number;
  total_packages: number;
  total_leads_assigned: number;
  total_revenue: number;
  total_orders: number;
}

// 获取商业化统计
export const getBusinessStats = (): Promise<BusinessStats> => {
  return request.get('/business/stats');
};