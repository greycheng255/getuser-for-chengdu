import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ConfigProvider, App as AntdApp, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useState, useEffect, lazy, Suspense } from 'react';
import { Spin } from 'antd';
import { bindMessageApi } from './utils/antdMessage';
import Layout from './components/Layout';
import AuthGuard from './components/AuthGuard';
import Dashboard from './pages/Dashboard';
import LeadList from './pages/LeadList';
import TaskManager from './pages/TaskManager';
import BusinessManager from './pages/BusinessManager';
import Analytics from './pages/Analytics';
import Settings from './pages/Settings';
import Login from './pages/Login';
import UserManagement from './pages/UserManagement';
import Mine from './pages/Mine';
import XWorkbench from './pages/XWorkbench';
import OpenNotebookCallback from './pages/OpenNotebookCallback';
// PRD 缺口补全方案 6.3 节：10 个新页面
import AlertCenter from './pages/AlertCenter';
import VideoGenConfig from './pages/VideoGenConfig';
import AccountManagement from './pages/AccountManagement';
import ReviewQueue from './pages/ReviewQueue';
import HotpointLibrary from './pages/HotpointLibrary';
import ScriptLibrary from './pages/ScriptLibrary';
import ViralReviews from './pages/ViralReviews';
import ExternalMetrics from './pages/ExternalMetrics';
import PromptLibrary from './pages/PromptLibrary';
import InteractionConfigPage from './pages/InteractionConfig';
import DMManager from './pages/DMManager';
import PublishSchedule from './pages/PublishSchedule';
import TalkingHead from './pages/TalkingHead';
import PipelineDashboard from './pages/PipelineDashboard';
import CommentMonitor from './pages/CommentMonitor';
import LocalLife from './pages/LocalLife';
import CustomerDispatch from './pages/CustomerDispatch';
import AiCustomerService from './pages/AiCustomerService';
// P1-6：操作日志页面（懒加载，避免影响首屏体积）
const SystemLogs = lazy(() => import('./pages/SystemLogs'));
// B6 营销素材管理 + C 类多平台发布中心（懒加载）
const MarketingMaterials = lazy(() => import('./pages/MarketingMaterials'));
const PublishCenter = lazy(() => import('./pages/PublishCenter'));

const PageFallback = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 300 }}>
    <Spin size="large" />
  </div>
);

// 桥接组件:从 antd App 上下文取出动态 message 实例并注入全局 holder,
// 使非组件代码(如 axios 拦截器)与早期静态调用都能消费 ConfigProvider 主题,
// 消除 antd "[antd: message] Static function can not consume context" 警告
function MessageBridge() {
  const { message } = AntdApp.useApp();
  useEffect(() => {
    bindMessageApi(message);
  }, [message]);
  return null;
}

function AnimatedRoutes() {
  const location = useLocation();

  return (
    <Routes location={location}>
      <Route path="/" element={<Dashboard />} />
      <Route path="/leads" element={<LeadList />} />
      <Route path="/tasks" element={<TaskManager />} />
      <Route path="/cookies" element={<Navigate to="/accounts" replace />} />
      <Route path="/business" element={<BusinessManager />} />
      <Route path="/analytics" element={<Analytics />} />
      <Route path="/users" element={<UserManagement />} />
      <Route path="/mine" element={<Mine />} />
      <Route path="/x-workbench" element={<XWorkbench />} />
      <Route path="/hotpoint" element={<Navigate to="/hotpoint-library" replace />} />
      <Route path="/alert-center" element={<AlertCenter />} />
      <Route path="/video-gen-config" element={<VideoGenConfig />} />
      <Route path="/accounts" element={<AccountManagement />} />
      <Route path="/bot-accounts" element={<Navigate to="/accounts" replace />} />
      <Route path="/publisher-accounts" element={<Navigate to="/accounts" replace />} />
      <Route path="/publish/accounts" element={<Navigate to="/accounts" replace />} />
      <Route path="/review-queue" element={<ReviewQueue />} />
      <Route path="/hotpoint-library" element={<HotpointLibrary />} />
      <Route path="/script-library" element={<ScriptLibrary />} />
      <Route path="/viral-reviews" element={<ViralReviews />} />
      <Route path="/external-metrics" element={<ExternalMetrics />} />
      <Route path="/prompt-library" element={<PromptLibrary />} />
      <Route path="/interaction-config" element={<InteractionConfigPage />} />
      <Route path="/dm-manager" element={<DMManager />} />
      <Route path="/publish-schedule" element={<PublishSchedule />} />
      <Route path="/talking-head" element={<TalkingHead />} />
      <Route path="/pipeline-dashboard" element={<PipelineDashboard />} />
      <Route path="/comment-monitor" element={<CommentMonitor />} />
      <Route path="/local-life" element={<LocalLife />} />
      <Route path="/customer-dispatch" element={<CustomerDispatch />} />
      <Route path="/ai-customer-service" element={<AiCustomerService />} />
      <Route
        path="/system-logs"
        element={
          <Suspense fallback={<PageFallback />}>
            <SystemLogs />
          </Suspense>
        }
      />
      <Route
        path="/marketing-materials"
        element={
          <Suspense fallback={<PageFallback />}>
            <MarketingMaterials />
          </Suspense>
        }
      />
      <Route
        path="/publish-center"
        element={
          <Suspense fallback={<PageFallback />}>
            <PublishCenter />
          </Suspense>
        }
      />
      <Route path="/settings" element={<Settings />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  const [isDark, setIsDark] = useState(() => {
    return localStorage.getItem('theme_mode') === 'dark';
  });

  useEffect(() => {
    localStorage.setItem('theme_mode', isDark ? 'dark' : 'light');
  }, [isDark]);

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: { colorPrimary: '#1677ff' },
      }}
    >
      <AntdApp>
        <MessageBridge />
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/integrations/opennotebook/callback" element={<OpenNotebookCallback />} />
            <Route
              path="/*"
              element={
                <AuthGuard>
                  <Layout isDark={isDark} onThemeChange={setIsDark}>
                    <AnimatedRoutes />
                  </Layout>
                </AuthGuard>
              }
            />
          </Routes>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}

export default App;
