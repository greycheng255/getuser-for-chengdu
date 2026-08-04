import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Modal, Form, Input, InputNumber, Select, Row, Col, Statistic, Empty, Spin, Descriptions, Progress } from 'antd';
import {
  ReloadOutlined, FireOutlined, ThunderboltOutlined, RocketOutlined,
  TrophyOutlined, SearchOutlined,
} from '@ant-design/icons';
import { viralReviewApi } from '../api/prdGap';

const { Option } = Select;

const ViralReviews: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [filter, setFilter] = useState<{ platform?: string; days?: number }>({ days: 30 });
  const [detail, setDetail] = useState<any>(null);
  const [detectOpen, setDetectOpen] = useState(false);
  const [detectResult, setDetectResult] = useState<any>(null);
  const [form] = Form.useForm();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await viralReviewApi.list({ ...filter, limit: 100 });
      const data = res?.data || res || {};
      setItems(data.items || []);
    } catch (e) {
      console.error('fetch viral reviews failed', e);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openDetail = async (id: string) => {
    try {
      const res = await viralReviewApi.get(id);
      setDetail(res?.data || res || null);
    } catch {
      message.error('加载详情失败');
    }
  };

  const handleDetect = async () => {
    try {
      const values = await form.validateFields();
      setDetectResult(null);
      const res = await viralReviewApi.detect(values);
      setDetectResult(res?.data || res || null);
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('识别失败');
    }
  };

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      const res = await viralReviewApi.create({ ...values, use_ai: true });
      message.success('复盘报告已生成');
      setDetectOpen(false);
      fetchData();
      const rid = res?.data?.report_id;
      if (rid) openDetail(rid);
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('生成失败');
    }
  };

  const columns = [
    {
      title: '内容标题', dataIndex: 'title',
      render: (v: string, r: any) => (
        <Space>
          {r.is_viral && <FireOutlined style={{ color: '#f5222d' }} />}
          <a onClick={() => openDetail(r.report_id)} style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
            {v || r.content_id || '-'}
          </a>
        </Space>
      ),
    },
    {
      title: '平台', dataIndex: 'platform', width: 90,
      render: (v: string) => <Tag>{v || '-'}</Tag>,
    },
    {
      title: '互动率', dataIndex: 'interaction_rate', width: 100,
      render: (v: number) => v ? `${(v * 100).toFixed(1)}%` : '-',
    },
    {
      title: '增速', dataIndex: 'growth_velocity', width: 100,
      render: (v: number) => v ? v.toFixed(1) : '-',
    },
    {
      title: '爆款', dataIndex: 'is_viral', width: 80,
      render: (v: boolean) => v ? <Tag color="red" icon={<RocketOutlined />}>爆款</Tag> : <Tag>普通</Tag>,
    },
    {
      title: '生成时间', dataIndex: 'created_at', width: 160,
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
            <TrophyOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            爆款复盘
          </h3>
        </Col>
        <Col>
          <Space>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => { setDetectOpen(true); setDetectResult(null); form.resetFields(); }}>
              识别爆款 + 生成报告
            </Button>
            <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="报告总数" value={items.length} prefix={<TrophyOutlined />} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="爆款数" value={items.filter((i) => i.is_viral).length} valueStyle={{ color: '#f5222d' }} prefix={<RocketOutlined />} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="平均互动率" value={items.length ? (items.reduce((s, i) => s + (i.interaction_rate || 0), 0) / items.length * 100).toFixed(1) : 0} suffix="%" /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="平台数" value={new Set(items.map((i) => i.platform).filter(Boolean)).size} /></Card>
        </Col>
      </Row>

      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Select
            allowClear
            placeholder="平台"
            style={{ width: 120 }}
            value={filter.platform}
            onChange={(v) => setFilter({ ...filter, platform: v })}
          >
            {['x', 'douyin', 'xhs', 'weibo', 'bili', 'ks', 'youtube', 'instagram'].map((p) => (
              <Option key={p} value={p}>{p}</Option>
            ))}
          </Select>
          <Select
            value={String(filter.days)}
            onChange={(v) => setFilter({ ...filter, days: Number(v) })}
            style={{ width: 120 }}
          >
            <Option value="7">近7天</Option>
            <Option value="30">近30天</Option>
            <Option value="90">近90天</Option>
          </Select>
        </Space>

        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <Empty description="暂无爆款复盘报告">
              <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => { setDetectOpen(true); setDetectResult(null); form.resetFields(); }}>
                识别爆款
              </Button>
            </Empty>
          ) : (
            <Table rowKey="report_id" columns={columns} dataSource={items} size="middle" pagination={{ pageSize: 15 }} scroll={{ x: 900 }} />
          )}
        </Spin>
      </Card>

      <Modal
        title="爆款复盘报告详情"
        open={!!detail}
        onCancel={() => setDetail(null)}
        footer={null}
        width={720}
      >
        {detail && (
          <div>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="标题" span={2}>
                <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>{detail.title || '-'}</span>
              </Descriptions.Item>
              <Descriptions.Item label="平台">{detail.platform || '-'}</Descriptions.Item>
              <Descriptions.Item label="是否爆款">
                {detail.is_viral ? <Tag color="red">爆款</Tag> : <Tag>普通</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="播放量">{detail.views || 0}</Descriptions.Item>
              <Descriptions.Item label="点赞">{detail.likes || 0}</Descriptions.Item>
              <Descriptions.Item label="评论">{detail.comments || 0}</Descriptions.Item>
              <Descriptions.Item label="分享">{detail.shares || 0}</Descriptions.Item>
              <Descriptions.Item label="互动率">{detail.interaction_rate ? (detail.interaction_rate * 100).toFixed(1) + '%' : '-'}</Descriptions.Item>
              <Descriptions.Item label="增速">{detail.growth_velocity?.toFixed(1) || '-'}</Descriptions.Item>
              <Descriptions.Item label="热点来源" span={2}>
                <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>{detail.hotspot_source || '-'}</span>
              </Descriptions.Item>
            </Descriptions>
            {detail.ai_summary && (
              <Card size="small" title="AI 复盘总结" style={{ marginTop: 16 }}>
                <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
                  {detail.ai_summary}
                </div>
              </Card>
            )}
            {detail.content_elements && (
              <Card size="small" title="内容要素分析" style={{ marginTop: 16 }}>
                <pre style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap', margin: 0 }}>
                  {JSON.stringify(detail.content_elements, null, 2)}
                </pre>
              </Card>
            )}
          </div>
        )}
      </Modal>

      <Modal
        title="识别爆款 + 生成复盘报告"
        open={detectOpen}
        onCancel={() => setDetectOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setDetectOpen(false)}>取消</Button>,
          <Button key="detect" icon={<SearchOutlined />} onClick={handleDetect}>仅识别</Button>,
          <Button key="create" type="primary" icon={<ThunderboltOutlined />} onClick={handleCreate}>生成报告</Button>,
        ]}
        width={640}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="内容标题">
            <Input placeholder="爆款内容标题" />
          </Form.Item>
          <Form.Item name="platform" label="平台">
            <Select allowClear>
              {['x', 'douyin', 'xhs', 'weibo', 'bili', 'ks', 'youtube'].map((p) => (
                <Option key={p} value={p}>{p}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="post_url" label="帖子URL">
            <Input placeholder="https://..." />
          </Form.Item>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="views" label="播放"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="likes" label="点赞"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="comments" label="评论"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="shares" label="分享"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            </Col>
          </Row>
          <Form.Item name="hotspot_source" label="热点来源">
            <Input placeholder="如：抖音热榜 XX 话题" />
          </Form.Item>
        </Form>

        {detectResult && (
          <Card size="small" title="识别结果" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Space>
                {detectResult.is_viral ? <Tag color="red" icon={<RocketOutlined />}>爆款</Tag> : <Tag>普通</Tag>}
                <span>爆款分数: {detectResult.viral_score?.toFixed(1) || '-'}</span>
              </Space>
              {detectResult.viral_reasons?.length > 0 && (
                <div>
                  <strong>命中原因:</strong>
                  <ul style={{ margin: '8px 0', paddingLeft: 20, wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                    {detectResult.viral_reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}
                  </ul>
                </div>
              )}
            </Space>
          </Card>
        )}
      </Modal>
    </div>
  );
};

export default ViralReviews;
