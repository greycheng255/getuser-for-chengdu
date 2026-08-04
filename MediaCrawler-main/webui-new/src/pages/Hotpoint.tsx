import { message } from '../utils/antdMessage';
import React, { useState, useEffect, useCallback } from 'react';
import { Tabs, Card, List, Tag, Button, Space, Spin, Empty, Tooltip, Badge, Row, Col, Statistic, Input } from 'antd';
import {
  ReloadOutlined,
  FireOutlined,
  LinkOutlined,
  GlobalOutlined,
  HomeOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import {
  getHotpointList,
  refreshAllHotpoints,
  type HotpointList,
  type PlatformData,
  type HotItem,
} from '../api/hotpoint';

const Hotpoint: React.FC = () => {
  const [data, setData] = useState<HotpointList | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeRegion, setActiveRegion] = useState<'china' | 'global'>('china');
  const [activePlatform, setActivePlatform] = useState<string>('');
  const [searchKeyword, setSearchKeyword] = useState('');

  const fetchData = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    try {
      const result = await getHotpointList(forceRefresh);
      setData(result);
      // 自动选择第一个平台
      if (!activePlatform && result[activeRegion]) {
        const firstPlatform = Object.keys(result[activeRegion])[0];
        if (firstPlatform) setActivePlatform(firstPlatform);
      }
    } catch (error) {
      console.error('Failed to fetch hotpoint data:', error);
      message.error('获取热点数据失败');
    } finally {
      setLoading(false);
    }
  }, [activePlatform, activeRegion]);

  useEffect(() => {
    fetchData();
  }, []);

  // 区域切换时自动选择第一个平台
  useEffect(() => {
    if (data && data[activeRegion]) {
      const platforms = Object.keys(data[activeRegion]);
      if (platforms.length > 0 && !platforms.includes(activePlatform)) {
        setActivePlatform(platforms[0]);
      }
    }
  }, [activeRegion, data, activePlatform]);

  const handleRefresh = async () => {
    await fetchData(true);
    message.success('已刷新所有平台热点');
  };

  const handleRefreshAll = async () => {
    setLoading(true);
    try {
      const result = await refreshAllHotpoints();
      message.success(`刷新完成: ${Object.entries(result.counts).map(([k, v]) => `${k}:${v}`).join(', ')}`);
      await fetchData(false);
    } catch (error) {
      message.error('强制刷新失败');
    } finally {
      setLoading(false);
    }
  };

  // 统计
  const chinaPlatforms = data?.china ? Object.keys(data.china) : [];
  const globalPlatforms = data?.global ? Object.keys(data.global) : [];
  const totalItems =
    chinaPlatforms.reduce((sum, p) => sum + (data!.china[p].items?.length || 0), 0) +
    globalPlatforms.reduce((sum, p) => sum + (data!.global[p].items?.length || 0), 0);

  // 当前平台数据
  const currentPlatformData: PlatformData | undefined =
    data && activePlatform
      ? (data.china[activePlatform] || data.global[activePlatform])
      : undefined;

  // 过滤搜索
  const filteredItems = (currentPlatformData?.items || []).filter(item =>
    !searchKeyword || item.title.toLowerCase().includes(searchKeyword.toLowerCase())
  );

  // 渲染单个热点项
  const renderItem = (item: HotItem) => {
    const rankColor = item.rank <= 3 ? ['#FF4D4F', '#FA8C16', '#FAAD14'][item.rank - 1] : '#999';
    return (
      <List.Item
        actions={[
          item.hot ? (
            <Tooltip key="hot" title="热度">
              <span style={{ color: '#FF4D4F' }}>
                <FireOutlined /> {item.hot}
              </span>
            </Tooltip>
          ) : null,
          <Tooltip key="open" title="在新窗口打开">
            <a href={item.url} target="_blank" rel="noopener noreferrer">
              <LinkOutlined /> 打开
            </a>
          </Tooltip>,
        ].filter(Boolean)}
      >
        <List.Item.Meta
          avatar={
            <div style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              backgroundColor: rankColor,
              color: '#fff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 'bold',
              fontSize: 14,
            }}>
              {item.rank}
            </div>
          }
          title={
            <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>
              {item.title}
            </a>
          }
          description={
            <Space size="small" wrap>
              {item.author && <Tag color="blue">{item.author}</Tag>}
              {item.extra?.subreddit ? <Tag color="orange">r/{String(item.extra.subreddit)}</Tag> : null}
              {item.extra?.comments !== undefined ? (
                <Tag>评论 {String(item.extra.comments)}</Tag>
              ) : null}
              {item.extra?.description ? (
                <Tooltip title={String(item.extra.description)}>
                  <span style={{ color: '#999', maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block' }}>
                    {String(item.extra.description).slice(0, 60)}
                  </span>
                </Tooltip>
              ) : null}
            </Space>
          }
        />
      </List.Item>
    );
  };

  // 平台 Tab
  const buildPlatformTabs = (region: 'china' | 'global') => {
    const platforms = data?.[region] || {};
    return Object.entries(platforms).map(([pid, pdata]) => ({
      key: pid,
      label: (
        <span>
          <Badge count={pdata.items?.length || 0} size="small" offset={[6, -2]} color={pdata.color}>
            <span style={{ color: pdata.color, marginRight: 4 }}>●</span>
            {pdata.name}
          </Badge>
        </span>
      ),
      children: (
        <List
          dataSource={(pdata.items || []).filter(item =>
            !searchKeyword || item.title.toLowerCase().includes(searchKeyword.toLowerCase())
          )}
          renderItem={renderItem}
          locale={{ emptyText: <Empty description="暂无热点数据" /> }}
          pagination={{ pageSize: 15, size: 'small' }}
        />
      ),
    }));
  };

  return (
    <div style={{ padding: 24 }}>
      {/* 顶部统计与操作 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <Row gutter={24} style={{ flex: 1 }}>
            <Col>
              <Statistic title="国内平台" value={chinaPlatforms.length} suffix="个" />
            </Col>
            <Col>
              <Statistic title="国外平台" value={globalPlatforms.length} suffix="个" />
            </Col>
            <Col>
              <Statistic title="热点总数" value={totalItems} suffix="条" />
            </Col>
          </Row>
          <Space>
            <Input
              placeholder="搜索热点标题"
              prefix={<SearchOutlined />}
              value={searchKeyword}
              onChange={e => setSearchKeyword(e.target.value)}
              allowClear
              style={{ width: 200 }}
            />
            <Button icon={<ReloadOutlined />} onClick={handleRefresh} loading={loading}>
              刷新缓存
            </Button>
            <Button type="primary" onClick={handleRefreshAll} loading={loading}>
              强制重新采集
            </Button>
          </Space>
        </div>
      </Card>

      <Card loading={loading && !data}>
        <Tabs
          activeKey={activeRegion}
          onChange={(key) => setActiveRegion(key as 'china' | 'global')}
          items={[
            {
              key: 'china',
              label: <span><HomeOutlined /> 国内热点 ({chinaPlatforms.length})</span>,
              children: (
                <Tabs
                  tabPosition="left"
                  activeKey={activePlatform}
                  onChange={setActivePlatform}
                  items={buildPlatformTabs('china')}
                  style={{ minHeight: 400 }}
                />
              ),
            },
            {
              key: 'global',
              label: <span><GlobalOutlined /> 国外热点 ({globalPlatforms.length})</span>,
              children: (
                <Tabs
                  tabPosition="left"
                  activeKey={activePlatform}
                  onChange={setActivePlatform}
                  items={buildPlatformTabs('global')}
                  style={{ minHeight: 400 }}
                />
              ),
            },
          ]}
        />
      </Card>

      {currentPlatformData && (
        <Card size="small" style={{ marginTop: 16 }}>
          <Space>
            <span style={{ color: currentPlatformData.color, fontWeight: 'bold' }}>
              ● {currentPlatformData.name}
            </span>
            <a href={currentPlatformData.home} target="_blank" rel="noopener noreferrer">
              <LinkOutlined /> 访问平台主页
            </a>
          </Space>
        </Card>
      )}
    </div>
  );
};

export default Hotpoint;
