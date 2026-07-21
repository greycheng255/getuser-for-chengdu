import React, { useEffect, useState, useCallback } from 'react';
import {
  Spin,
  Alert,
  Row,
  Col,
  Card,
  Statistic,
  Button,
  Space,
  Table,
  Tag,
  Empty,
  Modal,
  Input,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ReloadOutlined,
  ThunderboltOutlined,
  UndoOutlined,
  PlusOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import {
  xWorkbenchApi,
  type CookiePoolStatus,
  type CookiePoolItem,
} from '../../api/xWorkbench';

const { TextArea } = Input;
const { Text } = Typography;

/**
 * Cookie 号池管理面板
 * 展示 Cookie 池状态 + 添加/移除/重置/测试操作
 */
const CookiePoolPanel: React.FC = () => {
  const [status, setStatus] = useState<CookiePoolStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [newCookie, setNewCookie] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const r = await xWorkbenchApi.cookiePoolStatus();
      setStatus(r);
    } catch (e: any) {
      message.error('加载 Cookie 池状态失败: ' + (e?.message || ''));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(true);
    // 轮询时不显示 loading,避免 Spin 每 5 秒闪烁
    const t = setInterval(() => load(false), 5000);
    return () => clearInterval(t);
  }, [load]);

  const handleAdd = useCallback(async () => {
    if (!newCookie.trim()) {
      message.warning('请输入 Cookie 字符串');
      return;
    }
    if (!newCookie.includes('auth_token') || !newCookie.includes('ct0')) {
      message.warning('Cookie 必须包含 auth_token 和 ct0 字段');
      return;
    }
    setSubmitting(true);
    try {
      const r = await xWorkbenchApi.cookiePoolAdd(newCookie.trim());
      if (r.success) {
        message.success(r.message);
        setNewCookie('');
        setAddModalOpen(false);
        load();
      } else {
        message.warning(r.message);
      }
    } catch (e: any) {
      message.error('添加失败: ' + (e?.message || ''));
    } finally {
      setSubmitting(false);
    }
  }, [newCookie, load]);

  const handleRemove = useCallback(async (label: string, preview: string) => {
    Modal.confirm({
      title: '确认移除 Cookie',
      content: `将从池中移除 ${label}（${preview.slice(0, 30)}...），是否继续？`,
      okText: '移除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          // 使用 label 移除（更安全，不需要完整 cookie 字符串）
          const r = await xWorkbenchApi.cookiePoolRemove(label);
          if (r.success) {
            message.success(r.message);
            load();
          } else {
            message.warning(r.message);
          }
        } catch (e: any) {
          message.error('移除失败: ' + (e?.message || ''));
        }
      },
    });
  }, [load]);

  const handleReset = useCallback(async () => {
    try {
      const r = await xWorkbenchApi.cookiePoolReset();
      message.success(r.message);
      load();
    } catch (e: any) {
      message.error('重置失败: ' + (e?.message || ''));
    }
  }, [load]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    try {
      message.loading({ content: '正在测试 Cookie 有效性（启动浏览器访问 x.com）...', key: 'cookie-test', duration: 0 });
      const r = await xWorkbenchApi.cookiePoolTest();
      message.destroy('cookie-test');
      if (r.success) {
        message.success(r.message);
      } else {
        message.error(r.message);
      }
      load();
    } catch (e: any) {
      message.destroy('cookie-test');
      message.error('测试失败: ' + (e?.message || ''));
    } finally {
      setTesting(false);
    }
  }, [load]);

  const summary = status?.summary;
  const items = status?.items || [];

  const formatTime = (ts: number) => {
    if (!ts) return '-';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString();
  };

  const statusTagColor = (s: string) => {
    if (s === 'cooldown') return 'red';
    if (s === 'healthy') return 'green';
    return 'default';
  };

  const statusTagText = (s: string) => {
    if (s === 'cooldown') return '冷却中';
    if (s === 'healthy') return '健康';
    return '未使用';
  };

  const columns: ColumnsType<CookiePoolItem> = [
    {
      title: '#',
      dataIndex: 'index',
      width: 50,
      render: (v: number) => <Text strong>{v}</Text>,
    },
    {
      title: '标签',
      dataIndex: 'label',
      width: 100,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: 'Cookie 预览',
      dataIndex: 'cookie_preview',
      ellipsis: true,
      render: (v: string) => (
        <Text code style={{ fontSize: 12 }}>{v}</Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: string) => <Tag color={statusTagColor(s)}>{statusTagText(s)}</Tag>,
    },
    {
      title: '成功/失败',
      width: 110,
      render: (_: any, r: CookiePoolItem) => (
        <Space size={4}>
          <Text type="success">✓{r.successes}</Text>
          <Text type="danger">✗{r.failures}</Text>
        </Space>
      ),
    },
    {
      title: '最近使用',
      dataIndex: 'last_used',
      width: 100,
      render: (v: number) => v ? formatTime(v) : '-',
    },
    {
      title: '冷却到',
      dataIndex: 'cooldown_until',
      width: 100,
      render: (v: number, r: CookiePoolItem) => r.in_cooldown ? formatTime(v) : '-',
    },
    {
      title: '操作',
      width: 90,
      render: (_: any, r: CookiePoolItem) => (
        <Button
          size="small"
          danger
          onClick={() => handleRemove(r.label, r.cookie_preview)}
        >
          移除
        </Button>
      ),
    },
  ];

  return (
    <Spin spinning={loading}>
      <Alert
        type="info"
        showIcon
        message="Cookie 号池：通过多个 cookie 账号轮询使用，降低单个账号被风控的风险。失败 3 次自动进入 30 分钟冷却期。"
        style={{ marginBottom: 16 }}
      />

      {/* 汇总统计 */}
      {summary && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="总数" value={summary.total} prefix={<TeamOutlined />} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="可用"
                value={summary.available}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="冷却中"
                value={summary.in_cooldown}
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="冷却时长(秒)"
                value={summary.cooldown_seconds}
                suffix="s"
              />
            </Card>
          </Col>
        </Row>
      )}

      <Card
        title="Cookie 列表"
        size="small"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => load(true)} size="small">刷新</Button>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={handleTest}
              loading={testing}
              size="small"
            >
              测试 Cookie
            </Button>
            <Button
              icon={<UndoOutlined />}
              onClick={handleReset}
              size="small"
            >
              重置状态
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setAddModalOpen(true)}
              size="small"
            >
              添加 Cookie
            </Button>
          </Space>
        }
      >
        {items.length === 0 ? (
          <Empty
            description={
              <span>
                Cookie 池为空。请配置 <Text code>X_TWITTER_COOKIES</Text> 环境变量，或点击「添加 Cookie」。
              </span>
            }
          />
        ) : (
          <Table
            columns={columns}
            dataSource={items}
            rowKey="index"
            size="small"
            pagination={false}
          />
        )}
      </Card>

      {/* 添加 Cookie 弹窗 */}
      <Modal
        title="添加 Cookie 到号池"
        open={addModalOpen}
        onOk={handleAdd}
        onCancel={() => { setAddModalOpen(false); setNewCookie(''); }}
        confirmLoading={submitting}
        okText="添加"
        cancelText="取消"
        width={700}
      >
        <Alert
          type="warning"
          showIcon
          message="Cookie 格式要求"
          description="必须包含 auth_token 和 ct0 字段，格式如: auth_token=xxx; ct0=yyy; guest_id=zzz"
          style={{ marginBottom: 12 }}
        />
        <TextArea
          value={newCookie}
          onChange={(e) => setNewCookie(e.target.value)}
          placeholder="auth_token=672a8ff6...; ct0=9e08d8af...; guest_id=..."
          rows={5}
        />
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            提示：添加后仅在当前进程生效，重启服务后会丢失。如需持久化，请写入 .env 的 X_TWITTER_COOKIES_POOL（多个 cookie 用 | 分隔）。
          </Text>
        </div>
      </Modal>
    </Spin>
  );
};

export default CookiePoolPanel;
