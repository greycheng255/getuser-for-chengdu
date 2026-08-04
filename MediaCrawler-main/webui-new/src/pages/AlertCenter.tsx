import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Select, Row, Col, Statistic, Tooltip, Empty, Spin } from 'antd';
import {
  ReloadOutlined, CheckOutlined, BellOutlined, WarningOutlined,
  FireOutlined, AlertOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';
import { alertApi, hotpointAlertApi } from '../api/prdGap';

const { Option } = Select;

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red',
  high: 'volcano',
  medium: 'orange',
  low: 'gold',
  info: 'blue',
};

const SEVERITY_ICON: Record<string, React.ReactNode> = {
  critical: <AlertOutlined style={{ color: '#f5222d' }} />,
  high: <WarningOutlined style={{ color: '#fa541c' }} />,
  medium: <ExclamationCircleOutlined style={{ color: '#fa8c16' }} />,
  low: <BellOutlined style={{ color: '#faad14' }} />,
  info: <BellOutlined style={{ color: '#1677ff' }} />,
};

const TYPE_LABEL: Record<string, string> = {
  hot_breakout: '突发热点',
  account_anomaly: '账号异常',
  data_anomaly: '数据异常',
  content_anomaly: '内容异常',
};

const AlertCenter: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [unread, setUnread] = useState(0);
  const [filter, setFilter] = useState<{ alert_type?: string; severity?: string; status?: string }>({});
  const [alertStats, setAlertStats] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [listRes, unreadRes, statsRes] = await Promise.all([
        alertApi.list({ ...filter, limit: pageSize, offset: (page - 1) * pageSize }),
        alertApi.unreadCount().catch(() => ({ data: { count: 0 } })),
        hotpointAlertApi.stats().catch(() => ({ data: null })),
      ]);
      const data = listRes?.data || listRes || {};
      setItems(data.items || []);
      setTotal(data.total || 0);
      setUnread(unreadRes?.data?.count ?? unreadRes?.count ?? 0);
      setAlertStats(statsRes?.data || null);
    } catch (e) {
      console.error('fetch alerts failed', e);
      message.error('加载预警失败');
    } finally {
      setLoading(false);
    }
  }, [filter, page, pageSize]);

  useEffect(() => {
    fetchData();
    // 30 秒轮询
    const t = setInterval(fetchData, 30000);
    return () => clearInterval(t);
  }, [fetchData]);

  const handleMarkRead = async (id: string) => {
    try {
      await alertApi.markRead(id);
      message.success('已标记已读');
      fetchData();
    } catch {
      message.error('操作失败');
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await alertApi.markAllRead();
      message.success('全部已读');
      fetchData();
    } catch {
      message.error('操作失败');
    }
  };

  const columns = [
    {
      title: '级别',
      dataIndex: 'severity',
      width: 90,
      render: (v: string) => (
        <Tag color={SEVERITY_COLOR[v] || 'default'} icon={SEVERITY_ICON[v]}>
          {v}
        </Tag>
      ),
    },
    {
      title: '类型',
      dataIndex: 'alert_type',
      width: 110,
      render: (v: string) => TYPE_LABEL[v] || v,
    },
    {
      title: '标题',
      dataIndex: 'title',
      render: (v: string, r: any) => {
        // 帖子 URL：优先 metadata.post_url，其次 action_url（仅 http 外链）
        const postUrl =
          r.metadata?.post_url ||
          (r.action_url && /^https?:\/\//.test(r.action_url) ? r.action_url : '');
        return (
          <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
            <strong>{v}</strong>
            {r.content && (
              <div style={{ color: '#8c8c8c', fontSize: 12, marginTop: 4, whiteSpace: 'pre-wrap' }}>
                {r.content}
              </div>
            )}
            {postUrl && (
              <div style={{ marginTop: 4 }}>
                <a href={postUrl} target="_blank" rel="noreferrer" style={{ fontSize: 12, wordBreak: 'break-all' }}>
                  🔗 查看原帖内容
                </a>
              </div>
            )}
          </div>
        );
      },
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 140,
      render: (v: string) => v || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => (
        <Tag color={v === 'read' ? 'default' : 'processing'}>{v === 'read' ? '已读' : '未读'}</Tag>
      ),
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: any) => {
        if (!v) return '-';
        const d = typeof v === 'number' ? new Date(v > 1e12 ? v : v * 1000) : new Date(v);
        return d.toLocaleString('zh-CN');
      },
    },
    {
      title: '操作',
      width: 90,
      render: (_: any, r: any) =>
        r.status !== 'read' && (
          <Button size="small" type="link" icon={<CheckOutlined />} onClick={() => handleMarkRead(r.alert_id || r.id)}>
            已读
          </Button>
        ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <AlertOutlined style={{ color: '#f5222d', marginRight: 8 }} />
            预警中心
          </h3>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
            <Button icon={<CheckOutlined />} onClick={handleMarkAllRead}>全部已读</Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="未读预警" value={unread} valueStyle={{ color: '#f5222d' }} prefix={<BellOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="预警总数" value={total} prefix={<AlertOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="突发热点扫描"
              value={alertStats?.is_running ? '运行中' : '已停止'}
              valueStyle={{ color: alertStats?.is_running ? '#52c41a' : '#8c8c8c' }}
              prefix={<FireOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="已检测突发"
              value={alertStats?.total_detected ?? 0}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Select
            allowClear
            placeholder="预警类型"
            style={{ width: 150 }}
            value={filter.alert_type}
            onChange={(v) => { setFilter({ ...filter, alert_type: v }); setPage(1); }}
          >
            {Object.entries(TYPE_LABEL).map(([k, v]) => (
              <Option key={k} value={k}>{v}</Option>
            ))}
          </Select>
          <Select
            allowClear
            placeholder="级别"
            style={{ width: 120 }}
            value={filter.severity}
            onChange={(v) => { setFilter({ ...filter, severity: v }); setPage(1); }}
          >
            {['critical', 'high', 'medium', 'low', 'info'].map((k) => (
              <Option key={k} value={k}>{k}</Option>
            ))}
          </Select>
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120 }}
            value={filter.status}
            onChange={(v) => { setFilter({ ...filter, status: v }); setPage(1); }}
          >
            <Option value="unread">未读</Option>
            <Option value="read">已读</Option>
          </Select>
        </Space>

        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <Empty description="暂无预警" />
          ) : (
            <Table
              rowKey={(r) => r.alert_id || r.id}
              columns={columns}
              dataSource={items}
              pagination={{
                current: page,
                pageSize,
                total,
                showSizeChanger: true,
                onChange: (p, ps) => { setPage(p); setPageSize(ps); },
              }}
              size="middle"
              scroll={{ x: 900 }}
            />
          )}
        </Spin>
      </Card>
    </div>
  );
};

export default AlertCenter;
