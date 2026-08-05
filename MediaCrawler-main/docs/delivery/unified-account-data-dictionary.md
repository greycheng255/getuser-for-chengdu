# 统一账号数据字典

表：`unified_accounts`

唯一约束：`owner_user_id + platform + account_id`。

| 字段 | 类型/范围 | 说明 |
|---|---|---|
| `id` | integer | 数据库内部主键 |
| `account_id` | string(64) | 稳定业务账号标识 |
| `owner_user_id` | string(64) | 归属系统用户 |
| `platform` | string(32) | 规范平台编码，输入别名先归一化 |
| `account_name` | string(128) | 脱敏显示名称 |
| `role` | `publisher/interactor/both` | 业务角色 |
| `status` | 统一状态枚举 | `active/cooldown/expired/invalid/needs_relogin/disabled` |
| `auth_data` | JSON text | Cookie/Token 等认证信息，严禁 API 原文返回 |
| `capabilities` | JSON array | 发布、互动等能力 |
| `group_name` / `region` | string | 调度分组与地域 |
| `priority` / `weight` | integer | 调度优先级和权重 |
| `health_score` | 0—100 | 健康分 |
| `daily_limit` / `today_count` / `today_date` | integer/string | 每日配额状态 |
| `success_count` / `failure_count` | integer | 成败计数 |
| `cooldown_until` / `last_used_ts` | Unix timestamp | 冷却和最近使用时间 |
| `migration_batch_id` / `legacy_source` | string | 迁移审计和批次回滚依据 |
| `created_ts` / `updated_ts` | Unix timestamp | 审计时间 |

列表和详情只返回 `auth_configured`、字段级脱敏摘要，不返回 `auth_data` 原文。
