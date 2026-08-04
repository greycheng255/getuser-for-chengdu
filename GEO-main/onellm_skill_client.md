# onellm 多媒体生成 API 调用指南

> 给应用开发者：怎么通过 HTTP 接口调用 onellm 的图片/视频/音频/TTS 生成能力。底层架构看 [onellm_extend.md](onellm_extend.md)，本文只讲怎么用。

---

## 1. 这是什么

onellm 把 AI6700（灵壳AI）的图片 / 视频 / 音频 / TTS / 音乐生成统一封装成两种调用模式：

| 入口 | 行为 | 用途 |
|---|---|---|
| `POST /v1/media/generations` | **异步（默认）**：提交任务、冻结预扣费、立刻返回 `task_id`（HTTP 202）| 视频等长任务，客户端自己轮询 |
| `POST /v1/media/generations/sync` | **同步**：提交+阻塞轮询+完成时返回结果 | 短任务（图片、短音频），不想自己写轮询 |
| `GET  /v1/media/tasks/{task_id}` | 查询任务状态；**任务终态时驱动结算/退款** | 异步路径的标准轮询接口 |

异步路径采用**提交时预扣费**：
1. 提交任务时按 `model_info` 估算 credits → 冻结到调用方钱包（team_id 维度）
2. 客户端轮询状态接口
3. 状态接口检测到 `is_final=true` 时：成功就按上游真实 cost × markup 结算；失败就全额退还

异步返回的轻量任务收据是 `MediaTaskAccepted`（见 §2.1）；同步和"轮询到终态"的结果都是 `MediaResponse`（见 §6）。

---

## 2. Quick Start

### 2.1 异步（推荐 / 默认）

```bash
# 1) 提交：立即返回 task_id，预扣费已冻结
curl -X POST http://212.129.240.112:4000/v1/media/generations \
  -H "Authorization: Bearer $ONELLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ai6700/doubao-seedream-4-5-251128",
    "prompt": "a cat reading a book in a library, oil painting",
    "size": "2048x2048"
  }'
```

响应（HTTP **202 Accepted**）：

```json
{
  "object": "media.task",
  "task_id": "12345",
  "model": "doubao-seedream-4-5-251128",
  "media_type": "image",
  "status": "pending",
  "estimated_cost": 0.55,
  "price_markup": 1.1,
  "billing_method": "按张",
  "tenant_id": "team-abc",
  "created": 1716000000,
  "provider": "ai6700"
}
```

```bash
# 2) 轮询：客户端自己控制节奏，建议 5-10s 一次
curl http://212.129.240.112:4000/v1/media/tasks/12345 \
  -H "Authorization: Bearer $ONELLM_API_KEY"
```

任务未结束时返回上游原始 status（含 `progress`、`status_group` 等）。**首次返回 `is_final=true` 时**响应里就包含完整 `MediaResponse` 结构（URL、真实 cost、settled=true 标记）；重复轮询不会重复扣费（幂等）。

### 2.2 同步（短任务直接拿结果）

```bash
curl -X POST http://212.129.240.112:4000/v1/media/generations/sync \
  -H "Authorization: Bearer $ONELLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ai6700/doubao-seedream-4-5-251128",
    "prompt": "a cat reading a book in a library, oil painting",
    "size": "2048x2048"
  }'
```

完整 `MediaResponse`（节选）：

```json
{
  "object": "media.task",
  "task_id": "12345",
  "model": "doubao-seedream-4-5-251128",
  "media_type": "image",
  "status": "completed",
  "data": [{"url": "https://cdn.example.com/img/abc.png", "result_type": "image"}],
  "cost": 0.22,
  "raw_cost": 0.2,
  "price_markup": 1.1,
  "channel_group": "default分组",
  "duration_seconds": 30,
  "provider": "ai6700"
}
```

> 同步路径同样做预扣费 + 完成时结算，所以余额不足会在提交阶段直接 402 返回，不会浪费上游算力。

---

## 3. 鉴权

HTTP header：`Authorization: Bearer <your-onellm-key>`。

onellm proxy 自己持有上游 AI6700 的 key，你只用关心 onellm 自己的 key。

---

## 4. 三种 modality 的实战示例

### 4.1 图片生成

```bash
curl -X POST http://212.129.240.112:4000/v1/media/generations \
  -H "Authorization: Bearer $ONELLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ai6700/doubao-seedream-4-5-251128",
    "prompt": "赛博朋克风格的东京街景，夜晚下雨",
    "size": "2048x2048",
    "n": 2,
    "aspect_ratio": "16:9",
    "images": "https://your-cdn.com/ref.jpg"
  }'
```

返回的 `data` 数组里每个元素对应一张图（多张时多条）：

```json
{
  "data": [
    {"url": "https://cdn/.../1.png", "result_type": "image"},
    {"url": "https://cdn/.../2.png", "result_type": "image"}
  ]
}
```

**支持的图片模型**（举例，完整列表见配置）：
- `doubao-seedream-4-5-251128` / `doubao-seedream-5-0-260128` — 即梦 4.5/5.0
- `gemini-3-pro-image-preview` — Nano Banana Pro
- `gpt-image-2-all` / `gpt-image-1.5-all` — GPT Image
- `grok-4.1-image` / `grok-4.2-image` — Grok Image

### 4.2 视频生成

```bash
curl -X POST http://212.129.240.112:4000/v1/media/generations \
  -H "Authorization: Bearer $ONELLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ai6700/doubao-seedance-1-5-pro-251215",
    "prompt": "一只猫在草地上奔跑，电影感运镜",
    "size": "1920x1080",
    "seconds": 8,
    "input_reference": "https://your-cdn.com/firstframe.jpg",
    "ratio": "16:9",
    "generate_audio": "true",
    "timeout": 1800
  }'
```

返回的 `data[0].url` 是视频 mp4 下载地址；`duration_seconds` 是**生成耗时**（不是视频时长）。

**视频任务默认 timeout 是 900 秒**（15 分钟），生成视频本来就慢。需要更长可以传 `"timeout": 1800`。

**支持的视频模型**：
- `doubao-seedance-1-5-pro-251215` — 即梦 3.5 Pro
- `grok-video-3` / `grok-video-3-plus` — Grok Video
- `hailuo-2.3` — 海螺
- `happyhorse-t2v` / `happyhorse-i2v` / `happyhorse-r2v` — 文/图/参考生视频

### 4.3 TTS / 音频

```bash
curl -X POST http://212.129.240.112:4000/v1/media/generations \
  -H "Authorization: Bearer $ONELLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ai6700/doubao-tts-2.0",
    "prompt": "今天天气真好，我们一起去公园散步吧",
    "type": "audio",
    "speed": 1.25,
    "voice": "BV001_streaming",
    "parameters": {
      "emotion": "happy",
      "emotion_scale": "4"
    }
  }'
```

返回的 `data[0].url` 是 mp3 下载地址。

**支持的音频模型**：
- `doubao-tts-2.0` — 豆包语音合成 2.0（100+ 音色、多语言）
- `gemini-2.5-pro-preview-tts` / `gemini-3.1-flash-tts-preview` — Gemini TTS

> 注意：onellm 的音频统一走 `/v1/media/generations`，返回 URL，你自己下载。

---

## 5. 请求参数

### 5.1 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | string | ✅ | 形如 `ai6700/<model-name>` |
| `prompt` | string | ✅ | 文本提示词 |
| `type` | string |  | `image` / `video` / `audio` / `tts` / `music`。当模型未注册到 `model_list` 时显式指定 |
| `parameters` | object |  | AI6700-native 参数。**最高优先级**，会覆盖自动映射结果 |
| `count` / `n` | int |  | 生成数量（图片用） |
| `timeout` | float |  | 轮询总超时（秒）。默认 600；视频建议 900–1800 |
| `poll_interval` | float |  | 轮询间隔（秒），默认 5 |

### 5.2 OpenAI 风格参数——会被自动映射

| 你传 | 视频映射到 | 图片映射到 | 音频映射到 |
|---|---|---|---|
| `size` | `params.resolution`（`1280x720→720p`，`3840x2160→4K`...）| `params.size`（`1024x1024→1K`，`2048x2048→2K`，`4096x4096→4K`）| —— |
| `seconds` | `params.audio_duration` | —— | —— |
| `input_reference` / `image` / `image_url` | `params.images` | `params.images` | —— |
| `n` / `num_images` | —— | top-level `count` | —— |
| `speed` | —— | —— | `params.speech_rate`（连续浮点 → 离散吸附） |
| `voice` | —— | —— | `params.voice`（透传） |
| `quality` / `style` / `response_format` | （丢弃） | （丢弃） | （丢弃） |

### 5.3 AI6700 模型私有参数——直接透传

任何不在上表的 key 会被原样放进 AI6700 的 `params` 对象。例如：
- 视频：`ratio` / `generate_audio` / `audio_duration`（直接传也行）
- 图片：`aspect_ratio` / `quality_level`
- 音频：`emotion` / `emotion_scale` / `model_version`

### 5.4 优先级

`parameters` 显式指定的 key **永远赢**：

```json
{
  "model": "ai6700/m",
  "prompt": "...",
  "size": "1280x720",
  "parameters": {"resolution": "1080p"}
}
```

上例中 `size` 会自动映射成 `resolution="720p"`，但 `parameters.resolution="1080p"` 覆盖之，最终 `1080p` 生效。

---

## 6. 响应：MediaResponse

```json
{
  "object": "media.task",
  "task_id": "12345",
  "model": "grok-video-3",
  "media_type": "video",
  "status": "completed",

  "data": [
    {"url": "https://cdn/abc.mp4", "result_type": "video"}
  ],

  "cost": 1.65,
  "raw_cost": 1.5,
  "price_markup": 1.1,

  "channel_group": "标准渠道",
  "duration_seconds": 42,
  "created": 1716000000,
  "completed_at": 1716000042,
  "provider": "ai6700",

  "raw_response": { "...": "上游 task-status 原始 JSON 全量留底" }
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| `object` | 永远是 `"media.task"` |
| `task_id` | 上游任务 ID（字符串） |
| `model` | provider 前缀已剥离 |
| `media_type` | `image` / `video` / `audio` / `tts` / `music` |
| `status` | 只返回 `completed` 状态的；失败会返回 4xx/5xx |
| `data[]` | 结果资产列表。图片多张时这里会有多条 |
| `cost` | 实际扣费（`raw_cost × price_markup`），单位为算力 |
| `raw_cost` | 上游真实计价 |
| `price_markup` | 加价系数 |
| `channel_group` | 上游实际走的通道 |
| `duration_seconds` | 从提交到完成的耗时（秒） |
| `created` / `completed_at` | unix 时间戳 |
| `raw_response` | 上游 task-status 原始 JSON 全量留底 |

**响应头**（proxy 自动加）：
- `x-litellm-response-cost: 1.65`
- `x-litellm-call-id: ...`
- `x-litellm-model-id: ...`

---

## 7. 上传参考图 / 首帧——必须公网 URL

AI6700 不托管文件。所有 `type=upload` 的参数（`images`、`input_reference`、`first_frame` 等）只接受 `http(s)://...` 形式的公网 URL。

```json
// ✅ OK
{
  "model": "ai6700/grok-video-3",
  "prompt": "...",
  "input_reference": "https://your-bucket.s3.amazonaws.com/ref.jpg"
}
```

下面这些会被拒绝（HTTP 400，发请求前就拦截）：

```text
/local/path.jpg
file:///x.jpg
data:image/png;base64,...
""（空字符串）
```

**推荐的上传链路**：
1. 用户上传 → 你的应用 → 临时对象存储（S3 / OSS / COS）
2. 拿到公网 URL（或预签名 URL，有效期足够覆盖生成时长，**视频建议 ≥ 30 分钟**）
3. 把 URL 放入请求体

---

## 8. 错误处理

所有失败都以 HTTP 4xx/5xx 返回，响应体形如：

```json
{
  "error": {
    "message": "上游任务失败：...",
    "type": "AI6700Error",
    "code": 502
  }
}
```

常见情况：

| status_code | 含义 | 怎么修 |
|---:|---|---|
| 400 | prompt 为空 / 上传不是 URL / model 找不到 provider | 看 `message` 字段，按提示修参数 |
| 401 | API key 缺失或无效；API key 没有 team_id/user_id 无法计费 | 检查 `Authorization` header；确认 key 已挂到某个 team |
| 402 | **积分不足**（预扣费失败） | 看 `message` 里"当前可用 X C，需要 Y C"，给 team 充值 |
| 502 | 上游任务失败 / 缺 `result_url` | 看 `message` 里上游 `error` 字段；可能是模型本次失败，重试 |
| 504 | 同步路径轮询超时 | 改用异步路径（`POST /v1/media/generations`）+ 自己轮询；或加大 `timeout` |

504 / 异步路径超时时，任务在上游可能还在跑，可以用第 9 节的查询接口拿 `task_id` 单独查；查到 `is_final=true` 时也会自动结算/退款。

---

## 9. 查询单个任务状态（异步路径必读）

```bash
curl http://212.129.240.112:4000/v1/media/tasks/12345 \
  -H "Authorization: Bearer $ONELLM_API_KEY"
```

**未结束**时返回 AI6700 原始 task-status JSON：

```json
{
  "task_id": 12345,
  "status": "生成中",
  "status_group": "处理中",
  "is_final": false,
  "progress": "60%",
  "result_url": ""
}
```

**首次返回 `is_final=true`** 时，proxy 同时做了两件事：
1. 触发钱包结算（成功 → 真实 cost 扣费 + 释放冻结额度；失败 → 全额退还）
2. 把上游 status 转换成完整 `MediaResponse` 返回（同 §6 结构 + 增 `settled: true` / `refunded: true` 字段）

成功示例（首次终态查询响应）：
```json
{
  "object": "media.task",
  "task_id": "12345",
  "model": "doubao-seedream-4-5-251128",
  "media_type": "image",
  "status": "completed",
  "data": [{"url": "https://cdn/.../abc.png", "result_type": "image"}],
  "cost": 0.55,
  "raw_cost": 0.5,
  "price_markup": 1.1,
  "channel_group": "default分组",
  "duration_seconds": 30,
  "provider": "ai6700",
  "settled": true
}
```

失败示例：
```json
{
  "task_id": 12345,
  "status": "生成失败",
  "status_group": "失败",
  "is_final": true,
  "error": "上游模型超时",
  "settled": false,
  "refunded": true
}
```

**幂等**：重复查同一个终态 task，钱包数字不会再变，但响应结构每次都给完整 `MediaResponse`。客户端拿到 `is_final=true` 就可以停止轮询。

> 注意：只有通过 onellm 提交的任务（pre_deduct 留下了 tx 记录）才会触发结算/退款。直接打上游 API 提交的任务，这个接口只透传 status 不动钱包。

---

## 10. 怎么找到能用的模型

### 10.1 查询本地已注册的媒体模型

onellm 暴露三个查询接口，**只看本地 `model_list`（config.yaml / DB）里注册过的媒体模型**——即 `model_info.ai6700_media_type` 有值的 deployment。不直接代理上游，所以未注册的模型即使上游存在也查不到（返 404）。

```bash
# 全部已注册的媒体模型（按 base name 去重；tier1/tier2 折叠为同一条，附 channel_count）
curl 'http://212.129.240.112:4000/v1/media/models' \
  -H "Authorization: Bearer $ONELLM_API_KEY"

# 单个模型的元数据（来自 model_info：display_name / type / channel_group / option_prices 等）
curl 'http://212.129.240.112:4000/v1/media/models/grok-video-3' \
  -H "Authorization: Bearer $ONELLM_API_KEY"

# 该模型在本地注册的所有通道（tier1/tier2/...）的价格信息
curl 'http://212.129.240.112:4000/v1/media/models/grok-video-3/pricing' \
  -H "Authorization: Bearer $ONELLM_API_KEY"
```

返回体形如：

```json
// /v1/media/models
{
  "object": "list",
  "data": [
    {"name": "grok-video-3", "display_name": "Grok Video 3", "type": "video", "mode": "video_generation", "channel_count": 3}
  ]
}

// /v1/media/models/{model}/pricing
{
  "model": "grok-video-3",
  "type": "video",
  "channels": [
    {"name": "grok-video-3", "channel_group": "默认", "billing_method": "按秒", "base_price": 0.15, "price_markup": 1.1, "option_prices": [...], "is_active": true},
    {"name": "grok-video-3-tier1", "channel_group": "便宜通道", ...}
  ]
}
```

---

### 10.4 钱包 / 预扣费速记

异步路径强制走钱包，三条规则：

1. **谁付钱**：以调用 API 的 key 的 `team_id` 为钱包主体（无 team 时 fallback 到 `user_id`）。钱包表是 `app.credit_wallet`：`gift_balance` / `paid_balance` / `frozen_amount`。
2. **什么时候动账**：
   - 提交时：按 `model_info.base_price × option_multipliers × markup × quantity` 估算（最小 `0.1 C`），冻结到 `frozen_amount`。
   - `is_final=true` 第一次被查到时：成功 → gift 优先扣再扣 paid + 释放 frozen；失败 → 释放 frozen，不扣。
3. **额度估算保守原则**：视频 `duration='auto'` 默认按 15 秒预扣；实际 cost 由上游返回的 `cost` 决定，结算时多退少补。

流水查询走 `app.credit_transaction` 表（每个任务有 `pre_deduct` + `consumption`/`settlement` 或 `refund` 几条），可在 DB 直查或后续走管理 UI。

---

## 11. 常见陷阱

| 现象 | 原因 | 解决 |
|---|---|---|
| `Cannot infer media_type for 'ai6700/xxx'` | 模型未在 `model_list` 注册 | 加 `"type": "image"`（或 video/audio） |
| 提交后立马拿 task_id，但没 URL | 默认是异步！只返回 receipt | 用 `/v1/media/tasks/{task_id}` 轮询；想阻塞等结果调 `/sync` |
| 视频任务 504 超时（同步路径） | 复杂场景生成超过 900s | 改用异步路径自己轮询；或显式传 `"timeout": 1800` |
| HTTP 402 `积分不足` | 钱包余额或额度不够 | 给 team 充值；或确认 API key 已挂到有余额的 team |
| 上传参数报 400 | 传了本地路径 / base64 / `file://` | 必须公网 URL |
| `response_format=mp3` 没生效 | OpenAI 标准 key 被丢弃 | 用 `"parameters": {"output_format": "mp3"}` 透传 |
| `voice="alloy"` 报错 | OpenAI voice ID 不通用 | 用 AI6700 模型自带的 voice ID（如豆包的 `BV001_streaming`） |
| 多 tier 模型选哪个 | tier1 是 active 中最便宜 | 通常不需要自己选 tier，用裸名让 router 选 |
| `cost=0.0` | 上游本次没返回 cost（罕见，通常是失败任务）| 看 `raw_response.error` |
| 任务完成但 `settled=false` | 上游 task 不是通过 onellm 提交（无 pre_deduct 记录）| 这是正常的；通过 onellm 提交的任务永远会 settled |

---
