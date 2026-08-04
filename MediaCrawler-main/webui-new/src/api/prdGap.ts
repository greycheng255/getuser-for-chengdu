// -*- coding: utf-8 -*-
// PRD 缺口补全方案 — 统一 API 封装
// 覆盖阶段一~四 16 个新路由前缀，供 10 个新页面调用

import request from './request';

// 响应拦截器已剥壳（返回 response.data），所以这里直接拿到后端 body
// 后端统一结构: { code: 0, data: ... } 或 { success: true, ... }

// ============ 预警中心 /api/alerts ============
export const alertApi = {
  list: (params: {
    user_id?: number;
    alert_type?: string;
    severity?: string;
    status?: string;
    limit?: number;
    offset?: number;
  } = {}) => request.get<any, any>('/alerts', { params }),
  unreadCount: (user_id?: number) =>
    request.get<any, any>('/alerts/unread-count', { params: { user_id } }),
  markRead: (alert_id: string, user_id?: number) =>
    request.post<any, any>(`/alerts/${alert_id}/read`, { user_id }),
  markAllRead: (user_id?: number) =>
    request.post<any, any>('/alerts/read-all', { user_id }),
  types: () => request.get<any, any>('/alerts/types'),
};

// ============ 视频参数配置 /api/ai/video-config ============
export const videoConfigApi = {
  list: (user_id?: number, include_presets = true) =>
    request.get<any, any>('/ai/video-config', { params: { user_id, include_presets } }),
  create: (data: any) => request.post<any, any>('/ai/video-config', data),
  get: (config_id: string) => request.get<any, any>(`/ai/video-config/${config_id}`),
  delete: (config_id: string) => request.delete<any, any>(`/ai/video-config/${config_id}`),
  validValues: () => request.get<any, any>('/ai/video-config/options/valid-values'),
};

// ============ 批量视频生成 /api/ai/batch-generate ============
export const batchVideoApi = {
  start: (data: { hotspot_ids: string[]; config_ids?: string[]; user_id?: number }) =>
    request.post<any, any>('/ai/batch-generate', data),
  get: (task_id: string) => request.get<any, any>(`/ai/batch-generate/${task_id}`),
  list: () => request.get<any, any>('/ai/batch-generate'),
};

// ============ 提示词库 /api/ai/prompt-library ============
export const promptLibraryApi = {
  search: (data: {
    keyword?: string;
    category?: string;
    tags?: string[];
    style_keyword?: string;
    owner_user_id?: number;
    limit?: number;
    offset?: number;
  }) => request.post<any, any>('/ai/prompt-library/search', data),
  create: (data: any) => request.post<any, any>('/ai/prompt-library', data),
  get: (prompt_id: string) => request.get<any, any>(`/ai/prompt-library/${prompt_id}`),
  variant: (prompt_id: string, variant_intent = '') =>
    request.post<any, any>(`/ai/prompt-library/${prompt_id}/variant`, null, {
      params: { variant_intent },
    }),
  storyboard: (storyboard_id: string) =>
    request.get<any, any>(`/ai/storyboard/${storyboard_id}`),
};

// ============ 一键完整链路 /api/ai/full-pipeline ============
export const pipelineApi = {
  full: (data: {
    hotspot_video_url: string;
    hotspot_id?: string;
    owner_user_id?: number;
    video_config_id?: string;
    publish_platforms?: string[];
  }) => request.post<any, any>('/ai/full-pipeline', data),
  generateFromHotspot: (data: {
    hotspot_video_url: string;
    video_config_id?: string;
    auto_moderate?: boolean;
  }) => request.post<any, any>('/ai/generate-from-hotspot', data),
  extractPrompt: (data: { hotspot_video_url: string }) =>
    request.post<any, any>('/ai/extract-prompt', data),
};

// ============ 人工复核 /api/moderation/review ============
export const reviewApi = {
  create: (data: {
    content_type?: string;
    content_id: string;
    content_url?: string;
    content_preview?: string;
    auto_moderation_result?: any;
    owner_user_id?: number;
  }) => request.post<any, any>('/moderation/review', data),
  queue: (params: {
    user_id?: number;
    content_type?: string;
    limit?: number;
    offset?: number;
  } = {}) => request.get<any, any>('/moderation/review/queue', { params }),
  submit: (review_id: string, data: {
    reviewer_id: number;
    decision: string;
    notes?: string;
    tags?: string[];
  }) => request.post<any, any>(`/moderation/review/${review_id}/submit`, data),
  recent: (params: { user_id?: number; limit?: number } = {}) =>
    request.get<any, any>('/moderation/review/recent', { params }),
  get: (review_id: string) => request.get<any, any>(`/moderation/review/${review_id}`),
};

// ============ 合规归档 /api/moderation/archive ============
export const archiveApi = {
  list: (params: {
    archive_type?: string;
    platform?: string;
    owner_user_id?: number;
    start_date?: string;
    end_date?: string;
    limit?: number;
    offset?: number;
  } = {}) => request.get<any, any>('/moderation/archive', { params }),
  get: (archive_id: string) => request.get<any, any>(`/moderation/archive/${archive_id}`),
  migrateCold: () => request.post<any, any>('/moderation/archive/migrate-cold'),
  purgeExpired: () => request.post<any, any>('/moderation/archive/purge-expired'),
};

// ============ 机器人账号 /api/interact/bot-accounts ============
export const botAccountApi = {
  list: (params: {
    platform?: string;
    group?: string;
    region?: string;
    status?: string;
    user_id?: number;
    limit?: number;
    offset?: number;
  } = {}) => request.get<any, any>('/interact/bot-accounts', { params }),
  add: (data: {
    platform: string;
    cookie: string;
    label?: string;
    group?: string;
    region?: string;
    owner_user_id?: number;
  }) => request.post<any, any>('/interact/bot-accounts', data),
  batchAdd: (data: {
    platform: string;
    cookies: string[];
    group?: string;
    region?: string;
    owner_user_id?: number;
  }) => request.post<any, any>('/interact/bot-accounts/batch', data),
  delete: (account_id: string) =>
    request.delete<any, any>(`/interact/bot-accounts/${account_id}`),
  stats: (platform?: string) =>
    request.get<any, any>('/interact/bot-accounts/stats', { params: { platform } }),
  groups: () => request.get<any, any>('/interact/bot-accounts/groups'),
};

// ============ 话术库 /api/interact/scripts ============
export const scriptApi = {
  list: (params: {
    platform?: string;
    scene?: string;
    user_id?: number;
    limit?: number;
    offset?: number;
  } = {}) => request.get<any, any>('/interact/scripts', { params }),
  create: (data: {
    platform?: string;
    scene?: string;
    content: string;
    tags?: string[];
  }) => request.post<any, any>('/interact/scripts', data),
  delete: (script_id: string) => request.delete<any, any>(`/interact/scripts/${script_id}`),
  batchImport: (items: any[]) =>
    request.post<any, any>('/interact/scripts/batch-import', { items }),
  generate: (data: {
    script_type?: string;
    context?: string;
    platform?: string;
    count?: number;
    use_ai?: boolean;
    auto_save?: boolean;
  }) => request.post<any, any>('/interact/scripts/generate', data),
  generatorStatus: () => request.get<any, any>('/interact/scripts/generator/status'),
};

// ============ 互动量配置 /api/interact/configs ============
export const interactionConfigApi = {
  save: (data: any) => request.post<any, any>('/interact/configs', data),
  list: (params: { platform?: string; owner_user_id?: number } = {}) =>
    request.get<any, any>('/interact/configs', { params }),
  find: (params: { platform?: string; scene?: string; owner_user_id?: number } = {}) =>
    request.get<any, any>('/interact/configs/find', { params }),
  get: (config_id: string) => request.get<any, any>(`/interact/configs/${config_id}`),
  deactivate: (config_id: string) =>
    request.delete<any, any>(`/interact/configs/${config_id}`),
  split: (config_id: string, total = 30) =>
    request.post<any, any>(`/interact/configs/${config_id}/split`, null, {
      params: { total },
    }),
};

// ============ 数据分析仪表盘 /api/analytics ============
// 后端 api/routers/analytics.py：
//   - GET /analytics/dashboard                仪表盘汇总（直接返回对象，无 code/data 包裹）
//   - GET /analytics/platform-comparison      平台对比（直接返回对象）
//   - GET /analytics/content-performance      内容表现（直接返回对象）
//   - GET /analytics/external-metrics         外部指标（{code,data:{items,total}} 包裹）
export const analyticsApi = {
  getDashboard: (days: number = 7) =>
    request.get<any, any>('/analytics/dashboard', { params: { days } }),
  getPlatformComparison: (days: number = 30) =>
    request.get<any, any>('/analytics/platform-comparison', { params: { days } }),
  getContentPerformance: (limit: number = 20) =>
    request.get<any, any>('/analytics/content-performance', { params: { limit } }),
  getExternalMetrics: (params: { platform?: string; days?: number; limit?: number } = {}) =>
    request.get<any, any>('/analytics/external-metrics', { params }),
  exportDashboard: (days: number = 7) =>
    request.get<any, any>('/analytics/export/dashboard', {
      params: { days },
      responseType: 'blob',
    } as any),
  exportPlatformComparison: (days: number = 30) =>
    request.get<any, any>('/analytics/export/platform-comparison', {
      params: { days },
      responseType: 'blob',
    } as any),
  exportContentPerformance: (limit: number = 100) =>
    request.get<any, any>('/analytics/export/content-performance', {
      params: { limit },
      responseType: 'blob',
    } as any),
};

// ============ 外部数据采集 /api/analytics/external-metrics ============
export const externalMetricsApi = {
  list: (params: { platform?: string; days?: number; limit?: number } = {}) =>
    request.get<any, any>('/analytics/external-metrics', { params }),
  collect: (accounts: Array<{ platform: string; account_id: string }>) =>
    request.post<any, any>('/analytics/external-metrics/collect', { accounts }),
  utmUrl: (params: {
    base_url: string;
    source: string;
    medium?: string;
    campaign?: string;
    content?: string;
    term?: string;
  }) => request.post<any, any>('/analytics/external-metrics/utm-url', null, { params }),
  funnel: (data: { platform: string; days?: number }) =>
    request.post<any, any>('/analytics/funnel', data),
  funnelEvent: (data: {
    platform: string;
    account_id: string;
    event_type: string;
    target_url?: string;
    owner_user_id?: number;
  }) => request.post<any, any>('/analytics/funnel/event', data),
};

// ============ 爆款复盘 /api/analytics/viral-reviews ============
export const viralReviewApi = {
  list: (params: { platform?: string; days?: number; limit?: number } = {}) =>
    request.get<any, any>('/analytics/viral-reviews', { params }),
  get: (report_id: string) => request.get<any, any>(`/analytics/viral-reviews/${report_id}`),
  create: (data: any) => request.post<any, any>('/analytics/viral-reviews', data),
  detect: (data: any) => request.post<any, any>('/analytics/viral-reviews/detect', data),
};

// ============ 操作日志 /api/audit-logs ============
export const auditLogApi = {
  list: (params: {
    action_type?: string;
    user_id?: number;
    platform?: string;
    start_date?: string;
    end_date?: string;
    limit?: number;
    offset?: number;
  } = {}) => request.get<any, any>('/audit-logs', { params }),
  create: (data: {
    action_type: string;
    user_id?: number;
    platform?: string;
    target?: string;
    description?: string;
    request_data?: Record<string, unknown>;
    response_data?: Record<string, unknown>;
    ip_address?: string;
    user_agent?: string;
    status?: string;
    error_message?: string;
  }) => request.post<any, any>('/audit-logs', data),
  actionTypes: () => request.get<any, any>('/audit-logs/action-types'),
  reports: (params: { period?: string; limit?: number } = {}) =>
    request.get<any, any>('/audit-logs/reports', { params }),
  generateReport: (data: { period: string; days?: number }) =>
    request.post<any, any>('/audit-logs/reports', data),
  exportCsv: (params: {
    action_type?: string;
    user_id?: number;
    platform?: string;
    start_date?: string;
    end_date?: string;
  } = {}) =>
    request.get<any, any>('/audit-logs/export', {
      params,
      responseType: 'blob',
    } as any),
};

// ============ 账号分组 /api/publish/accounts ============
export const accountGroupApi = {
  groups: () => request.get<any, any>('/publish/accounts/groups'),
  listByGroup: (params: { group?: string; platform?: string; user_id?: number }) =>
    request.get<any, any>('/publish/accounts/by-group', { params }),
  setGroup: (account_id: number, data: { group: string; region?: string }) =>
    request.post<any, any>(`/publish/accounts/${account_id}/group`, data),
};

// ============ 多平台私信 /api/dm ============
export const dmApi = {
  platforms: () => request.get<any, any>('/dm/platforms/supported'),
  list: (params: { platform?: string; status?: string; limit?: number } = {}) =>
    request.get<any, any>('/dm/messages', { params }),
  listNeedsHuman: () => request.get<any, any>('/dm/messages/needs-human'),
  resolve: (msg_id: string | number) =>
    request.post<any, any>(`/dm/messages/${msg_id}/resolve`),
  monitorStatus: () => request.get<any, any>('/dm/monitor/status'),
  monitorStart: () => request.post<any, any>('/dm/monitor/start'),
  monitorStop: () => request.post<any, any>('/dm/monitor/stop'),
  previewReply: (data: { platform: string; message_text: string; sender_name?: string }) =>
    request.post<any, any>('/dm/reply/preview', data),
  reply: (data: { message_id: string; content: string; platform?: string }) =>
    request.post<any, any>('/dm/reply', data),
  addPlatform: (platform: string) =>
    request.post<any, any>('/dm/platforms', { platform }),
  removePlatform: (platform: string) =>
    request.delete<any, any>('/dm/platforms', { data: { platform } }),
  listMonitored: () => request.get<any, any>('/dm/platforms'),
};

// ============ 发布调度 /api/scheduling ============
export const schedulingApi = {
  createTask: (data: any) => request.post<any, any>('/scheduling/tasks', data),
  listTasks: (limit = 100) => request.get<any, any>('/scheduling/tasks', { params: { limit } }),
  cancelTask: (taskId: string | number) =>
    request.delete<any, any>(`/scheduling/tasks/${taskId}`),
  recommendTime: (platform: string) =>
    request.post<any, any>('/scheduling/recommend-time', { platform }),
  startScheduler: () => request.post<any, any>('/scheduling/scheduler/start'),
  stopScheduler: () => request.post<any, any>('/scheduling/scheduler/stop'),
  peakHours: () => request.get<any, any>('/scheduling/peak-hours'),
  peakHoursFor: (platform: string) =>
    request.get<any, any>(`/scheduling/peak-hours/${platform}`),
  isPeakNow: (platform: string) =>
    request.get<any, any>(`/scheduling/peak-hours/${platform}/is-peak`),
  smartStagger: (platforms: string[], minGapMinutes = 30) =>
    request.post<any, any>('/scheduling/smart-stagger', {
      platforms,
      min_gap_minutes: minGapMinutes,
    }),
  frequencyAdapt: (platform: string, successRate: number, currentInterval: number) =>
    request.post<any, any>('/scheduling/frequency-adapt', {
      platform,
      recent_success_rate: successRate,
      current_interval_minutes: currentInterval,
    }),
  calendarItems: (days = 7) =>
    request.get<any, any>('/scheduling/calendar/items', { params: { days } }),
  createCalendarItem: (data: any) =>
    request.post<any, any>('/scheduling/calendar/items', data),
};

// ============ 突发热点预警 /api/hotpoint/alerts ============
export const hotpointAlertApi = {
  stats: () => request.get<any, any>('/hotpoint/alerts/stats'),
  start: () => request.post<any, any>('/hotpoint/alerts/start'),
  stop: () => request.post<any, any>('/hotpoint/alerts/stop'),
  check: (hotspot_id: string) =>
    request.get<any, any>(`/hotpoint/alerts/check/${hotspot_id}`),
};

// ============ 热点筛选配置 /api/hotpoint/filter-config ============
export const hotpointFilterApi = {
  list: (params: { user_id?: number; active_only?: boolean } = {}) =>
    request.get<any, any>('/hotpoint/filter-config', { params }),
  save: (data: any) => request.post<any, any>('/hotpoint/filter-config', data),
  delete: (config_id: string) =>
    request.delete<any, any>(`/hotpoint/filter-config/${config_id}`),
  preview: (data: any) => request.post<any, any>('/hotpoint/filter-config/preview', data),
};

// ============ 系统配置 /api/system-config (阶段三 P2-7) ============
// 评分规则 / 通知设置等 KV 配置后端持久化
export const systemConfigApi = {
  // 读取配置(自动 JSON 反序列化)
  get: (key: string, user_id?: number) =>
    request.get<any, any>(`/system-config/${key}`, { params: { user_id } }),
  // 写入配置(UPSERT,自动 JSON 序列化)
  set: (key: string, value: any, config_type?: string, user_id?: number) =>
    request.post<any, any>(`/system-config/${key}`, { value, config_type: config_type || '', user_id }),
  // 删除配置
  delete: (key: string, user_id?: number) =>
    request.delete<any, any>(`/system-config/${key}`, { params: { user_id } }),
  // 列出配置(可按 config_type / user_id 筛选)
  list: (params: { config_type?: string; user_id?: number } = {}) =>
    request.get<any, any>('/system-config', { params }),
};

// ============ 营销素材库 /api/marketing (B6 前端缺口) ============
// 后端 api/routers/marketing.py：素材 CRUD + 视频植入 + 文案植入
// MaterialType 枚举值: logo / qr_code / link / slogan / event / contact
export const marketingApi = {
  // 列出营销素材 (GET /marketing/materials)
  listMaterials: (params: { material_type?: string; only_active?: boolean } = {}) =>
    request.get<any, any>('/marketing/materials', { params }),
  // 新增素材 (POST /marketing/materials)
  createMaterial: (data: {
    name: string;
    material_type?: string;
    content?: string;
    file_path?: string;
    link_url?: string;
    position?: string;
    is_active?: boolean;
  }) => request.post<any, any>('/marketing/materials', data),
  // 删除素材 (DELETE /marketing/materials/{id})
  deleteMaterial: (id: number) => request.delete<any, any>(`/marketing/materials/${id}`),
  // 视频添加图片水印 (POST /marketing/video/watermark)
  addWatermark: (data: {
    video_path: string;
    logo_path: string;
    output_path: string;
    position?: string;
    scale?: string;
  }) => request.post<any, any>('/marketing/video/watermark', data),
  // 视频添加文字水印 (POST /marketing/video/text-watermark)
  addTextWatermark: (data: {
    video_path: string;
    text: string;
    output_path: string;
    position?: string;
    font_size?: number;
    font_color?: string;
  }) => request.post<any, any>('/marketing/video/text-watermark', data),
  // 视频添加二维码贴片 (POST /marketing/video/qr-code)
  addQrCode: (data: {
    video_path: string;
    qr_image_path: string;
    output_path: string;
    position?: string;
    duration?: number;
  }) => request.post<any, any>('/marketing/video/qr-code', data),
  // AI 文案植入 (POST /marketing/copy/insert)
  insertCopy: (data: {
    content: string;
    platform?: string;
    slogans?: string[];
    link?: string | null;
    event_info?: string | null;
  }) => request.post<any, any>('/marketing/copy/insert', data),
  // 从素材库自动植入文案 (POST /marketing/copy/auto-insert)
  autoInsertCopy: (data: { content: string; platform?: string }) =>
    request.post<any, any>('/marketing/copy/auto-insert', data),
};

// ============ 多平台发布 /api/publish (C 类前端缺口) ============
// 后端 api/routers/publish.py：多平台/单平台发布 + 平台元数据 + 发布记录
export const publishApi = {
  // 列出所有支持的平台 (GET /publish/platforms)
  listPlatforms: (params: { category?: string } = {}) =>
    request.get<any, any>('/publish/platforms', { params }),
  // 获取单个平台详情 (GET /publish/platforms/{platform})
  getPlatform: (platform: string) => request.get<any, any>(`/publish/platforms/${platform}`),
  // 多平台并行发布 (POST /publish/multi-platform)
  multiPublish: (data: {
    title: string;
    content: string;
    keywords?: string[];
    images?: string[];
    video_path?: string | null;
    target_platforms: string[];
    user_id?: number;
    adapt_content?: boolean;
    enforce_moderation?: boolean;
    source_post_id?: string;
  }) => request.post<any, any>('/publish/multi-platform', data),
  // 单平台发布 (POST /publish/single/{platform})
  singlePublish: (platform: string, data: {
    title: string;
    content: string;
    keywords?: string[];
    images?: string[];
    video_path?: string | null;
    user_id?: number;
    adapt_content?: boolean;
    enforce_moderation?: boolean;
  }) => request.post<any, any>(`/publish/single/${platform}`, data),
  // 查询发布记录列表 (GET /publish/records)
  listRecords: (params: {
    platform?: string;
    status?: string;
    start_date?: string;
    end_date?: string;
    user_id?: number;
    limit?: number;
    offset?: number;
  } = {}) => request.get<any, any>('/publish/records', { params }),
  // 查询单条发布记录详情 (GET /publish/records/{id})
  getRecord: (id: number) => request.get<any, any>(`/publish/records/${id}`),
};

// ============ 五功能统一流水线 /api/pipeline ============
export const unifiedPipelineApi = {
  // 启动统一流水线 (POST /pipeline/run)
  run: (data: {
    source_type: 'hotspot_url' | 'prompt_id' | 'manual_text';
    source_value: string;
    video_config_id?: string;
    publish_platforms?: string[];
    owner_user_id?: number;
  }) => request.post<any, any>('/pipeline/run', data),
  // 查询流水线状态 (GET /pipeline/{pipeline_id})
  get: (pipeline_id: string) => request.get<any, any>(`/pipeline/${pipeline_id}`),
  // 列出最近流水线 (GET /pipeline)
  list: (limit: number = 20) => request.get<any, any>('/pipeline', { params: { limit } }),
};
