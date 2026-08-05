# GEO系统API参考文档

完整的API接口文档，包含所有可用的端点和参数。

## 基础信息

- **Base URL**: `http://localhost:8000`
- **API版本**: v1
- **Content-Type**: `application/json`

## 认证

目前API为开放访问，生产环境建议添加API Key认证。

```
Authorization: Bearer YOUR_API_KEY
```

## 端点概览

| 端点 | 方法 | 描述 |
|------|------|------|
| `/` | GET | 系统信息 |
| `/health` | GET | 健康检查 |
| `/api/v1/content/generate` | POST | 生成内容大纲 |
| `/api/v1/content/optimize` | POST | 优化内容 |
| `/api/v1/content/analyze` | POST | 分析内容 |
| `/api/v1/metrics/record` | POST | 记录指标 |
| `/api/v1/metrics/report` | GET | 获取报告 |
| `/api/v1/authority/pyramid` | GET | 信源金字塔 |
| `/api/v1/authority/official-site-plan` | POST | 官网建设方案 |

---

## 详细端点

### 系统信息

#### GET /

获取系统基本信息。

**响应示例**:
```json
{
  "message": "GEO内容工程系统API",
  "version": "1.0.0",
  "docs": "/docs"
}
```

#### GET /health

健康检查端点。

**响应示例**:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00"
}
```

---

### 内容生成

#### POST /api/v1/content/generate

生成GEO优化文章大纲。

**请求参数**:

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| title | string | 是 | 文章标题 |
| brand_name | string | 是 | 品牌名称 |
| industry | string | 否 | 所属行业，默认"AI营销" |
| expertise | array | 否 | 专业领域列表 |
| target_platform | string | 否 | 目标平台，默认"chatgpt" |
| word_count | integer | 否 | 目标字数，默认3000 |

**请求示例**:
```json
{
  "title": "什么是生成式引擎优化（GEO）",
  "brand_name": "智媒科技",
  "industry": "AI营销",
  "expertise": ["GEO", "AI搜索优化", "内容营销"],
  "target_platform": "chatgpt",
  "word_count": 3000
}
```

**响应示例**:
```json
{
  "success": true,
  "title": "什么是生成式引擎优化（GEO）",
  "outline": [
    {
      "level": 1,
      "title": "什么是生成式引擎优化（GEO）"
    },
    {
      "level": 2,
      "title": "GEO的核心理念"
    }
  ],
  "prompt": "# Role: GEO内容专家...",
  "message": "内容生成成功"
}
```

**错误响应**:
```json
{
  "detail": "错误信息"
}
```

---

### 内容优化

#### POST /api/v1/content/optimize

优化现有内容。

**请求参数**:

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| content | string | 是 | 要优化的内容 |
| optimization_level | string | 否 | 优化级别：light/medium/heavy，默认medium |

**请求示例**:
```json
{
  "content": "GEO是一种优化方法。它很重要。",
  "optimization_level": "medium"
}
```

**响应示例**:
```json
{
  "success": true,
  "optimized_content": "生成式引擎优化（GEO）是一种...",
  "score_before": 45.0,
  "score_after": 78.5,
  "improvements": [
    "添加了专业术语定义",
    "增加了数据支撑"
  ]
}
```

---

### 内容分析

#### POST /api/v1/content/analyze

分析内容质量。

**请求参数**:

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| content | string | 是 | 要分析的内容 |

**请求示例**:
```json
{
  "content": "# 什么是GEO\n\nGEO是生成式引擎优化..."
}
```

**响应示例**:
```json
{
  "success": true,
  "overall_score": 75.5,
  "structure_score": 80.0,
  "citation_score": 70.0,
  "readability_score": 85.0,
  "authority_score": 65.0,
  "geo_compliance": 78.0,
  "issues": [
    "引用数据不够具体",
    "缺少权威来源"
  ],
  "suggestions": [
    "添加具体的研究数据来源",
    "引用行业权威报告"
  ]
}
```

**评分标准**:

| 分数范围 | 评级 | 说明 |
|----------|------|------|
| 90-100 | 优秀 | 内容质量极佳，符合所有GEO标准 |
| 80-89 | 良好 | 内容质量较好，少量优化空间 |
| 60-79 | 合格 | 基本符合要求，需要一定优化 |
| 40-59 | 待改进 | 存在明显问题，需要大幅优化 |
| 0-39 | 不合格 | 不符合GEO标准，建议重写 |

---

### 指标记录

#### POST /api/v1/metrics/record

记录GEO指标数据。

**请求参数**:

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| ai_citation_count | integer | 是 | AI引用次数 |
| brand_mention_count | integer | 是 | 品牌提及次数 |
| answer_space_coverage | float | 是 | 答案空间覆盖率(0-1) |
| source_diversity_score | float | 是 | 信源多样性得分(0-1) |
| content_quality_score | float | 是 | 内容质量得分(0-1) |
| citations_by_platform | object | 否 | 各平台引用数 |
| mentions_by_source | object | 否 | 各来源提及数 |
| top_queries | array | 否 | 热门查询列表 |

**请求示例**:
```json
{
  "ai_citation_count": 100,
  "brand_mention_count": 150,
  "answer_space_coverage": 0.5,
  "source_diversity_score": 0.7,
  "content_quality_score": 0.8,
  "citations_by_platform": {
    "chatgpt": 50,
    "perplexity": 30,
    "google_ai": 20
  },
  "mentions_by_source": {
    "官网": 80,
    "知乎": 40,
    "微信公众号": 30
  },
  "top_queries": [
    "什么是GEO",
    "GEO优化方法",
    "AI搜索优化"
  ]
}
```

**响应示例**:
```json
{
  "success": true,
  "message": "指标记录成功"
}
```

---

### 报告获取

#### GET /api/v1/metrics/report

获取GEO指标报告。

**查询参数**:

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| report_type | string | 否 | 报告类型：daily/weekly/monthly，默认monthly |

**请求示例**:
```
GET /api/v1/metrics/report?report_type=monthly
```

**响应示例**:
```json
{
  "success": true,
  "ai_citation_rate": {
    "current": 45.5,
    "previous": 40.0,
    "change": 5.5
  },
  "brand_mention_rate": {
    "current": 60.0,
    "previous": 55.0,
    "change": 5.0
  },
  "answer_space_coverage": {
    "current": 0.35,
    "previous": 0.30,
    "change": 0.05
  },
  "visibility_score": {
    "current": 65.5,
    "previous": 60.0,
    "change": 5.5
  },
  "recommendations": [
    {
      "priority": "high",
      "suggestion": "增加高质量内容产出",
      "action": "每周发布3篇GEO优化文章"
    }
  ]
}
```

---

### 信源建设

#### GET /api/v1/authority/pyramid

获取四级信源权威金字塔。

**响应示例**:
```json
{
  "success": true,
  "data": {
    "name": "四级信源权威金字塔",
    "description": "从官网到社交媒体的四级权威体系",
    "levels": {
      "1": {
        "name": "官网与官方文档",
        "weight": 0.4,
        "description": "品牌官网、帮助中心、API文档"
      },
      "2": {
        "name": "权威媒体与行业报告",
        "weight": 0.3,
        "description": "权威媒体报道、行业白皮书"
      },
      "3": {
        "name": "行业社区与专业平台",
        "weight": 0.2,
        "description": "知乎、掘金、CSDN等专业社区"
      },
      "4": {
        "name": "社交媒体与UGC",
        "weight": 0.1,
        "description": "微信公众号、微博、小红书"
      }
    }
  }
}
```

#### POST /api/v1/authority/official-site-plan

获取官网权威化改造方案。

**请求参数**:

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| name | string | 是 | 品牌名称 |
| url | string | 是 | 官网URL |
| description | string | 是 | 品牌描述 |

**请求示例**:
```json
{
  "name": "智媒科技",
  "url": "https://www.zhimei.tech",
  "description": "AI营销技术解决方案提供商"
}
```

**响应示例**:
```json
{
  "success": true,
  "data": {
    "name": "官网权威化改造方案",
    "priority": "高",
    "components": {
      "schema_markup": {
        "name": "Schema.org结构化数据",
        "tasks": [
          "部署Organization标记",
          "添加Product标记",
          "配置FAQ标记"
        ]
      }
    }
  }
}
```

---

## 错误码

| 状态码 | 含义 | 说明 |
|--------|------|------|
| 200 | OK | 请求成功 |
| 400 | Bad Request | 请求参数错误 |
| 404 | Not Found | 资源不存在 |
| 422 | Validation Error | 参数验证失败 |
| 500 | Internal Server Error | 服务器内部错误 |

**错误响应格式**:
```json
{
  "detail": "详细的错误信息"
}
```

---

## 代码示例

### Python

```python
import requests

# 生成内容
response = requests.post(
    "http://localhost:8000/api/v1/content/generate",
    json={
        "title": "什么是GEO",
        "brand_name": "智媒科技",
        "industry": "AI营销"
    }
)

result = response.json()
print(result['outline'])
```

### JavaScript

```javascript
// 分析内容
fetch('http://localhost:8000/api/v1/content/analyze', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    content: '要分析的内容...'
  })
})
.then(response => response.json())
.then(data => {
  console.log('得分:', data.overall_score);
});
```

### cURL

```bash
# 记录指标
curl -X POST http://localhost:8000/api/v1/metrics/record \
  -H "Content-Type: application/json" \
  -d '{
    "ai_citation_count": 100,
    "brand_mention_count": 150,
    "answer_space_coverage": 0.5,
    "source_diversity_score": 0.7,
    "content_quality_score": 0.8
  }'
```

---

## 限流

生产环境建议配置限流：

- 普通端点：100次/分钟
- 生成端点：20次/分钟

---

## 更新日志

### v1.0.0 (2024-01-15)

- 初始版本发布
- 支持内容生成、优化、分析
- 支持指标记录和报告
- 支持信源建设

---

如有问题，请联系技术支持。
