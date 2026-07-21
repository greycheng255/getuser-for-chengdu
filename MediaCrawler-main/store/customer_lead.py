# -*- coding: utf-8 -*-
"""
获客功能模块 - 识别和捕获潜在客户咨询
"""
import re
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class LeadMatchResult:
    """匹配结果"""
    is_lead: bool
    matched_keywords: List[str]
    intent_type: str
    lead_score: int


class CustomerLeadDetector:
    """客户线索检测器"""
    
    # 咨询意图关键词
    INQUIRY_PATTERNS = [
        r'哪里有',
        r'哪里可以',
        r'哪里能',
        r'怎么找',
        r'怎么买',
        r'哪里买',
        r'求推荐',
        r'求分享',
        r'求告知',
        r'请问',
        r'谁知道',
        r'有没有',
        r'有没有推荐的',
        r'想要',
        r'需要',
        r'急需',
        r'求助',
        r'不懂就问',
        r'不懂就问',
        r'求',
        r'推荐',
        r'哪个好',
        r'哪家好',
        r'怎么选',
        r'对比',
        r'区别',
        r'怎么样',
        r'好用吗',
        r'值得买吗',
        r'靠谱吗',
        r'求链接',
        r'求网址',
        r'求入口',
        r'怎么用',
        r'如何使用',
        r'教程',
        r'攻略',
        r'新手',
        r'入门',
        r'体验',
        r'试用',
        r'免费',
        r'优惠',
        r'折扣',
        r'价格',
        r'多少钱',
        r'收费',
        r'付费',
        r'订阅',
        r'会员',
        r'注册',
        r'申请',
        r'开通',
        r'激活',
        r'邀请码',
        r'内测',
        r'公测',
        r'抢先',
        r'最新',
        r'版本',
        r'更新',
        r'升级',
        r'替代',
        r'类似',
        r'平替',
        r'国产',
        r'国内',
        r'中文版',
        r'中文',
        r'汉化',
        r'镜像',
        r'代理',
        r'梯子',
        r'翻墙',
        r'科学上网',
        r'VPN',
        r'加速器',
        r'访问',
        r'打不开',
        r'连不上',
        r'无法使用',
        r'报错',
        r'错误',
        r'问题',
        r'解决',
        r'修复',
        r'怎么办',
        r'怎么处理',
        r'如何应对',
    ]
    
    # AI产品关键词
    AI_PRODUCT_KEYWORDS = {
        # AI聊天/大模型
        'chatgpt': ['chatgpt', 'chat gpt', 'gpt-4', 'gpt4', 'gpt-3.5', 'gpt3.5', 'openai', 'openapi'],
        'claude': ['claude', 'claude3', 'claude 3', 'anthropic'],
        'gemini': ['gemini', 'gemini pro', 'gemini ultra', 'google gemini', 'bard'],
        'copilot': ['copilot', 'github copilot', 'microsoft copilot', 'bing copilot'],
        '文心一言': ['文心一言', '文心', 'ernie', '百度ai'],
        '通义千问': ['通义千问', '通义', 'qwen', '千问', '阿里ai'],
        '讯飞星火': ['讯飞星火', '星火', 'spark', '科大讯飞'],
        '智谱': ['智谱', 'chatglm', 'glm', '智谱ai'],
        'kimi': ['kimi', '月之暗面', 'moonshot'],
        '豆包': ['豆包', 'doubao', '字节ai'],
        '百川': ['百川', 'baichuan'],
        '混元': ['混元', 'hunyuan', '腾讯ai'],
        '商量': ['商量', 'sensechat', '商汤'],
        '天工': ['天工', 'tiangong'],
        '360智脑': ['360智脑', '360 ai'],
        
        # AI图像生成
        'midjourney': ['midjourney', 'mj', 'mid journey'],
        'stable_diffusion': ['stable diffusion', 'sd', 'stablediffusion'],
        'dalle': ['dalle', 'dall-e', 'dall e', 'image2'],
        'gpt_image': ['gpt image', 'gpt-image', 'image generation'],
        '文心一格': ['文心一格'],
        '通义万相': ['通义万相'],
        '即梦': ['即梦', 'dreamina'],
        '可灵': ['可灵', 'kling'],
        'runway': ['runway', 'runwayml'],
        'pika': ['pika', 'pika labs'],
        'leonardo': ['leonardo', 'leonardo.ai'],
        'ideogram': ['ideogram'],
        'firefly': ['firefly', 'adobe firefly'],
        
        # AI视频
        'sora': ['sora', 'openai sora'],
        'pika_video': ['pika video'],
        'heygen': ['heygen'],
        'd-id': ['d-id', 'did'],
        'synthesia': ['synthesia'],
        
        # AI聚合平台
        '聚合平台': ['聚合平台', 'ai聚合', 'ai平台', 'ai导航', 'ai工具箱', 'ai工具站', 'ai导航站'],
        'poe': ['poe', 'poe.com'],
        'you': ['you.com', 'you ai'],
        'perplexity': ['perplexity', 'perplexity.ai'],
        'hugging_face': ['huggingface', 'hugging face', 'hf'],
        'replicate': ['replicate'],
        'together': ['together.ai', 'together ai'],
        'vast': ['vast.ai'],
        'cursor': ['cursor', 'cursor.sh'],
        'windsurf': ['windsurf', 'codeium'],
        'trae': ['trae'],
        'bolt': ['bolt.new', 'bolt'],
        'lovable': ['lovable', 'lovable.dev'],
        'v0': ['v0.dev', 'v0'],
        
        # AI编程
        'github_copilot': ['github copilot'],
        'codeium': ['codeium'],
        'tabnine': ['tabnine'],
        'codegee': ['codegee', 'codegeex'],
        'amazon_codewhisperer': ['codewhisperer', 'amazon codewhisperer'],
        
        # AI办公
        'notion_ai': ['notion ai'],
        'microsoft_365_copilot': ['microsoft 365 copilot', 'office copilot'],
        'wps_ai': ['wps ai'],
        '飞书智能': ['飞书智能', '飞书ai'],
        
        # AI音乐
        'suno': ['suno', 'suno ai'],
        'udio': ['udio'],
        'mubert': ['mubert'],
        
        # AI搜索
        '秘塔': ['秘塔', 'metaso'],
        'devv': ['devv'],
        'phind': ['phind'],
        'kagi': ['kagi'],
        
        # 通用AI
        'ai': ['ai', '人工智能', '大模型', 'llm', '大语言模型', '生成式ai', 'aigc'],
        'api': ['api', 'api接口', '接口'],
        'key': ['api key', 'apikey', '密钥', 'token'],
    }
    
    # 意图类型映射
    INTENT_MAPPING = {
        'inquiry': ['哪里有', '哪里可以', '哪里能', '怎么找', '请问', '谁知道', '有没有', '求', '哪里买'],
        'recommendation': ['求推荐', '推荐', '哪个好', '哪家好', '怎么选', '对比', '区别'],
        'purchase': ['怎么买', '哪里买', '价格', '多少钱', '收费', '付费', '订阅', '会员', '优惠', '折扣'],
        'usage': ['怎么用', '如何使用', '教程', '攻略', '新手', '入门', '体验', '试用'],
        'access': ['访问', '打不开', '连不上', '无法使用', '翻墙', '梯子', 'vpn', '科学上网', '加速器'],
        'troubleshoot': ['报错', '错误', '问题', '解决', '修复', '怎么办'],
    }
    
    # 通用/无意义词，提取核心词时过滤掉
    _GENERIC_TERMS = {
        '寻找', '找', '的人', '用户', '测试', '测试关键词', '怎么', '如何',
        '需要', '想要', '的人', '的人的', '的人的',
    }
    
    # 前缀词（去除后保留核心主词）
    _PREFIXES = ['寻找', '找', '学', '怎么学', '如何学']
    
    # 后缀词（去除后保留核心主词）
    _SUFFIXES = [
        '教学', '教程', '启蒙', '练习', '入门', '培训', '课程', '学习',
        '怎么学', '如何学', '的人', '用户', '的人的',
    ]
    
    @classmethod
    def _extract_core_terms(cls, task_keywords: List[str]) -> set:
        """
        从任务关键词列表中提取核心词。
        例如:
          ["学琵琶", "琵琶教学"] → {"琵琶", "学琵琶", "琵琶教学"}
          ["寻找宋氏家具 宋式家具的人"] → {"宋氏家具", "宋式家具", "家具", "宋氏", "宋式"}
          ["寻找ai生成标书的用户"] → {"ai生成标书", "标书", "生成标书"}
          ["装修 家具"] → {"装修", "家具"}
        """
        core_terms = set()
        if not task_keywords:
            return core_terms
        
        for kw in task_keywords:
            if not kw:
                continue
            kw_lower = kw.lower().strip()
            if not kw_lower:
                continue
            
            # 1. 添加原关键词
            core_terms.add(kw_lower)
            
            # 2. 按空格/顿号分割（处理"装修 家具"、"寻找宋氏家具 宋式家具的人"）
            parts = re.split(r'[\s、，,]+', kw_lower)
            for part in parts:
                part = part.strip()
                if not part or len(part) < 2:
                    continue
                core_terms.add(part)
                # 去前缀
                for prefix in cls._PREFIXES:
                    if part.startswith(prefix) and len(part) > len(prefix):
                        core_terms.add(part[len(prefix):].strip())
                # 去后缀
                for suffix in cls._SUFFIXES:
                    if part.endswith(suffix) and len(part) > len(suffix):
                        core_terms.add(part[:-len(suffix)].strip())
                # 再次分割（去前缀/后缀后可能还有多个词）
                sub_parts = re.split(r'[\s、，,]+', part)
                for sp in sub_parts:
                    sp = sp.strip()
                    if sp and len(sp) >= 2:
                        core_terms.add(sp)
            
            # 3. 去前缀
            for prefix in cls._PREFIXES:
                if kw_lower.startswith(prefix) and len(kw_lower) > len(prefix):
                    remainder = kw_lower[len(prefix):].strip()
                    if remainder:
                        core_terms.add(remainder)
                        # remainder 可能还包含空格分隔的多个词
                        for sub in re.split(r'[\s、，,]+', remainder):
                            sub = sub.strip()
                            if sub and len(sub) >= 2:
                                core_terms.add(sub)
            
            # 4. 去后缀
            for suffix in cls._SUFFIXES:
                if kw_lower.endswith(suffix) and len(kw_lower) > len(suffix):
                    remainder = kw_lower[:-len(suffix)].strip()
                    if remainder:
                        core_terms.add(remainder)
        
        # 5. 过滤掉太短或太通用的词
        filtered = set()
        for t in core_terms:
            t = t.strip()
            if t and len(t) >= 2 and t not in cls._GENERIC_TERMS:
                filtered.add(t)
        
        return filtered
    
    @classmethod
    def detect(cls, content: str, title: str = "", task_keywords: List[str] = None) -> LeadMatchResult:
        """
        检测内容是否包含潜在客户咨询
        
        Args:
            content: 内容文本
            title: 标题文本
            task_keywords: 任务关键词列表（如["学琵琶", "琵琶教学"]）。
                          如果提供，则必须内容/标题与某个任务关键词相关，才可能判定为线索。
            
        Returns:
            LeadMatchResult: 匹配结果
        """
        if not content and not title:
            return LeadMatchResult(False, [], "", 0)
        
        full_text = f"{title} {content}".lower()
        matched_keywords = []
        intent_type = ""
        lead_score = 0
        
        # 0. 任务关键词相关性检查：内容或标题必须与任务关键词相关，才可能是线索
        # 避免采集到无关评论（如学琵琶任务里评论提到豆包/AI等不相关词被误判）
        task_related = True  # 默认相关（向后兼容，无关键词时不过滤）
        if task_keywords:
            task_related = False
            # 任务关键词的核心词（去掉"学/教学/启蒙/练习/入门"等修饰，保留主词如"琵琶"）
            core_terms = cls._extract_core_terms(task_keywords)
            # 检查 full_text 是否包含任一核心词
            for term in core_terms:
                if term and term in full_text:
                    task_related = True
                    matched_keywords.append(f"task_kw:{term}")
                    break
            # 任务关键词不相关，直接返回非线索
            if not task_related:
                return LeadMatchResult(False, [], "", 0)
        
        # 1. 检查是否包含咨询意图
        has_inquiry = False
        for pattern in cls.INQUIRY_PATTERNS:
            if re.search(pattern, full_text, re.IGNORECASE):
                has_inquiry = True
                matched_keywords.append(pattern)
                lead_score += 10
        
        # 2. 检查是否包含AI产品关键词
        has_ai_product = False
        for category, keywords in cls.AI_PRODUCT_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in full_text:
                    has_ai_product = True
                    matched_keywords.append(keyword)
                    lead_score += 15
                    break
        
        # 3. 确定意图类型
        if has_inquiry:
            for intent, patterns in cls.INTENT_MAPPING.items():
                for pattern in patterns:
                    if pattern in full_text:
                        intent_type = intent
                        break
                if intent_type:
                    break
            if not intent_type:
                intent_type = "inquiry"
        elif has_ai_product:
            intent_type = "discussion"
        
        # 4. 计算最终评分
        if has_inquiry and has_ai_product:
            lead_score = min(100, lead_score + 30)  # 同时满足意图+产品 = 高意向
        elif has_inquiry:
            lead_score = min(80, lead_score)
        elif has_ai_product:
            lead_score = min(50, lead_score)
        
        is_lead = has_inquiry or (has_ai_product and lead_score >= 40)
        
        # 当提供了任务关键词时：即使有咨询意图，也必须内容与任务相关
        # （前面已检查 task_related，此处再次确保）
        if task_keywords and not task_related:
            is_lead = False
            lead_score = 0
        
        # 去重
        matched_keywords = list(set(matched_keywords))
        
        return LeadMatchResult(is_lead, matched_keywords, intent_type, lead_score)


async def save_customer_lead(
    task_id: str,
    platform: str,
    data_type: str,
    data_id: str,
    user_id: str,
    nickname: str,
    avatar: str,
    ip_location: str,
    content: str,
    title: str,
    url: str,
    sec_uid: str = "",
    comment_url: str = "",
    profile_url: str = "",
    platform_display_id: str = "",
    detector: CustomerLeadDetector = None,
    extra_title: str = ""
) -> Optional[Dict]:
    """
    保存客户线索
    
    Args:
        task_id: 任务ID
        platform: 平台
        data_type: 数据类型
        data_id: 数据ID
        user_id: 用户ID
        nickname: 用户昵称
        avatar: 用户头像
        ip_location: IP位置
        content: 内容
        title: 标题
        url: 链接
        sec_uid: 安全用户ID（抖音主页用）
        detector: 检测器实例
        extra_title: 额外标题（如评论所属视频的标题），用于关键词相关性判断
        
    Returns:
        Optional[Dict]: 保存的线索数据，如果不是线索则返回None
    """
    if detector is None:
        detector = CustomerLeadDetector()
    
    # 从任务配置加载关键词，要求评论与任务关键词相关才算是线索
    # 同时获取 owner_user_id 用于数据隔离(修复:线索未继承任务 owner 导致用户看不到数据)
    task_keywords = None
    task_owner_uid = ""
    if task_id:
        try:
            import json
            from database.db_session import get_session
            from sqlalchemy import text as sa_text
            async with get_session() as session:
                r = await session.execute(
                    sa_text("SELECT keywords, owner_user_id FROM crawler_task WHERE id=:tid"),
                    {"tid": task_id}
                )
                row = r.fetchone()
                if row:
                    if row[0]:
                        try:
                            kw = json.loads(row[0])
                            if isinstance(kw, list):
                                task_keywords = kw
                            elif isinstance(kw, str):
                                task_keywords = [kw]
                        except Exception:
                            pass
                    if row[1]:
                        task_owner_uid = str(row[1])
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"[save_customer_lead] Failed to load task config for {task_id}: {e}"
            )
    
    # 将额外标题（如评论所属视频标题）拼接到标题中，用于关键词相关性判断
    combined_title = title
    if extra_title:
        combined_title = f"{title} {extra_title}" if title else extra_title
    
    result = detector.detect(content, combined_title, task_keywords=task_keywords)
    
    if not result.is_lead:
        return None
    
    lead_data = {
        "task_id": task_id,
        "platform": platform,
        "owner_user_id": task_owner_uid,
        "data_type": data_type,
        "data_id": data_id,
        "user_id": user_id,
        "sec_uid": sec_uid,
        "nickname": nickname,
        "avatar": avatar,
        "ip_location": ip_location,
        "content": content,
        "title": title,
        "url": url,
        "matched_keywords": ",".join(result.matched_keywords),
        "intent_type": result.intent_type,
        "lead_score": result.lead_score,
        "status": "new",
        "add_ts": int(time.time() * 1000),
        "last_modify_ts": int(time.time() * 1000),
        # 增强字段(客户需求:支持复制和打开链接)
        "comment_url": comment_url,
        "profile_url": profile_url,
        "platform_display_id": platform_display_id,
    }
    
    # 保存到数据库
    try:
        from database.db_session import get_session
        from database.models import CustomerLead
        
        async with get_session() as session:
            lead = CustomerLead(**lead_data)
            session.add(lead)
            await session.flush()
            
        return lead_data
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[save_customer_lead] Error saving lead: {e}", exc_info=True)
        return None


async def check_and_save_lead(
    task_id: str,
    platform: str,
    data_type: str,
    data: Dict,
    content_field: str = "content",
    title_field: str = "title",
    url_field: str = "url",
    user_id_field: str = "user_id",
    sec_uid_field: str = "sec_uid",
    nickname_field: str = "nickname",
    avatar_field: str = "avatar",
    ip_location_field: str = "ip_location",
    data_id_field: str = "comment_id",
    comment_url_field: str = "",
    profile_url_field: str = "",
    platform_display_id_field: str = "",
    extra_title: str = ""
) -> Optional[Dict]:
    """
    检查并保存线索（通用方法）
    
    Args:
        task_id: 任务ID
        platform: 平台
        data_type: 数据类型
        data: 数据字典
        content_field: 内容字段名
        title_field: 标题字段名
        url_field: URL字段名
        user_id_field: 用户ID字段名
        sec_uid_field: 安全用户ID字段名
        nickname_field: 昵称字段名
        avatar_field: 头像字段名
        ip_location_field: IP位置字段名
        data_id_field: 数据ID字段名
        comment_url_field: 原评论链接字段名(可选)
        profile_url_field: 用户主页链接字段名(可选)
        platform_display_id_field: 平台显示ID字段名(可选)
        
    Returns:
        Optional[Dict]: 保存的线索数据
    """
    return await save_customer_lead(
        task_id=task_id,
        platform=platform,
        data_type=data_type,
        data_id=data.get(data_id_field, ""),
        user_id=data.get(user_id_field, ""),
        sec_uid=data.get(sec_uid_field, ""),
        nickname=data.get(nickname_field, ""),
        avatar=data.get(avatar_field, ""),
        ip_location=data.get(ip_location_field, ""),
        content=data.get(content_field, ""),
        title=data.get(title_field, ""),
        url=data.get(url_field, ""),
        comment_url=data.get(comment_url_field, ""),
        profile_url=data.get(profile_url_field, ""),
        platform_display_id=data.get(platform_display_id_field, ""),
        extra_title=extra_title,
    )