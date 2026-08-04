import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Modal, Form, Input, Select, Row, Col, Statistic, Tabs, Empty, Spin, Descriptions, InputNumber } from 'antd';
import {
  ReloadOutlined, CheckOutlined, CloseOutlined, AuditOutlined,
  ClockCircleOutlined, FileSearchOutlined,
} from '@ant-design/icons';
import { reviewApi, archiveApi } from '../api/prdGap';

const { TextArea } = Input;

const DECISION_LABEL: Record<string, { text: string; color: string }> = {
  pending: { text: '待复核', color: 'processing' },
  approved: { text: '已通过', color: 'success' },
  rejected: { text: '已拒绝', color: 'error' },
};

const ReviewQueue: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [recent, setRecent] = useState<any[]>([]);
  const [archiveItems, setArchiveItems] = useState<any[]>([]);
  const [tab, setTab] = useState('queue');
  const [submitModal, setSubmitModal] = useState<{ open: boolean; review?: any }>({ open: false });
  const [form] = Form.useForm();

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    try {
      const res = await reviewApi.queue({ limit: 100 });
      const data = res?.data || res || {};
      setItems(data.items || []);
    } catch (e) {
      console.error('fetch review queue failed', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchRecent = useCallback(async () => {
    try {
      const res = await reviewApi.recent({ limit: 50 });
      const data = res?.data || res || {};
      setRecent(data.items || []);
    } catch (e) {
      console.error('fetch recent reviews failed', e);
    }
  }, []);

  const fetchArchive = useCallback(async () => {
    try {
      const res = await archiveApi.list({ limit: 100 });
      const data = res?.data || res || [];
      setArchiveItems(Array.isArray(data) ? data : data.items || []);
    } catch (e) {
      console.error('fetch archive failed', e);
    }
  }, []);

  useEffect(() => {
    if (tab === 'queue') fetchQueue();
    else if (tab === 'recent') fetchRecent();
    else if (tab === 'archive') fetchArchive();
  }, [tab, fetchQueue, fetchRecent, fetchArchive]);

  const openSubmit = (review: any) => {
    setSubmitModal({ open: true, review });
    form.resetFields();
    form.setFieldsValue({ reviewer_id: 1, decision: 'approved', notes: '' });
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (!submitModal.review) return;
      await reviewApi.submit(submitModal.review.review_id, values);
      // 流水线任务复核通过 → 后端自动创建发布调度任务
      const contentId = submitModal.review.content_id || '';
      if (values.decision === 'approved' && contentId.startsWith('pipeline_')) {
        message.success('复核通过，已自动创建定时发布任务，发布完成后将自动触发话术库互动');
      } else {
        message.success('已提交复核结果');
      }
      setSubmitModal({ open: false });
      fetchQueue();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('提交失败');
    }
  };

  const queueColumns = [
    {
      title: '内容类型', dataIndex: 'content_type', width: 100,
      render: (v: string) => <Tag>{v || 'video'}</Tag>,
    },
    {
      title: '内容ID', dataIndex: 'content_id', width: 180,
      render: (v: string) => (
        <span style={{ wordBreak: 'break-all' }}>
          {v}
          {v?.startsWith('pipeline_') && (
            <Tag color="purple" style={{ marginLeft: 4, fontSize: 11 }}>流水线</Tag>
          )}
        </span>
      ),
    },
    {
      title: '内容预览', dataIndex: 'content_preview',
      render: (v: string, r: any) => (
        <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', maxWidth: 400 }}>
          {v || r.content_url || '-'}
          {r.auto_moderation_result && (
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>
              自动审核: {JSON.stringify(r.auto_moderation_result).slice(0, 80)}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <Tag color={DECISION_LABEL[v]?.color || 'default'}>{DECISION_LABEL[v]?.text || v}</Tag>,
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
      title: '操作', width: 110,
      render: (_: any, r: any) => (
        <Button type="primary" size="small" icon={<CheckOutlined />} onClick={() => openSubmit(r)}>
          复核
        </Button>
      ),
    },
  ];

  const recentColumns = [
    ...queueColumns.slice(0, 5),
    {
      title: '结果', dataIndex: 'decision', width: 100,
      render: (v: string) => <Tag color={v === 'approved' ? 'success' : 'error'}>{DECISION_LABEL[v]?.text || v}</Tag>,
    },
    {
      title: '复核人', dataIndex: 'reviewer_id', width: 90,
    },
  ];

  const archiveColumns = [
    { title: '类型', dataIndex: 'archive_type', width: 100, render: (v: string) => <Tag>{v}</Tag> },
    { title: '平台', dataIndex: 'platform', width: 90 },
    {
      title: '内容', dataIndex: 'content',
      render: (v: string) => <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>{v || '-'}</span>,
    },
    { title: '存储层级', dataIndex: 'storage_tier', width: 100, render: (v: string) => v || 'hot' },
    {
      title: '归档时间', dataIndex: 'archived_at', width: 160,
      render: (v: any) => {
        if (!v) return '-';
        const d = typeof v === 'number' ? new Date(v > 1e12 ? v : v * 1000) : new Date(v);
        return d.toLocaleString('zh-CN');
      },
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <AuditOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            人工复核队列
          </h3>
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={() => tab === 'queue' ? fetchQueue() : tab === 'recent' ? fetchRecent() : fetchArchive()} loading={loading}>
            刷新
          </Button>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8}>
          <Card size="small"><Statistic title="待复核" value={items.length} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
        <Col xs={12} sm={8}>
          <Card size="small"><Statistic title="近期已处理" value={recent.length} prefix={<CheckOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col xs={12} sm={8}>
          <Card size="small"><Statistic title="合规归档" value={archiveItems.length} prefix={<FileSearchOutlined />} /></Card>
        </Col>
      </Row>

      <Card>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            { key: 'queue', label: `待复核队列 (${items.length})`, children: (
              <Spin spinning={loading}>
                {items.length === 0 && !loading ? <Empty description="队列为空" /> : (
                  <Table rowKey="review_id" columns={queueColumns} dataSource={items} size="middle" pagination={{ pageSize: 15 }} scroll={{ x: 900 }} />
                )}
              </Spin>
            )},
            { key: 'recent', label: `近期处理 (${recent.length})`, children: (
              <Table rowKey="review_id" columns={recentColumns} dataSource={recent} size="middle" pagination={{ pageSize: 15 }} scroll={{ x: 1000 }} />
            )},
            { key: 'archive', label: `合规归档 (${archiveItems.length})`, children: (
              <Table rowKey={(r) => r.archive_id || r.id} columns={archiveColumns} dataSource={archiveItems} size="middle" pagination={{ pageSize: 15 }} scroll={{ x: 900 }} />
            )},
          ]}
        />
      </Card>

      <Modal
        title="提交复核结果"
        open={submitModal.open}
        onOk={handleSubmit}
        onCancel={() => setSubmitModal({ open: false })}
        okText="提交"
        cancelText="取消"
      >
        {submitModal.review && (
          <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="内容ID">{submitModal.review.content_id}</Descriptions.Item>
            <Descriptions.Item label="预览">
              <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                {submitModal.review.content_preview || '-'}
              </span>
            </Descriptions.Item>
          </Descriptions>
        )}
        <Form form={form} layout="vertical">
          <Form.Item name="reviewer_id" label="复核人ID" rules={[{ required: true }]}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="decision" label="决定" rules={[{ required: true }]}>
            <Select>
              <Select.Option value="approved">通过</Select.Option>
              <Select.Option value="rejected">拒绝</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <TextArea rows={3} placeholder="复核意见..." />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ReviewQueue;
