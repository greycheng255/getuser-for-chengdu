import React, { useEffect, useState, useCallback, useRef } from 'react';
import { notification as antdNotification, Badge, Button, List, Empty } from 'antd';
import { CheckCircleOutlined, InfoCircleOutlined, WarningOutlined, CloseCircleOutlined } from '@ant-design/icons';
import { listNotifications, markNotificationRead, markAllNotificationsRead, type NotificationItem } from '../api/notifications';
import { authStorage } from '../api/auth';

export interface NoticeItem {
  id: string;
  title: string;
  message: string;
  type: 'success' | 'info' | 'warning' | 'error';
  timestamp: number;
  read: boolean;
  // 附加字段，用于跳转等
  extra?: any;
}

// 后端 msg_type → 前端 type 映射
const mapMsgType = (msgType: string): NoticeItem['type'] => {
  switch (msgType) {
    case 'success': return 'success';
    case 'warning': return 'warning';
    case 'error': return 'error';
    default: return 'info';
  }
};

// 后端 NotificationItem → 前端 NoticeItem
const toNoticeItem = (n: NotificationItem): NoticeItem => ({
  id: String(n.id),
  title: n.title,
  message: n.content,
  type: mapMsgType(n.msg_type),
  timestamp: n.created_ts * 1000,
  read: n.is_read,
  extra: (() => { try { return JSON.parse(n.extra || '{}'); } catch { return {}; } })(),
});

const STORAGE_KEY = 'global_notices';

export const useNotices = () => {
  const [notices, setNotices] = useState<NoticeItem[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });
  const [unreadCount, setUnreadCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notices.slice(0, 50)));
  }, [notices]);

  // 从后端拉取通知（合并到本地列表）
  const refreshFromServer = useCallback(async () => {
    try {
      const resp = await listNotifications({ limit: 50, unread_only: false });
      if (resp && resp.items) {
        const serverNotices = resp.items.map(toNoticeItem);
        // 合并：以服务端为准（去重），保留本地未同步的临时通知
        setNotices(prev => {
          const serverIds = new Set(serverNotices.map(n => n.id));
          const localOnly = prev.filter(n => !serverIds.has(n.id) && n.id.startsWith('notice_'));
          // 服务端在前，本地临时通知在后
          return [...serverNotices, ...localOnly].slice(0, 50);
        });
        setUnreadCount(resp.unread_count || 0);
      }
    } catch (e) {
      // 静默失败，不打扰用户
    }
  }, []);

  // 初始化：拉取一次 + 建立 WebSocket 连接 + 定时轮询兜底
  useEffect(() => {
    const token = authStorage.getToken();
    if (!token) return;

    // 首次拉取
    refreshFromServer();

    // 建立 WebSocket 实时通知连接
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/ws/notifications?token=${encodeURIComponent(token)}`;
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'notification') {
            // 实时推送的通知：加入列表 + 弹出提醒
            const newNotice: NoticeItem = {
              id: `ws_${data.ts}_${Math.random().toString(36).slice(2)}`,
              title: data.title,
              message: data.content,
              type: mapMsgType(data.msg_type),
              timestamp: data.ts,
              read: false,
              extra: data.extra || {},
            };
            setNotices(prev => [newNotice, ...prev].slice(0, 50));
            setUnreadCount(c => c + 1);

            // 弹出浏览器通知
            antdNotification[newNotice.type]({
              message: newNotice.title,
              description: newNotice.message,
              placement: 'topRight',
              duration: 6,
            });

            // 拉取一次服务端，同步持久化的通知（确保已读状态一致）
            setTimeout(refreshFromServer, 1000);
          }
        } catch {
          // ignore parse error
        }
      };
      // 心跳保活
      const heartbeat = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 25000);
      ws.onclose = () => clearInterval(heartbeat);
    } catch {
      // WebSocket 建立失败，降级到轮询
    }

    // 轮询兜底（每 60 秒拉取一次，防止 WebSocket 断连漏消息）
    pollTimerRef.current = setInterval(refreshFromServer, 60000);

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [refreshFromServer]);

  const addNotice = useCallback((notice: Omit<NoticeItem, 'id' | 'timestamp' | 'read'>) => {
    const item: NoticeItem = {
      ...notice,
      id: `notice_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      timestamp: Date.now(),
      read: false,
    };
    setNotices(prev => [item, ...prev]);
    setUnreadCount(c => c + 1);

    antdNotification[notice.type]({
      message: notice.title,
      description: notice.message,
      placement: 'topRight',
      duration: 4,
    });
  }, []);

  const markRead = useCallback((id: string) => {
    setNotices(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
    setUnreadCount(c => Math.max(0, c - 1));
    // 同步到服务端（仅对服务端返回的通知）
    if (!id.startsWith('notice_') && !id.startsWith('ws_')) {
      const numId = parseInt(id, 10);
      if (!isNaN(numId)) {
        markNotificationRead(numId).catch(() => {});
      }
    }
  }, []);

  const markAllRead = useCallback(() => {
    setNotices(prev => prev.map(n => ({ ...n, read: true })));
    setUnreadCount(0);
    markAllNotificationsRead().catch(() => {});
  }, []);

  const clearNotices = useCallback(() => {
    setNotices([]);
    setUnreadCount(0);
  }, []);

  return { notices, unreadCount, addNotice, markRead, markAllRead, clearNotices, refreshFromServer };
};

export const NoticeList: React.FC<{
  notices: NoticeItem[];
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
  onClear: () => void;
}> = ({ notices, onMarkRead, onMarkAllRead, onClear }) => {
  const typeConfig: Record<string, { icon: React.ReactNode; color: string }> = {
    success: { icon: <CheckCircleOutlined />, color: 'green' },
    info: { icon: <InfoCircleOutlined />, color: 'blue' },
    warning: { icon: <WarningOutlined />, color: 'orange' },
    error: { icon: <CloseCircleOutlined />, color: 'red' },
  };

  return (
    <div style={{ width: 360 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 16px', borderBottom: '1px solid #f0f0f0' }}>
        <span style={{ fontWeight: 500 }}>通知中心</span>
        <div>
          <Button type="link" size="small" onClick={onMarkAllRead}>全部已读</Button>
          <Button type="link" size="small" danger onClick={onClear}>清空</Button>
        </div>
      </div>
      {notices.length > 0 ? (
        <List
          size="small"
          dataSource={notices.slice(0, 20)}
          renderItem={item => {
            const config = typeConfig[item.type] || typeConfig.info;
            return (
              <List.Item
                style={{
                  padding: '8px 16px',
                  cursor: 'pointer',
                  background: item.read ? 'transparent' : '#e6f7ff',
                  opacity: item.read ? 0.7 : 1,
                }}
                onClick={() => onMarkRead(item.id)}
              >
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', width: '100%' }}>
                  <span style={{ color: config.color, marginTop: 2 }}>{config.icon}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: item.read ? 'normal' : 500, fontSize: 13 }}>{item.title}</div>
                    <div style={{ color: '#999', fontSize: 12, marginTop: 2, whiteSpace: 'pre-wrap' }}>{item.message}</div>
                    <div style={{ color: '#bbb', fontSize: 11, marginTop: 2 }}>
                      {new Date(item.timestamp).toLocaleString()}
                    </div>
                  </div>
                  {!item.read && <Badge status="processing" />}
                </div>
              </List.Item>
            );
          }}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" style={{ padding: 24 }} />
      )}
    </div>
  );
};
