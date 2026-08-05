export interface Lead {
  id: number;
  task_id: string;
  platform: string;
  data_type: string;
  data_id: string;
  user_id: string;
  nickname: string;
  avatar: string;
  ip_location: string;
  content: string;
  title: string;
  url: string;
  matched_keywords: string;
  intent_type: string;
  lead_score: number;
  intent_score?: number;
  product_score?: number;
  purchase_score?: number;
  sentiment_score?: number;
  status: 'new' | 'pending' | 'contacted' | 'qualified' | 'converted' | 'failed' | 'ignored';
  sec_uid?: string;
  notes: string;
  add_ts: number;
  last_modify_ts: number;
  create_time?: number;
  // 来源视频/作品信息(详情接口返回)
  source_aweme_id?: string;
  source_video_title?: string;
  source_video_desc?: string;
  source_video_url?: string;
  source_cover_url?: string;
  source_author_nickname?: string;
  // 增强字段(客户需求:支持复制和打开链接)
  comment_url?: string;
  profile_url?: string;
  platform_display_id?: string;
  // 获客采集增强字段(从 getuser-canrun 迁移)
  role_tag?: string;        // 角色分类: supplier(供方) / consumer(求方) / neutral(中性)
  contact_phone?: string;   // 采集到的联系电话
  contact_wechat?: string;  // 采集到的微信号
  contact_status?: string;  // 联系方式采集状态: none/pending/found/not_found
  dup_count?: number;       // 重复命中次数(相似内容累加)
}

export interface LeadListResponse {
  total: number;
  items: Lead[];
  page: number;
  page_size: number;
}

export interface LeadStats {
  total_leads: number;
  new_leads: number;
  pending_leads: number;
  contacted_leads: number;
  qualified_leads: number;
  converted_leads: number;
  failed_leads: number;
  ignored_leads: number;
  platform_distribution: Record<string, number>;
  intent_distribution: Record<string, number>;
  avg_lead_score: number;
}

export interface PromoConfig {
  product_name: string;
  product_desc: string;
  promo_link: string;
  contact_wechat: string;
  price_info: string;
  discount_info: string;
  free_quota: string;
  solution_desc: string;
  tutorial_name: string;
  tutorial_desc: string;
  cooperation_desc: string;
  commission_rate: string;
}

export interface CrawlerTask {
  id: string;
  name: string;
  platform: string;
  keywords: string[];
  crawl_type: string;
  data_types: string[];
  max_notes: number;
  min_lead_score: number;
  enable_lead_capture: boolean;
  schedule_type: string;
  status: 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';
  created_ts: number;
  total_crawled: number;
  total_leads: number;
  comment_count?: number;
  promo_config?: PromoConfig;
  publish_time_type?: number;
  // 精准获客配置(从 getuser-canrun 迁移)
  business_intent?: string;       // 业务意图描述(如"寻找需要学琵琶的用户")
  intent_keywords?: string[];     // 意向词(严格双词匹配)
  exclude_keywords?: string[];    // 排除词(命中即丢弃)
  target_role?: string;           // 目标角色: c端用户 / 厂家供应商 / 不限
  target_regions?: string[];      // 目标地区
}

export interface DashboardData {
  summary: {
    total_leads: number;
    today_new: number;
    pending_count: number;
    converted_count: number;
    conversion_rate: number;
  };
  trends: Array<{
    date: string;
    leads: number;
    converted?: number;
  }>;
  platform_distribution?: Array<{
    platform: string;
    count: number;
  }>;
  recent_leads: Lead[];
}

export const PLATFORM_MAP: Record<string, string> = {
  dy: 'dy',
  xhs: 'xhs',
  ks: 'ks',
  bili: 'bili',
  wb: 'wb',
  zhihu: 'zhihu',
  tieba: 'tieba',
  // 兼容旧key（仅用于显示已有数据，不在新建任务表单中暴露）
  douyin: 'dy',
  kuaishou: 'ks',
  weibo: 'wb',
  bilibili: 'bili',
};

export const INTENT_MAP: Record<string, string> = {
  inquiry: '咨询询问',
  recommendation: '求推荐',
  comparison: '对比询问',
  purchase: '购买意向',
  troubleshoot: '问题解决',
  discussion: '讨论交流',
};

export const STATUS_MAP: Record<string, { text: string; color: string }> = {
  new: { text: '新线索', color: '#52c41a' },
  pending: { text: '触达中', color: '#1890ff' },
  contacted: { text: '已联系', color: '#722ed1' },
  qualified: { text: '已确认', color: '#13c2c2' },
  converted: { text: '已转化', color: '#fa8c16' },
  failed: { text: '发送失败', color: '#ff4d4f' },
  ignored: { text: '已忽略', color: '#bfbfbf' },
};

// 角色分类映射(从 getuser-canrun 迁移:供方/求方/中性)
export const ROLE_MAP: Record<string, { text: string; color: string }> = {
  supplier: { text: '供方', color: '#fa541c' },   // 服务商/厂家(广告引流)
  consumer: { text: '求方', color: '#52c41a' },   // C端用户(咨询求购,精准目标)
  neutral: { text: '中性', color: '#8c8c8c' },    // 普通/无法判定
};

// 联系方式采集状态映射
export const CONTACT_STATUS_MAP: Record<string, { text: string; color: string }> = {
  none: { text: '未采集', color: '#bfbfbf' },
  pending: { text: '采集中', color: '#1890ff' },
  found: { text: '已采集', color: '#52c41a' },
  not_found: { text: '无联系方式', color: '#8c8c8c' },
};
