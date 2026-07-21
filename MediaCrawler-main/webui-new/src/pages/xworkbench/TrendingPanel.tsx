import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  Card,
  Input,
  Tag,
  Button,
  Space,
  Empty,
  Switch,
  Tooltip,
  message,
  Typography,
  Select,
  Checkbox,
  Modal,
  Progress,
} from 'antd';
import {
  FireOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  ScheduleOutlined,
  LoadingOutlined,
  VideoCameraOutlined,
  SelectOutlined,
  CloseOutlined,
} from '@ant-design/icons';
import {
  xWorkbenchApi,
  connectWorkbenchWS,
  type WorkbenchPost,
  type PlatformInfo,
  type CrawlStatus,
  type WorkbenchWSEvent,
  type BatchBreakdownProgressEvent,
} from '../../api/xWorkbench';
import BreakdownModal from './BreakdownModal';
import TrendingList from './TrendingList';
import PageSkeleton from '../../components/PageSkeleton';

const { Text } = Typography;

/**
 * 热点推文面板
 * 展示热点推文列表 + X 实时采集控制台
 */
const TrendingPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [posts, setPosts] = useState<WorkbenchPost[]>([]);
  const [keyword, setKeyword] = useState('');
  const [hasVideo, setHasVideo] = useState(false);
  const [platform, setPlatform] = useState<string>('x');
  const [platforms, setPlatforms] = useState<PlatformInfo[]>([]);
  const [sourceLabel, setSourceLabel] = useState<string>('');
  const [totalInDb, setTotalInDb] = useState<number>(0);
  const [addedCount, setAddedCount] = useState<number>(0);
  const [selectedPost, setSelectedPost] = useState<WorkbenchPost | null>(null);
  const [breakdownModal, setBreakdownModal] = useState(false);

  // 批量选择
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  // 批量拆解进度
  const [batchProgress, setBatchProgress] = useState<BatchBreakdownProgressEvent | null>(null);
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);

  // WebSocket
  const wsRef = useRef<WebSocket | null>(null);

  // X 采集相关状态
  const [crawlStatus, setCrawlStatus] = useState<CrawlStatus | null>(null);
  const [crawlLoading, setCrawlLoading] = useState(false);
  const [scheduledRunning, setScheduledRunning] = useState(false);

  // 用 ref 替代 window 全局变量,追踪已处理的采集完成事件(避免重复提示)
  const lastHandledCrawlRef = useRef(0);

  const refreshCrawlStatus = useCallback(async () => {
    try {
      const [s, sch] = await Promise.all([
        xWorkbenchApi.crawlStatus(),
        xWorkbenchApi.scheduledStatus(),
      ]);
      setCrawlStatus(s);
      setScheduledRunning(sch.running);
    } catch {}
  }, []);

  const loadTrending = useCallback(async () => {
    setLoading(true);
    try {
      const r = await xWorkbenchApi.getTrending({ limit: 10000, keyword, has_video: hasVideo, platform });
      setPosts(r.items || []);
      const src = r.source === 'database' ? '数据库' : r.source === 'hotpoint' ? `热点聚合(${r.platform_name || platform})` : r.source;
      setSourceLabel(src);
      setTotalInDb((r as any).total_in_db || 0);
      setAddedCount((r as any).added_count || 0);
      if ((r as any).persisted > 0) {
        message.success((r as any).hint || `已自动入库 ${(r as any).persisted} 条`);
      }
    } catch (e: any) {
      message.error('加载热点失败: ' + (e?.message || ''));
      setPosts([]);
    } finally {
      setLoading(false);
    }
  }, [keyword, hasVideo, platform]);

  const startCrawl = useCallback(async () => {
    setCrawlLoading(true);
    try {
      const r = await xWorkbenchApi.crawlOnce('', 20);
      if (r.success) {
        message.success('热点聚合采集已触发，正在获取最新热点...');
        refreshCrawlStatus();
        loadTrending();
      } else {
        message.warning(r.message);
      }
    } catch (e: any) {
      message.error('启动失败: ' + (e?.message || ''));
    } finally {
      setCrawlLoading(false);
    }
  }, [refreshCrawlStatus, loadTrending]);

  const toggleScheduled = useCallback(async () => {
    try {
      if (scheduledRunning) {
        await xWorkbenchApi.scheduledStop();
        message.success('已停止定时采集');
      } else {
        await xWorkbenchApi.scheduledStart();
        message.success('已启动定时采集');
      }
      refreshCrawlStatus();
    } catch (e: any) {
      message.error('操作失败: ' + (e?.message || ''));
    }
  }, [scheduledRunning, refreshCrawlStatus]);

  useEffect(() => {
    xWorkbenchApi.getPlatforms().then((r) => setPlatforms(r.platforms || [])).catch(() => {});
    refreshCrawlStatus();
  }, []);

  // 采集进行中时每 3 秒轮询状态,空闲时停止轮询(节省带宽)
  useEffect(() => {
    if (!crawlStatus?.running) return;
    const t = setInterval(refreshCrawlStatus, 3000);
    return () => clearInterval(t);
  }, [crawlStatus?.running, refreshCrawlStatus]);

  // platform 或 hasVideo 变化时重新加载
  useEffect(() => {
    loadTrending();
  }, [platform, hasVideo]);

  // 采集完成后自动刷新列表(用 ref 防止重复触发)
  useEffect(() => {
    if (crawlStatus?.stage === 'done' && crawlStatus.finished_at > 0) {
      if (crawlStatus.finished_at !== lastHandledCrawlRef.current) {
        lastHandledCrawlRef.current = crawlStatus.finished_at;
        if (platform === 'x') loadTrending();
        message.success(`采集完成！本次新增 ${crawlStatus.crawled_count} 条数据`);
      }
    }
  }, [crawlStatus?.stage, crawlStatus?.finished_at]);

  const openBreakdown = useCallback((post: WorkbenchPost) => {
    setSelectedPost(post);
    setBreakdownModal(true);
  }, []);

  // WebSocket 消息处理
  const handleWSMessage = useCallback((event: WorkbenchWSEvent) => {
    if (event.type === 'batch_breakdown_progress' || event.event === 'batch_breakdown_progress') {
      setBatchProgress(event.data as BatchBreakdownProgressEvent);
    }
  }, []);

  // 建立 WebSocket 连接
  const ensureWS = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;
    const token = localStorage.getItem('auth_token');
    if (!token) return;
    const ws = connectWorkbenchWS(token, handleWSMessage);
    if (ws) wsRef.current = ws;
  }, [handleWSMessage]);

  // 切换选择模式
  const toggleSelectMode = useCallback(() => {
    if (selectMode) {
      setSelectMode(false);
      setSelectedIds([]);
    } else {
      setSelectMode(true);
      setSelectedIds([]);
    }
  }, [selectMode]);

  // 单个选择
  const handleSelectChange = useCallback((postId: string, checked: boolean) => {
    setSelectedIds((prev) =>
      checked ? [...prev, postId] : prev.filter((id) => id !== postId)
    );
  }, []);

  // 全选/取消全选
  const handleSelectAll = useCallback((checked: boolean) => {
    if (checked) {
      setSelectedIds(posts.map((p) => p.post_id));
    } else {
      setSelectedIds([]);
    }
  }, [posts]);

  // 批量拆解
  const startBatchBreakdown = useCallback(async () => {
    if (selectedIds.length === 0) {
      message.warning('请先选择要拆解的推文');
      return;
    }
    ensureWS();
    setBatchModalOpen(true);
    setBatchLoading(true);
    setBatchProgress({
      current: 0,
      total: selectedIds.length,
      success: 0,
      failed: 0,
    });
    try {
      const r = await xWorkbenchApi.batchBreakdown(selectedIds);
      if (r.success) {
        message.success(`批量拆解完成：成功 ${r.success_count} 条，失败 ${r.failed_count} 条`);
      } else {
        message.error('批量拆解失败');
      }
    } catch (e: any) {
      message.error('批量拆解失败: ' + (e?.message || ''));
    } finally {
      setBatchLoading(false);
    }
  }, [selectedIds, ensureWS]);

  // 关闭批量拆解弹窗
  const closeBatchModal = useCallback(() => {
    setBatchModalOpen(false);
    if (!batchLoading) {
      setBatchProgress(null);
    }
  }, [batchLoading]);

  // 用 useMemo 缓存平台下拉选项,避免每次 render 重新 map
  const platformOptions = useMemo(
    () => platforms.map((p) => ({ value: p.id, label: p.name })),
    [platforms],
  );

  // 用 useMemo 缓存数据源标签
  const sourceTag = useMemo(() => {
    if (!sourceLabel) return null;
    const countInfo = platform === 'x' && totalInDb > 0
      ? `（本次 ${posts.length} 条，数据库总计 ${totalInDb} 条${addedCount > 0 ? `，新增 ${addedCount} 条` : ''}）`
      : `（共 ${posts.length} 条）`;
    return (
      <Tag color="blue" icon={<FireOutlined />}>
        数据源: {sourceLabel}{countInfo}
      </Tag>
    );
  }, [sourceLabel, posts.length, platform, totalInDb, addedCount]);

  return (
    <div>
      {/* X 平台时显示采集控制台 */}
      {platform === 'x' && (
        <Card size="small" style={{ marginBottom: 12, background: '#fafafa' }}>
          <Space wrap>
            <Text strong>X 实时采集：</Text>
            <Tag color="cyan">数据源: 热点聚合（自动获取最新热点）</Tag>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={crawlLoading || crawlStatus?.running}
              onClick={startCrawl}
            >
              {crawlStatus?.running ? '采集中...' : '触发热点聚合'}
            </Button>
            <Button
              onClick={toggleScheduled}
              icon={<ScheduleOutlined />}
            >
              {scheduledRunning ? '停止定时' : '启动定时（每小时）'}
            </Button>
            <Button onClick={refreshCrawlStatus} icon={<ReloadOutlined />}>查询状态</Button>
            {crawlStatus?.running && (
              <Tag color="processing" icon={<LoadingOutlined />}>
                阶段: {crawlStatus.stage} | 关键词: {crawlStatus.keywords}
              </Tag>
            )}
            {!crawlStatus?.running && (crawlStatus?.finished_at ?? 0) > 0 && (
              <Tag color={crawlStatus?.stage === 'done' ? 'success' : 'error'}>
                上次: {crawlStatus?.stage === 'done' ? `成功（共${crawlStatus?.crawled_count ?? 0}条）` : `失败 ${crawlStatus?.error ?? ''}`}
              </Tag>
            )}
          </Space>
        </Card>
      )}

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          value={platform}
          onChange={setPlatform}
          style={{ width: 160 }}
          options={platformOptions}
          placeholder="选择平台"
        />
        <Input.Search
          placeholder="搜索关键词"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={loadTrending}
          style={{ width: 240 }}
          allowClear
        />
        <Tooltip title="只看含视频的推文">
          <Switch
            checked={hasVideo}
            onChange={setHasVideo}
            checkedChildren="视频"
            unCheckedChildren="全部"
          />
        </Tooltip>
        <Button icon={<ReloadOutlined />} onClick={loadTrending}>
          刷新
        </Button>
        <Button
          icon={selectMode ? <CloseOutlined /> : <SelectOutlined />}
          onClick={toggleSelectMode}
          type={selectMode ? 'default' : 'default'}
        >
          {selectMode ? '取消选择' : '批量选择'}
        </Button>
        {selectMode && (
          <>
            <Checkbox
              checked={selectedIds.length === posts.length && posts.length > 0}
              indeterminate={selectedIds.length > 0 && selectedIds.length < posts.length}
              onChange={(e) => handleSelectAll(e.target.checked)}
            >
              全选
            </Checkbox>
            <Tag color="blue">已选 {selectedIds.length} 条</Tag>
            <Button
              type="primary"
              icon={<VideoCameraOutlined />}
              onClick={startBatchBreakdown}
              disabled={selectedIds.length === 0}
            >
              批量拆解
            </Button>
          </>
        )}
        {sourceTag}
      </Space>

      {loading ? (
        <PageSkeleton count={5} />
      ) : posts.length === 0 ? (
        <Empty description="暂无热点推文，请先在「热点聚合」抓取" />
      ) : (
        <TrendingList
          posts={posts}
          onOpenBreakdown={openBreakdown}
          loading={loading}
          selectable={selectMode}
          selectedIds={selectedIds}
          onSelectChange={handleSelectChange}
        />
      )}

      {breakdownModal && selectedPost && (
        <BreakdownModal
          post={selectedPost}
          open={breakdownModal}
          onClose={() => setBreakdownModal(false)}
        />
      )}

      <Modal
        title="批量视频拆解"
        open={batchModalOpen}
        onCancel={closeBatchModal}
        footer={[
          <Button key="close" onClick={closeBatchModal}>
            {batchLoading ? '后台运行' : '关闭'}
          </Button>,
        ]}
        width={500}
        maskClosable={!batchLoading}
      >
        {batchProgress && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <Text>
                进度：{batchProgress.current} / {batchProgress.total}
              </Text>
            </div>
            <Progress
              percent={Math.round((batchProgress.current / batchProgress.total) * 100)}
              status={batchLoading ? 'active' : 'success'}
            />
            <Space style={{ marginTop: 16 }} wrap>
              <Tag color="success">成功 {batchProgress.success}</Tag>
              <Tag color="error">失败 {batchProgress.failed}</Tag>
            </Space>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default TrendingPanel;
