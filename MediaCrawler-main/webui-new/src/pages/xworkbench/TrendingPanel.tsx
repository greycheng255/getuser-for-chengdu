import { message } from '../../utils/antdMessage';
import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { Card, Input, Tag, Button, Space, Empty, Switch, Tooltip, Typography, Checkbox, Modal, Progress, Alert } from 'antd';
import {
  FireOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  ScheduleOutlined,
  LoadingOutlined,
  VideoCameraOutlined,
  SelectOutlined,
  CloseOutlined,
  SendOutlined,
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
import CommentComposeModal from './CommentComposeModal';
import TrendingList from './TrendingList';
import PageSkeleton from '../../components/PageSkeleton';
import { usePlatform } from '../../context/PlatformContext';

const { Text } = Typography;

/**
 * 热点内容面板
 * 展示热点内容列表 + 平台实时采集控制台
 */
const TrendingPanel: React.FC = () => {
  const { platform, theme } = usePlatform();
  const [loading, setLoading] = useState(false);
  const [posts, setPosts] = useState<WorkbenchPost[]>([]);
  const [keyword, setKeyword] = useState('');
  const [hasVideo, setHasVideo] = useState(false);
  const [platforms, setPlatforms] = useState<PlatformInfo[]>([]);
  const [sourceLabel, setSourceLabel] = useState<string>('');
  const [totalInDb, setTotalInDb] = useState<number>(0);
  const [addedCount, setAddedCount] = useState<number>(0);
  const [selectedPost, setSelectedPost] = useState<WorkbenchPost | null>(null);
  const [breakdownModal, setBreakdownModal] = useState(false);

  // 评论撰写 Modal（生成评论/发送评论/生成发布文案，从 BreakdownModal 迁出）
  const [commentPost, setCommentPost] = useState<WorkbenchPost | null>(null);
  const [commentModal, setCommentModal] = useState(false);

  // 批量选择
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  // 批量拆解进度
  const [batchProgress, setBatchProgress] = useState<BatchBreakdownProgressEvent | null>(null);
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);

  // 一键拆解全流程（独立于视频拆解）
  const [pipelinePost, setPipelinePost] = useState<WorkbenchPost | null>(null);
  const [pipelineModalOpen, setPipelineModalOpen] = useState(false);
  const [pipelineTaskId, setPipelineTaskId] = useState<string>('');
  const [pipelineStatus, setPipelineStatus] = useState<any>(null);
  const [pipelinePolling, setPipelinePolling] = useState(false);
  const pipelinePollingRef = useRef<number | null>(null);

  const PIPELINE_STEPS = ['待启动', '视频拆解', '生成解说视频', '生成发布文案', 'AI自动选文案', '自动填入视频URL', '发布到X'];

  // WebSocket
  const wsRef = useRef<WebSocket | null>(null);

  // X 采集相关状态
  const [crawlStatus, setCrawlStatus] = useState<CrawlStatus | null>(null);
  const [crawlLoading, setCrawlLoading] = useState(false);
  const [scheduledRunning, setScheduledRunning] = useState(false);

  // 用 ref 替代 window 全局变量,追踪已处理的采集完成事件(避免重复提示)
  const lastHandledCrawlRef = useRef(0);
  // 追踪最新一次 loadTrending 请求的 id，用于丢弃过期响应（race condition 守卫）
  // 场景：切换平台时旧请求(x，1975条慢)的响应可能在新请求(bilibili，30条快)之后返回，
  // 若不丢弃会把 bilibili 数据覆盖成 x 数据
  const loadReqIdRef = useRef(0);

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
    // 每次调用递增 reqId，过期请求的响应会被丢弃
    const reqId = ++loadReqIdRef.current;
    setLoading(true);
    try {
      const r = await xWorkbenchApi.getTrending({ limit: 500, keyword, has_video: hasVideo, platform });
      // race condition 守卫：若期间又发起了新请求（如切换平台），丢弃本次过期响应
      if (reqId !== loadReqIdRef.current) return;
      setPosts(r.items || []);
      const src = r.source === 'database' ? '数据库' : r.source === 'hotpoint' ? `热点聚合(${r.platform_name || platform})` : r.source;
      setSourceLabel(src);
      setTotalInDb((r as any).total_in_db || 0);
      setAddedCount((r as any).added_count || 0);
      if ((r as any).persisted > 0) {
        message.success((r as any).hint || `已自动入库 ${(r as any).persisted} 条`);
      }
    } catch (e: any) {
      if (reqId !== loadReqIdRef.current) return;
      message.error('加载热点失败: ' + (e?.message || ''));
      setPosts([]);
    } finally {
      // 仅当本次请求仍是最新时才关闭 loading，避免被过期请求误关
      if (reqId === loadReqIdRef.current) {
        setLoading(false);
      }
    }
  }, [keyword, hasVideo, platform]);

  const startCrawl = useCallback(async () => {
    setCrawlLoading(true);
    try {
      const r = await xWorkbenchApi.crawlOnce('', 20, platform);
      if (r.success) {
        message.success(`${theme.name} 热点聚合采集已触发，正在获取最新热点...`);
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
  }, [refreshCrawlStatus, loadTrending, platform, theme.name]);

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
        // 所有平台都刷新（不再限制 platform === 'x'）
        loadTrending();
        message.success(`采集完成！本次新增 ${crawlStatus.crawled_count} 条数据`);
      }
    }
  }, [crawlStatus?.stage, crawlStatus?.finished_at]);

  const openBreakdown = useCallback((post: WorkbenchPost) => {
    setSelectedPost(post);
    setBreakdownModal(true);
  }, []);

  const openComment = useCallback((post: WorkbenchPost) => {
    setCommentPost(post);
    setCommentModal(true);
  }, []);

  // === 一键拆解全流程（独立按钮，与视频拆解隔离）===

  const stopPipelinePolling = useCallback(() => {
    if (pipelinePollingRef.current !== null) {
      window.clearTimeout(pipelinePollingRef.current);
      pipelinePollingRef.current = null;
    }
    setPipelinePolling(false);
  }, []);

  const pollPipelineStatus = useCallback(async (taskId: string) => {
    try {
      const r = await xWorkbenchApi.getAutoPipelineStatus(taskId);
      if (r.success) {
        setPipelineStatus(r.task);
        if (r.task.status === 'completed') {
          stopPipelinePolling();
          message.success('🎉 流水线执行完成！');
          if (r.task.tweet_url) {
            Modal.success({
              title: '发布成功！',
              content: (
                <div>
                  <p>推文链接: <a href={r.task.tweet_url} target="_blank" rel="noreferrer">{r.task.tweet_url}</a></p>
                  <p>推文ID: {r.task.tweet_id}</p>
                  <p>已自动开启评论监控，新评论将 AI 自动回复</p>
                </div>
              ),
            });
          }
          return;
        }
        if (r.task.status === 'failed') {
          stopPipelinePolling();
          message.error(`流水线失败: ${r.task.error_msg || '未知错误'}`);
          return;
        }
        pipelinePollingRef.current = window.setTimeout(() => pollPipelineStatus(taskId), 3000);
      }
    } catch {
      pipelinePollingRef.current = window.setTimeout(() => pollPipelineStatus(taskId), 5000);
    }
  }, [stopPipelinePolling]);

  const startAutoPipeline = useCallback(async (post: WorkbenchPost) => {
    // 打开流水线弹窗并立即启动
    setPipelinePost(post);
    setPipelineStatus({ status: 'running', current_step: 0, step_name: '待启动', step_detail: '任务创建中...' });
    setPipelineModalOpen(true);
    setPipelinePolling(true);

    try {
      const r = await xWorkbenchApi.startAutoPipeline(post.post_id, false);
      if (r.success && r.task_id) {
        setPipelineTaskId(r.task_id);
        setPipelineStatus({ status: 'running', current_step: 0, step_name: '待启动', step_detail: '任务已创建', post_id: post.post_id });
        message.info('🚀 流水线已启动，将自动完成所有步骤');
        pollPipelineStatus(r.task_id);
      } else {
        setPipelinePolling(false);
        setPipelineStatus({ status: 'failed', error_msg: r.message || '启动失败' });
        message.error(r.message || '启动失败');
      }
    } catch (e: any) {
      setPipelinePolling(false);
      setPipelineStatus({ status: 'failed', error_msg: e?.message || '启动异常' });
      message.error('启动异常: ' + (e?.message || ''));
    }
  }, [pollPipelineStatus]);

  const cancelPipeline = useCallback(async () => {
    if (!pipelineTaskId) return;
    try {
      stopPipelinePolling();
      await xWorkbenchApi.cancelAutoPipeline(pipelineTaskId);
      setPipelineStatus((prev: any) => prev ? { ...prev, status: 'failed', error_msg: '用户取消' } : null);
      message.warning('流水线已取消');
    } catch (e: any) {
      message.error('取消异常: ' + (e?.message || ''));
    }
  }, [pipelineTaskId, stopPipelinePolling]);

  const closePipelineModal = useCallback(() => {
    if (pipelinePolling) {
      // 流水线仍在运行，仅最小化（后台继续轮询）
      setPipelineModalOpen(false);
      return;
    }
    stopPipelinePolling();
    setPipelineModalOpen(false);
    setPipelineStatus(null);
    setPipelineTaskId('');
  }, [pipelinePolling, stopPipelinePolling]);

  // 组件卸载时停止轮询
  useEffect(() => {
    return () => stopPipelinePolling();
  }, [stopPipelinePolling]);

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

  // 用 useMemo 缓存数据源标签
  const sourceTag = useMemo(() => {
    if (!sourceLabel) return null;
    const countInfo = totalInDb > 0
      ? `（本次 ${posts.length} 条，数据库总计 ${totalInDb} 条${addedCount > 0 ? `，新增 ${addedCount} 条` : ''}）`
      : `（共 ${posts.length} 条）`;
    return (
      <Tag icon={<FireOutlined />} style={{ borderColor: theme.primaryColor, color: theme.primaryColor }}>
        数据源: {sourceLabel}{countInfo}
      </Tag>
    );
  }, [sourceLabel, posts.length, totalInDb, addedCount, theme.primaryColor]);

  return (
    <div>
      {/* 实时采集控制台：所有平台都显示（原 platform === 'x' 限制已移除） */}
      <Card size="small" style={{ marginBottom: 12, background: `${theme.primaryColor}08` }}>
        <Space wrap>
          <Text strong style={{ color: theme.primaryColor }}>{theme.name} 实时采集：</Text>
          <Tag color="cyan">数据源: 热点聚合（自动获取最新热点）</Tag>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={crawlLoading || crawlStatus?.running}
            onClick={startCrawl}
            style={{ backgroundColor: theme.primaryColor, borderColor: theme.primaryColor }}
          >
            {crawlStatus?.running ? '采集中...' : `触发${theme.name}热点聚合`}
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
              上次: {crawlStatus?.platform_name ? `${crawlStatus.platform_name} ` : ''}{crawlStatus?.stage === 'done' ? `成功（共${crawlStatus?.crawled_count ?? 0}条）` : `失败 ${crawlStatus?.error ?? ''}`}
            </Tag>
          )}
        </Space>
      </Card>

      <Space style={{ marginBottom: 16 }} wrap>
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
        <Empty description={`暂无${theme.name}热点内容，请先在「热点聚合」抓取`} />
      ) : (
        <TrendingList
          posts={posts}
          onOpenBreakdown={openBreakdown}
          onOpenComment={openComment}
          onStartAutoPipeline={startAutoPipeline}
          loading={loading}
          selectable={selectMode}
          selectedIds={selectedIds}
          onSelectChange={handleSelectChange}
          primaryColor={theme.primaryColor}
          PlatformIcon={theme.IconComponent}
        />
      )}

      {breakdownModal && selectedPost && (
        <BreakdownModal
          post={selectedPost}
          open={breakdownModal}
          onClose={() => setBreakdownModal(false)}
        />
      )}

      {commentModal && commentPost && (
        <CommentComposeModal
          post={commentPost}
          open={commentModal}
          onClose={() => setCommentModal(false)}
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
        mask={{ closable: !batchLoading }}
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

      {/* 一键拆解全流程 — 独立弹窗，与视频拆解完全隔离 */}
      <Modal
        title={
          <Space>
            <ThunderboltOutlined style={{ color: '#faad14' }} />
            <span>一键拆解全流程{pipelinePost ? ` - @${pipelinePost.username}` : ''}</span>
          </Space>
        }
        open={pipelineModalOpen}
        onCancel={closePipelineModal}
        width={680}
        footer={
          <Space>
            {pipelinePolling && (
              <Button danger onClick={cancelPipeline}>
                取消流水线
              </Button>
            )}
            <Button onClick={closePipelineModal}>
              {pipelinePolling ? '后台运行' : '关闭'}
            </Button>
          </Space>
        }
        mask={{ closable: !pipelinePolling }}
      >
        {pipelinePost && (
          <Typography.Paragraph ellipsis={{ rows: 2 }} type="secondary" style={{ marginBottom: 16 }}>
            {pipelinePost.content}
          </Typography.Paragraph>
        )}

        {!pipelineStatus ? (
          <Space>
            <LoadingOutlined style={{ color: '#faad14' }} />
            <Text>流水线启动中...</Text>
          </Space>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            {pipelineStatus.status === 'completed' && (
              <Alert
                type="success"
                showIcon
                message="✅ 流水线执行完成！"
                description={
                  pipelineStatus.tweet_url ? (
                    <span>
                      推文链接:{' '}
                      <a href={pipelineStatus.tweet_url} target="_blank" rel="noreferrer">
                        {pipelineStatus.tweet_url}
                      </a>
                    </span>
                  ) : '发布成功'
                }
              />
            )}
            {pipelineStatus.status === 'failed' && (
              <Alert
                type="error"
                showIcon
                message="❌ 流水线执行失败"
                description={pipelineStatus.error_msg || '未知错误'}
              />
            )}
            {(pipelineStatus.status === 'running' || pipelineStatus.status === 'completed') && (
              <Progress
                percent={pipelineStatus.status === 'completed' ? 100 : Math.round((pipelineStatus.current_step / 6) * 100)}
                status={pipelineStatus.status === 'completed' ? 'success' : 'active'}
              />
            )}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {PIPELINE_STEPS.slice(1).map((name, i) => {
                const stepNum = i + 1;
                const isDone = pipelineStatus.current_step > stepNum || pipelineStatus.status === 'completed';
                const isCurrent = pipelineStatus.current_step === stepNum && pipelineStatus.status === 'running';
                const isPending = pipelineStatus.current_step < stepNum && pipelineStatus.status === 'running';
                let color = 'default';
                let icon: React.ReactNode = <span>{stepNum}</span>;
                if (isDone) { color = 'success'; icon = '✓'; }
                else if (isCurrent) { color = 'processing'; icon = <LoadingOutlined />; }
                else if (isPending) { color = 'default'; }
                return (
                  <Tag key={stepNum} color={color as any} style={{ margin: 0 }}>
                    {icon} {name}
                  </Tag>
                );
              })}
            </div>
            {pipelineStatus.step_detail && pipelineStatus.status !== 'completed' && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                当前: {pipelineStatus.step_detail}
              </Text>
            )}
            {pipelineStatus.selected_content && (
              <Card size="small" title="AI 选中的发布文案" style={{ marginTop: 4 }}>
                <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                  {pipelineStatus.selected_content}
                </Typography.Paragraph>
              </Card>
            )}
            {pipelineStatus.tweet_url && pipelineStatus.status === 'completed' && (
              <div>
                <Text strong>发布结果:</Text>
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>推文ID: {pipelineStatus.tweet_id}</Text>
                </div>
                <Button
                  size="small"
                  type="link"
                  href={pipelineStatus.tweet_url}
                  target="_blank"
                  icon={<SendOutlined />}
                >
                  查看推文
                </Button>
              </div>
            )}
          </Space>
        )}
      </Modal>
    </div>
  );
};

export default TrendingPanel;
