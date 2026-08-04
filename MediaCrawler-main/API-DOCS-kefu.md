# 云客智能客服系统 - 接口开发文档

> 后端框架:Go + Gin ｜ 数据库:MySQL 8 ｜ 向量库:Milvus ｜ 实时:WebSocket
> 接口总数:60+ ｜ 路由定义:[backend/router/router.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/router/router.go)

---

## ⚠️ 端口与代理说明(先读)

当前部署存在两个端口,职责不同:

| 端口 | 服务 | 用途 |
|------|------|------|
| **8063** | yunke-frontend (Next.js) | 前端页面 |
| **18080** | yunke-backend (Gin) | **API 接口** |
| 18088 | yunke-embedding | 嵌入服务(内部) |
| 33008 | yunke-mysql | MySQL(内部) |
| 19530 | milvus-standalone | Milvus(内部) |

**本文档示例统一使用 `8063` 端口**(按对外入口书写)。但需注意:

- **后端实际监听 18080**。所有 API 由 [backend/router/router.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/router/router.go) 注册,且同时挂载在「无前缀」和「`/api` 前缀」两组路径上,即 `/login` 与 `/api/login` 等价。
- 若要通过 **8063 同域访问 API**(即 `http://<HOST>:8063/api/*`),需要由反向代理把 `/api/*` 转发到后端 18080。当前 yunke-frontend 容器内 `next.config.mjs` 的 rewrites 把 `/api/*` 指向 `localhost:18080`,而后端在另一容器,**容器内 localhost 不通**,因此 8063 同域代理当前失效(返回 404/308)。
- **推荐用法**:对接开发时直接调用后端 `http://<HOST>:18080/api/*`;若必须走 8063,请在前端容器前加 Nginx,将 `/api/`、`/agent/`、`/ws`、`/uploads/`、`/messages/upload` 等路径反代到 18080。

**Base URL(下文示例统一写作):**
```
http://<HOST>:8063/api
```
> 实际直连后端时,把 `8063` 换成 `18080` 即可;`/api` 前缀可保留也可去掉。

---

## 一、通用约定

### 1.1 认证机制

系统**未使用 JWT/Session**,而是基于请求头 `X-User-Id` 做身份识别:

- 登录成功后返回 `user_id` 与 `ws_token`;
- 后续所有需身份的请求在请求头携带 `X-User-Id: <user_id>`;
- 客服建立 WebSocket 连接时另需 `ws_token`(由 `user_id` 签发,24h 有效);
- 权限校验在后端 controller 内按需执行(非全局中间件)。

### 1.2 请求头

| 头部 | 必填场景 | 说明 |
|------|----------|------|
| `Content-Type: application/json` | JSON 接口 | |
| `Content-Type: multipart/form-data` | 文件上传 | |
| `X-User-Id` | 需身份的接口 | 当前用户 ID(uint) |
| `X-Trace-Id` | 可选 | 链路追踪 ID,未传则后端生成并回写响应头 |
| `X-Current-User-ID` | Admin 用户管理接口 | 管理员身份(也可用 query `current_user_id`) |

### 1.3 统一响应格式

成功:HTTP 2xx + JSON 业务体(各接口不同,见下文)。
失败:HTTP 4xx/5xx + `{"error": "错误描述"}`。

```json
// 失败示例
{ "error": "用户名或密码错误" }
```

### 1.4 CORS

- 允许所有来源(`*`);
- 允许方法:`GET / POST / PUT / DELETE / OPTIONS`;
- 允许自定义头:`Origin / Content-Type / Accept / X-User-Id / X-Trace-Id`。

### 1.5 权限键(PermissionKey)

定义见 [backend/service/permissions.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/service/permissions.go#L14-L24)。`admin` 角色视为全权限;`agent` 角色按 `permissions` 字段(JSON 数组)校验,为空时默认仅 `chat`。

| 键 | 说明 |
|----|------|
| `chat` | 对话 |
| `kb_test` | 知识库测试(内部对话) |
| `knowledge` | 知识库(含文档/导入) |
| `faqs` | 事件管理 |
| `analytics` | 数据报表 |
| `logs` | 日志中心 |
| `prompts` | 提示词 |
| `settings` | AI 配置 |
| `users` | 用户管理 |

---

## 二、认证

### POST /api/login — 登录

- **请求体**
```json
{ "username": "admin", "password": "admin123456" }
```
- **成功 200**
```json
{
  "message": "登录成功",
  "user_id": 1,
  "username": "admin",
  "role": "admin",
  "ws_token": "...",
  "ws_token_exp": "2026-08-03T20:00:00Z",
  "permissions": ["chat", "knowledge", "faqs", "..."]
}
```
- **错误**:400 用户名密码为空;401 用户名或密码错误。
- **说明**:`ws_token` 用于客服 WebSocket 鉴权(24h);`permissions` 供前端菜单显示,后端强校验以 `X-User-Id` 为准。

### POST /api/logout — 登出

- **响应 200**:`{ "message": "退出成功" }`(无服务端状态,纯语义接口)

---

## 三、用户管理(Admin)

> 鉴权方式特殊:通过 query 参数 `current_user_id` **或** 请求头 `X-Current-User-ID` 提供当前操作者 ID,且该用户必须 `role=admin`。源码:[admin_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/admin_controller.go#L28-L58)。

### GET /api/admin/users — 用户列表

- **请求**:query `current_user_id=<admin_uid>`
- **响应 200**:User 数组,见 [数据模型 §User](#user)。

### GET /api/admin/users/:id — 用户详情

- **请求**:query `current_user_id=<admin_uid>`
- **响应 200**:User 对象;404 用户不存在。

### POST /api/admin/users — 创建用户

- **请求体**
```json
{
  "username": "agent01",
  "password": "123456",
  "role": "agent",
  "permissions": ["chat", "knowledge"],
  "nickname": "小王",
  "email": "wang@example.com"
}
```
- **响应 200**:`{ "message": "创建成功", "user": {…} }`
- **错误**:400 用户名已存在。

### PUT /api/admin/users/:id — 更新用户

- **请求体**(全部可选,指针类型)
```json
{
  "role": "agent",
  "permissions": ["chat"],
  "nickname": "小王",
  "email": "wang@example.com",
  "receive_ai_conversations": true
}
```
- **响应 200**:`{ "message": "更新成功", "user": {…} }`

### DELETE /api/admin/users/:id — 删除用户

- **响应 200**:`{ "message": "删除成功", "transferred_ai_configs": <被转移的AI配置数> }`
- **说明**:被删用户的 AI 配置会转移给当前操作的管理员。

### PUT /api/admin/users/:id/password — 更新密码

- **请求体**
```json
{ "old_password": "旧密码", "new_password": "新密码" }
```
- **说明**:管理员改他人密码时 `old_password` 可不传;改自己密码需校验旧密码。
- **响应 200**:`{ "message": "密码更新成功" }`

### POST /api/admin/agents — 创建客服(兼容旧接口)

- **请求体**:`{ "username", "password", "role", "permissions" }`
- **响应 200**:`{ "message": "创建成功", "user_id", "username", "role" }`

---

## 四、个人资料(Profile)

源码:[profile_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/profile_controller.go)。

### GET /api/agent/profile/:user_id — 获取个人资料

- **响应 200**:Profile 对象(基于 User,含 nickname/email/avatar_url/receive_ai_conversations 等)。

### PUT /api/agent/profile/:user_id — 更新个人资料

- **请求体**(全部可选)
```json
{ "nickname": "小王", "email": "wang@example.com", "receive_ai_conversations": true }
```
- **响应 200**:更新后的 Profile 对象。

### POST /api/agent/avatar/:user_id — 上传头像

- **请求体**:`multipart/form-data`,字段 `avatar`(图片文件)
- **限制**:仅 jpg/jpeg/png/gif;≤ 10MB
- **响应 200**:Profile 对象(含新 `avatar_url`)。

---

## 五、会话管理(Conversation)

源码:[conversation_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/conversation_controller.go)。

### POST /api/conversation/init — 访客初始化/恢复会话

- **请求体**
```json
{
  "visitor_id": 1001,
  "website": "https://example.com/page",
  "referrer": "https://google.com",
  "browser": "Chrome",
  "os": "Windows",
  "language": "zh-CN",
  "chat_mode": "ai",
  "ai_config_id": 3
}
```
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| visitor_id | uint | 是 | 访客 ID |
| website | string | 否 | 当前页面 URL |
| referrer | string | 否 | 来源页 |
| browser | string | 否 | 浏览器(空则后端解析 UA) |
| os | string | 否 | 操作系统(空则后端解析 UA) |
| language | string | 否 | 语言 |
| chat_mode | string | 否 | `human`(默认)/ `ai` |
| ai_config_id | uint* | 否 | AI 模式时必填 |
- **响应 200**:`{ "conversation_id": 12, "status": "open" }`

### POST /api/conversations/internal — 创建内部对话(知识库测试)

- **权限**:`kb_test`
- **请求**:query `user_id=<客服ID>`
- **响应 200**:`{ "conversation_id": 20, "status": "open" }`

### GET /api/conversations — 会话列表

- **query**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| user_id | uint | - | 客服 ID |
| type | string | `visitor` | `visitor` / `internal`(internal 需 `kb_test` 权限) |
| status | string | `open` | `open` / `closed` |
- **响应 200**:数组,每项含 `id / conversation_type / visitor_id / agent_id / status / chat_mode / unread_count / has_participated / last_seen_at / created_at / updated_at / last_message{…}`。

### GET /api/conversations/:id — 会话详情

- **query**(可选)`user_id`
- **响应 200**:会话对象,含访客信息(website/referrer/browser/os/ip_address/location/email/phone/notes)、`unread_count`、`last_message{…}`。

### POST /api/conversations/:id/close — 关闭会话

- **权限**:`chat`
- **请求头**:`X-User-Id`
- **响应 200**:`{ "ok": true }`

### PUT /api/conversations/:id/contact — 更新访客联系信息

- **请求体**(至少一个)
```json
{ "email": "v@example.com", "phone": "13800000000", "notes": "VIP" }
```
- **响应 200**:`{ "email", "phone", "notes" }`

### GET /api/conversations/search — 搜索会话

- **query**:`q`(必填)、`status`(默认 `open`)
- **响应 200**:会话数组(同列表项结构)。

### GET /api/conversations/ai-models — 开放模型列表(访客选型)

- **query**:`model_type`(默认 `text`)
- **响应 200**:`{ "models": [...] }`

---

## 六、消息管理(Message)

源码:[message_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/message_controller.go)。

### POST /api/messages — 发送消息

- **请求头**:客服发送时必须 `X-User-Id`
- **请求体**
```json
{
  "conversation_id": 12,
  "content": "您好,有什么可以帮您?",
  "sender_is_agent": true,
  "sender_id": 1,
  "file_url": null,
  "file_type": null,
  "file_name": null,
  "file_size": null,
  "mime_type": null,
  "use_knowledge_base": true,
  "use_llm": true,
  "use_web_search": false,
  "need_web_search": false
}
```
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | uint | 是 | |
| content | string | 二选一 | 文本内容 |
| sender_is_agent | bool | 是 | true=客服,false=访客 |
| sender_id | uint | 是 | 客服发送时由后端覆写为 X-User-Id;访客发送时后端强制置 0 |
| file_url / file_type / file_name / file_size / mime_type | 各类型 | 选填 | 文件消息(配合上传接口) |
| use_knowledge_base | bool* | 否 | AI 模式是否用知识库(默认 true) |
| use_llm | bool* | 否 | AI 模式是否用大模型(默认 true) |
| use_web_search | bool* | 否 | AI 模式是否联网(默认 false) |
| need_web_search | bool | 否 | 是否需要联网 |
- **权限**:`sender_is_agent=true` 时按会话类型校验:visitor 会话需 `chat`;internal 会话需 `kb_test` 且仅创建者可发。
- **响应 200**:完整 Message 对象(见 [数据模型 §Message](#message))。
- **错误**:400 会话已关闭/不存在;403 无权限。

### POST /api/messages/upload — 文件上传

- **Content-Type**:`multipart/form-data`
- **表单字段**
| 字段 | 必填 | 说明 |
|------|------|------|
| file | 是 | 文件 |
| conversation_id | 二选一 | 访客上传时用此鉴权(校验会话存在且未关闭) |
- **请求头**:客服上传用 `X-User-Id`;访客上传用 `conversation_id`(二者至少其一)
- **限制**:≤ 10MB;扩展名白名单 jpg/jpeg/png/gif/webp/pdf/doc/docx/txt;同时校验 MIME 与 magic number 防伪造
- **响应 200**
```json
{
  "success": true,
  "data": {
    "file_url": "/uploads/...",
    "file_type": "image",
    "file_name": "xxx.png",
    "file_size": 102400,
    "mime_type": "image/png"
  }
}
```

### GET /api/messages — 消息列表

- **query**:`conversation_id`(必填)、`include_ai_messages`(默认 `false`)
- **权限**:internal 会话仅创建者且需 `kb_test`;visitor 会话客服需 `chat`。
- **响应 200**:Message 数组。

### PUT /api/messages/read — 标记已读

- **请求头**:客服读取时 `X-User-Id`
- **请求体**:`{ "conversation_id": 12, "reader_is_agent": true }`
- **响应 200**
```json
{
  "updated": 5,
  "message_ids": [101, 102, 103, 104, 105],
  "conversation_id": 12,
  "unread_count": 0,
  "read_at": "2026-08-03T12:00:00Z"
}
```

---

## 七、知识库管理(KnowledgeBase)

> 鉴权:需 `knowledge` 权限 + `X-User-Id`(校验「是否开放知识库」开关)。源码:[knowledge_base_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/knowledge_base_controller.go)。

### GET /api/knowledge-bases — 知识库列表
- **响应 200**:`{ "knowledge_bases": [...] }`

### GET /api/knowledge-bases/:id — 知识库详情
- **响应 200**:KB 对象;404 不存在。

### POST /api/knowledge-bases — 创建知识库
- **请求体**:`{ "name": "产品手册"(必填), "description": "..." }`
- **响应 200**:KB 对象。

### PUT /api/knowledge-bases/:id — 更新知识库
- **请求体**(全部可选):`{ "name", "description", "rag_enabled" }`
- **响应 200**:KB 对象。

### PATCH /api/knowledge-bases/:id/rag-enabled — 切换 RAG 参与
- **请求体**:`{ "rag_enabled": true }`
- **响应 200**:KB 对象。

### DELETE /api/knowledge-bases/:id — 删除知识库
- **响应 200**:`{ "message": "删除成功" }`

### GET /api/knowledge-bases/:id/documents — 知识库下文档列表
- **响应 200**:`{ "message": "请使用 /documents?knowledge_base_id=:id" }`(占位接口,实际用文档列表接口过滤)

---

## 八、文档管理(Document)

> 鉴权:`knowledge` 权限 + `X-User-Id` + 知识库开关。源码:[document_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/document_controller.go)。

### GET /api/documents — 文档列表
- **query**:`knowledge_base_id`、`page`(默认 1)、`page_size`(默认 20)、`keyword`、`status`
- **响应 200**:分页结果对象。

### GET /api/documents/:id — 文档详情
- **响应 200**:Document 对象;404 不存在。

### POST /api/documents — 创建文档
- **请求体**
```json
{
  "knowledge_base_id": 1,
  "title": "退货政策",
  "content": "7天无理由...",
  "summary": "退货说明",
  "type": "md",
  "status": "draft"
}
```
(`knowledge_base_id` / `title` / `content` 必填)
- **响应 200**:Document 对象。

### PUT /api/documents/:id — 更新文档
- **请求体**(全部可选):`{ "title", "content", "summary", "type", "status" }`
- **响应 200**:Document 对象。

### DELETE /api/documents/:id — 删除文档
- **响应 200**:`{ "message": "删除成功" }`

### GET /api/documents/search — 向量检索
- **query**:`query`(必填)、`top_k`(默认 5)、`knowledge_base_id`(可选)
- **响应 200**:`{ "count": N, "documents": [...] }`

### GET /api/documents/hybrid-search — 混合检索
- 参数同上(当前实现与向量检索一致)

### PUT /api/documents/:id/status — 更新文档状态
- **请求体**:`{ "status": "published" }`
- **响应 200**:`{ "message": "更新成功" }`

### POST /api/documents/:id/publish — 发布文档
- **响应 200**:`{ "message": "发布成功" }`

### POST /api/documents/:id/unpublish — 取消发布
- **响应 200**:`{ "message": "取消发布成功" }`

---

## 九、文档导入(Import)

> 鉴权:`knowledge` 权限 + `X-User-Id`(必填,缺失直接 401)。源码:[import_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/import_controller.go)。

### POST /api/import/documents — 批量导入(文件上传)
- **Content-Type**:`multipart/form-data`
- **表单字段**:`knowledge_base_id`(必填)、`files`(文件数组,多文件)
- **支持扩展名**:`.md / .txt / .pdf / .doc / .docx`
- **响应 200**:导入结果对象(含 `message: "导入完成"`,及成功/失败计数与明细)。

### POST /api/import/urls — 批量导入(URL 爬取)
- **请求体**
```json
{ "knowledge_base_id": 1, "urls": ["https://example.com/a", "https://example.com/b"] }
```
- **响应 200**:导入结果对象。

---

## 十、FAQ / 事件管理

> 鉴权:`faqs` 权限。源码:[faq_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/faq_controller.go)。

### GET /api/faqs — FAQ 列表
- **query**:`query`(关键词,可选)
- **响应 200**:`{ "faqs": [...] }`

### GET /api/faqs/:id — FAQ 详情
- **响应 200**:FAQ 对象;404 不存在。

### POST /api/faqs — 创建 FAQ
- **请求体**:`{ "question"(必填), "answer"(必填), "keywords": "退货,退款" }`
- **响应 200**:FAQ 对象。

### PUT /api/faqs/:id — 更新 FAQ
- **请求体**(全部可选):`{ "question", "answer", "keywords" }`
- **响应 200**:FAQ 对象。

### DELETE /api/faqs/:id — 删除 FAQ
- **响应 200**:`{ "message": "删除成功" }`

---

## 十一、AI 配置

> 鉴权:`settings` 权限 + `X-User-Id`。源码:[ai_config_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/ai_config_controller.go)。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/agent/ai-config/:user_id | 创建 AI 配置 |
| GET | /api/agent/ai-config/:user_id | 列出该用户的所有配置 |
| GET | /api/agent/ai-config/:user_id/:id | 获取单条配置 |
| PUT | /api/agent/ai-config/:user_id/:id | 更新配置 |
| DELETE | /api/agent/ai-config/:user_id/:id | 删除配置 |

**创建/更新请求体字段**:
```json
{
  "provider": "openai",
  "api_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "model": "gpt-4o-mini",
  "model_type": "chat",
  "is_active": true,
  "is_public": false,
  "description": "默认配置"
}
```
(创建时 `provider/api_url/api_key/model` 必填;更新时全部可选)

**响应 200**:AIConfig 对象(含 `id / user_id / provider / api_url / api_key / model / model_type / is_active / is_public / description / created_at / updated_at`)。

---

## 十二、Embedding 配置(平台级)

> 鉴权:`settings` 权限。源码:[embedding_config_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/embedding_config_controller.go)。

### GET /api/agent/embedding-config — 获取配置
- **query**:`user_id`
- **响应 200**
```json
{
  "user_id": 1,
  "embedding_type": "openai",
  "api_url": "...",
  "api_key": "sk-...",
  "model": "text-embedding-3-small",
  "customer_can_use_kb": true,
  "visitor_web_search_enabled": false,
  "web_search_source": "bing"
}
```

### PUT /api/agent/embedding-config — 更新配置
- **请求体**:`{ "user_id"(必填), "embedding_type", "api_url", "api_key", "model", "customer_can_use_kb", "visitor_web_search_enabled", "web_search_source" }`(除 user_id 外可选)
- **响应 200**:同上配置对象。
- **枚举**:`embedding_type` ∈ `openai / local`;`web_search_source` ∈ `bing / google`。

---

## 十三、提示词配置(平台级)

> 鉴权:`prompts` 权限。源码:[prompt_config_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/prompt_config_controller.go)。

### GET /api/agent/prompts — 获取所有提示词
- **query**:`user_id`
- **响应 200**:`{ "prompts": [{ "key", "content", "user_id", "created_at", "updated_at" }] }`

### PUT /api/agent/prompts — 更新单条提示词(仅管理员)
- **请求体**:`{ "user_id"(必填), "key"(必填), "content" }`
- **响应 200**:`{ "message": "保存成功" }`

---

## 十四、数据分析

### GET /api/agent/analytics/summary — 数据摘要
- **权限**:`analytics` + `X-User-Id`
- **query**:`from`、`to`(日期字符串,默认最近 7 天)
- **响应 200**
```json
{
  "start_date": "2026-07-28",
  "end_date": "2026-08-03",
  "total_conversations": 100,
  "total_messages": 500,
  "avg_response_time": 2.5,
  "engagement_rate": 0.85
}
```

---

## 十五、系统日志

> 鉴权:`logs` 权限 + `X-User-Id`(除前端上报外)。源码:[system_log_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/system_log_controller.go)。

### GET /api/agent/logs/api — 查询日志
- **query**:`from / to / level / category / event / source / conversation_id / keyword / page / page_size`
- **响应 200**
```json
{
  "total": 1000, "page": 1, "page_size": 50,
  "logs": [{ "id", "level", "category", "event", "message", "meta", "created_at" }]
}
```
- **日志级别**:`debug / info / warn / error / fatal`

### GET /api/agent/logs/min-level — 最低落库级别(读)
- **响应 200**:`{ "effective_min_level": "info", "env_min_level": "warn", "persisted_in_database": true }`

### PUT /api/agent/logs/min-level — 设置最低级别(写库生效)
- **请求体**:`{ "min_level": "debug" }`
- **响应 200**:`{ "ok": true, "effective_min_level": "debug" }`

### DELETE /api/agent/logs/min-level — 恢复为 .env 配置
- **响应 200**:`{ "ok": true, "effective_min_level": "warn" }`

### POST /api/agent/logs/frontend — 前端日志上报(无需鉴权)
- **请求体**
```json
{
  "level": "error",
  "category": "frontend",
  "event": "js_error",
  "trace_id": "...",
  "conversation_id": 12,
  "visitor_id": 1001,
  "message": "Uncaught TypeError: ...",
  "meta": { "url": "...", "stack": "..." }
}
```
- **响应 200**:`{ "ok": true }`

---

## 十六、访客接口(无需登录)

源码:[visitor_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/visitor_controller.go)。

### GET /api/visitor/online-agents — 在线客服列表
- **响应 200**:`{ "agents": [...] }`

### GET /api/visitor/widget-config — 访客小窗配置
- **响应 200**:配置对象(联网设置等,来自 EmbeddingConfig)。

### POST /api/visitor/analytics/widget-open — 打开小窗埋点
- **响应 200**:埋点结果。

---

## 十七、健康检查与指标

### GET /api/health — 健康检查
- **响应 200**:`{ "status": "healthy", "error": "" }`(异常时 503)

### GET /api/health/metrics — 性能指标
- **响应 200**:`{ "memory_usage_mb": ..., "cpu_percent": ..., "active_connections": ... }`

---

## 十八、知识库外部接口(预留)

> 当前为模拟实现,用于对接第三方知识库系统。源码:[kb_external_controller.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/controller/kb_external_controller.go)。

### GET /api/kb-external/health
- **响应 200**:`{ "status": "ok", "message": "...", "endpoints": [...] }`

### POST /api/kb-external/search
- **请求体**:`{ "query"(必填), "knowledge_base_id", "top_k", "threshold" }`
- **响应 200**:`{ "query", "results": [{ "id", "title", "content", "source", "score", "knowledge_base_id" }], "total" }`

### POST /api/kb-external/query
- **请求体**:`{ "query"(必填), "knowledge_base_id", "session_id", "top_k" }`
- **响应 200**:`{ "answer", "references": [...], "session_id", "query_time_ms" }`

### POST /api/kb-external/sync
- **请求体**:`{ "knowledge_base_id"(必填), "force" }`
- **响应 200**:`{ "knowledge_base_id", "force", "status": "pending", "message": "..." }`

---

## 十九、WebSocket 实时通信

源码:[websocket/handler.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/websocket/handler.go)、[client.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/websocket/client.go)。

### 连接地址
```
ws://<HOST>:18080/ws?conversation_id=<id>&is_visitor=<true|false>&agent_id=<uid>&ws_token=<token>
```
> 经 8063 反代时需把 `/ws` 也转发到 18080(WebSocket 升级)。

### 鉴权
- **访客**:`is_visitor=true`(默认),只需 `conversation_id`。
- **客服**:`is_visitor=false`,需 `agent_id` + `ws_token`(登录时签发,24h);后端校验 token 与用户角色(`admin/agent`)。

### 连接参数
| 参数 | 必填 | 说明 |
|------|------|------|
| conversation_id | 是 | 会话 ID |
| is_visitor | 否 | 默认 true |
| agent_id | 客服必填 | 客服用户 ID |
| ws_token | 客服必填 | 登录返回的 token |

### 协议约定
- 心跳:服务端 `pingPeriod = 54s`,`pongWait = 60s`,`writeWait = 10s`;客户端需响应 pong。
- 最大消息:512KB。
- 客户端入站消息结构:`{ "type": "...", "data": {…} }`(详见 [client.go:12](file:///home/ubuntu/ai-customer/AI-CS-master/backend/websocket/client.go#L12-L15))。
- 新消息、已读状态等业务事件由后端通过该连接推送给会话内的对端。

---

## 二十、数据模型

### User
```json
{
  "id": 1,
  "username": "admin",
  "password": "(bcrypt, 出于安全不应回传明文)",
  "role": "admin",            // admin / agent
  "permissions": "[\"chat\",\"knowledge\"]",  // JSON 字符串
  "avatar_url": "/uploads/...",
  "nickname": "管理员",
  "email": "admin@example.com",
  "receive_ai_conversations": true,
  "created_at": "...",
  "updated_at": "..."
}
```

### Conversation
```json
{
  "id": 12,
  "conversation_type": "visitor",   // visitor / internal
  "visitor_id": 1001,
  "agent_id": 1,
  "status": "open",                 // open / closed
  "website": "...", "referrer": "...",
  "browser": "Chrome", "os": "Windows", "language": "zh-CN",
  "ip_address": "...", "location": "...",
  "email": "", "phone": "", "notes": "",
  "last_seen_at": "...",
  "chat_mode": "ai",                // human / ai
  "ai_config_id": 3,
  "created_at": "...", "updated_at": "...",
  "unread_count": 2,
  "last_message": { /* Message 摘要 */ }
}
```

### Message
```json
{
  "id": 101,
  "conversation_id": 12,
  "sender_id": 1,            // 客服=用户ID;访客=0
  "sender_is_agent": true,
  "content": "...",
  "message_type": "user_message",   // user_message / system_message
  "chat_mode": "human",             // 发送时的会话模式
  "is_read": false,
  "read_at": null,
  "file_url": null, "file_type": null, "file_name": null,
  "file_size": null, "mime_type": null,
  "created_at": "..."
}
```

---

## 二十一、典型对接流程

1. **客服登录** → `POST /api/login` → 拿 `user_id`、`ws_token`、`permissions`。
2. **后续请求**统一带 `X-User-Id: <user_id>`。
3. **建立 WebSocket**(客服):`ws://<HOST>:18080/ws?conversation_id=X&is_visitor=false&agent_id=<uid>&ws_token=<token>`。
4. **拉会话列表** → `GET /api/conversations?user_id=<uid>&type=visitor&status=open`。
5. **收发消息**:HTTP `POST /api/messages` 发送;WebSocket 接收对端推送。
6. **上传附件** → `POST /api/messages/upload`,拿到 `file_url` 后在 `POST /api/messages` 里带上文件字段。
7. **知识库/文档/FAQ/配置/日志/报表**:按需调用对应分组接口,均需相应权限键。

---

## 二十二、错误码速查

| HTTP | 含义 | 常见原因 |
|------|------|----------|
| 400 | 参数错误 | 必填缺失、格式非法 |
| 401 | 未授权 | 缺 `X-User-Id` / `ws_token` 失效 |
| 403 | 无权限 | 权限键不足、知识库开关关闭、非会话创建者 |
| 404 | 不存在 | 资源 ID 无效 |
| 500 | 服务端错误 | DB / Milvus / 嵌入服务异常 |
| 503 | 健康检查失败 | 依赖服务不可用 |

---

> 文档基于源码生成,路由权威来源:[backend/router/router.go](file:///home/ubuntu/ai-customer/AI-CS-master/backend/router/router.go)。
> 如接口行为与文档不符,以 controller 实际实现为准。
