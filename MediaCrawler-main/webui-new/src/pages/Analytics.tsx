import { message } from '../utils/antdMessage';
import React, { useEffect, useMemo, useState } from 'react';
import { Card, Row, Col, Statistic, Empty, Select, DatePicker, Space, Tabs, Table, Tag, Tooltip } from 'antd';
import { Column, Funnel, Line, Pie } from '@ant-design/charts';
import {
  RiseOutlined,
  FallOutlined,
  BarChartOutlined,
  ScheduleOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
  TeamOutlined,
  GlobalOutlined,
} from '@ant-design/icons';
import { getTrends, getPlatformAnalytics, getFunnelData } from '../api/dashboard';
import { getLeadStats } from '../api/leads';
import { analyticsApi } from '../api/prdGap';
import SkeletonCard from '../components/SkeletonCard';
import type { LeadStats } from '../types';
import { PLATFORM_MAP, INTENT_MAP } from '../types';

const { RangePicker } = DatePicker;
const { Option } = Select;

// 长文本自动换行、无水平滚动条（用户偏好）
const wrapStyle: React.CSSProperties = {
  wordBreak: 'break-all',
  overflowWrap: 'anywhere',
  overflowX: 'hidden',
};

// 平台名称映射（后端返回的 platform 字段可能是 x_twitter / youtube / douyin 等）
const ANALYTICS_PLATFORM_LABEL: Record<string, string> = {
  x_twitter: 'X (Twitter)',
  x: 'X (Twitter)',
  youtube: 'YouTube',
  tiktok: 'TikTok',
  instagram: 'Instagram',
  facebook: 'Facebook',
  douyin: '抖音',
  xiaohongshu: '小红书',
  weibo: '微博',
  zhihu: '知乎',
  bilibili: '哔哩哔哩',
  baidu: '百度',
  toutiao: '今日头条',
};

const labelOf = (p?: string) => (p ? ANALYTICS_PLATFORM_LABEL[p] || PLATFORM_MAP[p] || p : '未知');

interface DashboardSummary {
  publish_count?: number;
  publish_success?: number;
  publish_success_rate?: number;
  scheduled_count?: number;
  scheduled_success?: number;
  moderation_total?: number;
  moderation_approved?: number;
  moderation_rejected?: number;
  moderation_pass_rate?: number;
  sentiment_alerts?: number;
  accounts?: Array<{ platform: string; total: number; active: number }>;
}

interface DashboardResponse {
  summary?: DashboardSummary;
  trends?: Array<{ date: string; publish_count: number }>;
  platform_distribution?: Array<{ platform: string; count: number }>;
  days?: number;
}

interface PlatformComparisonItem {
  platform: string;
  total: number;
  success: number;
  success_rate: number;
}

interface PlatformComparisonResponse {
  platforms?: PlatformComparisonItem[];
  days?: number;
}

interface ContentPerformanceItem {
  id: number;
  content_preview: string;
  tweet_id?: string;
  created_at?: string;
}

interface ContentPerformanceResponse {
  items?: ContentPerformanceItem[];
  count?: number;
}

interface ExternalMetricItem {
  metric_id?: string;
  platform: string;
  account_id?: string;
  metric_date?: string;
  followers_count?: number;
  followers_delta?: number;
  views_count?: number;
  likes_count?: number;
  comments_count?: number;
  shares_count?: number;
  posts_count?: number;
  impressions?: number;
  clicks?: number;
  visits?: number;
  conversions?: number;
}

const Analytics: React.FC = () => {
  // 日期范围（天数）默认 7 天；平台筛选（external-metrics 用）
  const [days, setDays] = useState<number>(7);
  const [platformFilter, setPlatformFilter] = useState<string | undefined>(undefined);

  // dashboard 数据
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [platformComparison, setPlatformComparison] = useState<PlatformComparisonItem[]>([]);
  const [contentPerformance, setContentPerformance] = useState<ContentPerformanceItem[]>([]);
  const [externalMetrics, setExternalMetrics] = useState<ExternalMetricItem[]>([]);

  // 原有线索数据
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [trends, setTrends] = useState<Array<{ date: string; leads: number }>>([]);
  const [platformData, setPlatformData] = useState<Array<{ platform: string; count: number }>>([]);
  const [funnelData, setFunnelData] = useState<Array<{ status: string; count: number }>>([]);

  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days, platformFilter]);

  const fetchAll = async () => {
    setLoading(true);
    try {
      // 第一批：与 days / platform 相关的并发请求
      const [dashRes, cmpRes, extRes, statsRes, trendsRes, platformRes, funnelRes] =
        await Promise.all([
          analyticsApi.getDashboard(days),
          analyticsApi.getPlatformComparison(Math.max(days, 30)),
          analyticsApi.getExternalMetrics({ platform: platformFilter, days, limit: 200 }),
          getLeadStats(),
          getTrends(days),
          getPlatformAnalytics(),
          getFunnelData(),
        ]);

      setDashboard(dashRes || null);
      const cmpData: PlatformComparisonResponse = cmpRes || {};
      setPlatformComparison(cmpData.platforms || []);
      // external-metrics 后端是 {code, data:{items,total}} 包裹格式
      const extData = extRes?.data || extRes || {};
      setExternalMetrics(extData.items || []);

      setStats(statsRes);
      setTrends(trendsRes.trends || []);
      setPlatformData(platformRes.platform_distribution || []);
      setFunnelData(funnelRes.funnel || []);

      // 第二批：内容表现（不依赖 days，但依赖默认 limit）
      try {
        const perfRes: ContentPerformanceResponse = await analyticsApi.getContentPerformance(50);
        setContentPerformance(perfRes.items || []);
      } catch (e) {
        console.error('Failed to fetch content performance:', e);
        setContentPerformance([]);
      }
    } catch (error) {
      console.error('Failed to fetch analytics data:', error);
      message.error('数据加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  // ============ 图表配置 ============

  // 平台对比柱状图：每个平台 total + success
  const platformComparisonChartData = useMemo(
    () =>
      platformComparison.flatMap(it => [
        { platform: labelOf(it.platform), type: '发布总量', value: it.total || 0 },
        { platform: labelOf(it.platform), type: '发布成功', value: it.success || 0 },
      ]),
    [platformComparison],
  );

  const platformComparisonConfig = {
    data: platformComparisonChartData,
    isGroup: true,
    xField: 'platform',
    yField: 'value',
    seriesField: 'type',
    color: ['#1677ff', '#52c41a'],
    label: { position: 'middle' as const },
    legend: { position: 'top' as const },
    meta: { platform: { alias: '平台' }, value: { alias: '数量' } },
  };

  // 发布趋势折线图（dashboard.trends）
  const publishTrendConfig = {
    data: (dashboard?.trends || []).map(t => ({ date: t.date, value: t.publish_count || 0 })),
    xField: 'date',
    yField: 'value',
    smooth: true,
    point: { size: 3 },
    color: ['#1677ff'],
    meta: { date: { alias: '日期' }, value: { alias: '发布量' } },
  };

  // 外部指标折线图：按日期展示 followers_delta / views / likes
  const externalMetricsChartData = useMemo(
    () =>
      externalMetrics
        .filter(it => it.metric_date)
        .flatMap(it => [
          { date: it.metric_date!, platform: labelOf(it.platform), type: '新增粉丝', value: it.followers_delta || 0 },
          { date: it.metric_date!, platform: labelOf(it.platform), type: '播放量', value: it.views_count || 0 },
          { date: it.metric_date!, platform: labelOf(it.platform), type: '点赞', value: it.likes_count || 0 },
        ]),
    [externalMetrics],
  );

  const externalMetricsChartConfig = {
    data: externalMetricsChartData,
    xField: 'date',
    yField: 'value',
    seriesField: 'type',
    smooth: true,
    point: { size: 2 },
    color: ['#1677ff', '#52c41a', '#fa8c16'],
    legend: { position: 'top' as const },
    meta: { date: { alias: '日期' }, value: { alias: '数值' } },
  };

  // ============ 原线索维度图表配置（保留作为底部 Tab）============
  const trendConfig = {
    data: trends.flatMap(item => [{ date: item.date, value: item.leads, type: '新增线索' }]),
    xField: 'date',
    yField: 'value',
    seriesField: 'type',
    smooth: true,
    point: { size: 3 },
    color: ['#1677ff'],
  };

  const intentData = stats?.intent_distribution
    ? Object.entries(stats.intent_distribution).map(([key, count]) => ({
        type: INTENT_MAP[key] || key,
        count,
      }))
    : [];

  const intentConfig = {
    data: intentData,
    xField: 'type',
    yField: 'count',
    label: { position: 'top' as const },
    color: '#1677ff',
  };

  const platformConfig = {
    data: platformData.map(item => ({
      type: labelOf(item.platform),
      value: item.count,
    })),
    angleField: 'value',
    colorField: 'type',
    radius: 0.8,
    // 注意：@ant-design/charts v2 + antd v6 下，label.type='outer' 会触发
    // "Unknown Component: shape.outer"（G2Plot 的 shape 未注册）。
    // 解决：不指定 type，用函数式 content 直接输出文案，避免 expr 和 shape 解析。
    label: {
      content: ({ percent }: { percent?: number }, item?: any) =>
        `${item?.type ?? ''} ${(percent != null ? percent * 100 : 0).toFixed(1)}%`,
    },
    interactions: [{ type: 'element-active' }],
  };

  const funnelChartData = funnelData.map(item => ({
    stage:
      item.status === 'new'
        ? '新线索'
        : item.status === 'contacted'
        ? '已联系'
        : item.status === 'qualified'
        ? '已确认'
        : item.status === 'converted'
        ? '已转化'
        : item.status,
    count: item.count,
  }));

  const funnelConfig = {
    data: funnelChartData,
    xField: 'stage',
    yField: 'count',
    compareField: 'stage',
    isTransposed: true,
    color: ['#1677ff', '#1890ff', '#40a9ff', '#69c0ff'],
  };

  // ============ 派生指标 ============

  const summary = dashboard?.summary || {};
  const totalAccounts = (summary.accounts || []).reduce((s, a) => s + (a.total || 0), 0);
  const activeAccounts = (summary.accounts || []).reduce((s, a) => s + (a.active || 0), 0);

  const totalLeads = stats?.total_leads || 0;
  const convertedLeads = stats?.converted_leads || 0;
  const avgScore = stats?.avg_lead_score || 0;
  const lossRate = totalLeads > 0 ? ((totalLeads - convertedLeads) / totalLeads) * 100 : 0;

  // ============ 内容表现表格列 ============

  const contentColumns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 80,
    },
    {
      title: '内容预览',
      dataIndex: 'content_preview',
      render: (text: string) => (
        <Tooltip title={text} placement="topLeft">
          <span style={{ ...wrapStyle, display: 'inline-block', maxWidth: 480 }}>{text || '-'}</span>
        </Tooltip>
      ),
    },
    {
      title: 'Tweet ID',
      dataIndex: 'tweet_id',
      width: 160,
      render: (text: string) => (
        <span style={wrapStyle}>{text || '-'}</span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (t: string) => (t ? String(t) : '-'),
    },
  ];

  // ============ 外部指标表格列 ============

  const intFormatter = (v: any) => {
    const n = Number(v || 0);
    return Number.isFinite(n) ? n.toLocaleString() : '-';
  };

  const externalColumns = [
    { title: '日期', dataIndex: 'metric_date', width: 120 },
    {
      title: '平台',
      dataIndex: 'platform',
      width: 120,
      render: (p: string) => <Tag color="blue">{labelOf(p)}</Tag>,
    },
    { title: '账号', dataIndex: 'account_id', width: 140, render: (t: string) => <span style={wrapStyle}>{t || '-'}</span> },
    { title: '粉丝数', dataIndex: 'followers_count', width: 110, render: intFormatter, align: 'right' as const },
    { title: '新增粉丝', dataIndex: 'followers_delta', width: 110, render: intFormatter, align: 'right' as const },
    { title: '播放量', dataIndex: 'views_count', width: 110, render: intFormatter, align: 'right' as const },
    { title: '点赞', dataIndex: 'likes_count', width: 100, render: intFormatter, align: 'right' as const },
    { title: '评论', dataIndex: 'comments_count', width: 100, render: intFormatter, align: 'right' as const },
    { title: '分享', dataIndex: 'shares_count', width: 100, render: intFormatter, align: 'right' as const },
    { title: '曝光', dataIndex: 'impressions', width: 110, render: intFormatter, align: 'right' as const },
    { title: '点击', dataIndex: 'clicks', width: 100, render: intFormatter, align: 'right' as const },
    { title: '访问', dataIndex: 'visits', width: 100, render: intFormatter, align: 'right' as const },
    { title: '转化', dataIndex: 'conversions', width: 100, render: intFormatter, align: 'right' as const },
  ];

  if (loading) {
    return (
      <div>
        <h3 style={{ marginBottom: 16 }}>数据分析</h3>
        <Row gutter={[16, 16]}>
          {[1, 2, 3, 4, 5, 6].map(i => (
            <Col xs={12} sm={8} md={4} key={i}>
              <SkeletonCard rows={2} />
            </Col>
          ))}
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} lg={12}>
            <SkeletonCard rows={6} />
          </Col>
          <Col xs={24} lg={12}>
            <SkeletonCard rows={6} />
          </Col>
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} lg={12}>
            <SkeletonCard rows={6} />
          </Col>
          <Col xs={24} lg={12}>
            <SkeletonCard rows={6} />
          </Col>
        </Row>
      </div>
    );
  }

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>数据分析</h3>
        </Col>
        <Col>
          <Space wrap>
            <Select
              value={days}
              onChange={(v: number) => setDays(v)}
              style={{ width: 120 }}
            >
              <Option value={7}>近7天</Option>
              <Option value={14}>近14天</Option>
              <Option value={30}>近30天</Option>
              <Option value={90}>近90天</Option>
            </Select>
            <Select
              allowClear
              placeholder="平台筛选"
              value={platformFilter}
              onChange={(v: string | undefined) => setPlatformFilter(v)}
              style={{ width: 160 }}
            >
              <Option value="x_twitter">X (Twitter)</Option>
              <Option value="youtube">YouTube</Option>
              <Option value="tiktok">TikTok</Option>
              <Option value="instagram">Instagram</Option>
              <Option value="facebook">Facebook</Option>
              <Option value="douyin">抖音</Option>
              <Option value="xiaohongshu">小红书</Option>
              <Option value="weibo">微博</Option>
              <Option value="zhihu">知乎</Option>
              <Option value="bilibili">哔哩哔哩</Option>
            </Select>
            <RangePicker size="small" />
          </Space>
        </Col>
      </Row>

      {/* ============ 1. 运营概览（dashboard.summary）============ */}
      <Card title="运营概览" size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="发布量"
              value={summary.publish_count || 0}
              prefix={<BarChartOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="发布成功率"
              value={summary.publish_success_rate || 0}
              suffix="%"
              precision={1}
              prefix={<RiseOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="定时任务数"
              value={summary.scheduled_count || 0}
              prefix={<ScheduleOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="审核通过率"
              value={summary.moderation_pass_rate || 0}
              suffix="%"
              precision={1}
              prefix={<SafetyCertificateOutlined />}
              valueStyle={{ color: '#13c2c2' }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="舆情预警"
              value={summary.sentiment_alerts || 0}
              prefix={<WarningOutlined />}
              valueStyle={{ color: '#fa8c16' }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="账号总数"
              value={totalAccounts}
              suffix={activeAccounts ? ` / 活跃 ${activeAccounts}` : ''}
              prefix={<TeamOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Col>
        </Row>
        {(summary.accounts || []).length > 0 && (
          <Row gutter={[8, 8]} style={{ marginTop: 12 }}>
            {(summary.accounts || []).map(a => (
              <Col key={a.platform} xs={12} sm={8} md={6} lg={4}>
                <Tag icon={<GlobalOutlined />} color="blue" style={{ marginTop: 4 }}>
                  {labelOf(a.platform)}：{a.total} / 活跃 {a.active}
                </Tag>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {/* ============ 2. 平台对比 + 发布趋势 ============ */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="平台对比" size="small">
            {platformComparisonChartData.length ? (
              <Column {...platformComparisonConfig} />
            ) : (
              <Empty description="暂无平台对比数据" />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="发布趋势" size="small">
            {(dashboard?.trends || []).length ? (
              <Line {...publishTrendConfig} />
            ) : (
              <Empty description="暂无趋势数据" />
            )}
          </Card>
        </Col>
      </Row>

      {/* ============ 3. 内容表现表格 ============ */}
      <Card title="内容表现" size="small" style={{ marginBottom: 16 }}>
        <Table
          rowKey="id"
          columns={contentColumns}
          dataSource={contentPerformance}
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <Empty description="暂无内容表现数据" /> }}
        />
      </Card>

      {/* ============ 4. 外部指标（涨粉/播放/引流/转化）============ */}
      <Card title="外部指标（涨粉 / 播放 / 引流 / 转化）" size="small" style={{ marginBottom: 16 }}>
        {externalMetricsChartData.length ? (
          <Line {...externalMetricsChartConfig} height={260} />
        ) : (
          <Empty description="暂无外部指标数据" style={{ marginBottom: 12 }} />
        )}
        <Table
          rowKey={(r) => `${r.metric_id || ''}-${r.platform}-${r.account_id || ''}-${r.metric_date || ''}`}
          columns={externalColumns}
          dataSource={externalMetrics}
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: true }}
          scroll={{ x: 'max-content' }}
          style={{ marginTop: 12 }}
          locale={{ emptyText: <Empty description="暂无外部指标明细" /> }}
        />
      </Card>

      {/* ============ 5. 底部 Tab：保留原线索维度数据 ============ */}
      <Card size="small">
        <Tabs
          defaultActiveKey="leads"
          items={[
            {
              key: 'leads',
              label: '线索数据',
              children: (
                <div>
                  <Row gutter={[16, 16]}>
                    <Col xs={12} sm={6}>
                      <Card size="small">
                        <Statistic
                          title="线索获取"
                          value={totalLeads}
                          prefix={<BarChartOutlined />}
                          valueStyle={{ color: '#1677ff' }}
                        />
                      </Card>
                    </Col>
                    <Col xs={12} sm={6}>
                      <Card size="small">
                        <Statistic
                          title="线索转化"
                          value={convertedLeads}
                          prefix={<RiseOutlined />}
                          valueStyle={{ color: '#52c41a' }}
                        />
                      </Card>
                    </Col>
                    <Col xs={12} sm={6}>
                      <Card size="small">
                        <Statistic
                          title="平均评分"
                          value={avgScore}
                          suffix="/100"
                          precision={1}
                          valueStyle={{ color: '#fa8c16' }}
                        />
                      </Card>
                    </Col>
                    <Col xs={12} sm={6}>
                      <Card size="small">
                        <Statistic
                          title="流失率"
                          value={lossRate}
                          suffix="%"
                          precision={1}
                          prefix={<FallOutlined />}
                          valueStyle={{ color: '#f5222d' }}
                        />
                      </Card>
                    </Col>
                  </Row>

                  <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
                    <Col xs={24} lg={12}>
                      <Card title="每日线索趋势" size="small">
                        {trends.length ? <Line {...trendConfig} /> : <Empty />}
                      </Card>
                    </Col>
                    <Col xs={24} lg={12}>
                      <Card title="意图类型分布" size="small">
                        {intentData.length ? <Column {...intentConfig} /> : <Empty />}
                      </Card>
                    </Col>
                  </Row>

                  <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
                    <Col xs={24} lg={12}>
                      <Card title="转化漏斗" size="small">
                        {funnelChartData.length ? <Funnel {...funnelConfig} /> : <Empty />}
                      </Card>
                    </Col>
                    <Col xs={24} lg={12}>
                      <Card title="平台分布" size="small">
                        {platformData.length ? <Pie {...platformConfig} /> : <Empty />}
                      </Card>
                    </Col>
                  </Row>
                </div>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
};

export default Analytics;
