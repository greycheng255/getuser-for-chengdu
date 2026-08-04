# -*- coding: utf-8 -*-
"""
平台元数据 + 风控词库

迁移自 GEO-main 的 publish_service.py.platform_configs + platform_content_adapter.py.PLATFORM_CONFIGS，
合并并精简为 MediaCrawler 第一阶段需要的 8 个主流平台。

包含：
1. PLATFORM_METADATA: 平台基础信息（名称/图标/支持内容类型/字数限制）
2. PLATFORM_LOGIN_GUIDES: 各平台登录关键 cookie 字段（迁移自 GEO PlatformLoginHelper）
3. XHS_CONTENT_RESTRICTIONS: 小红书社区规范词库（迁移自 GEO platform_content_adapter.py L67-107）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PlatformMeta:
    """平台元数据"""

    name: str  # 平台英文标识（douyin / xiaohongshu / ...）
    name_cn: str  # 中文名
    icon: str  # emoji 图标
    category: str  # 自媒体 / 视频平台 / 技术社区
    content_types: List[str] = field(default_factory=list)  # 支持的内容类型：article / video / image / note
    max_title_length: int = 100
    max_content_length: int = 10000
    max_images: int = 9
    supports_video: bool = False
    supports_image: bool = True
    supports_article: bool = False
    min_images: int = 0  # 小红书 = 1
    # 视频规格（P2-2 视频尺寸/时长自动适配）
    video_aspect_ratio: Optional[str] = None  # 目标宽高比，如 "9:16" / "16:9" / "1:1"
    max_video_duration: int = 60  # 视频时长上限（秒）
    setup_guide: str = ""
    doc_url: str = ""


# 8 个主流平台的元数据
PLATFORM_METADATA: Dict[str, PlatformMeta] = {
    "douyin": PlatformMeta(
        name="douyin",
        name_cn="抖音",
        icon="🎵",
        category="视频平台",
        content_types=["video", "image"],
        max_title_length=55,
        max_content_length=500,
        max_images=9,
        supports_video=True,
        supports_image=True,
        video_aspect_ratio="9:16",
        max_video_duration=60,
        setup_guide="需在抖音创作者中心扫码登录",
        doc_url="https://creator.douyin.com/",
    ),
    "xiaohongshu": PlatformMeta(
        name="xiaohongshu",
        name_cn="小红书",
        icon="📕",
        category="自媒体",
        content_types=["note", "image"],
        max_title_length=20,
        max_content_length=1000,
        max_images=9,
        supports_image=True,
        supports_video=True,
        min_images=1,  # 小红书必须至少 1 张图
        video_aspect_ratio="9:16",
        max_video_duration=60,
        setup_guide="需在小红书创作者中心扫码登录",
        doc_url="https://creator.xiaohongshu.com/",
    ),
    "bilibili": PlatformMeta(
        name="bilibili",
        name_cn="哔哩哔哩",
        icon="📺",
        category="视频平台",
        content_types=["video", "article"],
        max_title_length=40,
        max_content_length=10000,
        max_images=1,
        supports_video=True,
        supports_article=True,
        video_aspect_ratio="16:9",
        max_video_duration=60,
        setup_guide="需在B站创作中心扫码登录",
        doc_url="https://member.bilibili.com/",
    ),
    "weibo": PlatformMeta(
        name="weibo",
        name_cn="微博",
        icon="📢",
        category="自媒体",
        content_types=["weibo", "article"],
        max_title_length=140,
        max_content_length=2000,
        max_images=9,
        supports_image=True,
        supports_video=True,
        video_aspect_ratio="16:9",
        max_video_duration=60,
        setup_guide="需在微博开放平台扫码登录",
        doc_url="https://weibo.com/",
    ),
    "zhihu": PlatformMeta(
        name="zhihu",
        name_cn="知乎",
        icon="📚",
        category="技术社区",
        content_types=["article", "answer"],
        max_title_length=100,
        max_content_length=20000,
        max_images=1,
        supports_article=True,
        setup_guide="需在知乎开放平台扫码登录",
        doc_url="https://www.zhihu.com/",
    ),
    "x_twitter": PlatformMeta(
        name="x_twitter",
        name_cn="X(Twitter)",
        icon="🐦",
        category="海外平台",
        content_types=["tweet", "video"],
        max_title_length=280,
        max_content_length=280,
        max_images=4,
        supports_video=True,
        supports_image=True,
        video_aspect_ratio="16:9",
        max_video_duration=140,
        setup_guide="需配置 X_TWITTER_COOKIES 环境变量",
        doc_url="https://x.com/",
    ),
    # 保留 x_twitter_publisher 作为别名（兼容峰值时段、配额等配置）
    "x_twitter_publisher": PlatformMeta(
        name="x_twitter",
        name_cn="X(Twitter)",
        icon="🐦",
        category="海外平台",
        content_types=["tweet", "video"],
        max_title_length=280,
        max_content_length=280,
        max_images=4,
        supports_video=True,
        supports_image=True,
        video_aspect_ratio="16:9",
        max_video_duration=140,
        setup_guide="需配置 X_TWITTER_COOKIES 环境变量",
        doc_url="https://x.com/",
    ),
    "kuaishou": PlatformMeta(
        name="kuaishou",
        name_cn="快手",
        icon="🎬",
        category="视频平台",
        content_types=["video", "image"],
        max_title_length=50,
        max_content_length=500,
        max_images=9,
        supports_video=True,
        supports_image=True,
        video_aspect_ratio="9:16",
        max_video_duration=60,
        setup_guide="需在快手创作者中心扫码登录",
        doc_url="https://creator.kuaishou.com/",
    ),
    "wechat_public": PlatformMeta(
        name="wechat_public",
        name_cn="微信公众号",
        icon="💬",
        category="自媒体",
        content_types=["article"],
        max_title_length=64,
        max_content_length=50000,
        max_images=9,
        supports_article=True,
        setup_guide="需在微信公众平台扫码登录",
        doc_url="https://mp.weixin.qq.com/",
    ),
    "wechat_channels": PlatformMeta(
        name="wechat_channels",
        name_cn="微信视频号",
        icon="📹",
        category="视频平台",
        content_types=["video", "image"],
        max_title_length=30,
        max_content_length=1000,
        max_images=9,
        supports_video=True,
        supports_image=True,
        video_aspect_ratio="9:16",
        max_video_duration=60,
        setup_guide="需在微信视频号助手扫码登录",
        doc_url="https://channels.weixin.qq.com/",
    ),
    "toutiao": PlatformMeta(
        name="toutiao",
        name_cn="今日头条",
        icon="📰",
        category="自媒体",
        content_types=["video", "article", "image"],
        max_title_length=30,
        max_content_length=20000,
        max_images=9,
        supports_video=True,
        supports_image=True,
        supports_article=True,
        video_aspect_ratio="16:9",
        max_video_duration=60,
        setup_guide="需在头条号后台扫码登录",
        doc_url="https://mp.toutiao.com/",
    ),
    # ===== 海外 4 平台（P2-2 视频规格补齐） =====
    "tiktok": PlatformMeta(
        name="tiktok",
        name_cn="TikTok",
        icon="🎵",
        category="海外平台",
        content_types=["video"],
        max_title_length=150,
        max_content_length=2200,
        max_images=0,
        supports_video=True,
        supports_image=False,
        video_aspect_ratio="9:16",
        max_video_duration=60,
        setup_guide="需配置 TikTok cookies",
        doc_url="https://www.tiktok.com/",
    ),
    "instagram": PlatformMeta(
        name="instagram",
        name_cn="Instagram",
        icon="📷",
        category="海外平台",
        content_types=["video", "image"],
        max_title_length=2200,
        max_content_length=2200,
        max_images=10,
        supports_video=True,
        supports_image=True,
        video_aspect_ratio="9:16",
        max_video_duration=60,
        setup_guide="需配置 Instagram cookies",
        doc_url="https://www.instagram.com/",
    ),
    "youtube": PlatformMeta(
        name="youtube",
        name_cn="YouTube",
        icon="▶️",
        category="海外平台",
        content_types=["video"],
        max_title_length=100,
        max_content_length=5000,
        max_images=0,
        supports_video=True,
        supports_image=False,
        video_aspect_ratio="16:9",
        max_video_duration=60,
        setup_guide="需配置 YouTube cookies",
        doc_url="https://www.youtube.com/",
    ),
    "facebook": PlatformMeta(
        name="facebook",
        name_cn="Facebook",
        icon="👍",
        category="海外平台",
        content_types=["video", "image"],
        max_title_length=255,
        max_content_length=63206,
        max_images=10,
        supports_video=True,
        supports_image=True,
        video_aspect_ratio="16:9",
        max_video_duration=60,
        setup_guide="需配置 Facebook cookies",
        doc_url="https://www.facebook.com/",
    ),
}


# 各平台登录关键 cookie 字段（迁移自 GEO PlatformLoginHelper.PLATFORM_GUIDES）
PLATFORM_LOGIN_GUIDES: Dict[str, Dict] = {
    "douyin": {
        "key_cookies": ["sessionid", "sessionid_ss"],
        "login_url": "https://creator.douyin.com/",
        "redirect_keyword": "login",
    },
    "xiaohongshu": {
        "key_cookies": ["web_session", "access-token", "x-user-id"],
        "login_url": "https://creator.xiaohongshu.com/",
        "redirect_keyword": "login",
    },
    "bilibili": {
        "key_cookies": ["SESSDATA", "bili_jct"],
        "login_url": "https://www.bilibili.com/",
        "redirect_keyword": "passport.bilibili.com/login",
    },
    "weibo": {
        "key_cookies": ["SUB", "SUBP"],
        "login_url": "https://weibo.com/",
        "redirect_keyword": "passport.weibo",
    },
    "zhihu": {
        "key_cookies": ["z_c0", "d_c0"],
        "login_url": "https://www.zhihu.com/",
        "redirect_keyword": "signin",
    },
}


# 小红书社区规范词库（迁移自 GEO platform_content_adapter.py L67-107）
# 用于第三阶段内容风控：发布前程序化检测，禁止内容发出
XHS_CONTENT_RESTRICTIONS: Dict = {
    # 绝对化用语
    "absolute_words": [
        "最好", "第一", "顶级", "最强", "极致", "完美", "绝对", "100%", "万能",
        "神器", "必买", "必入", "闭眼入", "无脑冲", "天花板", "碾压", "吊打",
        "秒杀", "降维打击",
    ],
    # 夸张宣传
    "exaggeration_words": [
        "逆天", "炸裂", "绝了", "封神", "yyds", "逆天了", "无敌",
    ],
    # 诱导性用语
    "inducing_words": [
        "不看后悔", "错过等一年", "最后机会", "限时", "倒计时",
        "赶紧", "立刻", "马上抢", "手慢无",
    ],
    # 医疗/功效夸大
    "medical_words": [
        "治愈", "根治", "特效", "立竿见影", "药到病除",
        "美白", "祛斑", "祛痘", "抗衰老", "瘦身", "减肥",
    ],
    # 违规营销
    "illegal_marketing": [
        "代购", "微商", "代理", "加盟", "躺赚", "暴利", "稳赚",
    ],
    # 敏感政治社会
    "sensitive_political": [
        "政府", "国家", "机关", "领导人", "政治", "革命", "运动",
    ],
    # 敏感话题
    "sensitive_topics": [
        "政治", "宗教", "色情", "暴力", "赌博", "毒品", "枪支",
        "医疗诊断", "药品推荐", "投资理财", "金融诈骗",
    ],
    # 数量限制
    "max_hashtags": 5,
    "min_content_length": 50,
    # 标题要求
    "title_requirements": [
        "标题不能包含绝对化用语",
        "标题不能包含夸张宣传词",
        "标题长度 8-20 字",
        "标题不能为纯表情符号",
    ],
    # 内容要求
    "content_requirements": [
        "内容必须真实分享，避免硬广",
        "内容长度不少于 50 字",
        "话题标签不超过 5 个",
        "不使用诱导性用语",
        "不涉及医疗功效承诺",
        "不涉及违规营销",
    ],
}


def get_platform_meta(platform: str) -> Optional[PlatformMeta]:
    """获取平台元数据"""
    return PLATFORM_METADATA.get(platform)


def get_login_guide(platform: str) -> Optional[Dict]:
    """获取平台登录指导"""
    return PLATFORM_LOGIN_GUIDES.get(platform)


def list_supported_platforms(category: Optional[str] = None) -> List[PlatformMeta]:
    """列出所有支持的平台（可按分类过滤）"""
    if category:
        return [m for m in PLATFORM_METADATA.values() if m.category == category]
    return list(PLATFORM_METADATA.values())
