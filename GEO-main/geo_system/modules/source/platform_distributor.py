"""
多平台信源分发器
管理内容在不同平台的发布和优化
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class PlatformType(Enum):
    """平台类型"""
    OFFICIAL = "official"           # 官网
    MEDIA = "media"                 # 权威媒体
    COMMUNITY = "community"         # 行业社群
    SOCIAL = "social"               # 社交平台


@dataclass
class PlatformConfig:
    """平台配置"""
    name: str
    platform_type: PlatformType
    content_format: str           # 内容格式要求
    max_length: int               # 最大长度限制
    optimal_length: tuple         # 最佳长度范围
    posting_frequency: str        # 发布频率建议
    best_times: List[str]         # 最佳发布时间
    features: List[str]           # 平台特性
    geo_priority: int             # GEO优先级 (1-10)


@dataclass
class DistributionPlan:
    """分发计划"""
    platform: str
    adapted_content: str
    publish_time: str
    tags: List[str]
    seo_meta: Dict
    expected_reach: int


class PlatformDistributor:
    """
    多平台信源分发器
    
    管理内容在四级信源平台的适配和分发：
    1. 官网 - 数字总部
    2. 权威媒体 - 第三方背书
    3. 行业社群 - 专业圈子
    4. 社交平台 - 公众形象
    """
    
    def __init__(self):
        self.platforms = self._init_platforms()
        self.distribution_history = []
        
    def _init_platforms(self) -> Dict[str, PlatformConfig]:
        """初始化平台配置"""
        return {
            # 官网平台
            "official_blog": PlatformConfig(
                name="官网博客",
                platform_type=PlatformType.OFFICIAL,
                content_format="长文章",
                max_length=10000,
                optimal_length=(2000, 5000),
                posting_frequency="每周2-3篇",
                best_times=["周二 10:00", "周四 14:00"],
                features=["SEO友好", "品牌控制", "深度内容"],
                geo_priority=10
            ),
            
            # 权威媒体
            "36kr": PlatformConfig(
                name="36氪",
                platform_type=PlatformType.MEDIA,
                content_format="商业报道",
                max_length=5000,
                optimal_length=(1500, 3000),
                posting_frequency="每月1-2篇",
                best_times=[["周三 09:00"]],
                features=["科技媒体", "B2B受众", "行业影响力"],
                geo_priority=9
            ),
            "huxiu": PlatformConfig(
                name="虎嗅",
                platform_type=PlatformType.MEDIA,
                content_format="商业分析",
                max_length=4000,
                optimal_length=(1200, 2500),
                posting_frequency="每月1-2篇",
                best_times=[["周一 08:00", "周五 16:00"]],
                features=["商业洞察", "创业者受众", "观点输出"],
                geo_priority=9
            ),
            "tmtpost": PlatformConfig(
                name="钛媒体",
                platform_type=PlatformType.MEDIA,
                content_format="深度报道",
                max_length=6000,
                optimal_length=(2000, 4000),
                posting_frequency="每月1篇",
                best_times=[["周二 10:00"]],
                features=["TMT领域", "专业读者", "深度分析"],
                geo_priority=8
            ),
            
            # 行业社群
            "zhihu": PlatformConfig(
                name="知乎",
                platform_type=PlatformType.COMMUNITY,
                content_format="问答/文章",
                max_length=20000,
                optimal_length=(1000, 3000),
                posting_frequency="每周3-5篇",
                best_times=[["20:00", "21:00"]],
                features=["知识社区", "长尾流量", "专业讨论"],
                geo_priority=8
            ),
            "juejin": PlatformConfig(
                name="掘金",
                platform_type=PlatformType.COMMUNITY,
                content_format="技术文章",
                max_length=15000,
                optimal_length=(1500, 4000),
                posting_frequency="每周2-3篇",
                best_times=[["10:00", "14:00"]],
                features=["开发者社区", "技术导向", "代码分享"],
                geo_priority=7
            ),
            "csdn": PlatformConfig(
                name="CSDN",
                platform_type=PlatformType.COMMUNITY,
                content_format="技术博客",
                max_length=20000,
                optimal_length=(1000, 3000),
                posting_frequency="每周2-3篇",
                best_times=[["09:00", "15:00"]],
                features=["开发者平台", "SEO友好", "技术问答"],
                geo_priority=6
            ),
            
            # 社交平台
            "wechat": PlatformConfig(
                name="微信公众号",
                platform_type=PlatformType.SOCIAL,
                content_format="图文消息",
                max_length=20000,
                optimal_length=(1500, 3000),
                posting_frequency="每周2-3篇",
                best_times=[["07:00", "12:00", "18:00", "21:00"]],
                features=["私域流量", "粉丝经济", "深度阅读"],
                geo_priority=9
            ),
            "weibo": PlatformConfig(
                name="微博",
                platform_type=PlatformType.SOCIAL,
                content_format="短内容/长文",
                max_length=5000,
                optimal_length=(200, 800),
                posting_frequency="每日1-3条",
                best_times=[["08:00", "12:00", "18:00", "21:00"]],
                features=["实时传播", "热点跟进", "互动性强"],
                geo_priority=7
            ),
            "xiaohongshu": PlatformConfig(
                name="小红书",
                platform_type=PlatformType.SOCIAL,
                content_format="图文笔记",
                max_length=1000,
                optimal_length=(300, 800),
                posting_frequency="每周3-5篇",
                best_times=[["08:00", "12:00", "20:00"]],
                features=["种草平台", "年轻用户", "生活方式"],
                geo_priority=6
            ),
            "douyin": PlatformConfig(
                name="抖音",
                platform_type=PlatformType.SOCIAL,
                content_format="短视频文案",
                max_length=500,
                optimal_length=(100, 300),
                posting_frequency="每日1-3条",
                best_times=[["07:00", "12:00", "18:00", "21:00"]],
                features=["短视频", "算法推荐", "娱乐性强"],
                geo_priority=5
            ),
            "linkedin": PlatformConfig(
                name="LinkedIn",
                platform_type=PlatformType.SOCIAL,
                content_format="专业内容",
                max_length=3000,
                optimal_length=(500, 1500),
                posting_frequency="每周2-3篇",
                best_times=[["08:00", "12:00", "17:00"]],
                features=["B2B社交", "职场人群", "国际化"],
                geo_priority=8
            ),
            "twitter": PlatformConfig(
                name="Twitter/X",
                platform_type=PlatformType.SOCIAL,
                content_format="短推文/线程",
                max_length=280,
                optimal_length=(100, 250),
                posting_frequency="每日3-5条",
                best_times=[["08:00", "12:00", "17:00", "20:00"]],
                features=["实时对话", "国际受众", "话题传播"],
                geo_priority=7
            )
        }
    
    def adapt_content(self, original_content: str, target_platform: str) -> Dict:
        """
        为特定平台适配内容
        
        Args:
            original_content: 原始内容
            target_platform: 目标平台
            
        Returns:
            适配后的内容和元数据
        """
        platform = self.platforms.get(target_platform)
        if not platform:
            return {"error": f"未知平台: {target_platform}"}
        
        # 根据平台特性调整内容
        adapted_content = self._apply_platform_rules(original_content, platform)
        
        # 生成平台特定的元数据
        seo_meta = self._generate_seo_meta(adapted_content, platform)
        
        # 生成标签
        tags = self._generate_tags(adapted_content, platform)
        
        return {
            "platform": platform.name,
            "platform_type": platform.platform_type.value,
            "adapted_content": adapted_content,
            "content_length": len(adapted_content),
            "seo_meta": seo_meta,
            "tags": tags,
            "best_publish_time": platform.best_times[0] if platform.best_times else None,
            "geo_priority": platform.geo_priority
        }
    
    def _apply_platform_rules(self, content: str, platform: PlatformConfig) -> str:
        """应用平台适配规则"""
        adapted = content
        
        # 长度调整
        if len(adapted) > platform.max_length:
            adapted = self._truncate_content(adapted, platform.max_length)
        
        # 平台特定格式调整
        if platform.platform_type == PlatformType.SOCIAL:
            adapted = self._adapt_for_social(adapted, platform)
        elif platform.platform_type == PlatformType.MEDIA:
            adapted = self._adapt_for_media(adapted, platform)
        elif platform.platform_type == PlatformType.COMMUNITY:
            adapted = self._adapt_for_community(adapted, platform)
        
        return adapted
    
    def _truncate_content(self, content: str, max_length: int) -> str:
        """截断内容到指定长度"""
        if len(content) <= max_length:
            return content
        
        # 在句子边界截断
        truncated = content[:max_length-100]
        last_period = max(
            truncated.rfind('。'),
            truncated.rfind('.'),
            truncated.rfind('！'),
            truncated.rfind('?')
        )
        
        if last_period > max_length * 0.7:
            return truncated[:last_period + 1] + "\n\n[内容已截断，查看完整版请访问官网]"
        
        return truncated[:max_length-50] + "... [查看完整版]"
    
    def _adapt_for_social(self, content: str, platform: PlatformConfig) -> str:
        """适配社交平台"""
        # 添加话题标签
        if platform.name in ["微博", "Twitter/X"]:
            content = self._add_hashtags(content)
        
        # 添加引导互动
        if len(content) < 500:
            content += "\n\n你怎么看？欢迎在评论区分享你的想法！"
        
        return content
    
    def _adapt_for_media(self, content: str, platform: PlatformConfig) -> str:
        """适配媒体平台"""
        # 添加导语
        if not content.startswith("【"):
            first_para = content.split('\n')[0]
            content = f"【导语】{first_para[:100]}...\n\n{content}"
        
        # 添加作者信息
        content += "\n\n---\n本文仅代表作者观点，不代表平台立场。"
        
        return content
    
    def _adapt_for_community(self, content: str, platform: PlatformConfig) -> str:
        """适配社群平台"""
        # 知乎风格：添加"谢邀"等
        if platform.name == "知乎":
            if not content.startswith(("谢邀", "感谢", "首先")):
                content = "谢邀。\n\n" + content
        
        # 添加互动引导
        content += "\n\n如果对你有帮助，请点赞支持！有问题欢迎在评论区讨论。"
        
        return content
    
    def _add_hashtags(self, content: str) -> str:
        """添加话题标签"""
        # 提取关键词作为标签
        keywords = ["GEO", "AI搜索", "内容营销", "数字化转型"]
        hashtags = " ".join([f"#{kw}" for kw in keywords[:3]])
        return content + f"\n\n{hashtags}"
    
    def _generate_seo_meta(self, content: str, platform: PlatformConfig) -> Dict:
        """生成SEO元数据"""
        # 提取标题
        lines = content.split('\n')
        title = lines[0].replace('#', '').strip() if lines else ""
        
        # 生成描述
        description = ""
        for line in lines[1:]:
            if line.strip() and not line.startswith('#'):
                description = line.strip()[:150]
                break
        
        # 提取关键词
        keywords = self._extract_keywords(content)
        
        return {
            "title": title[:60] if len(title) > 60 else title,
            "description": description,
            "keywords": keywords[:5],
            "platform_specific": self._get_platform_meta(platform)
        }
    
    def _extract_keywords(self, content: str) -> List[str]:
        """提取关键词"""
        # 简化版关键词提取
        geo_keywords = [
            "GEO", "生成式引擎优化", "AI搜索", "内容优化",
            "AI营销", "搜索优化", "内容策略", "品牌可见性"
        ]
        found = [kw for kw in geo_keywords if kw in content]
        return found if found else ["GEO", "AI搜索"]
    
    def _get_platform_meta(self, platform: PlatformConfig) -> Dict:
        """获取平台特定元数据"""
        meta_templates = {
            "微信公众号": {
                "cover_image": "required",
                "summary": "required",
                "author": "required",
                "original": True
            },
            "知乎": {
                "topic_tags": ["人工智能", "搜索引擎优化", "内容运营"],
                "permission": "允许转载",
                "reward": True
            },
            "微博": {
                "visibility": "公开",
                "comment_permission": "所有人",
                "repost": True
            }
        }
        return meta_templates.get(platform.name, {})
    
    def _generate_tags(self, content: str, platform: PlatformConfig) -> List[str]:
        """生成标签"""
        base_tags = ["GEO", "AI搜索", "内容营销"]
        
        # 根据平台添加特定标签
        platform_tags = {
            "微信公众号": ["数字化转型", "营销趋势"],
            "知乎": ["人工智能", "搜索引擎", "互联网"],
            "微博": ["#GEO#", "#AI营销#"],
            "LinkedIn": ["Digital Marketing", "AI", "Content Strategy"]
        }
        
        return base_tags + platform_tags.get(platform.name, [])
    
    def create_distribution_plan(self, content: str, 
                                  platforms: List[str] = None) -> List[DistributionPlan]:
        """
        创建分发计划
        
        Args:
            content: 原始内容
            platforms: 目标平台列表，None表示所有平台
            
        Returns:
            分发计划列表
        """
        if platforms is None:
            # 默认选择高优先级平台
            platforms = [
                name for name, config in self.platforms.items()
                if config.geo_priority >= 7
            ]
        
        plans = []
        for platform_name in platforms:
            adapted = self.adapt_content(content, platform_name)
            
            if "error" not in adapted:
                plan = DistributionPlan(
                    platform=platform_name,
                    adapted_content=adapted["adapted_content"],
                    publish_time=self._schedule_publish_time(platform_name),
                    tags=adapted["tags"],
                    seo_meta=adapted["seo_meta"],
                    expected_reach=self._estimate_reach(platform_name)
                )
                plans.append(plan)
        
        # 按GEO优先级排序
        plans.sort(key=lambda x: self.platforms[x.platform].geo_priority, reverse=True)
        
        return plans
    
    def _schedule_publish_time(self, platform_name: str) -> str:
        """安排发布时间"""
        platform = self.platforms.get(platform_name)
        if platform and platform.best_times:
            return f"下一个{platform.best_times[0]}"
        return "待定"
    
    def _estimate_reach(self, platform_name: str) -> int:
        """估算触达人数"""
        # 基于平台特性的简化估算
        reach_estimates = {
            "微信公众号": 5000,
            "知乎": 3000,
            "微博": 2000,
            "36氪": 10000,
            "虎嗅": 8000,
            "LinkedIn": 1500,
            "官网博客": 1000
        }
        return reach_estimates.get(platform_name, 500)
    
    def get_platform_guide(self, platform_name: str) -> Dict:
        """
        获取平台指南
        
        Args:
            platform_name: 平台名称
            
        Returns:
            平台指南
        """
        platform = self.platforms.get(platform_name)
        if not platform:
            return {"error": "平台不存在"}
        
        return {
            "name": platform.name,
            "type": platform.platform_type.value,
            "content_format": platform.content_format,
            "length_limit": f"{platform.optimal_length[0]}-{platform.optimal_length[1]}字",
            "posting_frequency": platform.posting_frequency,
            "best_times": platform.best_times,
            "key_features": platform.features,
            "geo_priority": platform.geo_priority,
            "content_tips": self._get_content_tips(platform),
            "optimization_checklist": self._get_optimization_checklist(platform)
        }
    
    def _get_content_tips(self, platform: PlatformConfig) -> List[str]:
        """获取内容创作建议"""
        tips_map = {
            PlatformType.OFFICIAL: [
                "保持品牌调性一致性",
                "注重SEO关键词布局",
                "提供深度专业内容"
            ],
            PlatformType.MEDIA: [
                "突出新闻价值和时效性",
                "使用客观中立的语调",
                "提供独特观点和洞察"
            ],
            PlatformType.COMMUNITY: [
                "真诚分享，避免硬广",
                "积极参与讨论互动",
                "建立专业可信形象"
            ],
            PlatformType.SOCIAL: [
                "内容简洁，重点突出",
                "善用表情和视觉元素",
                "引导用户互动分享"
            ]
        }
        return tips_map.get(platform.platform_type, [])
    
    def _get_optimization_checklist(self, platform: PlatformConfig) -> List[Dict]:
        """获取优化检查清单"""
        return [
            {"item": "标题吸引人且包含关键词", "priority": "高"},
            {"item": "内容长度在推荐范围内", "priority": "高"},
            {"item": "添加了适当的标签/话题", "priority": "中"},
            {"item": "包含引导互动的元素", "priority": "中"},
            {"item": "检查了SEO元数据", "priority": "中"},
            {"item": "选择了最佳发布时间", "priority": "低"}
        ]
    
    def analyze_distribution_effect(self, platform_name: str, 
                                     metrics: Dict) -> Dict:
        """
        分析分发效果
        
        Args:
            platform_name: 平台名称
            metrics: 效果指标
            
        Returns:
            效果分析
        """
        platform = self.platforms.get(platform_name)
        
        analysis = {
            "platform": platform_name,
            "metrics": metrics,
            "performance_score": 0,
            "benchmarks": {},
            "suggestions": []
        }
        
        # 计算表现分数
        if "views" in metrics and "engagement" in metrics:
            engagement_rate = metrics["engagement"] / max(metrics["views"], 1)
            analysis["performance_score"] = min(100, engagement_rate * 1000)
        
        # 对比基准
        analysis["benchmarks"] = {
            "avg_views": self._estimate_reach(platform_name),
            "avg_engagement_rate": 0.05
        }
        
        # 生成建议
        if metrics.get("views", 0) < analysis["benchmarks"]["avg_views"]:
            analysis["suggestions"].append("曝光量低于平均水平，考虑优化标题或发布时间")
        
        return analysis


if __name__ == "__main__":
    distributor = PlatformDistributor()
    
    # 测试内容适配
    sample_content = """
# 什么是生成式引擎优化（GEO）

生成式引擎优化（GEO）是一种针对AI搜索引擎的内容优化方法。

## 为什么GEO很重要

根据2024年的研究显示，超过60%的用户开始使用AI搜索。

## 如何实施GEO

首先，你需要理解ERE框架。其次，优化你的内容结构。

## 总结

GEO是未来的趋势。
"""
    
    # 适配到不同平台
    print("=" * 60)
    print("平台内容适配示例")
    print("=" * 60)
    
    for platform in ["wechat", "zhihu", "weibo"]:
        result = distributor.adapt_content(sample_content, platform)
        print(f"\n【{result['platform']}】")
        print(f"内容长度: {result['content_length']} 字符")
        print(f"GEO优先级: {result['geo_priority']}/10")
        print(f"标签: {', '.join(result['tags'][:3])}")
    
    # 创建分发计划
    print("\n" + "=" * 60)
    print("分发计划")
    print("=" * 60)
    
    plans = distributor.create_distribution_plan(
        sample_content,
        platforms=["wechat", "zhihu", "weibo", "linkedin"]
    )
    
    for plan in plans:
        print(f"\n平台: {plan.platform}")
        print(f"预计触达: {plan.expected_reach} 人")
        print(f"发布时间: {plan.publish_time}")
