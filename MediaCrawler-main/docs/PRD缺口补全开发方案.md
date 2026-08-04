# C端平台运营矩阵起号引流系统 — PRD 缺口补全开发方案

> **文档版本**：v1.0
> **编写日期**：2026-07-26
> **基准文档**：`C端平台运营矩阵起号引流系统产品需求文档（PRD）.docx`
> **适用范围**：基于 PRD × GEO-main × MediaCrawler 三方对比分析得出的缺口清单，制定分阶段补全方案
> **关键前提**：GEO-main 业务模块已 100% 迁移完成，本方案所有任务均为**新建实现**

---

## 一、方案总览

### 1.1 目标

在 MediaCrawler 现有 16 个业务子目录（51 个 .py 文件）基础上，补齐 PRD 6 大模块的缺口能力，使系统完整覆盖 PRD 5.1-5.6 全流程，达到 PRD 验收标准。

### 1.2 范围

| 缺口类别 | 缺口数量 | 优先级分布 |
|---|---|---|
| 热点搜集（5.1） | 7 项 | P0×4 + P1×3 |
| 视频生成（5.2） | 6 项 | P0×4 + P4×1 + 优化×1 |
| 多平台分发（5.3） | 4 项 | P0×1 + P1×3 |
| 互动运营（5.4） | 6 项 | P0×2 + P1×4 |
| 后台数据统计（5.5） | 4 项 | P1×2 + P2×2 |
| 风控合规（5.6） | 5 项 | P1×2 + P2×3 |
| 横向能力 | 4 项 | P0×1 + P1×1 + P3×1 + P4×1 |
| **合计** | **36 项** | — |

### 1.3 总体策略

1. **优先补齐国内 P0 平台**（快手、视频号、今日头条），再扩展海外平台
2. **视频生成以"解说视频"为基础**（用户已确认可接受），重点补齐营销植入与参数配置
3. **预警系统统一架构**：突发热点 + 账号异常 + 数据异常复用同一预警中心
4. **机器人账号池与发布账号池分离**：独立数据表 + 独立 cookie 池管理
5. **配置化优先**：所有可变参数（频次、阈值、视频参数、互动量）通过配置中心暴露
6. **每个阶段产出可验收的端到端能力**，避免半成品堆积

### 1.4 总工期估算

| 阶段 | 工期 | 累计 |
|---|---|---|
| 阶段一：P0 核心能力补齐 | 6 周 | 6 周 |
| 阶段二：P1 海外平台 + 合规增强 | 7 周 | 13 周 |
| 阶段三：P2 优化项 | 5 周 | 18 周 |
| 阶段四：P3/P4 高级功能 | 4 周 | 22 周 |

---

## 二、阶段一：P0 核心能力补齐（6 周）

### 2.1 阶段目标

补齐 PRD P0 必做项，使系统具备"国内 P0 平台全链路自动化"能力：热点搜集 → 视频生成 → 多平台分发 → 互动运营 → 数据统计 → 风控预警。

### 2.2 任务拆解

#### 任务 1.1：快手发布器 + 互动器（1.5 周）

**目标**：补齐 PRD 5.3/5.4 国内 P0 平台缺口。

**实施步骤**：

1. **快手发布器** `api/services/publisher/platforms/kuaishou_publisher.py`
   - 继承 `BasePublisher`
   - 实现 `_do_publish`：图文笔记发布（参考 `douyin_publisher.py` 架构）
   - 关键点：快手创作者中心登录态校验、上传 API 调用、话题标签适配
   - 在 `platforms/__init__.py` 注册 `KuaishouPublisher`
   - 在 `publisher_factory.py` 通过 `@PublisherFactory.register("ks")` 注册

2. **快手互动器** `api/services/interactor/platforms/kuaishou_interactor.py`
   - 继承 `BaseInteractor`
   - 实现 `_do_like` / `_do_comment` / `_do_reply` / `_do_follow`
   - 关键点：快手 GraphQL API 调用、风控信号识别
   - 在 `interactor_factory.py` 通过 `@InteractorFactory.register("ks")` 注册

3. **平台元数据** 在 `publisher/platform_configs.py` 中新增 `kuaishou` 配置
   - 标题长度、内容长度、敏感词库、视频尺寸、话题标签规则

4. **MediaCrawler 原生快手爬虫复用**
   - 复用 `media_platform/kuaishou/` 下的登录、反检测逻辑
   - 通过 `stealth_browser.py` 共享浏览器启动参数

**验收标准**：
- ✅ 可通过 `/api/publish` 接口将图文内容发布到快手
- ✅ 可通过 `/api/interact` 接口对快手视频执行点赞/评论/回复/关注
- ✅ 失败重试 3 次机制生效
- ✅ 发布/互动记录入库

---

#### 任务 1.2：视频生成能力补全（1.5 周）

**目标**：在现有"解说视频"基础上，补齐营销植入、参数配置、批量生成、P4 分镜链路。

**实施步骤**：

1. **视频参数可配置中心** `api/services/ai/video_generation_config.py`（新建）
   - 数据类：`VideoGenConfig`
     - `duration_seconds: int = 15`（范围 15-60）
     - `resolution: str = "720p"`（720p/1080p）
     - `aspect_ratio: str = "9:16"`（9:16/16:9/1:1）
     - `visual_style: str = "modern"`（modern/minimal/cinematic/cartoon）
     - `voice_timbre: str = "female_warm"`（female_warm/male_deep/neutral/young）
     - `subtitle_style: str = "white_bold_black_outline"`
     - `bgm_mood: str = "upbeat"`（upbeat/calm/inspiring/tense）
   - 通过 `/api/ai/video-config` 暴露 CRUD 接口
   - 配置持久化到 `video_generation_configs` 表（含 `owner_user_id` 隔离）

2. **营销信息精细化植入** `api/services/marketing/copy_inserter.py`（增强）
   - 扩展 `CopyInserter` 支持植入位置/时长/形式配置：
     - `position: enum`（top_left/top_right/bottom_left/bottom_right/center/watermark）
     - `duration_seconds: int`（贴片时长，0=全程）
     - `form: enum`（logo/qrcode/text_banner/lower_third/end_card）
   - 与 `video_processor.py` 联动：FFmpeg 滤镜实现位置/时长控制
   - 新增 API：`POST /api/marketing/insert` 接受配置参数

3. **批量生成差异化视频** `api/services/ai/batch_video_generator.py`（新建）
   - 类：`BatchVideoGenerator`
   - 输入：多个热点 ID + 多个视频参数变体
   - 策略：通过参数组合（不同画面风格/音色/BGM）+ 随机扰动避免同质化
   - 输出：差异化视频列表 + 生成任务进度
   - API：`POST /api/ai/batch-generate` 接受 `hotspot_ids[]` + `variants[]`

4. **P4 大模型识别提示词/分镜链路串联** `api/services/ai/prompt_storyboard_pipeline.py`（新建）
   - 串联流程：热点视频 → `ai_agent_client` 拆解 → 提取提示词+分镜 → `explainer_video_client` 生成新视频
   - 类：`PromptStoryboardPipeline`
   - 关键方法：`extract_prompt_from_hotspot(hotspot_video_url) -> {prompt, storyboard}`
   - 关键方法：`generate_video_from_prompt(prompt, storyboard, config) -> video_url`
   - API：`POST /api/ai/generate-from-hotspot` 一键串联

5. **审核机制人工复核流程** `api/services/moderation/review_workflow.py`（新建）
   - 数据类：`ReviewTask`（video_id, status: auto_approved/pending_manual/approved/rejected, reviewer, notes）
   - 状态机：自动审核通过 → 直接入发布队列；自动审核失败 → 进入人工复核队列
   - API：`POST /api/moderation/review` 提交人工复核结果
   - API：`GET /api/moderation/review-queue` 查看待复核列表
   - 数据库表：`video_review_tasks`

**验收标准**：
- ✅ 可通过 API 配置视频时长（15-60s）、分辨率、画面风格、配音音色、字幕样式
- ✅ 可指定营销信息的植入位置、时长、形式
- ✅ 一次选择多个热点可批量生成差异化视频
- ✅ 给定热点视频 URL，可自动提取提示词+分镜并生成新视频
- ✅ 自动审核失败的视频进入人工复核队列

---

#### 任务 1.3：突发热点预警中心（1 周）

**目标**：补齐 PRD 5.1.3 第 6 条"高热度突发热点弹窗提醒 + 一键取材"。

**实施步骤**：

1. **热点热度突变检测** `api/services/hotpoint/hotpoint_alert.py`（新建）
   - 类：`HotpointAlertService`
   - 检测算法：维护热点历史热度曲线，检测 N 分钟内热度增量超过阈值
     - `delta_threshold: int = 1000`（10 分钟内热度增长 ≥1000 视为突发）
     - `velocity_threshold: float = 2.0`（10 分钟内热度增速 ≥2 倍视为突发）
   - 后台任务：每 5 分钟扫描最近 30 分钟热点，对比历史数据
   - 触发后写入 `hotpoint_alerts` 表

2. **WebSocket 实时弹窗推送** `api/routers/websocket.py`（增强）
   - 新增端点 `WS /ws/hotpoint-alerts`
   - 用户隔离：按 `owner_user_id` 推送
   - 推送内容：`{type, hotspot_id, title, heat_value, delta, velocity, platforms, suggest_action}`

3. **一键取材 API** `api/routers/hotpoint.py`（增强）
   - `POST /api/hotpoint/{hotspot_id}/quick-create` 一键将突发热点转为视频生成任务
   - 内部串联：热点详情 → 视频参数默认值 → `BatchVideoGenerator` → 任务进度

4. **前端弹窗组件** `webui-new/src/components/HotpointAlertToast.tsx`（新建）
   - 监听 `/ws/hotpoint-alerts`
   - 弹窗展示：热点标题、热度增量、适配平台、"一键取材"按钮
   - 点击按钮调用 `/api/hotpoint/{id}/quick-create`

**验收标准**：
- ✅ 热点热度突变时 5 分钟内可检测到
- ✅ 前端通过 WebSocket 收到弹窗提醒
- ✅ 点击"一键取材"可启动视频生成任务

---

#### 任务 1.4：统一预警中心（1 周）

**目标**：横向能力，覆盖突发热点 + 账号异常 + 数据异常 + 内容异常四类预警。

**实施步骤**：

1. **统一预警服务** `api/services/alert/alert_center.py`（新建）
   - 类：`AlertCenter`
   - 数据类：`Alert`（id, type, severity, source, title, content, action_url, created_at, status）
   - `AlertType` 枚举：`HOTPOINT_BURST` / `ACCOUNT_ANOMALY` / `DATA_ANOMALY` / `CONTENT_VIOLATION`
   - `AlertSeverity` 枚举：`INFO` / `WARNING` / `CRITICAL`
   - 关键方法：
     - `emit_alert(alert: Alert) -> str` 发送预警
     - `list_alerts(user_id, filter) -> List[Alert]` 查询预警
     - `mark_read(alert_id, user_id)` 标记已读
   - 持久化到 `alerts` 表（含 `owner_user_id` 隔离）

2. **账号异常实时预警链路** `api/services/risk_control/account_health.py`（增强）
   - 在现有健康度评分基础上增加实时预警触发器：
     - 健康分 < 30 → `AlertCenter.emit_alert(ACCOUNT_ANOMALY, WARNING)`
     - 检测到限流信号 → `CRITICAL`
     - 检测到登录失效 → `CRITICAL`
   - 监听 publisher/interactor 的失败事件，异步触发预警

3. **数据异常预警** `api/services/analytics/analytics_service.py`（增强）
   - 定时任务（每小时）：对比最近 3 小时与昨日同时段数据
   - 异常定义：
     - 发布成功率下降 > 20%
     - 互动量下降 > 30%
     - 任务卡死 > 1 小时
   - 触发 `AlertCenter.emit_alert(DATA_ANOMALY)`

4. **内容异常预警** `api/services/moderation/moderation_service.py`（增强）
   - 自动审核拦截违规内容时，触发 `AlertCenter.emit_alert(CONTENT_VIOLATION)`
   - 高违规率（>5%）触发 `CRITICAL` 预警

5. **预警路由** `api/routers/alert.py`（新建）
   - `GET /api/alerts` 查询预警列表（支持 type/severity/status 筛选）
   - `POST /api/alerts/{id}/read` 标记已读
   - `POST /api/alerts/read-all` 全部已读
   - `WS /ws/alerts` WebSocket 实时推送

6. **前端预警中心** `webui-new/src/pages/AlertCenter.tsx`（新建）
   - 顶部导航栏铃铛图标 + 未读计数
   - 预警列表按严重度排序，支持筛选

**验收标准**：
- ✅ 突发热点、账号异常、数据异常、内容异常四类预警统一汇集到 `/api/alerts`
- ✅ 前端可通过 WebSocket 实时收到预警
- ✅ 健康分 < 30 / 限流 / 登录失效均触发账号异常预警
- ✅ 发布成功率下降 > 20% 触发数据异常预警

---

#### 任务 1.5：独立机器人账号池（0.5 周）

**目标**：补齐 PRD 5.4 互动主体"独立机器人账号池"概念，与发布账号池分离。

**实施步骤**：

1. **机器人账号数据表** `database/models.py`（新增）
   - `BotAccount` 模型：`id, platform, cookie, label, group, region, status, health_score, owner_user_id, created_at, last_used_at`
   - `group` 字段支持：`domestic_new` / `domestic_mature` / `overseas_us` / `overseas_eu` 等

2. **机器人账号服务** `api/services/interactor/bot_account_pool.py`（新建）
   - 类：`BotAccountPool`
   - 关键方法：
     - `add_account(platform, cookie, label, group, region)`
     - `get_account(platform, group=None, region=None) -> BotAccount` 轮换选取
     - `mark_failed(account_id, failure_type)` 失败处理
     - `mark_success(account_id)` 成功反馈
   - 复用 `account_health.py` 评分逻辑，但独立存储
   - Cookie 池冷却/失效机制独立于发布账号池

3. **BaseInteractor 集成** `api/services/interactor/base_interactor.py`（增强）
   - 在 `_get_account` 方法中改为从 `BotAccountPool` 获取账号
   - 不再与 `publisher/account_service.py` 共享账号池

4. **机器人账号管理路由** `api/routers/interact.py`（增强）
   - `POST /api/interact/bot-accounts` 添加机器人账号
   - `GET /api/interact/bot-accounts` 列表（支持平台/分组/地区筛选）
   - `DELETE /api/interact/bot-accounts/{id}` 删除
   - `POST /api/interact/bot-accounts/{id}/health-check` 主动健康检查

5. **前端机器人账号管理页** `webui-new/src/pages/BotAccounts.tsx`（新建）
   - 按平台/分组/地区分类展示
   - 批量导入 Cookie
   - 健康分实时显示

**验收标准**：
- ✅ 机器人账号池与发布账号池独立存储，互不影响
- ✅ 支持按平台/分组/地区筛选账号
- ✅ 互动器执行时从机器人账号池获取账号

---

#### 任务 1.6：热点库管理增强（0.5 周）

**目标**：补齐 PRD 5.1.3 第 4-5 条"热点类型/适配平台自动标注 + 爆款/普通区分 + 库管理"。

**实施步骤**：

1. **热点类型自动标注** `api/services/hotpoint/hotpoint_classifier.py`（新建）
   - 类：`HotpointClassifier`
   - 基于关键词 + AI 双策略分类
   - 分类标签：娱乐 / 生活 / 职场 / 科技 / 财经 / 教育 / 健康 / 旅游 / 美食 / 时尚
   - 关键词词库 + LLM 兜底（调用 `ai_service` 生成分类）
   - 在热点入库时异步触发分类

2. **适配平台自动标注**
   - 规则：基于热点类型 → 推荐适配平台
     - 娱乐/生活/美食/时尚 → 抖音、小红书、微博
     - 科技/财经/职场 → 知乎、B站、X
     - 教育 → B站、知乎
   - 在 `hotpoint_fetcher.py` 入库时调用 `HotpointClassifier.recommend_platforms()`

3. **爆款/普通热点区分**
   - 阈值规则：热度 > 平台 P90 分位 + 增速 > 2x → 标记 `is_viral=True`
   - 数据库字段：`hotspots.is_viral BOOLEAN DEFAULT FALSE`
   - 每日定时任务更新所有热点的爆款标记

4. **热点库管理 API** `api/routers/hotpoint.py`（增强）
   - `POST /api/hotpoint/{id}/favorite` 收藏
   - `POST /api/hotpoint/{id}/disable` 禁用
   - `GET /api/hotpoint/search` 高级搜索（关键词+类型+平台+爆款+时间范围）
   - `POST /api/hotpoint/{id}/tags` 自定义标签

5. **前端热点库管理 UI** `webui-new/src/pages/HotpointLibrary.tsx`（新建）
   - 卡片式展示，支持收藏/禁用/打标
   - 多维度筛选侧边栏

**验收标准**：
- ✅ 新入库热点自动标注类型（10 类）和适配平台
- ✅ 爆款热点自动识别并标记
- ✅ 前端可收藏/禁用/搜索热点

---

#### 任务 1.7：热点筛选配置项 + 抓取频率可调（0.5 周）

**目标**：补齐 PRD 5.1.3 第 3 条"热度阈值/行业品类/受众人群/地域范围筛选 + 5 分钟级抓取频率"。

**实施步骤**：

1. **筛选规则配置中心** `api/services/hotpoint/hotpoint_filter_config.py`（新建）
   - 数据类：`HotpointFilterConfig`
     - `min_heat_value: int = 0` 最低热度阈值
     - `industry_categories: List[str]` 行业品类筛选
     - `target_audience: List[str]` 受众人群（年龄/性别/兴趣）
     - `regions: List[str]` 地域范围
     - `include_keywords: List[str]` 包含关键词
     - `exclude_keywords: List[str]` 排除关键词
     - `only_viral: bool = False` 仅看爆款
   - 持久化到 `hotpoint_filter_configs` 表（含 `owner_user_id` 隔离）

2. **抓取频率可调** `api/services/hotpoint_fetcher.py`（增强）
   - 配置项：`HOTPOINT_FETCH_INTERVAL_SECONDS`（环境变量，默认 1800 = 30 分钟）
   - 支持最小 5 分钟（300 秒）
   - 启动时从数据库读取用户自定义间隔，定时任务动态调整

3. **筛选 API** `api/routers/hotpoint.py`（增强）
   - `GET/POST /api/hotpoint/filter-config` 查询/更新筛选配置
   - `POST /api/hotpoint/preview` 预览筛选结果（不入库）

4. **前端筛选 UI** `webui-new/src/components/HotpointFilter.tsx`（新建）
   - 多维度筛选表单
   - 实时预览匹配热点数

**验收标准**：
- ✅ 可配置热度阈值、行业品类、受众人群、地域范围筛选
- ✅ 抓取频率可调至 5 分钟
- ✅ 筛选规则持久化，不同用户独立配置

---

### 2.3 阶段一里程碑

| 周次 | 交付物 |
|---|---|
| W1-W2 | 快手发布器+互动器上线，可端到端发布+互动 |
| W3 | 视频参数配置中心 + 营销植入精细化 + 批量生成 |
| W4 | 突发热点预警中心 + 统一预警中心上线 |
| W5 | 独立机器人账号池 + 热点库管理 + 筛选配置 |
| W6 | 集成测试 + 端到端验收 + 修复 |

---

## 三、阶段二：P1 海外平台 + 合规增强（7 周）

### 3.1 阶段目标

补齐 PRD P1 次必做项，使系统覆盖海外主流平台，并完成合规检测增强、智能调度、互动话术自定义。

### 3.2 任务拆解

#### 任务 2.1：海外平台发布器（2.5 周）

**目标**：补齐 PRD 5.3 海外平台缺口（TikTok、Instagram Reels、YouTube Shorts、Facebook、Twitter(X)）。

**实施步骤**：

1. **TikTok 发布器** `api/services/publisher/platforms/tiktok_publisher.py`
   - 通过 TikTok Creator Marketplace API 或 Playwright 自动化
   - 视频上传 + 标题/描述/话题标签
   - 9:16 竖屏视频必填

2. **Instagram Reels 发布器** `api/services/publisher/platforms/instagram_publisher.py`
   - 通过 Meta Graph API（需 Instagram Business 账号）
   - Reels 视频上传 + caption + hashtags
   - 9:16 竖屏视频必填

3. **YouTube Shorts 发布器** `api/services/publisher/platforms/youtube_publisher.py`
   - 通过 YouTube Data API v3
   - 视频上传 + title + description + tags
   - Shorts 标签：`#shorts`

4. **Facebook 发布器** `api/services/publisher/platforms/facebook_publisher.py`
   - 通过 Meta Graph API
   - 视频上传 + 文案 + 链接

5. **Twitter(X) 发布器** `api/services/publisher/platforms/twitter_publisher.py`
   - 整合现有 `x_comment_sender.py` 的 Media Upload + GraphQL CreateTweet 能力
   - 支持视频/图片/纯文本发布
   - 与 `publisher` 体系对齐

6. **平台元数据** 在 `publisher/platform_configs.py` 中新增 5 个海外平台配置
   - 视频尺寸、时长限制、话题标签规则、敏感词库

7. **海外平台账号管理** `api/services/publisher/account_service.py`（增强）
   - 支持 OAuth2 token 管理（IG/YT/FB）
   - 支持 cookie 持久化（TikTok/X）

**验收标准**：
- ✅ 5 个海外平台均可通过 `/api/publish` 发布视频
- ✅ 发布失败自动重试 3 次
- ✅ 发布记录入库（含平台、账号、链接、素材）

---

#### 任务 2.2：海外平台互动器（1.5 周）

**目标**：补齐 PRD 5.4 海外平台互动缺口。

**实施步骤**：

1. **TikTok/Instagram/YouTube/Facebook/Twitter 互动器** 5 个文件
   - 分别继承 `BaseInteractor`
   - 实现点赞/评论/回复/关注
   - 通过平台 API 或 Playwright 自动化

2. **地域适配串联** `api/services/interactor/base_interactor.py`（增强）
   - 在 `_get_account` 中按平台国家匹配代理 IP
   - 调用 `risk_control/proxy_pool.py` 的 `get_proxy_by_country(platform, country)`
   - 海外机器人执行互动时强制使用本地 IP

3. **互动类型扩展** `api/services/interactor/interaction_models.py`（增强）
   - `InteractionType` 新增 `FAVORITE`（收藏）、`REPOST`（轻微转发）
   - 各平台 interactor 实现新方法 `_do_favorite` / `_do_repost`

4. **时效控制** `api/services/interactor/interaction_scheduler.py`（新建）
   - 类：`InteractionScheduler`
   - 关键能力：发布后延迟 5-30 分钟启动互动（随机）
   - 频次控制：单条内容互动量自定义区间、点赞评论比例
   - 后台 asyncio 任务调度

**验收标准**：
- ✅ 5 个海外平台均可执行点赞/评论/回复/关注/收藏/转发
- ✅ 海外机器人执行时使用对应国家 IP
- ✅ 互动延迟 5-30 分钟启动，避免机器化特征

---

#### 任务 2.3：内容合规检测增强（1 周）

**目标**：补齐 PRD 5.6 涉政识别 + 侵权检测。

**实施步骤**：

1. **涉政内容检测** `api/services/moderation/political_detector.py`（新建）
   - 类：`PoliticalDetector`
   - 三层检测：
     - L1：涉政敏感词库（自定义 + 内置）+ 正则匹配
     - L2：调用 AI 服务（`ai_service`）做语义级涉政识别
     - L3：高危内容直接拦截，中危进入人工复核
   - 集成到 `ModerationService.moderate()` 流程

2. **侵权内容检测** `api/services/moderation/copyright_detector.py`（新建）
   - 类：`CopyrightDetector`
   - 图片侵权：感知哈希（pHash）+ 与已知版权图库对比
   - 视频侵权：关键帧提取 + pHash + 与平台已有内容对比
   - 音频侵权：音频指纹（AcoustID 集成）
   - 集成到 `ModerationService.moderate()` 流程

3. **统一频次硬限制配置中心** `api/services/risk_control/quota_config.py`（新建）
   - 数据类：`QuotaConfig`
     - `platform: str`
     - `max_publishes_per_day: int`
     - `max_interactions_per_day: int`
     - `max_comments_per_post: int`
     - `like_comment_ratio: float` 点赞评论比例
   - 持久化到 `quota_configs` 表
   - 在 publisher/interactor 执行前校验

4. **合规留存归档机制** `api/services/moderation/compliance_archive.py`（新建）
   - 类：`ComplianceArchiveService`
   - 长期留存：所有发布内容、互动记录、操作日志
   - 归档策略：90 天热数据（DB） + 1 年冷数据（对象存储/文件系统）
   - API：`GET /api/moderation/archive` 查询归档记录

**验收标准**：
- ✅ 涉政内容自动识别并拦截
- ✅ 图片/视频/音频侵权可检测
- ✅ 单账号单日发布/互动频次可配置且强制校验
- ✅ 所有操作记录归档留存 ≥1 年

---

#### 任务 2.4：发布节奏智能调度（1 周）

**目标**：在现有 `publish_scheduler.py` 基础上增加错峰策略优化。

**实施步骤**：

1. **平台活跃时段模型** `api/services/scheduling/peak_hours.py`（新建）
   - 数据类：`PeakHours`（按平台/工作日/周末分时段统计活跃度）
   - 内置默认值：
     - 抖音：12-13 / 19-22
     - 小红书：7-9 / 12-13 / 20-22
     - B站：18-23
     - 海外平台按时区调整
   - API：`GET /api/scheduling/peak-hours/{platform}`

2. **错峰发布策略** `api/services/scheduling/publish_scheduler.py`（增强）
   - 新增策略：`smart_stagger`（智能错峰）
     - 自动选择下一个活跃时段
     - 避免与同账号已发布内容时间冲突
     - 多平台分发时按平台时区分散
   - 配置项：`schedule_strategy: enum`（immediate/scheduled/smart_stagger）

3. **发布频率自适应** 
   - 监控账号近期发布成功率，自动调整频率
   - 失败率高时降低频率，成功率稳定时恢复

**验收标准**：
- ✅ 可查询各平台活跃时段
- ✅ 智能错峰策略可自动选择最佳发布时间
- ✅ 失败率高时自动降频

---

#### 任务 2.5：互动话术自定义（1 周）

**目标**：补齐 PRD 5.4 话术智能配置。

**实施步骤**：

1. **话术词库管理** `api/services/interactor/script_library.py`（新建）
   - 类：`ScriptLibrary`
   - 数据类：`Script`（id, platform, scene, content, tags, usage_count, owner_user_id）
   - 场景分类：`comment_reply` / `direct_message` / `engagement_boost` / `conversion`
   - 支持 CRUD + 批量导入

2. **AI 随机差异化话术生成** `api/services/interactor/script_generator.py`（新建）
   - 类：`ScriptGenerator`
   - 关键方法：`generate(script_type, context, count=5) -> List[str]`
   - 基于 `ai_service` 生成多个差异化话术变体
   - 同义词替换、句式重排、零宽字符注入

3. **话术路由 API** `api/routers/interact.py`（增强）
   - `GET/POST/PUT/DELETE /api/interact/scripts` 话术 CRUD
   - `POST /api/interact/scripts/generate` AI 生成话术
   - `POST /api/interact/scripts/batch-import` 批量导入

4. **前端话术管理页** `webui-new/src/pages/ScriptLibrary.tsx`（新建）
   - 按平台/场景分类展示
   - 编辑器 + 标签管理
   - AI 生成按钮

**验收标准**：
- ✅ 可自定义话术词库，按平台/场景分类
- ✅ AI 可生成差异化话术变体
- ✅ 互动时随机选取话术，避免重复

---

#### 任务 2.6：视频号 + 今日头条发布器（0.5 周）

**目标**：补齐国内 P0 平台剩余 2 个。

**实施步骤**：

1. **视频号发布器** `api/services/publisher/platforms/wechat_channels_publisher.py`
   - 通过微信视频号助手 Playwright 自动化
   - 视频上传 + 描述 + 话题标签

2. **今日头条发布器** `api/services/publisher/platforms/toutiao_publisher.py`
   - 通过头条号后台 Playwright 自动化
   - 视频上传 + 标题 + 描述

3. **平台元数据** 在 `publisher/platform_configs.py` 中新增 2 个平台配置

**验收标准**：
- ✅ 2 个平台均可通过 `/api/publish` 发布视频
- ✅ 失败重试机制生效

---

### 3.3 阶段二里程碑

| 周次 | 交付物 |
|---|---|
| W1-W2 | 海外 5 平台发布器上线 |
| W3 | 海外 5 平台互动器 + 地域适配 + 时效控制 |
| W4 | 涉政/侵权检测 + 频次配置中心 + 合规归档 |
| W5 | 智能调度 + 错峰策略 |
| W6 | 互动话术自定义 |
| W7 | 视频号 + 今日头条发布器 + 集成测试 |

---

## 四、阶段三：P2 优化项（5 周）

### 4.1 阶段目标

补齐 PRD P2 优化项，提升系统智能化与运营效率。

### 4.2 任务拆解

#### 任务 3.1：外部平台数据采集（1.5 周）

**目标**：补齐 PRD 5.5"账号涨粉量、平台引流访问量、转化量"外部数据采集。

**实施步骤**：

1. **外部数据采集服务** `api/services/analytics/external_metrics.py`（新建）
   - 类：`ExternalMetricsCollector`
   - 平台 API 集成：
     - 抖音开放平台（粉丝数/视频播放量/互动量）
     - 小红书蒲公英（数据看板）
     - B站创作中心（粉丝/播放/互动）
     - YouTube Data API（subscriber/view/like）
     - TikTok Business API
     - Meta Graph API（IG/FB insights）
   - 定时任务：每日凌晨拉取昨日数据
   - 持久化到 `external_metrics` 表

2. **转化量追踪** 
   - 通过 UTM 参数追踪引流链接
   - 落地页埋点上报
   - 数据回写到 `external_metrics`

3. **API 暴露** `api/routers/analytics.py`（增强）
   - `GET /api/analytics/external-metrics` 查询外部数据
   - `GET /api/analytics/funnel` 转化漏斗分析

**验收标准**：
- ✅ 每日自动拉取各平台粉丝/播放/互动数据
- ✅ 可查询转化漏斗（曝光→点击→访问→转化）

---

#### 任务 3.2：爆款内容复盘（1 周）

**目标**：PRD P2 爆款内容复盘。

**实施步骤**：

1. **爆款识别** `api/services/analytics/viral_detector.py`（新建）
   - 基于互动量增速、互动率、播放完成率识别爆款
   - 阈值：互动率 > 平台 P90 + 增速 > 3x

2. **复盘报告生成** `api/services/analytics/viral_review.py`（新建）
   - 类：`ViralReviewService`
   - 自动生成报告：热点溯源、内容要素分析、发布时机、互动节奏、AI 总结
   - 调用 `ai_service` 生成可读报告
   - 持久化到 `viral_review_reports` 表

3. **API** `api/routers/analytics.py`（增强）
   - `GET /api/analytics/viral-reviews` 复盘报告列表
   - `GET /api/analytics/viral-reviews/{id}` 报告详情

**验收标准**：
- ✅ 自动识别爆款内容
- ✅ 生成可读的复盘报告

---

#### 任务 3.3：热点热度预测模型（1 周）

**目标**：PRD P2 热点热度预测。

**实施步骤**：

1. **预测模型** `api/services/hotpoint/heat_predictor.py`（新建）
   - 类：`HeatPredictor`
   - 基于历史热度曲线 + 时间序列预测（指数平滑/ARIMA）
   - 输出：未来 1/3/6/12 小时热度预测
   - 模型每日重训练

2. **预警联动**
   - 预测热度将持续上升 → 提前触发"潜力热点"预警
   - 通过统一预警中心推送

**验收标准**：
- ✅ 可预测热点未来热度走势
- ✅ 潜力热点提前预警

---

#### 任务 3.4：互动数据精细化分析 + 多账号权重优化（1 周）

**实施步骤**：

1. **互动数据精细化** `api/services/analytics/interaction_analytics.py`（新建）
   - 互动完成率、互动增量、异常互动识别
   - 按平台/账号/内容维度分析

2. **多账号权重优化** `api/services/risk_control/account_weight.py`（新建）
   - 基于账号健康分、互动效果、违规记录动态调整账号权重
   - 权重影响账号在池中的选取优先级

**验收标准**：
- ✅ 互动数据可按多维度分析
- ✅ 账号权重动态调整

---

#### 任务 3.5：操作日志完善 + 日/周/月报表定时生成（0.5 周）

**实施步骤**：

1. **操作日志查询** `api/services/utils/audit_log.py`（新建）
   - 统一记录所有用户操作（发布/互动/配置变更/账号管理）
   - 持久化到 `audit_logs` 表
   - API：`GET /api/audit-logs` 多维度查询

2. **定时报表生成** `api/services/analytics/report_scheduler.py`（新建）
   - 定时任务：每日/每周/每月生成报表
   - 自动调用 `export_service` 导出 CSV/Excel
   - 通过邮件/Webhook 推送

**验收标准**：
- ✅ 所有用户操作可追溯
- ✅ 报表定时生成并推送

---

## 五、阶段四：P3/P4 高级功能（4 周）

### 5.1 阶段目标

补齐 PRD P3 多平台自动回复私信 + P4 大模型识别提示词/分镜串联深度。

### 5.2 任务拆解

#### 任务 4.1：多平台自动回复私信（2 周）

**目标**：扩展 `dm/` 从 X 平台到 5 个国内 + 5 个海外平台。

**实施步骤**：

1. **私信监控平台适配** `api/services/dm/dm_monitor.py`（增强）
   - 新增 9 个平台的私信监控：
     - 国内：抖音、小红书、B站、微博、知乎
     - 海外：TikTok、Instagram、YouTube、Facebook
   - 每个平台通过 API 或 Playwright 拉取私信

2. **DM Replier 增强** `api/services/dm/dm_replier.py`（增强）
   - 多平台回复能力适配
   - 意图识别优化（咨询/投诉/合作/闲聊/高价值）

3. **API** `api/routers/dm.py`（增强）
   - `GET /api/dm/platforms` 支持的平台列表
   - `POST /api/dm/{platform}/reply` 跨平台回复

**验收标准**：
- ✅ 10 个平台均可监控私信
- ✅ AI 可自动回复或转人工

---

#### 任务 4.2：P4 大模型识别提示词/分镜深度串联（1.5 周）

**目标**：在阶段一任务 1.2 的基础上，构建完整的"热点视频 → 提示词/分镜 → 视频生成"全链路工作流。

**实施步骤**：

1. **提示词库沉淀** `api/services/ai/prompt_library.py`（新建）
   - 类：`PromptLibrary`
   - 从历史热点视频提取的提示词+分镜结构化存储
   - 支持检索、复用、变体生成
   - 持久化到 `prompt_library` 表

2. **分镜结构化解析** `api/services/ai/storyboard_parser.py`（新建）
   - 类：`StoryboardParser`
   - 从 `ai_agent_client` 输出的分镜文本，解析为结构化数据
   - 数据类：`Storyboard`（scenes: List[Scene]，每个 Scene 含：shot_type, duration, visual_prompt, voiceover, subtitle, transition）

3. **生成链路编排** `api/services/ai/prompt_storyboard_pipeline.py`（增强）
   - 完整流程：
     1. 热点视频 → `ai_agent_client` 拆解
     2. 拆解结果 → `StoryboardParser` 结构化
     3. 结构化分镜 → `PromptLibrary` 沉淀 + 检索相似案例
     4. 优化提示词 → `explainer_video_client` 生成视频
     5. 生成视频 → `ModerationService` 审核
     6. 审核通过 → `publisher` 多平台分发

4. **API** `api/routers/ai.py`（增强）
   - `POST /api/ai/prompt-library/search` 检索提示词
   - `GET /api/ai/storyboard/{id}` 查询分镜
   - `POST /api/ai/full-pipeline` 一键执行完整链路

**验收标准**：
- ✅ 提示词库可检索复用
- ✅ 分镜可结构化解析
- ✅ 一键执行从热点到发布的完整链路

---

#### 任务 4.3：账号分组管理 + 互动量配置 UI（0.5 周）

**实施步骤**：

1. **账号分组** `api/services/publisher/account_service.py`（增强）
   - 数据库字段：`publisher_accounts.group`（domestic_new/domestic_mature/overseas_us/overseas_eu）
   - 分组管理 API

2. **互动量配置 UI** `webui-new/src/pages/InteractionConfig.tsx`（新建）
   - 单条内容互动量区间配置
   - 点赞评论比例配置
   - 时效控制配置（延迟 5-30 分钟）

**验收标准**：
- ✅ 账号可分组管理
- ✅ 互动量参数前端可配置

---

## 六、技术架构与依赖

### 6.1 新增数据库表清单

| 表名 | 阶段 | 用途 |
|---|---|---|
| `hotpoint_alerts` | 一 | 突发热点预警记录 |
| `alerts` | 一 | 统一预警中心 |
| `bot_accounts` | 一 | 机器人账号池 |
| `hotpoint_filter_configs` | 一 | 热点筛选规则配置 |
| `video_generation_configs` | 一 | 视频生成参数配置 |
| `video_review_tasks` | 一 | 人工复核任务 |
| `quota_configs` | 二 | 频次硬限制配置 |
| `external_metrics` | 三 | 外部平台数据 |
| `viral_review_reports` | 三 | 爆款复盘报告 |
| `audit_logs` | 三 | 操作日志 |
| `prompt_library` | 四 | 提示词库 |
| `storyboards` | 四 | 分镜结构化数据 |

### 6.2 新增 API 路由清单

| 路由前缀 | 阶段 | 用途 |
|---|---|---|
| `/api/alerts` | 一 | 统一预警中心 |
| `/api/ai/video-config` | 一 | 视频参数配置 |
| `/api/ai/batch-generate` | 一 | 批量视频生成 |
| `/api/ai/generate-from-hotspot` | 一 | 热点转视频 |
| `/api/moderation/review` | 一 | 人工复核 |
| `/api/moderation/archive` | 二 | 合规归档 |
| `/api/scheduling/peak-hours` | 二 | 平台活跃时段 |
| `/api/interact/scripts` | 二 | 话术库 |
| `/api/interact/bot-accounts` | 一 | 机器人账号管理 |
| `/api/analytics/external-metrics` | 三 | 外部数据 |
| `/api/analytics/viral-reviews` | 三 | 爆款复盘 |
| `/api/audit-logs` | 三 | 操作日志 |
| `/api/ai/prompt-library` | 四 | 提示词库 |

### 6.3 新增前端页面

| 页面 | 阶段 | 用途 |
|---|---|---|
| `AlertCenter.tsx` | 一 | 预警中心 |
| `BotAccounts.tsx` | 一 | 机器人账号管理 |
| `HotpointLibrary.tsx` | 一 | 热点库管理 |
| `VideoGenConfig.tsx` | 一 | 视频参数配置 |
| `ReviewQueue.tsx` | 一 | 人工复核队列 |
| `ScriptLibrary.tsx` | 二 | 话术库 |
| `InteractionConfig.tsx` | 四 | 互动量配置 |
| `ExternalMetrics.tsx` | 三 | 外部数据看板 |
| `ViralReviews.tsx` | 三 | 爆款复盘 |
| `PromptLibrary.tsx` | 四 | 提示词库 |

### 6.4 关键技术选型

| 能力 | 选型 | 理由 |
|---|---|---|
| 时序热度预测 | 指数平滑 + ARIMA | 轻量级，无需深度学习框架 |
| 涉政识别 | 关键词 + AI 语义双层 | 兼顾准确性和成本 |
| 侵权检测 | pHash + AcoustID | 业界标准方案 |
| 外部数据采集 | 各平台官方 API | 合规优先 |
| 视频生成链路 | 现有 `explainer_video_client` + 参数扩展 | 用户已确认可接受 |
| WebSocket 推送 | 现有 `/ws/` 架构扩展 | 复用基础设施 |

---

## 七、风险与缓解措施

| 风险点 | 影响 | 缓解措施 |
|---|---|---|
| 海外平台 API 配额限制 | 发布/互动频率受限 | 多账号轮换 + 请求队列削峰 |
| 视频生成 AI 服务不稳定 | 5.2 模块阻塞 | 多模型链（OneLLM→gpt-image→DALL-E）已有，扩展视频生成兜底 |
| 平台反检测升级 | 发布/互动失败率上升 | `stealth_browser` 持续迭代 + `proxy_pool` IP 轮换 |
| 涉政误判 | 内容被错误拦截 | 三级检测（关键词→AI→人工复核），保留申诉通道 |
| 外部数据 API 失效 | 数据统计断档 | 多源兜底 + 失败告警 + 手动导入 |
| 机器人账号大规模封禁 | 互动能力瘫痪 | 独立账号池 + 健康分管理 + 风控冷却 + 分散操作 |
| 工期延误 | 阶段交付延期 | 每阶段独立可验收，避免强依赖 |

---

## 八、验收标准（对照 PRD 第 8 章）

### 8.1 热点模块（PRD 8.1）

- ✅ 可正常抓取海内外主流平台热点
- ✅ 支持筛选（热度阈值/行业/受众/地域）、排序、预警
- ✅ 数据实时有效（5 分钟级抓取）
- ✅ 突发热点弹窗提醒 + 一键取材

### 8.2 视频模块（PRD 8.2）

- ✅ 可基于热点自动生成视频
- ✅ 支持自定义植入营销信息（位置/时长/形式）
- ✅ 视频参数可配置（时长/分辨率/风格/音色/字幕）
- ✅ 审核功能正常生效（自动 + 人工复核）
- ✅ 支持批量生成差异化视频

### 8.3 分发模块（PRD 8.3）

- ✅ 可批量/定时发布至海内外全部目标平台
- ✅ 发布成功率 ≥ 99%（含失败重试）
- ✅ 账号分组管理 + 状态监控
- ✅ 差异化分发（视频尺寸/时长/文案/话题）

### 8.4 互动模块（PRD 8.4）

- ✅ 机器人可自动完成点赞、评论、留言、收藏、转发
- ✅ 行为贴合真人逻辑（延迟启动 + 随机间隔 + 地域适配）
- ✅ 无集中风控异常
- ✅ 独立机器人账号池 + 分组管理
- ✅ 话术自定义 + AI 差异化生成

### 8.5 抓取视频（PRD 8.5）

- ✅ 抓取的视频大模型识别提示词、分镜信息
- ✅ 提示词库可检索复用
- ✅ 串联到视频生成输入链路

### 8.6 回复私信（PRD 8.6）

- ✅ 机器人自动回复营销视频私信
- ✅ 覆盖 10 个平台（5 国内 + 5 海外）
- ✅ AI 意图识别 + 转人工

### 8.7 数据模块（PRD 8.7）

- ✅ 全链路运营数据统计准确
- ✅ 报表可正常导出、趋势可视化展示
- ✅ 日/周/月报表定时生成
- ✅ 外部平台数据（涨粉/访问/转化）采集

---

## 九、附录：任务依赖关系图

```
阶段一（P0）：
  1.5 机器人账号池 ──┐
                     ├── 1.1 快手发布器+互动器
  1.7 筛选配置 ──────┘
  1.6 热点库管理 ──── 1.3 突发热点预警 ──── 1.4 统一预警中心
  1.2 视频生成能力补全（独立）

阶段二（P1）：
  2.1 海外发布器 ── 2.2 海外互动器 ──── 1.4 统一预警中心（复用）
  2.3 合规增强 ──── 1.4 统一预警中心（复用）
  2.4 智能调度（依赖 2.1）
  2.5 话术自定义（依赖 1.5）
  2.6 视频号+头条（独立）

阶段三（P2）：
  3.1 外部数据采集 ── 3.2 爆款复盘
  3.3 热点预测 ──── 1.3 突发预警（联动）
  3.4 互动分析 ──── 1.5 机器人池（复用）
  3.5 操作日志+报表（独立）

阶段四（P3/P4）：
  4.1 多平台私信（依赖 2.1/2.2 海外平台）
  4.2 P4 提示词串联（依赖 1.2 视频生成）
  4.3 账号分组+互动量 UI（依赖 1.5）
```

---

## 十、文档版本历史

| 版本 | 日期 | 变更说明 |
|---|---|---|
| v1.0 | 2026-07-26 | 初始版本，基于 PRD 缺口清单制定 4 阶段 22 周开发方案 |
