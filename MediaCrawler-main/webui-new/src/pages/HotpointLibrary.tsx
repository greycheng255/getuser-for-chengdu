import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Modal, Form, Input, Select, Switch, Popconfirm, Row, Col, Statistic, Tabs, InputNumber, Tooltip } from 'antd';
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, FireOutlined,
  FilterOutlined, ThunderboltOutlined, StarOutlined, StopOutlined,
} from '@ant-design/icons';
import { hotpointFilterApi, hotpointAlertApi } from '../api/prdGap';
import HotpointListPanel from './HotpointListPanel';

const { Option } = Select;

const HotpointLibrary: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [configs, setConfigs] = useState<any[]>([]);
  const [alertStats, setAlertStats] = useState<any>(null);
  const [tab, setTab] = useState('list');
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const fetchConfigs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await hotpointFilterApi.list();
      const data = res?.data || res || {};
      setConfigs(data.items || []);
    } catch (e) {
      console.error('fetch filter configs failed', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchAlertStats = useCallback(async () => {
    try {
      const res = await hotpointAlertApi.stats();
      setAlertStats(res?.data || null);
    } catch (e) {
      console.error('fetch alert stats failed', e);
    }
  }, []);

  useEffect(() => {
    if (tab === 'filters') fetchConfigs();
    else if (tab === 'alert') fetchAlertStats();
  }, [tab, fetchConfigs, fetchAlertStats]);

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({
      name: '', min_heat_value: 1000, industry_categories: [], regions: [],
      include_keywords: [], exclude_keywords: [], only_viral: false,
      categories: [], platforms: [], fetch_interval_seconds: 1800, is_active: true,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await hotpointFilterApi.save(values);
      message.success('保存成功');
      setModalOpen(false);
      fetchConfigs();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('保存失败');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await hotpointFilterApi.delete(id);
      message.success('已删除');
      fetchConfigs();
    } catch {
      message.error('删除失败');
    }
  };

  const toggleAlert = async (start: boolean) => {
    try {
      if (start) {
        await hotpointAlertApi.start();
        message.success('突发热点扫描已启动');
      } else {
        await hotpointAlertApi.stop();
        message.success('突发热点扫描已停止');
      }
      fetchAlertStats();
    } catch {
      message.error('操作失败');
    }
  };

  const configColumns = [
    {
      title: '名称', dataIndex: 'name',
      render: (v: string, r: any) => (
        <Space>
          <FireOutlined style={{ color: '#fa541c' }} />
          <strong>{v}</strong>
          {r.is_active && <Tag color="green">启用</Tag>}
        </Space>
      ),
    },
    { title: '热度阈值', dataIndex: 'min_heat_value', width: 100, render: (v: number) => v || 0 },
    {
      title: '行业品类', dataIndex: 'industry_categories', width: 160,
      render: (v: string[]) => (v?.length ? v.map((c) => <Tag key={c}>{c}</Tag>) : '-'),
    },
    {
      title: '包含关键词', dataIndex: 'include_keywords',
      render: (v: string[]) => (
        <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
          {v?.length ? v.join('、') : '-'}
        </span>
      ),
    },
    {
      title: '排除关键词', dataIndex: 'exclude_keywords',
      render: (v: string[]) => (
        <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
          {v?.length ? v.join('、') : '-'}
        </span>
      ),
    },
    { title: '抓取间隔', dataIndex: 'fetch_interval_seconds', width: 100, render: (v: number) => v ? `${v}s` : '-' },
    {
      title: '操作', width: 80,
      render: (_: any, r: any) => (
        <Popconfirm title="确认删除?" onConfirm={() => handleDelete(r.config_id)}>
          <Button size="small" type="text" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <FireOutlined style={{ color: '#fa541c', marginRight: 8 }} />
            热点中心
          </h3>
        </Col>
        {tab !== 'list' && (
          <Col>
            <Space>
              <Button
                icon={<ReloadOutlined />}
                onClick={() => (tab === 'filters' ? fetchConfigs() : fetchAlertStats())}
                loading={loading}
              >
                刷新
              </Button>
              {tab === 'filters' && (
                <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                  新建筛选配置
                </Button>
              )}
            </Space>
          </Col>
        )}
      </Row>

      <Card>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            {
              key: 'list',
              label: <span><FireOutlined /> 热点聚合</span>,
              children: <HotpointListPanel compact />,
            },
            {
              key: 'filters',
              label: <span><FilterOutlined /> 筛选配置 ({configs.length})</span>,
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                    <Button icon={<ReloadOutlined />} onClick={fetchConfigs} loading={loading}>刷新</Button>
                    <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建配置</Button>
                  </Space>
                  <Table
                    rowKey="config_id"
                    columns={configColumns}
                    dataSource={configs}
                    loading={loading}
                    size="middle"
                    pagination={{ pageSize: 15 }}
                    scroll={{ x: 1000 }}
                  />
                </Space>
              ),
            },
            {
              key: 'alert',
              label: <span><ThunderboltOutlined /> 突发热点预警</span>,
              children: (
                <div>
                  <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                    <Col xs={12} sm={6}>
                      <Card size="small">
                        <Statistic
                          title="扫描状态"
                          value={alertStats?.is_running ? '运行中' : '已停止'}
                          valueStyle={{ color: alertStats?.is_running ? '#52c41a' : '#8c8c8c' }}
                          prefix={<ThunderboltOutlined />}
                        />
                      </Card>
                    </Col>
                    <Col xs={12} sm={6}>
                      <Card size="small"><Statistic title="已检测突发" value={alertStats?.total_detected ?? 0} prefix={<FireOutlined />} /></Card>
                    </Col>
                    <Col xs={12} sm={6}>
                      <Card size="small"><Statistic title="扫描间隔" value={alertStats?.check_interval ?? '-'} suffix="秒" /></Card>
                    </Col>
                    <Col xs={12} sm={6}>
                      <Card size="small"><Statistic title="历史样本" value={alertStats?.history_size ?? 0} /></Card>
                    </Col>
                  </Row>
                  <Space>
                    {alertStats?.is_running ? (
                      <Button danger icon={<StopOutlined />} onClick={() => toggleAlert(false)}>停止扫描</Button>
                    ) : (
                      <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => toggleAlert(true)}>启动扫描</Button>
                    )}
                  </Space>
                </div>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="新建热点筛选配置"
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={680}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="配置名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：科技类高热度筛选" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="min_heat_value" label="最小热度阈值">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="fetch_interval_seconds" label="抓取间隔(秒)">
                <InputNumber min={60} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="industry_categories" label="行业品类">
            <Select mode="tags" placeholder="输入后回车" />
          </Form.Item>
          <Form.Item name="regions" label="地域">
            <Select mode="tags" placeholder="如 cn、us" />
          </Form.Item>
          <Form.Item name="include_keywords" label="包含关键词">
            <Select mode="tags" placeholder="输入关键词后回车" />
          </Form.Item>
          <Form.Item name="exclude_keywords" label="排除关键词">
            <Select mode="tags" placeholder="输入关键词后回车" />
          </Form.Item>
          <Form.Item name="platforms" label="目标平台">
            <Select mode="tags" placeholder="如 douyin、xhs" />
          </Form.Item>
          <Form.Item name="only_viral" label="仅爆款" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default HotpointLibrary;
