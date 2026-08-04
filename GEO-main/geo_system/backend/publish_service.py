"""
一键分发服务
实现AI生成内容的多平台自动发布
"""

import requests
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

from platform_content_adapter import platform_adapter, PlatformType as AdapterPlatformType
from image_generation_service import image_service
from xiaohongshu_content_strategy import content_strategy

# 导入 PostgreSQL 平台账号服务
from platform_account_postgres import PlatformAccountServicePostgres
from postgresql_database import db as postgres_db

logger = logging.getLogger(__name__)


class PublishStatus(Enum):
    """发布状态"""
    PENDING = "pending"      # 待发布
    PUBLISHING = "publishing" # 发布中
    SUCCESS = "success"      # 发布成功
    FAILED = "failed"        # 发布失败
    RETRYING = "retrying"    # 重试中


class PlatformType(Enum):
    """平台类型 - 扩展媒体矩阵"""
    # 自媒体平台
    ZHIHU = "zhihu"                    # 知乎
    XIAOHONGSHU = "xiaohongshu"        # 小红书
    WEIBO = "weibo"                    # 微博
    WECHAT_PUBLIC = "wechat_public"    # 微信公众号
    TOUTIAO = "toutiao"                # 今日头条
    BAIJIAHAO = "baijiahao"            # 百家号
    DOUYIN = "douyin"                  # 抖音
    BILIBILI = "bilibili"              # B站
    
    # 官网平台
    WEBSITE_BLOG = "website_blog"      # 官网博客
    WEBSITE_FAQ = "website_faq"        # 官网FAQ
    
    # 垂直媒体
    TUBATU = "tubatu"                  # 土巴兔
    QIJIA = "qijia"                    # 齐家网
    
    # 综合门户
    SINA = "sina"                      # 新浪网
    NETEASE = "netease"                # 网易
    SOHU = "sohu"                      # 搜狐
    TENCENT = "tencent"                # 腾讯网
    
    # 技术社区
    CSDN = "csdn"                      # CSDN
    JUEJIN = "juejin"                  # 掘金
    JIANSHU = "jianshu"                # 简书
    
    # 问答社区
    BAIDU_ZHIDAO = "baidu_zhidao"      # 百度知道
    SOGOU_WENWEN = "sogou_wenwen"      # 搜狗问问
    
    # 海外平台
    LINKEDIN = "linkedin"              # LinkedIn
    MEDIUM = "medium"                  # Medium
    REDDIT = "reddit"                  # Reddit


@dataclass
class PlatformAccount:
    """平台账号配置"""
    id: int = None
    user_id: int = None
    platform: PlatformType = None
    account_name: str = None
    cookies: str = None           # 登录凭证
    api_token: str = None         # API令牌
    refresh_token: str = None     # 刷新令牌
    status: str = 'active'
    is_active: bool = True
    last_login_time: datetime = None
    last_publish_time: datetime = None
    daily_limit: int = 5          # 每日发布限制


@dataclass
class PublishTask:
    """发布任务"""
    content_id: int        # 关联的AI生成内容ID
    content_type: str      # article, faq, short
    title: str
    content: str
    keywords: List[str]
    id: int = None
    user_id: int = None    # 用户ID，用于获取平台账号
    images: List[str] = None
    target_platforms: List[PlatformType] = None
    status: PublishStatus = PublishStatus.PENDING
    platform_results: Dict = None
    created_at: datetime = None
    published_at: datetime = None
    error_message: str = None


class PublishService:
    """
    一键分发服务
    """

    def __init__(self, db_path: str = "publish.db"):
        self.db_path = db_path
        self.init_database()
        self.platform_handlers = {
            PlatformType.ZHIHU: self.publish_to_zhihu,
            PlatformType.XIAOHONGSHU: self.publish_to_xiaohongshu,
            PlatformType.WEIBO: self.publish_to_weibo,
            PlatformType.WECHAT_PUBLIC: self.publish_to_wechat_public,
            PlatformType.TOUTIAO: self.publish_to_toutiao,
            PlatformType.BAIJIAHAO: self.publish_to_baijiahao,
            PlatformType.BILIBILI: self.publish_to_bilibili,
            PlatformType.DOUYIN: self.publish_to_douyin,
            PlatformType.WEBSITE_BLOG: self.publish_to_website_blog,
            PlatformType.WEBSITE_FAQ: self.publish_to_website_faq,
            PlatformType.CSDN: self.publish_to_csdn,
            PlatformType.JUEJIN: self.publish_to_juejin,
            PlatformType.JIANSHU: self.publish_to_jianshu,
        }

        # 平台配置信息
        self.platform_configs = self._init_platform_configs()

    def _init_platform_configs(self) -> Dict:
        """初始化平台配置信息"""
        return {
            # 自媒体平台
            PlatformType.ZHIHU: {
                "name": "知乎",
                "icon": "📚",
                "category": "自媒体",
                "description": "中文互联网高质量的问答社区",
                "content_type": ["article", "answer"],
                "max_length": 20000,
                "supports_html": True,
                "supports_markdown": True,
                "setup_guide": "需要配置知乎开放平台API",
                "doc_url": "https://www.zhihu.com/"
            },
            PlatformType.XIAOHONGSHU: {
                "name": "小红书",
                "icon": "📕",
                "category": "自媒体",
                "description": "生活方式分享平台，种草社区",
                "content_type": ["note"],
                "max_length": 1000,
                "supports_html": False,
                "supports_markdown": False,
                "setup_guide": "需要申请小红书创作者API",
                "doc_url": "https://www.xiaohongshu.com/"
            },
            PlatformType.WEIBO: {
                "name": "微博",
                "icon": "📢",
                "category": "自媒体",
                "description": "社交媒体平台，实时信息传播",
                "content_type": ["weibo", "article"],
                "max_length": 2000,
                "supports_html": False,
                "supports_markdown": False,
                "setup_guide": "需要配置微博开放平台API",
                "doc_url": "https://weibo.com/"
            },
            PlatformType.WECHAT_PUBLIC: {
                "name": "微信公众号",
                "icon": "💬",
                "category": "自媒体",
                "description": "微信内容创作与传播平台",
                "content_type": ["article"],
                "max_length": 50000,
                "supports_html": True,
                "supports_markdown": True,
                "setup_guide": "需要配置微信公众平台API",
                "doc_url": "https://mp.weixin.qq.com/"
            },
            PlatformType.TOUTIAO: {
                "name": "今日头条",
                "icon": "📰",
                "category": "自媒体",
                "description": "资讯内容分发平台",
                "content_type": ["article", "micro"],
                "max_length": 10000,
                "supports_html": True,
                "supports_markdown": False,
                "setup_guide": "需要申请头条号API权限",
                "doc_url": "https://mp.toutiao.com/"
            },
            PlatformType.BAIJIAHAO: {
                "name": "百家号",
                "icon": "📝",
                "category": "自媒体",
                "description": "百度内容创作平台，搜索权重高",
                "content_type": ["article", "video"],
                "max_length": 20000,
                "supports_html": True,
                "supports_markdown": False,
                "setup_guide": "需要配置百家号API",
                "doc_url": "https://baijiahao.baidu.com/"
            },
            PlatformType.BILIBILI: {
                "name": "哔哩哔哩",
                "icon": "📺",
                "category": "自媒体",
                "description": "年轻人文化社区，视频+图文",
                "content_type": ["video", "article"],
                "max_length": 10000,
                "supports_html": False,
                "supports_markdown": True,
                "setup_guide": "需要配置B站开放平台API",
                "doc_url": "https://www.bilibili.com/"
            },
            PlatformType.DOUYIN: {
                "name": "抖音",
                "icon": "🎵",
                "category": "自媒体",
                "description": "短视频内容平台",
                "content_type": ["video"],
                "max_length": 500,
                "supports_html": False,
                "supports_markdown": False,
                "setup_guide": "需要申请抖音开放平台API",
                "doc_url": "https://www.douyin.com/"
            },
            # 官网平台
            PlatformType.WEBSITE_BLOG: {
                "name": "官网博客",
                "icon": "🌐",
                "category": "官网",
                "description": "品牌官网博客系统",
                "content_type": ["article"],
                "max_length": 50000,
                "supports_html": True,
                "supports_markdown": True,
                "setup_guide": "已内置，无需额外配置",
                "doc_url": None
            },
            PlatformType.WEBSITE_FAQ: {
                "name": "官网FAQ",
                "icon": "❓",
                "category": "官网",
                "description": "品牌官网FAQ系统",
                "content_type": ["faq"],
                "max_length": 10000,
                "supports_html": True,
                "supports_markdown": True,
                "setup_guide": "已内置，无需额外配置",
                "doc_url": None
            },
            # 技术社区
            PlatformType.CSDN: {
                "name": "CSDN",
                "icon": "💻",
                "category": "技术社区",
                "description": "IT技术社区，开发者聚集",
                "content_type": ["article"],
                "max_length": 50000,
                "supports_html": True,
                "supports_markdown": True,
                "setup_guide": "需要配置CSDN博客API",
                "doc_url": "https://blog.csdn.net/"
            },
            PlatformType.JUEJIN: {
                "name": "掘金",
                "icon": "⛏️",
                "category": "技术社区",
                "description": "开发者技术社区",
                "content_type": ["article"],
                "max_length": 30000,
                "supports_html": False,
                "supports_markdown": True,
                "setup_guide": "需要配置掘金API",
                "doc_url": "https://juejin.cn/"
            },
            PlatformType.JIANSHU: {
                "name": "简书",
                "icon": "📖",
                "category": "技术社区",
                "description": "创作社区，适合长文",
                "content_type": ["article"],
                "max_length": 20000,
                "supports_html": False,
                "supports_markdown": True,
                "setup_guide": "需要配置简书API",
                "doc_url": "https://www.jianshu.com/"
            },
            # 综合门户
            PlatformType.SINA: {
                "name": "新浪网",
                "icon": "🌊",
                "category": "综合门户",
                "description": "综合新闻门户网站",
                "content_type": ["article"],
                "max_length": 20000,
                "supports_html": True,
                "supports_markdown": False,
                "setup_guide": "需要申请新浪看点",
                "doc_url": "https://www.sina.com.cn/"
            },
            PlatformType.NETEASE: {
                "name": "网易",
                "icon": "☁️",
                "category": "综合门户",
                "description": "综合新闻门户网站",
                "content_type": ["article"],
                "max_length": 20000,
                "supports_html": True,
                "supports_markdown": False,
                "setup_guide": "需要申请网易号",
                "doc_url": "https://www.163.com/"
            },
            PlatformType.SOHU: {
                "name": "搜狐",
                "icon": "🦊",
                "category": "综合门户",
                "description": "综合新闻门户网站",
                "content_type": ["article"],
                "max_length": 20000,
                "supports_html": True,
                "supports_markdown": False,
                "setup_guide": "需要申请搜狐号",
                "doc_url": "https://www.sohu.com/"
            },
            PlatformType.TENCENT: {
                "name": "腾讯网",
                "icon": "🐧",
                "category": "综合门户",
                "description": "综合新闻门户网站",
                "content_type": ["article"],
                "max_length": 20000,
                "supports_html": True,
                "supports_markdown": False,
                "setup_guide": "需要申请腾讯内容开放平台",
                "doc_url": "https://www.qq.com/"
            },
            # 垂直媒体
            PlatformType.TUBATU: {
                "name": "土巴兔",
                "icon": "🐰",
                "category": "垂直媒体",
                "description": "家装垂直平台",
                "content_type": ["article", "case"],
                "max_length": 15000,
                "supports_html": True,
                "supports_markdown": False,
                "setup_guide": "需要申请土巴兔商家入驻",
                "doc_url": "https://www.to8to.com/"
            },
            PlatformType.QIJIA: {
                "name": "齐家网",
                "icon": "🏠",
                "category": "垂直媒体",
                "description": "家装垂直平台",
                "content_type": ["article", "case"],
                "max_length": 15000,
                "supports_html": True,
                "supports_markdown": False,
                "setup_guide": "需要申请齐家网商家入驻",
                "doc_url": "https://www.jia.com/"
            },
            # 问答社区
            PlatformType.BAIDU_ZHIDAO: {
                "name": "百度知道",
                "icon": "❓",
                "category": "问答社区",
                "description": "百度问答平台",
                "content_type": ["answer"],
                "max_length": 5000,
                "supports_html": False,
                "supports_markdown": False,
                "setup_guide": "需要配置百度知道合伙人",
                "doc_url": "https://zhidao.baidu.com/"
            },
            PlatformType.SOGOU_WENWEN: {
                "name": "搜狗问问",
                "icon": "🔍",
                "category": "问答社区",
                "description": "搜狗问答平台",
                "content_type": ["answer"],
                "max_length": 5000,
                "supports_html": False,
                "supports_markdown": False,
                "setup_guide": "需要申请搜狗问问专家",
                "doc_url": "https://wenwen.sogou.com/"
            },
            # 海外平台
            PlatformType.LINKEDIN: {
                "name": "LinkedIn",
                "icon": "💼",
                "category": "海外平台",
                "description": "职业社交网络平台",
                "content_type": ["article"],
                "max_length": 3000,
                "supports_html": False,
                "supports_markdown": False,
                "setup_guide": "需要配置LinkedIn API",
                "doc_url": "https://www.linkedin.com/"
            },
            PlatformType.MEDIUM: {
                "name": "Medium",
                "icon": "📰",
                "category": "海外平台",
                "description": "国际内容创作平台",
                "content_type": ["article"],
                "max_length": 50000,
                "supports_html": False,
                "supports_markdown": True,
                "setup_guide": "需要配置Medium API Token",
                "doc_url": "https://medium.com/"
            },
            PlatformType.REDDIT: {
                "name": "Reddit",
                "icon": "🔴",
                "category": "海外平台",
                "description": "国际社区讨论平台",
                "content_type": ["post"],
                "max_length": 40000,
                "supports_html": False,
                "supports_markdown": True,
                "setup_guide": "需要配置Reddit API",
                "doc_url": "https://www.reddit.com/"
            }
        }

    def get_platform_info(self, platform_type: PlatformType = None) -> Dict:
        """获取平台信息"""
        if platform_type:
            return self.platform_configs.get(platform_type)
        return self.platform_configs

    def get_platforms_by_category(self, category: str) -> List[Dict]:
        """按分类获取平台"""
        platforms = []
        for pt, config in self.platform_configs.items():
            if config["category"] == category:
                platforms.append({
                    "id": pt.value,
                    **config
                })
        return platforms

    def get_all_platforms(self) -> List[Dict]:
        """获取所有平台信息"""
        platforms = []
        for pt, config in self.platform_configs.items():
            # 检查是否已配置
            account = self.get_platform_account(pt)
            platforms.append({
                "id": pt.value,
                "configured": account is not None,
                **config
            })
        return platforms

    def init_database(self):
        """初始化数据库 - 使用 PostgreSQL"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()

                # 发布任务表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS publish_tasks (
                        id SERIAL PRIMARY KEY,
                        content_id INTEGER,
                        content_type TEXT,
                        title TEXT,
                        content TEXT,
                        keywords TEXT,
                        images TEXT,
                        target_platforms TEXT,
                        status TEXT DEFAULT 'pending',
                        platform_results TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        published_at TIMESTAMP,
                        error_message TEXT
                    )
                ''')

                conn.commit()
                print("[PublishService] PostgreSQL 数据库表初始化完成")
        except Exception as e:
            print(f"[PublishService] 数据库初始化失败: {e}")

    def create_publish_task(self, task: PublishTask) -> int:
        """创建发布任务 - 使用 PostgreSQL"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT INTO publish_tasks 
                    (content_id, content_type, title, content, keywords, images, 
                     target_platforms, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    task.content_id,
                    task.content_type,
                    task.title,
                    task.content,
                    json.dumps(task.keywords),
                    json.dumps(task.images) if task.images else None,
                    json.dumps([p.value for p in task.target_platforms]),
                    task.status.value,
                    datetime.now()
                ))

                task_id = cursor.fetchone()[0]
                conn.commit()
                return task_id
        except Exception as e:
            print(f"[PublishService] 创建发布任务失败: {e}")
            return None

    def _adapt_content_for_platform(self, task: PublishTask, platform: PlatformType) -> PublishTask:
        """
        根据平台特性适配内容
        
        Args:
            task: 原始发布任务
            platform: 目标平台
            
        Returns:
            适配后的发布任务
        """
        try:
            # 获取平台配置
            platform_str = platform.value
            config = platform_adapter.get_platform_config(platform_str)
            
            # 适配标题
            adapted_title = task.title[:config.max_title_length]
            
            # 适配内容
            adapted_content = task.content[:config.max_content_length]
            
            # 根据平台调整内容格式
            if platform == PlatformType.XIAOHONGSHU:
                # 小红书：添加话题标签，调整语气
                adapted_content = self._format_xiaohongshu_content(adapted_content, task.keywords)
            elif platform == PlatformType.ZHIHU:
                # 知乎：专业深度，结构化
                adapted_content = self._format_zhihu_content(adapted_content)
            elif platform == PlatformType.WEIBO:
                # 微博：简短，带话题
                adapted_content = self._format_weibo_content(adapted_content, task.keywords)
            elif platform == PlatformType.DOUYIN:
                # 抖音：视频脚本格式
                adapted_content = self._format_douyin_content(adapted_content)
            
            # 创建新的任务对象
            adapted_task = PublishTask(
                content_id=task.content_id,
                content_type=task.content_type,
                title=adapted_title,
                content=adapted_content,
                keywords=task.keywords,
                target_platforms=[platform],
                status=task.status,
                user_id=task.user_id
            )
            
            logger.info(f"内容已适配到平台 {platform.value}: 标题{len(adapted_title)}字, 内容{len(adapted_content)}字")
            
            return adapted_task
            
        except Exception as e:
            logger.error(f"内容适配失败 {platform.value}: {str(e)}")
            # 如果适配失败，返回原始任务
            return task
    
    def _format_xiaohongshu_content(self, content: str, keywords: List[str], title: str = "") -> str:
        """格式化小红书内容 - 使用真实分享策略"""
        # 使用内容策略生成更真实的内容
        try:
            brand_info = {
                "style": "简约自然",
                "features": ["原木", "温馨", "实用"],
                "website": "www.zhiranhome.com"
            }
            
            # 生成真实内容
            generated = content_strategy.generate_content(brand_info, keywords)
            
            # 返回生成的内容
            return generated["content"]
        except Exception as e:
            logger.warning(f"内容策略生成失败，使用默认格式: {str(e)}")
            # 添加话题标签
            if keywords:
                tags = ' '.join([f'#{kw}#' for kw in keywords[:5]])
                content = f"{content}\n\n{tags}"
            
            # 添加互动引导
            content += "\n\n💬 你觉得怎么样？评论区告诉我吧！"
            
            return content
    
    def _format_zhihu_content(self, content: str) -> str:
        """格式化知乎内容"""
        # 添加专业结尾
        content += "\n\n---\n*以上内容基于专业分析，如有疑问欢迎讨论*"
        return content
    
    def _format_weibo_content(self, content: str, keywords: List[str]) -> str:
        """格式化微博内容"""
        # 添加话题标签
        if keywords:
            tags = ' '.join([f'#{kw}#' for kw in keywords[:3]])
            content = f"{tags}\n\n{content}"
        
        # 添加互动引导
        content += "\n\n转发+评论，抽3位送福利🎁"
        
        return content
    
    def _format_douyin_content(self, content: str) -> str:
        """格式化抖音内容（视频脚本格式）"""
        return f"""🎬 视频脚本

【开场】
{content[:100]}...

【正文】
{content[100:300]}...

【结尾】
{content[300:]}...

💡 拍摄建议：
- 时长：15-60秒
- 背景音乐：热门音乐
- 字幕：重点内容加粗"""

    def execute_publish_task(self, task_id: int, user_id: int = None, images: List[str] = None) -> Dict:
        """执行发布任务"""
        task = self.get_task(task_id)
        if not task:
            return {'success': False, 'error': '任务不存在'}

        # 更新任务中的user_id
        if user_id:
            task.user_id = user_id

        # 更新状态为发布中
        self.update_task_status(task_id, PublishStatus.PUBLISHING)

        results = {}

        for platform in task.target_platforms:
            try:
                handler = self.platform_handlers.get(platform)
                if handler:
                    # 根据平台特性适配内容
                    adapted_task = self._adapt_content_for_platform(task, platform)

                    # 小红书和抖音需要图片，如果没有则自动生成
                    # 使用 task.user_id 确保使用正确的用户ID
                    effective_user_id = user_id or task.user_id or 1
                    if platform in (PlatformType.XIAOHONGSHU, PlatformType.DOUYIN):
                        if not images or len(images) == 0:
                            logger.info(f"{platform.value} 没有图片，正在使用AI生成...")
                            generated_images = image_service.generate_xiaohongshu_images(
                                title=adapted_task.title,
                                content=adapted_task.content,
                                keywords=adapted_task.keywords,
                                count=3  # 生成3张图
                            )
                            if generated_images:
                                logger.info(f"成功生成 {len(generated_images)} 张图片")
                                images = generated_images
                            else:
                                logger.warning("图片生成失败，将尝试无图发布")

                        result = handler(adapted_task, effective_user_id, images)
                    else:
                        result = handler(adapted_task, effective_user_id)

                    results[platform.value] = result

                    # 记录发布结果
                    if result.get('success'):
                        self.update_platform_last_publish(platform, effective_user_id)
                else:
                    results[platform.value] = {
                        'success': False,
                        'error': '未实现的平台处理器'
                    }
            except Exception as e:
                logger.error(f"发布到平台 {platform.value} 失败: {str(e)}")
                results[platform.value] = {
                    'success': False,
                    'error': str(e)
                }

        # 更新任务状态
        all_success = all(r.get('success') for r in results.values())
        final_status = PublishStatus.SUCCESS if all_success else PublishStatus.FAILED

        self.update_task_status(
            task_id,
            final_status,
            platform_results=results,
            published_at=datetime.now()
        )

        return {
            'success': all_success,
            'task_id': task_id,
            'results': results
        }

    def publish_to_zhihu(self, task: PublishTask, user_id: int = None) -> Dict:
        """
        发布到知乎 - 优先使用 Playwright 浏览器自动化，失败时回退到 API
        """
        account = self.get_platform_account(PlatformType.ZHIHU, user_id)
        if not account:
            return {
                'success': False,
                'error': '未配置知乎账号',
                'setup_guide': '''
                知乎发布配置步骤：
                1. 在「平台账号管理」中点击知乎「配置账号」
                2. 点击「获取登录二维码」并用知乎 App 扫码
                3. 扫码成功后系统自动保存 Cookie

                注意：知乎反爬虫严格，推荐使用扫码登录获取 Cookie
                '''
            }

        # 优先尝试 Playwright 自动化（更稳定，能绕过反爬）
        try:
            from zhihu_automation import ZhihuAutomation
            import asyncio

            logger.info(f"[知乎发布] 使用 Playwright 自动化发布，user_id={user_id}")
            automation = ZhihuAutomation(account.cookies, user_id=user_id)
            result = asyncio.run(automation.publish_article(
                title=task.title,
                content=task.content,
                topic=(task.keywords[0] if task.keywords else None)
            ))

            if result.get('success'):
                return {
                    'success': True,
                    'platform': 'zhihu',
                    'url': result.get('article_url'),
                    'message': '知乎专栏文章发布成功（Playwright）',
                    'debug_info': result.get('debug_info', [])
                }

            # Playwright 失败，记录日志后回退到 API
            logger.warning(f"[知乎发布] Playwright 失败，回退到 API: {result.get('error')}")
            api_fallback_error = result.get('error')
        except Exception as e:
            logger.warning(f"[知乎发布] Playwright 异常，回退到 API: {e}")
            api_fallback_error = str(e)

        # 回退：使用 Cookie 调用 HTTP API
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': account.cookies,
                'Content-Type': 'application/json',
                'Origin': 'https://zhuanlan.zhihu.com',
                'Referer': 'https://zhuanlan.zhihu.com/write'
            }

            article_data = {
                'title': task.title,
                'content': self.format_zhihu_content(task.content),
                'topics': task.keywords[:5]
            }

            response = requests.post(
                'https://zhuanlan.zhihu.com/api/articles',
                headers=headers,
                json=article_data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                article_id = result.get('id')
                article_url = result.get('url', f'https://zhuanlan.zhihu.com/p/{article_id}')
                return {
                    'success': True,
                    'platform': 'zhihu',
                    'article_id': article_id,
                    'url': article_url,
                    'message': '文章已发布到知乎（API）'
                }
            else:
                return {
                    'success': False,
                    'platform': 'zhihu',
                    'error': f'知乎API返回错误: HTTP {response.status_code}',
                    'detail': response.text[:500],
                    'playwright_error': api_fallback_error
                }

        except Exception as e:
            return {
                'success': False,
                'platform': 'zhihu',
                'error': str(e),
                'playwright_error': api_fallback_error
            }

    def publish_to_xiaohongshu(self, task: PublishTask, user_id: int = None, images: List[str] = None) -> Dict:
        """发布到小红书 - 使用浏览器自动化"""
        print(f"[PublishService] 正在获取小红书账号，user_id={user_id}")
        account = self.get_platform_account(PlatformType.XIAOHONGSHU, user_id)
        print(f"[PublishService] 获取账号结果: {account}")
        if not account:
            print(f"[PublishService] 未找到小红书账号")
            return {
                'success': False,
                'error': '未配置小红书账号',
                'platform': 'xiaohongshu',
                'setup_guide': '''
                小红书发布配置步骤：
                1. 访问 https://creator.xiaohongshu.com/
                2. 使用手机号或扫码登录创作者平台
                3. 按F12打开开发者工具，切换到Application/应用标签
                4. 复制web_session字段的值
                5. 在平台账号管理中粘贴保存
                '''
            }
        print(f"[PublishService] 找到账号: {account.account_name}, cookies长度: {len(account.cookies) if account.cookies else 0}")

        try:
            # 尝试使用浏览器自动化发布
            try:
                from xiaohongshu_automation import auto_publish_to_xiaohongshu
                from image_generation_service import image_service

                # 优先使用任务自带的真实内容，模板只作为fallback
                xhs_title = task.title[:20] if task.title else ''
                xhs_content = task.content or ''
                xhs_keywords = task.keywords[:5] if task.keywords else []
                
                # 如果任务内容为空或太短，使用内容策略生成
                if not xhs_content or len(xhs_content) < 100:
                    try:
                        brand_info = {
                            "style": "简约自然",
                            "features": ["原木", "温馨", "实用"],
                            "website": "www.zhiranhome.com"
                        }
                        generated = content_strategy.generate_content(brand_info, task.keywords or [])
                        if not xhs_title:
                            xhs_title = generated["title"][:20]
                        if not xhs_content or len(xhs_content) < 100:
                            xhs_content = generated["content"]
                        if not xhs_keywords:
                            xhs_keywords = generated["hashtags"]
                        logger.info(f"[小红书发布] 内容不足，使用模板补充: {xhs_title}")
                    except Exception as e:
                        logger.warning(f"内容策略生成失败，使用任务内容: {str(e)}")
                
                if not xhs_title:
                    xhs_title = task.title[:20] if task.title else '分享'
                
                logger.info(f"[小红书发布] 发布标题: {xhs_title}")
                logger.info(f"[小红书发布] 发布内容: {xhs_content[:200]}...")
                logger.info(f"[小红书发布] 标签: {xhs_keywords}")

                # 处理图片 - 将base64转换为临时文件路径
                image_paths = []
                if images:
                    import base64
                    import tempfile
                    import os

                    for idx, img_base64 in enumerate(images[:9]):  # 小红书最多9张图
                        try:
                            # 移除base64前缀
                            if ',' in img_base64:
                                img_base64 = img_base64.split(',')[1]

                            # 解码并保存为临时文件
                            img_data = base64.b64decode(img_base64)
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as f:
                                f.write(img_data)
                                image_paths.append(f.name)
                        except Exception as e:
                            logger.warning(f"处理图片 {idx} 失败: {str(e)}")

                # 如果没有图片，自动生成图片
                if not image_paths:
                    logger.info("没有提供图片，正在使用AI生成图片...")
                    try:
                        # 从任务中提取品牌名
                        brand_name = ''
                        if hasattr(task, 'content_type') and task.content_type:
                            # 尝试从标题提取品牌（标题格式通常是"品牌名 内容类型"）
                            title_parts = (task.title or '').split(' ')
                            if len(title_parts) > 1:
                                brand_name = title_parts[0]
                        
                        # 生成小红书配图
                        generated_images = image_service.generate_xiaohongshu_images(
                            title=xhs_title,
                            content=xhs_content,
                            keywords=xhs_keywords,
                            count=3,  # 生成3张图：1张封面 + 2张配图
                            brand_name=brand_name or None
                        )

                        if generated_images:
                            logger.info(f"成功生成 {len(generated_images)} 张图片")
                            for idx, img_base64 in enumerate(generated_images):
                                temp_path = image_service.save_base64_to_temp(img_base64)
                                if temp_path:
                                    image_paths.append(temp_path)
                                    logger.info(f"图片 {idx+1} 已保存到临时文件: {temp_path}")
                        else:
                            logger.warning("AI图片生成失败，将尝试发布无图笔记")
                    except Exception as e:
                        logger.error(f"AI图片生成过程出错: {str(e)}")

                # 确保至少有一张图片（小红书必须上传图片）
                if not image_paths:
                    return {
                        'success': False,
                        'platform': 'xiaohongshu',
                        'error': '小红书发布必须包含至少1张图片',
                        'message': '图片生成失败，请手动上传图片或检查AI服务配置',
                        'debug_info': ['图片生成服务可能未配置或API密钥无效']
                    }

                result = auto_publish_to_xiaohongshu(
                    title=xhs_title,
                    content=xhs_content,
                    cookies=account.cookies,
                    keywords=xhs_keywords,
                    images=image_paths,
                    user_id=user_id
                )

                # 清理临时文件
                for path in image_paths:
                    try:
                        os.unlink(path)
                    except:
                        pass

                return result

            except ImportError as ie:
                logger.warning(f"Playwright未安装，使用备用方案: {str(ie)}")
                # 如果Playwright不可用，返回手动发布指导
                return {
                    'success': False,
                    'error': '自动发布需要安装Playwright',
                    'platform': 'xiaohongshu',
                    'manual_guide': f'''
📱 小红书手动发布指南

由于自动发布需要额外配置，请手动发布：

1️⃣ 访问 https://creator.xiaohongshu.com/
2️⃣ 点击"发布笔记"
3️⃣ 填写以下内容：

━━━━━━━━━━━━━━━━━━━━
📌 标题：{task.title[:20]}

📝 内容：
{self.format_xiaohongshu_content(task.content)[:500]}

🏷️ 话题：{" ".join([f"#{kw}" for kw in (task.keywords or [])[:5]])}
━━━━━━━━━━━━━━━━━━━━

💡 如需自动发布，请联系管理员安装Playwright
                    '''.strip()
                }

        except Exception as e:
            logger.error(f"小红书发布失败: {str(e)}")
            return {
                'success': False,
                'platform': 'xiaohongshu',
                'error': f'发布异常: {str(e)}'
            }

    def publish_to_weibo(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到微博 - 优先使用 Playwright 自动化，失败时回退到 API"""
        account = self.get_platform_account(PlatformType.WEIBO, user_id)
        if not account:
            return {
                'success': False,
                'error': '未配置微博账号',
                'setup_guide': '请在「平台账号管理」中点击微博「配置账号」并扫码登录'
            }

        # 优先尝试 Playwright 自动化
        try:
            from weibo_automation import WeiboAutomation
            import asyncio

            logger.info(f"[微博发布] 使用 Playwright 自动化发布，user_id={user_id}")
            automation = WeiboAutomation(account.cookies, user_id=user_id)
            result = asyncio.run(automation.publish_post(
                content=task.content[:2000]
            ))

            if result.get('success'):
                return {
                    'success': True,
                    'platform': 'weibo',
                    'url': result.get('post_url'),
                    'message': '微博发布成功（Playwright）',
                    'debug_info': result.get('debug_info', [])
                }

            logger.warning(f"[微博发布] Playwright 失败，回退到 API: {result.get('error')}")
            api_fallback_error = result.get('error')
        except Exception as e:
            logger.warning(f"[微博发布] Playwright 异常，回退到 API: {e}")
            api_fallback_error = str(e)

        # 回退：使用 Cookie 调用 HTTP API
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': account.cookies,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': 'https://weibo.com/'
            }

            weibo_content = task.content[:2000]

            data = {
                'title': task.title,
                'content': weibo_content,
            }

            response = requests.post(
                'https://weibo.com/ajax/statuses/create',
                headers=headers,
                data=data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                weibo_id = result.get('data', {}).get('id') or result.get('id')
                if weibo_id:
                    weibo_url = f'https://weibo.com/detail/{weibo_id}'
                    return {
                        'success': True,
                        'platform': 'weibo',
                        'weibo_id': weibo_id,
                        'url': weibo_url,
                        'message': '内容已发布到微博（API）'
                    }

            return {
                'success': False,
                'platform': 'weibo',
                'error': f'微博API返回错误: HTTP {response.status_code}',
                'detail': response.text[:500],
                'playwright_error': api_fallback_error
            }

        except Exception as e:
            return {
                'success': False,
                'platform': 'weibo',
                'error': str(e),
                'playwright_error': api_fallback_error
            }

    def publish_to_website_blog(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到官网博客"""
        try:
            # 将内容保存到数据库或文件
            blog_post = {
                'title': task.title,
                'content': task.content,
                'keywords': task.keywords,
                'slug': self.generate_slug(task.title),
                'created_at': datetime.now().isoformat(),
                'status': 'published'
            }

            # 保存到JSON文件（实际应该保存到数据库）
            import os
            blog_dir = '/home/ubuntu/GEO/geo_system/web/blog'
            os.makedirs(blog_dir, exist_ok=True)

            filename = f"{blog_post['slug']}.json"
            filepath = os.path.join(blog_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(blog_post, f, ensure_ascii=False, indent=2)

            # 同时生成HTML文件
            html_content = self.generate_blog_html(blog_post)
            html_path = os.path.join(blog_dir, f"{blog_post['slug']}.html")

            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            return {
                'success': True,
                'platform': 'website_blog',
                'url': f'/blog/{blog_post["slug"]}.html',
                'filepath': filepath,
                'message': '文章已发布到官网博客'
            }

        except Exception as e:
            return {
                'success': False,
                'platform': 'website_blog',
                'error': str(e)
            }

    def publish_to_website_faq(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到官网FAQ"""
        try:
            faq_data = {
                'question': task.title,
                'answer': task.content,
                'keywords': task.keywords,
                'created_at': datetime.now().isoformat()
            }

            # 保存到FAQ数据库
            faq_dir = '/home/ubuntu/GEO/geo_system/web/data'
            os.makedirs(faq_dir, exist_ok=True)

            faq_file = os.path.join(faq_dir, 'faqs.json')

            # 读取现有FAQ
            faqs = []
            if os.path.exists(faq_file):
                with open(faq_file, 'r', encoding='utf-8') as f:
                    faqs = json.load(f)

            # 添加新FAQ
            faqs.append(faq_data)

            # 保存
            with open(faq_file, 'w', encoding='utf-8') as f:
                json.dump(faqs, f, ensure_ascii=False, indent=2)

            return {
                'success': True,
                'platform': 'website_faq',
                'message': 'FAQ已添加到官网'
            }

        except Exception as e:
            return {
                'success': False,
                'platform': 'website_faq',
                'error': str(e)
            }

    # ========== 新增平台发布处理器 ==========

    def publish_to_wechat_public(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到微信公众号 - 使用微信公众平台API"""
        account = self.get_platform_account(PlatformType.WECHAT_PUBLIC)
        if not account:
            return {
                'success': False,
                'error': '未配置微信公众号',
                'setup_guide': '''配置步骤：
                1. 登录微信公众平台
                2. 申请开发者权限
                3. 获取AppID和AppSecret
                4. 配置IP白名单
                '''
            }

        try:
            # 获取access_token
            app_id = account.api_key or account.cookies
            app_secret = account.api_secret or ''

            if not app_id or not app_secret:
                return {
                    'success': False,
                    'error': '微信公众号AppID或AppSecret未配置'
                }

            token_url = f'https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={app_id}&secret={app_secret}'
            token_resp = requests.get(token_url, timeout=10)
            token_data = token_resp.json()
            access_token = token_data.get('access_token')

            if not access_token:
                return {
                    'success': False,
                    'platform': 'wechat_public',
                    'error': f'获取access_token失败: {token_data.get("errmsg", "未知错误")}'
                }

            # 创建草稿
            draft_data = {
                'articles': [{
                    'title': task.title,
                    'content': task.content,
                    'digest': task.content[:120],
                }]
            }

            draft_url = f'https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}'
            draft_resp = requests.post(draft_url, json=draft_data, timeout=30)
            draft_result = draft_resp.json()

            media_id = draft_result.get('media_id')
            if media_id:
                return {
                    'success': True,
                    'platform': 'wechat_public',
                    'media_id': media_id,
                    'url': f'https://mp.weixin.qq.com/cgi-bin/appmsg?t=appmsg/edit&action=edit&type=77&token={access_token[:20]}',
                    'message': '文章已创建为微信公众号草稿，请到公众平台手动发布'
                }
            else:
                return {
                    'success': False,
                    'platform': 'wechat_public',
                    'error': f'创建草稿失败: {draft_result.get("errmsg", "未知错误")}'
                }

        except Exception as e:
            return {
                'success': False,
                'platform': 'wechat_public',
                'error': str(e)
            }

    def publish_to_toutiao(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到今日头条 - 使用头条号API"""
        account = self.get_platform_account(PlatformType.TOUTIAO)
        if not account:
            return {
                'success': False,
                'error': '未配置今日头条账号',
                'setup_guide': '请申请头条号并配置API密钥'
            }

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': account.cookies,
                'Content-Type': 'application/json',
                'Referer': 'https://mp.toutiao.com/'
            }

            article_data = {
                'title': task.title,
                'content': task.content,
            }

            response = requests.post(
                'https://mp.toutiao.com/pgc/article/create',
                headers=headers,
                json=article_data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                article_id = result.get('data', {}).get('article_id')
                if article_id:
                    return {
                        'success': True,
                        'platform': 'toutiao',
                        'article_id': article_id,
                        'url': f'https://www.toutiao.com/article/{article_id}',
                        'message': '文章已发布到今日头条'
                    }

            return {
                'success': False,
                'platform': 'toutiao',
                'error': f'头条API返回错误: HTTP {response.status_code}',
                'detail': response.text[:500]
            }

        except Exception as e:
            return {
                'success': False,
                'platform': 'toutiao',
                'error': str(e)
            }

    def publish_to_baijiahao(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到百家号 - 使用百家号API"""
        account = self.get_platform_account(PlatformType.BAIJIAHAO)
        if not account:
            return {
                'success': False,
                'error': '未配置百家号',
                'setup_guide': '请申请百家号并配置API密钥'
            }

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': account.cookies,
                'Content-Type': 'application/json',
                'Referer': 'https://baijiahao.baidu.com/'
            }

            article_data = {
                'title': task.title,
                'content': task.content,
            }

            response = requests.post(
                'https://baijiahao.baidu.com/builderinner/api/content/article/create',
                headers=headers,
                json=article_data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                article_id = result.get('data', {}).get('article_id')
                if article_id:
                    return {
                        'success': True,
                        'platform': 'baijiahao',
                        'article_id': article_id,
                        'url': f'https://baijiahao.baidu.com/s?id={article_id}',
                        'message': '文章已发布到百家号'
                    }

            return {
                'success': False,
                'platform': 'baijiahao',
                'error': f'百家号API返回错误: HTTP {response.status_code}',
                'detail': response.text[:500]
            }

        except Exception as e:
            return {
                'success': False,
                'platform': 'baijiahao',
                'error': str(e)
            }

    def publish_to_bilibili(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到哔哩哔哩 - 优先使用 Playwright 自动化，失败时回退到 API"""
        account = self.get_platform_account(PlatformType.BILIBILI, user_id)
        if not account:
            return {
                'success': False,
                'error': '未配置B站账号',
                'setup_guide': '请在「平台账号管理」中点击 Bilibili「配置账号」并扫码登录'
            }

        # 优先尝试 Playwright 自动化
        try:
            from bilibili_automation import BilibiliAutomation
            import asyncio

            logger.info(f"[B站发布] 使用 Playwright 自动化发布，user_id={user_id}")
            automation = BilibiliAutomation(account.cookies, user_id=user_id)
            result = asyncio.run(automation.publish_article(
                title=task.title,
                content=task.content
            ))

            if result.get('success'):
                return {
                    'success': True,
                    'platform': 'bilibili',
                    'url': result.get('article_url'),
                    'message': 'B站专栏发布成功（Playwright）',
                    'debug_info': result.get('debug_info', [])
                }

            logger.warning(f"[B站发布] Playwright 失败，回退到 API: {result.get('error')}")
            api_fallback_error = result.get('error')
        except Exception as e:
            logger.warning(f"[B站发布] Playwright 异常，回退到 API: {e}")
            api_fallback_error = str(e)

        # 回退：使用 Cookie 调用 HTTP API
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': account.cookies,
                'Content-Type': 'application/json',
                'Referer': 'https://member.bilibili.com/'
            }

            article_data = {
                'title': task.title,
                'content': task.content,
                'category': 0,
                'summary': task.content[:200],
                'words': len(task.content),
            }

            response = requests.post(
                'https://api.bilibili.com/x/article/creative/draft/addupdate',
                headers=headers,
                json=article_data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                aid = result.get('data', {}).get('aid')
                if aid:
                    return {
                        'success': True,
                        'platform': 'bilibili',
                        'article_id': aid,
                        'url': f'https://www.bilibili.com/read/cv{aid}',
                        'message': '专栏已发布到B站（API）'
                    }

            return {
                'success': False,
                'platform': 'bilibili',
                'error': f'B站API返回错误: HTTP {response.status_code}',
                'detail': response.text[:500],
                'playwright_error': api_fallback_error
            }

        except Exception as e:
            return {
                'success': False,
                'platform': 'bilibili',
                'error': str(e),
                'playwright_error': api_fallback_error
            }

    def publish_to_douyin(self, task: PublishTask, user_id: int = None, images: List[str] = None) -> Dict:
        """发布到抖音 - 使用 Playwright 浏览器自动化（图文发布）"""
        account = self.get_platform_account(PlatformType.DOUYIN, user_id)
        if not account:
            return {
                'success': False,
                'error': '未配置抖音账号',
                'setup_guide': '请在「平台账号管理」中点击抖音「配置账号」并扫码登录'
            }

        try:
            from douyin_automation import DouyinAutomation
            import asyncio
            import base64
            import tempfile
            import os

            logger.info(f"[抖音发布] 使用 Playwright 自动化发布，user_id={user_id}")

            # 处理图片 - 将 base64 转换为临时文件路径
            image_paths = []
            if images:
                for idx, img_base64 in enumerate(images[:9]):
                    try:
                        if ',' in img_base64:
                            img_base64 = img_base64.split(',')[1]
                        img_data = base64.b64decode(img_base64)
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as f:
                            f.write(img_data)
                            image_paths.append(f.name)
                    except Exception as e:
                        logger.warning(f"处理图片 {idx} 失败: {e}")

            # 如果没有图片，尝试用 AI 生成
            if not image_paths:
                try:
                    from image_generation_service import image_service
                    logger.info("[抖音发布] 没有图片，正在使用 AI 生成...")
                    generated_images = image_service.generate_xiaohongshu_images(
                        title=task.title,
                        content=task.content,
                        keywords=task.keywords or [],
                        count=3
                    )
                    if generated_images:
                        for img_base64 in generated_images:
                            temp_path = image_service.save_base64_to_temp(img_base64)
                            if temp_path:
                                image_paths.append(temp_path)
                except Exception as e:
                    logger.error(f"[抖音发布] AI 图片生成失败: {e}")

            # 抖音图文发布至少需要 1 张图片
            if not image_paths:
                return {
                    'success': False,
                    'platform': 'douyin',
                    'error': '抖音图文发布至少需要 1 张图片',
                    'debug_info': ['图片生成失败，请手动上传图片']
                }

            automation = DouyinAutomation(account.cookies, user_id=user_id)
            result = asyncio.run(automation.publish_post(
                content=task.content[:2000],
                image_paths=image_paths
            ))

            # 清理临时文件
            for path in image_paths:
                try:
                    os.unlink(path)
                except:
                    pass

            if result.get('success'):
                return {
                    'success': True,
                    'platform': 'douyin',
                    'url': result.get('post_url'),
                    'message': '抖音图文发布成功（Playwright）',
                    'debug_info': result.get('debug_info', [])
                }

            return {
                'success': False,
                'platform': 'douyin',
                'error': result.get('error', '抖音发布失败'),
                'debug_info': result.get('debug_info', [])
            }

        except ImportError:
            return {
                'success': False,
                'platform': 'douyin',
                'error': '自动发布模块未安装（需要 Playwright）'
            }
        except Exception as e:
            logger.error(f"[抖音发布] 异常: {e}")
            return {
                'success': False,
                'platform': 'douyin',
                'error': f'发布异常: {e}'
            }

    def publish_to_csdn(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到CSDN - 使用Cookie认证调用真实API"""
        account = self.get_platform_account(PlatformType.CSDN)
        if not account:
            return {
                'success': False,
                'error': '未配置CSDN账号',
                'setup_guide': '请注册CSDN博客并配置Cookie'
            }

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': account.cookies,
                'Content-Type': 'application/json',
                'Referer': 'https://mp.csdn.net/'
            }

            article_data = {
                'title': task.title,
                'markdowncontent': task.content,
                'content': task.content,
            }

            response = requests.post(
                'https://mp.csdn.net/mp_blog/creatie',
                headers=headers,
                json=article_data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                article_id = result.get('data', {}).get('articleId')
                if article_id:
                    return {
                        'success': True,
                        'platform': 'csdn',
                        'article_id': article_id,
                        'url': f'https://blog.csdn.net/article/details/{article_id}',
                        'message': '文章已发布到CSDN'
                    }

            return {
                'success': False,
                'platform': 'csdn',
                'error': f'CSDN API返回错误: HTTP {response.status_code}',
                'detail': response.text[:500]
            }

        except Exception as e:
            return {
                'success': False,
                'platform': 'csdn',
                'error': str(e)
            }

    def publish_to_juejin(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到掘金 - 使用掘金API"""
        account = self.get_platform_account(PlatformType.JUEJIN)
        if not account:
            return {
                'success': False,
                'error': '未配置掘金账号',
                'setup_guide': '请注册掘金并配置API Token'
            }

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': account.cookies,
                'Content-Type': 'application/json',
                'Referer': 'https://juejin.cn/'
            }

            article_data = {
                'title': task.title,
                'content': task.content,
                'category_id': '0',
                'tag_ids': [],
            }

            response = requests.post(
                'https://api.juejin.cn/content_api/v1/article/publish',
                headers=headers,
                json=article_data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                article_id = result.get('data', {}).get('article_id')
                if article_id:
                    return {
                        'success': True,
                        'platform': 'juejin',
                        'article_id': article_id,
                        'url': f'https://juejin.cn/post/{article_id}',
                        'message': '文章已发布到掘金'
                    }

            return {
                'success': False,
                'platform': 'juejin',
                'error': f'掘金API返回错误: HTTP {response.status_code}',
                'detail': response.text[:500]
            }

        except Exception as e:
            return {
                'success': False,
                'platform': 'juejin',
                'error': str(e)
            }

    def publish_to_jianshu(self, task: PublishTask, user_id: int = None) -> Dict:
        """发布到简书 - 使用Cookie认证调用真实API"""
        account = self.get_platform_account(PlatformType.JIANSHU)
        if not account:
            return {
                'success': False,
                'error': '未配置简书账号',
                'setup_guide': '请注册简书并配置Cookie'
            }

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': account.cookies,
                'Content-Type': 'application/json',
                'Referer': 'https://www.jianshu.com/'
            }

            article_data = {
                'title': task.title,
                'content': task.content,
            }

            response = requests.post(
                'https://www.jianshu.com/author/notes',
                headers=headers,
                json=article_data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                note_id = result.get('id') or result.get('data', {}).get('id')
                if note_id:
                    return {
                        'success': True,
                        'platform': 'jianshu',
                        'article_id': note_id,
                        'url': f'https://www.jianshu.com/p/{note_id}',
                        'message': '文章已发布到简书'
                    }

            return {
                'success': False,
                'platform': 'jianshu',
                'error': f'简书API返回错误: HTTP {response.status_code}',
                'detail': response.text[:500]
            }

        except Exception as e:
            return {
                'success': False,
                'platform': 'jianshu',
                'error': str(e)
            }

    def format_zhihu_content(self, content: str) -> str:
        """格式化知乎内容"""
        # 知乎支持Markdown
        # 添加标题、分段、图片等
        formatted = content.replace('\n\n', '\n\n')  # 保持段落
        return formatted

    def format_xiaohongshu_content(self, content: str) -> str:
        """格式化小红书内容"""
        # 小红书需要更短、更口语化
        lines = content.split('\n')
        # 取前10行，每行加emoji
        short_lines = lines[:10]
        return '\n'.join([f"✨ {line}" for line in short_lines if line.strip()])

    def generate_slug(self, title: str) -> str:
        """生成URL友好的slug"""
        import re
        # 移除特殊字符，替换空格为连字符
        slug = re.sub(r'[^\w\s-]', '', title)
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.lower()[:50]

    def generate_blog_html(self, blog_post: Dict) -> str:
        """生成博客HTML页面"""
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{blog_post['title']} - 织然家具</title>
    <meta name="keywords" content="{','.join(blog_post['keywords'])}">
    <script type="application/ld+json">
    {{
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": "{blog_post['title']}",
        "datePublished": "{blog_post['created_at']}",
        "author": {{
            "@type": "Organization",
            "name": "织然家具"
        }}
    }}
    </script>
</head>
<body>
    <article>
        <h1>{blog_post['title']}</h1>
        <div class="content">
            {blog_post['content'].replace(chr(10), '<br>')}
        </div>
    </article>
</body>
</html>'''

    def get_task(self, task_id: int) -> Optional[PublishTask]:
        """获取任务详情 - 使用 PostgreSQL"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM publish_tasks WHERE id = %s', (task_id,))
                row = cursor.fetchone()
                if row:
                    return self.row_to_task(row)
        except Exception as e:
            print(f"[PublishService] 获取任务失败: {e}")
        return None

    def get_tasks(self, status: PublishStatus = None, limit: int = 50) -> List[PublishTask]:
        """获取任务列表 - 使用 PostgreSQL"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                if status:
                    cursor.execute(
                        'SELECT * FROM publish_tasks WHERE status = %s ORDER BY created_at DESC LIMIT %s',
                        (status.value, limit)
                    )
                else:
                    cursor.execute(
                        'SELECT * FROM publish_tasks ORDER BY created_at DESC LIMIT %s',
                        (limit,)
                    )
                rows = cursor.fetchall()
                return [self.row_to_task(row) for row in rows]
        except Exception as e:
            print(f"[PublishService] 获取任务列表失败: {e}")
            return []

    def row_to_task(self, row) -> PublishTask:
        """数据库行转任务对象"""
        return PublishTask(
            id=row[0],
            content_id=row[1],
            content_type=row[2],
            title=row[3],
            content=row[4],
            keywords=json.loads(row[5]) if row[5] else [],
            images=json.loads(row[6]) if row[6] else None,
            target_platforms=[PlatformType(p) for p in json.loads(row[7])] if row[7] else [],
            status=PublishStatus(row[8]),
            platform_results=json.loads(row[9]) if row[9] else None,
            created_at=row[10],
            published_at=row[11],
            error_message=row[12]
        )

    def update_task_status(self, task_id: int, status: PublishStatus,
                          platform_results: Dict = None,
                          published_at: datetime = None,
                          error_message: str = None):
        """更新任务状态 - 使用 PostgreSQL"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE publish_tasks 
                    SET status = %s, platform_results = %s, published_at = %s, error_message = %s
                    WHERE id = %s
                ''', (
                    status.value,
                    json.dumps(platform_results) if platform_results else None,
                    published_at,
                    error_message,
                    task_id
                ))
                conn.commit()
        except Exception as e:
            print(f"[PublishService] 更新任务状态失败: {e}")

    def add_platform_account(self, account: PlatformAccount, user_id: int = None):
        """添加或更新平台账号 - 使用 PostgreSQL"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                uid = user_id or 1

                # 检查是否已存在该平台的账号
                cursor.execute(
                    'SELECT id FROM platform_accounts WHERE user_id = %s AND platform = %s',
                    (uid, account.platform.value)
                )
                existing = cursor.fetchone()

                if existing:
                    # 更新现有账号
                    cursor.execute('''
                        UPDATE platform_accounts
                        SET account_name = %s, cookies = %s, api_token = %s, is_active = %s, daily_limit = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = %s AND platform = %s
                    ''', (
                        account.account_name,
                        account.cookies,
                        account.api_token,
                        account.is_active,
                        account.daily_limit,
                        uid,
                        account.platform.value
                    ))
                else:
                    # 插入新账号
                    cursor.execute('''
                        INSERT INTO platform_accounts
                        (user_id, platform, account_name, cookies, api_token, is_active, daily_limit)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        uid,
                        account.platform.value,
                        account.account_name,
                        account.cookies,
                        account.api_token,
                        account.is_active,
                        account.daily_limit
                    ))
                conn.commit()
        except Exception as e:
            print(f"[PublishService] 添加账号失败: {e}")

    def get_platform_account(self, platform: PlatformType, user_id: int = None) -> Optional[PlatformAccount]:
        """获取平台账号 - 使用 PostgreSQL"""
        try:
            postgres_service = PlatformAccountServicePostgres()
            
            # 如果指定了 user_id，先尝试获取该用户的账号
            if user_id:
                print(f"[PublishService] 从PostgreSQL获取账号: platform={platform.value}, user_id={user_id}")
                account_data = postgres_service.get_account(user_id, platform.value)
                if account_data and account_data.get('is_active'):
                    print(f"[PublishService] 找到用户 {user_id} 的账号")
                    return PlatformAccount(
                        id=account_data['id'],
                        user_id=account_data['user_id'],
                        platform=PlatformType(account_data['platform']),
                        account_name=account_data['account_name'],
                        cookies=account_data['cookies'],
                        api_token=account_data['api_token'],
                        refresh_token=account_data.get('refresh_token'),
                        status=account_data.get('status', 'active'),
                        is_active=account_data['is_active'],
                        last_login_time=account_data.get('last_login_time'),
                        last_publish_time=account_data.get('last_publish_time'),
                        daily_limit=account_data.get('daily_limit', 5)
                    )
            
            # 如果没有指定 user_id 或没找到，尝试获取任何用户的账号
            print(f"[PublishService] 尝试获取任意用户的 {platform.value} 账号")
            with postgres_service.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT * FROM platform_accounts WHERE platform = %s AND is_active = true ORDER BY id DESC LIMIT 1',
                    (platform.value,)
                )
                row = cursor.fetchone()
                if row:
                    print(f"[PublishService] 找到账号: user_id={row[1]}")
                    return PlatformAccount(
                        id=row[0],
                        user_id=row[1],
                        platform=PlatformType(row[2]),
                        account_name=row[3],
                        cookies=row[4],
                        api_token=row[5],
                        refresh_token=row[6],
                        status=row[7],
                        is_active=row[8],
                        last_login_time=row[9],
                        last_publish_time=row[10],
                        daily_limit=row[12] if len(row) > 12 else 5
                    )
                else:
                    print(f"[PublishService] 未找到任何 {platform.value} 账号")
        except Exception as e:
            print(f"[PublishService] 获取账号失败: {e}")
            import traceback
            traceback.print_exc()
        return None

    def update_platform_last_publish(self, platform: PlatformType, user_id: int = None):
        """更新平台最后发布时间 - 使用 PostgreSQL"""
        try:
            postgres_service = PlatformAccountServicePostgres()
            with postgres_service.db.get_connection() as conn:
                cursor = conn.cursor()
                if user_id:
                    cursor.execute(
                        'UPDATE platform_accounts SET last_publish_time = %s WHERE user_id = %s AND platform = %s',
                        (datetime.now(), user_id, platform.value)
                    )
                else:
                    cursor.execute(
                        'UPDATE platform_accounts SET last_publish_time = %s WHERE platform = %s',
                        (datetime.now(), platform.value)
                    )
                conn.commit()
        except Exception as e:
            print(f"[PublishService] 更新最后发布时间失败: {e}")


# 全局服务实例 - 使用统一的数据库路径
import os
DB_PATH = os.environ.get('DB_PATH', '/app/data/publish.db')
publish_service = PublishService(db_path=DB_PATH)


# 便捷函数
def quick_publish(content_id: int, title: str, content: str,
                  content_type: str = 'article',
                  keywords: List[str] = None,
                  platforms: List[str] = None,
                  images: List[str] = None) -> Dict:
    """
    快速发布内容到多个平台

    Args:
        content_id: 内容ID
        title: 标题
        content: 内容
        content_type: 内容类型 article/faq/short
        keywords: 关键词列表
        platforms: 目标平台列表 ['zhihu', 'xiaohongshu', 'website_blog']
        images: 图片列表（base64编码或文件路径）

    Returns:
        发布结果
    """
    if platforms is None:
        platforms = ['website_blog']  # 默认只发布到官网

    task = PublishTask(
        content_id=content_id,
        content_type=content_type,
        title=title,
        content=content,
        keywords=keywords or [],
        target_platforms=[PlatformType(p) for p in platforms],
        status=PublishStatus.PENDING
    )

    # 创建任务
    task_id = publish_service.create_publish_task(task)

    # 执行任务（传递图片）
    result = publish_service.execute_publish_task(task_id, images=images)

    return result
