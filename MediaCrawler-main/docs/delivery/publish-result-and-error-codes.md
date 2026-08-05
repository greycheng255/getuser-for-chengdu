# 统一发布结果与错误码

## 结果字段

| 字段 | 含义 |
|---|---|
| `success` | 是否确认发布成功 |
| `platform` | 规范平台编码 |
| `account_id` | 统一账号内部标识 |
| `task_id` | 发布任务标识 |
| `post_id` | 平台作品标识 |
| `post_url` | 平台作品链接 |
| `error_code` | 标准错误码；成功时为空 |
| `error_message` | 脱敏错误描述 |
| `retryable` | 是否允许有限重试 |
| `started_at` / `finished_at` | UTC ISO 时间 |

`url`、`platform_id`、`error` 为兼容字段，与新字段双向同步。

## 错误处理

| 错误码 | 自动重试 | 账号/平台处理 |
|---|---:|---|
| `AUTH_EXPIRED` | 否 | 账号标记 `needs_relogin` |
| `CAPTCHA_REQUIRED` | 否 | 账号立即冷却，转人工 |
| `RATE_LIMITED` | 是 | 账号立即冷却，到期后有限重试 |
| `INVALID_MEDIA` | 否 | 返回素材修复 |
| `CONTENT_REJECTED` | 否 | 人工复核内容与平台规则 |
| `UPLOAD_FAILED` | 是 | 有限重试 |
| `SELECTOR_CHANGED` | 否 | 停止当前任务自动重试并保留证据 |
| `TIMEOUT` | 是 | 先执行发布后二次确认和作品列表补偿查询 |
| `UNKNOWN` | 否 | 不盲目重试，转人工复核 |

发布按钮点击不等于成功。抖音和小红书均需命中成功提示、作品页/管理页跳转，或在作品管理页通过标题补偿查询到最近作品。
