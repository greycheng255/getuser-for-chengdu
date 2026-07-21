/**
 * 套餐与计费 API(v6.6 商业化)
 */
import request from './request';

export interface PlanInfo {
  plan_type: string;
  plan_name: string;
  display_name: string;
  is_active: boolean;
  expires_ts: number;
  started_ts: number;
  balance: number; // 分
  total_spent: number; // 分
  // 配额
  max_tasks: number;
  max_notes_per_task: number;
  max_publish_time_type: number;
  min_comments_per_task: number;
  max_comments_per_task: number;
  // 用量
  usage_period_start_ts: number;
  usage_notes_count: number;
  usage_comments_count: number;
  usage_leads_count: number;
  // 价格
  price_monthly: number;
  price_yearly: number;
}

export interface PlanConfig {
  name: string;
  display_name: string;
  max_tasks: number;
  max_notes_per_task: number;
  max_publish_time_type: number;
  min_comments_per_task: number;
  max_comments_per_task: number;
  price_monthly: number;
  price_yearly: number;
  overage_note_price: number;
  overage_comment_price: number;
  overage_lead_price: number;
}

/** 获取套餐列表(公开) */
export async function listPlans(): Promise<{ plans: PlanConfig[] }> {
  return request.get<any, { plans: PlanConfig[] }>('/plans');
}

/** 获取当前用户套餐状态与用量 */
export async function getMyPlan(): Promise<{ success: boolean; plan: PlanInfo }> {
  return request.get<any, { success: boolean; plan: PlanInfo }>('/plans/me');
}

/** 套餐升级 */
export async function upgradePlan(plan_type: string, duration: 'monthly' | 'yearly'): Promise<any> {
  return request.post('/plans/upgrade', { plan_type, duration });
}

/** 余额充值 */
export async function rechargeBalance(amount_yuan: number): Promise<any> {
  return request.post('/plans/recharge', { amount_yuan });
}

/** 管理员:所有用户套餐概览 */
export async function listUsersPlans(): Promise<any> {
  return request.get('/plans/users');
}

/** 管理员:调整用户套餐 */
export async function adminUpdateUserPlan(user_id: number, data: {
  plan_type?: string;
  plan_expires_ts?: number;
  balance?: number;
  reset_usage?: boolean;
}): Promise<any> {
  return request.put(`/plans/users/${user_id}`, data);
}
