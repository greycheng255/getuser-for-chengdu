import React, { useState, useEffect, useMemo } from 'react';
import { Layout as AntLayout, Menu, Badge, Button, theme, Popover, Dropdown, Avatar } from 'antd';
import {
  DashboardOutlined,
  UserOutlined,
  SettingOutlined,
  RobotOutlined,
  BellOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  LogoutOutlined,
  MoonOutlined,
  SunOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  DollarOutlined,
  BarChartOutlined,
  CrownOutlined,
  TwitterOutlined,
  FireOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { useNotices, NoticeList } from './GlobalNotice';
import OnboardingTour from './OnboardingTour';
import { authStorage } from '../api/auth';

const { Header, Sider, Content } = AntLayout;

const roleLabels: Record<string, string> = {
  admin: '管理员',
  operator: '运营',
  viewer: '观察员',
};

interface LayoutProps {
  children: React.ReactNode;
  isDark?: boolean;
  onThemeChange?: (isDark: boolean) => void;
}

const Layout: React.FC<LayoutProps> = ({ children, isDark, onThemeChange }) => {
  const [collapsed, setCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const {
    token: { colorBgContainer },
  } = theme.useToken();
  const { notices, unreadCount, markRead, markAllRead, clearNotices } = useNotices();

  const currentUser = useMemo(() => authStorage.getUser(), []);
  const isAdmin = currentUser?.role === 'admin';
  const displayName = currentUser?.nickname || currentUser?.username || '用户';
  const roleText = roleLabels[currentUser?.role || ''] || '用户';

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
      if (window.innerWidth < 768) {
        setCollapsed(true);
      }
    };
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  // 简化导航(v6.6):8项精简为5项,提升信息密度
  // - 工作台:数据驾驶舱(原首页)
  // - 获客中心:任务管理+数据分析(Tab切换)
  // - 客户线索:线索列表+看板
  // - 我的:套餐状态+用量+Cookie管理+商业化(用户视角)
  // - 设置:系统配置(管理员可见用户管理)
  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: '工作台' },
    { key: '/tasks', icon: <RobotOutlined />, label: '获客中心' },
    { key: '/leads', icon: <UserOutlined />, label: '客户线索' },
    { key: '/mine', icon: <CrownOutlined />, label: '我的' },
    { key: '/x-workbench', icon: <RobotOutlined />, label: 'X 获客工作台' },
    { key: '/hotpoint', icon: <FireOutlined />, label: '热点聚合' },
    { key: '/settings', icon: <SettingOutlined />, label: '设置' },
  ];

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        theme="light"
        breakpoint="lg"
        collapsedWidth={isMobile ? 0 : 80}
        onCollapse={(collapsed) => setCollapsed(collapsed)}
        style={{
          boxShadow: '2px 0 8px rgba(0,0,0,0.06)',
          position: isMobile ? 'fixed' : 'relative',
          zIndex: 100,
          height: '100vh',
        }}
      >
        <div style={{ 
          height: 64, 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: collapsed ? 'center' : 'flex-start', 
          padding: collapsed ? 0 : '0 16px',
          borderBottom: '1px solid #f0f0f0',
          overflow: 'hidden',
          whiteSpace: 'nowrap',
        }}>
          <RobotOutlined style={{ fontSize: 24, color: '#1677ff', flexShrink: 0 }} />
          {!collapsed && (
            <span style={{ marginLeft: 12, fontSize: 16, fontWeight: 600, color: '#1677ff' }}>
              获客系统
            </span>
          )}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => {
            navigate(key);
            if (isMobile) setCollapsed(true);
          }}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <AntLayout>
        <Header style={{ 
          background: colorBgContainer, 
          padding: '0 24px', 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'space-between', 
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
          position: 'sticky',
          top: 0,
          zIndex: 99,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(!collapsed)}
              style={{ fontSize: 16 }}
            />
            <h2 style={{ margin: 0, fontSize: 18, color: '#262626' }}>
              获客系统
            </h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Button
              type="text"
              icon={isDark ? <SunOutlined /> : <MoonOutlined />}
              onClick={() => onThemeChange?.(!isDark)}
              title={isDark ? '切换亮色' : '切换暗色'}
            />
            <Popover
              content={
                <NoticeList
                  notices={notices}
                  onMarkRead={markRead}
                  onMarkAllRead={markAllRead}
                  onClear={clearNotices}
                />
              }
              trigger="click"
              open={noticeOpen}
              onOpenChange={setNoticeOpen}
              placement="bottomRight"
            >
              <Badge count={unreadCount} size="small">
                <BellOutlined style={{ fontSize: 20, color: '#595959', cursor: 'pointer' }} />
              </Badge>
            </Popover>
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'profile',
                    icon: <UserOutlined />,
                    label: `${displayName} (${roleText})`,
                    disabled: true,
                  },
                  {
                    key: 'restart_onboarding',
                    icon: <RobotOutlined />,
                    label: '查看新手引导',
                    onClick: () => {
                      (window as any).__restartOnboarding?.();
                    },
                  },
                  { type: 'divider' as const },
                  {
                    key: 'logout',
                    icon: <LogoutOutlined />,
                    label: '退出登录',
                    danger: true,
                    onClick: () => {
                      authStorage.clear();
                      navigate('/login');
                    },
                  },
                ],
              }}
              placement="bottomRight"
            >
              <Button type="text" icon={<Avatar size="small" icon={<UserOutlined />} style={{ backgroundColor: isAdmin ? '#f5222d' : '#1890ff' }} />}>
                {displayName}
              </Button>
            </Dropdown>
          </div>
        </Header>
        <Content style={{ 
          margin: isMobile ? 12 : 24, 
          padding: isMobile ? 12 : 24, 
          background: colorBgContainer, 
          borderRadius: 8, 
          minHeight: 280,
          overflow: 'auto',
        }}>
          {children}
        </Content>
      </AntLayout>
      <OnboardingTour />
    </AntLayout>
  );
};

export default Layout;
