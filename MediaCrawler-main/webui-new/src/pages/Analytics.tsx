import React, { useEffect, useState } from 'react';
import { Card, Row, Col, Statistic, Empty, Select, DatePicker, Space } from 'antd';
import { Column, Funnel, Line } from '@ant-design/charts';
import { RiseOutlined, FallOutlined, BarChartOutlined } from '@ant-design/icons';
import { getTrends, getPlatformAnalytics, getFunnelData } from '../api/dashboard';
import { getLeadStats } from '../api/leads';
import SkeletonCard from '../components/SkeletonCard';
import type { LeadStats } from '../types';
import { PLATFORM_MAP, INTENT_MAP } from '../types';

const { RangePicker } = DatePicker;
const { Option } = Select;

const Analytics: React.FC = () => {
  const [timeRange, setTimeRange] = useState('30');
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [trends, setTrends] = useState<Array<{ date: string; leads: number }>>([]);
  const [platformData, setPlatformData] = useState<Array<{ platform: string; count: number }>>([]);
  const [funnelData, setFunnelData] = useState<Array<{ status: string; count: number }>>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData();
  }, [timeRange]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [statsRes, trendsRes, platformRes, funnelRes] = await Promise.all([
        getLeadStats(),
        getTrends(parseInt(timeRange)),
        getPlatformAnalytics(),
        getFunnelData(),
      ]);
      setStats(statsRes);
      setTrends(trendsRes.trends || []);
      setPlatformData(platformRes.platform_distribution || []);
      setFunnelData(funnelRes.funnel || []);
    } catch (error) {
      console.error('Failed to fetch analytics data:', error);
    } finally {
      setLoading(false);
    }
  };

  const trendConfig = {
    data: trends.flatMap(item => [
      { date: item.date, value: item.leads, type: '新增线索' },
    ]),
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
      type: PLATFORM_MAP[item.platform] || item.platform,
      value: item.count,
    })),
    angleField: 'value',
    colorField: 'type',
    radius: 0.8,
    label: {
      type: 'outer' as const,
      content: '{name} {percentage}',
    },
    interactions: [{ type: 'element-active' }],
  };

  const funnelChartData = funnelData.map(item => ({
    stage: item.status === 'new' ? '新线索' :
           item.status === 'contacted' ? '已联系' :
           item.status === 'qualified' ? '已确认' :
           item.status === 'converted' ? '已转化' : item.status,
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

  const totalLeads = stats?.total_leads || 0;
  const convertedLeads = stats?.converted_leads || 0;
  const avgScore = stats?.avg_lead_score || 0;
  const lossRate = totalLeads > 0 ? ((totalLeads - convertedLeads) / totalLeads * 100) : 0;

  if (loading) {
    return (
      <div>
        <h3 style={{ marginBottom: 16 }}>数据统计</h3>
        <Row gutter={[16, 16]}>
          {[1, 2, 3, 4].map(i => (
            <Col xs={12} sm={6} key={i}><SkeletonCard rows={2} /></Col>
          ))}
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} lg={12}><SkeletonCard rows={6} /></Col>
          <Col xs={24} lg={12}><SkeletonCard rows={6} /></Col>
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} lg={12}><SkeletonCard rows={6} /></Col>
          <Col xs={24} lg={12}><SkeletonCard rows={6} /></Col>
        </Row>
      </div>
    );
  }

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>数据统计</h3>
        </Col>
        <Col>
          <Space>
            <Select value={timeRange} onChange={setTimeRange} style={{ width: 120 }}>
              <Option value="7">近7天</Option>
              <Option value="30">近30天</Option>
              <Option value="90">近90天</Option>
            </Select>
            <RangePicker size="small" />
          </Space>
        </Col>
      </Row>

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
          <Card title="每日线索趋势">
            {trends.length ? <Line {...trendConfig} /> : <Empty />}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="意图类型分布">
            {intentData.length ? <Column {...intentConfig} /> : <Empty />}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="转化漏斗">
            {funnelChartData.length ? <Funnel {...funnelConfig} /> : <Empty />}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="平台分布">
            {platformData.length ? <Pie {...platformConfig} /> : <Empty />}
          </Card>
        </Col>
      </Row>
    </div>
  );
};

// 补充Pie导入
import { Pie } from '@ant-design/charts';

export default Analytics;
