# 获客线索 API 对接文档

> 版本：v1 · 更新日期：2026-06-28

## 一、快速开始

### 1. 认证方式

所有接口在 Header 携带 API Key：

```
X-API-Key: 你的API密钥
Content-Type: application/json
```

### 2. 基础地址

```
http://{服务器地址}:35092/api/v1/external
```

### 3. 最简对接（3 步上线）

```bash
# ① 拉取高意向线索（每次50条，自动去重）
curl -X POST "{BASE_URL}/leads/pull" \
  -H "X-API-Key: 你的密钥" \
  -H "Content-Type: application/json" \
  -d '{"level":"high","limit":50,"only_new":true}'

# ② 业务跟进后回传状态
curl -X POST "{BASE_URL}/status/callback" \
  -H "X-API-Key: 你的密钥" \
  -H "Content-Type: application/json" \
  -d '{"lead_id":"123","status":"contacted","remark":"已联系"}'

# ③ 循环拉取更多线索（only_new 会自动跳过已拉取的）
# 重复步骤①即可
```

---

## 二、接口列表

### 接口 1：拉取线索 `POST /leads/pull`

核心接口。按条件拉取线索，高意向优先返回。

**请求参数（JSON Body）：**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `platform` | string | 否 | - | 平台：`douyin` / `xhs` / `ks` / `bili` / `wb` |
| `level` | string | 否 | - | 意向等级：`high`(高) / `medium`(中) / `low`(低) |
| `min_score` | int | 否 | - | 最低意向分（0-100），与 level 二选一 |
| `task_id` | string | 否 | - | 按获客任务ID过滤 |
| `ip_location` | string | 否 | - | 地域关键词，模糊匹配，如 `"广东"` |
| `keyword` | string | 否 | - | 内容关键词，模糊匹配，如 `"沙发"` |
| `limit` | int | 否 | 50 | 每次拉取数量，1-100 |
| `offset` | int | 否 | 0 | 分页偏移量 |
| `only_new` | bool | 否 | false | `true` = 只返回未拉取过的新线索（推荐） |
| `package_id` | string | 否 | - | 线索包ID（按条计费模式用，包年用户忽略） |

**响应示例：**

```json
{
  "success": true,
  "total": 3627,
  "leads": [
    {
      "lead_id": "1040285",
      "platform": "douyin",
      "content": "怎么联系怎么买？",
      "ip_location": "山东",
      "lead_score": 100,
      "lead_level": "high",
      "task_id": "task_8066523f",
      "user_id": "110793984291",
      "user_name": "Happy",
      "nickname": "Happy",
      "created_at": 1782625241157
    }
  ]
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `lead_id` | string | 线索唯一ID（回传状态时用） |
| `platform` | string | 来源平台 |
| `content` | string | 用户评论内容 |
| `ip_location` | string | IP归属地 |
| `lead_score` | int | 意向分（0-100，越高越精准） |
| `lead_level` | string | 意向等级：`high`≥50 / `medium` 25-49 / `low` <25 |
| `task_id` | string | 所属获客任务ID |
| `user_id` | string | 评论用户ID |
| `user_name` | string | 用户名 |
| `nickname` | string | 昵称 |
| `created_at` | int | 评论时间戳（毫秒） |

**意向等级对照：**

| 等级 | 分数 | 含义 |
|------|------|------|
| `high` | ≥50 | 高意向（含明确购买/询价/求链接信号） |
| `medium` | 25-49 | 中意向（讨论相关但无明确购买意图） |
| `low` | <25 | 低意向（泛泛提及） |

---

### 接口 2：回传跟进状态 `POST /status/callback`

将线索的跟进结果回传，用于统计转化率。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `lead_id` | string | 是 | 线索ID（从拉取接口获得） |
| `status` | string | 是 | 跟进状态（见下表） |
| `remark` | string | 否 | 备注信息 |
| `follow_up_time` | int | 否 | 跟进时间戳（毫秒），默认当前时间 |

**status 可选值：**

| 值 | 含义 |
|----|------|
| `contacted` | 已联系 |
| `qualified` | 已确认意向 |
| `converted` | 已成交 |
| `lost` | 流失/无意向 |

**请求示例：**

```bash
curl -X POST "{BASE_URL}/status/callback" \
  -H "X-API-Key: 你的密钥" \
  -H "Content-Type: application/json" \
  -d '{"lead_id":"1040285","status":"converted","remark":"客户已下单5000元"}'
```

**响应：**

```json
{
  "success": true,
  "message": "Status updated successfully"
}
```

---

### 接口 3：获取线索包列表 `GET /packages`

获取可选线索包（按条计费模式用，包年用户可忽略）。

**Query 参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `level` | string | 否 | 按等级过滤：`high` / `medium` / `low` |
| `platform` | string | 否 | 按平台过滤 |
| `keyword` | string | 否 | 搜索包名/描述 |

**响应示例：**

```json
{
  "success": true,
  "total": 1,
  "packages": [
    {
      "package_id": "pkg_1aa45845",
      "name": "广东高意向线索包",
      "platform": "douyin",
      "level": "high",
      "ip_location": "广东",
      "total_count": 100,
      "available_count": 85,
      "price_per_lead": 10,
      "status": "active"
    }
  ]
}
```

---

### 接口 4：购买线索包 `POST /packages/purchase`

按条计费模式专用。包年用户跳过此接口。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `package_id` | string | 是 | 线索包ID |
| `quantity` | int | 是 | 购买数量 |

**响应示例：**

```json
{
  "success": true,
  "order_id": "ord_1717800100_def67890",
  "purchased_count": 10,
  "total_price": 100,
  "balance_after": 95000
}
```

> 金额单位：分（100分=1元）

---

## 三、对接代码示例

### Python

```python
import requests

BASE_URL = "http://你的服务器地址:35092/api/v1/external"
API_KEY = "你的API密钥"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def pull_leads(level="high", limit=50, only_new=True):
    """拉取线索"""
    resp = requests.post(
        f"{BASE_URL}/leads/pull",
        json={"level": level, "limit": limit, "only_new": only_new},
        headers=HEADERS,
    )
    data = resp.json()
    print(f"总数: {data['total']}, 本次: {len(data['leads'])}条")
    return data["leads"]


def callback(lead_id, status, remark=""):
    """回传跟进状态"""
    resp = requests.post(
        f"{BASE_URL}/status/callback",
        json={"lead_id": str(lead_id), "status": status, "remark": remark},
        headers=HEADERS,
    )
    return resp.json()


# === 主流程 ===
leads = pull_leads(level="high", limit=50, only_new=True)

for lead in leads:
    print(f"[{lead['lead_level']}] {lead['content'][:30]}  ({lead['ip_location']})")

    # TODO: 你的业务跟进逻辑
    # result = your_crm_follow_up(lead)

    # 回传状态
    callback(lead["lead_id"], "contacted", "已电话联系")
```

### Node.js

```javascript
const BASE_URL = "http://你的服务器地址:35092/api/v1/external";
const API_KEY = "你的API密钥";

async function pullLeads(params = {}) {
  const resp = await fetch(`${BASE_URL}/leads/pull`, {
    method: "POST",
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ level: "high", limit: 50, only_new: true, ...params }),
  });
  const data = await resp.json();
  console.log(`总数: ${data.total}, 本次: ${data.leads.length}条`);
  return data.leads;
}

async function callback(leadId, status, remark = "") {
  const resp = await fetch(`${BASE_URL}/status/callback`, {
    method: "POST",
    headers: {
      "X-API-Key": API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ lead_id: String(leadId), status, remark }),
  });
  return resp.json();
}

// 主流程
const leads = await pullLeads({ level: "high", only_new: true });
for (const lead of leads) {
  console.log(`[${lead.lead_level}] ${lead.content.slice(0, 30)} (${lead.ip_location})`);
  await callback(lead.lead_id, "contacted", "已联系");
}
```

### Java

```java
// 使用 OkHttp
String BASE_URL = "http://你的服务器地址:35092/api/v1/external";
String API_KEY = "你的API密钥";

// 拉取线索
RequestBody body = RequestBody.create(
    "{\"level\":\"high\",\"limit\":50,\"only_new\":true}",
    MediaType.parse("application/json")
);
Request request = new Request.Builder()
    .url(BASE_URL + "/leads/pull")
    .header("X-API-Key", API_KEY)
    .post(body)
    .build();
Response response = client.newCall(request).execute();
String result = response.body().string();
```

---

## 四、常见对接场景

### 场景 1：定时增量拉取（推荐）

每 5 分钟拉取一批新线索，避免重复：

```python
import time

while True:
    leads = pull_leads(level="high", limit=50, only_new=True)
    for lead in leads:
        # 入库 + 跟进
        callback(lead["lead_id"], "contacted")
    time.sleep(300)  # 5分钟
```

### 场景 2：按平台拉取

```python
# 只要 douyin 线索
pull_leads(platform="douyin", level="high")

# 只要 xhs 线索
pull_leads(platform="xhs", level="high")
```

### 场景 3：按地域+关键词拉取

```python
# 广东地区 + 内容含"沙发"
resp = requests.post(f"{BASE_URL}/leads/pull", json={
    "ip_location": "广东",
    "keyword": "沙发",
    "limit": 50,
    "only_new": True
}, headers=HEADERS)
```

### 场景 4：拉取指定任务线索

```python
# 拉取某个获客任务的全部线索
resp = requests.post(f"{BASE_URL}/leads/pull", json={
    "task_id": "task_8066523f",
    "limit": 100
}, headers=HEADERS)
```

---

## 五、错误码

| HTTP 状态码 | 含义 | 处理建议 |
|------------|------|----------|
| 200 | 成功 | - |
| 400 | 参数错误 | 检查请求体格式 |
| 401 | API Key 无效 | 检查 Header 中的 X-API-Key |
| 404 | 线索不存在 | lead_id 错误或非本账号线索 |
| 500 | 服务器错误 | 联系技术支持 |

**错误响应格式：**

```json
{
  "detail": "Invalid API Key"
}
```

---

## 六、注意事项

1. **API Key 安全**：仅在服务端使用，不要暴露在前端或 APP 中
2. **频率限制**：建议每秒不超过 10 次请求
3. **增量拉取**：推荐 `only_new: true`，系统自动记录已拉取的线索，避免重复
4. **意向分参考**：`high`（≥50）为推荐优先跟进的高意向线索
5. **回传状态**：跟进后请及时回传，便于平台优化线索质量
6. **时间戳**：所有时间戳均为毫秒级

---

## 七、联调检查清单

- [ ] API Key 已获取且能通过认证（调 `/leads/pull` 返回 200）
- [ ] 能拉到线索数据（`total > 0`）
- [ ] `only_new: true` 第二次拉取不返回重复线索
- [ ] 回传状态接口返回 `success: true`
- [ ] 定时任务配置完成（每 5 分钟增量拉取）
