import request from './request';

export interface XTwitterPost {
  id: number;
  post_id: string;
  username: string;
  nickname: string;
  content: string;
  image_urls: string;
  video_url: string;
  video_duration: number;
  likes_count: string;
  retweets_count: string;
  replies_count: string;
  quotes_count: string;
  bookmarks_count: string;
  views_count: string;
  post_url: string;
  source_keyword: string;
  hashtags: string;
  created_at: number;
  add_ts: number;
  comment_count?: number;
}

export interface XTwitterComment {
  id: number;
  comment_id: string;
  post_id: string;
  username: string;
  nickname: string;
  content: string;
  likes_count: string;
  replies_count: string;
  created_at: number;
  add_ts: number;
}

export interface XTwitterVideoBreakdown {
  id: number;
  post_id: string;
  video_url: string;
  script: string;
  storyboard: string;
  analysis: string;
  add_ts: number;
}

export interface XTwitterStats {
  total_posts: number;
  total_comments: number;
  total_video_breakdowns: number;
  video_posts_count: number;
  recent_posts: Array<{
    post_id: string;
    content: string;
    add_ts: number;
  }>;
  recent_comments: Array<{
    comment_id: string;
    content: string;
    add_ts: number;
  }>;
}

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export async function getPosts(params: {
  page?: number;
  page_size?: number;
  keyword?: string;
  has_video?: boolean;
}): Promise<PaginatedResponse<XTwitterPost>> {
  return request.get('/api/x-twitter/posts', { params });
}

export async function getPost(postId: string): Promise<XTwitterPost> {
  return request.get(`/api/x-twitter/posts/${postId}`);
}

export async function getPostComments(params: {
  post_id: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<XTwitterComment>> {
  return request.get(`/api/x-twitter/posts/${params.post_id}/comments`, {
    params: { page: params.page, page_size: params.page_size },
  });
}

export async function getComments(params: {
  page?: number;
  page_size?: number;
  keyword?: string;
}): Promise<PaginatedResponse<XTwitterComment>> {
  return request.get('/api/x-twitter/comments', { params });
}

export async function getVideoBreakdowns(params: {
  page?: number;
  page_size?: number;
  post_id?: string;
}): Promise<PaginatedResponse<XTwitterVideoBreakdown>> {
  return request.get('/api/x-twitter/video-breakdowns', { params });
}

export async function getStats(): Promise<XTwitterStats> {
  return request.get('/api/x-twitter/stats');
}


// ========== 回复模板管理 ==========

export interface KeywordReplyRule {
  keywords: string[];
  replies: string[];
  priority: number;
}

export interface ReplyConfig {
  ai_reply_enabled: boolean;
  keyword_match_first: boolean;
  reply_daily_limit: number;
  system_prompt: string;
  comment_templates: string[];
  scheduled_crawl_enabled: boolean;
  crawl_interval_minutes: number;
  batch_breakdown_size: number;
  batch_comment_size: number;
}

export async function getReplyRules(): Promise<{ rules: KeywordReplyRule[] }> {
  return request.get('/api/x-twitter/reply-rules');
}

export async function updateReplyRules(rules: KeywordReplyRule[]): Promise<{ success: boolean; rules: KeywordReplyRule[] }> {
  return request.put('/api/x-twitter/reply-rules', rules);
}

export async function getReplyConfig(): Promise<ReplyConfig> {
  return request.get('/api/x-twitter/reply-config');
}

// ========== 任务调度 ==========

export interface CrawlStatus {
  running: boolean;
  interval_minutes: number;
}

export async function startScheduledCrawl(): Promise<{ success: boolean; message: string }> {
  return request.post('/api/x-twitter/crawl/start');
}

export async function stopScheduledCrawl(): Promise<{ success: boolean; message: string }> {
  return request.post('/api/x-twitter/crawl/stop');
}

export async function getCrawlStatus(): Promise<CrawlStatus> {
  return request.get('/api/x-twitter/crawl/status');
}

// ========== 批量操作 ==========

export interface BatchResult {
  success: boolean;
  total: number;
  success_count: number;
  failed_count: number;
  results: Array<{
    post_id: string;
    success: boolean;
    error?: string;
    comment?: string;
    post_url?: string;
    breakdown?: string;
  }>;
}

export async function batchVideoBreakdown(postIds: string[]): Promise<BatchResult> {
  return request.post('/api/x-twitter/batch/breakdown', { post_ids: postIds });
}

export async function batchPostComments(postIds: string[], comments?: string[]): Promise<BatchResult> {
  return request.post('/api/x-twitter/batch/comment', { post_ids: postIds, comments });
}

// ========== WebSocket 实时通知 ==========

export interface XTwitterWSEvent {
  type: string;
  event: string;
  data: Record<string, unknown>;
  ts: number;
}

export function connectXTwitterWebSocket(token: string, onMessage: (event: XTwitterWSEvent) => void): WebSocket | null {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const wsUrl = `${protocol}//${host}/ws/x-twitter?token=${token}`;

  try {
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('[X-Twitter WS] Connected');
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        onMessage(data);
      } catch (err) {
        console.error('[X-Twitter WS] Parse error:', err);
      }
    };

    ws.onerror = (err) => {
      console.error('[X-Twitter WS] Error:', err);
    };

    ws.onclose = () => {
      console.log('[X-Twitter WS] Disconnected');
    };

    // 心跳保活
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, 25000);

    ws.addEventListener('close', () => {
      clearInterval(pingInterval);
    });

    return ws;
  } catch (err) {
    console.error('[X-Twitter WS] Connection failed:', err);
    return null;
  }
}
