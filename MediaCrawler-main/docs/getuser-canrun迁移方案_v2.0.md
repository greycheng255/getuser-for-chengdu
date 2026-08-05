# 获客采集数据迁移方案 v2.0（聚焦版）

> **文档版本**: v2.0（替代 v1.0）  
> **编写日期**: 2026-08-04  
> **目标**: 将 getuser-canrun 的「获客采集数据」功能完整迁移到 MediaCrawler-main，迁移完成后**彻底删除 getuser-canrun 目录**  
> **核心约束**: 营销中心完全不迁移；MediaCrawler-main 迁移后必须完全自包含

---

## 一、迁移边界（明确迁什么、不迁什么）

### 1.1 迁移清单（A 类：获客采集数据）

| # | 功能 | 源文件 | 迁移方式 | 依赖 |
|---|------|--------|---------|------|
| A1 | 线索检测器（角色分类+严格双词+去重） | `store/customer_lead.py`（1456行） | **覆盖** MediaCrawler 584行旧版 | 标准库 only |
| A2 | 任务线索扫描（scan_task_leads） | `api/routers/tasks.py` L2942-3384 | **覆盖** MediaCrawler 旧版 | A1 |
| A3 | 任务精准获客配置端点 | `api/routers/tasks.py` L1659-1900 | **增量** 添加 | A1 |
| A4 | 线索列表/导出/统计增强 | `api/routers/customer_lead.py`（1278行） | **覆盖** MediaCrawler 763行旧版 | A1 |
| A5 | 联系方式采集服务 | `api/services/contact_collector.py`（789行） | **新建** | A6 + 共享浏览器 |
| A6 | 联系方式提取（从主页） | `outreach_automation.py` L2505-2688 | **剥离**为独立模块 | page参数+DB |
| A7 | IM 对话读取 | `outreach_automation.py` L1314-1409 | **剥离**为独立模块 | page参数 only |
| A8 | 抖音线索评论回扫 | `api/services/comment_reply_monitor.py`（抖音版） | **新建** `lead_comment_monitor.py` | A6 + 共享浏览器 |
| A9 | 抖音采集增强（反检测+真人模拟+验证码旁路+cursor翻页） | `media_platform/douyin/core.py` | **增量**合并 | A10 + A11 |
| A10 | 反检测脚本工具 | `tools/anti_detect.py` | **新建** | 标准库+playwright |
| A11 | account_pool 搜索熔断器 | `api/services/account_pool.py` L332-892 | **增量**合并 | 独立 |
| A12 | 反检测浏览器启动器 | `outreach_automation.py` L1472+L1752 | **剥离**为 `lead_browser.py` | A10 |
| A13 | 数据库表/字段补齐 | `database/models.py` + 迁移SQL | **增量** | 无 |
| A14 | 启动注册（contact_collector循环+抖音reply_monitor循环） | `api/main.py` L138+L146 | **增量** | A5 + A8 |

### 1.2 不迁移清单（B 类：营销/商业化，随目录删除消失）

| # | 功能 | 源文件 | 不迁原因 |
|---|------|--------|---------|
| B1 | outreach 自动触达（私信发送） | `outreach_automation.py` 主体 | 营销触达，非采集 |
| B2 | X 平台发布 | `x_publisher.py` | MediaCrawler 已有 publisher/ |
| B3 | X 发布调度+健康分 | `x_schedule_runner.py` | MediaCrawler 已有 scheduling/ |
| B4 | FFmpeg 视频混剪 | `video_compose.py` | MediaCrawler 已有 mixcut/ |
| B5 | 素材库 | `media_assets.py` + `MediaAsset` 表 | 营销素材管理 |
| B6 | X 账号养号 | `x_account.py` + `XAccount` 表 | 起号营销 |
| B7 | X 发布计划 | `x_schedule.py` + `XPublishSchedule` 表 | 起号营销 |
| B8 | 业务画像规则 | `business_profiles.py` | 营销配置（A1已含精准获客） |
| B9 | 商业化交付闭环（15表） | `database/models.py` L802-1044 | 销售CRM+买断 |
| B10 | 交付验收循环 | `api/main.py` L123 | 商业化 |
| B11 | account_pool 每日发送配额 | `account_pool.py` L697-720 | outreach专属 |
| B12 | OutreachMessage 模型 | `database/models.py` L598 | 私信记录（A7只读对话不入库） |
| B13 | 计费账本 BillingLedger | `plan.py` + `BillingLedgerModel` | MediaCrawler 已有算力计费 |
| B14 | 营销中心前端6页面 | `webui-new/src/pages/` 6个tsx | 营销UI |

---

## 二、耦合点剥离方案（关键）

### 2.1 最大耦合点：`_launch_browser_for_outreach`

**问题**：contact_collector（L387）和抖音版 comment_reply_monitor（L322）都调用 `outreach_automation._launch_browser_for_outreach` 启动浏览器，这是与营销模块的核心耦合。

**剥离方案**：新建 `api/services/lead_browser.py` 共享浏览器启动器

```python
# api/services/lead_browser.py（新建）
"""获客采集专用浏览器启动器
从 outreach_automation._launch_browser_for_outreach 剥离，
仅供 contact_collector / lead_comment_monitor 使用，
不依赖 outreach_automation 任何代码。
"""
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from tools.anti_detect import get_anti_detect_script, read_browser_fingerprint
# 复用 MediaCrawler-main 已有的 cookie_manager
from .cookie_manager import get_cookie

async def launch_lead_browser(
    platform: str,
    user_id: int = 0,
    headless: bool = True,
) -> tuple[Browser, BrowserContext, Page]:
    """启动获客采集专用浏览器
    
    功能：
    1. 启动系统 Chrome（channel="chrome"）
    2. 注入 anti_detect 反检测脚本（WebRTC/AudioContext/WebGL2补全）
    3. 加载平台 Cookie
    4. 返回 (browser, context, page)
    """
    # ... 从 outreach_automation._launch_browser_for_outreach + _inject_anti_detection 剥离
```

**改造点**：
- `contact_collector.py` L387：`from .outreach_automation import _launch_browser_for_outreach` → `from .lead_browser import launch_lead_browser`
- `comment_reply_monitor.py`（抖音版）L322：同上改造
- 迁移后两个服务完全脱离 outreach_automation

### 2.2 联系方式提取剥离

**问题**：`_extract_user_contact_info` 和 `_update_customer_lead_contact` 在 outreach_automation.py 中，但仅依赖 page 参数和 CustomerLead 表。

**剥离方案**：合并到 `contact_collector.py` 或新建 `contact_extractor.py`

```python
# 从 outreach_automation.py L2505-2688 剥离到 contact_collector.py
async def extract_user_contact_info(page: Page, platform: str) -> dict:
    """从用户主页提取手机/微信/简介（原 _extract_user_contact_info）"""
    # 仅依赖 page.evaluate + 正则，无 outreach 依赖

async def update_customer_lead_contact(lead_id: int, contact_info: dict):
    """回写联系方式到 CustomerLead 表（原 _update_customer_lead_contact）"""
    # 仅依赖 database.models.CustomerLead
```

### 2.3 IM 对话读取剥离

**问题**：`_read_im_conversation` 接受 page 参数，无 outreach 依赖；但 `_save_conversation_messages` 依赖营销模型 OutreachMessage。

**剥离方案**：仅迁移 `_read_im_conversation`，不迁移 `_save_conversation_messages`

```python
# 从 outreach_automation.py L1314-1409 剥离到 im_reader.py
async def read_im_conversation(page: Page) -> list[dict]:
    """读取 IM 对话气泡（原 _read_im_conversation）
    
    返回 [{"direction": "sent/received", "content": "...", "ts": ...}]
    不入库（入库逻辑属营销，不迁移）
    """
    # 仅依赖 page.evaluate
```

### 2.4 account_pool 熔断器剥离

**问题**：搜索熔断器（A 类）和每日发送配额（B 类）混在 account_pool.py 中。

**剥离方案**：仅迁移熔断器，配额逻辑保留但不激活

```python
# 迁移到 MediaCrawler-main 的 account_pool.py（增量添加）
_search_circuit_breaker_until: float = 0.0
_search_circuit_breaker_cooldown: int = 1800  # 30分钟

def is_search_circuit_open(self) -> bool: ...
def get_circuit_breaker_remaining(self) -> int: ...
def _trigger_search_circuit_breaker(self, reason: str): ...
def reset_search_circuit_breaker(self): ...

# 不迁移：record_daily_send / MAX_DAILY_SENDS_PER_ACCOUNT / daily_send_count
```

---

## 三、修订后的迁移清单与工作量

### 3.1 必须迁移的文件（14项）

| # | 任务 | 类型 | 工作量 | 负责人 |
|---|------|------|--------|--------|
| M1 | 数据库表/字段补齐（CustomerLead 8字段 + CrawlerTask 5字段 + LeadCommentReply 表） | SQL+ORM | 0.5天 | A |
| M2 | `tools/anti_detect.py` 全量迁移 | 新建 | 0.5天 | A |
| M3 | `store/customer_lead.py` 增强版覆盖（1456行） | 覆盖 | 0.5天 | B |
| M4 | `api/routers/customer_lead.py` 增强版覆盖（1278行） | 覆盖 | 0.5天 | B |
| M5 | `api/routers/tasks.py` scan_task_leads + 精准获客端点合并 | 增量 | 1天 | B |
| M6 | 评分门槛调整（高≥80/中≥50）+ level阈值 | 修改 | 0.5天 | B |
| M7 | `api/services/lead_browser.py` 新建（剥离自outreach） | 新建 | 1天 | A |
| M8 | `api/services/contact_collector.py` 迁移+解耦 | 新建 | 1.5天 | A |
| M9 | `api/services/lead_comment_monitor.py` 新建（抖音版） | 新建 | 1天 | A |
| M10 | 联系方式提取+IM读取剥离到独立模块 | 剥离 | 0.5天 | A |
| M11 | `api/services/account_pool.py` 熔断器合并 | 增量 | 0.5天 | A |
| M12 | `media_platform/douyin/core.py` 采集增强合并 | 增量 | 2天 | A |
| M13 | `api/main.py` 启动注册补全 | 增量 | 0.5天 | A |
| M14 | 配置开关 + 前端任务配置页/线索列表页改造 | 增量 | 1.5天 | A |
| **合计** | | | **12天** | |

### 3.2 不迁移的文件（随目录删除消失）

- `api/services/outreach_automation.py`（主体，仅剥离3个函数）
- `api/services/x_publisher.py`
- `api/services/x_schedule_runner.py`
- `api/services/video_compose.py`
- `api/routers/business_profiles.py`
- `api/routers/media_assets.py`
- `api/routers/video_compose.py`
- `api/routers/x_publish.py`
- `api/routers/x_schedule.py`
- `api/routers/x_account.py`
- `webui-new/src/pages/` 下6个营销页面
- `database/models.py` 中15张商业化表 + 8张起号营销表
- `api/services/plan.py` 的 BillingLedger 部分

---

## 四、执行步骤

### Phase 1：数据基础与纯模块迁移（2.5天）

```
Step 1: 数据库迁移脚本（备份→ALTER→CREATE）
        ├── CustomerLead 加8字段
        ├── CrawlerTask 加5字段
        └── LeadCommentReply 新建表
Step 2: tools/anti_detect.py 全量迁移（纯模块，无依赖）
Step 3: store/customer_lead.py 覆盖迁移（1456行，纯模块）
Step 4: 评分门槛 + level阈值调整
Step 5: database/models.py ORM 同步
```

### Phase 2：API 层迁移（2天）

```
Step 6: api/routers/customer_lead.py 覆盖迁移（1278行）
Step 7: api/routers/tasks.py 合并：
        ├── scan_task_leads 评分分支重构
        ├── PUT /{task_id}/lead-config 端点
        ├── POST /{task_id}/filter-unrelated-leads
        ├── POST /{task_id}/dedup-leads
        └── 链接混淆变体10
Step 8: 前端任务配置页加精准获客字段
Step 9: 前端线索列表页加角色/联系方式列
```

### Phase 3：浏览器启动解耦（1.5天，关键路径）

```
Step 10: 新建 api/services/lead_browser.py
         ├── 从 outreach_automation._launch_browser_for_outreach 剥离启动逻辑
         ├── 从 outreach_automation._inject_anti_detection 剥离反检测注入
         └── 集成 tools/anti_detect.py
Step 11: 联系方式提取+IM读取剥离到 contact_extractor.py / im_reader.py
```

### Phase 4：采集服务迁移（3天）

```
Step 12: api/services/contact_collector.py 迁移
         ├── 从 getuser-canrun 全量迁移
         ├── L387 改为 from .lead_browser import launch_lead_browser
         └── 集成 contact_extractor
Step 13: api/services/lead_comment_monitor.py 新建（抖音版）
         ├── 从 getuser-canrun comment_reply_monitor.py 迁移
         ├── L322 改为 from .lead_browser import launch_lead_browser
         └── 避免与 MediaCrawler X版同名冲突
Step 14: account_pool 熔断器合并
Step 15: media_platform/douyin/core.py 采集增强合并
         ├── anti_detect 导入
         ├── 浏览器指纹缓存
         ├── 真人鼠标轨迹+滚动
         ├── 5种验证码旁路
         ├── cursor翻页+关键词扩展
         ├── 搜索入口多样化+URL混淆
         ├── verify_check检测+账号切换
         ├── UA修复+sec-ch-ua头
         └── .env override=False
Step 16: api/main.py 启动注册
         ├── contact_collector.start_contact_collector_loop
         └── lead_comment_monitor.start_reply_monitor_loop
```

### Phase 5：集成测试与删除验证（3天）

```
Step 17: 单元测试
         ├── 角色分类准确率
         ├── 双词匹配
         ├── 相似度去重
         └── 联系方式正则
Step 18: 集成测试
         ├── 端到端抖音采集→线索检测→联系方式采集
         └── 评论回扫
Step 19: 回归测试
         ├── X工作台不受影响
         ├── AI内容生产不受影响
         └── 多平台发布/互动不受影响
Step 20: 自包含性验证（见第五节）
Step 21: 删除 getuser-canrun 目录
```

**总工作量：12天 + 3天测试 = 15天（约3周）**

---

## 五、彻底删除 getuser-canrun 的验证清单

迁移完成后，执行以下验证，全部通过才能删除目录：

### 5.1 代码引用验证

```bash
# 1. 确认 MediaCrawler-main 不再引用 getuser-canrun 任何路径
grep -r "getuser-canrun" /home/ubuntu/getuser-for-chengdu/MediaCrawler-main/ \
  --include="*.py" --include="*.ts" --include="*.tsx" --include="*.json" \
  --include="*.yml" --include="*.yaml" --include="*.md" --include="*.env"
# 期望：0 条结果

# 2. 确认 MediaCrawler-main 不引用 outreach_automation（已剥离）
grep -rn "from.*outreach_automation import" /home/ubuntu/getuser-for-chengdu/MediaCrawler-main/api/
# 期望：0 条结果（除非 MediaCrawler-main 原本就有自己的 outreach）

# 3. 确认 lead_browser 已替代 _launch_browser_for_outreach
grep -rn "_launch_browser_for_outreach" /home/ubuntu/getuser-for-chengdu/MediaCrawler-main/
# 期望：0 条结果

# 4. 确认 anti_detect 已迁移
grep -rn "from tools.anti_detect import" /home/ubuntu/getuser-for-chengdu/MediaCrawler-main/
# 期望：≥2 条（core.py + lead_browser.py）

# 5. 确认 contact_collector 已迁移
ls /home/ubuntu/getuser-for-chengdu/MediaCrawler-main/api/services/contact_collector.py
# 期望：文件存在

# 6. 确认 lead_comment_monitor 已迁移
ls /home/ubuntu/getuser-for-chengdu/MediaCrawler-main/api/services/lead_comment_monitor.py
# 期望：文件存在
```

### 5.2 数据库验证

```sql
-- 1. CustomerLead 表含全部8个新字段
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'customer_lead' 
AND column_name IN ('content_hash','dup_count','role_tag','contact_phone',
                    'contact_wechat','bio_text','contact_status','reply_monitor_ts');
-- 期望：8 行

-- 2. CrawlerTask 表含全部5个新字段
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'crawler_task' 
AND column_name IN ('business_intent','intent_keywords','exclude_keywords',
                    'target_role','target_regions');
-- 期望：5 行

-- 3. LeadCommentReply 表存在
SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'lead_comment_reply');
-- 期望：true
```

### 5.3 功能验证

| 验证项 | 验证方法 | 期望结果 |
|--------|---------|---------|
| 抖音采集 | 创建采集任务，触发搜索 | 正常采集+线索入库 |
| 角色分类 | 查看线索列表 role_tag 字段 | 供方/求方正确标注 |
| 双词匹配 | 配置 intent_keywords，采集 | 仅双词命中入库 |
| 联系方式采集 | 触发 collect-contact | 手机/微信正确提取 |
| 评论回扫 | 触发 monitor-replies | 回复正确监测 |
| 熔断器 | 触发风控后检查 | 30分钟冷却生效 |
| 反检测 | 浏览器启动日志 | anti_detect 脚本注入 |
| X工作台 | 访问 /x-workbench | 功能正常 |
| AI客服 | 访问 /ai-customer-service | 功能正常 |
| 热点中心 | 访问 /hotpoint-library | 功能正常 |

### 5.4 删除执行

```bash
# 所有验证通过后，执行删除
mv /home/ubuntu/getuser-for-chengdu/getuser-canrun \
   /home/ubuntu/getuser-for-chengdu/_getuser-canrun-backup-$(date +%Y%m%d)
# 先重命名为备份，观察1周无问题后再彻底删除
rm -rf /home/ubuntu/getuser-for-chengdu/_getuser-canrun-backup-*
```

---

## 六、风险评估与对策

### 6.1 关键风险

| 风险 | 等级 | 影响 | 对策 |
|------|------|------|------|
| lead_browser 剥离不完整，反检测质量下降 | **高** | 采集触发风控 | 直接迁移 _inject_anti_detection 全文，不重写 |
| customer_lead.py 覆盖后与 MediaCrawler 现有调用不兼容 | **高** | 线索功能异常 | 对比两版 detect 签名，保留 MediaCrawler 独有调用 |
| 抖音 core.py 合并冲突 | **中** | 采集失败 | 用 getuser 版增量覆盖，保留 MediaCrawler 独有功能 |
| LeadCommentReply 与 MediaCrawler 现有 X版 comment_reply_monitor 冲突 | **中** | 服务启动失败 | 抖音版用新文件名 lead_comment_monitor.py |
| 数据库迁移失败 | **低** | 数据丢失 | 先备份，迁移后验证 |

### 6.2 回滚方案

```bash
# 代码回滚
cd /home/ubuntu/getuser-for-chengdu/MediaCrawler-main
git checkout .  # 回滚所有修改

# 数据库回滚
psql -c "RESTORE TABLE customer_lead FROM customer_lead_backup;"
psql -c "DROP TABLE IF EXISTS lead_comment_reply;"
psql -c "ALTER TABLE customer_lead DROP COLUMN IF EXISTS content_hash, dup_count, role_tag, contact_phone, contact_wechat, bio_text, contact_status, reply_monitor_ts;"
psql -c "ALTER TABLE crawler_task DROP COLUMN IF EXISTS business_intent, intent_keywords, exclude_keywords, target_role, target_regions;"
```

---

## 七、与 v1.0 方案的差异

| 维度 | v1.0 | v2.0 |
|------|------|------|
| 迁移范围 | A-J 全部10类 | 仅 A 类（获客采集） |
| 营销中心 | 选择性迁移 | **完全不迁移** |
| 商业化闭环 | 暂不迁移 | **完全不迁移** |
| 计费账本 | 建议迁移 | **不迁移**（MediaCrawler 已有算力计费） |
| 起号营销 | 选择性迁移 | **完全不迁移** |
| 浏览器启动 | 未识别耦合点 | **识别并剥离** lead_browser.py |
| outreach_automation | 整体考虑 | **仅剥离3个纯函数**，主体不迁移 |
| 工作量 | 22.5天 | **15天** |
| 终态 | getuser-canrun 保留 | **彻底删除** getuser-canrun |

---

## 八、附录

### 8.1 迁移文件清单（一图速览）

```
getuser-canrun（源）                    MediaCrawler-main（目标）
─────────────────────────────────────────────────────────────────
store/customer_lead.py (1456行)    ──覆盖──>  store/customer_lead.py
api/routers/customer_lead.py       ──覆盖──>  api/routers/customer_lead.py
api/routers/tasks.py (部分)         ──合并──>  api/routers/tasks.py
api/services/contact_collector.py  ──迁移──>  api/services/contact_collector.py
api/services/comment_reply_monitor ──新建──>  api/services/lead_comment_monitor.py
api/services/account_pool.py (部分) ──增量──>  api/services/account_pool.py
media_platform/douyin/core.py (部分)──增量──>  media_platform/douyin/core.py
tools/anti_detect.py               ──迁移──>  tools/anti_detect.py
api/main.py (部分)                  ──增量──>  api/main.py
database/models.py (部分)           ──增量──>  database/models.py
outreach_automation.py (3个函数)    ──剥离──>  api/services/lead_browser.py
                                            api/services/contact_extractor.py
                                            api/services/im_reader.py
config/base_config.py (部分)        ──增量──>  config/base_config.py
```

### 8.2 不迁移文件清单（随目录删除）

```
api/services/outreach_automation.py（主体）
api/services/x_publisher.py
api/services/x_schedule_runner.py
api/services/video_compose.py
api/routers/business_profiles.py
api/routers/media_assets.py
api/routers/video_compose.py
api/routers/x_publish.py
api/routers/x_schedule.py
api/routers/x_account.py
webui-new/src/pages/MarketingHub.tsx
webui-new/src/pages/MediaAssets.tsx
webui-new/src/pages/VideoCompose.tsx
webui-new/src/pages/XPublish.tsx
webui-new/src/pages/Incubator.tsx
webui-new/src/pages/BusinessProfiles.tsx
database/models.py 中15张商业化表 + 8张起号营销表
api/services/plan.py 的 BillingLedger 部分
```

### 8.3 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|---------|
| v1.0 | 2026-08-04 | 初版：全量对比+迁移方案 |
| v2.0 | 2026-08-04 | 聚焦版：仅迁获客采集，剥离耦合点，支持彻底删除 |

---

**文档结束**
