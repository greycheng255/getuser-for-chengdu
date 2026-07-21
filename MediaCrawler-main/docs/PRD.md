# MediaCrawler 获客系统 PRD

> **文档版本**: v6.6（商业化套餐版）
> **编写日期**: 2026-07-15
> **状态**: 整合完成
> **说明**: 本文档整合了历史 v1.0（基础版）、v2.0（零学习成本版）、v4.0（自动化获客合并版）三版 PRD 的全部内容,去除重复,统一编号,并将"已实现但未纳入正文"的功能统一纳入对应章节,确保文档与代码实现一致。

---

## 1. 项目概述

### 1.1 背景
MediaCrawler 是一个多平台自媒体数据采集框架,支持小红书、抖音、快手、B站、微博、贴吧、知乎等平台。在已有数据采集能力基础上,需要构建系统化的**获客线索管理**能力,将散落在评论区的潜在客户咨询转化为可运营的线索资产。

### 1.2 目标
构建一套完整的 **AI 获客系统**,在现有采集框架基础上:
- 自动识别用户咨询意图(如"哪里有AI聚合平台""求推荐GPT工具")
- 捕获并管理潜在客户线索
- 提供可视化的线索管理界面
- 支持线索跟进、转化追踪与自动化触达

### 1.3 核心价值
- **自动化获客**: 7x24 小时自动监控多平台用户咨询
- **精准识别**: AI 意图识别,过滤无效信息,高意向必须具备成交意愿
- **高效管理**: 线索分级、状态追踪、批量操作
- **数据驱动**: 统计分析,优化获客策略
- **合规安全**: 平台名称脱敏、用户可见处统一"采集"表述、用户级数据隔离

### 1.4 产品愿景
基于评论数据中的高意向/中意向用户,自动分析其需求,生成个性化广告内容,并通过自动化流程触达目标客户,实现"发现 → 分析 → 触达 → 转化"的全链路自动化。

### 1.5 设计哲学:零学习成本

#### 1.5.1 核心原则
- **零学习成本**:用户第一次打开就知道怎么操作
- **三步完成**:任何核心操作不超过 3 步
- **即时反馈**:每个操作都有明确的结果提示
- **智能默认**:系统自动选择最合适的配置,用户只需确认

#### 1.5.2 用户场景

| 用户类型 | 目标 | 当前痛点 | 解决方案 |
|---------|------|---------|---------|
| 小白运营 | 每天自动获客 | 参数太多看不懂 | 一键创建+智能推荐 |
| 资深运营 | 精准获客 | 筛选条件藏太深 | 全局搜索+快捷筛选 |
| 管理者 | 看效果报表 | 数据分散在各页 | 首页汇总+一键下钻 |

---

## 2. 系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      前端层 (React + Vite)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  任务管理面板  │  │  获客线索面板  │  │  数据统计面板     │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      API层 (FastAPI)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ /api/crawler │  │ /api/leads   │  │ /api/tasks       │  │
│  │ 采集任务控制  │  │ 线索CRUD     │  │ 任务/意向/触达    │  │
│  ├──────────────┼  ├──────────────┤  ├──────────────────┤  │
│  │ /api/business│  │ /v1/external │  │ /api/cookies     │  │
│  │ 客户/线索包   │  │ 外部API对接   │  │ Cookie池管理     │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      业务逻辑层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ CrawlerManager│  │LeadDetector  │  │ AutoOutreach     │  │
│  │ 采集任务管理  │  │ 意图识别引擎  │  │ 自动化触达引擎    │  │
│  ├──────────────┼  ├──────────────┤  ├──────────────────┤  │
│  │ AccountPool  │  │CookieManager │  │ 需求分析/文案生成 │  │
│  │ 账号池/IP轮换 │  │ Cookie单一源 │  │                  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      数据存储层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  PostgreSQL  │  │  Redis(可选) │  │  本地文件存储     │  │
│  │  主数据库     │  │  会话/缓存   │  │  截图/导出文件    │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | React 18 + Vite + Tailwind CSS | 现代化UI框架 |
| 后端 | FastAPI + Python 3.11 | 高性能异步API,全链路 async/await |
| 数据库 | PostgreSQL 15+ | 主数据存储 |
| ORM | SQLAlchemy 2.0 | 异步数据库操作 |
| 采集 | Playwright + asyncio + CDP | 浏览器自动化(连接真实Chrome) |
| 浏览器 | 系统 Chrome(非 Playwright Chromium) | 保证浏览器指纹一致性 |
| 虚拟显示 | Xvfb | 无头环境下支持 headed 模式 |
| 通信 | WebSocket | 日志/状态实时推送 |

### 2.3 信息架构(4个入口)

```
获客系统(仅4个入口)
├── 🏠 首页(Dashboard)
│   ├── 今日获客概况(数字卡片)
│   ├── 最近捕获的线索(列表,点击可处理)
│   ├── 快速创建任务(大按钮)
│   └── 快捷入口:待处理线索 | 运行中任务 | 数据导出
│
├── 🎯 获客任务(原任务管理)
│   ├── 任务卡片列表(可视化进度)
│   ├── 一键创建任务(3步向导)
│   └── 任务详情(实时日志+采集数据预览+评论获客)
│
├── 👥 客户线索(原获客线索)
│   ├── 线索看板(按状态Tab切换:新线索/已联系/已转化)
│   ├── 全局搜索(关键词搜索)
│   ├── 快捷操作(一键标记/导出/忽略)
│   └── 线索详情(侧边滑出,快速跟进)
│
└── ⚙️ 设置
    ├── 获客偏好(关键词/平台/评分规则)
    ├── 通知设置(仅 Webhook)
    ├── 账号管理
    ├── Cookie 管理(用户级隔离)
    └── 运行日志
```

**删除/合并的页面:**
- ❌ 数据统计页 → 合并到首页 Dashboard
- ❌ 系统日志页 → 移入设置-运行日志
- ❌ 用户管理页 → 移入设置-账号管理

### 2.4 核心流程

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  1.发现用户  │ → │  2.需求分析  │ → │  3.内容生成  │ → │  4.自动触达  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
      │                  │                  │                  │
      ▼                  ▼                  ▼                  ▼
  采集评论数据      解析评论内容        生成个性化        访问用户主页
  筛选高意向用户    识别需求类型        广告文案(链接混淆) 发送私信/评论回复
```

---

## 3. 功能模块规划

```
获客系统
├── 3.1 意图识别引擎 (LeadDetector)
│   ├── 关键词匹配规则(任务相关词+通用强意向+行业信号)
│   ├── 意向精准化降级(回忆/讨论/长文本/过去式购买)
│   ├── 核心词提取(去前导动词/无意义后缀)
│   └── 评分算法(分级 + 同步降级)
│
├── 3.2 线索捕获模块 (LeadCapture)
│   ├── 扫描入库(全量/增量)
│   ├── 低质量内容过滤
│   ├── 跨任务去重(task_id + comment_id)
│   └── 评论真实时间回填
│
├── 3.3 线索管理模块 (LeadManagement)
│   ├── 线索列表(关键词搜索)
│   ├── 线索详情(侧边滑出)
│   ├── 状态流转(new/contacted/qualified/converted/ignored)
│   └── 跟进记录(follow-ups)
│
├── 3.4 任务管理模块 (TaskManagement)
│   ├── 创建任务(3步向导)
│   ├── 任务监控(实时日志/进度)
│   ├── 关键词配置
│   └── 调度策略(仅 once)
│
├── 3.5 数据统计模块 (Dashboard)
│   ├── 实时看板
│   ├── 平台分布/意图分布
│   └── 高价值线索 Top N
│
├── 3.6 系统配置模块 (Settings)
│   ├── 关键词库管理
│   ├── 评分规则(硬编码,前端不可配置)
│   ├── 通知设置(仅 Webhook)
│   ├── 账号管理
│   └── Cookie 池管理(用户级)
│
├── 3.7 自动化获客模块 (AutoOutreach)
│   ├── 智能需求分析引擎
│   ├── 个性化广告内容生成(链接混淆)
│   ├── 自动化触达引擎(私信/评论回复)
│   └── 防封策略(频率限制/风控冷却/人类行为模拟)
│
├── 3.8 商业化模块 (Business)
│   ├── 客户管理(BusinessUser)
│   ├── 线索包管理(LeadPackage,按条计费)
│   ├── 线索分配(LeadAssignment)
│   ├── 购买订单(PurchaseOrder)
│   ├── API 客户端(ApiClient,双模式)
│   └── 跟进记录(FollowUpRecord)
│
└── 3.9 外部API对接模块 (ExternalAPI)
    ├── 直拉模式(包年/付费用户)
    ├── 按条计费模式(购买线索包后拉取)
    └── 状态回调(Webhook)
```

---

## 4. 详细功能设计

### 4.1 意图识别引擎 (LeadDetector)

#### 4.1.1 识别维度

| 维度 | 说明 | 权重 |
|------|------|------|
| **咨询意图** | "哪里有""怎么找""求推荐"等 | 40% |
| **产品关键词** | 任务相关词+通用产品词 | 35% |
| **购买信号** | "多少钱""怎么买""价格"等 | 15% |
| **情感倾向** | 积极/消极/中性 | 10% |

#### 4.1.2 意图分类

```python
INTENT_TYPES = {
    "inquiry": "咨询询问",      # "哪里有AI工具"
    "recommendation": "求推荐",  # "求推荐好用的GPT"
    "comparison": "对比询问",    # "ChatGPT和Claude哪个好"
    "purchase": "购买意向",      # "怎么买GPT会员"
    "troubleshoot": "问题解决",  # "ChatGPT打不开怎么办"
    "discussion": "讨论交流",    # "分享一个AI工具"
}
```

#### 4.1.3 评分算法(基础版)

```python
def calculate_lead_score(content, title=""):
    score = 0
    # 1. 咨询意图匹配 (0-40分)
    inquiry_patterns = ["哪里有", "怎么找", "求推荐", "请问", "有没有"]
    matched_inquiry = sum(1 for p in inquiry_patterns if p in content)
    score += min(40, matched_inquiry * 10)

    # 2. 产品关键词匹配 (0-35分)
    ai_keywords = ["chatgpt", "gpt", "ai", "claude", "midjourney"]
    matched_keywords = sum(1 for k in ai_keywords if k in content.lower())
    score += min(35, matched_keywords * 7)

    # 3. 购买信号 (0-15分)
    purchase_signals = ["价格", "多少钱", "怎么买", "会员"]
    matched_purchase = sum(1 for p in purchase_signals if p in content)
    score += min(15, matched_purchase * 5)

    # 4. 情感加分 (0-10分)
    if any(w in content for w in ["急需", "求求", "拜托"]):
        score += 10

    return min(100, score)
```

> **完整评分算法(含意向精准化降级、行业信号、核心词提取)** 详见 §10.1。

#### 4.1.4 关键词库管理

```python
KEYWORD_LIBRARY = {
    "ai_chat": {
        "name": "AI聊天工具",
        "keywords": ["chatgpt", "claude", "gemini", "文心一言", "通义千问"],
        "weight": 1.2,
        "category": "product"
    },
    "ai_image": {
        "name": "AI图像生成",
        "keywords": ["midjourney", "stable diffusion", "dalle", "gpt image"],
        "weight": 1.2,
        "category": "product"
    },
    "ai_platform": {
        "name": "AI聚合平台",
        "keywords": ["聚合平台", "ai导航", "ai工具箱", "poe", "cursor"],
        "weight": 1.5,
        "category": "platform"
    },
}
```

### 4.2 线索捕获模块 (LeadCapture)

#### 4.2.1 扫描入库流程

```
采集获取评论数据
    │
    ▼
┌─────────────────┐
│  内容预处理      │  清洗HTML标签、去除广告
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  低质量过滤      │  空/纯表情/极短内容/纯标点数字
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  意图识别引擎    │  LeadDetector.detect()
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
 是线索     非线索
    │         │
    ▼         ▼
┌────────┐  ┌────────┐
│跨任务去重│  │ 丢弃   │
│写入数据库│  │        │
└────────┘  └────────┘
```

#### 4.2.2 去重机制

```python
DEDUPLICATION_RULES = {
    "strict": {
        "fields": ["user_id", "content_hash"],
        "time_window": "24h",
        "description": "同一用户24小时内相同内容"
    },
    "normal": {
        "fields": ["content_hash"],
        "time_window": "7d",
        "description": "7天内相同内容"
    },
    "loose": {
        "fields": ["user_id"],
        "time_window": "1h",
        "description": "同一用户1小时内只算一条"
    }
}
```

> **跨任务去重**:不同任务爬取到的同一条评论按 `(task_id, comment_id)` 联合保留,确保任务间数据互不影响(详见 §10.2)。

### 4.3 线索管理模块 (LeadManagement)

#### 4.3.1 线索状态流转

```
┌─────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  new    │───▶│ contacted│───▶│ qualified│───▶│ converted│
│ (新线索) │    │ (已联系)  │    │ (已确认)  │    │ (已转化)  │
└────┬────┘    └──────────┘    └──────────┘    └──────────┘
     │
     │ (无效线索)
     ▼
┌─────────┐
│ ignored │
│ (已忽略) │
└─────────┘
```

> **注意**:线索看板目前仅支持 Tab 切换状态,**未实现拖拽变更状态**(详见 §11.2 验收标准)。

#### 4.3.2 线索字段定义

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| task_id | String | 关联任务ID |
| platform | String | 来源平台代号(dy/xhs/ks/bili/wb/zhihu/tieba) |
| data_type | String | 数据类型 (note/comment/video/answer) |
| data_id | String | 原始数据ID |
| user_id | String | 用户ID |
| sec_uid | String | 安全用户ID(抖音主页链接用) |
| nickname | String | 用户昵称 |
| avatar | Text | 用户头像 |
| ip_location | String | IP属地 |
| content | Text | 咨询内容 |
| title | Text | 帖子标题 |
| url | Text | 原始链接 |
| matched_keywords | Text | 匹配关键词 |
| intent_type | String | 意图类型 |
| lead_score | Integer | 线索评分 (0-100) |
| level | String | 意向等级(high/medium/low) |
| status | String | 线索状态 |
| notes | Text | 跟进备注 |
| add_ts | BigInteger | 入库时间戳 |
| create_time | BigInteger | 评论真实创建时间戳(秒,从原始评论表回填) |
| last_modify_ts | BigInteger | 更新时间 |
| owner_user_id | String(64) | 归属用户ID(数据隔离,索引) |
| source_aweme_id | String | 源视频/作品ID |
| source_video_title | Text | 源视频标题 |
| source_video_desc | Text | 源视频描述 |
| source_video_url | Text | 源视频链接 |
| source_cover_url | Text | 源视频封面URL |
| source_author_nickname | String | 源视频作者昵称 |

#### 4.3.3 筛选与排序

```python
FILTERS = {
    "platform": ["dy", "xhs", "ks", "bili", "wb", "zhihu", "tieba"],
    "intent_type": ["inquiry", "recommendation", "comparison", "purchase", "troubleshoot"],
    "status": ["new", "contacted", "qualified", "converted", "ignored"],
    "score_range": [(0, 30), (30, 60), (60, 80), (80, 100)],
    "date_range": ["today", "week", "month", "custom"]
}

SORT_OPTIONS = [
    ("lead_score_desc", "评分从高到低"),
    ("lead_score_asc", "评分从低到高"),
    ("add_ts_desc", "最新优先"),
    ("add_ts_asc", "最早优先"),
]
```

> **限制**:线索搜索仅支持关键词搜索,无多维度检索;LeadList 未实现虚拟滚动(详见 §11.2)。

### 4.4 任务管理模块 (TaskManagement)

#### 4.4.1 任务配置

```python
class CrawlerTaskConfig:
    """采集任务配置"""
    # 基础配置
    platform: str              # 目标平台代号(dy/xhs/ks/bili/wb/zhihu/tieba)
    keywords: List[str]        # 搜索关键词
    crawl_type: str           # 采集类型 (search/creator/trending)
    data_types: List[str]     # 数据类型 (note/comment/video)

    # 高级配置
    max_notes: int = 100      # 最大采集数量
    crawl_interval: int = 5   # 采集间隔(秒)
    retry_times: int = 3      # 重试次数(每次切换Cookie+IP)
    timeout: int = 1800       # 超时时间(秒)

    # 获客配置
    enable_lead_capture: bool = True    # 启用获客
    min_lead_score: int = 50            # 最低评分阈值
    auto_notify: bool = True            # 自动通知(仅Webhook)

    # 调度配置
    schedule_type: str = "once"         # 调度类型(仅 once)
```

> **硬约束**:定时任务仅支持 `once` 类型,无 daily/weekly 自动执行功能(详见 §11.2)。

#### 4.4.2 任务状态

```python
TASK_STATUS = {
    "pending": "待执行",
    "running": "执行中",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消"
}
```

### 4.5 数据统计模块 (Dashboard)

#### 4.5.1 核心指标

| 指标 | 说明 | 计算方式 |
|------|------|----------|
| 线索总数 | 累计捕获线索 | COUNT(*) WHERE owner_user_id=? |
| 新增线索(今日) | 今日新增 | COUNT(*) WHERE date = today |
| 转化率 | 转化线索占比 | converted / total * 100% |
| 平均评分 | 线索质量均值 | AVG(lead_score) |
| 响应时间 | 首次响应平均时长 | AVG(first_response_time) |
| 平台分布 | 各平台线索占比 | GROUP BY platform |
| 意图分布 | 各意图类型占比 | GROUP BY intent_type |

#### 4.5.2 数据看板

```
┌─────────────────────────────────────────────────────────────┐
│  📊 获客数据看板                                              │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ 线索总数  │  │ 今日新增  │  │ 转化率   │  │ 平均评分  │  │
│  │  1,234   │  │   +56    │  │  12.5%   │  │  72.3    │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
│                                                             │
│  ┌────────────────────┐    ┌────────────────────┐        │
│  │   线索趋势图        │    │   平台分布饼图      │        │
│  │   (近7天/30天)     │    │                    │        │
│  └────────────────────┘    └────────────────────┘        │
│                                                             │
│  ┌────────────────────────────────────────────────────┐  │
│  │           最新高价值线索 (Top 10)                    │  │
│  │  ┌────┬────────┬──────────┬──────┬────────┬──────┐ │  │
│  │  │平台│  用户  │  内容    │评分  │ 意图   │时间  │ │  │
│  │  ├────┼────────┼──────────┼──────┼────────┼──────┤ │  │
│  │  │xhs │ 用户A  │哪里有... │ 95   │inquiry │2分钟前│ │  │
│  │  └────┴────────┴──────────┴──────┴────────┴──────┘ │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

> **限制**:转化漏斗图、平台对比 Analytics 页未挂到路由(详见 §11.2)。

### 4.6 自动化获客模块 (AutoOutreach)

#### 4.6.1 智能需求分析引擎

**输入**:用户评论内容 + 意向标签
**输出**:结构化需求报告

```typescript
interface UserNeedAnalysis {
  user_id: string;
  nickname: string;
  sec_uid: string;
  need_type: 'product_inquiry' | 'price_sensitive' | 'tutorial_request' |
             'cooperation' | 'comparison' | 'frustration' | 'general';
  need_summary: string;
  need_detail: string;
  pain_points: string[];
  product_preferences: string[];
  budget_sensitivity: 'high' | 'medium' | 'low';
  urgency: 'urgent' | 'normal' | 'low';
  recommended_pitch: string;
  recommended_products: string[];
}
```

**需求类型定义**:

| 类型 | 关键词 | 示例评论 | 营销策略 |
|------|--------|----------|----------|
| product_inquiry | 哪里买、求推荐、有没有 | "哪里有好用的AI聚合平台?" | 直接推荐产品+优惠码 |
| price_sensitive | 多少钱、贵不贵、免费 | "这个要多少钱?有免费的吗?" | 强调性价比+限时优惠 |
| tutorial_request | 怎么学、教程、入门 | "新手怎么入门AI?" | 提供免费教程+进阶付费 |
| cooperation | 合作、代理、资源 | "我有客户资源,想合作" | 介绍合作模式+分佣方案 |
| comparison | 对比、哪个好、vs | "ChatGPT和Claude哪个好?" | 提供对比分析+推荐自家 |
| frustration | 麻烦、不行、坑 | "注册太麻烦了" | 强调便捷性+专属服务 |
| general | 其他一般性评论 | "确实不错" | 品牌曝光+引导关注 |

#### 4.6.2 个性化广告内容生成

**输入**:需求分析结果 + 产品库 + 推广配置
**输出**:个性化广告文案(含链接混淆)

```typescript
interface AdContent {
  user_id: string;
  direct_message: string;   // 私信文案
  comment_reply: string;    // 评论回复文案
  profile_message: string;  // 主页留言文案
  version: 'friendly' | 'professional' | 'casual';
  products: ProductInfo[];
  call_to_action: string;
}
```

**文案模板库**(以 product_inquiry 为例):

```typescript
const messageTemplates = {
  product_inquiry: {
    friendly: `嗨 {nickname}!看到你在找{product},我们刚好有解决方案 😊
{product_desc}
现在注册还有专属优惠,要不要了解一下?`,
    professional: `您好 {nickname},
注意到您对{product}感兴趣。我们是{company},专注于{field}。
{product_desc}
如有兴趣,可以安排一次免费演示。`,
  },
};
```

> **链接混淆**:文案中的 URL 会被随机替换为 10 种变体之一(详见 §10.4),绕过平台私信链接过滤。

#### 4.6.3 自动化触达引擎

**功能**:模拟人工操作,自动访问用户主页并发送私信或回复评论

```typescript
interface OutreachTask {
  id: string;
  user_id: string;
  sec_uid: string;
  platform: 'dy' | 'xhs';
  method: 'direct_message' | 'comment_reply' | 'follow_then_dm';
  status: 'pending' | 'running' | 'completed' | 'failed';
  steps: OutreachStep[];
  result?: {
    success: boolean;
    message: string;
    screenshot?: string;
    timestamp: number;
  };
}
```

**触达流程(抖音)**:

```
1. 打开用户主页
   → https://www.douyin.com/user/{sec_uid}
2. 点击"私信"按钮
   → 等待私信窗口弹出
3. 输入生成的文案(链接已混淆)
   → 粘贴个性化广告内容
4. 点击发送
   → 确认发送成功
5. 截图保存
   → 记录触达结果
```

**防封策略**:
- 随机延迟:每个操作间隔 3-10 秒随机
- 频率限制:每小时≤30条,每天≤720条,递增间隔(连续发送越多间隔越长)
- 风控冷却:检测到风控信号自动进入 30 分钟冷却期
- 内容随机化:同义替换、零宽字符、标点变体、句子重排
- 时间段分散:在 9:00-11:00, 14:00-16:00, 20:00-22:00 分散发送
- 人工审核:高意向用户发送前可人工确认

### 4.7 商业化模块 (Business)

#### 4.7.1 商业模式

仅支持**线索包按条计费**模型,无"包年订阅"模型。包年/付费 API 用户通过"直拉模式"按条件拉取线索,无需购买线索包。

#### 4.7.2 客户管理 (BusinessUser)

```python
class BusinessUser:
    user_id: str           # 客户ID
    name: str              # 客户名称
    api_key: str           # API密钥
    webhook_url: str       # Webhook回调地址
    push_mode: str         # 推送模式(batch/realtime)
    balance: int           # 余额(分)
    status: str            # 状态(normal/disabled)
    owner_user_id: str     # 归属系统用户ID(数据隔离)
```

#### 4.7.3 线索包管理 (LeadPackage)

```python
class LeadPackage:
    id: str                # 线索包ID
    name: str              # 包名
    description: str       # 描述
    platform: str          # 平台筛选
    task_id: str           # 任务筛选
    min_score: int         # 最低意向分
    max_score: int         # 最高意向分
    level: str             # 意向等级(high/medium/low/all)
    ip_location: str       # 地域筛选
    keyword: str           # 关键词筛选
    total_count: int       # 线索总数
    available_count: int   # 可售数量
    sold_count: int        # 已售数量
    price_per_lead: int    # 单价(分)
    total_price: int       # 总价(分)
    expire_days: int       # 有效期天数(默认90)
    status: str            # 状态(draft/active/sold_out/discontinued)
    owner_user_id: str     # 归属系统用户ID
```

#### 4.7.4 线索分配 (LeadAssignment)

```python
class LeadAssignment:
    lead_id: int           # 线索ID
    package_id: str        # 线索包ID
    business_user_id: str  # 分配给的业务用户ID
    assign_type: str       # 分配类型(purchase/manual/auto/api_pull)
    price_paid: int        # 支付金额(分)
    status: str            # 状态(assigned/used/expired/refunded/pulled)
    expire_ts: int         # 过期时间戳
    assigned_ts: int       # 分配时间戳
    used_ts: int           # 使用时间戳
    owner_user_id: str     # 归属系统用户ID
```

> **pulled 状态**:API 直拉模式下的去重标记,前端显示为"已拉取"(蓝色),不应出现在"已分配线索"列表中(详见 §10.3.2)。

#### 4.7.5 跟进记录 (FollowUpRecord)

```python
class FollowUpRecord:
    lead_id: int           # 线索ID
    business_user_id: str  # 业务用户ID
    content: str           # 跟进内容
    follow_up_type: str    # 跟进类型(call/meeting/note)
    next_follow_up_ts: int # 下次跟进时间
    owner_user_id: str     # 归属系统用户ID
```

### 4.8 外部API对接模块 (ExternalAPI)

#### 4.8.1 双模式设计

```
┌─────────────────────────────────────────────────────────────┐
│                    API 客户端 (ApiClient)                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  模式1:直拉模式(包年/付费用户)                              │
│  ────────────────────────────────────                       │
│  · 直接按条件拉取 owner_user_id 名下所有线索                 │
│  · 无需购买线索包                                            │
│  · 不消耗余额                                                │
│  · 拉取后标记 status=pulled(去重)                           │
│                                                             │
│  模式2:按条计费模式                                          │
│  ────────────────────────────────────                       │
│  · 先调 /packages/purchase 购买线索包                        │
│  · 再用 package_id 拉取已购买线索                            │
│  · 消耗余额                                                  │
│  · 拉取后 status 保持 assigned                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 4.8.2 API 客户端管理 (ApiClient)

```python
class ApiClient:
    client_id: str         # 客户端ID
    name: str              # 客户端名称
    api_key: str           # API密钥(唯一)
    webhook_url: str       # Webhook回调地址
    push_mode: str         # 推送模式(batch/realtime)
    push_status: str       # 推送状态(normal/error)
    owner_user_id: str     # 归属系统用户ID
```

> **外部 API 对接详细文档**:见 `docs/api-integration-guide.md`。

---

## 5. UI/UX 设计

### 5.1 整体布局

```
┌─────────────────────────────────────────────────────────────┐
│  🕷️ MediaCrawler 获客系统          [🔔] [👤 admin] [⚙️]   │
├──────────┬──────────────────────────────────────────────────┤
│          │                                                  │
│  📋 导航栏 │              主内容区域                          │
│          │                                                  │
│  ┌──────┐│  ┌────────────────────────────────────────────┐  │
│  │仪表盘 ││  │                                            │  │
│  ├──────┤│  │           根据路由显示不同页面               │  │
│  │任务管理││  │                                            │  │
│  ├──────┤│  │   - 仪表盘页                                │  │
│  │获客线索││  │   - 任务管理页                              │  │
│  ├──────┤│  │   - 线索列表页                              │  │
│  │系统设置││  │   - 系统设置页                              │  │
│  └──────┘│  └────────────────────────────────────────────┘  │
└──────────┴──────────────────────────────────────────────────┘
```

### 5.2 首页 Dashboard

```
┌─────────────────────────────────────────────────────────────┐
│  MediaCrawler 获客系统                    [🔔] [👤]         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────┐│
│  │ 今日新线索  │  │ 累计获客    │  │ 转化率     │  │ 进行中 ││
│  │    23      │  │   1,245    │  │   12.5%   │  │  3个   ││
│  │ ↑ 5 vs昨天 │  │            │  │            │  │        ││
│  └────────────┘  └────────────┘  └────────────┘  └────────┘│
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  🚀 快速开始                                         │   │
│  │  [ + 新建获客任务 ]    [ 📥 导出今日线索 ]          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌────────────────────────┐  ┌──────────────────────────┐  │
│  │ 📋 最新线索(10条)      │  │ 📊 近7天获客趋势        │  │
│  │ 用户A  xhs  95分       │  │    📈 折线图             │  │
│  │ "哪里有AI聚合平台..."  │  │                          │  │
│  │ [标记已联系] [忽略]    │  │                          │  │
│  └────────────────────────┘  └──────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 🔄 运行中的任务(3个)                                 │   │
│  │ 任务1: AI工具监控  [██████░░░░] 60%  预计10分钟后完成 │   │
│  │ 任务2: dy获客      [████████░░] 80%  预计5分钟后完成  │   │
│  │ 任务3: 知乎监控    [██░░░░░░░░] 20%  进行中...       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

> **限制**:首页加载未做性能优化(详见 §11.2)。

### 5.3 获客任务页

#### 5.3.1 任务列表(卡片式)

```
┌─────────────────────────────────────────────────────────────┐
│  获客任务                                      [ + 新建任务 ]│
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 🟢 AI工具监控                    [运行中] [⏸] [🗑]  │   │
│  │ 平台: xhs | 关键词: AI工具, ChatGPT                 │   │
│  │ [████████████████████░░░░░░░░░░] 67%               │   │
│  │ 已获线索: 156 | 预计完成: 5分钟后                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ ⚪ dy获客测试                    [待启动] [▶] [✏]   │   │
│  │ 平台: dy | 关键词: AI聚合平台                        │   │
│  │ 上次运行: 昨天 14:30 | 获客: 45条                   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

#### 5.3.2 新建任务向导(3步完成)

**Step 1: 选择获客目标(单选,大卡片)**
```
你想从哪里获客?

[ 🍠 xhs ]  [ 🎵 dy ]  [ 📺 bili ]
[ 🐦 wb ]   [ ❓ zhihu ] [ 📌 tieba ]

选中后自动推荐热门关键词
```

> **合规约束**:平台选择卡片仅显示代号(dy/xhs/ks/bili/wb/zhihu/tieba),不暴露正式名称(详见 §10.5)。

**Step 2: 填写关键词(输入框+智能推荐)**
```
你想找什么样的客户?

关键词: [ AI工具, 聚合平台, ChatGPT        ]
        💡 推荐添加: "大模型", "LLM", "AI导航"

获客强度: [ 标准 ] [ 积极 ] [ 深度 ]
         100条   500条   2000条
```

**Step 3: 确认并启动**
```
任务预览
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
平台:     xhs
关键词:   AI工具, 聚合平台, ChatGPT
预计获客: 100条线索
预计耗时: 约15分钟
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[ 保存为草稿 ]    [ 立即启动 ]
```

#### 5.3.3 任务详情页

任务详情页包含以下 Tab:
- **任务信息**:基础配置、运行状态
- **📊 采集数据**:展示该任务爬取的视频/笔记数据(按核心词匹配)
- **💬 评论获客**:展示评论线索,按高/中/低意向分级(仅 dy/xhs/ks/bili/wb/zhihu/tieba 平台)
- **运行日志**:实时日志(WebSocket 推送)
- **获客任务**:自动化触达任务列表

> **平台差异化展示**:xhs 任务详情页**必须屏蔽"采集数据"和"评论获客"Tab**(详见 §11.1 未实现清单)。

### 5.4 客户线索页

#### 5.4.1 线索看板(Tab 切换式)

```
┌─────────────────────────────────────────────────────────────┐
│  客户线索                                      [ 🔍 搜索... ]│
├─────────────────────────────────────────────────────────────┤
│  全部 | 新线索(12) | 已联系(8) | 已确认(3) | 已转化(1)      │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ 🆕 新线索     │  │ 📞 已联系    │  │ ✅ 已转化     │     │
│  │    12条      │  │    8条       │  │    1条       │     │
│  ├──────────────┤  ├──────────────┤  ├──────────────┤     │
│  │ 用户A  95分  │  │ 用户C  88分  │  │ 用户F  92分  │     │
│  │ "哪里有..."  │  │ "已加微信"   │  │ "已付款"     │     │
│  │ [联系] [忽略]│  │ [推进] [备注]│  │ [查看订单]   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

> **限制**:线索看板目前仅支持 Tab 切换状态,**未实现拖拽变更状态**(详见 §11.2)。

#### 5.4.2 线索详情(侧边滑出)

```
┌────────────────────────────────────────────┐
│ 👤 用户A                        [×]        │
├────────────────────────────────────────────┤
│ 平台: xhs  |  评分: 95/100                 │
│ 时间: 2分钟前                              │
├────────────────────────────────────────────┤
│ 📄 原始内容                                │
│ "哪里有好用的AI聚合平台?求推荐!            │
│  想找一个能同时用ChatGPT和Claude的          │
│  工具,付费也可以"                          │
│                                            │
│ 🏷️ 识别标签                               │
│ [求推荐] [购买意向] [AI聚合平台]           │
│                                            │
│ 🔗 原始链接                                │
│ https://xhs.example.com/post/123           │
│                                            │
│ 📹 源视频信息                              │
│ 标题: AI工具盘点                           │
│ 作者: 科技博主                             │
│                                            │
├────────────────────────────────────────────┤
│ 跟进状态                                   │
│ [ 新线索 ▼ ]                               │
│ 备注                                       │
│ [ 填写跟进记录... ]                        │
│                                            │
│ [ 📋 复制信息 ]  [ 📤 导出 ]               │
│ [ ✅ 标记已联系 ]                           │
└────────────────────────────────────────────┘
```

### 5.5 评论获客页

```
┌─────────────────────────────────────────────────────────────┐
│  评论获客 (4480条)                              [导出CSV]   │
├─────────────────────────────────────────────────────────────┤
│  高意向: 130    中意向: 1371    低意向: 2979               │
│                                                             │
│  [全部显示 ▼]  [🤖 批量分析需求]  [📤 批量生成文案]  [🚀 开始触达]│
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 👤 用户1931095371404  河南  [潜在需求]  [51分]       │   │
│  │ "codex需要国外的手机号,虚拟的还不行😭"              │   │
│  │ 🎯 需求分析: 需要国内可用的AI编程工具               │   │
│  │ 💡 推荐话术: "试试我们的AI编程助手,无需国外手机号   │   │
│  │              直接微信扫码就能用!"                   │   │
│  │ [复制信息] [访问主页] [🤖 分析需求] [✉️ 生成文案] [🚀 触达]│   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

> **单条私信按钮 loading 必须按 comment_id 隔离**(用 outreachLoadingMap),不能用全局 outreachLoading,避免所有评论同时显示 loading。

### 5.6 设置页

```
┌─────────────────────────────────────────────────────────────┐
│  设置                                                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 🎯 获客偏好                                          │   │
│  │ [ 关键词库管理 → ]  [ 评分规则(只读) → ]            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 🔔 通知设置 (仅 Webhook)                            │   │
│  │ [ Webhook 配置 → ]                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 🍪 Cookie 管理 (用户级隔离)                         │   │
│  │ [ dy Cookie → ]  [ xhs Cookie → ]  ...              │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 👤 账号管理                                          │   │
│  │ 当前用户: admin (管理员)                             │   │
│  │ [ 修改密码 ] [ 退出登录 ]                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 📋 运行日志                                          │   │
│  │ [ 查看系统运行日志 → ]                               │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

> **限制**:通知方式仅实现 Webhook,无邮件/站内消息通知(详见 §11.2)。
> **Cookie 管理访问控制**:用户可管理自己的 Cookie 和 Cookie 池,但无法查看或修改他人的 Cookie。

### 5.7 交互规范

#### 5.7.1 按钮优先级
```
主操作:   [ 蓝色实心 ]  立即启动 / 确认创建 / 标记已联系
次操作:   [ 白色边框 ]  保存草稿 / 取消 / 返回
危险操作: [ 红色文字 ]  删除 / 忽略线索
快捷操作: [ 图标按钮 ]  ⏸ ▶ ✏ 🗑
```

#### 5.7.2 状态颜色
```
🟢 运行中 / 成功 / 已转化
🟡 待启动 / 警告 / 已联系
🔵 已完成 / 信息 / 已拉取
🔴 失败 / 错误 / 已忽略 / 已过期
⚪ 草稿 / 默认
```

#### 5.7.3 空状态设计
```
还没有线索?
[ + 创建第一个获客任务 ]

或

暂无运行中的任务
[ + 新建任务 ] 或 [ 📋 查看任务模板 ]
```

---

## 6. API 接口设计

### 6.1 内部 API

#### 6.1.1 获客线索接口

```yaml
# 线索列表
GET /api/leads/list
Parameters:
  - task_id: string (可选)
  - platform: string (可选) dy|xhs|ks|bili|wb|zhihu|tieba
  - intent_type: string (可选)
  - status: string (可选) new|contacted|qualified|converted|ignored
  - min_score: int (可选) 0-100
  - keyword: string (可选) 搜索关键词
  - page: int (默认1)
  - page_size: int (默认20, 最大100)
Response: { total, items, page, page_size }

# 线索统计
GET /api/leads/stats
Response: { total_leads, new_leads, contacted_leads, qualified_leads, converted_leads, ignored_leads, platform_distribution, intent_distribution, avg_lead_score }

# 更新线索状态
POST /api/leads/{lead_id}/status
Body: { status, notes }
Response: { success, message }

# 线索详情
GET /api/leads/{lead_id}
Response: Lead 对象

# 批量操作
POST /api/leads/batch
Body: { ids, action, status }
Response: { success, affected_count }

# 删除任务下所有线索
DELETE /api/leads/task/{task_id}
```

#### 6.1.2 任务管理接口

```yaml
# 任务列表
GET /api/tasks/list
Response: { items, total }

# 创建任务
POST /api/tasks
Body: { platform, keywords, crawl_type, data_types, max_notes, enable_lead_capture, min_lead_score }
Response: { task_id, status }

# 启动任务
POST /api/tasks/{task_id}/start
# 暂停任务
POST /api/tasks/{task_id}/pause
# 重试任务
POST /api/tasks/{task_id}/retry
# 删除任务
DELETE /api/tasks/{task_id}
# 删除任务评论
DELETE /api/tasks/{task_id}/comments
# 任务详情(含视频/评论数据)
GET /api/tasks/{task_id}?comment_offset=0&comment_limit=100
# 扫描线索(全量/增量)
POST /api/tasks/{task_id}/scan-leads?force_full=false
# 任务线索汇总
GET /api/tasks/{task_id}/leads-summary
# 任务日志
GET /api/tasks/{task_id}/logs
```

#### 6.1.3 Dashboard 聚合接口

```typescript
GET /api/tasks/dashboard
Response: {
  today_new_leads, total_leads, conversion_rate, running_tasks,
  recent_leads, task_progress, weekly_trend
}
```

#### 6.1.4 需求分析与文案生成接口

```yaml
# 需求分析
POST /api/tasks/{task_id}/analyze-needs
Body: { user_ids, max_users }
Response: { analyzed_count, results: [...] }

# 生成文案
POST /api/tasks/{task_id}/generate-content
Body: { user_ids, content_type, tone }
Response: { generated_count, contents: [...] }
```

#### 6.1.5 触达任务接口

```yaml
# 创建触达任务
POST /api/tasks/{task_id}/outreach/create
Body: { user_id, sec_uid, platform, method, content, require_confirm }
Response: { task_id, status }

# 执行触达任务
POST /api/tasks/{task_id}/outreach/{outreach_id}/execute
# 查询触达状态
GET /api/tasks/{task_id}/outreach/{outreach_id}/status
# 触达记录列表
GET /api/tasks/{task_id}/outreach/records

# 批量自动触达
POST /api/tasks/{task_id}/auto-outreach/start
Body: { user_ids, config }
# 自动触达状态
GET /api/tasks/{task_id}/auto-outreach/{job_id}/status
# 取消自动触达
POST /api/tasks/{task_id}/auto-outreach/{job_id}/cancel
```

#### 6.1.6 商业化接口

```yaml
# 客户管理
POST   /api/business/users
GET    /api/business/users
GET    /api/business/users/{user_id}
PATCH  /api/business/users/{user_id}
POST   /api/business/users/{user_id}/recharge
POST   /api/business/users/{user_id}/reset-api-key

# 线索包管理
POST   /api/business/packages
PUT    /api/business/packages/{package_id}
DELETE /api/business/packages/{package_id}
GET    /api/business/packages
POST   /api/business/packages/{package_id}/publish
POST   /api/business/packages/{package_id}/discontinue

# 购买与分配
POST   /api/business/purchase
POST   /api/business/assign
GET    /api/business/assigned-leads  # 排除 assign_type=api_pull

# 跟进记录
POST   /api/business/follow-ups
GET    /api/business/follow-ups

# API 客户端
POST   /api/business/api-clients
GET    /api/business/api-clients
PUT    /api/business/api-clients/{client_id}
POST   /api/business/api-clients/{client_id}/toggle
POST   /api/business/api-clients/{client_id}/push

# 统计
GET    /api/business/stats
```

#### 6.1.7 Cookie 管理接口

```yaml
GET    /api/cookies                # 获取所有Cookie(当前用户)
POST   /api/cookies/update         # 更新Cookie
POST   /api/cookies/parse          # 解析Cookie
GET    /api/cookies/check/{platform}
POST   /api/cookies/test/{platform}
GET    /api/cookies/pool           # Cookie池
POST   /api/cookies/pool/add
POST   /api/cookies/pool/remove
POST   /api/cookies/pool/clear
POST   /api/cookies/pool/clear-invalid
GET    /api/cookies/accounts       # 账号池状态
POST   /api/cookies/accounts/refresh
POST   /api/cookies/accounts/clear-bad-ips
```

#### 6.1.8 其他接口

```yaml
# 采集控制
POST /api/crawler/start
POST /api/crawler/stop
GET  /api/crawler/status
GET  /api/crawler/logs

# 数据文件
GET /api/data/files
GET /api/data/files/{file_path}
GET /api/data/download/{file_path}
GET /api/data/stats

# 认证
POST /api/auth/login
POST /api/auth/register
GET  /api/auth/me
POST /api/auth/change-password
GET  /api/auth/users
POST /api/auth/users
PUT  /api/auth/users/{user_id}
DELETE /api/auth/users/{user_id}

# WebSocket(仅日志/状态推送,不推送新线索)
WS /ws/logs
WS /ws/status
```

### 6.2 外部 API(供乙方CRM对接)

```yaml
# 认证:Header X-API-Key

# 线索包列表
GET /v1/external/packages

# 购买线索包(按条计费模式)
POST /v1/external/packages/purchase

# 拉取线索(双模式)
POST /v1/external/leads/pull
Body:
  - package_id: string (可选,传则按条计费模式)
  - platform: string (可选)
  - min_score: int (可选)
  - max_score: int (可选)
  - level: string (可选) high|medium|low
  - ip_location: string (可选)
  - keyword: string (可选)
  - offset: int
  - limit: int

# 状态回调
POST /v1/external/status/callback
```

> **外部 API 详细对接文档**:见 `docs/api-integration-guide.md`。

---

## 7. 数据库设计

### 7.1 业务表清单

所有业务表均包含 `owner_user_id` 字段(String(64),索引),实现用户级数据隔离。

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| customer_lead | 获客线索 | task_id, platform, user_id, lead_score, level, status, create_time |
| crawler_task | 采集任务 | task_id, platform, keywords, config, status |
| task_log | 任务日志 | task_id, level, message |
| keyword_library | 关键词库 | category, keywords, weight |
| operation_log | 操作日志 | user_id, action, target_id |
| outreach_record | 触达记录 | user_id, platform, status |
| outreach_task | 触达任务 | user_id, sec_uid, method, status |
| douyin_dm_record | 抖音私信记录 | user_id, content |
| auto_outreach_job | 自动触达任务 | task_id, status, config |
| business_user | 业务客户 | api_key, webhook_url, balance |
| lead_package | 线索包 | name, filters, price_per_lead |
| lead_assignment | 线索分配 | lead_id, package_id, business_user_id, status |
| follow_up_record | 跟进记录 | lead_id, content |
| purchase_order | 购买订单 | business_user_id, package_id, amount |
| api_client | API客户端 | api_key, webhook_url, push_mode |

### 7.2 采集源数据表

| 平台代号 | 视频表 | 评论表 |
|---------|--------|--------|
| dy | douyin_aweme | douyin_aweme_comment |
| xhs | xhs_note | xhs_note_comment |
| ks | kuaishou_video | kuaishou_video_comment |
| bili | bilibili_video | bilibili_video_comment |
| wb | weibo_note | weibo_note_comment |
| zhihu | zhihu_content | zhihu_comment |
| tieba | tieba_note | tieba_comment |

> **跨任务去重**:评论表通过 `(task_id, comment_id)` 联合保留,不同任务爬取的同一条评论分别存储。
> **评论真实时间**:所有评论表均含 `create_time` 字段(秒级时间戳),线索入库时从原始评论表回填,前端优先显示 create_time,add_ts 兜底。

### 7.3 核心表结构示例

```sql
-- 获客线索表
CREATE TABLE customer_lead (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(255) INDEX,
    platform VARCHAR(20),         -- dy/xhs/ks/bili/wb/zhihu/tieba
    data_type VARCHAR(20),        -- note/comment/video/answer
    data_id VARCHAR(255),
    user_id VARCHAR(255) INDEX,
    sec_uid VARCHAR(255) DEFAULT '',
    nickname VARCHAR(255),
    avatar TEXT,
    ip_location VARCHAR(255) DEFAULT '',
    content TEXT,
    title TEXT,
    url TEXT,
    matched_keywords TEXT,
    intent_type VARCHAR(50),
    lead_score INTEGER DEFAULT 0,
    level VARCHAR(20),            -- high/medium/low
    status VARCHAR(20) DEFAULT 'new',
    notes TEXT,
    add_ts BIGINT,
    create_time BIGINT,           -- 评论真实创建时间戳(秒)
    last_modify_ts BIGINT,
    owner_user_id VARCHAR(64) INDEX,  -- 数据隔离
    source_aweme_id VARCHAR(255) DEFAULT '',
    source_video_title TEXT DEFAULT '',
    source_video_desc TEXT DEFAULT '',
    source_video_url TEXT DEFAULT '',
    source_cover_url TEXT DEFAULT '',
    source_author_nickname VARCHAR(255) DEFAULT ''
);

CREATE INDEX idx_lead_platform ON customer_lead(platform);
CREATE INDEX idx_lead_status ON customer_lead(status);
CREATE INDEX idx_lead_score ON customer_lead(lead_score);
CREATE INDEX idx_lead_add_ts ON customer_lead(add_ts);
CREATE INDEX idx_lead_owner ON customer_lead(owner_user_id);

-- 线索分配表
CREATE TABLE lead_assignment (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER INDEX,
    package_id VARCHAR(64) DEFAULT '',
    business_user_id VARCHAR(64) INDEX,
    assign_type VARCHAR(20) DEFAULT 'purchase',  -- purchase/manual/auto/api_pull
    price_paid INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'assigned',       -- assigned/used/expired/refunded/pulled
    expire_ts BIGINT DEFAULT 0,
    assigned_ts BIGINT,
    used_ts BIGINT DEFAULT 0,
    owner_user_id VARCHAR(64) INDEX
);
```

---

## 8. 核心算法设计

### 8.1 意图识别算法(基础版)

```python
class LeadDetector:
    def detect(self, content: str, title: str = "") -> LeadMatchResult:
        full_text = f"{title} {content}".lower()

        inquiry_score = self._match_inquiry_patterns(full_text)
        product_score, matched_products = self._match_product_keywords(full_text)
        purchase_score = self._match_purchase_signals(full_text)
        sentiment_score = self._analyze_sentiment(full_text)

        total_score = (
            inquiry_score * 0.4 +
            product_score * 0.35 +
            purchase_score * 0.15 +
            sentiment_score * 0.10
        )

        intent_type = self._determine_intent_type(
            inquiry_score, product_score, purchase_score
        )

        return LeadMatchResult(
            is_lead=total_score >= self.min_score_threshold,
            matched_keywords=matched_products,
            intent_type=intent_type,
            lead_score=min(100, int(total_score))
        )
```

> **完整生产实现**(含意向精准化降级、行业信号、核心词提取)详见 §10.1。

### 8.2 去重算法

```python
class DeduplicationEngine:
    def is_duplicate(self, lead: CustomerLead) -> bool:
        content_hash = self._hash_content(lead.content)

        # 策略1: 严格去重(同用户+同内容,24h)
        # 策略2: 内容去重(同内容,7d)
        # 策略3: 相似去重(编辑距离>90%,3d)
        ...

    def _hash_content(self, content: str) -> str:
        cleaned = re.sub(r'[^\w]', '', content.lower())
        return hashlib.md5(cleaned.encode()).hexdigest()
```

### 8.3 需求分析引擎

```python
def analyze_user_need(comment: str, intent: str) -> UserNeedAnalysis:
    need_type = classify_need_type(comment)
    pain_points = extract_pain_points(comment)
    product_preferences = extract_product_preferences(comment)
    budget_sensitivity = analyze_budget_sensitivity(comment)
    urgency = analyze_urgency(comment)
    recommended_pitch = generate_pitch(need_type, pain_points, product_preferences)
    return UserNeedAnalysis(...)
```

### 8.4 前端路由与组件复用

```typescript
const routes = [
  { path: '/', component: Dashboard },         // 首页
  { path: '/tasks', component: TaskManager },  // 获客任务
  { path: '/leads', component: LeadList },     // 客户线索
  { path: '/settings', component: Settings },  // 设置
];

// 统一组件
<StatCard title="今日新线索" value={23} trend="+5" onClick={() => navigate('/leads?status=new')} />
<LeadItem lead={lead} actions={['contact', 'ignore', 'detail']} onAction={handleAction} />
<TaskCard task={task} showProgress showActions />
```

---

## 9. 使用流程

### 9.1 单用户自动化流程(MVP)

```
1. 进入"评论获客"标签页
2. 筛选"高意向"用户
3. 点击目标用户的"🤖 分析需求"按钮
4. 查看需求分析结果
5. 点击"✉️ 生成文案"按钮
6. 查看生成的个性化文案(链接已混淆)
7. 点击"🚀 触达"按钮
8. 确认文案并点击"开始执行"
9. 系统自动打开浏览器,访问用户主页,发送私信
10. 查看执行结果和截图
```

### 9.2 批量自动化流程

```
1. 进入"评论获客"标签页
2. 勾选多个高意向用户(或点击"全选")
3. 点击顶部"🤖 批量分析需求"
4. 等待分析完成
5. 点击"📤 批量生成文案"
6. 查看生成的文案列表
7. 点击"🚀 开始触达"
8. 设置执行参数(每日限额、时间段等)
9. 系统自动排队执行触达任务
10. 在"触达记录"页面查看执行进度和结果
```

### 9.3 日常操作流程

```
早上打开系统 → 看首页今日新线索数量
           → 点击处理新线索(标记/联系/忽略)
           → 查看运行中任务状态
           → 如有需要,快速创建新任务
```

### 9.4 外部 API 对接流程

```
1. 管理员在"API对接"页创建 ApiClient,获取 API Key
2. 乙方CRM通过 X-API-Key 认证调用接口
3. 包年用户:直接调 /v1/external/leads/pull 按条件拉取
4. 按条计费用户:先调 /packages/purchase,再调 /leads/pull?package_id=xxx
5. 系统通过 Webhook 推送状态变更到乙方CRM
```

---

## 10. 功能补遗(已实现但需重点说明)

本章汇总已实现但需特别说明的关键功能,涵盖意向识别增强、线索捕获增强、API 扩展、自动化触达增强、UI/UX 优化、数据安全与合规、部署运维增强七大类。

### 10.1 意图识别引擎增强

#### 10.1.1 意向精准化降级机制

针对商业场景下"高意向必须具备成交意愿"的硬约束,新增多维度意向降级逻辑,避免讨论性、回忆性、过去式购买陈述被误判为高意向。降级优先级为:**回忆 > 强意向 > 讨论/过去式购买**。

| 降级类型 | 触发条件 | 降级后 level | 降级后 score 上限 |
|---------|---------|-------------|------------------|
| 回忆性陈述 | 命中 `以前/曾经/之前/那会/小时候/以前学过/我记得` 等回忆词 | 中 | 45 |
| 讨论/过去式购买 | 命中 `我挑/我买/我选/我用/我觉得/我认为` 且无强意向信号 | 中 | 45 |
| 长文本陈述 | 长度 > 50 字 且强意向信号命中次数 ≤ 1 且含讨论/过去式/回忆标志 | 中 | 45 |
| 未命中任务关键词且无强意向 | 既无任务相关词命中也无强意向信号(同步降级 score,避免 score≥50 但 level=中 的不一致) | 中 | 45 |

**实现位置**:`api/routers/tasks.py` 中的公共函数 `_apply_intent_downgrade(base, content_lower, strong_signals, nostal_as_high)`,由 `calculate_user_value_for_task` 的各评分分支统一调用,确保 level 与 score 同步降级。

**关键信号库**:
- `NOSTALGIA_PATTERNS`(回忆词):`小时候/当年/曾经/过去/那年/以前我/那会儿/前几年/我记得` 等
- `DISCUSSION_PATTERNS`(讨论词):`压力/辛苦/逼孩子/天赋/该不该/有什么用/我觉得/评论区` + 诗词背诵标志(`浔阳江头/犹抱琵琶半遮面` 等)
- `PAST_PURCHASE_PATTERNS`(过去式购买):`买了/买来/花了/入手了/已买/我挑/老板说` 等

#### 10.1.2 核心词提取

从任务关键词中去除前导动词和无意义后缀,提取核心词,确保评论仅提及核心词时仍能命中任务相关词。

| 处理类型 | 示例 | 提取结果 |
|---------|------|---------|
| 去前导动词 | `学琵琶` → `琵琶` | 去除 `寻找/想学/要学/想买/定制/学/找/寻/买` 等 |
| 去尾部后缀 | `宋式家具的人` → `宋式家具` | 去除 `的人/的用户/的客户/信息/线索` 等 |
| 长度约束 | `找老师` → 不提取(核心词 < 3 字) | 避免把"老师/琴"等通用词当核心词误命中 |

**实现位置**:`api/routers/tasks.py` 中的 `_build_task_related_keywords()` 函数(第 5 步,LEADING_VERBS 列表)。

**基础相关词扩展**:出现任务关键词时,通过 `EXTEND_MAP` 补充相关咨询词。例如任务含"培训"时补充 `学费/课时/报名/怎么收/多少钱/哪里学/学琴/上课`。注意:不放"老师/琴/想学"等通用词(会被"我们老师""弹琴""想学唢呐"误命中),改由行业信号模板 `想学{w}` 精确生成。

#### 10.1.3 行业强意向信号动态生成

基于任务核心词动态生成行业特定信号,避免硬编码每个行业。

```
核心词"琵琶" → 生成:想学琵琶/想买琵琶/琵琶多少钱/求推荐琵琶/哪里学琵琶/求琵琶老师/求琵琶谱...
核心词"家具" → 生成:想买家具/定制家具/家具多少钱/哪里买家具/找家具师傅...
```

**实现位置**:`api/routers/tasks.py` 中的 `_build_industry_strong_signals()` + `INDUSTRY_SIGNAL_TEMPLATES` 列表(含购买类/学习类/询价类/求资源类/定制类/亲属需求类/主动咨询类模板),结果按 `(task_name, keywords, desc)` 缓存(`_INDUSTRY_SIGNALS_CACHE`,上限 200)。

**通用强意向信号优化**:移除宽泛词(`买/想买` 会误命中"买吃的/买木板"),保留明确信号(`求链接/多少钱/怎么联系/想报名/求谱/找个老师`),购买意向通过行业信号(如"想买琵琶")体现,确保语义明确。

### 10.2 线索捕获增强

#### 10.2.1 低质量内容过滤

扫描入库时过滤低质量评论,提升线索数据质量。

| 过滤类型 | 判定条件 | 处理 |
|---------|---------|------|
| 空内容 | `text` 为空或纯空白 | 跳过 |
| 纯表情 | 去除 `[xx]` 表情符号和 emoji 后有效内容 < 2 字 | 跳过 |
| 纯标点/数字 | `fullmatch([\d\s\W]+)` | 跳过 |
| 同任务重复 | 同任务内相同 `content`(不同用户发的相同简短内容) | 跳过 |

**实现位置**:`api/routers/tasks.py` 的 `scan-leads` 接口内的 `_is_low_quality()` 内部函数 + `seen_contents` 去重集合。

#### 10.2.2 跨任务评论去重

不同任务爬取的同一条评论分别保留,同任务内相同 `comment_id` 才视为重复。

**实现位置**:`store/douyin/_store_impl.py` 第 158 行,注释明确:"跨任务去重:同 comment_id + 同 task_id 才算重复(不同任务爬到同一条评论应分别保留)"。

**导入工具**:`import_jsonl_to_db.py` 第 49 行,查询条件为 `WHERE comment_id = $1 AND task_id = $2`,确保跨任务隔离。

#### 10.2.3 任务详情爬取数据展示

任务详情页"采集数据"Tab 展示该任务爬取的视频/笔记数据,按核心词匹配查询,支持重新采集和分页加载。

**实现位置**:`api/routers/tasks.py` 的 `get_task_detail` 接口,按 `task_id` + 核心词查询 `DouyinAweme`/`XhsNote` 表;前端 `TaskManager.tsx` 的 `📊 采集数据` TabPane(第 1634 行)。

### 10.3 API 功能扩展

#### 10.3.1 API 双模式设计

外部 API 支持两种拉取模式,适配不同付费方式:

| 模式 | 适用客户 | 流程 | 实现位置 |
|------|---------|------|---------|
| 直拉模式 | 包年/付费 API 用户 | 直接按条件(platform/task_id/min_score/level/ip_location/keyword)拉取 `CustomerLead` 表数据,无需购买线索包 | `external_api.py` 第 322 行 |
| 按条计费模式 | 按线索条数付费用户 | 先调 `/packages/purchase` 购买线索包,再用 `package_id` 拉取已分配的线索 | `external_api.py` 第 267 行 |

**模式判断**:传入 `package_id` 且该客户有 `status in ('assigned','used')` 的分配记录 → 按购买模式;否则走直拉模式。

**only_new 去重**:直拉模式支持 `only_new=true`,通过 `LeadAssignment.status='pulled'` 标记排除已拉取过的线索。

#### 10.3.2 pulled 状态线索(API 直拉去重标记)

`LeadAssignment.status` 新增 `pulled` 状态,用于 API 直拉模式的去重标记(区别于 `assigned`/`used`/`expired`)。

| 状态 | 含义 | assign_type |
|------|------|------------|
| assigned | 已分配(按条计费购买) | purchase |
| used | 已使用 | purchase |
| expired | 已过期 | purchase |
| pulled | 已拉取(API 直拉去重标记,price_paid=0) | api_pull |

**前端处理**:`BusinessManager.tsx` 将 `pulled` 状态显示为"已拉取"(蓝色标签),保留"已过期"(红色)给真实过期线索;`list_assigned_leads` 接口排除 `assign_type='api_pull'` 记录,确保"已分配线索"页只显示真实分配的线索。

#### 10.3.3 API 客户端管理 (ApiClient)

```python
class ApiClient:
    id: str                # 客户端ID
    name: str              # 客户端名称
    business_user_id: str  # 关联业务用户
    api_key: str           # API密钥(unique)
    api_secret: str        # 密钥密码
    webhook_url: str       # 推送地址
    callback_url: str      # 回调地址
    filters: str(JSON)     # 筛选条件:platform/min_score/ip_location等
    push_mode: str         # batch/realtime
    push_interval: int     # 批量推送间隔(秒)
    status: str            # active/disabled
    total_pushed: int      # 累计推送数
    owner_user_id: str     # 归属系统用户(数据隔离)
```

**实现位置**:`database/models.py` 的 `ApiClient` 表;`api/routers/external_api.py` 的 `authenticate_api_key` 依赖项。

### 10.4 自动化获客增强

#### 10.4.1 风控冷却期机制

检测到风控信号时自动进入冷却期,暂停发送,避免账号被封。

| 信号类型 | 冷却时长 | 实现位置 |
|---------|---------|---------|
| 重度风控(账号被封/验证码连续失败) | 30 分钟 | `outreach_automation.py:3349` |
| 中度风控(连续失败) | 10 分钟 | `outreach_automation.py:3354` |
| 轻度风控 | 5 分钟 | `outreach_automation.py:3358` |

**实现位置**:`api/services/outreach_automation.py` 的 `_enter_risk_control_cooldown(duration)` 函数(第 139 行),通过全局变量 `_risk_control_cooldown_until` 控制冷却截止时间,发送前检查 `_check_risk_control()` 跳过冷却期内的请求。

#### 10.4.2 链接混淆 10 种变体

将私信中的 URL 混淆处理,绕过抖音/小红书私信链接过滤,核心思路是将域名拆散到无法被正则匹配。

| 变体 | 示例(hropenai.cn) |
|------|-------------------|
| 1. 搜+域名+加+后缀 | `搜 hropenai 加 cn` |
| 2. 域名+中文点+后缀 | `hropenai 点 cn` |
| 3. 搜索+域名+点后缀 | `搜索 hropenai 点cn` |
| 4. 域名+emoji+后缀 | `hropenai✨cn` |
| 5. 带前缀完整混淆 | `ai点hropenai点cn` |
| 6. 域名+(点)+后缀 | `hropenai(点)cn` |
| 7. 域名+空格点空格+后缀 | `hropenai . cn` |
| 8. 换行拆分 | `hropenai\n点cn` |
| 9. 中文谐音提示 | `hropenai 点 c n` |
| 10. 搜索引擎提示 | `百度搜 hropenai` |

**实现位置**:`api/routers/tasks.py` 的 `_obfuscate_link_in_text(text, link)` 函数(第 2755 行),随机选择一种变体替换原始链接。

#### 10.4.3 CDP 模式连接 Chrome(复用浏览器实例)

自动化触达优先连接搜索任务已有的 Chrome 实例(有完整登录状态,IM 面板才能正常工作),而非启动新浏览器。

**连接流程**:
1. `_find_existing_chrome_cdp_port()` 查找已有 Chrome 的 CDP 端口
2. `httpx.get(/json/version)` 获取 WebSocket URL
3. `playwright.chromium.connect_over_cdp(ws_url, timeout=120000)` 连接
4. 复用已有 context 和 page(共享登录状态)
5. 导航到平台首页刷新登录状态 + 加载 Cookie

**实现位置**:`api/services/outreach_automation.py` 的 `_create_browser()` 函数(第 1189 行)。**注意**:小红书不能复用抖音浏览器,需独立启动(`platform == "xhs"` 时不查找已有端口)。

**浏览器实例缓存**:`_cached_browser` + `_browser_last_used` + `_BROWSER_CACHE_TTL`,验证页面存活后复用,过期或登录失效则重新启动。

#### 10.4.4 验证码旁路策略

搜索/评论接口被风控时,优先尝试旁路策略(重新导航/子页面访问/推荐页入口),最后才回退到滑块识别。

| 阶段 | 策略 | 实现位置 |
|------|------|---------|
| 1. HTTP API 重试 | 2 层冷却重试(30s → 60s)切换 Cookie+IP | `douyin/core.py` 搜索逻辑 |
| 2. 浏览器搜索 fallback | HTTP API 耗尽重试后走 `search_by_browser()` | `douyin/core.py:907` |
| 3. 验证码旁路 | 重新导航/子页面/推荐页入口(最多 3 次尝试) | `douyin/core.py:424-470` |
| 4. 推荐流 fallback | 搜索完全被拦截时走 `fetch_recommend_feed()` | `douyin/core.py:921` |
| 5. 滑块识别 | 旁路全部失败后才回退到滑块 | `douyin/core.py:470` |

**风控信号识别**:`account_pool.py` 的 `_classify_failure()` 识别 `captcha/blocked(2483)/verify_check/cookie_invalid/timeout/rate_limit/network_error` 七类失败,对应不同扣分和冷却策略。

### 10.5 UI/UX 优化

#### 10.5.1 平台名称脱敏(合规)

所有用户可见界面使用代号而非正式名称,避免产品对外售卖违规。

| 内部 key | 显示名 |
|---------|--------|
| dy | dy |
| xhs | xhs |
| ks | ks |
| bili | bili |
| wb | wb |
| zhihu | zhihu |
| tieba | tieba |

**实现位置**:`webui-new/src/types/index.ts` 的 `PLATFORM_MAP`(第 112 行),含旧 key 兼容映射(`douyin→dy`、`kuaishou→ks`、`weibo→wb`、`bilibili→bili`),仅用于显示已有数据,不在新建任务表单中暴露。

**覆盖范围**:任务选择平台卡片、任务列表平台标签、任务详情页、Cookie 管理、日志、后端错误消息。

#### 10.5.2 用户可见处去除"爬虫/爬取"字样(合规)

所有用户可见的界面文本统一使用"采集/采集数据/采集任务"表述,不暴露"爬虫/爬取"字样。

**覆盖范围**:任务管理、Cookie 管理、系统日志、设置页、错误提示等。

### 10.6 数据安全与合规

#### 10.6.1 数据隔离(owner_user_id)

所有业务表均包含 `owner_user_id` 字段,实现用户级数据隔离。

**覆盖表**:`CustomerLead`、`DouyinAweme`、`DouyinAwemeComment`、`XhsNote`、`XhsNoteComment`、`BusinessUser`、`LeadPackage`、`LeadAssignment`、`FollowUpRecord`、`PurchaseOrder`、`ApiClient`(共 11 张表,见 `database/models.py`)。

**隔离规则**:
- 新用户首次使用看到零初始数据(线索、Cookie、设置均为空)
- 存储键按 user_id 隔离:`mediacrawler_settings_${userId}`、`mediacrawler_message_templates_${userId}`
- Cookie 管理仅能管理自己的 Cookie 和 Cookie 池,无法查看或修改他人 Cookie
- `owner_user_id` 为空字符串会导致 `WHERE owner_user_id='1'` 不匹配(已回填历史空值到 `'1'`)

#### 10.6.2 线索回访跟进记录(FollowUpRecord)

```python
class FollowUpRecord:
    lead_id: int           # 线索ID
    lead_assignment_id: int # 分配记录ID
    business_user_id: str  # 跟进人ID(销售)
    action_type: str       # 跟进方式: call/message/visit/wechat
    action_ts: int         # 跟进时间戳
    result: str            # pending/contacted/interested/not_interested/converted/failed
    notes: str             # 跟进备注
    next_follow_ts: int    # 下次跟进时间戳
    owner_user_id: str     # 归属系统用户(数据隔离)
```

**实现位置**:`database/models.py` 的 `FollowUpRecord` 表(第 697 行)。

### 10.7 部署与运维增强

#### 10.7.1 Xvfb 虚拟显示支持

无头服务器环境下自动启动 Xvfb 虚拟显示器,使 Chrome headed 模式可用(反检测效果优于 headless)。

**实现位置**:`api/services/outreach_automation.py`:
- `_ensure_xvfb()`(第 904 行):先清理无效 Xvfb 和 Chrome 孤儿进程,再查找已有实例复用,最后启动新实例(`Xvfb :{display_num} -screen 0 1920x1080x24`)
- `_cleanup_stale_xvfb()`(第 783 行):检查每个 Xvfb 进程对应的 DISPLAY 是否有效,清理无效实例和对应的孤儿 Chrome 进程

**CDP 模式下自动启动 Xvfb**:在 `_create_browser()` 中调用 `_ensure_xvfb()`,使 headed 模式在无显示器服务器上可用。

#### 10.7.2 账号池/IP 轮换(AccountPool)

多账号 + 多 IP 轮换,单次请求失败自动切换 Cookie+IP 组合,提升采集稳定性。

| 维度 | 说明 |
|------|------|
| 账号健康分 | 100 分制,成功 +5,失败 -5~-50(按失败类型) |
| 自动冷却 | 健康分 < 30 或连续失败 3 次,冷却 10-30 分钟后自动恢复 |
| Bad IP 标记 | 被封 IP 自动标记,10 分钟后自动恢复;所有 IP 都坏时触发全量清除重试 |
| 失败切换 | blocked(2483)/verify_check/captcha/连续 3 次超时 → 立即切换 Cookie+IP |
| IP 轮换 | 支持多网卡(eth0/eth1/eth2...),按健康分和最久未使用排序选账号 |

**实现位置**:`api/services/account_pool.py` 的 `AccountPool` 类(第 201 行),`_classify_failure()` 识别 7 类失败类型,`FAIL_PENALTY_MAP` 定义扣分和冷却策略。

**Cookie 池配置**:`.env` 中 `DY_COOKIES_POOL` 使用 `|||` 分隔多个 Cookie,未配置时回退到 `DY_COOKIES`。

#### 10.7.3 定时任务调度器(daily/weekly)

支持 daily/weekly 自动执行采集任务,无需手动触发。

| 维度 | 说明 |
|------|------|
| 调度类型 | `once`(立即执行)/ `daily`(每日指定时间)/ `weekly`(每周指定星期几+时间) |
| 调度时间 | `schedule_time` 字段(HH:MM 格式),默认 09:00 |
| 周几执行 | `schedule_weekday` 字段(1-7),weekly 类型生效 |
| 防重复触发 | `next_scheduled_ts` 字段,执行后自动计算下次时间 |
| 调度循环 | 每 60 秒检查一次到期任务 |
| 触发方式 | 内部 HTTP 调用 `/api/tasks/{task_id}/start`,复用完整逻辑 |

**实现位置**:
- `api/services/task_scheduler.py`(调度器主循环 + 下次时间计算)
- `api/main.py` 启动时通过 `start_scheduler()` 拉起后台任务
- `database/models.py` 的 `CrawlerTaskModel` 新增 4 个调度字段

#### 10.7.4 邮件/站内消息通知

扩展原 Webhook 通知,新增邮件和站内消息两种渠道。

| 渠道 | 实现 | 适用场景 |
|------|------|---------|
| Webhook | `business.py` 的 `push_leads_to_webhook` | 线索推送到外部系统 |
| 邮件 | `notification_service.py` 的 `send_email`(SMTP) | 严重告警/任务完成通知 |
| 站内消息 | `notification_service.py` 的 `send_in_app_message` | 系统通知/线索提醒 |

**邮件配置**:环境变量 `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_USE_SSL`。

**站内消息 API**:
- `GET /api/notifications` - 拉取消息列表(支持 unread_only 筛选)
- `POST /api/notifications/{id}/read` - 标记单条已读
- `POST /api/notifications/read-all` - 全部标记已读
- `POST /api/notifications/webhook` - 接收 Alertmanager 推送

**实现位置**:`api/services/notification_service.py` + `api/routers/notifications.py` + `database/models.py` 的 `Notification` 表。

#### 10.7.5 Docker 部署配置

完整的容器化部署方案,支持一键启动全部服务。

| 文件 | 作用 |
|------|------|
| `Dockerfile` | 后端镜像(多阶段构建,内置 Xvfb + Playwright Chromium + 中文字体) |
| `Dockerfile.webui` | 前端镜像(node 构建 + nginx 运行) |
| `docker-compose.yml` | 编排:backend + webui + postgres + redis + prometheus + grafana + alertmanager + node-exporter |
| `docker/nginx.conf` | 前端 nginx 配置(SPA 路由 + API 反代 + WebSocket + 静态资源缓存 + gzip) |

**启动命令**:`docker-compose up -d`

**健康检查**:backend 容器内置 `/health` 端点健康检查,start_period 60s。

#### 10.7.6 监控告警(Prometheus + Grafana + Alertmanager)

完整的运维监控体系,覆盖主机资源、服务可用性、业务指标三个层面。

| 组件 | 作用 | 端口 |
|------|------|------|
| Prometheus | 指标采集与存储(30 天保留) | 9090 |
| Grafana | 可视化看板(默认账号 admin/admin) | 3000 |
| Alertmanager | 告警分发(邮件 + Webhook) | 9093 |
| node-exporter | 主机指标采集(CPU/内存/磁盘) | 9100 |

**告警规则**(`docker/alert_rules.yml`):
- 主机告警:CPU>80%、内存>85%、磁盘<10%
- 服务可用性:Backend/PostgreSQL/Redis 离线告警
- 业务告警:API 5xx 错误率>10%、任务卡死>1 小时、账号池可用数为 0

**后端指标端点**:`GET /metrics`(通过 `prometheus_client` 暴露),定义指标:
- `mediacrawler_leads_total`(线索总数,按平台/等级)
- `mediacrawler_task_running`(运行中任务数)
- `mediacrawler_task_duration_seconds`(任务执行耗时直方图)
- `mediacrawler_account_pool_available`(账号池可用数,按平台)
- `http_requests_total`(HTTP 请求总数,按 method/endpoint/status)

**告警抑制**:服务离线时自动抑制该服务下的其他告警,避免告警风暴。

#### 10.7.7 需求分析/文案结果/产品库持久化

新增 3 张表,补齐 v4 PRD §12 要求的持久化能力,支持历史回看和复用。

| 表名 | 作用 | 关键字段 |
|------|------|---------|
| `user_need_analysis` | 用户需求分析结果持久化 | lead_id, need_type, pain_points, pitch |
| `ad_content` | 生成的广告文案结果持久化 | lead_id, direct_message, comment_reply, used |
| `product_info` | 产品库(替代任务级 promo_config) | name, product_desc, promo_link, price_info |

**数据隔离**:三张表均含 `owner_user_id` 字段,与现有 11 张业务表一致。

**实现位置**:`database/models.py` 的 `UserNeedAnalysis`/`AdContent`/`ProductInfo` 三个类。

#### 10.7.8 意向规则可配置(替代硬编码)

新增 `intent_rule` 和 `keyword_category` 两张表,支持运行时增删改查意向识别规则,无需重启服务。

| 能力 | 说明 |
|------|------|
| 规则类型 | strong_intent(通用强意向)/ industry_template(行业模板)/ nostalgia(回忆降级)/ discussion(讨论降级)/ past_purchase(过去式降级) |
| 自动初始化 | 首次访问 `/api/config/intent-rules` 时自动从 tasks.py 硬编码规则 seed 到数据库 |
| 动作配置 | upgrade(升级为高意向)/ downgrade(降级为低/中) + score_delta + score_cap |
| 启用/禁用 | 单条规则可快速开关,无需删除 |
| 关键词库 | 按分类组织,支持权重倍数 |

**API 路由**(`api/routers/config.py`):
- `GET /api/config/intent-rules` - 列表(支持按类型/启用状态筛选)
- `POST /api/config/intent-rules` - 新建
- `PUT /api/config/intent-rules/{id}` - 更新
- `DELETE /api/config/intent-rules/{id}` - 删除
- `POST /api/config/intent-rules/seed` - 手动触发初始化
- `GET/POST/PUT/DELETE /api/config/keyword-categories` - 关键词分类 CRUD

**前端界面**:`Settings.tsx` 新增"意向规则"Tab,支持完整 CRUD(规则类型下拉、模式输入、动作/等级配置、启用开关、批量管理)。

#### 10.7.9 线索看板拖拽变更状态

消除 PRD v2 §10.2 历史造假项,实现真正的拖拽变更线索状态。

| 维度 | 说明 |
|------|------|
| 视图切换 | LeadList 顶部新增"列表/看板"切换按钮,看板模式按状态分列展示 |
| 列布局 | 按 STATUS_MAP 7 个状态(new/pending/contacted/qualified/converted/failed/ignored)横向分列 |
| 拖拽实现 | HTML5 原生 `draggable` + `onDragStart/onDragOver/onDrop`,无需引入第三方依赖 |
| 状态变更 | 拖拽到目标列后调用 `updateLeadStatus` API 更新数据库,自动刷新列表 |
| 卡片信息 | 显示昵称/分数/意向类型/平台/评论摘要,双击打开详情 |
| 数据量 | 看板模式自动拉取 200 条(覆盖大多数场景),列表模式保持 50 条/页 |
| 防重复 | 拖拽到当前所在列不会触发更新 |

**实现位置**:`webui-new/src/pages/LeadList.tsx` 的 `viewMode` state + `boardData` 分组 + Kanban 渲染区块。

#### 10.7.10 WebSocket 新线索推送

采集流程写入线索后,实时推送到对应用户的前端,无需手动刷新。

| 维度 | 说明 |
|------|------|
| 新端点 | `GET /api/ws/leads`(WebSocket,query 参数携带 token 鉴权) |
| 用户隔离 | 连接时解析 token 绑定 user_id,推送时按 `owner_user_id` 精准匹配 |
| 触发时机 | `tasks.py` 批量插入线索后调用 `notify_new_leads`(不阻塞主流程) |
| 推送内容 | `{type, task_id, platform, count, high_count, medium_count, low_count}` |
| 前端订阅 | LeadList 挂载时建立连接,收到 `new_lead` 事件后 toast 提示 + 自动刷新列表和统计 |
| 断线重连 | 前端 onclose 后 5 秒自动重连 |
| 心跳保活 | 30 秒超时收发 ping/pong |

**实现位置**:
- 后端:`api/routers/websocket.py` 的 `ConnectionManager.broadcast_new_lead` + `/ws/leads` 端点 + `notify_new_leads` 函数
- 触发点:`api/routers/tasks.py` 的 `flush_batch` 后(约 2370 行)
- 前端:`webui-new/src/pages/LeadList.tsx` 的 WebSocket useEffect

#### 10.7.11 后端自动化测试体系

建立 pytest + httpx + 临时 SQLite 的 API 测试基础设施,覆盖核心业务路径。

| 测试文件 | 覆盖范围 | 用例数 |
|---------|---------|--------|
| `tests/test_intent_downgrade.py` | §10.1.1 意向精准化降级(回忆/讨论/过去式/长篇陈述) | 10 |
| `tests/test_config_api.py` | §10.7.8 评分规则 CRUD + 首次 seed + 筛选 | 8 |
| `tests/test_leads_api.py` | §10.2 线索列表 11 维度筛选 + 状态变更 + 导出 | 19 |
| `tests/test_leads_import.py` | §10.7 第三批 批量导入 CSV/Excel + 边界 | 8 |
| `tests/test_analytics_api.py` | Analytics 页面 趋势/平台/漏斗 | 7 |

**基础设施**(`tests/conftest.py`):
- `test_engine` fixture:会话级临时 SQLite 文件库,自动建表(含动态注册的 account_pool)
- `app_client` fixture:httpx AsyncClient + ASGITransport,patch `get_async_engine` 指向临时库,override `get_current_user` 返回测试管理员,每测试前清表隔离
- `seed_lead` fixture:插入测试线索,返回 id
- `pyproject.toml` 配置 `testpaths = ["tests"]`、`pythonpath = ["."]`

**运行结果**:`pytest tests/ -q` → 52 passed(新增)+ 49 passed(原有)= 101 passed,1 failed(预先存在的 `test_store_factory` 环境问题,与本次无关)。

**环境注意事项**:
- 当前环境 sqlite3 C 扩展对 in-memory `:memory:` 的 deserialize 符号支持异常,故 test_engine 用文件库
- `python-multipart` 需安装(导入 UploadFile 端点时 FastAPI 校验)

### 10.8 搜索数据净化与关键词强相关采集(v6.5)

针对任务采集到的视频/评论与关键词无关的问题(如"学琵琶"任务采集到"蛋仔派对""世界杯"等推荐内容),新增搜索数据净化机制,确保采集数据与任务关键词强相关。

#### 10.8.1 搜索 API 数据隔离

| 问题 | 根因 | 修复 |
|------|------|------|
| 搜索结果混入推荐 feed 数据 | `search_by_browser` 路由拦截匹配 `feed`/`item`/`module` 等宽泛 URL,slider 验证后页面跳到热搜页时收集了推荐数据 | 路由拦截只匹配搜索 API(`/aweme/` + `search`),slider 验证后清空已收集的数据 |

**实现位置**:`media_platform/douyin/core.py` 的 `search_by_browser` 方法,过滤 `search_data_list` 仅保留搜索 API 响应。

#### 10.8.2 搜索失败不再 fallback 到推荐 feed

| 问题 | 根因 | 修复 |
|------|------|------|
| 搜索 API 返回空结果时,爬虫 fallback 到 `fetch_recommend_feed` 获取推荐视频,导致采集到大量无关视频 | `search` 方法在 `search_by_browser` 返回空时调用 `fetch_recommend_feed` | 搜索失败时直接跳过该关键词,不再 fallback 到推荐 feed |

**实现位置**:`media_platform/douyin/core.py` 的 `search` 方法,`else` 分支改为 `page_aweme_list = []` 并打印 warning 日志。

#### 10.8.3 评论线索检测补充视频/笔记标题上下文

| 问题 | 根因 | 修复 |
|------|------|------|
| 评论内容不含"琵琶"但视频标题包含"琵琶"时,线索检测漏检 | 评论存储时 `title_field=""`,线索检测器无法获取视频标题上下文 | 评论存储时查询关联视频/笔记标题,通过 `extra_title` 参数传入 `CustomerLeadDetector.detect` |

**实现位置**:
- `store/douyin/_store_impl.py` 评论存储时查询 `DouyinAweme.title`
- `store/xhs/_store_impl.py` 评论存储时查询 `XhsNote.title`
- `store/customer_lead.py` 的 `detect` 方法新增 `extra_title` 参数,纳入相关性判断

#### 10.8.4 线索检测关键词相关性强制校验

| 问题 | 根因 | 修复 |
|------|------|------|
| 高意向评论与任务关键词完全无关(如 AI 工具、足球等评论被标记为琵琶任务线索) | `CustomerLeadDetector.detect` 仅检查咨询意图词,未校验与任务关键词的相关性 | `detect` 方法新增 `task_keywords` 参数,要求内容(或视频标题)必须命中任务关键词核心词才判定为线索 |

**核心词提取**:`CustomerLeadDetector._extract_core_terms` 方法,按空格/顿号分割关键词,去除前导动词(`学/找/买/想学` 等)和尾部后缀(`的人/信息/线索` 等),过滤通用词(`老师/琴/想学` 等)。

**实现位置**:`store/customer_lead.py` 的 `detect` 和 `_extract_core_terms` 方法。

#### 10.8.5 任务采集量上限统一调整

| 问题 | 根因 | 修复 |
|------|------|------|
| 任务 `max_notes=100` 导致每个关键词仅采集约 20 条视频,无法覆盖足够评论数据 | 历史任务创建时默认 `max_notes=100` | 所有任务 `max_notes` 统一更新为 50000 |

**实现位置**:`crawler_task` 表的 `max_notes` 字段,通过 API/DB 更新。

---

### 10.9 商业化套餐与按量计费(v6.6)

#### 10.9.1 设计目标

将获客系统从"内部工具"升级为"可对外服务的商业化产品",通过套餐订阅 + 按量计费混合模式,确保:
- **注册即可用**:免费用户也能跑通完整获客流程,体验核心价值
- **付费提效**:升级套餐解锁更高采集量、更全数据时效、更多并行任务
- **关键数据保障**:每个套餐都保证最低评论采集数,确保线索检测有足够输入
- **资源可控**:通过配额限制防止单用户过度占用爬虫资源

#### 10.9.2 套餐配置

| 套餐 | 价格(月/年) | 最大任务数 | 单任务视频上限 | 数据时效 | 单任务评论上限 | 超额单价(视频/评论/线索) |
|------|------------|-----------|---------------|---------|---------------|----------------------|
| free 免费版 | ¥0/¥0 | 3 | 1,000 | 一周内 | 500 | ¥0.01/¥0.001/¥0.05 |
| basic 基础版 | ¥99/¥990 | 10 | 10,000 | 一月内 | 2,000 | ¥0.01/¥0.001/¥0.05 |
| pro 专业版 | ¥399/¥3990 | 50 | 50,000 | 半年内 | 5,000 | ¥0.01/¥0.001/¥0.05 |
| enterprise 企业版 | ¥1999/¥19990 | 不限 | 不限 | 不限 | 不限 | ¥0.01/¥0.001/¥0.05 |

> 管理员账号自动享有 enterprise 套餐,不受任何配额限制。

#### 10.9.3 数据模型

`sys_user` 表新增字段:

| 字段 | 类型 | 说明 |
|------|------|------|
| `plan_type` | VARCHAR(20) | 套餐类型: free / basic / pro / enterprise |
| `plan_expires_ts` | BIGINT | 套餐过期时间戳(0=永久,如免费版) |
| `plan_started_ts` | BIGINT | 套餐开始时间戳 |
| `balance` | BIGINT | 账户余额(分,用于超额按量计费) |
| `total_spent` | BIGINT | 累计消费(分) |
| `usage_period_start_ts` | BIGINT | 当前计费周期开始时间戳 |
| `usage_notes_count` | INTEGER | 当前周期已采集视频/笔记数 |
| `usage_comments_count` | INTEGER | 当前周期已采集评论数 |
| `usage_leads_count` | INTEGER | 当前周期已捕获线索数 |

#### 10.9.4 配额校验链路

**任务创建时**(`POST /api/tasks`):
1. 校验套餐是否在有效期(`is_plan_active`)
2. 校验当前任务数是否超限(`check_task_quota`)
3. 根据 `max_notes_per_task` 自动调低 `max_notes`(`clamp_max_notes`)
4. 根据 `max_publish_time_type` 自动收紧 `publish_time_type`(`clamp_publish_time_type`)

**任务启动时**(`POST /api/tasks/{id}/start`):
1. 再次校验套餐有效性(防止套餐过期后启动旧任务)
2. 根据当前套餐重新 clamp `max_notes` 和 `publish_time_type`(防止套餐降级后越权)
3. 根据 `max_comments_per_task` 设置单视频评论采集上限,保障关键数据

#### 10.9.5 API 接口

| 接口 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/api/plans` | GET | 公开 | 套餐列表(供定价页展示) |
| `/api/plans/me` | GET | 用户 | 当前用户套餐状态与用量 |
| `/api/plans/upgrade` | POST | 用户 | 套餐升级(从余额扣费) |
| `/api/plans/recharge` | POST | 用户 | 余额充值(元转分) |
| `/api/plans/users` | GET | 管理员 | 所有用户套餐概览 |
| `/api/plans/users/{id}` | PUT | 管理员 | 手动调整用户套餐/余额/有效期 |

#### 10.9.6 计费流程

1. 用户注册即享免费版(永久有效,无需付费)
2. 用户充值余额(元 → 分,1 元 = 100 分)
3. 用户选择套餐并升级:
   - 月订阅:扣费 `price_monthly`,有效期 30 天
   - 年订阅:扣费 `price_yearly`,有效期 365 天
4. 套餐到期后自动降级为 free
5. 超额按量计费(待实现):采集量超出套餐配额时,从余额扣费

#### 10.9.7 关键数据保障

为确保注册用户能"爬到关键的数据"(核心商业承诺):

| 保障项 | 实现方式 |
|--------|---------|
| 视频数保障 | 每个套餐都有 `max_notes_per_task` 下限(free=1000),确保有足够视频输入 |
| 评论数保障 | 每个套餐都有 `max_comments_per_task`(free=500),确保评论线索检测有数据 |
| 数据时效保障 | `max_publish_time_type` 限制采集时间范围,确保数据新鲜度 |
| 线索检测保障 | 视频和评论存储时关联任务关键词,确保线索检测准确性(§10.8.3/§10.8.4) |

---

## 11. 未实现与已知限制

本章汇总当前版本尚未实现或存在已知限制的功能,供产品验收和后续迭代参考。

### 11.1 未实现功能清单

> **更新说明**:2026-06-30 累计已修复 15 项历史遗留问题。当前所有 PRD v2 验收项均已达标。

| 功能 | 说明 | 影响 |
|------|------|------|
| (无) | 第三批全部完成,详见下方修复清单 | - |

> **已修复(2026-06-30 第一批)**: xhs 任务 Tab 屏蔽 ✅、定时任务 daily/weekly 调度器 ✅、邮件/站内消息通知 ✅、评分规则前端可配置 CRUD ✅、Docker 部署配置 ✅、Prometheus/Grafana 监控告警 ✅、3 张缺失表(user_need_analysis/ad_content/product_info) ✅、合规残留清除 ✅
>
> **已修复(2026-06-30 第二批)**: 线索看板拖拽变更状态 ✅(Kanban 视图 + HTML5 拖拽)、WebSocket 新线索推送 ✅(/ws/leads 按用户隔离)、Analytics 页面挂载路由 ✅、线索多维度检索补全 ✅(时间/分数/意向类型)
>
> **已修复(2026-06-30 第三批)**: 首页性能优化 ✅(LeadList 虚拟滚动 + Dashboard 后台暂停轮询)、批量导入线索 ✅(/leads/import-file CSV/Excel)、首次使用引导 ✅(OnboardingTour 5 步引导)

### 11.2 验收标准对照

> **历史说明**:PRD v2 §10.2 验收标准中"线索看板支持拖拽变更状态"曾标记为已完成但实际未实现(历史造假项)。该问题已于 2026-06-30 第二批修复(LeadList.tsx 看板视图 + HTML5 拖拽)。本节对齐当前真实实现状态。

| 验收项 | PRD 标记 | 实际状态 | 说明 |
|--------|---------|---------|------|
| 线索看板拖拽变更状态 | 已完成 | ✅ 已实现 | LeadList.tsx 看板视图(HTML5 拖拽,2026-06-30 修复,见 §10.7.9) |
| 线索看板 Tab 切换 | 已完成 | ✅ 已实现 | BusinessManager.tsx |
| WebSocket 日志推送 | 已完成 | ✅ 已实现 | 仅日志/状态 |
| WebSocket 新线索推送 | 已完成 | ✅ 已实现 | /ws/leads 按用户隔离推送(2026-06-30 修复,见 §10.7.10) |
| 定时任务 once 类型 | 已完成 | ✅ 已实现 | 仅 once |
| 定时任务 daily/weekly | 已完成 | ✅ 已实现 | task_scheduler.py(2026-06-30 修复,见 §10.7.3) |
| Webhook 通知 | 已完成 | ✅ 已实现 | business.py |
| 邮件/站内消息通知 | 已完成 | ✅ 已实现 | notification_service.py + /api/notifications(2026-06-30 修复,见 §10.7.4) |
| 平台名称脱敏 | 已完成 | ✅ 已实现 | PLATFORM_MAP(§10.5.1) |
| "爬虫/爬取"字样清除 | 已完成 | ✅ 已实现 | 2026-06-30 全量清除(CookieManager/Settings/SystemLogs) |
| xhs 任务 Tab 屏蔽 | 已完成 | ✅ 已实现 | TaskManager.tsx platform!=='xhs'(2026-06-30 修复,见 §10.5.3) |
| 数据隔离 owner_user_id | 已完成 | ✅ 已实现 | 11 张表覆盖(§10.6.1) |
| API 双模式 | 已完成 | ✅ 已实现 | 直拉 + 按条计费(§10.3.1) |
| 意向精准化降级 | 已完成 | ✅ 已实现 | `_apply_intent_downgrade`(§10.1.1) |
| 评分规则前端可配置 | 未要求 | ✅ 已实现 | /api/config/intent-rules + Settings.tsx(2026-06-30 新增,见 §10.1.4) |
| Docker 部署配置 | 已要求 | ✅ 已实现 | Dockerfile + docker-compose.yml(2026-06-30 新增,见 §10.7.5) |
| 监控告警 | 已要求 | ✅ 已实现 | Prometheus + Grafana + Alertmanager(2026-06-30 新增,见 §10.7.6) |
| 需求分析持久化 | 已要求 | ✅ 已实现 | user_need_analysis 表(2026-06-30 新增,见 §10.7.7) |
| 文案结果持久化 | 已要求 | ✅ 已实现 | ad_content 表(2026-06-30 新增,见 §10.7.7) |
| 产品库 | 已要求 | ✅ 已实现 | product_info 表(2026-06-30 新增,见 §10.7.7) |
| 数据分析页面 | 已要求 | ✅ 已实现 | Analytics.tsx 挂载路由(2026-06-30 修复,转化漏斗/平台对比) |
| 线索多维度检索 | 已要求 | ✅ 已实现 | 11 维度筛选(2026-06-30 补全:时间/分数/意向类型) |
| 首页性能优化 | 已要求 | ✅ 已实现 | LeadList 虚拟滚动 + Dashboard 后台暂停轮询(2026-06-30 第三批) |
| 批量导入线索 | 已要求 | ✅ 已实现 | /leads/import-file 支持 CSV/Excel(2026-06-30 第三批) |
| 首次使用引导 | 已要求 | ✅ 已实现 | OnboardingTour 5 步引导(2026-06-30 第三批) |

---

## 12. 文档版本历史

| 版本 | 日期 | 变更说明 |
|------|------|---------|
| v1.0 | 2026-06 | 基础版:线索识别、捕获、管理、统计 |
| v2.0 | 2026-06 | 零学习成本版:3步创建任务向导、卡片式任务列表、首页 Dashboard 重构 |
| v4.0 | 2026-06 | 自动化获客合并版:需求分析引擎、文案生成、自动化触达、防封策略 |
| v6.0 | 2026-06-30 | 整合重构版:合并 v1/v2/v4,去重统一编号,新增 §10 功能补遗(23 项已实现功能)和 §11 未实现与已知限制 |
| v6.1 | 2026-06-30 | 8 项历史遗留修复:① xhs 任务 Tab 屏蔽 ② 定时任务 daily/weekly 调度器(§10.7.3) ③ 邮件/站内消息通知(§10.7.4) ④ 评分规则前端可配置 CRUD(§10.7.8) ⑤ Docker 部署配置(§10.7.5) ⑥ Prometheus/Grafana 监控告警(§10.7.6) ⑦ 3 张缺失表 user_need_analysis/ad_content/product_info(§10.7.7) ⑧ 合规残留清除。同步更新 §11 验收对照表,标注历史造假项"线索看板拖拽"未修复。 |
| v6.2 | 2026-06-30 | 第二批 4 项修复:① 线索看板拖拽变更状态(§10.7.9,消除历史造假项) ② WebSocket 新线索推送(§10.7.10,按用户隔离) ③ Analytics 页面挂载路由(转化漏斗/平台对比可访问) ④ 线索多维度检索补全(时间范围/分数区间/意向类型)。§11 验收对照表全部达标。 |
| v6.3 | 2026-06-30 | 第三批 3 项修复:① 首页性能优化(LeadList 虚拟滚动 + Dashboard 后台暂停轮询) ② 批量导入线索(/leads/import-file CSV/Excel) ③ 首次使用引导(OnboardingTour 5 步,Antd Tour 原生实现)。至此 PRD v2 §11 所有未实现项清零。 |
| v6.4 | 2026-06-30 | 第四批 A 后端自动化测试体系(§10.7.11):建立 pytest + httpx + 临时 SQLite 基础设施,新增 52 个测试用例,覆盖意向降级、评分规则 CRUD、线索 11 维度筛选、状态变更、导出、批量导入、数据分析 API。原有测试无回归。 |
| v6.5 | 2026-07-15 | 搜索数据净化与关键词强相关采集(§10.8):① 搜索 API 数据隔离,过滤推荐 feed 污染 ② 搜索失败不再 fallback 到推荐 feed ③ 评论线索检测补充视频/笔记标题上下文(`extra_title`) ④ 线索检测关键词相关性强制校验(`task_keywords` + 核心词提取) ⑤ 任务 `max_notes` 统一调整为 50000。同步清理 38 个无效测试脚本和 14 个临时配置备份文件。 |
| v6.6 | 2026-07-15 | 商业化套餐与按量计费(§10.9):① `sys_user` 表新增 9 个套餐/计费/用量字段 ② 定义 free/basic/pro/enterprise 四档套餐,管理员不限 ③ 任务创建和启动时双重配额校验(`max_tasks`/`max_notes`/`publish_time_type`/`max_comments`) ④ 新增 `/api/plans` 系列 API(套餐查询/升级/充值/管理员管理) ⑤ 关键数据保障:每个套餐都保证最低评论采集数,确保注册用户能爬到关键数据。 |