import { useState, Suspense, lazy, useCallback } from 'react';
import { Alert, Tabs, Typography, Select, Card, Space } from 'antd';
import ErrorBoundary from '../components/ErrorBoundary';
import PageSkeleton from '../components/PageSkeleton';
import { PlatformProvider, usePlatform } from '../context/PlatformContext';
import { PLATFORM_LIST } from '../constants/platformThemes';

const { Title } = Typography;
const { Option } = Select;

const TrendingPanel = lazy(() => import('./xworkbench/TrendingPanel'));
const SentCommentsPanel = lazy(() => import('./xworkbench/SentCommentsPanel'));
const AnalyticsPanel = lazy(() => import('./xworkbench/AnalyticsPanel'));

const WorkbenchContent: React.FC = () => {
  const [activeTab, setActiveTab] = useState('trending');
  const { platform, theme, setPlatform } = usePlatform();

  // 4 个配置 Tab（监控设置/评论模板/通知渠道/回复规则）已迁移到「账号与互动」页面，避免重复
  const tabItems = [
    { key: 'trending', label: '热点内容' },
    { key: 'sent', label: '已发评论 & 回复' },
    { key: 'analytics', label: '效果分析' },
  ];

  const renderPanel = (key: string) => {
    switch (key) {
      case 'trending':
        return (
          <ErrorBoundary title="热点内容面板出错">
            <Suspense fallback={<PageSkeleton count={5} />}>
              <TrendingPanel />
            </Suspense>
          </ErrorBoundary>
        );
      case 'sent':
        return (
          <ErrorBoundary title="已发评论面板出错">
            <Suspense fallback={<PageSkeleton count={5} />}>
              <SentCommentsPanel />
            </Suspense>
          </ErrorBoundary>
        );
      case 'analytics':
        return (
          <ErrorBoundary title="效果分析面板出错">
            <Suspense fallback={<PageSkeleton count={5} />}>
              <AnalyticsPanel />
            </Suspense>
          </ErrorBoundary>
        );
      default:
        return null;
    }
  };

  const handleChange = useCallback((key: string) => setActiveTab(key), []);

  const IconComponent = theme.IconComponent;

  return (
    <div>
      <Card
        style={{
          background: theme.bgGradient,
          border: `1px solid ${theme.primaryColor}30`,
          marginBottom: 16,
        }}
        styles={{ body: { padding: '20px 24px' } }}
      >
        <Space align="center" style={{ width: '100%', justifyContent: 'space-between' }} wrap>
          <Space align="center" size={16}>
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: '50%',
                background: theme.iconBg,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontSize: 24,
              }}
            >
              <IconComponent />
            </div>
            <div>
              <Title level={4} style={{ margin: 0, color: theme.primaryColor }}>
                {theme.fullName}
              </Title>
              <div style={{ color: '#666', fontSize: 13, marginTop: 4 }}>
                使用流程:1. 在「热点内容」选择热门内容 → 2. 点击「视频拆解」选择目标平台一键发布 → 3. 在「已发评论」监控回复,AI 自动回复 → 4. 互动配置见「账号与互动」
              </div>
            </div>
          </Space>
          <Select
            value={platform}
            onChange={setPlatform}
            style={{ width: 180 }}
            size="large"
            variant="outlined"
          >
            {PLATFORM_LIST.map((p) => {
              const PIcon = p.IconComponent;
              return (
                <Option key={p.id} value={p.id}>
                  <Space>
                    <span style={{ color: p.primaryColor }}>
                      <PIcon />
                    </span>
                    {p.name}
                  </Space>
                </Option>
              );
            })}
          </Select>
        </Space>
      </Card>

      <Alert
        type="info"
        showIcon
        message="使用流程:1. 在「热点内容」选择热门内容 → 2. 点击「视频拆解」生成脚本分镜 → 3. 选择多平台一键发布 → 4. 在「已发评论」监控回复,AI 自动回复。互动量配置/监控设置/评论模板/通知渠道/回复规则 已迁移到「账号与互动」页面。"
        style={{ marginBottom: 16 }}
      />

      <Tabs
        activeKey={activeTab}
        onChange={handleChange}
        items={tabItems.map((item) => ({
          key: item.key,
          label: item.label,
          children: renderPanel(item.key),
        }))}
      />
    </div>
  );
};

const XWorkbench = () => {
  return (
    <PlatformProvider defaultPlatform="x">
      <WorkbenchContent />
    </PlatformProvider>
  );
};

export default XWorkbench;
