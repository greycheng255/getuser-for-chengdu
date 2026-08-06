import request from './request';

export interface CookieStatus {
  name: string;
  platform: string;
  has_cookie: boolean;
  cookie_length: number;
  status: string;
  check_field: string;
}

export interface CookieCheckResult {
  valid: boolean;
  message: string;
  platform: string;
  check_field?: string;
  has_key_field?: boolean;
}

export interface CookieTestResult {
  success: boolean;
  logged_in?: boolean;
  message: string;
  platform: string;
  indicators?: string[];
}

export const getCookies = (): Promise<Record<string, CookieStatus>> => {
  return request.get('/cookies');
};

export const updateCookie = (platform: string, cookies: string): Promise<{ success: boolean; message: string; platform: string; cookie_length: number }> => {
  return request.post('/cookies/update', { platform, cookies });
};

export const checkCookie = (platform: string): Promise<CookieCheckResult> => {
  return request.get(`/cookies/check/${platform}`);
};

export const testCookie = (platform: string): Promise<CookieTestResult> => {
  return request.post(`/cookies/test/${platform}`);
};

export interface CookieParseResult {
  success: boolean;
  platform: string;
  original_length: number;
  parsed_length: number;
  formatted_length: number;
  cookie_keys: string[];
  cookie_preview: Record<string, string>;
  formatted_cookie: string;
  has_login_field: boolean;
  check_field: string;
  missing_fields: string[];
  required_fields: string[];
  login_tip: string;
}

export const parseCookie = (platform: string, cookies: string): Promise<CookieParseResult> => {
  return request.post('/cookies/parse', { platform, cookies });
};

// ============================================================
// Cookie 池管理 API（多Cookie支持）
// ============================================================
export interface CookiePoolItem {
  index: number;
  cookie_length: number;
  cookie_preview: string;
  has_session: boolean;
  is_valid?: boolean;
}

export interface CookiePoolStatus {
  platform: string;
  pool_size: number;
  valid_count?: number;
  invalid_count?: number;
  cookies: CookiePoolItem[];
}

export const getCookiePool = (platform?: string): Promise<CookiePoolStatus | Record<string, CookiePoolStatus>> => {
  return request.get('/cookies/pool', { params: platform ? { platform } : {} });
};

export const addCookieToPool = (platform: string, cookie: string, alias?: string, phone?: string, email?: string): Promise<{
  success: boolean;
  message: string;
  pool_size?: number;
  session_valid?: boolean;
  missing_fields?: string[];
  hint?: string;
}> => {
  return request.post('/cookies/pool/add', null, { params: { platform, cookie, alias: alias || '', phone: phone || '', email: email || '' } });
};

export const removeCookieFromPool = (platform: string, cookie: string, cookieId?: number): Promise<{ success: boolean; message: string; pool_size: number }> => {
  return request.post('/cookies/pool/remove', null, { params: cookieId != null ? { platform, cookie_id: cookieId } : { platform, cookie } });
};

export const clearCookiePool = (platform: string): Promise<{ success: boolean; message: string }> => {
  return request.post('/cookies/pool/clear', null, { params: { platform } });
};

export const clearInvalidCookies = (platform: string): Promise<{ success: boolean; message: string; removed: number; remaining: number }> => {
  return request.post('/cookies/pool/clear-invalid', null, { params: { platform } });
};

// ============================================================
// 账号池管理 API（多Cookie+多IP组合管理）
// ============================================================
export interface AccountItem {
  account_id: string;
  alias: string;
  status: string;  // healthy / cooldown / banned / dead
  cookie_status: string;  // valid / invalid / expired / cooldown / unknown
  cookie_missing_fields: string[];
  health_score: number;
  fail_count: number;
  success_count: number;
  total_requests: number;
  total_fails: number;
  cooldown_remaining: number;
  cooldown_reason: string;
  last_used_at: number;
  has_cookie: boolean;
  proxy_ip: string;
  network_interface: string;  // 网卡名: eth0/eth1/eth2
  public_ip: string;          // 绑定的公网IP
  ip_blocked: boolean;        // 当前绑定的IP是否被block
}

export interface BadIpInfo {
  key: string;
  interface: string;
  ip: string;
  marked_at: number;
  remaining_ttl: number;
}

export interface IpHealthInfo {
  ip: string;
  status: string;  // healthy / blocked / unknown
  remaining_ttl: number;
}

export interface AccountPoolStatus {
  platform: string;
  total: number;
  healthy: number;
  cooldown: number;
  dead: number;
  bad_ips: number;
  bad_ip_list: BadIpInfo[];
  ip_health: Record<string, IpHealthInfo>;
  current_account: string | null;
  accounts: AccountItem[];
  network_interfaces: Record<string, string>;  // 网卡名 → 公网IP
}

export interface HealthCheckResult {
  platform: string;
  checked_at: number;
  accounts_checked: number;
  ips_checked: number;
  cookie_results: Array<{
    account_id: string;
    alias: string;
    cookie_status: string;
    has_required_fields: boolean;
    missing_fields: string[];
    check_field: string;
    runtime_status: string;
    health_score: number;
    fail_count: number;
    login_check?: { valid: boolean; status: string; detail: string; page_title: string } | null;
  }>;
  ip_results: Record<string, {
    ip: string;
    status: string;  // healthy / blocked / unknown
    marked_bad: boolean;
    remaining_ttl?: number;
    error?: string;
    last_checked: number;
  }>;
  summary: {
    cookie_valid: number;
    cookie_invalid: number;
    cookie_expired: number;
    ip_healthy: number;
    ip_blocked: number;
  };
}

export const getAccounts = (platform: string = 'dy'): Promise<AccountPoolStatus> => {
  return request.get('/cookies/accounts', { params: { platform } });
};

export const refreshAccounts = (platform: string = 'dy'): Promise<{ success: boolean; message: string; total: number; network_interfaces: Record<string, string> }> => {
  return request.post('/cookies/accounts/refresh', null, { params: { platform } });
};

export const clearBadIps = (platform: string = 'dy'): Promise<{ success: boolean; message: string }> => {
  return request.post('/cookies/accounts/clear-bad-ips', null, { params: { platform } });
};

export const checkAccountHealth = (platform: string = 'dy'): Promise<HealthCheckResult> => {
  return request.post('/cookies/accounts/check-health', null, { params: { platform } });
};
