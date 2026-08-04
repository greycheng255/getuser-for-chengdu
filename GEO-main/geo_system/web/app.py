"""
GEO系统Web应用
基于Streamlit的交互式界面
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import streamlit as st
import json
from datetime import datetime

# 设置页面配置
st.set_page_config(
    page_title="GEO内容工程系统",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 导入核心模块
from core.content_generator import GEOArticleGenerator
from core.content_optimizer import GEOContentOptimizer
from utils.content_analyzer import ContentAnalyzer
from modules.data.metrics_tracker import GEOMetricsTracker, GEOMetrics
from modules.data.roi_calculator import ROICalculator
from modules.source.authority_builder import AuthorityBuilder


def init_session_state():
    """初始化session state"""
    if 'generated_content' not in st.session_state:
        st.session_state.generated_content = None
    if 'analysis_result' not in st.session_state:
        st.session_state.analysis_result = None
    if 'optimization_result' not in st.session_state:
        st.session_state.optimization_result = None


def render_sidebar():
    """渲染侧边栏"""
    with st.sidebar:
        st.title("🚀 GEO系统")
        st.markdown("---")
        
        # 导航
        page = st.radio(
            "功能导航",
            ["🏠 首页", "✍️ 内容生成", "🔍 内容分析", "⚡ 内容优化", 
             "📊 数据监测", "💰 ROI计算", "🏛️ 信源建设", "📚 使用指南"]
        )
        
        st.markdown("---")
        st.markdown("### 关于")
        st.markdown("GEO内容工程系统 v1.0.0")
        st.markdown("基于姚金刚GEO方法论")
        
        return page


def render_home():
    """渲染首页"""
    st.title("🚀 GEO内容工程系统")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("AI引用率", "45.5%", "+5.5%")
    with col2:
        st.metric("品牌提及率", "60.0%", "+5.0%")
    with col3:
        st.metric("综合可见性", "65.5", "+5.5")
    
    st.markdown("---")
    
    st.markdown("""
    ## 系统概述
    
    GEO（Generative Engine Optimization）内容工程系统是一套面向AI搜索时代的内容优化解决方案。
    
    ### 核心功能
    
    - **📝 内容生成**：基于ERE框架智能生成GEO优化内容
    - **🔍 内容分析**：全面评估内容质量和GEO合规性
    - **⚡ 内容优化**：自动优化提升AI引用率
    - **📊 数据监测**：追踪GEO指标和效果
    - **💰 ROI计算**：评估GEO投资回报
    - **🏛️ 信源建设**：构建四级权威信源体系
    
    ### 快速开始
    
    1. 在侧边栏选择功能
    2. 填写必要信息
    3. 获取GEO优化结果
    
    ### 核心理念
    
    > **不要争排名，要争引用。**
    """)
    
    # 显示系统状态
    st.markdown("---")
    st.subheader("系统状态")
    
    status_col1, status_col2, status_col3, status_col4 = st.columns(4)
    
    with status_col1:
        st.info("✅ 内容生成器")
    with status_col2:
        st.info("✅ 内容分析器")
    with status_col3:
        st.info("✅ 数据监测")
    with status_col4:
        st.info("✅ 信源建设")


def render_content_generator():
    """渲染内容生成页面"""
    st.title("✍️ GEO内容生成")
    
    st.markdown("生成基于ERE框架的GEO优化文章大纲")
    
    with st.form("content_generation_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            title = st.text_input("文章标题", placeholder="输入文章标题")
            brand_name = st.text_input("品牌名称", placeholder="你的品牌名")
            industry = st.text_input("所属行业", value="AI营销")
        
        with col2:
            expertise = st.text_area("专业领域", placeholder="每行一个领域", 
                                    value="GEO\nAI搜索优化\n内容营销")
            target_platform = st.selectbox(
                "目标平台",
                ["chatgpt", "perplexity", "google_ai", "kimi", "doubao"]
            )
            word_count = st.slider("目标字数", 1000, 5000, 3000, 500)
        
        submitted = st.form_submit_button("🚀 生成内容大纲", use_container_width=True)
    
    if submitted and title and brand_name:
        with st.spinner("正在生成GEO优化内容大纲..."):
            try:
                generator = GEOArticleGenerator()
                
                brand_info = {
                    "name": brand_name,
                    "industry": industry,
                    "expertise": [e.strip() for e in expertise.split('\n') if e.strip()]
                }
                
                result = generator.generate(
                    title=title,
                    brand_info=brand_info,
                    target_platform=target_platform,
                    word_count=word_count
                )
                
                st.session_state.generated_content = result
                
                st.success("✅ 内容生成成功！")
                
            except Exception as e:
                st.error(f"生成失败: {e}")
    
    # 显示生成结果
    if st.session_state.generated_content:
        result = st.session_state.generated_content
        
        st.markdown("---")
        st.subheader("📄 生成结果")
        
        # 显示大纲
        st.markdown("#### 文章大纲")
        for item in result['outline']:
            indent = "&nbsp;&nbsp;&nbsp;&nbsp;" * (item['level'] - 1)
            if item['level'] == 1:
                st.markdown(f"{indent}**📌 {item['title']}**")
            elif item['level'] == 2:
                st.markdown(f"{indent}▸ {item['title']}")
            else:
                st.markdown(f"{indent}• {item['title']}")
        
        # 显示提示词
        with st.expander("查看完整提示词"):
            st.text_area("Prompt", result['prompt'], height=300)
        
        # 下载按钮
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "📥 下载大纲(JSON)",
                json.dumps(result['outline'], ensure_ascii=False, indent=2),
                file_name=f"geo_outline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
        with col2:
            st.download_button(
                "📥 下载提示词",
                result['prompt'],
                file_name=f"geo_prompt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            )


def render_content_analyzer():
    """渲染内容分析页面"""
    st.title("🔍 内容质量分析")
    
    st.markdown("分析内容的GEO合规性和质量得分")
    
    content = st.text_area(
        "输入要分析的内容",
        height=300,
        placeholder="在这里粘贴你的文章内容..."
    )
    
    if st.button("🔍 开始分析", use_container_width=True) and content:
        with st.spinner("正在分析内容质量..."):
            try:
                analyzer = ContentAnalyzer()
                result = analyzer.analyze(content)
                
                st.session_state.analysis_result = result
                
            except Exception as e:
                st.error(f"分析失败: {e}")
    
    # 显示分析结果
    if st.session_state.analysis_result:
        result = st.session_state.analysis_result
        
        st.markdown("---")
        st.subheader("📊 分析结果")
        
        # 总体得分
        score_col1, score_col2, score_col3 = st.columns(3)
        
        with score_col1:
            st.metric("整体得分", f"{result.overall_score:.1f}", "")
        with score_col2:
            st.metric("GEO合规性", f"{result.geo_compliance:.1f}", "")
        with score_col3:
            grade = "优秀" if result.overall_score >= 80 else "良好" if result.overall_score >= 60 else "需改进"
            st.metric("评级", grade, "")
        
        # 详细得分
        st.markdown("#### 详细得分")
        
        detail_col1, detail_col2, detail_col3 = st.columns(3)
        
        with detail_col1:
            st.progress(result.structure_score / 100)
            st.caption(f"结构得分: {result.structure_score:.1f}")
            
            st.progress(result.citation_score / 100)
            st.caption(f"引用得分: {result.citation_score:.1f}")
        
        with detail_col2:
            st.progress(result.readability_score / 100)
            st.caption(f"可读性得分: {result.readability_score:.1f}")
            
            st.progress(result.authority_score / 100)
            st.caption(f"权威性得分: {result.authority_score:.1f}")
        
        with detail_col3:
            # 雷达图数据
            chart_data = {
                "维度": ["结构", "引用", "可读性", "权威性", "合规性"],
                "得分": [
                    result.structure_score,
                    result.citation_score,
                    result.readability_score,
                    result.authority_score,
                    result.geo_compliance
                ]
            }
            st.bar_chart(chart_data, x="维度", y="得分", height=200)
        
        # 问题和建议
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### ⚠️ 发现的问题")
            if result.issues:
                for issue in result.issues[:5]:
                    st.warning(issue)
            else:
                st.success("未发现明显问题")
        
        with col2:
            st.markdown("#### 💡 优化建议")
            if result.suggestions:
                for suggestion in result.suggestions[:5]:
                    st.info(suggestion)
            else:
                st.success("内容质量良好，无需优化")


def render_content_optimizer():
    """渲染内容优化页面"""
    st.title("⚡ 内容优化")
    
    st.markdown("自动优化内容，提升GEO合规性")
    
    content = st.text_area(
        "输入要优化的内容",
        height=300,
        placeholder="在这里粘贴需要优化的内容..."
    )
    
    optimization_level = st.select_slider(
        "优化级别",
        options=["light", "medium", "heavy"],
        value="medium",
        format_func=lambda x: {"light": "轻度", "medium": "中度", "heavy": "重度"}[x]
    )
    
    if st.button("⚡ 开始优化", use_container_width=True) and content:
        with st.spinner("正在优化内容..."):
            try:
                optimizer = GEOContentOptimizer()
                result = optimizer.optimize(content, optimization_level)
                
                st.session_state.optimization_result = result
                
            except Exception as e:
                st.error(f"优化失败: {e}")
    
    # 显示优化结果
    if st.session_state.optimization_result:
        result = st.session_state.optimization_result
        
        st.markdown("---")
        st.subheader("✨ 优化结果")
        
        # 得分对比
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("优化前", f"{result.score_before:.1f}")
        with col2:
            improvement = result.score_after - result.score_before
            st.metric("优化后", f"{result.score_after:.1f}", f"+{improvement:.1f}")
        with col3:
            improvement_pct = (improvement / max(result.score_before, 1)) * 100
            st.metric("提升幅度", f"{improvement_pct:.1f}%")
        
        # 改进项
        if result.improvements:
            st.markdown("#### 📝 改进内容")
            for improvement in result.improvements:
                st.success(improvement)
        
        # 优化后的内容
        st.markdown("#### 📄 优化后的内容")
        st.text_area("", result.optimized_content, height=300)
        
        # 下载按钮
        st.download_button(
            "📥 下载优化后的内容",
            result.optimized_content,
            file_name=f"optimized_content_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )


def render_metrics_tracker():
    """渲染数据监测页面"""
    st.title("📊 GEO数据监测")
    
    st.markdown("记录和追踪GEO关键指标")
    
    # 输入指标
    st.subheader("📝 记录今日指标")
    
    col1, col2 = st.columns(2)
    
    with col1:
        ai_citation = st.number_input("AI引用次数", min_value=0, value=0)
        brand_mention = st.number_input("品牌提及次数", min_value=0, value=0)
        coverage = st.slider("答案空间覆盖率", 0.0, 1.0, 0.5)
    
    with col2:
        diversity = st.slider("信源多样性得分", 0.0, 1.0, 0.7)
        quality = st.slider("内容质量得分", 0.0, 1.0, 0.8)
    
    if st.button("💾 记录指标", use_container_width=True):
        with st.spinner("正在记录..."):
            try:
                tracker = GEOMetricsTracker()
                
                metrics = GEOMetrics(
                    date=datetime.now().isoformat(),
                    ai_citation_count=ai_citation,
                    brand_mention_count=brand_mention,
                    answer_space_coverage=coverage,
                    source_diversity_score=diversity,
                    content_quality_score=quality,
                    citations_by_platform={},
                    mentions_by_source={},
                    top_queries=[]
                )
                
                tracker.record_metrics(metrics)
                st.success("✅ 指标记录成功！")
                
            except Exception as e:
                st.error(f"记录失败: {e}")
    
    # 显示报告
    st.markdown("---")
    st.subheader("📈 查看报告")
    
    report_type = st.selectbox("报告类型", ["daily", "weekly", "monthly"])
    
    if st.button("📊 生成报告", use_container_width=True):
        with st.spinner("正在生成报告..."):
            try:
                tracker = GEOMetricsTracker()
                report = tracker.generate_report(report_type)
                
                # 显示关键指标
                st.markdown("#### 核心指标")
                
                metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
                
                with metric_col1:
                    st.metric("AI引用率", 
                             f"{report['basic_metrics']['ai_citation_rate']['current']:.1f}",
                             f"{report['basic_metrics']['ai_citation_rate']['change']:+.1f}")
                
                with metric_col2:
                    st.metric("品牌提及率", 
                             f"{report['basic_metrics']['brand_mention_rate']['current']:.1f}",
                             f"{report['basic_metrics']['brand_mention_rate']['change']:+.1f}")
                
                with metric_col3:
                    st.metric("答案空间覆盖", 
                             f"{report['basic_metrics']['answer_space_coverage']['current']:.1%}",
                             f"{report['basic_metrics']['answer_space_coverage']['change']:+.1%}")
                
                with metric_col4:
                    st.metric("综合可见性", 
                             f"{report['basic_metrics']['visibility_score']['current']:.1f}",
                             f"{report['basic_metrics']['visibility_score']['change']:+.1f}")
                
                # 优化建议
                if report['recommendations']:
                    st.markdown("#### 💡 优化建议")
                    for rec in report['recommendations'][:3]:
                        priority_emoji = "🔴" if rec['priority'] == 'high' else "🟡" if rec['priority'] == 'medium' else "🟢"
                        st.info(f"{priority_emoji} {rec['suggestion']}")
                
            except Exception as e:
                st.error(f"生成报告失败: {e}")


def render_roi_calculator():
    """渲染ROI计算页面"""
    st.title("💰 GEO ROI计算")
    
    st.markdown("计算GEO策略的投资回报率")
    
    with st.form("roi_form"):
        st.subheader("📊 投资参数")
        
        col1, col2 = st.columns(2)
        
        with col1:
            content_investment = st.number_input("内容投资 (¥)", min_value=0, value=50000, step=10000)
            tech_investment = st.number_input("技术投资 (¥)", min_value=0, value=30000, step=10000)
            personnel_investment = st.number_input("人力投资 (¥)", min_value=0, value=80000, step=10000)
        
        with col2:
            citation_increase = st.slider("AI引用率提升 (%)", 0, 100, 40)
            conversion_rate = st.slider("转化率 (%)", 0.0, 10.0, 2.5, 0.1)
            customer_value = st.number_input("平均客户价值 (¥)", min_value=0, value=5000, step=1000)
        
        submitted = st.form_submit_button("🧮 计算ROI", use_container_width=True)
    
    if submitted:
        with st.spinner("正在计算ROI..."):
            try:
                calculator = ROICalculator()
                
                params = {
                    'content_investment': content_investment,
                    'technology_investment': tech_investment,
                    'personnel_investment': personnel_investment,
                    'ai_citation_increase': citation_increase,
                    'brand_mention_increase': citation_increase * 0.875,
                    'conversion_rate': conversion_rate,
                    'avg_customer_value': customer_value,
                    'time_period_months': 12
                }
                
                result = calculator.calculate_basic_roi(params)
                
                st.markdown("---")
                st.subheader("📈 ROI分析结果")
                
                # 关键指标
                result_col1, result_col2, result_col3 = st.columns(3)
                
                with result_col1:
                    st.metric("总投资", f"¥{result['total_investment']:,.0f}")
                    st.metric("预期收益", f"¥{result['revenue']:,.0f}")
                
                with result_col2:
                    st.metric("净收益", f"¥{result['net_profit']:,.0f}")
                    st.metric("ROI", f"{result['roi_percentage']:.1f}%")
                
                with result_col3:
                    st.metric("回收期", f"{result['payback_period_months']:.1f}个月")
                    st.metric("新客户", f"{result['new_customers']:.0f}")
                
                # ROI评估
                st.markdown("#### 📊 ROI评估")
                
                if result['roi_percentage'] >= 200:
                    st.success("🌟 优秀的投资回报！建议立即实施。")
                elif result['roi_percentage'] >= 100:
                    st.success("✅ 良好的投资回报，值得实施。")
                elif result['roi_percentage'] >= 50:
                    st.warning("⚠️ 中等回报，建议优化参数后实施。")
                else:
                    st.error("❌ 回报较低，建议重新评估策略。")
                
            except Exception as e:
                st.error(f"计算失败: {e}")


def render_authority_builder():
    """渲染信源建设页面"""
    st.title("🏛️ 信源权威建设")
    
    st.markdown("构建四级信源权威体系")
    
    # 显示信源金字塔
    st.subheader("📊 四级信源权威金字塔")
    
    builder = AuthorityBuilder()
    pyramid = builder.get_authority_pyramid()
    
    # 使用列显示金字塔
    col1, col2, col3, col4 = st.columns(4)
    
    levels = pyramid['levels']
    
    with col1:
        st.info(f"**一级**\n\n{levels['1']['name']}\n\n权重: {levels['1']['weight']}")
    
    with col2:
        st.success(f"**二级**\n\n{levels['2']['name']}\n\n权重: {levels['2']['weight']}")
    
    with col3:
        st.warning(f"**三级**\n\n{levels['3']['name']}\n\n权重: {levels['3']['weight']}")
    
    with col4:
        st.error(f"**四级**\n\n{levels['4']['name']}\n\n权重: {levels['4']['weight']}")
    
    # 官网建设方案
    st.markdown("---")
    st.subheader("🏢 官网权威化改造")
    
    with st.form("authority_form"):
        brand_name = st.text_input("品牌名称", placeholder="你的品牌")
        brand_url = st.text_input("官网URL", placeholder="https://example.com")
        brand_desc = st.text_area("品牌描述", placeholder="简要描述你的品牌")
        
        submitted = st.form_submit_button("📋 生成改造方案", use_container_width=True)
    
    if submitted and brand_name and brand_url:
        with st.spinner("正在生成方案..."):
            try:
                brand_info = {
                    "name": brand_name,
                    "url": brand_url,
                    "description": brand_desc
                }
                
                plan = builder.build_official_site_authority(brand_info)
                
                st.markdown("#### 📋 改造方案")
                
                for component_name, component in plan['components'].items():
                    with st.expander(f"{component['name']} ({len(component['tasks'])}项任务)"):
                        for task in component['tasks']:
                            st.checkbox(task, key=f"{component_name}_{task}")
                
            except Exception as e:
                st.error(f"生成方案失败: {e}")


def render_guide():
    """渲染使用指南页面"""
    st.title("📚 使用指南")
    
    st.markdown("""
    ## GEO系统使用指南
    
    ### 什么是GEO？
    
    GEO（Generative Engine Optimization，生成式引擎优化）是一种针对AI搜索引擎的内容优化方法。
    
    与传统SEO关注排名不同，GEO关注的是**品牌在AI答案中的引用率**。
    
    ### 核心概念
    
    #### ERE框架
    
    - **Entity（实体）**：明确的品牌、产品、概念定义
    - **Relation（关系）**：实体之间的逻辑关联
    - **Evidence（证据）**：数据、案例、研究支撑
    
    #### 四级信源权威体系
    
    1. **一级**：官网、官方文档（权重40%）
    2. **二级**：权威媒体、行业报告（权重30%）
    3. **三级**：行业社区、专业平台（权重20%）
    4. **四级**：社交媒体、UGC内容（权重10%）
    
    ### 使用流程
    
    1. **内容生成**：使用"内容生成"功能创建GEO优化文章大纲
    2. **内容分析**：使用"内容分析"评估现有内容质量
    3. **内容优化**：使用"内容优化"自动改进内容
    4. **数据监测**：定期记录GEO指标，追踪效果
    5. **ROI计算**：评估GEO投资回报
    6. **信源建设**：构建四级权威信源体系
    
    ### 最佳实践
    
    - 每篇文章都要遵循ERE框架
    - 使用具体数据支撑观点
    - 引用权威来源
    - 定期监测指标变化
    - 持续优化内容质量
    
    ### 评分标准
    
    | 分数 | 评级 | 说明 |
    |------|------|------|
    | 90-100 | 优秀 | 内容质量极佳 |
    | 80-89 | 良好 | 质量较好，少量优化空间 |
    | 60-79 | 合格 | 基本符合要求 |
    | 40-59 | 待改进 | 需要大幅优化 |
    | 0-39 | 不合格 | 建议重写 |
    
    ### 核心理念
    
    > **不要争排名，要争引用。**
    
    GEO的目标是让AI在回答用户问题时引用你的品牌，而不是仅仅在搜索结果中显示你的网站。
    """)


def create_web_app():
    """创建Web应用"""
    init_session_state()
    
    page = render_sidebar()
    
    if "首页" in page:
        render_home()
    elif "内容生成" in page:
        render_content_generator()
    elif "内容分析" in page:
        render_content_analyzer()
    elif "内容优化" in page:
        render_content_optimizer()
    elif "数据监测" in page:
        render_metrics_tracker()
    elif "ROI计算" in page:
        render_roi_calculator()
    elif "信源建设" in page:
        render_authority_builder()
    elif "使用指南" in page:
        render_guide()


if __name__ == "__main__":
    create_web_app()
