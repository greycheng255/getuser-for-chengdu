# GEO内容工程系统

🚀 **面向AI搜索时代的内容优化解决方案**

## 系统概述

GEO（Generative Engine Optimization）内容工程系统是一套完整的AI搜索优化解决方案，帮助品牌在AI搜索时代获得更多曝光和引用。

### 核心理念

> **不要争排名，要争引用。**

与传统SEO关注搜索引擎排名不同，GEO关注的是**品牌在AI答案中的引用率**。通过ERE框架（实体-关系-证据）构建高质量内容，让AI在回答用户问题时主动引用你的品牌。

## 系统架构

```
GEO系统
├── 前端 (web/)
│   ├── index.html    - 现代化Web界面
│   ├── app.js        - 前端逻辑与API交互
│   └── styles.css    - 样式表
│
├── 后端 (backend/)
│   ├── app.py        - Flask API服务
│   └── requirements.txt - Python依赖
│
├── 核心模块 (core/)
│   ├── content_generator.py   - 内容生成
│   ├── content_optimizer.py   - 内容优化
│   └── rag_engine.py          - RAG引擎
│
├── 工具模块 (utils/)
│   └── content_analyzer.py    - 内容分析
│
├── 功能模块 (modules/)
│   ├── data/
│   │   ├── metrics_tracker.py - 数据监测
│   │   └── roi_calculator.py  - ROI计算
│   │
│   └── source/
│       ├── authority_builder.py     - 信源建设
│       ├── platform_distributor.py  - 平台分发
│       └── schema_optimizer.py      - Schema优化
│
├── 示例 (examples/)
│   └── quick_start.py   - 快速入门示例
│
├── 配置 (config/)
│   └── models.yaml      - 模型配置
│
├── 测试 (tests/)
│   ├── test_content_generator.py
│   └── test_modules.py
│
└── 文档 (docs/)
    ├── tutorial.md      - 使用教程
    └── api_reference.md - API文档
```

## 快速开始

### 方式一：使用启动脚本（推荐）

Windows用户直接双击运行：

```bash
start.bat
```

或使用Python启动器：

```bash
python start_server.py
```

### 方式二：手动启动

1. **启动后端API服务**

```bash
cd backend
pip install -r requirements.txt
python app.py
```

后端服务将在 http://localhost:5000 启动

2. **启动前端页面**

```bash
cd web
python -m http.server 8080
```

前端页面将在 http://localhost:8080 启动

3. **访问系统**

打开浏览器访问 http://localhost:8080

## 功能模块

### 1. ✍️ 内容生成

基于ERE框架智能生成GEO优化文章大纲，支持多平台适配。

**API端点**: `POST /api/content/generate`

```json
{
  "title": "2024年GEO优化指南",
  "brand_info": {
    "name": "你的品牌",
    "industry": "AI营销"
  },
  "target_platform": "chatgpt",
  "word_count": 3000
}
```

### 2. 🔍 内容分析

全面评估内容质量和GEO合规性，提供详细优化建议。

**API端点**: `POST /api/content/analyze`

```json
{
  "content": "要分析的文章内容..."
}
```

### 3. ⚡ 内容优化

自动优化内容结构和表达方式，提升AI引用率。

**API端点**: `POST /api/content/optimize`

```json
{
  "content": "要优化的内容...",
  "optimization_level": "medium"
}
```

### 4. 📊 数据监测

追踪GEO关键指标，生成周期性效果报告。

**API端点**: 
- `POST /api/metrics/record` - 记录指标
- `GET /api/metrics/report` - 获取报告
- `GET /api/metrics/history` - 获取历史

### 5. 💰 ROI计算

评估GEO投资回报，预测业务收益。

**API端点**: `POST /api/roi/calculate`

```json
{
  "content_investment": 50000,
  "technology_investment": 30000,
  "personnel_investment": 80000,
  "ai_citation_increase": 40,
  "conversion_rate": 2.5,
  "avg_customer_value": 5000
}
```

### 6. 🏛️ 信源建设

构建四级权威信源体系，提升品牌可信度。

**API端点**: 
- `GET /api/authority/pyramid` - 获取信源金字塔
- `POST /api/authority/official-site-plan` - 官网建设方案

## 支持的AI平台

| 平台 | ID | 说明 |
|------|-----|------|
| ChatGPT | chatgpt | OpenAI的对话AI |
| Perplexity | perplexity | AI搜索引擎 |
| Google AI | google_ai | Google AI搜索 |
| Kimi | kimi | 月之暗面AI助手 |
| 豆包 | doubao | 字节跳动AI助手 |

## API文档

### 基础信息

- **基础URL**: `http://localhost:5000/api`
- **数据格式**: JSON
- **编码**: UTF-8

### 响应格式

```json
{
  "success": true,
  "data": { ... },
  "message": "操作成功"
}
```

### 健康检查

```bash
GET /api/health
```

### 系统统计

```bash
GET /api/stats
```

## 开发指南

### 环境要求

- Python 3.8+
- Flask 3.0+
- 现代浏览器（Chrome/Firefox/Edge）

### 安装依赖

```bash
pip install -r backend/requirements.txt
```

### 运行测试

```bash
python -m pytest tests/
```

## 核心概念

### ERE框架

- **Entity（实体）**: 核心概念和对象
- **Relation（关系）**: 实体间的联系
- **Evidence（证据）**: 支撑论点的数据和案例

### RAG架构

- **Retrieval（检索）**: 从知识库检索相关信息
- **Augmented（增强）**: 结合检索结果增强内容
- **Generation（生成）**: 生成优化后的内容

### 四级信源金字塔

1. **第一层 - 官网**: 权重40%
2. **第二层 - 权威媒体**: 权重30%
3. **第三层 - 行业社区**: 权重20%
4. **第四层 - 社交平台**: 权重10%

## 最佳实践

1. **内容生成**: 使用ERE框架确保内容结构完整
2. **平台适配**: 根据不同AI平台调整内容风格
3. **持续监测**: 定期记录指标，追踪优化效果
4. **信源建设**: 优先建设官网和权威媒体信源
5. **ROI评估**: 定期评估投资回报，调整策略

## 文件结构

```
geo_system/
├── backend/          # 后端API服务
├── web/              # 前端Web界面
├── core/             # 核心模块
├── modules/          # 功能模块
├── utils/            # 工具函数
├── examples/         # 示例代码
├── tests/            # 测试文件
├── config/           # 配置文件
├── docs/             # 文档
├── start.bat         # Windows启动脚本
├── start_server.py   # Python启动脚本
└── README.md         # 项目说明
```

## 更新日志

### v1.0.0
- ✅ 完整的前后端分离架构
- ✅ 现代化Web界面设计
- ✅ RESTful API接口
- ✅ 内容生成、分析、优化功能
- ✅ 数据监测和ROI计算
- ✅ 信源建设和平台适配
- ✅ 用户认证系统
- ✅ 缓存和错误处理优化

## 许可证

MIT License

## 联系方式

如有问题或建议，欢迎提交Issue或Pull Request。

---

**让AI主动引用你的品牌！** 🚀
