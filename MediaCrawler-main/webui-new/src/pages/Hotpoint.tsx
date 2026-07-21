import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Tabs,
  Card,
  List,
  Tag,
  Button,
  Space,
  Empty,
  Tooltip,
  Badge,
  Row,
  Col,
  Statistic,
  Input,
  message,
  Typography,
  Skeleton,
} from 'antd';
import {
  ReloadOutlined,
  FireOutlined,
  LinkOutlined,
  GlobalOutlined,
  HomeOutlined,
  SearchOutlined,
  CopyOutlined,
  ClockCircleOutlined,
  TrophyOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import {
  getHotpointList,
  refreshAllHotpoints,
  type HotpointList,
  type PlatformData,
  type HotItem,
} from '../api/hotpoint';

const { Text } = Typography;

// ==================== 辅助函数 ====================

/** 格式化热度值: > 1亿显示"X.X亿", > 1万显示"X.X万", 否则显示原值 */
function formatHotValue(hot: string | undefined): string {
  if (!hot) return '';
  const num = parseInt(hot, 10);
  if (isNaN(num)) return hot;
  if (num >= 100_000_000) return (num / 100_000_000).toFixed(1) + '亿';
  if (num >= 10_000) return (num / 10_000).toFixed(1) + '万';
  return String(num);
}

/** 获取排名样式: 前3名金银铜, 其他灰色 */
function getRankStyle(rank: number): { bg: string; color: string; isTop3: boolean } {
  if (rank === 1) return { bg: '#FFD700', color: '#fff', isTop3: true }; // 金
  if (rank === 2) return { bg: '#C0C0C0', color: '#fff', isTop3: true }; // 银
  if (rank === 3) return { bg: '#CD7F32', color: '#fff', isTop3: true }; // 铜
  return { bg: '#f0f0f0', color: '#999', isTop3: false };
}

/** 聚合所有平台的热点, 按热度值降序排序 */
function aggregateAllItems(data: HotpointList | null): Array<HotItem & { platformId: string; platformName: string; platformColor: string }> {
  if (!data) return [];
  const all: Array<HotItem & { platformId: string; platformName: string; platformColor: string }> = [];
  for (const region of ['china', 'global'] as const) {
    for (const [pid, pdata] of Object.entries(data[region] || {})) {
      for (const item of pdata.items || []) {
        all.push({
          ...item,
          platformId: pid,
          platformName: pdata.name,
          platformColor: pdata.color,
        });
      }
    }
  }
  // 按热度值降序排序
  all.sort((a, b) => {
    const ha = parseInt(a.hot, 10) || 0;
    const hb = parseInt(b.hot, 10) || 0;
    return hb - ha;
  });
  return all;
}

/** 复制链接到剪贴板 */
async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    message.success('链接已复制');
  } catch {
    message.error('复制失败,请手动复制');
  }
}

// ==================== 排名徽章组件 ====================

const RankBadge: React.FC<{ rank: number; size?: number }> = ({ rank, size = 32 }) => {
  const style = getRankStyle(rank);
  return (
    <div style={{
      width: size,
      height: size,
      borderRadius: '50%',
      backgroundColor: style.bg,
      color: style.color,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontWeight: 'bold',
      fontSize: style.isTop3 ? 16 : 14,
      flexShrink: 0,
      boxShadow: style.isTop3 ? `0 2px 6px ${style.bg}80` : 'none',
    }}>
      {style.isTop3 && rank === 1 ? '🥇' : style.isTop3 && rank === 2 ? '🥈' : style.isTop3 && rank === 3 ? '🥉' : rank}
    </div>
  );
};

// ==================== 热点项组件 ====================

interface HotItemCardProps {
  item: HotItem;
  showPlatform?: boolean;
  platformName?: string;
  platformColor?: string;
}

const HotItemCard: React.FC<HotItemCardProps> = ({ item, showPlatform, platformName, platformColor }) => {
  return (
    <List.Item
      actions={[
        item.hot ? (
          <Tooltip key="hot" title={`热度: ${item.hot}`}>
            <span style={{ color: '#FF4D4F', fontWeight: 500, whiteSpace: 'nowrap' }}>
              <FireOutlined /> {formatHotValue(item.hot)}
            </span>
          </Tooltip>
        ) : null,
        <Tooltip key="copy" title="复制链接">
          <Button
            type="text"
            size="small"
            icon={<CopyOutlined />}
            onClick={() => copyToClipboard(item.url)}
          />
        </Tooltip>,
        <Tooltip key="open" title="在新窗口打开">
          <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ whiteSpace: 'nowrap' }}>
            <LinkOutlined /> 打开
          </a>
        </Tooltip>,
      ].filter(Boolean)}
    >
      <List.Item.Meta
        avatar={<RankBadge rank={item.rank} />}
        title={
          <Space wrap align="start" size={[4, 4]}>
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: 'inherit',
                wordBreak: 'break-all',
                overflowWrap: 'anywhere',
                lineHeight: 1.5,
              }}
            >
              {item.title}
            </a>
            {showPlatform && platformName && (
              <Tag color={platformColor} style={{ margin: 0 }}>
                {platformName}
              </Tag>
            )}
          </Space>
        }
        description={
          <Space size="small" wrap>
            {item.author && <Tag color="blue">{item.author}</Tag>}
            {item.extra?.subreddit ? <Tag color="orange">r/{String(item.extra.subreddit)}</Tag> : null}
            {item.extra?.comments !== undefined ? (
              <Tag>评论 {String(item.extra.comments)}</Tag>
            ) : null}
          </Space>
        }
      />
    </List.Item>
  );
};

// ==================== 平台菜单项组件 ====================

interface PlatformMenuItemProps {
  name: string;
  color: string;
  count: number;
  active: boolean;
  onClick: () => void;
}

const PlatformMenuItem: React.FC<PlatformMenuItemProps> = ({ name, color, count, active, onClick }) => {
  return (
    <div
      onClick={onClick}
      style={{
        padding: '10px 14px',
        cursor: 'pointer',
        borderRadius: 6,
        background: active ? `${color}15` : 'transparent',
        borderLeft: active ? `3px solid ${color}` : '3px solid transparent',
        transition: 'all 0.2s',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 4,
      }}
    >
      <Space size={8}>
        <span style={{ color, fontSize: 16 }}>●</span>
        <Text strong={active} style={{ color: active ? color : undefined }}>
          {name}
        </Text>
      </Space>
      <Badge count={count} color={color} overflowCount={999} />
    </div>
  );
};

// ==================== 主组件 ====================

const Hotpoint: React.FC = () => {
  const [data, setData] = useState<HotpointList | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [activePlatform, setActivePlatform] = useState<string>('');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [lastUpdate, setLastUpdate] = useState<number>(0);
  const [activeTab, setActiveTab] = useState<string>('ranking');

  const fetchData = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    try {
      const result = await getHotpointList(forceRefresh);
      setData(result);
      setLastUpdate(Date.now());
      // 自动选择第一个平台
      if (!activePlatform && result.china) {
        const firstPlatform = Object.keys(result.china)[0];
        if (firstPlatform) setActivePlatform(firstPlatform);
      }
    } catch (error) {
      console.error('Failed to fetch hotpoint data:', error);
      message.error('获取热点数据失败');
    } finally {
      setLoading(false);
    }
  }, [activePlatform]);

  useEffect(() => {
    fetchData();
  }, []);

  // 区域切换时自动选择第一个平台
  useEffect(() => {
    if (data && activeTab !== 'ranking') {
      const region = activeTab as 'china' | 'global';
      const platforms = Object.keys(data[region] || {});
      if (platforms.length > 0 && !platforms.includes(activePlatform)) {
        setActivePlatform(platforms[0]);
      }
    }
  }, [activeTab, data, activePlatform]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetchData(true);
      message.success('已刷新热点数据');
    } finally {
      setRefreshing(false);
    }
  };

  const handleRefreshAll = async () => {
    setRefreshing(true);
    try {
      const result = await refreshAllHotpoints();
      message.success(result.message || '强制采集完成');
      await fetchData(false);
    } catch {
      message.error('强制采集失败');
    } finally {
      setRefreshing(false);
    }
  };

  // 统计
  const chinaPlatforms = useMemo(() => data?.china ? Object.entries(data.china) : [], [data]);
  const globalPlatforms = useMemo(() => data?.global ? Object.entries(data.global) : [], [data]);
  const totalItems = useMemo(() => {
    return chinaPlatforms.reduce((sum, [, p]) => sum + (p.items?.length || 0), 0) +
      globalPlatforms.reduce((sum, [, p]) => sum + (p.items?.length || 0), 0);
  }, [chinaPlatforms, globalPlatforms]);

  // 聚合所有热点（综合热搜榜）
  const allRankedItems = useMemo(() => aggregateAllItems(data), [data]);

  // 全局搜索过滤
  const searchMatch = useCallback((title: string) => {
    if (!searchKeyword) return true;
    return title.toLowerCase().includes(searchKeyword.toLowerCase());
  }, [searchKeyword]);

  // 综合热搜榜数据（Top 50 + 搜索过滤）
  const rankedItems = useMemo(() => {
    return allRankedItems
      .filter(item => searchMatch(item.title))
      .slice(0, 50);
  }, [allRankedItems, searchMatch]);

  // 当前平台数据
  const currentPlatformData: PlatformData | undefined = useMemo(() => {
    if (!data || !activePlatform) return undefined;
    return data.china[activePlatform] || data.global[activePlatform];
  }, [data, activePlatform]);

  // 当前平台过滤后的热点
  const filteredPlatformItems = useMemo(() => {
    return (currentPlatformData?.items || []).filter(item => searchMatch(item.title));
  }, [currentPlatformData, searchMatch]);

  // 格式化更新时间
  const formattedUpdateTime = useMemo(() => {
    if (!lastUpdate) return '-';
    const d = new Date(lastUpdate);
    return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }, [lastUpdate]);

  // 渲染综合热搜榜
  const renderRanking = () => {
    if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;
    if (rankedItems.length === 0) {
      return <Empty description={searchKeyword ? '未找到匹配的热点' : '暂无热点数据'} />;
    }
    return (
      <List
        dataSource={rankedItems}
        renderItem={(item) => (
          <HotItemCard
            item={item}
            showPlatform
            platformName={item.platformName}
            platformColor={item.platformColor}
          />
        )}
        pagination={{ pageSize: 20, size: 'small', showTotal: (t) => `共 ${t} 条` }}
      />
    );
  };

  // 渲染平台热点视图（国内/国外）
  const renderPlatformView = (region: 'china' | 'global') => {
    const platforms = region === 'china' ? chinaPlatforms : globalPlatforms;
    if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;
    if (platforms.length === 0) {
      return <Empty description="暂无平台数据" />;
    }

    return (
      <Row gutter={[12, 12]} style={{ minHeight: 400 }}>
        {/* 左侧平台菜单 */}
        <Col xs={24} sm={6} md={5}>
          <Card size="small" styles={{ body: { padding: 8 } }}>
            {platforms.map(([pid, pdata]) => (
              <PlatformMenuItem
                key={pid}
                name={pdata.name}
                color={pdata.color}
                count={pdata.items?.length || 0}
                active={activePlatform === pid}
                onClick={() => setActivePlatform(pid)}
              />
            ))}
          </Card>
        </Col>

        {/* 右侧热点列表 */}
        <Col xs={24} sm={18} md={19}>
          {currentPlatformData ? (
            <Card
              size="small"
              title={
                <Space>
                  <span style={{ color: currentPlatformData.color, fontSize: 18 }}>●</span>
                  <Text strong>{currentPlatformData.name}</Text>
                  <Tag>{filteredPlatformItems.length} 条热点</Tag>
                  {currentPlatformData.home && (
                    <a href={currentPlatformData.home} target="_blank" rel="noopener noreferrer">
                      <LinkOutlined /> 主页
                    </a>
                  )}
                </Space>
              }
            >
              {filteredPlatformItems.length === 0 ? (
                <Empty description={searchKeyword ? '未找到匹配的热点' : '暂无热点'} />
              ) : (
                <List
                  dataSource={filteredPlatformItems}
                  renderItem={(item) => <HotItemCard item={item} />}
                  pagination={{ pageSize: 15, size: 'small', showTotal: (t) => `共 ${t} 条` }}
                />
              )}
            </Card>
          ) : (
            <Empty description="请选择左侧平台" />
          )}
        </Col>
      </Row>
    );
  };

  return (
    <div>
      {/* === 顶部统计栏 === */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <Row gutter={20} style={{ flex: 1, minWidth: 300 }}>
            <Col>
              <Statistic
                title="国内平台"
                value={chinaPlatforms.length}
                suffix="个"
                prefix={<HomeOutlined style={{ color: '#52c41a' }} />}
              />
            </Col>
            <Col>
              <Statistic
                title="国外平台"
                value={globalPlatforms.length}
                suffix="个"
                prefix={<GlobalOutlined style={{ color: '#1890ff' }} />}
              />
            </Col>
            <Col>
              <Statistic
                title="热点总数"
                value={totalItems}
                suffix="条"
                prefix={<FireOutlined style={{ color: '#ff4d4f' }} />}
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Col>
            <Col>
              <Statistic
                title="最后更新"
                value={formattedUpdateTime}
                prefix={<ClockCircleOutlined style={{ color: '#faad14' }} />}
              />
            </Col>
          </Row>
          <Space wrap>
            <Input
              placeholder="全局搜索热点标题"
              prefix={<SearchOutlined />}
              value={searchKeyword}
              onChange={e => setSearchKeyword(e.target.value)}
              allowClear
              style={{ width: 220 }}
            />
            <Button
              icon={<ReloadOutlined />}
              onClick={handleRefresh}
              loading={refreshing}
            >
              刷新缓存
            </Button>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={handleRefreshAll}
              loading={refreshing}
            >
              强制采集
            </Button>
          </Space>
        </div>
      </Card>

      {/* === Tab 内容 === */}
      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'ranking',
              label: (
                <span>
                  <TrophyOutlined /> 综合热搜榜
                  <Badge count={allRankedItems.length} size="small" offset={[6, -2]} color="#ff4d4f" />
                </span>
              ),
              children: renderRanking(),
            },
            {
              key: 'china',
              label: (
                <span>
                  <HomeOutlined /> 国内热点 ({chinaPlatforms.length})
                </span>
              ),
              children: renderPlatformView('china'),
            },
            {
              key: 'global',
              label: (
                <span>
                  <GlobalOutlined /> 国外热点 ({globalPlatforms.length})
                </span>
              ),
              children: renderPlatformView('global'),
            },
          ]}
        />
      </Card>
    </div>
  );
};

export default Hotpoint;
