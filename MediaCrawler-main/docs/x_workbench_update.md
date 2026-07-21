# X Twitter 工作台评论回复监控更新文档

## 一、问题概述

之前的评论回复监控存在以下逻辑混乱问题：

1. **回复原帖而非回复者评论**：AI 回复时使用底部回复框，导致所有回复都变成对原帖的评论，而非对回复者的回复
2. **监控范围错误**：访问原帖 URL 抓取所有评论，而非访问用户评论 URL 只抓取对用户评论的回复
3. **URL 后缀问题**：捕获的评论 URL 包含 `/analytics` 后缀，导致无法正常访问
4. **用户名过滤缺失**：无法区分自己和他人的评论

## 二、架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                    X Twitter 工作台                            │
├─────────────────────────────────────────────────────────────────┤
│  热点推文选择  →  视频拆解  →  评论生成  →  发送评论             │
│                                                    │          │
│                                                    ▼          │
│                                          监控回复（每180秒）    │
│                                                    │          │
│              ┌─────────────────────────────────────┘          │
│              ▼                                                │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                 评论回复监控流程                          │ │
│  ├───────────────────────────────────────────────────────────┤ │
│  │  1. 查询 monitoring=1 的已发评论                          │ │
│  │  2. 访问用户评论 URL（而非原帖）                          │ │
│  │  3. 调用 X.com GraphQL API 获取评论线程                  │ │
│  │  4. 过滤掉用户自己的评论和已记录的回复                      │ │
│  │  5. 新回复写入数据库，触发 AI 自动回复                     │ │
│  │  6. 访问回复者评论 URL，点击其 reply 按钮回复              │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## 三、关键数据流

### 3.1 评论发送流程

| 步骤 | 操作 | 文件 |
|------|------|------|
| 1 | 用户在前端选择评论并点击「真实发送」 | `XWorkbench.tsx` |
| 2 | 调用 `/api/x-workbench/comments/send` | `x_twitter_workbench.py` |
| 3 | 启动浏览器，访问原帖，点击回复按钮 | `x_comment_sender.py::send_comment` |
| 4 | 在输入框输入评论，点击发送 | `x_comment_sender.py::_launch_browser_and_send` |
| 5 | 捕获评论 URL（去除 `/analytics` 后缀） | `x_comment_sender.py::第174-196行` |
| 6 | 保存到 `XTwitterSentComment` 表，`monitoring=1` | `x_twitter_workbench.py::第400-410行` |

### 3.2 回复监控流程

| 步骤 | 操作 | 文件 |
|------|------|------|
| 1 | 后台定时任务触发（每 180 秒） | `comment_reply_monitor.py::_monitor_loop` |
| 2 | 查询 `monitoring=1` 且未过期的评论 | `comment_reply_monitor.py::_check_all_sent_comments` |
| 3 | **访问用户评论 URL**（而非原帖 URL） | `comment_reply_monitor.py::_check_one_sent_comment` |
| 4 | 调用 X.com GraphQL API 获取评论线程 | `comment_reply_monitor.py::_fetch_replies_via_post_page` |
| 5 | 解析 GraphQL 响应，提取回复列表 | `comment_reply_monitor.py::_parse_graphql_replies` |
| 6 | 过滤已存在的回复和用户自己的评论 | `comment_reply_monitor.py::_check_one_sent_comment` |
| 7 | 新回复写入 `XTwitterReply` 表 | `comment_reply_monitor.py::第142-158行` |
| 8 | 触发 AI 自动回复 | `comment_reply_monitor.py::_auto_reply_to_new_replies` |

### 3.3 AI 自动回复流程

| 步骤 | 操作 | 文件 |
|------|------|------|
| 1 | 检查每日 AI 回复上限 | `comment_reply_monitor.py::_auto_reply_to_new_replies` |
| 2 | 调用 AI Agent 生成回复内容 | `ai_agent_client.py::generate_auto_reply` |
| 3 | **访问回复者评论 URL**，点击其 reply 按钮 | `x_comment_sender.py::reply_to_comment` |
| 4 | 在回复对话框输入内容，点击发送 | `x_comment_sender.py::第339-389行` |
| 5 | 更新数据库状态 | `comment_reply_monitor.py::第342-359行` |

## 四、核心修复点

### 4.1 评论 URL 捕获修复

**问题**：之前简单取最后一个 `/status/` 链接，可能获取到 `/analytics` 等无效 URL

**修复**：逆序查找符合 `/username/status/id` 格式的链接，自动去除后缀

```python
# x_comment_sender.py 第174-196行
for link in reversed(links):
    href = await link.get_attribute("href")
    if href and href.startswith("/"):
        parts = href.strip("/").split("/status/")
        if len(parts) == 2:
            status_id = parts[1].split("?")[0].split("#")[0].split("/")[0]
            if status_id.isdigit():
                comment_url = f"https://x.com{parts[0]}/status/{status_id}"
                break
```

### 4.2 回复监控目标修复

**问题**：之前访问原帖 URL，抓取所有评论当成回复

**修复**：改为访问用户评论 URL（`sc.comment_url`），只抓取对用户评论的回复

```python
# comment_reply_monitor.py 第110-117行
async def _check_one_sent_comment(sc: XTwitterSentComment):
    if sc.sent_status != "success" or not sc.comment_url:
        return
    replies = await _fetch_replies_for_post(sc.comment_url)
```

### 4.3 回复方式修复

**问题**：之前使用页面底部回复框，总是回复到原帖

**修复**：改为找到目标评论的 reply 按钮，点击后在对话框中回复

```python
# x_comment_sender.py 第335-351行
articles = await page.query_selector_all('article[data-testid="tweet"]')
target_article = articles[0]
reply_btn = await target_article.wait_for_selector('[data-testid="reply"]')
await reply_btn.click()
```

### 4.4 使用 GraphQL API 替代浏览器抓取

**问题**：浏览器 DOM 解析不稳定，难以正确识别嵌套回复

**修复**：优先使用 X.com GraphQL API 获取评论线程，更准确可靠

```python
# comment_reply_monitor.py 第216-257行
response = await client.get(
    "https://x.com/i/api/graphql/0xqQ8gOaPQ8aQ8OaPQ8aQ/TweetDetail",
    headers=headers,
    params=params,
)
data = response.json()
return _parse_graphql_replies(data, tweet_id)
```

## 五、数据库表结构

### XTwitterSentComment

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| post_id | str | 原帖 ID |
| post_url | str | 原帖 URL |
| comment_url | str | 发送的评论 URL（关键！） |
| comment_content | str | 评论内容 |
| sent_status | str | success/failed/draft |
| monitoring | int | 1=监控中，0=停止 |
| reply_count | int | 收到的回复数 |
| auto_replied_count | int | AI 已回复数 |
| sent_at | int | 发送时间戳 |
| last_check_ts | int | 最后检查时间 |

### XTwitterReply

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| sent_comment_id | int | 关联的已发评论 ID |
| reply_id | str | 回复者评论 ID |
| reply_url | str | 回复者评论 URL（关键！） |
| replier_username | str | 回复者用户名 |
| reply_content | str | 回复内容 |
| auto_reply_status | str | pending/sent/failed |
| auto_reply_content | str | AI 回复内容 |
| auto_reply_url | str | AI 回复后的 URL |

## 六、API 接口

### 评论发送

```
POST /api/x-workbench/comments/send
Content-Type: application/json

{
    "post_id": "2075595994327077095",
    "post_url": "https://x.com/i/web/status/2075595994327077095",
    "content": "评论内容",
    "real_send": true
}
```

### 回复监控

```
POST /api/x-workbench/monitor/start    - 启动监控
POST /api/x-workbench/monitor/stop     - 停止监控
GET  /api/x-workbench/monitor/status   - 获取监控状态
POST /api/x-workbench/monitor/check-now - 立即检查一次
```

### 已发评论列表

```
GET /api/x-workbench/comments?page=1&page_size=20
```

### 评论回复列表

```
GET /api/x-workbench/comments/{sent_comment_id}/replies
```

## 七、配置说明

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| X_TWITTER_COOKIES | X Twitter 登录 cookies | 空 |
| X_TWITTER_COOKIES_POOL | cookies 池（\| 分隔） | 空 |
| X_WORKBENCH_REPLY_CHECK_INTERVAL | 监控间隔（秒） | 180 |
| X_WORKBENCH_REPLY_DAILY_LIMIT | 每日 AI 回复上限 | 30 |

## 八、已知限制

1. **GraphQL API 限制**：X.com 的 GraphQL API 可能随时变更，需要定期更新
2. **Cookie 有效期**：cookies 有有效期，过期后需重新获取
3. **评论嵌套深度**：当前只处理一级回复，不处理嵌套回复的回复
4. **Rate Limit**：X.com 对 API 调用有限制，建议保持 180 秒间隔

## 九、更新日志

### 2026-07-17 v2.0

- [修复] 评论 URL 捕获去除 `/analytics` 后缀
- [修复] 监控访问用户评论 URL 而非原帖 URL
- [修复] AI 回复点击回复者的 reply 按钮而非底部回复框
- [新增] 使用 GraphQL API 获取评论线程（更可靠）
- [新增] 浏览器降级方案
- [清理] 删除之前错误的回复记录（32 条）
- [文档] 编写本更新文档
