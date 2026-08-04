# 视频/音频解析服务 API 文档

> 本文档基于 [main.py](../main.py) 与 [app/models.py](../app/models.py) 实际代码整理，与线上服务保持一致。
> 线上交互式文档（Swagger）：<http://122.51.51.177:8002/docs>

## 目录

- [概览](#概览)
- [通用约定](#通用约定)
- [枚举值](#枚举值)
- [公开接口](#公开接口)
  - [1. 创建视频解析任务](#1-创建视频解析任务)
  - [2. 上传音频创建 ASR 任务](#2-上传音频创建-asr-任务)
  - [3. 查询任务状态与结果](#3-查询任务状态与结果)
  - [4. 批量查询任务](#4-批量查询任务)
  - [5. 查询任务进度](#5-查询任务进度)
  - [6. 删除任务](#6-删除任务)
  - [7. 导出字幕](#7-导出字幕)
  - [8. 字幕关键词搜索](#8-字幕关键词搜索)
  - [9. 音频文件列表](#9-音频文件列表)
  - [10. 获取音频文件](#10-获取音频文件)
  - [11. 视频流代理](#11-视频流代理)
  - [12. 健康检查](#12-健康检查)
  - [13. 服务信息](#13-服务信息)
- [管理接口（内部）](#管理接口内部)
- [数据模型](#数据模型)
- [典型调用流程](#典型调用流程)

---

## 概览

| 项目 | 值 |
|---|---|
| Base URL | `http://122.51.51.177:8002` |
| API 前缀 | `/api/v1` |
| 鉴权 | 无（CORS 允许全部来源） |
| 请求体格式 | `application/json`（上传接口为 `multipart/form-data`） |
| 交互式文档 | `/docs`（Swagger）、`/redoc`、`/openapi.json` |

支持的平台：抖音（`/video/`、`/jingxuan?modal_id=`、短链 `v.douyin.com`）、小红书（`xiaohongshu.com/explore/`）、B 站（`bilibili.com/video/`）。

## 通用约定

### 统一响应格式

除文件下载类接口外，所有接口返回统一结构：

```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

- `code = 0` 表示成功；非 0 表示业务错误。
- HTTP 状态码：`200` 成功，`400` 参数错误，`404` 资源不存在，`500` 服务异常。

### 错误响应

参数错误或服务异常时返回（FastAPI 默认格式）：

```json
{ "detail": "错误描述" }
```

## 枚举值

### TaskType 任务类型

| 值 | 说明 |
|---|---|
| `video` | 视频解析（默认） |
| `audio` | 音频识别 |
| `image` | 图片 |
| `webpage` | 网页 |

### TaskStatus 任务状态

| 值 | 说明 |
|---|---|
| `pending` | 排队中 |
| `processing` | 处理中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |

### Priority 优先级

| 值 | 说明 |
|---|---|
| `3` | 低 |
| `5` | 普通（默认） |
| `8` | 高 |

### ParseOptions 解析选项

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `extract_audio` | bool | `false` | 是否提取音频 |
| `thumbnail_quality` | string | `"high"` | 封面质量 |
| `language` | string | `"zh-CN"` | 识别语言 |
| `generate_summary` | bool | `true` | 是否生成摘要 |

---

## 公开接口

### 1. 创建视频解析任务

提交一个视频 URL，异步解析（提取媒体、字幕、摘要等）。

```
POST /api/v1/parse/tasks
```

**请求体**（`CreateTaskRequest`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `url` | string | 是 | 视频 URL（支持抖音/小红书/B站） |
| `type` | TaskType | 否 | 默认 `video` |
| `priority` | Priority | 否 | 默认 `5` |
| `callback_url` | string | 否 | 任务完成后回调通知地址 |
| `options` | ParseOptions | 否 | 解析选项 |

**示例**

```bash
curl -X POST http://122.51.51.177:8002/api/v1/parse/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.douyin.com/video/7123456789012345678",
    "options": { "generate_summary": true, "language": "zh-CN" }
  }'
```

**响应**（`CreateTaskResponse`）

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "task_id": "task_20260802103045_abc123de",
    "status": "pending",
    "created_at": 0,
    "estimated_duration": 30
  }
}
```

**错误**

- `400`：URL 无法识别（返回支持的平台格式说明）。

---

### 2. 上传音频创建 ASR 任务

直接上传音频文件创建语音识别任务。

```
POST /api/v1/parse/audio
```

**请求体**（`multipart/form-data`）

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `file` | file | 是 | — | 音频文件，支持 MP3/WAV/OGG/AAC/M4A |
| `priority` | int | 否 | `5` | 优先级 1-10 |
| `language` | string | 否 | `"zh"` | 识别语言 |
| `generate_summary` | bool | 否 | `true` | 是否生成摘要 |

**示例**

```bash
curl -X POST http://122.51.51.177:8002/api/v1/parse/audio \
  -F "file=@record.mp3" \
  -F "language=zh" \
  -F "generate_summary=true"
```

**响应**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "task_id": "task_20260802103100_fedcba98",
    "status": "pending",
    "file_name": "record.mp3",
    "file_size": 1024000,
    "estimated_duration": 30
  }
}
```

**错误**

- `400`：不支持的文件类型。

---

### 3. 查询任务状态与结果

查询单个任务的完整状态与解析结果。

```
GET /api/v1/parse/tasks/{task_id}
```

**路径参数**

| 参数 | 说明 |
|---|---|
| `task_id` | 任务 ID |

**示例**

```bash
curl http://122.51.51.177:8002/api/v1/parse/tasks/task_20260802103045_abc123de
```

**响应**（`TaskQueryResponse`，`data` 为 [`TaskResult`](#taskresult)）

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "task_id": "task_20260802103045_abc123de",
    "status": "completed",
    "type": "video",
    "progress": 100,
    "source": {
      "url": "https://www.douyin.com/video/7123456789012345678",
      "platform": "douyin",
      "title": "示例视频",
      "author": "作者",
      "duration": 60
    },
    "content": {
      "video_url": "https://...",
      "audio_url": "https://...",
      "formats": [
        { "quality": "720p", "url": "https://...", "size": 12.3, "format": "mp4", "width": 720, "height": 1280 }
      ],
      "content": "字幕合并后的全文内容",
      "subtitles": [
        { "content": "第一句字幕", "start_time": 0.0, "end_time": 5.2, "source": "qwen_asr" }
      ],
      "audio_files": [
        { "filename": "audio_abc123.mp3", "url": "/audio/audio_abc123.mp3", "full_url": "http://122.51.51.177:8002/audio/audio_abc123.mp3", "size": 1048576, "size_mb": 1.0 }
      ]
    },
    "summary": {
      "text": "视频内容摘要",
      "key_points": ["要点一", "要点二"],
      "generated_at": "2026-08-02T10:31:30"
    },
    "thumbnail": {
      "original": "https://...",
      "small": "https://...",
      "medium": "https://...",
      "large": "https://..."
    },
    "created_at": "2026-08-02T10:30:45",
    "completed_at": "2026-08-02T10:31:30",
    "updated_at": "2026-08-02T10:31:30"
  }
}
```

**说明**

- `content.content` 会将字幕文本拼接到视频描述后。
- `content.audio_files` 为 ASR 生成的音频文件（按 `asr_audio_path` 或 URL hash 匹配）。
- 任务未完成时 `content`/`summary`/`thumbnail` 可能为 `null`。

**错误**

- `404`：任务不存在。

---

### 4. 批量查询任务

一次性查询多个任务状态。

```
POST /api/v1/parse/tasks/batch
```

**请求体**（`BatchQueryRequest`）

```json
{ "task_ids": ["task_xxx", "task_yyy"] }
```

**示例**

```bash
curl -X POST http://122.51.51.177:8002/api/v1/parse/tasks/batch \
  -H "Content-Type: application/json" \
  -d '{"task_ids": ["task_20260802103045_abc123de"]}'
```

**响应**（`BatchQueryResponse`，`data` 为 [`TaskResult`](#taskresult) 数组）

```json
{
  "code": 0,
  "message": "success",
  "data": [ { "task_id": "task_20260802103045_abc123de", "status": "completed", "..." : "..." } ]
}
```

> 不存在的任务会被静默跳过（不报错，不返回）。

---

### 5. 查询任务进度

轻量级进度查询，适合轮询。

```
GET /api/v1/parse/tasks/{task_id}/progress
```

**示例**

```bash
curl http://122.51.51.177:8002/api/v1/parse/tasks/task_20260802103045_abc123de/progress
```

**响应**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "task_id": "task_20260802103045_abc123de",
    "status": "processing",
    "progress": 45,
    "updated_at": "2026-08-02T10:31:00"
  }
}
```

- `progress`：0-100。

**错误**

- `404`：任务不存在。

---

### 6. 删除任务

从数据库彻底删除任务及其结果。

```
DELETE /api/v1/parse/tasks/{task_id}
```

**示例**

```bash
curl -X DELETE http://122.51.51.177:8002/api/v1/parse/tasks/task_20260802103045_abc123de
```

**响应**

```json
{
  "code": 0,
  "message": "Task deleted successfully",
  "data": { "task_id": "task_20260802103045_abc123de" }
}
```

> 若任务正在处理中，仅删除数据库记录，已派发的后台处理不会被强制中断。

**错误**

- `404`：任务不存在。

---

### 7. 导出字幕

将任务字幕导出为文件下载。任务须为 `completed`。

```
GET /api/v1/parse/tasks/{task_id}/subtitles/export?format=txt
```

**查询参数**

| 参数 | 类型 | 默认 | 可选值 | 说明 |
|---|---|---|---|---|
| `format` | string | `txt` | `txt` / `srt` / `json` | 导出格式 |

**示例**

```bash
# 导出 SRT
curl -OJ "http://122.51.51.177:8002/api/v1/parse/tasks/task_xxx/subtitles/export?format=srt"
```

**响应**：文件流下载

| format | Content-Type | 文件名 |
|---|---|---|
| `txt` | `text/plain` | `subtitles_{task_id}.txt` |
| `srt` | `application/x-subrip` | `subtitles_{task_id}.srt` |
| `json` | `application/json` | `subtitles_{task_id}.json` |

**说明**

- `srt` 格式的时间轴为按句分割模拟生成（每句约 5 秒），非真实时间轴。
- `json` 格式包含 `task_id`、`video_info`、`content`、`subtitles` 完整结构。

**错误**

- `400`：任务未完成 / 不支持的格式。
- `404`：任务/结果/字幕不存在。

---

### 8. 字幕关键词搜索

在已完成任务的字幕和正文中搜索关键词，返回带上下文的高亮匹配。

```
GET /api/v1/parse/tasks/{task_id}/subtitles/search?keyword=关键词
```

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `keyword` | string | 是 | 搜索关键词 |

**示例**

```bash
curl "http://122.51.51.177:8002/api/v1/parse/tasks/task_xxx/subtitles/search?keyword=产品"
```

**响应**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "task_id": "task_xxx",
    "keyword": "产品",
    "total_matches": 2,
    "matches": [
      {
        "subtitle_index": 0,
        "language": "unknown",
        "keyword": "产品",
        "context": "前文**产品**后文",
        "position": 12
      },
      {
        "source": "content",
        "keyword": "产品",
        "context": "...**产品**...",
        "position": 5
      }
    ]
  }
}
```

- `context` 中关键词被 `**` 包裹高亮；上下文为关键词前后各 30 字符。
- `subtitle_index` 标识字幕段索引；`source: "content"` 标识正文匹配。

**错误**

- `400`：任务未完成 / 关键词为空。
- `404`：任务/结果不存在。

---

### 9. 音频文件列表

列出服务端 `audio_files` 目录下所有 `.mp3` 文件。

```
GET /api/v1/audio/files
```

**示例**

```bash
curl http://122.51.51.177:8002/api/v1/audio/files
```

**响应**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "total": 2,
    "files": [
      {
        "filename": "audio_abc123.mp3",
        "url": "/audio/audio_abc123.mp3",
        "full_url": "http://122.51.51.177:8002/audio/audio_abc123.mp3",
        "size": 1048576,
        "size_mb": 1.0,
        "created_at": "2026-08-02T10:31:00"
      }
    ]
  }
}
```

- 按创建时间倒序排列。

---

### 10. 获取音频文件

直接下载/播放指定音频文件。

```
GET /api/v1/audio/files/{filename}
```

**示例**

```bash
curl -OJ http://122.51.51.177:8002/api/v1/audio/files/audio_abc123.mp3
```

**响应**：`audio/mpeg` 文件流。

**错误**

- `404`：文件不存在。

---

### 11. 视频流代理

代理视频流，用于绕过抖音等 CDN 的防盗链（自动加 Referer/UA 头）。

```
GET /proxy/video?url=<原始视频URL>
```

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `url` | string | 是 | 原始视频 URL |

**示例**

```bash
curl "http://122.51.51.177:8002/proxy/video?url=https://v26-web.douyinvod.com/xxxx"
```

**响应**：流式视频内容（`StreamingResponse`）。

---

### 12. 健康检查

```
GET /health
```

**响应**

```json
{
  "status": "healthy",
  "service": "视频解析服务",
  "version": "1.0.0"
}
```

---

### 13. 服务信息

```
GET /
```

**响应**

```json
{
  "service": "视频解析服务",
  "version": "1.0.0",
  "docs": "/docs",
  "api_prefix": "/api/v1"
}
```

---

## 管理接口（内部）

> 以下接口供管理面板与 ASR 服务内部调用，**非对外公开接口**，调用前请评估影响。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin` | 管理面板 HTML 页面 |
| GET | `/api/v1/admin/tasks` | 任务列表，支持 `status` / `has_audio` / `no_subtitles` 过滤 |
| POST | `/api/v1/admin/tasks/{task_id}/retry` | 重试任务（仅 `failed`/`completed` 可重试） |
| DELETE | `/api/v1/admin/tasks` | **清空所有任务（危险操作）** |
| POST | `/api/v1/admin/tasks/{task_id}/asr_status` | 更新 ASR 状态（供 ASR 服务调用） |
| POST | `/api/v1/admin/tasks/{task_id}/subtitles` | 写入字幕（供 ASR 服务调用） |

**`asr_status` 请求体**

```json
{ "status": "processing", "increment_retry": false }
```

- `status`：`pending` / `processing` / `completed` / `failed`
- `increment_retry`：`true` 且 `status=failed` 时重试次数 +1
- `status=completed` 时联动将主任务状态置为 `completed`

**`subtitles` 请求体**

```json
{ "subtitles": [ { "start": 0, "end": 5, "content": "字幕文本", "source": "qwen_asr" } ] }
```

---

## 数据模型

### TaskResult

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 ID |
| `status` | TaskStatus | 任务状态 |
| `type` | TaskType | 任务类型 |
| `progress` | int | 进度 0-100 |
| `source` | SourceInfo | 来源信息 |
| `content` | ContentInfo | 解析内容 |
| `summary` | SummaryInfo | 摘要 |
| `thumbnail` | ThumbnailInfo | 封面 |
| `created_at` | datetime | 创建时间 |
| `completed_at` | datetime | 完成时间 |
| `updated_at` | datetime | 更新时间 |

### SourceInfo

| 字段 | 类型 | 说明 |
|---|---|---|
| `url` | string | 原始 URL |
| `platform` | string | 平台（douyin/xhs/bilibili） |
| `title` | string | 标题 |
| `author` | string | 作者 |
| `duration` | int | 时长（秒） |

### ContentInfo

| 字段 | 类型 | 说明 |
|---|---|---|
| `video_url` | string | 视频地址 |
| `audio_url` | string | 音频地址 |
| `formats` | MediaFile[] | 媒体格式列表 |
| `content` | string | 文本内容（含字幕合并） |
| `subtitles` | SubtitleInfo[] | 字幕列表 |
| `audio_files` | AudioFileInfo[] | ASR 音频文件 |

### MediaFile

| 字段 | 类型 | 说明 |
|---|---|---|
| `quality` | string | 画质（如 `720p`、`original`） |
| `url` | string | 文件 URL |
| `size` | float | 大小（MB） |
| `format` | string | 格式（mp4/jpg…） |
| `width` | int | 宽 |
| `height` | int | 高 |
| `bitrate` | int | 码率 |

### SubtitleInfo

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | string | 字幕文本 |
| `start_time` | float | 起始时间（秒） |
| `end_time` | float | 结束时间（秒） |
| `source` | string | 来源（如 `qwen_asr`） |

### AudioFileInfo

| 字段 | 类型 | 说明 |
|---|---|---|
| `filename` | string | 文件名 |
| `url` | string | 相对路径 `/audio/xxx.mp3` |
| `full_url` | string | 完整 URL |
| `size` | int | 大小（字节） |
| `size_mb` | float | 大小（MB） |

### SummaryInfo

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string | 摘要正文 |
| `key_points` | string[] | 要点列表 |
| `generated_at` | datetime | 生成时间 |

### ThumbnailInfo

| 字段 | 类型 | 说明 |
|---|---|---|
| `original` | string | 原图 |
| `small` | string | 小图 |
| `medium` | string | 中图 |
| `large` | string | 大图 |

---

## 典型调用流程

```bash
# 1. 创建任务
TASK_ID=$(curl -s -X POST http://122.51.51.177:8002/api/v1/parse/tasks \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.douyin.com/video/xxx"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['task_id'])")

# 2. 轮询进度
curl http://122.51.51.177:8002/api/v1/parse/tasks/$TASK_ID/progress

# 3. 获取完整结果
curl http://122.51.51.177:8002/api/v1/parse/tasks/$TASK_ID

# 4. 导出字幕
curl -OJ "http://122.51.51.177:8002/api/v1/parse/tasks/$TASK_ID/subtitles/export?format=srt"
```
