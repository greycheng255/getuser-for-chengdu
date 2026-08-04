import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Modal, Form, Input, Select, Row, Col, Statistic, Empty, Spin, InputNumber, Descriptions, Progress } from 'antd';
import {
  ReloadOutlined, GlobalOutlined, LineChartOutlined, LinkOutlined,
  ThunderboltOutlined, FunnelPlotOutlined,
} from '@ant-design/icons';
import { externalMetricsApi } from '../api/prdGap';

const { Option } = Select;

const ExternalMetrics: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [filter, setFilter] = useState<{ platform?: string; days?: number }>({ days: 30 });
  const [funnelData, setFunnelData] = useState<any>(null);
  const [utmOpen, setUtmOpen] = useState(false);
  const [utmResult, setUtmResult] = useState('');
  const [form] = Form.useForm();
  const [utmForm] = Form.useForm();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await externalMetricsApi.list({ ...filter, limit: 100 });
      const data = res?.data || res || {};
      setItems(data.items || []);
    } catch (e) {
      console.error('fetch external metrics failed', e);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleFunnel = async (platform: string) => {
    try {
      const res = await externalMetricsApi.funnel({ platform, days: filter.days });
      setFunnelData(res?.data || res || null);
    } catch {
      message.error('漏斗分析失败');
    }
  };

  const handleBuildUtm = async () => {
    try {
      const values = await utmForm.validateFields();
      const res = await externalMetricsApi.utmUrl(values);
      setUtmResult(res?.data?.url || '');
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('生成失败');
    }
  };

  const columns = [
    {
      title: '平台', dataIndex: 'platform', width: 100,
      render: (v: string) => <Tag icon={<GlobalOutlined />}>{v}</Tag>,
    },
    { title: '账号ID', dataIndex: 'account_id', width: 140,
      render: (v: string) => <span style={{ wordBreak: 'break-all' }}>{v}</span> },
    { title: '粉丝数', dataIndex: 'followers', width: 100,
      render: (v: number) => v?.toLocaleString() || 0 },
    { title: '播放量', dataIndex: 'views', width: 100,
      render: (v: number) => v?.toLocaleString() || 0 },
    { title: '点赞', dataIndex: 'likes', width: 90,
      render: (v: number) => v?.toLocaleString() || 0 },
    { title: '评论', dataIndex: 'comments', width: 90,
      render: (v: number) => v?.toLocaleString() || 0 },
    { title: '分享', dataIndex: 'shares', width: 90,
      render: (v: number) => v?.toLocaleString() || 0 },
    {
      title: '采集时间', dataIndex: 'collected_at', width: 160,
      render: (v: any) => {
        if (!v) return '-';
        const d = typeof v === 'number' ? new Date(v > 1e12 ? v : v * 1000) : new Date(v);
        return d.toLocaleString('zh-CN');
      },
    },
    {
      title: '操作', width: 110,
      render: (_: any, r: any) => (
        <Button size="small" type="link" icon={<FunnelPlotOutlined />} onClick={() => handleFunnel(r.platform)}>
          漏斗
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <LineChartOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            外部数据看板
          </h3>
        </Col>
        <Col>
          <Space>
            <Button icon={<LinkOutlined />} onClick={() => { setUtmOpen(true); setUtmResult(''); utmForm.resetFields(); }}>
              UTM 链接生成
            </Button>
            <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="采集记录" value={items.length} prefix={<GlobalOutlined />} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="平台数" value={new Set(items.map((i) => i.platform).filter(Boolean)).size} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="总粉丝" value={items.reduce((s, i) => s + (i.followers || 0), 0)} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="总播放" value={items.reduce((s, i) => s + (i.views || 0), 0)} /></Card>
        </Col>
      </Row>

      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Select
            allowClear
            placeholder="平台"
            style={{ width: 140 }}
            value={filter.platform}
            onChange={(v) => setFilter({ ...filter, platform: v })}
          >
            {['youtube', 'instagram', 'facebook', 'tiktok', 'douyin', 'xhs', 'x'].map((p) => (
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
            <Empty description="暂无外部数据，可通过 POST /api/analytics/external-metrics/collect 触发采集" />
          ) : (
            <Table rowKey={(r) => `${r.platform}-${r.account_id}-${r.collected_at}`} columns={columns} dataSource={items} size="middle" pagination={{ pageSize: 15 }} scroll={{ x: 1000 }} />
          )}
        </Spin>
      </Card>

      {funnelData && (
        <Modal
          title="转化漏斗分析"
          open={!!funnelData}
          onCancel={() => setFunnelData(null)}
          footer={null}
          width={600}
        >
          <div style={{ marginBottom: 16 }}>
            {funnelData.stages?.map((stage: any, i: number) => (
              <div key={i} style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span>{stage.name || stage.stage}</span>
                  <span>{stage.count} ({stage.rate?.toFixed(1) || 0}%)</span>
                </div>
                <Progress percent={stage.rate || 0} showInfo={false} />
              </div>
            )) || <Empty description="暂无漏斗数据" />}
          </div>
        </Modal>
      )}

      <Modal
        title="生成 UTM 追踪链接"
        open={utmOpen}
        onCancel={() => setUtmOpen(false)}
        footer={null}
        width={560}
      >
        <Form form={utmForm} layout="vertical">
          <Form.Item name="base_url" label="目标 URL" rules={[{ required: true }]}>
            <Input placeholder="https://example.com/landing" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="source" label="来源" rules={[{ required: true }]}>
                <Input placeholder="如：douyin" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="medium" label="媒介" initialValue="social">
                <Input placeholder="如：social" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="campaign" label="活动">
                <Input placeholder="如：summer_promo" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="content" label="内容">
                <Input placeholder="如：video_a" />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" icon={<ThunderboltOutlined />} onClick={handleBuildUtm} block>生成</Button>
        </Form>
        {utmResult && (
          <Card size="small" style={{ marginTop: 16 }}>
            <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', fontFamily: 'monospace' }}>
              {utmResult}
            </div>
            <Button
              size="small"
              type="link"
              icon={<LinkOutlined />}
              onClick={() => { navigator.clipboard?.writeText(utmResult); message.success('已复制'); }}
            >
              复制链接
            </Button>
          </Card>
        )}
      </Modal>
    </div>
  );
};

export default ExternalMetrics;
