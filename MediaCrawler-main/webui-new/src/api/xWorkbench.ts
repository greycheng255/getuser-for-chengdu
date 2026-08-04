import request from './request';
import axios from 'axios';

// ==================== 类型定义 ====================

export interface WorkbenchPost {
  post_id: string;
  post_url: string;
  username: string;
  nickname: string;
  content: string;
  video_url: string;
  image_urls: string;
  likes_count: string;
  retweets_count: string;
  replies_count: string;
  views_count: string;
  created_at: number;
  source_keyword: string;
}

export interface PlatformInfo {
  id: string;
  name: string;
  color: string;
  region: string;
}

export interface CrawlStatus {
  running: boolean;
  started_at: number;
  finished_at: number;
  keywords: string;
  error: string;
  crawled_count: number;
  stage: 'idle' | 'starting' | 'crawling' | 'saving' | 'done' | 'failed' | 'cancelled';
  platform?: string;
  platform_name?: string;
}

export interface TrendingResp {
  source: string;
  platform?: string;
  platform_name?: string;
  platform_color?: string;
  total: number;
  items: WorkbenchPost[];
  error?: string;
}

export interface BreakdownResp {
  source: string;
  post_id: string;
  script: string;
  storyboards: string[] | string;
  key_points: string[] | string;
  suggested_comments: string[] | string;
  full_text?: string;
}

export interface GenerateCommentsResp {
  post_id: string;
  comments: string[];
}

export interface ExplainerVideoCreateResp {
  post_id: string;
  task_id: string;
  status: string;
  model: 'kwvideo-v2' | 'kwvideo-v2-ref';
  model_name: string;
  reference_count: number;
}

export interface ExplainerVideoStatusResp {
  task_id: string;
  status: string;
  is_final: boolean;
  progress: number;
  current_step: string;
  result_url: string;
  result_reference?: string;
  error: string;
  cost: number;
}

export interface SendCommentResp {
  success: boolean;
  mode: 'real' | 'draft';
  message: string;
  sent_comment_id: number;
  comment_url: string;
}

export interface SentComment {
  id: number;
  post_id: string;
  post_url: string;
  post_content: string;
  post_username: string;
  video_url: string;
  comment_content: string;
  comment_url: string;
  sent_status: 'pending' | 'success' | 'failed' | 'draft';
  sent_error: string;
  sent_at: number;
  source: string;
  monitoring: number;
  reply_count: number;
  auto_replied_count: number;
  last_check_ts: number;
}

export interface ReplyRecord {
  id: number;
  reply_id: string;
  reply_url: string;
  replier_username: string;
  replier_nickname: string;
  replier_avatar: string;
  reply_content: string;
  reply_likes_count: string;
  reply_created_at: number;
  auto_reply_status: 'pending' | 'sent' | 'failed' | 'skipped';
  auto_reply_content: string;
  auto_reply_url: string;
  auto_replied_at: number;
  add_ts: number;
}

export interface WorkbenchStats {
  total_sent_comments: number;
  success_sent: number;
  draft_or_failed: number;
  total_replies: number;
  auto_replied: number;
  pending_replies: number;
}

export interface MonitorStatus {
  running: boolean;
  check_interval: number;
  daily_limit: number;
  batch_size: number;
  monitor_ttl_days: number;
}

// ==================== 自动化流水线类型 ====================

export interface AutoPipelineTask {
  id: number;
  task_id: string;
  post_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  current_step: number;
  step_name: string;
  step_detail: string;
  breakdown_id: number | null;
  video_task_id: string;
  video_url: string;
  video_status: string;
  candidate_contents: string[];
  selected_content: string;
  tweet_id: string;
  tweet_url: string;
  error_msg: string;
  skip_video: number;
  add_ts: number;
  update_ts: number;
}

// ==================== Cookie 池相关类型 ====================

export interface CookiePoolSummary {
  total: number;
  available: number;
  in_cooldown: number;
  cooldown_seconds: number;
  max_failures: number;
}

export interface CookiePoolItem {
  index: number;
  label: string;
  cookie_preview: string;
  successes: number;
  failures: number;
  last_used: number;
  cooldown_until: number;
  in_cooldown: boolean;
  status: 'cooldown' | 'healthy' | 'unused';
}

export interface CookiePoolStatus {
  summary: CookiePoolSummary;
  items: CookiePoolItem[];
}

// ==================== 评论模板类型 ====================

export interface TemplateCategory {
  value: string;
  label: string;
  color: string;
  desc: string;
}

export interface CommentTemplate {
  id: number;
  name: string;
  content: string;
  category: string;
  category_label: string;
  tags: string;
  tags_list: string[];
  use_count: number;
  last_used_ts: number;
  is_active: number;
  created_by: string;
  add_ts: number;
  last_modify_ts: number;
}

export interface TemplateListResp {
  total: number;
  page: number;
  page_size: number;
  items: CommentTemplate[];
}

// ==================== 评论效果分析类型 ====================

export interface AnalyticsSummary {
  period: { start_ts: number; end_ts: number };
  send_stats: {
    total: number;
    success: number;
    failed: number;
    draft: number;
    success_rate: number;
  };
  reply_stats: {
    total_replies: number;
    ai_replied: number;
    ai_pending: number;
    ai_failed: number;
    reply_rate: number;
    ai_coverage: number;
  };
  monitoring: { active_count: number };
  response_time: { avg_seconds: number; avg_hours: number; desc: string };
}

export interface CommentAnalytics {
  id: number;
  post_id: string;
  post_username: string;
  post_content: string;
  comment_content: string;
  comment_url: string;
  sent_at: number;
  sent_status: string;
  reply_count: number;
  auto_replied_count: number;
  monitoring: number;
  engagement_score: number;
  hours_since_sent: number;
  reply_rate: number;
}

export interface AnalyticsCommentsResp {
  total: number;
  page: number;
  page_size: number;
  sort_by: string;
  items: CommentAnalytics[];
}

export interface AnalyticsTimeline {
  days: number;
  dates: string[];
  sent_counts: number[];
  success_counts: number[];
  reply_counts: number[];
  ai_reply_counts: number[];
}

export interface TopicStat {
  topic: string;
  comment_count: number;
  success_count: number;
  reply_count: number;
  ai_replied_count: number;
  reply_rate: number;
  ai_coverage: number;
}

// ==================== 通知渠道类型 ====================

export interface ChannelTypeOption {
  value: string;
  label: string;
}

export interface NotificationMeta {
  channels: ChannelTypeOption[];
  events: ChannelTypeOption[];
}

export interface NotificationChannel {
  id: number;
  name: string;
  channel_type: string;
  config: Record<string, any>;
  events: string[];
  is_active: number;
  min_interval_seconds: number;
  last_trigger_ts: number;
  success_count: number;
  fail_count: number;
  note: string;
  created_ts: number;
  updated_ts: number;
}

export interface NotificationChannelListResp {
  total: number;
  items: NotificationChannel[];
}

// ==================== 全自动模式类型 ====================

export interface AutoModeStatus {
  running: boolean;
  started_at: number;
  last_cycle_at: number;
  last_cycle_summary: string;
  total_cycles: number;
  total_comments_sent: number;
  total_comments_failed: number;
  current_phase: 'idle' | 'starting' | 'crawling' | 'selecting' | 'commenting' | 'monitoring' | 'waiting';
  error: string;
  cycle_interval_seconds: number;
  max_posts_per_cycle: number;
}

// ==================== 关键词回复规则类型 ====================

export interface KeywordReplyRule {
  keywords: string[];
  replies: string[];
  priority: number;
}

export interface ReplyRulesResp {
  rules: KeywordReplyRule[];
}

// ==================== 批量视频拆解类型 ====================

export interface BatchBreakdownResult {
  post_id: string;
  success: boolean;
  breakdown_preview?: string;
  error?: string;
}

export interface BatchBreakdownResp {
  success: boolean;
  total: number;
  success_count: number;
  failed_count: number;
  results: BatchBreakdownResult[];
}

// ==================== X 发布文案类型 ====================

export interface XPostContentResp {
  post_id: string;
  contents: string[];
}

export interface PublishToXResp {
  success: boolean;
  message: string;
  tweet_id: string;
  tweet_url: string;
  auto_monitor: boolean;
}

export interface UploadVideoResp {
  success: boolean;
  filename: string;
  file_path: string;
  file_url: string;
  size: number;
}

// ==================== WebSocket 事件类型 ====================

export interface WorkbenchWSEvent {
  type: string;
  event: string;
  data: Record<string, any>;
  ts: number;
}

export interface BatchBreakdownProgressEvent {
  current: number;
  total: number;
  success: number;
  failed: number;
}

// ==================== API 方法 ====================

export interface PlatformMonitorInfo {
  id: string;
  name: string;
  region: string;
  color: string;
  home: string;
  db_count: number;
  cache_count: number;
  cache_age_seconds: number;
}

export interface PlatformsOverviewResp {
  platforms: PlatformMonitorInfo[];
  total_platforms: number;
  domestic_count: number;
  global_count: number;
}

export const xWorkbenchApi = {
  // 热点推文
  getTrending: (params?: { limit?: number; keyword?: string; has_video?: boolean; platform?: string }) =>
    request.get<any, TrendingResp>('/x-workbench/trending', { params }),

  // 平台列表
  getPlatforms: () =>
    request.get<any, { platforms: PlatformInfo[]; error?: string }>('/x-workbench/platforms'),

  // 多平台监控总览（15 个平台的采集状态）
  getMonitorPlatforms: () =>
    request.get<any, PlatformsOverviewResp>('/x-workbench/monitor/platforms'),

  // 采集 - 单次触发（支持所有平台，platform 默认 x）
  crawlOnce: (keywords: string, max_posts = 20, platform = 'x') =>
    request.post<any, { success: boolean; message: string; keywords: string; platform?: string }>('/x-workbench/crawl/once', { keywords, max_posts, platform }),

  // X 采集 - 状态查询
  crawlStatus: () =>
    request.get<any, CrawlStatus>('/x-workbench/crawl/status'),

  // X 采集 - 取消
  crawlCancel: () =>
    request.post<any, { success: boolean }>('/x-workbench/crawl/cancel'),

  // X 采集 - 获取/设置关键词
  getKeywords: () =>
    request.get<any, { keywords: string; max_posts: number; interval_minutes: number }>('/x-workbench/crawl/keywords'),
  updateKeywords: (keywords: string) =>
    request.put<any, { success: boolean; keywords: string }>('/x-workbench/crawl/keywords', { keywords }),

  // X 采集 - 定时任务
  scheduledStatus: () =>
    request.get<any, { running: boolean; interval_minutes: number }>('/x-workbench/crawl/scheduled/status'),
  scheduledStart: () =>
    request.post<any, { success: boolean; message: string }>('/x-workbench/crawl/scheduled/start'),
  scheduledStop: () =>
    request.post<any, { success: boolean; message: string }>('/x-workbench/crawl/scheduled/stop'),

  // 视频拆解（支持所有平台，非X平台需传 post_url/content 等）
  generateBreakdown: (params: {
    post_id: string;
    force_refresh?: boolean;
    platform?: string;
    post_url?: string;
    content?: string;
    username?: string;
    video_url?: string;
  }) =>
    request.post<any, BreakdownResp>('/x-workbench/breakdown', params),

  // 使用拆解上下文生成低成本 Seedance 解说视频（支持所有平台 + 自定义内容）
  generateExplainerVideo: (
    post_id: string,
    idempotency_key: string,
    options?: {
      platform?: string;
      post_url?: string;
      content?: string;
      video_url?: string;
      username?: string;
      custom_prompt?: string;
    },
  ) =>
    request.post<any, ExplainerVideoCreateResp>(
      '/x-workbench/explainer-video',
      { post_id, idempotency_key, ...(options || {}) },
      { skipRetry: true },
    ),

  // 查询 Seedance 解说视频异步任务
  getExplainerVideoStatus: (task_id: string) =>
    request.get<any, ExplainerVideoStatusResp>(`/x-workbench/explainer-video/${encodeURIComponent(task_id)}`),

  // 生成评论
  generateComments: (post_id: string, count = 3) =>
    request.post<any, GenerateCommentsResp>('/x-workbench/generate-comments', { post_id, count }),

  // 发送评论
  sendComment: (data: { post_id: string; post_url: string; content: string; real_send?: boolean; platform?: string }) =>
    request.post<any, SendCommentResp>('/x-workbench/comments/send', data),

  // 已发评论列表（按平台过滤）
  listComments: (params?: { page?: number; page_size?: number; status?: string; keyword?: string; start_ts?: number; end_ts?: number; platform?: string }) =>
    request.get<any, { total: number; page: number; page_size: number; items: SentComment[] }>(
      '/x-workbench/comments',
      { params }
    ),

  // 某条评论收到的回复
  listReplies: (sent_comment_id: number) =>
    request.get<any, { total: number; items: ReplyRecord[] }>(
      `/x-workbench/comments/${sent_comment_id}/replies`
    ),

  // 手动回复
  manualReply: (data: { reply_id: number; content: string; real_send?: boolean }) =>
    request.post<any, any>('/x-workbench/replies/manual', data),

  // 手动触发 AI 自动回复
  triggerAutoReply: (reply_id: number) =>
    request.post<any, any>(`/x-workbench/replies/${reply_id}/auto-reply`),

  // 更新监控状态
  updateMonitoring: (sent_comment_id: number, monitoring: number) =>
    request.put<any, any>('/x-workbench/comments/monitoring', { sent_comment_id, monitoring }),

  // 立即检查回复
  checkNow: () => request.post<any, any>('/x-workbench/monitor/check-now'),

  // 监控状态
  getMonitorStatus: () => request.get<any, MonitorStatus>('/x-workbench/monitor/status'),

  // 启动/停止监控
  startMonitor: () => request.post<any, any>('/x-workbench/monitor/start'),
  stopMonitor: () => request.post<any, any>('/x-workbench/monitor/stop'),

  // AI 健康
  aiHealth: () => request.get<any, any>('/x-workbench/ai/health'),

  // 统计
  getStats: (platform?: string) => request.get<any, WorkbenchStats>('/x-workbench/stats', { params: platform ? { platform } : {} }),

  // ==================== Cookie 池管理 ====================

  // Cookie 池状态
  cookiePoolStatus: () =>
    request.get<any, CookiePoolStatus>('/x-workbench/cookie-pool/status'),

  // 添加 Cookie
  cookiePoolAdd: (cookie: string) =>
    request.post<any, { success: boolean; message: string }>('/x-workbench/cookie-pool/add', { cookie }),

  // 移除 Cookie（需要传完整的 cookie 字符串）
  cookiePoolRemove: (cookie: string) =>
    request.post<any, { success: boolean; message: string }>('/x-workbench/cookie-pool/remove', { cookie }),

  // 重置所有 Cookie 的失败计数和冷却
  cookiePoolReset: () =>
    request.post<any, { success: boolean; message: string }>('/x-workbench/cookie-pool/reset'),

  // 测试当前 Cookie 是否有效
  cookiePoolTest: () =>
    request.post<any, { success: boolean; message: string }>('/x-workbench/cookie-pool/test'),

  // ==================== 评论模板 ====================

  // 获取模板分类
  templateCategories: () =>
    request.get<any, { categories: TemplateCategory[] }>('/x-workbench/templates/categories'),

  // 获取模板列表
  listTemplates: (params?: { page?: number; page_size?: number; category?: string; keyword?: string; active_only?: boolean }) =>
    request.get<any, TemplateListResp>('/x-workbench/templates', { params }),

  // 获取单条模板
  getTemplate: (id: number) =>
    request.get<any, CommentTemplate>(`/x-workbench/templates/${id}`),

  // 创建模板
  createTemplate: (data: { name: string; content: string; category?: string; tags?: string }) =>
    request.post<any, CommentTemplate>('/x-workbench/templates', data),

  // 更新模板
  updateTemplate: (id: number, data: Partial<{ name: string; content: string; category: string; tags: string; is_active: number }>) =>
    request.put<any, CommentTemplate>(`/x-workbench/templates/${id}`, data),

  // 删除模板(软删除)
  deleteTemplate: (id: number) =>
    request.delete<any, { success: boolean; message: string }>(`/x-workbench/templates/${id}`),

  // 标记模板为已使用
  useTemplate: (id: number) =>
    request.post<any, { success: boolean; message: string }>(`/x-workbench/templates/${id}/use`),

  // 初始化内置模板
  seedTemplates: () =>
    request.post<any, { success: boolean; message: string; created: number }>('/x-workbench/templates/seed'),

  // ==================== 评论效果分析 ====================

  // 总体概览
  analyticsSummary: (params?: { start_ts?: number; end_ts?: number }) =>
    request.get<any, AnalyticsSummary>('/x-workbench/analytics/summary', { params }),

  // 单条评论效果排名
  analyticsComments: (params?: { page?: number; page_size?: number; sort_by?: string; start_ts?: number; end_ts?: number }) =>
    request.get<any, AnalyticsCommentsResp>('/x-workbench/analytics/comments', { params }),

  // 时间序列(用于折线图)
  analyticsTimeline: (days?: number) =>
    request.get<any, AnalyticsTimeline>('/x-workbench/analytics/timeline', { params: { days } }),

  // 按话题分组
  analyticsTopics: (params?: { start_ts?: number; end_ts?: number }) =>
    request.get<any, { total_topics: number; items: TopicStat[] }>('/x-workbench/analytics/topics', { params }),

  // ==================== 数据导出 ====================

  // 导出已发评论 (CSV/Excel)
  exportSentComments: (params: { format?: 'csv' | 'xlsx'; status?: string; start_ts?: number; end_ts?: number }) =>
    _downloadBlob('/x-workbench/export/sent-comments', params, `sent_comments.${params.format || 'csv'}`),

  // 导出收到的回复 (CSV/Excel)
  exportReplies: (params: { format?: 'csv' | 'xlsx'; status?: string; start_ts?: number; end_ts?: number }) =>
    _downloadBlob('/x-workbench/export/replies', params, `replies.${params.format || 'csv'}`),

  // 导出完整效果分析报告 (Excel 多 sheet)
  exportAnalytics: () =>
    _downloadBlob('/x-workbench/export/analytics', { format: 'xlsx' }, 'analytics_report.xlsx'),

  // ==================== 通知渠道管理 ====================

  // 渠道类型/事件类型元数据
  notificationMeta: () =>
    request.get<any, NotificationMeta>('/x-workbench/notifications/meta'),

  // 渠道列表
  listNotificationChannels: (params?: { active_only?: boolean; channel_type?: string }) =>
    request.get<any, NotificationChannelListResp>(
      '/x-workbench/notifications/channels',
      { params }
    ),

  // 渠道详情
  getNotificationChannel: (id: number) =>
    request.get<any, NotificationChannel>(`/x-workbench/notifications/channels/${id}`),

  // 创建渠道
  createNotificationChannel: (data: {
    name: string;
    channel_type: string;
    config: Record<string, any>;
    events: string[];
    is_active?: boolean;
    min_interval_seconds?: number;
    note?: string;
  }) =>
    request.post<any, NotificationChannel>('/x-workbench/notifications/channels', data),

  // 更新渠道
  updateNotificationChannel: (id: number, data: Partial<{
    name: string;
    channel_type: string;
    config: Record<string, any>;
    events: string[];
    is_active: boolean;
    min_interval_seconds: number;
    note: string;
  }>) =>
    request.put<any, NotificationChannel>(`/x-workbench/notifications/channels/${id}`, data),

  // 删除渠道(软删除:禁用)
  deleteNotificationChannel: (id: number) =>
    request.delete<any, { success: boolean; message: string }>(`/x-workbench/notifications/channels/${id}`),

  // 测试推送
  testNotificationChannel: (id: number) =>
    request.post<any, { success: boolean; message: string }>(`/x-workbench/notifications/channels/${id}/test`),

  // ==================== 全自动模式 ====================

  // 启动全自动模式(仅管理员)
  startAutoMode: () =>
    request.post<any, { success: boolean; message: string }>('/x-workbench/auto-mode/start'),

  // 停止全自动模式(仅管理员)
  stopAutoMode: () =>
    request.post<any, { success: boolean; message: string }>('/x-workbench/auto-mode/stop'),

  // 查询全自动模式状态
  getAutoModeStatus: () =>
    request.get<any, AutoModeStatus>('/x-workbench/auto-mode/status'),

  // ==================== 关键词回复规则 ====================

  // 获取回复规则
  getReplyRules: () =>
    request.get<any, ReplyRulesResp>('/x-workbench/reply-rules'),

  // 更新回复规则
  updateReplyRules: (rules: KeywordReplyRule[]) =>
    request.put<any, { success: boolean; rules: KeywordReplyRule[] }>('/x-workbench/reply-rules', rules),

  // ==================== 批量视频拆解 ====================

  // 批量视频拆解
  batchBreakdown: (post_ids: string[]) =>
    request.post<any, BatchBreakdownResp>('/x-workbench/batch/breakdown', { post_ids }),

  // 生成 X 发布文案
  generateXPostContent: (post_id: string, count = 3) =>
    request.post<any, XPostContentResp>('/x-workbench/x-post-content', { post_id, count }),

  // 发布视频/文案到 X
  publishToX: (data: { post_id: string; content: string; video_url?: string; auto_monitor?: boolean }) =>
    request.post<any, PublishToXResp>('/x-workbench/publish-x', data),

  // 上传视频文件
  uploadVideo: (file: File): Promise<UploadVideoResp> => {
    const formData = new FormData();
    formData.append('file', file);
    return request.post('/x-workbench/upload-video', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as Promise<UploadVideoResp>;
  },

  // ==================== 自动化流水线 ====================

  // 启动一键自动发布流水线
  startAutoPipeline: (post_id: string, skip_video = false) =>
    request.post<any, { success: boolean; task_id: string; message: string }>('/x-workbench/auto-pipeline', { post_id, skip_video }),

  // 查询流水线任务状态
  getAutoPipelineStatus: (task_id: string) =>
    request.get<any, { success: boolean; task: AutoPipelineTask }>(`/x-workbench/auto-pipeline/${task_id}`),

  // 取消流水线任务
  cancelAutoPipeline: (task_id: string) =>
    request.post<any, { success: boolean; message: string }>(`/x-workbench/auto-pipeline/${task_id}/cancel`),

  // 查询流水线任务列表
  listAutoPipelines: (limit = 20) =>
    request.get<any, { success: boolean; total: number; tasks: AutoPipelineTask[] }>('/x-workbench/auto-pipeline', { params: { limit } }),
};

// ==================== 内部辅助:文件下载 ====================
//
// 由于 request 拦截器返回 response.data,这里用 axios 直接调用以拿到完整 response,
// 从 Content-Disposition header 提取服务端生成的文件名,无法提取时用默认文件名。
async function _downloadBlob(url: string, params: Record<string, any>, defaultFilename: string): Promise<void> {
  const token = localStorage.getItem('auth_token');
  const baseURL = import.meta.env.VITE_API_BASE_URL || '/api';
  const resp = await axios.get(baseURL + url, {
    params,
    responseType: 'blob',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  const blob: Blob = resp.data;
  // 尝试从 Content-Disposition 解析文件名
  const cd = resp.headers['content-disposition'] || '';
  let filename = defaultFilename;
  const m = cd.match(/filename="?([^";]+)"?/);
  if (m && m[1]) filename = decodeURIComponent(m[1]);
  // 触发浏览器下载
  const link = document.createElement('a');
  link.href = window.URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(link.href);
}

// ==================== WebSocket 连接 ====================

export function connectWorkbenchWS(
  token: string,
  onMessage: (event: WorkbenchWSEvent) => void
): WebSocket | null {
  if (!token) return null;

  const apiBase = import.meta.env.VITE_API_BASE_URL || '/api';
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsHost = window.location.host;
  let wsUrl: string;

  if (apiBase.startsWith('http')) {
    const url = new URL(apiBase);
    wsUrl = `${url.protocol === 'https:' ? 'wss:' : 'ws:'}//${url.host}${url.pathname}/x-workbench/ws/events?token=${encodeURIComponent(token)}`;
  } else {
    wsUrl = `${wsProtocol}//${wsHost}${apiBase}/x-workbench/ws/events?token=${encodeURIComponent(token)}`;
  }

  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('[Workbench WS] Connected');
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data as WorkbenchWSEvent);
    } catch (e) {
      console.warn('[Workbench WS] Failed to parse message:', e);
    }
  };

  ws.onerror = (error) => {
    console.error('[Workbench WS] Error:', error);
  };

  ws.onclose = () => {
    console.log('[Workbench WS] Disconnected');
  };

  return ws;
}
