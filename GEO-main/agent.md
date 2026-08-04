# Agent API 接口文档

本文档描述了 `/api/v1/agent` 相关的 Agent 生成任务（图片、视频、音频生成）接口规范，内容与 `backend/app/api/v1/agent.py` 保持一致。
## 基础信息

- **Base URL**: `https://api.opennotebook.chat`
- **支持的任务类型 (`type`)**:
  - `image` / `imagegen` — 图片生成
  - `video` / `videogen` — 视频生成
  - `audio` / `tts` / `music` / `audiogen` — 音频 / 语音 / 音乐生成

### 鉴权说明

大多数请求需要传递 `Tenant ID` 用于积分扣除。优先级为：`body.tenant_id` > `X-Tenant-ID` Header > `tenant_id` Cookie > 系统默认值。

| 传递方式 | 示例 |
| :--- | :--- |
| 请求头 | `X-Tenant-ID: 29803cbb-10b0-49c1-ac49-1eb296cf9f36` |
| Cookie | `tenant_id=29803cbb-10b0-49c1-ac49-1eb296cf9f36` |
| Body 字段 | `"tenantId": "29803cbb-..."` 或 `"tenant_id": "29803cbb-..."` |

---

## 1. 获取可用模型列表

**`GET /models`**

返回所有可用的媒体生成模型及其参数定义，无需鉴权。

### 请求示例

```http
GET /api/v1/agent/models
```

### 响应示例

```json
{
  "models": [
    {
      "name": "midjourney",
      "type": "image",
      "label": "Midjourney V6",
      "description": "高质量图像生成模型，支持文生图和图生图。",
      "params": {
        "prompt":    { "type": "string", "description": "提示词", "required": true },
        "size":      { "type": "string", "description": "图片尺寸", "options": ["1024x1024", "16:9", "9:16", "3:4", "4:3"], "default": "1024x1024" },
        "image_url": { "type": "string", "description": "参考图（垫图）URL", "required": false }
      }
    },
    {
      "name": "gpt-image-2",
      "type": "image",
      "label": "GPT Image 2",
      "description": "OpenAI 最新一代图像生成模型，支持文生图与图生图。",
      "params": {
        "prompt":   { "type": "string", "description": "提示词", "required": true },
        "size":     { "type": "string", "options": ["1152x2048", "2048x1152", "2048x2048", "auto", "1024x1024", "1536x1024", "1024x1536", "2160x3840", "3840x2160"], "default": "auto" },
        "images":   { "type": "upload", "description": "上传1-10张参考图", "required": false },
        "quality":  { "type": "string", "options": ["auto", "high", "medium", "low"], "default": "auto" }
      }
    },
    {
      "name": "kling-v1",
      "type": "video",
      "label": "Kling V1",
      "description": "先进的视频生成模型，支持文本/图片生成动态视频。",
      "params": {
        "prompt":    { "type": "string", "description": "提示词", "required": true },
        "duration":  { "type": "number", "options": [5, 10], "default": 5 },
        "image_url": { "type": "string", "description": "首帧参考图URL", "required": false }
      }
    },
    {
      "name": "suno-v3",
      "type": "music",
      "label": "Suno V3",
      "description": "强大的音乐与音频生成模型，支持自定义风格。",
      "params": {
        "prompt":   { "type": "string", "description": "歌词或提示词", "required": true },
        "is_music": { "type": "boolean", "default": true },
        "tags":     { "type": "string", "description": "音乐风格标签", "required": false }
      }
    }
  ]
}
```

---

## 2. 创建生成任务

**`POST /generate`**

提交一个新的生成任务。后端先预扣积分，然后在后台异步执行 LangGraph 工作流，并立即返回 `task_id`。

### 请求头

| Header | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `X-Tenant-ID` | string | 否 | 租户 ID（也可通过 Body 或 Cookie 传递） |

### 请求体 (JSON)

| 字段 | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `model` | string | **是** | 模型名称，如 `midjourney`、`gpt-image-2`、`kling-v1`、`suno-v3` |
| `prompt` | string | **是** | 提示词或描述文本 |
| `workspaceId` / `workspace_id` | string | **是** | 当前工作区 ID |
| `type` | string | 否 | 任务类型（不传时根据 `model` 自动推断） |
| `params` | object | 否 | 模型专属参数（支持 camelCase / snake_case） |
| `count` | integer | 否 | 生成数量，默认 `1` |
| `tenantId` / `tenant_id` | string | 否 | 租户 ID |

> **`params` 中的 camelCase 别名**：`modelId` → `model_id`，`modelName` → `model_name`，`imageUrl` → `image_url`，`isMusic` → `is_music`。两种写法均可，后端自动归一化。

### 请求示例（图片生成 — Midjourney）

```http
POST /api/v1/agent/generate
Content-Type: application/json
X-Tenant-ID: 29803cbb-10b0-49c1-ac49-1eb296cf9f36

{
  "type": "image",
  "model": "midjourney",
  "prompt": "a beautiful mountain landscape at sunset",
  "params": {
    "size": "16:9",
    "image_url": "https://example.com/ref.png"
  },
  "workspaceId": "1e324609-62bd-4593-81bd-09679a1da76d"
}
```

### 请求示例（图片生成 — GPT Image 2）

```http
POST /api/v1/agent/generate
Content-Type: application/json
X-Tenant-ID: 29803cbb-10b0-49c1-ac49-1eb296cf9f36

{
  "model": "gpt-image-2",
  "prompt": "a futuristic city skyline, cyberpunk style",
  "params": {
    "size": "2048x1152",
    "quality": "high"
  },
  "workspaceId": "1e324609-62bd-4593-81bd-09679a1da76d"
}
```

### 响应示例

**成功 `200 OK`**

```json
{
  "code": 200,
  "msg": "提交成功",
  "data": {
    "task_id": "fd019938-5c96-4877-a4a8-cea23bd3bac7"
  }
}
```

**积分不足 `402 Payment Required`**

```json
{
  "error": "INSUFFICIENT_CREDITS",
  "message": "积分不足"
}
```

**参数错误 `400 Bad Request`**

```json
{
  "detail": "Missing workspace_id"
}
```

**不支持的类型 `404 Not Found`**

```json
{
  "detail": "Unsupported agent type: xxx"
}
```

---

## 3. 查询任务状态

**`GET /status`**

轮询获取任务的执行状态、进度及生成结果。

### 请求参数

| 参数 | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `task_id` | string (Query) | **是** | 创建任务时返回的 `task_id` |

### 请求示例

```http
GET /api/v1/agent/status?task_id=fd019938-5c96-4877-a4a8-cea23bd3bac7
```

### 响应字段说明

| 字段 | 类型 | 描述 |
| :--- | :--- | :--- |
| `task_id` | string | 任务 ID（UUID） |
| `status` | string | 当前状态：`running` \| `completed` \| `error` |
| `is_final` | boolean | `true` 表示任务终止（成功或失败），**此时停止轮询** |
| `progress` | string | 进度百分比，如 `"10%"`、`"100%"` |
| `result_url` | string \| null | 生成结果的资源 URL（完成后非空） |
| `result_type` | string | 结果媒体类型，与请求时的 `type` 一致 |
| `cost` | number | 本次任务实际消耗积分（完成后为精确值，进行中为预估值） |
| `error` | string | 错误信息（无错误时为空字符串 `""`） |

### 响应示例（进行中）

```json
{
  "code": 200,
  "data": {
    "task_id": "fd019938-5c96-4877-a4a8-cea23bd3bac7",
    "status": "running",
    "is_final": false,
    "progress": "10%",
    "result_url": null,
    "result_type": "image",
    "cost": 5.0,
    "error": ""
  }
}
```

### 响应示例（已完成）

```json
{
  "code": 200,
  "data": {
    "task_id": "70921017-5d0b-47dd-9f2c-2e12f65defa1",
    "status": "completed",
    "is_final": true,
    "progress": "100%",
    "result_url": "https://cos.example.com/uploads/2026/05/04/image.png",
    "result_type": "image",
    "cost": 5.0,
    "error": ""
  }
}
```

### 响应示例（失败）

```json
{
  "code": 200,
  "data": {
    "task_id": "fd019938-5c96-4877-a4a8-cea23bd3bac7",
    "status": "error",
    "is_final": true,
    "progress": "10%",
    "result_url": null,
    "result_type": "image",
    "cost": 0.0,
    "error": "Missing model_id"
  }
}
```

**任务不存在 `404 Not Found`**

```json
{
  "detail": "Record not found"
}
```

---

## 轮询建议

- 建议每 **5 秒**轮询一次（对应后端 `POLL_INTERVAL_SECONDS = 5`）。
- 最多轮询 **240 次**（约 20 分钟，对应 `MAX_POLL_ATTEMPTS = 240`）。
- 当 `is_final == true` 时立即停止轮询。

---

## 工作流说明

`POST /generate` 成功后，后端按以下流程在后台执行：

```
创建 DB 记录 (status=running)
    → 预扣积分 (pre_deduct)
    → 异步执行 LangGraph 工作流
        ├── IMAGE_TYPES  → imagegen_workflow_graph
        ├── VIDEO_TYPES  → videogen_workflow_graph
        └── AUDIO_TYPES  → audiogen_workflow_graph
    → 工作流失败时退款 (refund_credits) + 更新 status=error
    → 工作流成功时结算积分 + 更新 status=completed + result_data
```

传入工作流的 `state_input` 统一使用 **snake_case**：

```python
{
  "prompt":            "...",
  "record_id":         "uuid",
  "workspace_id":      "uuid",
  "model_id":          "midjourney",
  "model_name":        "Midjourney V6",
  "extra_params":      { "size": "1024x1024" },
  "tenant_id":         "uuid",
  "estimated_credits": 5.0
}
```
