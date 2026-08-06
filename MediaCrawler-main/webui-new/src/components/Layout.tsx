import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Layout as AntLayout, Menu, Badge, Button, theme, Popover, Dropdown, Avatar, type MenuProps } from 'antd';
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
  TeamOutlined,
  BarChartOutlined,
  CrownOutlined,
  TwitterOutlined,
  FireOutlined,
  AlertOutlined,
  VideoCameraOutlined,
  AuditOutlined,
  MessageOutlined,
  TrophyOutlined,
  LineChartOutlined,
  ExperimentOutlined,
  InteractionOutlined,
  ScheduleOutlined,
  GiftOutlined,
  CloudUploadOutlined,
  ThunderboltOutlined,
  ShopOutlined,
  EnvironmentOutlined,
  CommentOutlined,
  CustomerServiceOutlined,
  AppstoreOutlined,
  KeyOutlined,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { useNotices, NoticeList } from './GlobalNotice';
import OnboardingTour from './OnboardingTour';
import HotpointAlertToast from './HotpointAlertToast';
import { authStorage } from '../api/auth';

const { Header, Sider, Content } = AntLayout;

declare global {
  interface Window {
    __restartOnboarding?: () => void;
  }
}

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

// 菜单项支持 requiredPermission 字段(阶段三 P2-6 细粒度 RBAC)
// 未指定 requiredPermission 的菜单项默认所有登录用户可见
interface MenuItemConfig {
  key: string;
  icon?: React.ReactNode;
  label: string;
  requiredPermission?: string;
  children?: MenuItemConfig[];
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

  // 细粒度 RBAC: 加载当前用户权限码列表(阶段三 P2-6)
  const [permissions, setPermissions] = useState<string[]>([]);
  const permissionsLoaded = useRef(false);

  useEffect(() => {
    if (permissionsLoaded.current) return;
    permissionsLoaded.current = true;
    const loadPermissions = async () => {
      try {
        const token = authStorage.getToken();
        if (!token) return;
        const resp = await fetch('/api/auth/permissions', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (resp.ok) {
          const data = await resp.json();
          setPermissions(data.permissions || []);
        }
      } catch (e) {
        // 权限加载失败时不阻塞菜单渲染(fallback 到显示全部)
        console.warn('加载权限列表失败', e);
      }
    };
    loadPermissions();
  }, []);

  // 判断用户是否拥有指定权限码(admin 或拥有该权限码则通过)
  const hasPermission = (code?: string): boolean => {
    if (!code) return true; // 未指定权限的菜单项默认可见
    if (isAdmin) return true;
    return permissions.includes(code);
  };

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
  // 菜单项配置 requiredPermission 字段,无权限的菜单项不渲染(阶段三 P2-6)
  const allMenuItems: MenuItemConfig[] = [
    { key: '/', icon: <DashboardOutlined />, label: '工作台' },
    { key: '/tasks', icon: <RobotOutlined />, label: '获客中心' },
    { key: '/leads', icon: <UserOutlined />, label: '客户线索' },
    { key: '/mine', icon: <CrownOutlined />, label: '我的' },
    // Cookie 与账号池管理（原设计归属于"我的"下的 Cookie管理）
    { key: '/cookies', icon: <KeyOutlined />, label: 'Cookie管理' },
    // PRD 缺口补全：内容运营矩阵
    {
      key: 'grp_content',
      icon: <VideoCameraOutlined />,
      label: '内容运营',
      children: [
        { key: '/pipeline-dashboard', icon: <ThunderboltOutlined />, label: '自动化流水线' },
        { key: '/hotpoint-library', icon: <FireOutlined />, label: '热点中心', requiredPermission: 'hotpoint:view' },
        { key: '/video-gen-config', icon: <VideoCameraOutlined />, label: '视频参数配置' },
        { key: '/prompt-library', icon: <ExperimentOutlined />, label: '提示词库' },
        { key: '/script-library', icon: <MessageOutlined />, label: '话术库', requiredPermission: 'interactor:config' },
        { key: '/review-queue', icon: <AuditOutlined />, label: '人工复核', requiredPermission: 'moderation:review' },
        { key: '/publish-schedule', icon: <ScheduleOutlined />, label: '发布调度管理', requiredPermission: 'scheduling:manage' },
        { key: '/marketing-materials', icon: <GiftOutlined />, label: '营销素材' },
        { key: '/publish-center', icon: <CloudUploadOutlined />, label: '发布中心' },
      ],
    },
    // PRD 缺口补全：账号与互动（含私信管理 — 私信本质是机器人账号与用户的互动）
    {
      key: 'grp_account',
      icon: <TeamOutlined />,
      label: '账号与互动',
      children: [
        { key: '/x-workbench', icon: <TwitterOutlined />, label: '互动监控', requiredPermission: 'interactor:view' },
        { key: '/accounts', icon: <TeamOutlined />, label: '账号管理' },
        { key: '/interaction-config', icon: <InteractionOutlined />, label: '互动量配置', requiredPermission: 'interactor:config' },
        { key: '/dm-manager', icon: <MessageOutlined />, label: '私信管理', requiredPermission: 'dm:view' },
        { key: '/talking-head', icon: <VideoCameraOutlined />, label: '数字人口播' },
      ],
    },
    // PRD 缺口补全：风控预警与数据
    {
      key: 'grp_data',
      icon: <BarChartOutlined />,
      label: '风控与数据',
      children: [
        { key: '/analytics', icon: <LineChartOutlined />, label: '数据分析', requiredPermission: 'analytics:view' },
        { key: '/alert-center', icon: <AlertOutlined />, label: '预警中心' },
        { key: '/external-metrics', icon: <LineChartOutlined />, label: '外部数据看板', requiredPermission: 'analytics:view' },
        { key: '/viral-reviews', icon: <TrophyOutlined />, label: '爆款复盘', requiredPermission: 'analytics:view' },
        // P1-6：操作日志（接入 audit_logs 表）
        { key: '/system-logs', icon: <AuditOutlined />, label: '操作日志' },
      ],
    },
    // 本地获客：评论监控 + 本地生活 + 客户分配 + AI客服
    {
      key: 'grp_local_acquisition',
      icon: <ShopOutlined />,
      label: '本地获客',
      children: [
        { key: '/comment-monitor', icon: <CommentOutlined />, label: '评论监控' },
        { key: '/local-life', icon: <EnvironmentOutlined />, label: '本地生活' },
        { key: '/customer-dispatch', icon: <AppstoreOutlined />, label: '客户分配调度' },
        { key: '/ai-customer-service', icon: <CustomerServiceOutlined />, label: 'AI 客服' },
      ],
    },
    { key: '/settings', icon: <SettingOutlined />, label: '设置', requiredPermission: 'system:config' },
  ];

  // 按权限过滤菜单项(递归过滤子菜单;若父菜单的子项全部被过滤掉,则父菜单也不渲染)
  const filterMenuItems = (items: MenuItemConfig[]): NonNullable<MenuProps['items']> => {
    const result: NonNullable<MenuProps['items']> = [];
    for (const item of items) {
      if (!hasPermission(item.requiredPermission)) continue;
      if (item.children && item.children.length > 0) {
        const filteredChildren = filterMenuItems(item.children);
        if (filteredChildren.length === 0) continue; // 子项全部无权限,父菜单不渲染
        result.push({
          key: item.key,
          icon: item.icon,
          label: item.label,
          children: filteredChildren,
        });
      } else {
        result.push({
          key: item.key,
          icon: item.icon,
          label: item.label,
        });
      }
    }
    return result;
  };

  const menuItems = useMemo(
    () => filterMenuItems(allMenuItems),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [permissions, isAdmin],
  );

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
                      window.__restartOnboarding?.();
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
      <HotpointAlertToast />
    </AntLayout>
  );
};

export default Layout;
