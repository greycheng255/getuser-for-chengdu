import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ConfigProvider, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useState, useEffect } from 'react';
import Layout from './components/Layout';
import AuthGuard from './components/AuthGuard';
import Dashboard from './pages/Dashboard';
import LeadList from './pages/LeadList';
import TaskManager from './pages/TaskManager';
import CookieManager from './pages/CookieManager';
import BusinessManager from './pages/BusinessManager';
import Analytics from './pages/Analytics';
import Settings from './pages/Settings';
import Login from './pages/Login';
import UserManagement from './pages/UserManagement';
import Mine from './pages/Mine';
import XWorkbench from './pages/XWorkbench';
import Hotpoint from './pages/Hotpoint';

function AnimatedRoutes() {
  const location = useLocation();

  return (
    <Routes location={location}>
      <Route path="/" element={<Dashboard />} />
      <Route path="/leads" element={<LeadList />} />
      <Route path="/tasks" element={<TaskManager />} />
      <Route path="/cookies" element={<CookieManager />} />
      <Route path="/business" element={<BusinessManager />} />
      <Route path="/analytics" element={<Analytics />} />
      <Route path="/users" element={<UserManagement />} />
      <Route path="/mine" element={<Mine />} />
      <Route path="/x-workbench" element={<XWorkbench />} />
      <Route path="/hotpoint" element={<Hotpoint />} />
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
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
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
    </ConfigProvider>
  );
}

export default App;
