import request from './request';

export interface UserInfo {
  id: number;
  username: string;
  nickname: string;
  email: string;
  role: 'admin' | 'operator' | 'viewer';
  status: 'active' | 'disabled';
  created_ts?: number;
  last_login_ts?: number;
}

export interface LoginResponse {
  token: string;
  user: UserInfo;
  message?: string;
}

export interface LoginParams {
  username: string;
  password: string;
}

export interface RegisterParams {
  username: string;
  password: string;
  nickname?: string;
  email?: string;
}

export interface CreateUserParams {
  username: string;
  password: string;
  nickname?: string;
  email?: string;
  role?: 'admin' | 'operator' | 'viewer';
}

export interface UpdateUserParams {
  nickname?: string;
  email?: string;
  role?: 'admin' | 'operator' | 'viewer';
  status?: 'active' | 'disabled';
  password?: string;
}

/** 登录 */
export const login = (data: LoginParams) =>
  request.post<any, LoginResponse>('/auth/login', data);

/** 注册(首个用户自动成为管理员) */
export const register = (data: RegisterParams) =>
  request.post<any, LoginResponse>('/auth/register', data);

/** 获取当前用户信息 */
export const getMe = () =>
  request.get<any, { user: UserInfo }>('/auth/me');

/** 校验 token 是否有效 */
export const checkAuth = () =>
  request.get<any, { valid: boolean; user: UserInfo }>('/auth/check');

/** 修改自己的密码 */
export const changePassword = (old_password: string, new_password: string) =>
  request.post<any, { message: string }>('/auth/change-password', { old_password, new_password });

/** 获取用户列表(管理员) */
export const listUsers = () =>
  request.get<any, { users: UserInfo[]; total: number }>('/auth/users');

/** 创建用户(管理员) */
export const createUser = (data: CreateUserParams) =>
  request.post<any, { user: UserInfo; message: string }>('/auth/users', data);

/** 更新用户(管理员) */
export const updateUser = (userId: number, data: UpdateUserParams) =>
  request.put<any, { user: UserInfo; message: string }>(`/auth/users/${userId}`, data);

/** 删除用户(管理员) */
export const deleteUser = (userId: number) =>
  request.delete<any, { message: string }>(`/auth/users/${userId}`);

/** 本地存储工具 */
export const authStorage = {
  getToken: () => localStorage.getItem('auth_token'),
  setToken: (token: string) => localStorage.setItem('auth_token', token),
  getUser: (): UserInfo | null => {
    const raw = localStorage.getItem('user_info');
    if (!raw) return null;
    try {
      return JSON.parse(raw) as UserInfo;
    } catch {
      return null;
    }
  },
  setUser: (user: UserInfo) => localStorage.setItem('user_info', JSON.stringify(user)),
  clear: () => {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user_info');
  },
};
