import request from './request';

export type AccountRole = 'publisher' | 'interactor' | 'both';
export type AccountStatus = 'active' | 'expired' | 'invalid' | 'needs_relogin' | 'cooldown' | 'disabled';

export interface UnifiedAccount {
  id: number;
  account_id: string;
  owner_user_id: string;
  platform: string;
  account_name: string;
  role: AccountRole;
  status: AccountStatus;
  auth_configured: boolean;
  auth_preview: Record<string, string>;
  capabilities: string[];
  group_name: string;
  region: string;
  priority: number;
  weight: number;
  health_score: number;
  daily_limit: number;
  today_count: number;
  success_count: number;
  failure_count: number;
  cooldown_until: number;
  in_cooldown: boolean;
  last_used_ts: number;
  created_ts: number;
  updated_ts: number;
}

export interface AccountListResponse {
  items: UnifiedAccount[];
  total: number;
  page: number;
  page_size: number;
}

export interface AccountFilters {
  platform?: string;
  role?: AccountRole;
  status?: AccountStatus;
  group_name?: string;
  page?: number;
  page_size?: number;
}

export interface AccountInput {
  account_id?: string;
  platform: string;
  account_name?: string;
  role?: AccountRole;
  status?: AccountStatus;
  auth_data?: Record<string, unknown>;
  capabilities?: string[];
  group_name?: string;
  region?: string;
  priority?: number;
  weight?: number;
  health_score?: number;
  daily_limit?: number;
}

export interface AccountBatchResponse {
  created: UnifiedAccount[];
  failed: Array<{ index: number; account_id?: string; platform?: string; error: string }>;
}

export const listAccounts = (filters: AccountFilters): Promise<AccountListResponse> =>
  request.get('/accounts', { params: filters }) as unknown as Promise<AccountListResponse>;

export const createAccount = (input: AccountInput): Promise<UnifiedAccount> =>
  request.post('/accounts', input, { sensitive: true, skipRetry: true }) as unknown as Promise<UnifiedAccount>;

export const batchCreateAccounts = (items: AccountInput[]): Promise<AccountBatchResponse> =>
  request.post('/accounts/batch', { items }, { sensitive: true, skipRetry: true }) as unknown as Promise<AccountBatchResponse>;

export const updateAccount = (accountId: string, input: Partial<AccountInput>): Promise<UnifiedAccount> =>
  request.put(`/accounts/${encodeURIComponent(accountId)}`, input, { sensitive: true, skipRetry: true }) as unknown as Promise<UnifiedAccount>;

export const disableAccount = (accountId: string): Promise<UnifiedAccount> =>
  request.delete(`/accounts/${encodeURIComponent(accountId)}`, { skipRetry: true }) as unknown as Promise<UnifiedAccount>;

export const resetAccountCooldown = (accountId: string): Promise<UnifiedAccount> =>
  request.post(`/accounts/${encodeURIComponent(accountId)}/reset-cooldown`, null, { skipRetry: true }) as unknown as Promise<UnifiedAccount>;

export const validateAccount = (accountId: string): Promise<{
  account_id: string;
  valid: boolean;
  mode: string;
  status: AccountStatus;
  message: string;
}> => request.post(`/accounts/${encodeURIComponent(accountId)}/validate`, null, { skipRetry: true }) as unknown as Promise<{
  account_id: string;
  valid: boolean;
  mode: string;
  status: AccountStatus;
  message: string;
}>;
