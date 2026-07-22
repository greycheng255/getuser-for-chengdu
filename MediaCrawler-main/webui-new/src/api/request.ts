import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { shouldRetryRequest } from './retryPolicy.js';

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 计费/非幂等 POST 可禁止拦截器自动重试。 */
    skipRetry?: boolean;
  }

  export interface InternalAxiosRequestConfig {
    skipRetry?: boolean;
  }
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

const request = axios.create({
  baseURL: BASE_URL,
  timeout: 180000,
  headers: {
    'Content-Type': 'application/json',
  },
});

const RETRY_DELAY = 1000;

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// 请求拦截器：添加token
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器：重试逻辑 + 错误处理
request.interceptors.response.use(
  (response) => response.data,
  async (error: AxiosError) => {
    const config = error.config as InternalAxiosRequestConfig & { retryCount?: number };
    
    if (!config) {
      return Promise.reject(error);
    }

    config.retryCount = config.retryCount || 0;

    if (shouldRetryRequest({
      skipRetry: config.skipRetry,
      retryCount: config.retryCount,
      hasResponse: Boolean(error.response),
      status: error.response?.status,
    })) {
      config.retryCount++;
      console.warn(`请求失败，第 ${config.retryCount} 次重试...`, config.url);
      await sleep(RETRY_DELAY * config.retryCount);
      return request(config);
    }

    // 最终错误处理
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('user_info');
      window.location.href = '/login';
    }

    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

export default request;
