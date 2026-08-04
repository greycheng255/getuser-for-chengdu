"""
平台内容适配器
为不同社交媒体平台生成适配的内容
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class PlatformType(Enum):
    """平台类型"""
    XIAOHONGSHU = "xiaohongshu"      # 小红书 - 图文/短视频
    DOUYIN = "douyin"                # 抖音 - 短视频
    ZHIHU = "zhihu"                  # 知乎 - 长文/问答
    WEIBO = "weibo"                  # 微博 - 短文/图文
    WECHAT = "wechat"                # 微信公众号 - 长文
    BILIBILI = "bilibili"            # B站 - 视频/图文
    KUAISHOU = "kuaishou"            # 快手 - 短视频
    TOUTIAO = "toutiao"              # 今日头条 - 文章/微头条


@dataclass
class PlatformConfig:
    """平台配置"""
    name: str                          # 平台名称
    name_cn: str                       # 中文名称
    content_type: str                  # 内容类型：article/image/video/mixed
    max_title_length: int              # 标题最大长度
    max_content_length: int            # 内容最大长度
    max_images: int                    # 最大图片数
    hashtag_style: str                 # 标签风格：#话题# / #话题 / #话题#
    support_topics: bool               # 是否支持话题标签
    support_mentions: bool             # 是否支持@提及
    support_links: bool                # 是否支持外链
    tone_style: str                    # 语气风格
    emoji_support: bool                # 是否支持表情
    structure_template: str            # 结构模板
    content_restrictions: Dict = None  # 内容限制规则（可选）


# 平台配置字典
PLATFORM_CONFIGS = {
    PlatformType.XIAOHONGSHU: PlatformConfig(
        name="xiaohongshu",
        name_cn="小红书",
        content_type="mixed",
        max_title_length=20,
        max_content_length=1000,
        max_images=18,
        hashtag_style="#话题#",
        support_topics=True,
        support_mentions=True,
        support_links=False,
        tone_style="亲切、真实、种草、分享",
        emoji_support=True,
        structure_template="""
标题（20字内，吸引眼球，避免夸张和绝对化用词）

正文：
- 开头：场景引入/痛点共鸣（1-2句，自然真实）
- 中间：经验分享/产品种草（3-5点，具体细节）
- 结尾：互动引导/CTA（真诚互动，避免诱导）

标签：#关键词# #相关话题#
""",
        # 小红书社区规范约束
        content_restrictions={
            "forbidden_words": [
                # 绝对化用语
                "最好", "第一", "顶级", "最强", "极致", "完美", "绝对", "100%", "百分之百",
                "万能", "神器", "必买", "必入", "闭眼入", "无脑冲", "冲就完了",
                # 夸张宣传
                "逆天", "炸裂", "绝了", "封神", "yyds", "永远的神", "天花板",
                "碾压", "吊打", "秒杀", "碾压级", "降维打击",
                # 诱导性用语
                "不看后悔", "错过等一年", "最后机会", "限时", "倒计时",
                "赶紧", "立刻", "马上", "马上抢", "手慢无",
                # 医疗/功效夸大
                "治愈", "根治", "特效", "神效", "立竿见影", "药到病除",
                "美白", "祛斑", "祛痘", "抗衰老", "逆龄", "瘦身", "减肥",
                # 违规营销
                "代购", "微商", "代理", "加盟", "躺赚", "暴利", "稳赚",
                # 敏感政治/社会
                "政府", "国家", "机关", "领导人", "政治", "革命", "运动",
            ],
            "sensitive_topics": [
                "政治", "宗教", "色情", "暴力", "赌博", "毒品", "枪支",
                "医疗诊断", "药品推荐", "投资理财", "金融诈骗",
            ],
            "max_hashtags": 5,
            "min_content_length": 50,
            "title_requirements": [
                "避免使用感叹号连续出现（不超过1个）",
                "避免使用全部大写字母",
                "避免使用过多表情符号（不超过2个）",
                "标题应真实反映内容，避免标题党",
            ],
            "content_requirements": [
                "内容需原创或经过充分改编，避免直接复制",
                "避免过度营销和硬广，保持分享感",
                "图片需清晰、真实，避免过度P图",
                "避免在内容中放置二维码、微信号、手机号等联系方式",
                "避免诱导分享、诱导关注、诱导点赞",
                "尊重知识产权，避免侵权内容",
            ],
        }
    ),
    PlatformType.DOUYIN: PlatformConfig(
        name="douyin",
        name_cn="抖音",
        content_type="video",
        max_title_length=55,
        max_content_length=500,
        max_images=0,
        hashtag_style="#话题",
        support_topics=True,
        support_mentions=True,
        support_links=True,
        tone_style="轻松、有趣、抓眼球、节奏快",
        emoji_support=True,
        structure_template="""
视频脚本：
- 开头（3秒）：黄金3秒，吸引注意
- 中间（15-30秒）：内容展开，价值输出
- 结尾（3秒）：引导互动/关注

文案（55字内）：
- 悬念/痛点开头
- 核心信息
- 话题标签
"""
    ),
    PlatformType.ZHIHU: PlatformConfig(
        name="zhihu",
        name_cn="知乎",
        content_type="article",
        max_title_length=50,
        max_content_length=50000,
        max_images=20,
        hashtag_style="无",
        support_topics=False,
        support_mentions=True,
        support_links=True,
        tone_style="专业、理性、深度、客观",
        emoji_support=False,
        structure_template="""
标题（疑问句/干货型）：

正文结构：
- 引言：问题背景/个人经历
- 目录：文章大纲
- 正文：分点论述，数据支撑
- 总结：核心观点回顾
- 参考文献：权威来源
"""
    ),
    PlatformType.WEIBO: PlatformConfig(
        name="weibo",
        name_cn="微博",
        content_type="mixed",
        max_title_length=0,
        max_content_length=5000,
        max_images=18,
        hashtag_style="#话题#",
        support_topics=True,
        support_mentions=True,
        support_links=True,
        tone_style="轻松、热点、互动性强",
        emoji_support=True,
        structure_template="""
文案（简短有力）：
- 热点关联/观点表达
- 核心信息
- @相关账号
- #话题标签#
"""
    ),
    PlatformType.WECHAT: PlatformConfig(
        name="wechat",
        name_cn="微信公众号",
        content_type="article",
        max_title_length=64,
        max_content_length=20000,
        max_images=50,
        hashtag_style="无",
        support_topics=False,
        support_mentions=False,
        support_links=True,
        tone_style="专业、深度、品牌调性",
        emoji_support=True,
        structure_template="""
标题（吸引点击）：

封面图：

正文：
- 导语：引入话题
- 正文：分段论述，图文并茂
- 小结：核心观点
- 引导：关注/转发/阅读原文
"""
    ),
    PlatformType.BILIBILI: PlatformConfig(
        name="bilibili",
        name_cn="B站",
        content_type="video",
        max_title_length=80,
        max_content_length=2000,
        max_images=0,
        hashtag_style="无",
        support_topics=False,
        support_mentions=False,
        support_links=True,
        tone_style="年轻、有趣、二次元、硬核",
        emoji_support=True,
        structure_template="""
视频标题：

视频简介：
- 视频内容概述
- 时间节点（可选）
- 相关链接
- 互动引导（一键三连）
"""
    ),
    PlatformType.KUAISHOU: PlatformConfig(
        name="kuaishou",
        name_cn="快手",
        content_type="video",
        max_title_length=55,
        max_content_length=500,
        max_images=0,
        hashtag_style="#话题",
        support_topics=True,
        support_mentions=True,
        support_links=True,
        tone_style="真实、接地气、生活化",
        emoji_support=True,
        structure_template="""
视频脚本：
- 开头：真实场景，快速入题
- 中间：内容展示，情感共鸣
- 结尾：互动引导

文案：
- 生活化表达
- 情感共鸣点
- 话题标签
"""
    ),
    PlatformType.TOUTIAO: PlatformConfig(
        name="toutiao",
        name_cn="今日头条",
        content_type="article",
        max_title_length=30,
        max_content_length=20000,
        max_images=20,
        hashtag_style="#话题#",
        support_topics=True,
        support_mentions=False,
        support_links=True,
        tone_style="客观、信息量大、易读",
        emoji_support=True,
        structure_template="""
标题（悬念/数字/对比）：

正文：
- 导语：核心信息前置
- 正文：分段论述
- 配图：相关图片
- 话题标签
"""
    ),
}


class PlatformContentAdapter:
    """平台内容适配器"""
    
    def __init__(self):
        self.configs = PLATFORM_CONFIGS
    
    def get_platform_config(self, platform: str) -> PlatformConfig:
        """获取平台配置"""
        platform_enum = PlatformType(platform.lower()) if isinstance(platform, str) else platform
        return self.configs.get(platform_enum, self.configs[PlatformType.XIAOHONGSHU])
    
    def adapt_content(self, original_content: str, platform: str, 
                     keywords: List[str] = None) -> Dict[str, Any]:
        """
        将通用内容适配为平台特定格式
        
        Args:
            original_content: 原始内容
            platform: 目标平台
            keywords: 关键词列表
            
        Returns:
            适配后的内容字典
        """
        config = self.get_platform_config(platform)
        
        # 根据平台类型选择适配策略
        if config.content_type == "article":
            return self._adapt_article(original_content, config, keywords)
        elif config.content_type == "video":
            return self._adapt_video(original_content, config, keywords)
        elif config.content_type == "mixed":
            return self._adapt_mixed(original_content, config, keywords)
        else:
            return self._adapt_article(original_content, config, keywords)
    
    def _adapt_article(self, content: str, config: PlatformConfig, 
                      keywords: List[str]) -> Dict[str, Any]:
        """适配文章类平台"""
        return {
            "platform": config.name_cn,
            "content_type": "article",
            "title_max_length": config.max_title_length,
            "content_max_length": config.max_content_length,
            "max_images": config.max_images,
            "tone_style": config.tone_style,
            "structure_template": config.structure_template,
            "adaptation_prompt": self._generate_adaptation_prompt(content, config, keywords)
        }
    
    def _adapt_video(self, content: str, config: PlatformConfig, 
                    keywords: List[str]) -> Dict[str, Any]:
        """适配视频类平台"""
        return {
            "platform": config.name_cn,
            "content_type": "video",
            "title_max_length": config.max_title_length,
            "content_max_length": config.max_content_length,
            "max_images": 0,
            "tone_style": config.tone_style,
            "structure_template": config.structure_template,
            "adaptation_prompt": self._generate_video_prompt(content, config, keywords)
        }
    
    def _adapt_mixed(self, content: str, config: PlatformConfig, 
                    keywords: List[str]) -> Dict[str, Any]:
        """适配混合类平台（图文）"""
        return {
            "platform": config.name_cn,
            "content_type": "mixed",
            "title_max_length": config.max_title_length,
            "content_max_length": config.max_content_length,
            "max_images": config.max_images,
            "tone_style": config.tone_style,
            "structure_template": config.structure_template,
            "adaptation_prompt": self._generate_mixed_prompt(content, config, keywords)
        }
    
    def _generate_adaptation_prompt(self, content: str, config: PlatformConfig, 
                                   keywords: List[str]) -> str:
        """生成内容适配提示词"""
        keyword_str = ', '.join(keywords[:5]) if keywords else "根据内容提取"
        
        return f"""# 平台内容适配任务

## 原始内容
{content[:1000]}...

## 目标平台
- 平台：{config.name_cn}
- 内容类型：{config.content_type}
- 语气风格：{config.tone_style}

## 限制条件
- 标题长度：{config.max_title_length}字以内
- 内容长度：{config.max_content_length}字以内
- 最大图片数：{config.max_images}张
- 标签格式：{config.hashtag_style}

## 关键词
{keyword_str}

## 适配要求
1. 根据平台特性调整语气风格
2. 优化标题，符合平台用户喜好
3. 调整内容结构，适应平台阅读习惯
4. 添加合适的话题标签（{config.hashtag_style}格式）
5. 控制字数在限制范围内

## 输出格式
请按以下格式输出适配后的内容：

**标题**：
（{config.max_title_length}字以内）

**正文**：
（{config.max_content_length}字以内，分段清晰）

**建议图片**：
（描述需要配什么样的图片，{config.max_images}张以内）

**话题标签**：
（{config.hashtag_style}格式，3-5个）

**发布建议**：
（最佳发布时间、互动策略等）
"""
    
    def _generate_video_prompt(self, content: str, config: PlatformConfig, 
                              keywords: List[str]) -> str:
        """生成视频脚本提示词"""
        keyword_str = ', '.join(keywords[:5]) if keywords else "根据内容提取"
        
        return f"""# 视频脚本生成任务

## 原始内容
{content[:1000]}...

## 目标平台
- 平台：{config.name_cn}
- 内容类型：短视频
- 语气风格：{config.tone_style}

## 限制条件
- 标题长度：{config.max_title_length}字以内
- 文案长度：{config.max_content_length}字以内
- 标签格式：{config.hashtag_style}

## 关键词
{keyword_str}

## 脚本要求
1. 黄金3秒开头，快速吸引注意
2. 内容节奏快，信息密度高
3. 适合{config.name_cn}平台风格
4. 有明确的互动引导

## 输出格式

**视频标题**：
（{config.max_title_length}字以内，吸引点击）

**视频脚本**：
- 开头（0-3秒）：
- 中间（3-30秒）：
- 结尾（最后3秒）：

**画面描述**：
（每个镜头配什么画面）

**文案/字幕**：
（{config.max_content_length}字以内）

**话题标签**：
（{config.hashtag_style}格式）

**BGM建议**：
（适合的音乐风格）
"""
    
    def _generate_mixed_prompt(self, content: str, config: PlatformConfig, 
                              keywords: List[str]) -> str:
        """生成图文混合提示词"""
        keyword_str = ', '.join(keywords[:5]) if keywords else "根据内容提取"
        
        # 小红书特殊规范提示
        xiaohongshu_rules = ""
        if config.name == "xiaohongshu" and config.content_restrictions:
            restrictions = config.content_restrictions
            forbidden_words = restrictions.get("forbidden_words", [])
            sensitive_topics = restrictions.get("sensitive_topics", [])
            title_reqs = restrictions.get("title_requirements", [])
            content_reqs = restrictions.get("content_requirements", [])
            
            xiaohongshu_rules = f"""

## ⚠️ 小红书社区规范（必须遵守）

### 禁止使用的词汇
{chr(10).join([f"- {w}" for w in forbidden_words[:15]])}
...等夸张、绝对化、诱导性词汇

### 敏感话题（避免涉及）
{chr(10).join([f"- {t}" for t in sensitive_topics])}

### 标题规范
{chr(10).join([f"- {r}" for r in title_reqs])}

### 内容规范
{chr(10).join([f"- {r}" for r in content_reqs])}

### 合规建议
- 使用真实、自然的分享语气，像朋友间推荐
- 避免过度营销感，减少"必买""神器"等词汇
- 多使用个人体验描述："我用了一段时间""感觉还不错"
- 适当提及小缺点或适用人群，增加真实感
- 标签数量控制在{restrictions.get('max_hashtags', 5)}个以内
- 内容长度不少于{restrictions.get('min_content_length', 50)}字

### 内容质量要求（重要！）
- **避免硬广**：不要直接放网址、联系方式、价格信息
- **真实体验**：分享真实使用体验，包括优点和 minor 缺点
- **具体细节**：提供具体的场景、数据、对比，避免空泛描述
- **视觉价值**：图片要有美感、信息量，避免纯文字图片或低质量截图
- **互动引导**：用真诚的提问引导互动，避免"求点赞""求关注"
- **价值输出**：每篇笔记要让读者获得实用信息或情感共鸣
- **个人化**：加入个人经历、感受、故事，避免像官方账号
"""
        
        return f"""# 图文内容生成任务

## 原始内容
{content[:1000]}...

## 目标平台
- 平台：{config.name_cn}
- 内容类型：图文笔记
- 语气风格：{config.tone_style}

## 限制条件
- 标题长度：{config.max_title_length}字以内
- 正文长度：{config.max_content_length}字以内
- 最大图片数：{config.max_images}张
- 标签格式：{config.hashtag_style}

## 关键词
{keyword_str}
{xiaohongshu_rules}

## 内容要求
1. 标题吸引眼球，符合平台调性
2. 正文真实、有分享感
3. 图片和文字配合
4. 有互动引导
5. 严格遵守上述社区规范，避免违规词汇和敏感内容

## 输出格式

**标题**：
（{config.max_title_length}字以内）

**正文**：
（{config.max_content_length}字以内）
- 开头：
- 中间：
- 结尾：

**配图建议**：
（{config.max_images}张以内，每张配文字说明）

**话题标签**：
（{config.hashtag_style}格式，3-5个）

**发布建议**：
（最佳时间、互动策略）
"""
    
    def generate_multi_platform_content(self, original_content: str, 
                                       platforms: List[str],
                                       keywords: List[str] = None) -> Dict[str, Any]:
        """
        为多个平台生成适配内容
        
        Args:
            original_content: 原始内容
            platforms: 目标平台列表
            keywords: 关键词列表
            
        Returns:
            各平台适配内容字典
        """
        results = {}
        
        for platform in platforms:
            try:
                adapted = self.adapt_content(original_content, platform, keywords)
                results[platform] = adapted
            except Exception as e:
                results[platform] = {
                    "error": str(e),
                    "platform": platform
                }
        
        return results


# 全局适配器实例
platform_adapter = PlatformContentAdapter()
