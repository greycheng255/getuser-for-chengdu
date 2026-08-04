# GEO系统使用教程

本教程将带你从零开始使用GEO内容工程系统。

## 目录

1. [快速开始](#快速开始)
2. [核心概念](#核心概念)
3. [内容生成](#内容生成)
4. [内容优化](#内容优化)
5. [知识库管理](#知识库管理)
6. [信源建设](#信源建设)
7. [数据监测](#数据监测)
8. [API使用](#api使用)
9. [CLI工具](#cli工具)
10. [最佳实践](#最佳实践)

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/your-org/geo-system.git
cd geo-system

# 安装依赖
pip install -r requirements.txt
```

### 初始化

```bash
# 使用CLI初始化系统
python -m geo_system.cli init

# 或者手动创建配置文件
```

### 第一个GEO文章

```python
from geo_system.core.content_generator import GEOArticleGenerator

generator = GEOArticleGenerator()

result = generator.generate(
    title="什么是生成式引擎优化（GEO）",
    brand_info={
        "name": "你的品牌",
        "industry": "AI营销",
        "expertise": ["GEO", "内容营销"]
    }
)

print(result['outline'])
```

## 核心概念

### ERE框架

ERE框架是GEO内容的核心结构：

- **Entity（实体）**：明确的品牌、产品、概念定义
- **Relation（关系）**：实体之间的逻辑关联
- **Evidence（证据）**：数据、案例、研究支撑

### 四级信源权威体系

1. **一级**：官网、官方文档
2. **二级**：权威媒体、行业报告
3. **三级**：行业社区、专业平台
4. **四级**：社交媒体、UGC内容

### AI引用率

衡量品牌在AI回答中被引用的频率，是GEO的核心KPI。

## 内容生成

### 基本使用

```python
from geo_system.core.content_generator import GEOArticleGenerator

generator = GEOArticleGenerator()

# 生成文章大纲
result = generator.generate(
    title="文章标题",
    brand_info={
        "name": "品牌名",
        "industry": "行业",
        "expertise": ["专业领域1", "专业领域2"]
    },
    target_platform="chatgpt",  # 目标平台
    word_count=3000  # 目标字数
)

# 输出生成的提示词
print(result['prompt'])
```

### 多平台适配

```python
# 为不同平台生成适配内容
platforms = ['chatgpt', 'perplexity', 'google_ai']

for platform in platforms:
    result = generator.generate(
        title="同一主题",
        brand_info=brand_info,
        target_platform=platform
    )
    # 保存各平台版本
```

### 批量生成

```python
from geo_system.examples.batch_processor import BatchContentProcessor

processor = BatchContentProcessor()

topics = [
    {"title": "主题1", "keywords": ["GEO"]},
    {"title": "主题2", "keywords": ["AI搜索"]}
]

results = processor.process_topics(topics, brand_info)
```

## 内容优化

### 分析内容质量

```python
from geo_system.utils.content_analyzer import ContentAnalyzer

analyzer = ContentAnalyzer()

with open('article.md', 'r') as f:
    content = f.read()

result = analyzer.analyze(content)

print(f"整体得分: {result.overall_score}")
print(f"问题: {result.issues}")
print(f"建议: {result.suggestions}")
```

### 自动优化

```python
from geo_system.core.content_optimizer import GEOContentOptimizer

optimizer = GEOContentOptimizer()

# 优化内容
result = optimizer.optimize(content, optimization_level="medium")

print(f"优化前: {result.score_before}")
print(f"优化后: {result.score_after}")
print(result.optimized_content)
```

## 知识库管理

### 构建知识库

```python
from geo_system.core.rag_engine import RAGEngine, GEOKnowledgeBuilder

engine = RAGEngine()
builder = GEOKnowledgeBuilder(engine)

# 添加实体
builder.add_entity(
    name="GEO",
    definition="生成式引擎优化",
    attributes={"全称": "Generative Engine Optimization"}
)

# 添加关系
builder.add_relation("GEO", "基于", "RAG", "GEO基于RAG技术")

# 添加证据
builder.add_evidence(
    claim="GEO有效",
    evidence="研究显示引用率提升40%",
    source="Princeton Research",
    evidence_type="研究数据"
)
```

### 查询知识

```python
# 查询知识库
knowledge = builder.query_for_article("GEO优化")

print(knowledge['entities'])
print(knowledge['relations'])
print(knowledge['evidence'])
```

## 信源建设

### 四级信源体系

```python
from geo_system.modules.source.authority_builder import AuthorityBuilder

builder = AuthorityBuilder()

# 获取信源金字塔
pyramid = builder.get_authority_pyramid()

for level, info in pyramid['levels'].items():
    print(f"{level}: {info['name']} - {info['weight']}")
```

### 官网权威化

```python
# 生成官网改造方案
plan = builder.build_official_site_authority({
    "name": "品牌名",
    "url": "https://example.com",
    "description": "品牌描述"
})

for component_name, component in plan['components'].items():
    print(f"{component['name']}: {len(component['tasks'])} 项任务")
```

### Schema.org优化

```python
from geo_system.modules.source.schema_optimizer import SchemaOptimizer

optimizer = SchemaOptimizer()

# 优化Organization
org_data = {
    "name": "品牌名",
    "description": "描述",
    "url": "https://example.com"
}

optimized = optimizer.optimize_organization(org_data)

# 验证Schema
validation = optimizer.validate_schema(optimized)
print(f"完整度: {validation['completeness_score']}%")
```

## 数据监测

### 记录指标

```python
from geo_system.modules.data.metrics_tracker import GEOMetricsTracker, GEOMetrics

tracker = GEOMetricsTracker()

metrics = GEOMetrics(
    date=datetime.now().isoformat(),
    ai_citation_count=100,
    brand_mention_count=150,
    answer_space_coverage=0.5,
    source_diversity_score=0.7,
    content_quality_score=0.8,
    citations_by_platform={
        "chatgpt": 50,
        "perplexity": 30,
        "google_ai": 20
    },
    mentions_by_source={
        "官网": 80,
        "知乎": 40,
        "微信公众号": 30
    },
    top_queries=["什么是GEO", "GEO优化"]
)

tracker.record_metrics(metrics)
```

### 生成报告

```python
# 生成月度报告
report = tracker.generate_report("monthly")

print(f"AI引用率: {report['basic_metrics']['ai_citation_rate']['current']}")
print(f"优化建议: {len(report['recommendations'])} 条")
```

### ROI计算

```python
from geo_system.modules.data.roi_calculator import ROICalculator

calculator = ROICalculator()

params = {
    'content_investment': 50000,
    'technology_investment': 30000,
    'personnel_investment': 80000,
    'ai_citation_increase': 40,
    'brand_mention_increase': 35,
    'conversion_rate': 2.5,
    'avg_customer_value': 5000,
    'time_period_months': 12
}

result = calculator.calculate_basic_roi(params)

print(f"ROI: {result['roi_percentage']:.1f}%")
print(f"回收期: {result['payback_period_months']:.1f}个月")
```

## API使用

### 启动API服务器

```bash
python -m geo_system.api.server
```

### API端点

#### 生成内容

```bash
curl -X POST http://localhost:8000/api/v1/content/generate \
  -H "Content-Type: application/json" \
  -d '{
    "title": "什么是GEO",
    "brand_name": "你的品牌",
    "industry": "AI营销",
    "expertise": ["GEO", "内容营销"]
  }'
```

#### 分析内容

```bash
curl -X POST http://localhost:8000/api/v1/content/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "content": "要分析的内容..."
  }'
```

#### 获取报告

```bash
curl http://localhost:8000/api/v1/metrics/report?report_type=monthly
```

## CLI工具

### 安装CLI

```bash
pip install -e .
```

### 常用命令

```bash
# 初始化
goo init

# 生成内容
goo generate --title "文章标题" --brand "品牌名"

# 分析内容
goo analyze --file article.md

# 优化内容
goo optimize --file article.md --output optimized.md

# 记录指标
goo metrics --file metrics.json

# 生成报告
goo report --type monthly

# 计算ROI
goo roi --investment 160000 --citation-increase 40

# 启动API服务器
goo server --port 8000
```

## 最佳实践

### 1. 内容策略

- **主题规划**：建立主题集群，覆盖用户搜索意图
- **ERE框架**：每篇文章都要有清晰的实体定义、关系建立、证据支撑
- **数据驱动**：用真实数据支撑观点，标注数据来源

### 2. 技术实施

- **Schema标记**：全面部署Schema.org结构化数据
- **多平台适配**：针对不同AI平台优化内容格式
- **性能优化**：确保网站加载速度，提升用户体验

### 3. 监测优化

- **定期监测**：每周记录GEO指标，追踪变化趋势
- **A/B测试**：对比不同策略的效果
- **持续迭代**：根据数据反馈优化内容策略

### 4. 团队协作

- **内容日历**：制定内容发布计划
- **质量审核**：建立内容质量检查清单
- **知识共享**：定期分享GEO最佳实践

## 常见问题

### Q: GEO和SEO有什么区别？

A: SEO关注搜索引擎排名，GEO关注AI引用率。SEO优化网页在搜索结果中的位置，GEO优化品牌在AI答案中的出现。

### Q: 如何衡量GEO效果？

A: 核心指标包括AI引用率、品牌提及率、答案空间覆盖率。使用GEO系统的metrics_tracker模块进行监测。

### Q: 需要多长时间看到效果？

A: 通常需要3-6个月。GEO是长期策略，需要持续的内容建设和信源积累。

### Q: 小型团队如何实施GEO？

A: 建议：
1. 优先建设官网权威
2. 聚焦2-3个核心主题
3. 使用GEO系统自动化内容生成
4. 建立内容复用机制

## 进阶主题

### 自定义提示词

可以修改 `config/prompts/` 目录下的提示词模板，定制内容生成风格。

### 扩展数据源

继承 `RAGEngine` 类，可以接入更多知识数据源。

### 自定义评分规则

修改 `geo_rules.yaml` 配置文件，调整内容评分权重。

## 获取帮助

- 查看示例：`examples/` 目录
- 阅读源码：`core/` 和 `modules/` 目录
- 提交Issue：GitHub Issues
- 联系支持：support@geo-system.com

---

**记住GEO的核心理念：不要争排名，要争引用。**
