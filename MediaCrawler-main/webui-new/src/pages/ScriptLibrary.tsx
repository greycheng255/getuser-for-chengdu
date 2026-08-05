import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Modal, Form, Input, Select, Popconfirm, Row, Col, Statistic, Empty, Spin, InputNumber } from 'antd';
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, MessageOutlined,
  RobotOutlined, ThunderboltOutlined, CopyOutlined,
} from '@ant-design/icons';
import { scriptApi } from '../api/prdGap';

const { TextArea } = Input;
const { Option } = Select;

const SCENE_LABEL: Record<string, string> = {
  comment_reply: '评论回复',
  comment: '评论',
  dm_reply: '私信回复',
  follow: '关注话术',
};

const TYPE_LABEL: Record<string, string> = {
  comment: '评论',
  direct_message: '私信',
  publish: '发布文案',
};

const ScriptLibrary: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [filter, setFilter] = useState<{ platform?: string; script_type?: string; scene?: string }>({});
  const [addOpen, setAddOpen] = useState(false);
  const [genOpen, setGenOpen] = useState(false);
  const [genResult, setGenResult] = useState<any[]>([]);
  const [genLoading, setGenLoading] = useState(false);
  const [form] = Form.useForm();
  const [genForm] = Form.useForm();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await scriptApi.list({ ...filter, limit: 200 });
      const data = res?.data || res || [];
      setItems(Array.isArray(data) ? data : data.items || []);
    } catch (e) {
      console.error('fetch scripts failed', e);
      message.error('加载话术失败');
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
      await scriptApi.create({
        ...values,
        tags: values.tags ? values.tags.split(',').map((v: string) => v.trim()).filter(Boolean) : [],
        platform_constraints: values.platform_constraints
          ? values.platform_constraints.split(',').map((v: string) => v.trim()).filter(Boolean)
          : [],
      });
      message.success('添加成功');
      form.resetFields();
      setAddOpen(false);
      fetchData();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('添加失败');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await scriptApi.delete(id);
      message.success('已删除');
      fetchData();
    } catch {
      message.error('删除失败');
    }
  };

  const handleGenerate = async () => {
    try {
      const values = await genForm.validateFields();
      setGenLoading(true);
      setGenResult([]);
      const res = await scriptApi.generate({ ...values, auto_save: true });
      const data = res?.data || res || {};
      setGenResult(data.variants || []);
      message.success(`生成 ${data.count || 0} 条话术并已入库`);
      fetchData();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('生成失败');
    } finally {
      setGenLoading(false);
    }
  };

  const columns = [
    {
      title: '内容', dataIndex: 'content',
      render: (v: string) => (
        <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', maxWidth: 500 }}>
          {v}
        </div>
      ),
    },
    {
      title: '平台', dataIndex: 'platform', width: 90,
      render: (v: string) => v ? <Tag>{v}</Tag> : <Tag>通用</Tag>,
    },
    {
      title: '类型', dataIndex: 'script_type', width: 100,
      render: (v: string) => <Tag color="purple">{TYPE_LABEL[v] || v}</Tag>,
    },
    {
      title: '场景', dataIndex: 'scene', width: 110,
      render: (v: string) => <Tag color="blue">{SCENE_LABEL[v] || v}</Tag>,
    },
    {
      title: '标签', dataIndex: 'tags', width: 160,
      render: (v: string[]) => v?.length ? v.map((t) => <Tag key={t}>{t}</Tag>) : '-',
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 160,
      render: (v: any) => {
        if (!v) return '-';
        const d = typeof v === 'number' ? new Date(v > 1e12 ? v : v * 1000) : new Date(v);
        return d.toLocaleString('zh-CN');
      },
    },
    {
      title: '操作', width: 120,
      render: (_: any, r: any) => (
        <Space size="small">
          <Button
            size="small"
            type="text"
            icon={<CopyOutlined />}
            onClick={() => {
              navigator.clipboard?.writeText(r.content);
              message.success('已复制');
            }}
          />
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(r.script_id)}>
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <MessageOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            话术库
          </h3>
        </Col>
        <Col>
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setAddOpen(true); }}>新增话术</Button>
            <Button icon={<ThunderboltOutlined />} onClick={() => { setGenOpen(true); setGenResult([]); genForm.resetFields(); }}>
              AI 生成话术
            </Button>
            <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8}>
          <Card size="small"><Statistic title="话术总数" value={items.length} prefix={<MessageOutlined />} /></Card>
        </Col>
        <Col xs={12} sm={8}>
          <Card size="small"><Statistic title="场景数" value={new Set(items.map((i) => i.scene)).size} /></Card>
        </Col>
        <Col xs={12} sm={8}>
          <Card size="small"><Statistic title="平台数" value={new Set(items.map((i) => i.platform).filter(Boolean)).size} /></Card>
        </Col>
      </Row>

      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Select
            allowClear
            placeholder="一级类型"
            style={{ width: 130 }}
            value={filter.script_type}
            onChange={(v) => setFilter({ ...filter, script_type: v })}
          >
            {Object.entries(TYPE_LABEL).map(([k, v]) => <Option key={k} value={k}>{v}</Option>)}
          </Select>
          <Select
            allowClear
            placeholder="平台"
            style={{ width: 120 }}
            value={filter.platform}
            onChange={(v) => setFilter({ ...filter, platform: v })}
          >
            {['x', 'douyin', 'xhs', 'weibo', 'bili', 'ks'].map((p) => (
              <Option key={p} value={p}>{p}</Option>
            ))}
          </Select>
          <Select
            allowClear
            placeholder="场景"
            style={{ width: 150 }}
            value={filter.scene}
            onChange={(v) => setFilter({ ...filter, scene: v })}
          >
            {Object.entries(SCENE_LABEL).map(([k, v]) => (
              <Option key={k} value={k}>{v}</Option>
            ))}
          </Select>
        </Space>

        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <Empty description="暂无话术，点击「AI 生成话术」快速创建" />
          ) : (
            <Table rowKey="script_id" columns={columns} dataSource={items} size="middle" pagination={{ pageSize: 15 }} scroll={{ x: 900 }} />
          )}
        </Spin>
      </Card>

      <Modal title="新增统一话术" open={addOpen} onOk={handleAdd} onCancel={() => { form.resetFields(); setAddOpen(false); }}>
        <Form form={form} layout="vertical" initialValues={{ script_type: 'comment', scene: 'comment_reply' }}>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="script_type" label="一级类型" rules={[{ required: true }]}><Select options={Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))} /></Form.Item></Col>
            <Col span={12}><Form.Item name="scene" label="二级场景" rules={[{ required: true }]}><Select options={Object.entries(SCENE_LABEL).map(([value, label]) => ({ value, label }))} /></Form.Item></Col>
          </Row>
          <Form.Item name="platform" label="平台（留空为通用）"><Input /></Form.Item>
          <Form.Item name="title" label="标题（发布文案可用）"><Input /></Form.Item>
          <Form.Item name="content" label="正文" rules={[{ required: true }]}><TextArea rows={5} /></Form.Item>
          <Form.Item name="tags" label="标签（逗号分隔）"><Input /></Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="media_type" label="媒体类型"><Input placeholder="image / video / article" /></Form.Item></Col>
            <Col span={12}><Form.Item name="platform_constraints" label="平台约束（逗号分隔）"><Input /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title="AI 生成话术"
        open={genOpen}
        onCancel={() => setGenOpen(false)}
        footer={null}
        width={680}
      >
        <Form form={genForm} layout="vertical">
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="script_type" label="场景类型">
                <Select defaultValue="comment_reply">
                  {Object.entries(SCENE_LABEL).map(([k, v]) => (
                    <Option key={k} value={k}>{v}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="platform" label="平台">
                <Select allowClear>
                  {['x', 'douyin', 'xhs', 'weibo', 'bili'].map((p) => (
                    <Option key={p} value={p}>{p}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="count" label="生成数量">
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="context" label="上下文（帖子标题/话题）">
            <TextArea rows={2} placeholder="如：低价电子产品推荐" />
          </Form.Item>
          <Form.Item name="use_ai" label="使用AI" valuePropName="checked" initialValue={true}>
            <Select>
              <Option value={true}>使用 AI</Option>
              <Option value={false}>本地变体生成</Option>
            </Select>
          </Form.Item>
          <Button type="primary" icon={<RobotOutlined />} loading={genLoading} onClick={handleGenerate} block>
            生成并入库
          </Button>
        </Form>

        {genResult.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <h4>生成结果（已自动入库）</h4>
            {genResult.map((v, i) => (
              <Card key={i} size="small" style={{ marginBottom: 8 }}>
                <Space>
                  <Tag color="blue">{v.variant_type}</Tag>
                  {v.script_id && <Tag color="green">已入库</Tag>}
                </Space>
                <div style={{ marginTop: 8, wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                  {v.content}
                </div>
              </Card>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
};

export default ScriptLibrary;
