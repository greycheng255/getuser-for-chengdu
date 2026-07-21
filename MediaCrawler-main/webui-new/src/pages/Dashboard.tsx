import React, { useEffect, useState } from 'react';
import { Row, Col, Card, Statistic, Button, Badge, Tag, Space, Empty, Progress, Avatar, Tooltip, Typography, Divider } from 'antd';
import {
  ArrowUpOutlined,
  UserOutlined,
  FileAddOutlined,
  CheckCircleOutlined,
  PercentageOutlined,
  PlusOutlined,
  DownloadOutlined,
  RobotOutlined,
  RightOutlined,
  CrownOutlined,
  WalletOutlined,
  FileTextOutlined,
  MessageOutlined,
} from '@ant-design/icons';
import type { DashboardData, CrawlerTask } from '../types';
import { PLATFORM_MAP, INTENT_MAP } from '../types';
import { getDashboardData } from '../api/dashboard';
import { getTasks } from '../api/tasks';
import { getMyPlan, type PlanInfo } from '../api/plan';
import SkeletonCard from '../components/SkeletonCard';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useNavigate } from 'react-router-dom';

dayjs.extend(relativeTime);

const { Text } = Typography;

// 套餐颜色映射
const PLAN_COLORS: Record<string, string> = {
  free: '#8c8c8c',
  basic: '#1677ff',
  pro: '#722ed1',
  enterprise: '#fa8c16',
};

const PLAN_LABELS: Record<string, string> = {
  free: '免费版',
  basic: '基础版',
  pro: '专业版',
  enterprise: '企业版',
};

const Dashboard: React.FC = () => {
  const [data, setData] = useState<DashboardData | null>(null);
  const [tasks, setTasks] = useState<CrawlerTask[]>([]);
  const [plan, setPlan] = useState<PlanInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetchData(true);
    fetchTasks();
    fetchPlan();
    // 后台轮询:每 30 秒刷新(页面不可见时暂停,节省资源)
    const interval = setInterval(() => {
      if (document.hidden) return;
      fetchData(false);
      fetchTasks();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchData = async (isInitial: boolean = false) => {
    if (isInitial) setLoading(true);
    try {
      const res = await getDashboardData();
      setData(res);
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error);
    } finally {
      if (isInitial) setLoading(false);
    }
  };

  const fetchTasks = async () => {
    try {
      const res = await getTasks();
      setTasks(res);
    } catch (error) {
      console.error('Failed to fetch tasks:', error);
    }
  };

  const fetchPlan = async () => {
    try {
      const res = await getMyPlan();
      setPlan(res.plan);
    } catch (error) {
      console.error('Failed to fetch plan:', error);
    }
  };

  const runningTasks = tasks.filter(t => t.status === 'running');

  // 趋势数据
  const trendData = data?.trends?.map(item => ({
    date: item.date,
    value: item.leads,
  })) || [];

  if (loading) {
    return (
      <div>
        <Row gutter={[16, 16]}>
          {[1, 2, 3, 4].map(i => (
            <Col xs={24} sm={12} lg={6} key={i}>
              <SkeletonCard rows={2} />
            </Col>
          ))}
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
      {/* === 顶部:套餐状态条(v6.6 新增) === */}
      {plan && (
        <Card
          size="small"
          style={{
            marginBottom: 16,
            background: `linear-gradient(90deg, ${PLAN_COLORS[plan.plan_type] || '#8c8c8c'}10 0%, transparent 100%)`,
            border: `1px solid ${PLAN_COLORS[plan.plan_type] || '#8c8c8c'}30`,
          }}
        >
          <Row gutter={[16, 8]} align="middle">
            <Col flex="auto">
              <Space size="middle">
                <CrownOutlined style={{ fontSize: 20, color: PLAN_COLORS[plan.plan_type] || '#8c8c8c' }} />
                <div>
                  <Text strong>{PLAN_LABELS[plan.plan_type] || plan.plan_type}</Text>
                  {plan.is_active
                    ? <Tag color="success" style={{ marginLeft: 8 }}>有效</Tag>
                    : <Tag color="error" style={{ marginLeft: 8 }}>已过期</Tag>
                  }
                </div>
                <Divider type="vertical" />
                <Space split={<Divider type="vertical" />}>
                  <Tooltip title="已采集视频/笔记">
                    <Space size={4}>
                      <FileTextOutlined style={{ color: '#722ed1' }} />
                      <span>{plan.usage_notes_count}</span>
                      {plan.max_notes_per_task > 0 && (
                        <Text type="secondary" style={{ fontSize: 12 }}>/ {plan.max_notes_per_task}</Text>
                      )}
                    </Space>
                  </Tooltip>
                  <Tooltip title="已采集评论">
                    <Space size={4}>
                      <MessageOutlined style={{ color: '#fa8c16' }} />
                      <span>{plan.usage_comments_count}</span>
                    </Space>
                  </Tooltip>
                  <Tooltip title="已捕获线索">
                    <Space size={4}>
                      <UserOutlined style={{ color: '#52c41a' }} />
                      <span>{plan.usage_leads_count}</span>
                    </Space>
                  </Tooltip>
                  <Tooltip title="账户余额">
                    <Space size={4}>
                      <WalletOutlined style={{ color: '#52c41a' }} />
                      <span>¥{(plan.balance / 100).toFixed(2)}</span>
                    </Space>
                  </Tooltip>
                </Space>
              </Space>
            </Col>
            <Col>
              <Button type="link" onClick={() => navigate('/mine')} style={{ padding: 0 }}>
                管理套餐 <RightOutlined />
              </Button>
            </Col>
          </Row>
        </Card>
      )}

      {/* === 核心指标卡片 - 可点击下钻 === */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate('/leads')} style={{ cursor: 'pointer' }}>
            <Statistic
              title="今日新线索"
              value={data?.summary?.today_new || 0}
              prefix={<FileAddOutlined />}
              valueStyle={{ color: '#52c41a' }}
              suffix={data?.summary?.today_new ? <ArrowUpOutlined style={{ fontSize: 14 }} /> : null}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              累计 {data?.summary?.total_leads || 0} 条 <RightOutlined />
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate('/leads?status=new')} style={{ cursor: 'pointer' }}>
            <Statistic
              title="待处理"
              value={data?.summary?.pending_count || 0}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#fa8c16' }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              点击立即处理 <RightOutlined />
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate('/tasks')} style={{ cursor: 'pointer' }}>
            <Statistic
              title="运行中任务"
              value={runningTasks.length}
              prefix={<RobotOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              查看任务进度 <RightOutlined />
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="转化率"
              value={data?.summary?.conversion_rate || 0}
              prefix={<PercentageOutlined />}
              suffix="%"
              valueStyle={{ color: '#722ed1' }}
              precision={1}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              已转化 {(data?.summary as any)?.converted_count || 0} 条
            </div>
          </Card>
        </Col>
      </Row>

      {/* 快速开始区域 */}
      <Card style={{ marginTop: 16, background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', border: 'none' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ color: '#fff' }}>
            <h3 style={{ margin: 0, color: '#fff', fontSize: 20 }}>快速开始获客</h3>
            <p style={{ margin: '8px 0 0', opacity: 0.9 }}>选择平台、输入关键词，3步开启自动获客</p>
          </div>
          <Space>
            <Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => navigate('/tasks')} style={{ background: '#fff', color: '#667eea', border: 'none' }}>
              新建获客任务
            </Button>
            <Button size="large" icon={<DownloadOutlined />} onClick={() => navigate('/leads')} style={{ background: 'rgba(255,255,255,0.2)', color: '#fff', border: 'none' }}>
              导出线索
            </Button>
          </Space>
        </div>
      </Card>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* 最新线索 - 首页直接处理 */}
        <Col xs={24} lg={12}>
          <Card
            title="最新线索"
            extra={<Button type="link" onClick={() => navigate('/leads')}>查看全部</Button>}
          >
            {data?.recent_leads?.length ? (
              <div>
                {data.recent_leads.slice(0, 5).map(lead => (
                  <div key={lead.id} style={{ padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                          <Avatar size="small" icon={<UserOutlined />} />
                          <span style={{ fontWeight: 500 }}>{lead.nickname}</span>
                          <Tag color="blue">{PLATFORM_MAP[lead.platform] || lead.platform}</Tag>
                          <Badge count={lead.lead_score} style={{
                            backgroundColor: lead.lead_score >= 80 ? '#f5222d' : lead.lead_score >= 60 ? '#fa8c16' : '#52c41a',
                          }} />
                        </div>
                        <div style={{ color: '#666', fontSize: 13, lineHeight: 1.5 }}>
                          {lead.content?.slice(0, 60)}{lead.content?.length > 60 ? '...' : ''}
                        </div>
                        <div style={{ marginTop: 4, fontSize: 12, color: '#999' }}>
                          {dayjs(lead.create_time ? lead.create_time * 1000 : lead.add_ts).fromNow()} · {INTENT_MAP[lead.intent_type] || lead.intent_type}
                        </div>
                      </div>
                    </div>
                    <Space style={{ marginTop: 8 }}>
                      <Button size="small" type="primary" onClick={() => navigate('/leads', { state: { highlightId: lead.id } })}>处理</Button>
                      <Button size="small">忽略</Button>
                    </Space>
                  </div>
                ))}
              </div>
            ) : (
              <Empty description="暂无线索，快去创建任务吧" />
            )}
          </Card>
        </Col>

        {/* 右侧：趋势图 + 任务进度 */}
        <Col xs={24} lg={12}>
          <Card title="近7天获客趋势">
            {trendData.length > 0 ? (
              <div style={{ height: 200, display: 'flex', alignItems: 'flex-end', gap: 8, padding: '20px 0' }}>
                {(() => {
                  // maxVal 提到循环外,避免每次迭代重复计算
                  const maxVal = Math.max(...trendData.map(d => d.value), 1);
                  return trendData.map((item, i) => {
                    const height = (item.value / maxVal) * 160;
                    return (
                      <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                        <span style={{ fontSize: 12, color: '#666' }}>{item.value}</span>
                        <div style={{ width: '60%', height, background: '#1677ff', borderRadius: '4px 4px 0 0', minHeight: 4 }} />
                        <span style={{ fontSize: 12, color: '#999' }}>{item.date.slice(5)}</span>
                      </div>
                    );
                  });
                })()}
              </div>
            ) : <Empty description="暂无数据" />}
          </Card>

          {runningTasks.length > 0 && (
            <Card title="运行中的任务" style={{ marginTop: 16 }}>
              {runningTasks.map(task => {
                // 采集进度 = 已采集/目标采集量;目标为0时不显示百分比
                const crawlTarget = task.max_notes || 0;
                const crawlPercent = crawlTarget > 0
                  ? Math.min(100, Math.round((task.total_crawled / crawlTarget) * 100))
                  : 0;
                return (
                <div key={task.id} style={{ padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontWeight: 500 }}>{task.name}</span>
                    <Tag color="processing">运行中</Tag>
                  </div>
                  <Progress
                    percent={crawlPercent}
                    size="small"
                    status="active"
                    format={() => `${task.total_crawled}${crawlTarget > 0 ? `/${crawlTarget}` : ''}`}
                  />
                  <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                    已获客 {task.total_leads} 条 · {PLATFORM_MAP[task.platform] || task.platform}
                  </div>
                </div>
                );
              })}
              <Button type="link" block onClick={() => navigate('/tasks')} style={{ marginTop: 8 }}>
                查看全部任务
              </Button>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
};

export default Dashboard;
