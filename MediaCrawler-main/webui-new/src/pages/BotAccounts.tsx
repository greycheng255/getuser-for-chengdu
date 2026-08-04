import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Modal, Form, Input, Select, Popconfirm, Row, Col, Statistic, Empty, Spin, Tabs } from 'antd';
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, RobotOutlined,
  TeamOutlined, GlobalOutlined, SafetyCertificateOutlined,
  EyeOutlined, MessageOutlined, BellOutlined, ControlOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import { botAccountApi } from '../api/prdGap';
import CookieManager from './CookieManager';
// 迁移自 XWorkbench 的 4 个互动配置 Tab + 1 个独立的互动量配置页
import MonitorPanel from './xworkbench/MonitorPanel';
import TemplatesPanel from './xworkbench/TemplatesPanel';
import ReplyRulesPanel from './xworkbench/ReplyRulesPanel';
import NotificationsPanel from './xworkbench/NotificationsPanel';
import InteractionConfigPage from './InteractionConfig';

const { Option } = Select;
const { TextArea } = Input;

const STATUS_COLOR: Record<string, string> = {
  active: 'green',
  idle: 'blue',
  busy: 'gold',
  cooldown: 'orange',
  disabled: 'red',
  banned: 'red',
};

const GROUP_LABEL: Record<string, string> = {
  domestic_new: '国内新号',
  domestic_mature: '国内成熟号',
  overseas_us: '海外美国',
  overseas_eu: '海外欧洲',
  overseas_sea: '海外东南亚',
};

const BotAccounts: React.FC = () => {
  const [activeTab, setActiveTab] = useState('accounts');

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <RobotOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            账号与互动
          </h3>
        </Col>
      </Row>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        type="line"
        size="middle"
        items={[
          {
            key: 'accounts',
            label: (
              <span>
                <RobotOutlined />
                账号列表
              </span>
            ),
            children: <BotAccountsPanel />,
          },
          {
            key: 'cookies',
            label: (
              <span>
                <SafetyCertificateOutlined />
                Cookie池
              </span>
            ),
            children: <CookieManager />,
          },
          {
            key: 'interaction-config',
            label: (
              <span>
                <ControlOutlined />
                互动量配置
              </span>
            ),
            children: <InteractionConfigPage />,
          },
          {
            key: 'monitor',
            label: (
              <span>
                <EyeOutlined />
                互动监控
              </span>
            ),
            children: <MonitorPanel />,
          },
          {
            key: 'templates',
            label: (
              <span>
                <MessageOutlined />
                评论模板
              </span>
            ),
            children: <TemplatesPanel />,
          },
          {
            key: 'reply-rules',
            label: (
              <span>
                <ThunderboltOutlined />
                回复规则
              </span>
            ),
            children: <ReplyRulesPanel />,
          },
          {
            key: 'notifications',
            label: (
              <span>
                <BellOutlined />
                通知渠道
              </span>
            ),
            children: <NotificationsPanel />,
          },
        ]}
      />
    </div>
  );
};

const BotAccountsPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<any>(null);
  const [groups, setGroups] = useState<any>({ groups: [], statuses: [] });
  const [filter, setFilter] = useState<{ platform?: string; group?: string; status?: string }>({});
  const [modalOpen, setModalOpen] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [form] = Form.useForm();
  const [batchForm] = Form.useForm();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [listRes, statsRes, groupsRes] = await Promise.all([
        botAccountApi.list({ ...filter, limit: 200 }),
        botAccountApi.stats().catch(() => ({ data: null })),
        botAccountApi.groups().catch(() => ({ data: { groups: [], statuses: [] } })),
      ]);
      const data = listRes?.data || listRes || {};
      setItems(data.items || []);
      setTotal(data.total || 0);
      setStats(statsRes?.data || null);
      setGroups(groupsRes?.data || { groups: [], statuses: [] });
    } catch (e) {
      console.error('fetch bot accounts failed', e);
      message.error('加载机器人账号失败');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAdd = async () => {
    try {
      const values = await form.validateFields();
      await botAccountApi.add(values);
      message.success('添加成功');
      setModalOpen(false);
      form.resetFields();
      fetchData();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('添加失败');
    }
  };

  const handleBatchAdd = async () => {
    try {
      const values = await batchForm.validateFields();
      const cookies = (values.cookies as string)
        .split(/[\n|]/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (cookies.length === 0) {
        message.warning('请输入至少一个 cookie');
        return;
      }
      const res = await botAccountApi.batchAdd({
        platform: values.platform,
        cookies,
        group: values.group,
        region: values.region,
      });
      message.success(`成功添加 ${res?.data?.added ?? cookies.length} 个账号`);
      setBatchOpen(false);
      batchForm.resetFields();
      fetchData();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('批量添加失败');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await botAccountApi.delete(id);
      message.success('已删除');
      fetchData();
    } catch {
      message.error('删除失败');
    }
  };

  const columns = [
    {
      title: '标签',
      dataIndex: 'label',
      render: (v: string, r: any) => (
        <Space>
          <RobotOutlined style={{ color: '#1677ff' }} />
          <strong>{v || r.account_id?.slice(0, 8)}</strong>
        </Space>
      ),
    },
    { title: '平台', dataIndex: 'platform', width: 90 },
    {
      title: '分组', dataIndex: 'group', width: 120,
      render: (v: string) => <Tag>{GROUP_LABEL[v] || v}</Tag>,
    },
    {
      title: '地域', dataIndex: 'region', width: 80,
      render: (v: string) => v ? <Tag icon={<GlobalOutlined />}>{v.toUpperCase()}</Tag> : '-',
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '健康度', dataIndex: 'health_score', width: 90,
      render: (v: number) => (
        <span style={{ color: v >= 80 ? '#52c41a' : v >= 50 ? '#faad14' : '#f5222d' }}>
          {v ?? '-'}
        </span>
      ),
    },
    {
      title: '失败次数', dataIndex: 'fail_count', width: 90,
      render: (v: number) => (v > 0 ? <Tag color="red">{v}</Tag> : 0),
    },
    {
      title: '操作', width: 80,
      render: (_: any, r: any) => (
        <Popconfirm title="确认删除该机器人账号?" onConfirm={() => handleDelete(r.account_id)}>
          <Button size="small" type="text" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="账号总数" value={total} prefix={<TeamOutlined />} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="活跃" value={stats?.active ?? 0} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="冷却中" value={stats?.cooldown ?? 0} valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="禁用/封禁" value={stats?.disabled ?? 0} valueStyle={{ color: '#f5222d' }} /></Card>
        </Col>
      </Row>

      <Card
        title="机器人账号列表"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
            <Button icon={<PlusOutlined />} onClick={() => setBatchOpen(true)}>批量导入</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加账号</Button>
          </Space>
        }
      >
        <Space style={{ marginBottom: 16 }} wrap>
          <Select
            allowClear
            placeholder="平台"
            style={{ width: 120 }}
            value={filter.platform}
            onChange={(v) => setFilter({ ...filter, platform: v })}
          >
            {['x', 'douyin', 'xhs', 'weibo', 'bili', 'ks', 'zhihu'].map((p) => (
              <Option key={p} value={p}>{p}</Option>
            ))}
          </Select>
          <Select
            allowClear
            placeholder="分组"
            style={{ width: 150 }}
            value={filter.group}
            onChange={(v) => setFilter({ ...filter, group: v })}
          >
            {groups.groups?.map((g: string) => (
              <Option key={g} value={g}>{GROUP_LABEL[g] || g}</Option>
            ))}
          </Select>
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120 }}
            value={filter.status}
            onChange={(v) => setFilter({ ...filter, status: v })}
          >
            {groups.statuses?.map((s: string) => (
              <Option key={s} value={s}>{s}</Option>
            ))}
          </Select>
        </Space>

        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <Empty description="暂无机器人账号">
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加账号</Button>
            </Empty>
          ) : (
            <Table
              rowKey="account_id"
              columns={columns}
              dataSource={items}
              size="middle"
              pagination={{ pageSize: 15 }}
              scroll={{ x: 900 }}
            />
          )}
        </Spin>
      </Card>

      <Modal
        title="添加机器人账号"
        open={modalOpen}
        onOk={handleAdd}
        onCancel={() => setModalOpen(false)}
        okText="添加"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select>
              {['x', 'douyin', 'xhs', 'weibo', 'bili', 'ks', 'zhihu'].map((p) => (
                <Option key={p} value={p}>{p}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="cookie" label="Cookie" rules={[{ required: true }]}>
            <TextArea rows={4} placeholder="粘贴账号 cookie" />
          </Form.Item>
          <Form.Item name="label" label="标签">
            <Input placeholder="如：抖音小号01" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="group" label="分组">
                <Select>
                  {groups.groups?.map((g: string) => (
                    <Option key={g} value={g}>{GROUP_LABEL[g] || g}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="region" label="地域">
                <Select>
                  {['cn', 'us', 'eu', 'sea', 'jp', 'kr'].map((r) => (
                    <Option key={r} value={r}>{r.toUpperCase()}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title="批量导入机器人账号"
        open={batchOpen}
        onOk={handleBatchAdd}
        onCancel={() => setBatchOpen(false)}
        okText="批量添加"
        cancelText="取消"
        width={600}
      >
        <Form form={batchForm} layout="vertical">
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select>
              {['x', 'douyin', 'xhs', 'weibo', 'bili', 'ks', 'zhihu'].map((p) => (
                <Option key={p} value={p}>{p}</Option>
              ))}
            </Select>
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="group" label="分组">
                <Select>
                  {groups.groups?.map((g: string) => (
                    <Option key={g} value={g}>{GROUP_LABEL[g] || g}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="region" label="地域">
                <Select>
                  {['cn', 'us', 'eu', 'sea'].map((r) => (
                    <Option key={r} value={r}>{r.toUpperCase()}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="cookies" label="Cookies（每行一个，或用 | 分隔）" rules={[{ required: true }]}>
            <TextArea rows={6} placeholder={'cookie1\ncookie2\ncookie3'} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default BotAccounts;
