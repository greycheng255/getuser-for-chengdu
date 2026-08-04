import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Modal, Button, Space, Tag, Typography } from 'antd';
import { FireOutlined, ThunderboltOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { alertApi, hotpointAlertApi } from '../api/prdGap';

const { Text, Paragraph } = Typography;

interface BreakoutAlert {
  alert_id?: string;
  id?: string;
  title: string;
  description?: string;
  severity?: string;
  alert_type?: string;
  source?: string;
  hotspot_id?: string;
  post_url?: string;
}

/**
 * 突发热点弹窗组件（PRD 8.1 验收点：突发热点弹窗提醒 + 一键取材）
 *
 * 工作机制：
 * 1. 启动时轮询 /api/alerts?alert_type=hot_breakout&status=unread 获取未读突发热点
 * 2. 每 60 秒轮询一次
 * 3. 检测到新突发热点时弹出 Modal 提醒
 * 4. 提供「一键取材」按钮跳转到热点库管理 / X 获客工作台
 */
const HotpointAlertToast: React.FC = () => {
  const navigate = useNavigate();
  const [visible, setVisible] = useState(false);
  const [current, setCurrent] = useState<BreakoutAlert | null>(null);
  const [queue, setQueue] = useState<BreakoutAlert[]>([]);
  const seenIds = useRef<Set<string>>(new Set());
  const wsRef = useRef<WebSocket | null>(null);

  const showNext = useCallback(() => {
    setQueue((prev) => {
      if (prev.length === 0) {
        setVisible(false);
        setCurrent(null);
        return prev;
      }
      const [first, ...rest] = prev;
      setCurrent(first);
      setVisible(true);
      return rest;
    });
  }, []);

  const enqueue = useCallback((alerts: BreakoutAlert[]) => {
    const fresh = alerts.filter((a) => {
      const id = a.alert_id || a.id || a.title;
      return !seenIds.current.has(id);
    });
    if (fresh.length === 0) return;
    fresh.forEach((a) => seenIds.current.add(a.alert_id || a.id || a.title));
    setQueue((prev) => (prev.length === 0 && !visible ? prev.concat(fresh) : prev.concat(fresh)));
    if (!visible) {
      // 立即展示第一条
      setQueue((prev) => {
        if (prev.length === 0) return prev;
        const [first, ...rest] = prev;
        setCurrent(first);
        setVisible(true);
        return rest;
      });
    }
  }, [visible]);

  // 轮询获取突发热点预警
  useEffect(() => {
    const poll = async () => {
      try {
        const res = await alertApi.list({ alert_type: 'hot_breakout', status: 'unread', limit: 10 });
        const data = res?.data || res || {};
        const items: BreakoutAlert[] = data.items || [];
        if (items.length > 0) enqueue(items);
      } catch (e) {
        // 静默失败，不影响主流程
      }
    };
    poll();
    const t = setInterval(poll, 60000);
    return () => clearInterval(t);
  }, [enqueue]);

  // WebSocket 实时推送（可选，失败降级为轮询）
  useEffect(() => {
    let closed = false;
    try {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      const ws = new WebSocket(`${proto}//${host}/api/alerts/ws`);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === 'heartbeat') return;
          if (data.alert_type === 'hot_breakout' || data.alert_type === 'hot_breakout_alert') {
            enqueue([data]);
          }
        } catch {
          // ignore
        }
      };
      ws.onerror = () => { /* 降级为轮询 */ };
      return () => {
        closed = true;
        ws.close();
      };
    } catch {
      // WebSocket 不可用，依赖轮询
    }
    return () => {
      if (!closed && wsRef.current) wsRef.current.close();
    };
  }, [enqueue]);

  const handleTakeMaterial = useCallback(() => {
    if (!current) return;
    // 标记已读
    const id = current.alert_id || current.id;
    if (id) {
      alertApi.markRead(id).catch(() => {});
    }
    setVisible(false);
    // 一键取材：跳转到热点库管理（携带 hotspot_id 便于定位）
    const hotspotId = current.hotspot_id || '';
    if (hotspotId) {
      navigate(`/hotpoint-library?hotspot_id=${encodeURIComponent(hotspotId)}`);
    } else {
      navigate('/hotpoint-library');
    }
    message.success('已跳转热点库，可一键取材');
    // 展示下一条
    setTimeout(showNext, 300);
  }, [current, navigate, showNext]);

  const handleIgnore = useCallback(() => {
    const id = current?.alert_id || current?.id;
    if (id) {
      alertApi.markRead(id).catch(() => {});
    }
    setVisible(false);
    setTimeout(showNext, 300);
  }, [current, showNext]);

  return (
    <Modal
      open={visible}
      onCancel={handleIgnore}
      footer={null}
      width={480}
      closable={false}
      mask={{ closable: false }}
      styles={{ body: { padding: 24 } }}
      title={
        <Space>
          <ThunderboltOutlined style={{ color: '#f5222d' }} />
          <span style={{ color: '#f5222d' }}>突发热点预警</span>
        </Space>
      }
    >
      {current && (
        <div>
          <div style={{ marginBottom: 12 }}>
            <Tag color="red" icon={<FireOutlined />}>突发热点</Tag>
            {current.severity && <Tag color="volcano">{current.severity}</Tag>}
            {current.source && <Tag>{current.source}</Tag>}
          </div>
          <Paragraph style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
            {current.title}
          </Paragraph>
          {current.description && (
            <Paragraph type="secondary" style={{ marginBottom: 16, wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
              {current.description}
            </Paragraph>
          )}
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button onClick={handleIgnore}>稍后处理</Button>
            <Button type="primary" danger icon={<ArrowRightOutlined />} onClick={handleTakeMaterial}>
              一键取材
            </Button>
          </Space>
        </div>
      )}
    </Modal>
  );
};

export default HotpointAlertToast;
