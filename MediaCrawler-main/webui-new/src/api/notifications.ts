import request from './request';

export interface NotificationItem {
  id: number;
  title: string;
  content: string;
  msg_type: 'info' | 'success' | 'warning' | 'error' | 'lead' | 'task';
  extra: string;
  is_read: boolean;
  created_ts: number;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  total: number;
  unread_count: number;
}

/** 拉取站内消息列表 */
export const listNotifications = (params?: { limit?: number; offset?: number; unread_only?: boolean }) =>
  request.get<any, NotificationListResponse>('/notifications', { params });

/** 标记单条消息为已读 */
export const markNotificationRead = (notifId: number) =>
  request.post<any, { success: boolean }>(`/notifications/${notifId}/read`);

/** 全部标记已读 */
export const markAllNotificationsRead = () =>
  request.post<any, { success: boolean }>('/notifications/read-all');
