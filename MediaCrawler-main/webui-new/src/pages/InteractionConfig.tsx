import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Modal, Form, Input, InputNumber, Select, Switch, Popconfirm, Row, Col, Statistic, Empty, Spin, Slider, Divider } from 'antd';
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, SettingOutlined,
  ThunderboltOutlined, InteractionOutlined, CalculatorOutlined,
} from '@ant-design/icons';
import { interactionConfigApi } from '../api/prdGap';

const { Option } = Select;

const InteractionConfigPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [splitOpen, setSplitOpen] = useState<{ open: boolean; config?: any }>({ open: false });
  const [splitResult, setSplitResult] = useState<any>(null);
  const [splitTotal, setSplitTotal] = useState(30);
  const [form] = Form.useForm();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await interactionConfigApi.list();
      const data = res?.data || res || [];
      setItems(Array.isArray(data) ? data : data.items || []);
    } catch (e) {
      console.error('fetch interaction configs failed', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({
      name: '',
      platform: 'all',
      scene: 'default',
      min_likes: 5, max_likes: 20,
      min_comments: 1, max_comments: 5,
      min_shares: 0, max_shares: 3,
      min_favorites: 0, max_favorites: 5,
      like_comment_ratio: 5.0,
      interaction_target_total: 30,
      delay_start_min_minutes: 5,
      delay_start_max_minutes: 30,
      interval_min_seconds: 30,
      interval_max_seconds: 180,
      weight_like: 0.6, weight_comment: 0.15, weight_share: 0.1, weight_favorite: 0.15,
      is_active: true,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await interactionConfigApi.save(values);
      message.success('保存成功');
      setModalOpen(false);
      fetchData();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('保存失败');
    }
  };

  const handleDeactivate = async (id: string) => {
    try {
      await interactionConfigApi.deactivate(id);
      message.success('已停用');
      fetchData();
    } catch {
      message.error('停用失败');
    }
  };

  const handleSplit = async () => {
    if (!splitOpen.config) return;
    try {
      const res = await interactionConfigApi.split(splitOpen.config.config_id, splitTotal);
      setSplitResult(res?.data || res || null);
    } catch {
      message.error('计算失败');
    }
  };

  const columns = [
    {
      title: '名称', dataIndex: 'name',
      render: (v: string, r: any) => (
        <Space>
          <SettingOutlined style={{ color: '#1677ff' }} />
          <strong>{v || '未命名'}</strong>
          {r.is_active && <Tag color="green">启用</Tag>}
        </Space>
      ),
    },
    { title: '平台', dataIndex: 'platform', width: 90 },
    { title: '场景', dataIndex: 'scene', width: 100 },
    {
      title: '点赞区间', width: 110,
      render: (_: any, r: any) => `${r.min_likes}~${r.max_likes}`,
    },
    {
      title: '评论区间', width: 110,
      render: (_: any, r: any) => `${r.min_comments}~${r.max_comments}`,
    },
    {
      title: '目标总量', dataIndex: 'interaction_target_total', width: 90,
    },
    {
      title: '启动延迟(分)', width: 120,
      render: (_: any, r: any) => `${r.delay_start_min_minutes}~${r.delay_start_max_minutes}`,
    },
    {
      title: '操作', width: 160,
      render: (_: any, r: any) => (
        <Space size="small">
          <Button size="small" type="link" icon={<CalculatorOutlined />} onClick={() => { setSplitOpen({ open: true, config: r }); setSplitResult(null); setSplitTotal(r.interaction_target_total || 30); }}>
            分配
          </Button>
          {r.is_active && (
            <Popconfirm title="确认停用?" onConfirm={() => handleDeactivate(r.config_id)}>
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <InteractionOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            互动量配置
          </h3>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建配置</Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="配置总数" value={items.length} prefix={<SettingOutlined />} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="启用中" value={items.filter((i) => i.is_active).length} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="平台覆盖" value={new Set(items.map((i) => i.platform)).size} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="场景覆盖" value={new Set(items.map((i) => i.scene)).size} /></Card>
        </Col>
      </Row>

      <Card>
        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <Empty description="暂无互动量配置">
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建配置</Button>
            </Empty>
          ) : (
            <Table rowKey="config_id" columns={columns} dataSource={items} size="middle" pagination={{ pageSize: 15 }} scroll={{ x: 1000 }} />
          )}
        </Spin>
      </Card>

      <Modal
        title="新建互动量配置"
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={720}
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="name" label="配置名称" rules={[{ required: true }]}>
                <Input placeholder="如：抖音-日常互动" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="platform" label="平台">
                <Select>
                  <Option value="all">全部平台</Option>
                  {['x', 'douyin', 'xhs', 'weibo', 'bili', 'ks'].map((p) => (
                    <Option key={p} value={p}>{p}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="scene" label="场景">
                <Select>
                  <Option value="default">默认</Option>
                  <Option value="comment_reply">评论回复</Option>
                  <Option value="promotion">推广</Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Divider plain>互动量区间</Divider>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="min_likes" label="最少点赞"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="max_likes" label="最多点赞"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="min_comments" label="最少评论"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="max_comments" label="最多评论"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="min_shares" label="最少分享"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="max_shares" label="最多分享"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="min_favorites" label="最少收藏"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="max_favorites" label="最多收藏"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
          </Row>
          <Form.Item name="interaction_target_total" label="目标互动总量">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>

          <Divider plain>时效控制</Divider>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="delay_start_min_minutes" label="启动延迟下限(分钟)">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="delay_start_max_minutes" label="启动延迟上限(分钟)">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="interval_min_seconds" label="互动间隔下限(秒)">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="interval_max_seconds" label="互动间隔上限(秒)">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          <Divider plain>权重分配（总和应为1）</Divider>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="weight_like" label="点赞权重"><InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="weight_comment" label="评论权重"><InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="weight_share" label="分享权重"><InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="weight_favorite" label="收藏权重"><InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} /></Form.Item>
            </Col>
          </Row>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="互动量分配预览"
        open={splitOpen.open}
        onCancel={() => setSplitOpen({ open: false })}
        footer={null}
        width={520}
      >
        {splitOpen.config && (
          <div>
            <p>配置：<strong>{splitOpen.config.name}</strong></p>
            <div style={{ marginBottom: 16 }}>
              <label>目标总量：{splitTotal}</label>
              <Slider min={1} max={200} value={splitTotal} onChange={setSplitTotal} />
            </div>
            <Button type="primary" icon={<CalculatorOutlined />} onClick={handleSplit} block>计算分配</Button>
            {splitResult && (
              <Card size="small" style={{ marginTop: 16 }}>
                <Row gutter={16}>
                  <Col span={6}><Statistic title="点赞" value={splitResult.likes ?? 0} /></Col>
                  <Col span={6}><Statistic title="评论" value={splitResult.comments ?? 0} /></Col>
                  <Col span={6}><Statistic title="分享" value={splitResult.shares ?? 0} /></Col>
                  <Col span={6}><Statistic title="收藏" value={splitResult.favorites ?? 0} /></Col>
                </Row>
              </Card>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
};

export default InteractionConfigPage;
