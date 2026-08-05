# GEO内容工程系统 - 产品需求文档 (PRD)

## 文档信息
- **版本**: v1.0.0
- **日期**: 2026-05-16
- **状态**: 已完成开发
- **作者**: AI Assistant

---

## 1. 产品概述

### 1.1 产品背景
随着AI搜索引擎（ChatGPT、Perplexity、Google AI等）的兴起，传统SEO已无法满足品牌在AI时代的可见性需求。GEO（Generative Engine Optimization，生成式引擎优化）成为新的内容优化范式。

### 1.2 产品定义
GEO内容工程系统是一个面向AI搜索时代的**内容优化平台**，帮助企业和内容创作者：
- 生成AI友好的内容结构
- 优化内容以提高AI引用率
- 监测品牌在AI搜索中的表现
- 量化GEO投资回报

### 1.3 目标用户
- 内容营销团队
- SEO/GEO优化师
- 品牌运营人员
- 企业市场部门
- 独立内容创作者

### 1.4 核心价值主张
> **让品牌内容在AI搜索中被看见、被引用、被信任**

---

## 2. 系统架构

### 2.1 技术栈
```
前端: HTML5 + CSS3 + JavaScript (Vanilla)
后端: Python Flask
数据库: SQLite (支持MySQL扩展)
认证: JWT Token
API: RESTful API
```

### 2.2 系统架构图
```
┌─────────────────────────────────────────────────────────┐
│                      前端界面层                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │ 内容生成 │ │ 内容分析 │ │ 内容优化 │ │ 数据监测 │       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                   │
│  │ ROI计算  │ │ 信源建设 │ │ 用户中心 │                   │
│  └─────────┘ └─────────┘ └─────────┘                   │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      API网关层                           │
│              RESTful API / JWT认证                       │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      业务逻辑层                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │
│  │ 内容生成引擎 │ │ 内容分析引擎 │ │ 内容优化引擎 │       │
│  └─────────────┘ └─────────────┘ └─────────────┘       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │
│  │ 指标追踪器   │ │ ROI计算器   │ │ 信源构建器   │       │
│  └─────────────┘ └─────────────┘ └─────────────┘       │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      数据持久层                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │ 用户表   │ │ 生成历史 │ │ 分析记录 │ │ 优化记录 │       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                   │
│  │ 指标记录 │ │ ROI记录  │ │ 系统配置 │                   │
│  └─────────┘ └─────────┘ └─────────┘                   │
│                    SQLite数据库                         │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 功能模块详解

### 3.1 用户认证模块

#### 3.1.1 功能描述
- 用户注册
- 用户登录
- JWT Token认证
- 用户信息管理

#### 3.1.2 用户流程
```
1. 访问系统 → 显示登录/注册选项
2. 新用户 → 填写用户名、密码、邮箱 → 注册成功
3. 老用户 → 输入用户名、密码 → 登录成功 → 获取JWT Token
4. Token存储在localStorage，后续请求自动携带
5. 登出 → 清除Token → 返回未登录状态
```

#### 3.1.3 API接口
| 接口 | 方法 | 描述 | 认证 |
|------|------|------|------|
| /api/auth/register | POST | 用户注册 | 否 |
| /api/auth/login | POST | 用户登录 | 否 |
| /api/auth/logout | POST | 用户登出 | 是 |
| /api/auth/profile | GET | 获取用户信息 | 是 |

---

### 3.2 内容生成模块

#### 3.2.1 功能描述
基于**ERE框架**（Entity-Relation-Evidence）智能生成GEO优化的文章大纲。

#### 3.2.2 ERE框架说明
```
Entity (实体): 核心概念、产品、品牌
Relation (关系): 实体间的逻辑关联
Evidence (证据): 数据、案例、权威引用
```

#### 3.2.3 输入参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| title | string | 是 | 文章标题 |
| brand_name | string | 是 | 品牌名称 |
| industry | string | 否 | 行业领域 |
| expertise | array | 否 | 专业领域列表 |
| target_platform | string | 否 | 目标平台(chatgpt/perplexity/google_ai/kimi/doubao) |
| word_count | number | 否 | 字数要求(默认3000) |

#### 3.2.4 输出结果
```json
{
  "outline": [
    {"level": 1, "title": "引言：AI搜索时代的挑战与机遇"},
    {"level": 2, "title": "传统SEO的局限性"},
    {"level": 2, "title": "GEO的兴起与价值"},
    {"level": 1, "title": "ERE框架详解"},
    ...
  ],
  "prompt": "完整的AI提示词，可直接用于生成文章",
  "platform_adaptation": "平台特定的优化建议"
}
```

#### 3.2.5 用户操作流程
```
1. 进入"内容生成"页面
2. 填写文章标题
3. 填写品牌信息（名称、行业、专业领域）
4. 选择目标平台
5. 设置字数要求
6. 点击"生成内容大纲"
7. 系统返回：
   - 结构化大纲（可展开/收起）
   - 完整提示词（可复制）
   - 下载JSON功能
8. 数据自动保存到"生成历史"
```

---

### 3.3 内容分析模块

#### 3.3.1 功能描述
全面评估内容质量和GEO合规性，提供详细优化建议。

#### 3.3.2 评分维度
| 维度 | 权重 | 说明 |
|------|------|------|
| 结构得分 | 25% | 标题层级、段落组织、逻辑清晰度 |
| 引用得分 | 25% | 数据引用、权威来源、证据充分性 |
| 可读性得分 | 25% | 语言流畅度、复杂度、易读性 |
| 权威性得分 | 25% | 专业术语、品牌展示、信任度 |

#### 3.3.3 输出结果
```json
{
  "overall_score": 75.5,
  "structure_score": 80.0,
  "citation_score": 70.0,
  "readability_score": 78.0,
  "authority_score": 74.0,
  "geo_compliance": "good",
  "issues": [
    "缺少数据引用支撑",
    "品牌提及次数不足"
  ],
  "suggestions": [
    "建议添加权威数据源",
    "增加品牌自然提及"
  ]
}
```

#### 3.3.4 用户操作流程
```
1. 进入"内容分析"页面
2. 粘贴文章内容（至少50字符）
3. 点击"开始分析"
4. 系统返回：
   - 综合评分（圆形进度条展示）
   - 各维度得分（条形图）
   - 问题列表
   - 优化建议
5. 数据自动保存到"分析历史"
```

---

### 3.4 内容优化模块

#### 3.4.1 功能描述
智能优化内容结构和表达，提升AI引用率和可读性。

#### 3.4.2 优化级别
| 级别 | 说明 |
|------|------|
| light | 轻度优化 - 保留原意，微调结构 |
| medium | 中度优化 - 平衡改进和原意 |
| heavy | 深度优化 - 全面提升GEO合规性 |

#### 3.4.3 优化策略
1. **结构优化**: 添加小标题、调整段落顺序
2. **引用增强**: 插入数据点、添加权威引用
3. **可读性提升**: 简化复杂句子、优化过渡
4. **权威性强化**: 增加专业术语、品牌展示

#### 3.4.4 输出结果
```json
{
  "optimized_content": "优化后的完整内容",
  "score_before": 65.0,
  "score_after": 82.0,
  "improvements": [
    "添加了3个数据引用",
    "优化了5个段落的过渡",
    "增加了品牌自然提及"
  ]
}
```

---

### 3.5 数据监测模块

#### 3.5.1 功能描述
实时追踪GEO效果指标，生成多维度数据报告。

#### 3.5.2 核心指标
| 指标 | 说明 | 计算方式 |
|------|------|----------|
| AI引用率 | 内容被AI引用的频率 | 引用次数/总查询数 |
| 品牌提及率 | 品牌被提及的比例 | 提及次数/总回答数 |
| 答案空间覆盖 | 覆盖的查询主题比例 | 覆盖主题/总相关主题 |
| 来源多样性 | 引用来源的丰富度 | 不同来源数/总来源数 |
| 内容质量分 | 整体内容质量评估 | 多维度加权评分 |

#### 3.5.3 报告类型
- **日报**: 当日数据快照
- **周报**: 7天趋势分析
- **月报**: 30天综合报告

#### 3.5.4 用户操作流程
```
1. 进入"数据监测"页面
2. 记录今日指标：
   - AI引用次数
   - 品牌提及次数
   - 答案空间覆盖率
   - 来源多样性得分
   - 内容质量得分
3. 点击"保存指标"
4. 选择报告类型（日报/周报/月报）
5. 查看报告：
   - 当前周期数据
   - 环比变化
   - 优化建议
```

---

### 3.6 ROI计算模块

#### 3.6.1 功能描述
量化GEO投资回报，评估策略效果。

#### 3.6.2 计算公式
```
总投资 = 内容投资 + 技术投资 + 人力投资

新增流量价值 = AI引用提升 × 转化率 × 客户平均价值

净收益 = 新增流量价值 - 总投资

ROI = (净收益 / 总投资) × 100%

回收期 = 总投资 / (净收益 / 时间周期)
```

#### 3.6.3 输入参数
| 参数 | 说明 | 默认值 |
|------|------|--------|
| content_investment | 内容制作投入 | 50,000元 |
| technology_investment | 技术工具投入 | 30,000元 |
| personnel_investment | 人力成本投入 | 80,000元 |
| ai_citation_increase | AI引用提升比例 | 40% |
| conversion_rate | 转化率 | 2.5% |
| avg_customer_value | 客户平均价值 | 5,000元 |

#### 3.6.4 输出结果
```json
{
  "total_investment": 160000,
  "revenue": 450000,
  "net_profit": 290000,
  "roi_percentage": 181.25,
  "payback_period_months": 4.3,
  "new_customers": 90,
  "evaluation": "优秀的投资回报！建议立即实施。"
}
```

---

### 3.7 信源建设模块

#### 3.7.1 功能描述
构建四级信源金字塔，提升品牌在AI搜索中的权威性。

#### 3.7.2 四级信源金字塔
```
        ┌─────────────────┐
        │   一级：官方网站   │  权重 40%
        │  (品牌控制的核心)  │
        ├─────────────────┤
        │   二级：权威媒体   │  权重 30%
        │ (行业媒体、新闻)   │
        ├─────────────────┤
        │   三级：行业社区   │  权重 20%
        │ (论坛、问答平台)   │
        ├─────────────────┤
        │   四级：社交平台   │  权重 10%
        │ (社交媒体、KOL)   │
        └─────────────────┘
```

#### 3.7.3 官网建设方案
1. **Schema.org标记**: 结构化数据标记
2. **实体页面**: 核心概念独立页面
3. **关系图谱**: 内容间关联链接
4. **证据展示**: 数据、案例、证书

---

## 4. 数据库设计

### 4.1 表结构

#### users (用户表)
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    email TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active INTEGER DEFAULT 1
);
```

#### generation_history (内容生成历史)
```sql
CREATE TABLE generation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT NOT NULL,
    brand_name TEXT,
    industry TEXT,
    platform TEXT,
    word_count INTEGER,
    outline TEXT,  -- JSON
    prompt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

#### analysis_records (内容分析记录)
```sql
CREATE TABLE analysis_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    content TEXT NOT NULL,
    overall_score REAL,
    structure_score REAL,
    citation_score REAL,
    readability_score REAL,
    authority_score REAL,
    geo_compliance TEXT,
    issues TEXT,  -- JSON
    suggestions TEXT,  -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

#### metrics_records (GEO指标记录)
```sql
CREATE TABLE metrics_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    record_date DATE NOT NULL,
    ai_citation_count INTEGER DEFAULT 0,
    brand_mention_count INTEGER DEFAULT 0,
    answer_space_coverage REAL DEFAULT 0,
    source_diversity_score REAL DEFAULT 0,
    content_quality_score REAL DEFAULT 0,
    citations_by_platform TEXT,  -- JSON
    mentions_by_source TEXT,  -- JSON
    top_queries TEXT,  -- JSON
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, record_date)
);
```

---

## 5. API接口文档

### 5.1 认证相关

#### POST /api/auth/register
**请求体:**
```json
{
  "username": "string",
  "password": "string",
  "email": "string"
}
```

**响应:**
```json
{
  "success": true,
  "user_id": 1,
  "username": "string",
  "message": "用户创建成功"
}
```

#### POST /api/auth/login
**请求体:**
```json
{
  "username": "string",
  "password": "string"
}
```

**响应:**
```json
{
  "success": true,
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "username": "string",
  "user_id": 1,
  "message": "登录成功"
}
```

### 5.2 内容生成

#### POST /api/content/generate
**请求头:** `Authorization: Bearer <token>`

**请求体:**
```json
{
  "title": "string",
  "brand_info": {
    "name": "string",
    "industry": "string",
    "expertise": ["string"]
  },
  "target_platform": "chatgpt",
  "word_count": 3000
}
```

### 5.3 内容分析

#### POST /api/content/analyze
**请求体:**
```json
{
  "content": "string"
}
```

**响应:**
```json
{
  "success": true,
  "data": {
    "overall_score": 75.5,
    "structure_score": 80.0,
    "citation_score": 70.0,
    "readability_score": 78.0,
    "authority_score": 74.0,
    "geo_compliance": "good",
    "issues": ["string"],
    "suggestions": ["string"]
  }
}
```

### 5.4 数据监测

#### POST /api/metrics/record
**请求体:**
```json
{
  "date": "2026-05-16",
  "ai_citation_count": 10,
  "brand_mention_count": 5,
  "answer_space_coverage": 0.35,
  "source_diversity_score": 0.7,
  "content_quality_score": 0.8
}
```

#### GET /api/metrics/report?type=monthly
**响应:**
```json
{
  "success": true,
  "data": {
    "basic_metrics": {
      "ai_citation_rate": {"current": 10.5, "change": 2.3},
      "brand_mention_rate": {"current": 8.0, "change": 1.5},
      "answer_space_coverage": {"current": 0.35, "change": 0.05},
      "visibility_score": {"current": 75.0, "change": 5.0}
    },
    "recommendations": [
      {"priority": "high", "suggestion": "string"}
    ]
  }
}
```

### 5.5 ROI计算

#### POST /api/roi/calculate
**请求体:**
```json
{
  "content_investment": 50000,
  "technology_investment": 30000,
  "personnel_investment": 80000,
  "ai_citation_increase": 40,
  "brand_mention_increase": 35,
  "conversion_rate": 2.5,
  "avg_customer_value": 5000,
  "time_period_months": 12
}
```

---

## 6. 用户界面设计

### 6.1 页面结构
```
┌────────────────────────────────────────┐
│  侧边栏导航                              │
│  ├─ 🏠 首页                             │
│  ├─ ✍️ 内容生成                          │
│  ├─ 🔍 内容分析                          │
│  ├─ ⚡ 内容优化                          │
│  ├─ 📊 数据监测                          │
│  ├─ 💰 ROI计算                          │
│  └─ 🏛️ 信源建设                          │
├────────────────────────────────────────┤
│  主内容区                                │
│  ├─ 页面标题                             │
│  ├─ 功能卡片                             │
│  ├─ 输入表单                             │
│  └─ 结果展示                             │
└────────────────────────────────────────┘
```

### 6.2 设计规范
- **主色调**: #667eea (紫色) / #764ba2 (深紫)
- **辅助色**: #10b981 (成功绿) / #ef4444 (错误红)
- **字体**: 系统默认无衬线字体
- **圆角**: 8px-12px
- **阴影**: 0 4px 6px rgba(0,0,0,0.1)

---

## 7. 部署指南

### 7.1 环境要求
- Python 3.8+
- pip 包管理器
- 现代浏览器（Chrome/Firefox/Edge）

### 7.2 安装步骤

#### 步骤1: 克隆/解压项目
```bash
cd geo_system
```

#### 步骤2: 安装依赖
```bash
cd backend
pip install -r requirements.txt
```

#### 步骤3: 启动后端
```bash
python app_real.py
```

#### 步骤4: 启动前端
```bash
cd web
python -m http.server 8080
```

#### 步骤5: 访问系统
打开浏览器访问: `http://localhost:8080/index_real.html`

### 7.3 一键启动
Windows用户可直接运行:
```bash
start_real.bat
```

---

## 8. 使用流程示例

### 8.1 完整工作流
```
1. 注册/登录
   └─ 创建账户或登录现有账户

2. 内容生成
   └─ 输入标题和品牌信息
   └─ 生成GEO优化大纲
   └─ 复制提示词到AI工具生成文章

3. 内容分析
   └─ 粘贴生成的文章
   └─ 分析内容质量
   └─ 查看评分和建议

4. 内容优化
   └─ 根据分析结果优化
   └─ 使用优化工具自动改进
   └─ 对比优化前后效果

5. 数据监测
   └─ 定期记录GEO指标
   └─ 生成周报/月报
   └─ 追踪优化效果

6. ROI评估
   └─ 输入投资成本
   └─ 计算投资回报
   └─ 评估策略有效性

7. 信源建设
   └─ 查看信源金字塔
   └─ 制定权威度建设方案
   └─ 提升品牌可信度
```

---

## 9. 常见问题 (FAQ)

### Q1: 系统需要联网吗？
**A:** 基础功能不需要联网，所有数据存储在本地SQLite数据库。但建议联网以获取最新的AI平台适配策略。

### Q2: 支持多用户吗？
**A:** 支持。每个用户有独立的数据空间，通过JWT Token认证隔离。

### Q3: 数据会丢失吗？
**A:** 数据存储在 `backend/geo_system.db` 文件中，建议定期备份此文件。

### Q4: 可以导出数据吗？
**A:** 可以。内容生成结果支持JSON导出，优化后的内容支持Markdown导出。

### Q5: 如何升级数据库到MySQL？
**A:** 修改 `backend/database.py` 中的数据库连接配置，安装PyMySQL驱动即可。

---

## 10. 更新日志

### v1.0.0 (2026-05-16)
- ✅ 初始版本发布
- ✅ 用户认证系统
- ✅ 内容生成模块（ERE框架）
- ✅ 内容分析模块
- ✅ 内容优化模块
- ✅ 数据监测模块
- ✅ ROI计算模块
- ✅ 信源建设模块
- ✅ SQLite数据库支持
- ✅ RESTful API
- ✅ Web界面

---

## 11. 联系方式

如有问题或建议，请通过以下方式联系：
- 项目文档: README.md
- API文档: http://localhost:5000/api/health

---

**文档结束**
