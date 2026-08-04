# API 能力文档 - ai.hropenai.cn

> 自动生成时间: 2026-05-18
> 平台地址: https://ai.hropenai.cn
> API Base URL: https://api.lk888.ai/api

---

## 认证方式

所有接口使用 Bearer Token 认证：

```
Authorization: Bearer {API Key}
```

**API Key**: `sk-099e46fe8c0761992b84268f741db298ae44cebe1f216086`
**存储位置**: `/home/ubuntu/GEO/geo_system/backend/ai_service.py`

---

## 可用模型列表

### 聊天模型 (Chat)

| 模型名称 | 显示名称 | 类型 | API格式 | 端点 |
|---------|---------|------|---------|------|
| gpt-5.4 | GPT-5.4 | chat | openai | /v1/chat/completions |
| gpt-5.5 | GPT-5.5 | chat | openai | /v1/chat/completions |
| gpt-5.5-xhigh | GPT-5.5 深度推理 | chat | openai | /v1/chat/completions |
| gpt-5.5-high | GPT-5.5 高推理 | chat | openai | /v1/chat/completions |
| gpt-5.5-medium | GPT-5.5 中推理 | chat | openai | /v1/chat/completions |
| gpt-5.5-low | GPT-5.5 低推理 | chat | openai | /v1/chat/completions |
| gpt-5.3-chat-latest | GPT-5.3 对话 | chat | openai | /v1/chat/completions |
| claude-opus-4-7 | opus-4-7 | chat | anthropic | /v1/messages |
| claude-opus-4-6 | opus-4-6 | chat | anthropic | /v1/messages |
| claude-sonnet-4-6 | sonnet-4-6 | chat | anthropic | /v1/messages |
| claude-opus-4-5-20251101 | opus-4-5 | chat | anthropic | /v1/messages |
| gemini-3.1-pro-preview | Gemini 3.1 Pro | chat | gemini | /v1beta/models/{model}:{action} |
| gemini-3-pro-preview | Gemini 3 Pro | chat | gemini | /v1beta/models/{model}:{action} |

### 图片生成模型 (Image)

| 模型名称 | 显示名称 | 类型 | 功能标签 |
|---------|---------|------|---------|
| midjourney-v6 | Midjourney V6 | image | 文生图, 图生图 |
| midjourney-v7 | Midjourney V7 | image | 文生图, 图生图 |
| gpt-image-2 | GPT Image 2 | image | 文生图, 图生图, 编辑 |
| nanobanana-pro | NB Pro | image | 文生图 |
| nanobanana-2 | NB 2.0 | image | 文生图 |
| qwen-image-max | Qwen Image Max | image | 文生图 |

### 视频生成模型 (Video)

| 模型名称 | 显示名称 | 类型 | 功能标签 |
|---------|---------|------|---------|
| kling-v1 | 可灵 V1 | video | 文生视频, 图生视频 |
| kling-v2 | 可灵 V2 | video | 文生视频, 图生视频 |
| luma-dream-machine | Luma Dream Machine | video | 文生视频, 图生视频 |
| runway-gen4 | Runway Gen-4 | video | 文生视频, 图生视频 |
| pika-2 | Pika 2.0 | video | 文生视频, 图生视频 |

### 音频/TTS/音乐模型 (Audio)

| 模型名称 | 显示名称 | 类型 | 功能 |
|---------|---------|------|------|
| suno-v3 | Suno V3 | audio | 音乐生成 |
| suno-v4 | Suno V4 | audio | 音乐生成 |
| elevenlabs-v3 | ElevenLabs V3 | audio | TTS语音合成 |
| fish-speech | Fish Speech | audio | TTS语音合成 |

---

## API 接口列表

### 1. 模型查询接口

#### 获取模型列表
```
GET /v1/skills/models?type={type}
```

**参数**:
- `type` (可选): chat | image | video | audio

**响应**: 返回模型列表，包含名称、显示名称、类型、功能标签等

#### 获取模型详情
```
GET /v1/skills/models/{name}
```

#### 获取模型价格
```
GET /v1/skills/models/{name}/pricing
```

### 2. 任务提交接口

#### 创建生成任务
```
POST /v1/media/generate
```

**请求体**:
```json
{
  "model": "模型名称",
  "prompt": "提示词",
  "workspaceId": "工作区ID",
  "params": {}
}
```

#### 查询任务状态
```
GET /v1/media/task-status?task_id={task_id}
```

### 3. 聊天接口

#### OpenAI 格式
```
POST /v1/chat/completions
```

**请求体**:
```json
{
  "model": "gpt-5.4",
  "messages": [
    {"role": "system", "content": "系统提示"},
    {"role": "user", "content": "用户消息"}
  ],
  "temperature": 0.7,
  "max_tokens": 2000,
  "stream": false
}
```

#### Anthropic 格式
```
POST /v1/messages
```

**请求体**:
```json
{
  "model": "claude-opus-4-7",
  "messages": [
    {"role": "user", "content": "用户消息"}
  ],
  "max_tokens": 2000
}
```

### 4. 账户接口

#### 查询余额
```
GET /v1/skills/balance
```

#### 查询消费记录
```
GET /v1/skills/usage?days=7
```

### 5. 反馈接口

#### 提交反馈
```
POST /v1/skills/feedback
```

**请求体**:
```json
{
  "type": "接口报错|文档疑问|功能建议",
  "question": "问题描述",
  "endpoint": "相关接口路径",
  "context": "操作背景"
}
```

---

## 调用代码示例

### Python - OpenAI 格式聊天

```python
import requests

api_key = 'sk-099e46fe8c0761992b84268f741db298ae44cebe1f216086'
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {api_key}'
}

data = {
    'model': 'gpt-5.4',
    'messages': [
        {'role': 'user', 'content': 'Hello!'}
    ],
    'temperature': 0.7,
    'max_tokens': 1000,
    'stream': False
}

response = requests.post(
    'https://api.lk888.ai/api/v1/chat/completions',
    headers=headers,
    json=data,
    timeout=120
)

result = response.json()
content = result['choices'][0]['message']['content']
```

### Python - 媒体生成任务

```python
import requests

api_key = 'sk-099e46fe8c0761992b84268f741db298ae44cebe1f216086'
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {api_key}'
}

# 提交任务
data = {
    'model': 'midjourney-v6',
    'prompt': 'a beautiful landscape',
    'workspaceId': 'default',
    'params': {
        'width': 1024,
        'height': 1024
    }
}

response = requests.post(
    'https://api.lk888.ai/api/v1/media/generate',
    headers=headers,
    json=data,
    timeout=30
)

task_id = response.json()['task_id']

# 查询任务状态
status_response = requests.get(
    f'https://api.lk888.ai/api/v1/media/task-status?task_id={task_id}',
    headers=headers,
    timeout=10
)
```

---

## 计费方式

- 按实际使用量计费
- 不同模型价格不同，可通过 `/v1/skills/models/{name}/pricing` 查询
- 余额查询: `/v1/skills/balance`

---

## 注意事项

1. 文件上传需要自行托管到 CDN 或对象存储，然后传入 URL
2. 媒体生成是异步任务，需要轮询查询状态
3. 每个 API Key 每小时最多提交 10 条反馈
4. 支持流式输出 (stream=true)

---

## 更新记录

- 2026-05-18: 初始创建，包含所有模型和接口信息
