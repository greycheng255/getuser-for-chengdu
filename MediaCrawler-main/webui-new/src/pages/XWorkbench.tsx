import { useState, Suspense, lazy, useCallback } from 'react';
import { Alert, Tabs, Typography } from 'antd';
import { TwitterOutlined } from '@ant-design/icons';
import ErrorBoundary from '../components/ErrorBoundary';
import PageSkeleton from '../components/PageSkeleton';

const { Title } = Typography;

// 代码分割:每个 Tab 面板按需加载,减小首屏 bundle 体积
const TrendingPanel = lazy(() => import('./xworkbench/TrendingPanel'));
const SentCommentsPanel = lazy(() => import('./xworkbench/SentCommentsPanel'));
const MonitorPanel = lazy(() => import('./xworkbench/MonitorPanel'));
const TemplatesPanel = lazy(() => import('./xworkbench/TemplatesPanel'));
const AnalyticsPanel = lazy(() => import('./xworkbench/AnalyticsPanel'));
const NotificationsPanel = lazy(() => import('./xworkbench/NotificationsPanel'));
const ReplyRulesPanel = lazy(() => import('./xworkbench/ReplyRulesPanel'));

/**
 * X Twitter 获客工作台主入口
 *
 * 子面板拆分至 ./xworkbench/ 目录(每个面板 lazy load,减小首屏体积):
 * - TrendingPanel       热点推文
 * - SentCommentsPanel   已发评论 & 回复
 * - MonitorPanel        监控设置
 * - TemplatesPanel      评论模板
 * - AnalyticsPanel      效果分析
 * - NotificationsPanel  通知渠道
 * - ReplyRulesPanel     回复规则
 *
 * Cookie 管理已统一在「我的」页面,此处不再重复展示。
 * 每个 Tab 内容用 ErrorBoundary 包裹,单面板出错不影响其他面板。
 */
const XWorkbench = () => {
  const [activeTab, setActiveTab] = useState('trending');

  const tabItems = [
    {
      key: 'trending',
      label: '热点推文',
      children: (
        <ErrorBoundary title="热点推文面板出错">
          <Suspense fallback={<PageSkeleton count={5} />}>
            <TrendingPanel />
          </Suspense>
        </ErrorBoundary>
      ),
    },
    {
      key: 'sent',
      label: '已发评论 & 回复',
      children: (
        <ErrorBoundary title="已发评论面板出错">
          <Suspense fallback={<PageSkeleton count={5} />}>
            <SentCommentsPanel />
          </Suspense>
        </ErrorBoundary>
      ),
    },
    {
      key: 'monitor',
      label: '监控设置',
      children: (
        <ErrorBoundary title="监控设置面板出错">
          <Suspense fallback={<PageSkeleton count={3} />}>
            <MonitorPanel />
          </Suspense>
        </ErrorBoundary>
      ),
    },
    {
      key: 'templates',
      label: '评论模板',
      children: (
        <ErrorBoundary title="评论模板面板出错">
          <Suspense fallback={<PageSkeleton count={5} />}>
            <TemplatesPanel />
          </Suspense>
        </ErrorBoundary>
      ),
    },
    {
      key: 'analytics',
      label: '效果分析',
      children: (
        <ErrorBoundary title="效果分析面板出错">
          <Suspense fallback={<PageSkeleton count={5} />}>
            <AnalyticsPanel />
          </Suspense>
        </ErrorBoundary>
      ),
    },
    {
      key: 'notifications',
      label: '通知渠道',
      children: (
        <ErrorBoundary title="通知渠道面板出错">
          <Suspense fallback={<PageSkeleton count={3} />}>
            <NotificationsPanel />
          </Suspense>
        </ErrorBoundary>
      ),
    },
    {
      key: 'reply-rules',
      label: '回复规则',
      children: (
        <ErrorBoundary title="回复规则面板出错">
          <Suspense fallback={<PageSkeleton count={3} />}>
            <ReplyRulesPanel />
          </Suspense>
        </ErrorBoundary>
      ),
    },
  ];

  const handleChange = useCallback((key: string) => setActiveTab(key), []);

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>
        <TwitterOutlined style={{ color: '#1DA1F2', marginRight: 8 }} />
        X Twitter 获客工作台
      </Title>
      <Alert
        type="info"
        showIcon
        message="使用流程:1. 在「热点推文」选择热门内容 → 2. 点击「视频拆解」生成脚本分镜 → 3. 生成评论并发送到 X.com → 4. 在「已发评论」监控回复,AI 自动回复。"
        style={{ marginBottom: 16 }}
      />
      <Tabs activeKey={activeTab} onChange={handleChange} items={tabItems} />
    </div>
  );
};

export default XWorkbench;
