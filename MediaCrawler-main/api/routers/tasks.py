# -*- coding: utf-8 -*-
"""
任务管理API路由 - 使用数据库存储
"""
import asyncio
import json
import time
import uuid
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc, func, update, or_, delete, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

import config
from tools import utils
from database.db_session import get_async_engine
from database.models import CrawlerTaskModel, TaskLogModel, CustomerLead, DouyinAweme, DouyinAwemeComment, XhsNote, XhsNoteComment, OutreachRecord, OutreachTaskModel, KuaishouVideoComment, WeiboNoteComment, BilibiliVideoComment, TiebaComment, ZhihuComment, AutoOutreachJobModel
from ..services.auth import get_current_user, user_scope_filter, is_admin

router = APIRouter(prefix="/tasks", tags=["tasks"])

# 内存缓存（用于快速访问，重启后从数据库加载）
_tasks_cache: Dict[str, dict] = {}

# 日志同步任务（按任务ID隔离）
_log_sync_tasks: Dict[str, asyncio.Task] = {}

# 高意向关键词（用于用户价值评分）
HIGH_INTENT_KEYWORDS = [
    # 购买意向 - 强信号(用多字组合,避免单字"买"命中"买家/买的")
    "购买", "多少钱", "价格", "优惠", "折扣", "便宜", "贵", "值得",
    "怎么买", "哪里买", "求链接", "链接", "网址", "网站", "地址", "入口", "怎么进",
    "下单", "下单了", "已买", "入手",
    "必入", "闭眼入", "种草", "安利",
    # 需求表达 - 中强信号
    "想要", "需要", "求推荐", "推荐",
    # 咨询意向 - 中强信号
    "怎么用", "好用吗", "怎么样", "效果", "体验", "测评", "评测",
    "求教程", "教程", "怎么做", "方法", "攻略", "步骤", "如何使用",
    # 合作意向 - 强信号
    "合作", "代理", "加盟", "商务", "联系", "私信", "加我", "微信",
    "怎么联系", "联系方式", "咨询", "了解", "感兴趣", "想做",
    # 情感倾向 - 弱信号但可挖掘(移除"喜欢/爱"等易被叙述句误命中的词)
    "太棒了", "好用", "不错", "满意", "惊喜", "感谢", "谢谢",
    # 行动意向 - 中强信号
    "试试", "想试", "准备", "打算", "计划", "马上", "立刻", "赶紧",
    # 获客相关 - 强信号(移除单字"求/找/怎么/哪里",改用组合)
    "带带我", "教教我", "学习", "入门", "新手",
    # AI/科技产品相关 - 强信号
    "充值", "会员", "api", "接口", "gpt", "chatgpt", "claude", "ai", "模型", "调用",
    "免费", "试用", "注册", "账号", "登录", "翻墙", "梯子", "vpn",
    "聚合", "平台", "工具", "软件", "app", "应用",
    "同款", "求同款", "抄作业", "求分享", "分享下", "能发下",
    "求购", "转让",
]

# 低意向/负面关键词
LOW_INTENT_KEYWORDS = [
    "垃圾", "骗子", "坑", "假的", "骗人", "别信", "避雷", "踩雷",
    "不好", "差", "后悔", "失望", "烂", "恶心", "滚", "无语",
    "智商税", "割韭菜", "忽悠",
]

# 关键词权重配置
KEYWORD_WEIGHTS = {
    # 购买意向 - 权重 3
    "买": 3, "购买": 3, "多少钱": 3, "价格": 3, "优惠": 3, "折扣": 3,
    "怎么买": 3, "哪里买": 3, "求链接": 3, "链接": 3, "网址": 3, "网站": 3,
    "地址": 3, "入口": 3, "怎么进": 3, "在哪": 3,
    "下单": 3, "已买": 3, "入手": 3,
    "必入": 3, "闭眼入": 3,
    # 合作意向 - 权重 3
    "合作": 3, "代理": 3, "加盟": 3, "商务": 3, "联系": 3, "私信": 3,
    "加我": 3, "微信": 3, "怎么联系": 3, "联系方式": 3, "想做": 3,
    # AI/科技产品 - 权重 3
    "充值": 3, "会员": 3, "api": 3, "接口": 3, "gpt": 3, "chatgpt": 3,
    "claude": 3, "模型": 3, "调用": 3, "聚合": 3, "平台": 2,
    "翻墙": 3, "梯子": 3, "vpn": 3,
    "求购": 3, "同款": 3, "求同款": 3, "抄作业": 3,
    # 咨询意向 - 权重 2
    "怎么用": 2, "好用吗": 2, "怎么样": 2, "效果": 2, "测评": 2, "评测": 2,
    "求教程": 2, "教程": 2, "怎么做": 2, "方法": 2, "攻略": 2, "如何使用": 2,
    # 需求表达 - 权重 2
    "想要": 2, "需要": 2, "求推荐": 2,
    "免费": 2, "试用": 2, "注册": 2, "账号": 2,
    "求分享": 2, "分享下": 2, "能发下": 2,
    # 获客相关 - 权重 2
    "带带我": 2, "教教我": 2, "入门": 2, "新手": 2,
    "ai": 2, "工具": 2, "软件": 2, "app": 2, "应用": 2,
    # 行动意向 - 权重 1
    "试试": 1, "想试": 1, "准备": 1, "打算": 1, "计划": 1,
    # 情感倾向 - 权重 1
    "喜欢": 1, "感谢": 1, "谢谢": 1,
}

# === 意向精准化:区分"明确意向"与"讨论/回忆" ===
# 通用强意向信号(适用所有行业):命中 → 保证"高"
# 注意:只放明确无歧义的信号。"买/想买"太宽泛(买吃的?买木板?),不放这里,
# 购买意向通过行业信号(如"想买琵琶")体现,确保语义明确
STRONG_INTENT_SIGNALS = [
    # 求资源/求链接(明确)
    "求链接", "求同款", "求推荐", "求教", "求分享", "求教程", "求购",
    # 询价(明确,带"多少钱/价格"等明确询价词)
    "多少钱", "怎么卖", "怎么收", "价格多少", "怎么算", "报价",
    # 报名/合作意向(明确)
    "想报名", "要报名", "想加入", "想合作", "加盟", "代理",
    # 咨询意向(明确)
    "怎么联系", "联系方式", "私信我", "加我", "咨询一下",
    # 教育/音乐行业通用信号(用更明确的组合,避免"老师""一节课"被叙述句误命中)
    "求谱", "求谱子", "求好老师", "找个老师", "找老师学",
    "学费多少", "课时费", "一节多少", "一节课多少",
    # 服务行业通用信号
    "上门", "量尺", "预约", "约课",
]

# 行业强意向信号模板:基于任务核心词动态生成(避免硬编码每个行业)
# 例:核心词"琵琶" → "想学琵琶/想买琵琶/琵琶多少钱/求推荐琵琶/..."
# 例:核心词"家具" → "想买家具/定制家具/家具多少钱/哪里买家具/..."
INDUSTRY_SIGNAL_TEMPLATES = [
    # 购买类(明确成交意愿)
    "想买{w}", "要买{w}", "想要{w}", "想入手{w}", "准备买{w}", "打算买{w}",
    "求购{w}", "想订{w}", "要订{w}",
    # 学习/体验类
    "想学{w}", "要学{w}", "想试{w}", "想体验{w}", "准备学{w}", "打算学{w}",
    # 询价类(明确询价=成交前置)
    "{w}多少钱", "{w}价格", "{w}怎么卖", "{w}怎么收", "{w}报价", "{w}价位",
    "{w}学费", "{w}收费",
    # 求资源类(明确求推荐/求链接=成交前置)
    "求推荐{w}", "求{w}", "求链接{w}", "求同款{w}",
    "哪里买{w}", "在哪买{w}", "哪里学{w}", "在哪学{w}", "哪里有{w}", "哪有{w}",
    "求教{w}", "求{w}老师", "求{w}谱",
    # 定制/服务类
    "定制{w}", "找{w}师傅", "找{w}老师", "需要{w}", "想做{w}",
    # 亲属需求类(培训/教育/家庭场景)
    "闺女要{w}", "儿子要{w}", "孩子要{w}", "女儿要{w}", "我家娃要{w}",
    "闺女想{w}", "儿子想{w}", "孩子想{w}", "女儿想{w}",
    "给我儿子买{w}", "给我闺女买{w}", "给我女儿买{w}", "给家里买{w}",
    # 主动咨询类
    "想了解{w}", "想咨询{w}", "想看看{w}", "想问问{w}", "请问{w}",
]

# 回忆性内容(命中即降级,优先级高于强意向 —— 回忆里的"想学"不是当前需求)
NOSTALGIA_PATTERNS = [
    "小时候", "当年", "曾经", "过去", "那年", "以前我", "以前也",
    "我那会", "那会儿", "那会", "那阵", "那阵子", "前几年", "前阵子",
    "我记得", "我记得我", "我之前", "我从前", "我想起",
]

# 讨论性/教育理念类(命中且无强意向 → 降级)
DISCUSSION_PATTERNS = [
    # 压力/痛苦
    "压力", "辛苦", "痛苦", "逼着", "逼孩子", "心疼", "掉泪", "落泪", "泪水", "哭",
    "枯燥", "乏味", "三分钟热度",
    # 教育理念
    "天赋", "戾气", "键盘侠", "该不该", "要不要学", "值得学", "值得吗",
    "有什么用", "用处", "作用", "好处", "坏处", "利弊",
    "滞后性", "延迟性", "兴趣班", "特长",
    # 评论性陈述
    "我觉得", "我认为", "90%", "评论区",
    # 通用讨论标志(适用更多行业)
    "讨论一下", "大家觉得", "你们觉得", "有人知道", "请问值得",
    # 诗词背诵/文学引用(非成交意向,如《琵琶行》背诵)
    "浔阳江头", "犹抱琵琶半遮面", "嘈嘈切切", "大珠小珠落玉盘", "千呼万唤",
    "此时无声胜有声", "同是天涯沦落人", "相逢何必曾相识", "东船西舫",
    # 古诗/古文通用标志
    "李白", "杜甫", "白居易", "苏轼", "辛弃疾", "李清照",
]

# 过去式购买/拥有陈述(命中且无强意向 → 降级,因为"买了XX"是陈述过去,非当前意向)
PAST_PURCHASE_PATTERNS = [
    "买了", "买来", "买的", "花了", "买过", "入手了", "已买", "买了个",
    "已经有了", "早就买了", "之前买的",
    # 陈述性购物经历(回忆买的过程,非当前意向)
    "我挑", "我说", "老板说", "店主说", "卖家说", "店家说",
    "看中了", "看中个", "看中了一", "问能不能", "便宜点", "换个",
    "仿了个", "给我仿", "给我做", "给我做款",
]


# 行业强意向信号缓存(任务上下文 → 合并后的信号列表),避免每条评论重复生成
_INDUSTRY_SIGNALS_CACHE: dict = {}


def _build_industry_strong_signals(task_name: str, task_keywords: list, task_desc: str = "") -> list:
    """基于任务核心词动态生成行业强意向信号

    通用模板 + 任务核心词 → 行业相关的强意向短语
    例如任务"学琵琶",核心词"琵琶":
      → ["想买琵琶", "想学琵琶", "琵琶多少钱", "求推荐琵琶", "闺女要琵琶", ...]
    例如任务"家具定制",核心词"家具":
      → ["想买家具", "定制家具", "家具多少钱", "哪里买家具", ...]
    """
    # 通用停用词(无行业信号价值)
    STOPWORDS = {"寻找", "学生", "家长", "推荐", "获客", "营销", "推广", "学员", "客户", "线索",
                 "寻找学", "学生家长", "寻找学", "目标"}
    # 行业后缀:包含这些后缀的词,额外提取后缀前的主体作为核心词
    # 例:"少儿英语培训" → 额外提取"少儿英语"和"英语";"全屋定制家具" → 额外提取"家具"
    INDUSTRY_SUFFIXES = ["培训", "课程", "机构", "定制", "装修", "带货", "护肤",
                         "代理", "加盟", "批发", "零售", "专卖", "旗舰店"]
    # 前导动词:去除后得到真正核心词(例:"学琵琶" → "琵琶","找老师" → "老师")
    LEADING_VERBS = ["寻找", "找", "学", "买", "做", "看", "想", "要", "求", "寻"]

    def _extract_core_words(text: str) -> set:
        """从一段文本提取核心词"""
        words = set()
        if not text:
            return words
        for part in re.split(r'[\s,，、_\-/]+', text.strip()):
            if not part or len(part) < 2 or part in STOPWORDS:
                continue
            part_lower = part.lower()
            # 1. 去除尾部"的人/的客户/的用户"等无信号后缀("宋式家具的人"→"宋式家具")
            TAIL_NOISE = ["的人", "的客户", "的用户", "的买家", "的卖家", "群体", "人群"]
            for tail in TAIL_NOISE:
                if part_lower.endswith(tail) and len(part_lower) > len(tail) + 2:
                    part_lower = part_lower[:-len(tail)]
                    break
            words.add(part_lower)
            # 2. 去除前导动词("学琵琶"→"琵琶","寻找宋氏家具"→"宋氏家具")
            #    支持多字前导动词("寻找"是2字)
            for vb in sorted(LEADING_VERBS, key=len, reverse=True):
                if part_lower.startswith(vb) and len(part_lower) > len(vb) + 1:
                    stripped = part_lower[len(vb):]
                    if len(stripped) >= 2 and stripped not in STOPWORDS:
                        words.add(stripped)
                    break
            # 3. 拆分行业后缀("少儿英语培训"→"少儿英语";"全屋定制家具"→"全屋定制")
            for suf in INDUSTRY_SUFFIXES:
                if suf in part_lower and part_lower.endswith(suf):
                    body = part_lower[:-len(suf)]
                    if len(body) >= 2:
                        words.add(body)
                    # 进一步:对"少儿英语"这种,再提取"英语"(去掉"少儿/成人/儿童"等修饰)
                    MODIFIERS = ["少儿", "成人", "儿童", "幼儿", "小学", "初中", "高中", "全屋", "整屋"]
                    for mod in MODIFIERS:
                        if body.startswith(mod) and len(body) > len(mod) + 1:
                            words.add(body[len(mod):])
                    break
            # 4. 对"宋氏家具"等含"氏/式"的词,额外提取主体("宋氏家具"→"家具")
            if any(ch in part_lower for ch in ["氏", "式"]):
                for marker in ["氏", "式"]:
                    if marker in part_lower:
                        suffix_part = part_lower.split(marker, 1)[1]
                        if len(suffix_part) >= 2:
                            words.add(suffix_part)
                        break
        return words

    core_words = set()
    for kw in (task_keywords or []):
        if isinstance(kw, str):
            core_words.update(_extract_core_words(kw))
    core_words.update(_extract_core_words(task_name))
    core_words.update(_extract_core_words(task_desc))

    # 过滤核心词:去掉含停用词的(避免生成"定制寻找宋氏家具"这类不通顺信号)
    clean_words = {w for w in core_words if not any(sw in w for sw in STOPWORDS)}

    signals = set()
    for w in clean_words:
        for tpl in INDUSTRY_SIGNAL_TEMPLATES:
            signals.add(tpl.format(w=w))
    return list(signals)


def calculate_user_value(content: str, like_count: str = "0") -> dict:
    """计算用户价值评分 - 优化版
    
    Returns:
        dict: {
            "score": int (0-100),
            "level": str ("高"|"中"|"低"),
            "intent": str ("购买意向"|"咨询意向"|"合作意向"|"潜在需求"|"一般关注"),
            "matched_keywords": list,
            "reason": str
        }
    """
    if not content:
        return {
            "score": 0,
            "level": "低",
            "intent": "无",
            "matched_keywords": [],
            "reason": "评论内容为空"
        }
    
    content_lower = content.lower()
    matched_high = []
    matched_low = []
    total_weight = 0
    
    for kw in HIGH_INTENT_KEYWORDS:
        if kw in content_lower:
            matched_high.append(kw)
            total_weight += KEYWORD_WEIGHTS.get(kw, 1)
    
    for kw in LOW_INTENT_KEYWORDS:
        if kw in content_lower:
            matched_low.append(kw)
    
    # 基础分数 20
    score = 20
    
    # 根据关键词权重加分（权重越高分数越高）
    score += total_weight * 12
    
    # 匹配关键词数量额外加分（多个关键词组合意向更强）
    if len(matched_high) >= 3:
        score += 10
    elif len(matched_high) >= 2:
        score += 5
    
    # 低意向关键词减分
    score -= len(matched_low) * 15
    
    # 点赞数加分（说明评论有影响力，是KOC/KOL）
    try:
        likes = int(like_count)
        if likes > 500:
            score += 20
        elif likes > 100:
            score += 15
        elif likes > 50:
            score += 10
        elif likes > 10:
            score += 5
    except:
        pass
    
    # 评论长度加分（详细评论通常更有价值）
    content_len = len(content)
    if content_len > 100:
        score += 8
    elif content_len > 50:
        score += 5
    elif content_len > 20:
        score += 2
    
    # 限制分数范围
    score = max(0, min(100, score))
    
    # 确定等级 - 降低高意向门槛，让更多潜在客户可以被触达
    if score >= 50:
        level = "高"
    elif score >= 25:
        level = "中"
    else:
        level = "低"
    
    # 确定意向类型
    if matched_high:
        buy_kws = ["买", "购买", "多少钱", "价格", "优惠", "折扣", "下单", "入手", "想要", "求链接", "必入", "闭眼入"]
        consult_kws = ["怎么用", "好用吗", "怎么样", "效果", "教程", "方法", "攻略", "如何使用", "求教程", "测评", "评测"]
        coop_kws = ["合作", "代理", "加盟", "商务", "联系", "私信", "加我", "咨询", "想做", "找"]
        need_kws = ["需要", "求推荐", "带带我", "教教我", "入门", "新手", "准备", "打算", "计划"]
        
        buy_match = any(kw in matched_high for kw in buy_kws)
        consult_match = any(kw in matched_high for kw in consult_kws)
        coop_match = any(kw in matched_high for kw in coop_kws)
        need_match = any(kw in matched_high for kw in need_kws)
        
        if buy_match:
            intent = "购买意向"
        elif coop_match:
            intent = "合作意向"
        elif consult_match:
            intent = "咨询意向"
        elif need_match:
            intent = "潜在需求"
        else:
            intent = "潜在需求"
    else:
        intent = "一般关注"
    
    # 生成原因
    if matched_high:
        top_kws = matched_high[:3]
        reason = f"匹配意向关键词: {', '.join(top_kws)}"
    elif matched_low:
        reason = f"包含负面关键词: {', '.join(matched_low[:3])}"
    else:
        reason = "普通评论"
    
    return {
        "score": score,
        "level": level,
        "intent": intent,
        "matched_keywords": matched_high,
        "reason": reason
    }


def _build_task_related_keywords(task_name: str, task_keywords: list, task_desc: str = "") -> list:
    """从任务名称/关键词/描述中提取"任务相关词",用于意向匹配加分

    例如任务"琵琶培训获客",关键词"琵琶 培训",会提取:
    ["琵琶", "培训", "琵琶培训", "学费", "课时", "老师", "学琴", ...] (后者来自基础相关词扩展)
    """
    related = set()
    # 1. 任务关键词
    for kw in (task_keywords or []):
        if isinstance(kw, str):
            # 按空格/逗号/中文逗号拆分
            for part in re.split(r'[\s,，]+', kw.strip()):
                if part and len(part) >= 2:
                    related.add(part.lower())
    # 2. 任务名称
    if task_name:
        for part in re.split(r'[\s,，、_\-/]+', task_name.strip()):
            if part and len(part) >= 2:
                related.add(part.lower())
    # 3. 任务描述
    if task_desc:
        for part in re.split(r'[\s,，、_\-/]+', task_desc.strip()):
            if part and len(part) >= 2:
                related.add(part.lower())

    # 4. 基础相关词扩展:出现任务关键词时,补充相关咨询词
    # 注意:不放"老师/琴/想学"等通用词(会被"我们老师""弹琴""想学唢呐""不想学"误命中)
    # 想学/怎么学等通过行业信号模板"想学{w}"精确生成(如"想学琵琶")
    EXTEND_MAP = {
        "培训": ["学费", "课时", "报名", "怎么收", "多少钱", "哪里学", "学琴", "上课"],
        "教": ["学费", "怎么教", "怎么收", "报名"],
        "学": ["怎么学", "学费", "入门", "新手", "零基础"],
        "机构": ["学费", "怎么收", "多少钱", "报名", "靠谱"],
        "课": ["学费", "课时", "怎么收", "报名"],
    }
    extended = set()
    for kw in list(related):
        for prefix, extras in EXTEND_MAP.items():
            if prefix in kw:
                extended.update(extras)
    related.update(extended)

    # 5. 去前导动词提取核心词(如"学琵琶"→"琵琶","寻找宋氏家具"→"宋氏家具")
    # 确保评论里只提"琵琶"但不提"学琵琶"时,仍能命中任务关键词
    # 注意:只对长度>=3的词提取,避免"找老师"→"老师"这种把通用词当核心词
    LEADING_VERBS = ["寻找", "想学", "要学", "想做", "要买", "想买", "定制", "全屋",
                     "学", "找", "寻", "买"]
    for kw in list(related):
        for verb in LEADING_VERBS:
            if kw.startswith(verb) and len(kw) > len(verb) + 1:
                core = kw[len(verb):]
                if len(core) >= 3:  # 核心词至少3字,避免"老师""琴"等通用词
                    related.add(core)

    return list(related)


def _apply_intent_downgrade(base: dict, content_lower: str, strong_signals: list = None,
                            nostal_as_high: bool = False) -> None:
    """意向精准化降级(公共逻辑,被两个分支调用)

    优先级:回忆 > 强意向 > 讨论/过去式购买
    - 回忆性内容:直接降到"中"(回忆里的"想学/多少钱"不是当前需求)
    - 讨论性/过去式购买:仅当未命中强意向时,从"高"降到"中"

    Args:
        base: 评分字典(原地修改)
        content_lower: 评论小写文本
        strong_signals: 当前任务的强意向信号列表(通用+行业),用于判断是否命中强意向
        nostal_as_high: 回忆是否仍保留"高"(默认 False,即回忆降级)
    """
    has_nostalgia = any(p in content_lower for p in NOSTALGIA_PATTERNS)
    strong_signals_list = strong_signals or STRONG_INTENT_SIGNALS
    has_strong_intent = any(s in content_lower for s in strong_signals_list)
    has_discussion = any(p in content_lower for p in DISCUSSION_PATTERNS)
    has_past_purchase = any(p in content_lower for p in PAST_PURCHASE_PATTERNS)

    # 长文本陈述检测:>50字且强意向信号密度低(命中次数<=1),且含讨论/过去式/回忆标志
    # 这类是"长篇叙述里夹一两个意向词",实际不是当前成交意向
    strong_hit_count = sum(1 for s in strong_signals_list if s in content_lower)
    is_long_narrative = (
        len(content_lower) > 50
        and strong_hit_count <= 1
        and (has_discussion or has_past_purchase or has_nostalgia)
    )

    if has_nostalgia and not nostal_as_high:
        # 回忆性内容:直接降级到中(即使命中强意向)
        if base["level"] == "高":
            base["level"] = "中"
            base["score"] = min(base["score"], 45)
            base["reason"] = f"回忆性内容,降级; " + base.get("reason", "")
    elif is_long_narrative:
        # 长篇陈述夹带零星意向词:降级(高→中)
        if base["level"] == "高":
            base["level"] = "中"
            base["score"] = min(base["score"], 45)
            base["reason"] = f"长篇陈述非当前意向,降级; " + base.get("reason", "")
    elif not has_strong_intent and (has_discussion or has_past_purchase):
        # 讨论性/过去式购买(无强意向):降级(高→中)
        if base["level"] == "高":
            base["level"] = "中"
            base["score"] = min(base["score"], 45)
            reason_part = "讨论性内容" if has_discussion else "过去式购买陈述"
            base["reason"] = f"{reason_part},降级; " + base.get("reason", "")


def calculate_user_value_for_task(content: str, like_count: str = "0",
                                  task_name: str = "", task_keywords: list = None,
                                  task_desc: str = "") -> dict:
    """针对任务上下文的用户价值评分

    在原 calculate_user_value 基础上,加入"任务相关词"加分 + 意向精准化:
    - 命中任务关键词/强意向信号 → 提升等级
    - 回忆/讨论/过去式购买 → 降级(避免占用高意向名额)
    """
    base = calculate_user_value(content, like_count)

    if not content:
        return base

    related_kws = _build_task_related_keywords(task_name, task_keywords or [], task_desc)
    if not related_kws:
        return base

    # 合并通用强意向信号 + 行业动态生成信号(带缓存,避免每条评论重复生成)
    cache_key = (task_name, tuple(task_keywords or []), task_desc)
    if cache_key in _INDUSTRY_SIGNALS_CACHE:
        strong_signals = _INDUSTRY_SIGNALS_CACHE[cache_key]
    else:
        industry_signals = _build_industry_strong_signals(task_name, task_keywords or [], task_desc)
        strong_signals = list(set(STRONG_INTENT_SIGNALS + industry_signals))
        # 缓存上限 200,避免内存无限增长
        if len(_INDUSTRY_SIGNALS_CACHE) >= 200:
            _INDUSTRY_SIGNALS_CACHE.clear()
        _INDUSTRY_SIGNALS_CACHE[cache_key] = strong_signals

    content_lower = content.lower()
    matched_task_kws = [kw for kw in related_kws if kw in content_lower]

    if not matched_task_kws:
        # 评论未命中任务关键词。但若命中强意向信号(多少钱/求链接/求谱等明确信号),
        # 仍视为高意向 —— 用户在视频评论区询价,即使没提"琵琶"也是明确需求
        # 注意:区分"行业特定信号"(如"想学琵琶")与"通用信号"(如"联系方式/私信我")
        # 通用信号在无关评论里也常见(如情感帖"删除联系方式"),需结合任务词或购买上下文
        industry_only_signals = [s for s in strong_signals if s not in STRONG_INTENT_SIGNALS]
        generic_signal_hits = [s for s in STRONG_INTENT_SIGNALS if s in content_lower]
        industry_signal_hits = [s for s in industry_only_signals if s in content_lower]

        # 行业特定信号命中(如"琵琶多少钱")→ 直接高意向
        if industry_signal_hits:
            if base["score"] < 50:
                base["score"] = max(50, base["score"] + 15)
            if base["level"] != "高":
                base["level"] = "高"
            base["reason"] = f"明确意向信号(未命中任务词); " + base.get("reason", "")
            _apply_intent_downgrade(base, content_lower, strong_signals, nostal_as_high=False)
            return base
        # 仅通用信号命中(如"联系方式/私信我"):需同时含购买/询价上下文才算高意向
        if generic_signal_hits:
            # 购买/询价上下文标志(避免情感帖"删除联系方式"误判)
            PURCHASE_CTX = ["买", "购", "下单", "订", "想要", "需要", "价格", "多少钱",
                            "便宜", "优惠", "预算", "求", "想了解", "想做", "咨询"]
            has_purchase_ctx = any(ctx in content_lower for ctx in PURCHASE_CTX)
            if has_purchase_ctx:
                if base["score"] < 50:
                    base["score"] = max(50, base["score"] + 15)
                if base["level"] != "高":
                    base["level"] = "高"
                base["reason"] = f"通用意向信号+购买上下文(未命中任务词); " + base.get("reason", "")
                _apply_intent_downgrade(base, content_lower, strong_signals, nostal_as_high=False)
                return base
        # 与任务不相关且无强意向:降分(避免无关评论占用高意向)
        base["score"] = max(0, base["score"] - 15)
        base["reason"] = (base.get("reason", "") + "; 与任务关键词不相关").strip("; ")
        # 降级:level 与 score 必须一致(避免 score>=50 但 level="中" 的不一致)
        if base["level"] == "高":
            base["level"] = "中"
            base["score"] = min(base["score"], 45)  # 降级时同步降 score
        elif base["level"] == "中" and base["score"] < 25:
            base["level"] = "低"
        return base

    # 命中任务相关词,加分(权重每词+8,上限+30)
    bonus = min(30, len(matched_task_kws) * 8)
    base["score"] = min(100, base["score"] + bonus)

    # 重新评级(基于新分数)
    if base["score"] >= 50:
        base["level"] = "高"
    elif base["score"] >= 25:
        base["level"] = "中"
    else:
        base["level"] = "低"

    # 合并匹配关键词
    existing = set(base.get("matched_keywords", []))
    existing.update(matched_task_kws)
    base["matched_keywords"] = list(existing)
    base["reason"] = f"匹配任务关键词: {', '.join(matched_task_kws[:3])}; " + base.get("reason", "")

    # === 意向精准化:区分"明确意向"与"讨论/回忆" ===
    # 命中强意向 → 保证"高";回忆/讨论/过去式购买 → 降级(回忆优先级最高)
    has_strong_intent = any(s in content_lower for s in strong_signals)
    if has_strong_intent:
        if base["score"] < 50:
            base["score"] = max(50, base["score"] + 15)
        if base["level"] != "高":
            base["level"] = "高"
        base["reason"] = f"明确意向信号; " + base.get("reason", "")
    # 走公共降级检查(回忆优先于强意向;讨论/过去式购买仅当无强意向时降级)
    _apply_intent_downgrade(base, content_lower, strong_signals, nostal_as_high=False)

    return base


async def _get_db_session() -> AsyncSession:
    """获取数据库会话"""
    from sqlalchemy.orm import sessionmaker
    from database.db_session import get_async_engine
    import config
    engine = get_async_engine(config.SAVE_DATA_OPTION)
    if not engine:
        raise HTTPException(status_code=500, detail="Database not configured")
    AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return AsyncSessionFactory()


def _apply_owner_filter(stmt, user: dict, model_cls):
    """为查询语句附加 owner_user_id 过滤条件(管理员不过滤)。

    使用方式:
        stmt = select(CrawlerTaskModel)
        stmt = _apply_owner_filter(stmt, user, CrawlerTaskModel)
    """
    cond = user_scope_filter(user, model_cls)
    if cond is not None:
        stmt = stmt.where(cond)
    return stmt


def _require_task_owned_by(task: CrawlerTaskModel, user: dict):
    """校验任务归属。非管理员且非任务所有者 -> 403"""
    if is_admin(user):
        return
    owner = getattr(task, "owner_user_id", "") or ""
    if owner and owner != str(user["id"]):
        raise HTTPException(status_code=403, detail="无权访问该任务")


def _owner_id(user: dict) -> str:
    return str(user["id"])


async def _task_to_dict(task: CrawlerTaskModel, session: AsyncSession = None) -> dict:
    """将ORM对象转换为字典，包含实时统计数据"""
    need_close = False
    if session is None:
        session = await _get_db_session()
        need_close = True

    try:
        # 根据平台查询统计数据 - 优先按 task_id 关联
        content_count = 0
        comment_count = 0

        # 从未运行过的任务不显示历史数据
        has_run = task.status in ("running", "completed", "paused", "failed")

        if task.platform in ("dy", "douyin"):
            # 只按 task_id 精确统计
            result = await session.execute(
                select(func.count()).where(
                    DouyinAweme.task_id == task.id
                )
            )
            content_count = result.scalar() or 0

            result = await session.execute(
                select(func.count()).where(
                    DouyinAwemeComment.task_id == task.id
                )
            )
            comment_count = result.scalar() or 0

        elif task.platform in ("xhs", "xiaohongshu"):
            result = await session.execute(
                select(func.count()).where(
                    XhsNote.task_id == task.id
                )
            )
            content_count = result.scalar() or 0

            result = await session.execute(
                select(func.count()).where(
                    XhsNoteComment.task_id == task.id
                )
            )
            comment_count = result.scalar() or 0

        elif task.platform in ("ks", "kuaishou"):
            from database.models import KuaishouVideo, KuaishouVideoComment
            result = await session.execute(
                select(func.count()).select_from(KuaishouVideo).where(KuaishouVideo.task_id == task.id)
            )
            content_count = result.scalar() or 0
            result = await session.execute(
                select(func.count()).select_from(KuaishouVideoComment).where(KuaishouVideoComment.task_id == task.id)
            )
            comment_count = result.scalar() or 0

        elif task.platform in ("wb", "weibo"):
            from database.models import WeiboNote, WeiboNoteComment
            result = await session.execute(
                select(func.count()).select_from(WeiboNote).where(WeiboNote.task_id == task.id)
            )
            content_count = result.scalar() or 0
            result = await session.execute(
                select(func.count()).select_from(WeiboNoteComment).where(WeiboNoteComment.task_id == task.id)
            )
            comment_count = result.scalar() or 0

        elif task.platform in ("bili", "bilibili"):
            from database.models import BilibiliVideoComment
            # BilibiliVideo 表无 task_id 字段，改用评论表去重统计视频数
            result = await session.execute(
                select(func.count(func.distinct(BilibiliVideoComment.video_id)))
                .where(BilibiliVideoComment.task_id == task.id)
            )
            content_count = result.scalar() or 0
            result = await session.execute(
                select(func.count()).select_from(BilibiliVideoComment)
                .where(BilibiliVideoComment.task_id == task.id)
            )
            comment_count = result.scalar() or 0

        elif task.platform == "tieba":
            from database.models import TiebaNote, TiebaComment
            result = await session.execute(
                select(func.count()).select_from(TiebaNote).where(TiebaNote.task_id == task.id)
            )
            content_count = result.scalar() or 0
            result = await session.execute(
                select(func.count()).select_from(TiebaComment).where(TiebaComment.task_id == task.id)
            )
            comment_count = result.scalar() or 0

        elif task.platform == "zhihu":
            from database.models import ZhihuContent, ZhihuComment
            # ZhihuContent 表无 task_id 字段,改用 source_keyword 模糊关联(容错)
            try:
                keywords = json.loads(task.keywords) if task.keywords else []
                if keywords:
                    result = await session.execute(
                        select(func.count()).select_from(ZhihuContent).where(
                            ZhihuContent.source_keyword.in_(keywords)
                        )
                    )
                    content_count = result.scalar() or 0
                else:
                    content_count = 0
            except Exception:
                content_count = 0
            result = await session.execute(
                select(func.count()).select_from(ZhihuComment).where(ZhihuComment.task_id == task.id)
            )
            comment_count = result.scalar() or 0

        else:
            content_count = 0
            comment_count = 0

        # 实时查询获客线索数量
        result = await session.execute(
            select(func.count()).where(
                CustomerLead.task_id == task.id
            )
        )
        lead_count = result.scalar() or 0

        promo_config = None
        if task.promo_config:
            try:
                promo_config = json.loads(task.promo_config)
            except:
                promo_config = None

        return {
            "id": task.id,
            "name": task.name,
            "platform": task.platform,
            "keywords": json.loads(task.keywords) if task.keywords else [],
            "crawl_type": task.crawl_type,
            "data_types": json.loads(task.data_types) if task.data_types else ["note", "comment"],
            "max_notes": task.max_notes,
            "min_lead_score": task.min_lead_score,
            "enable_lead_capture": bool(task.enable_lead_capture),
            "schedule_type": task.schedule_type,
            "status": task.status,
            "created_ts": task.created_ts,
            "total_crawled": content_count,
            "total_leads": lead_count,
            "comment_count": comment_count,
            "promo_config": promo_config,
            "publish_time_type": task.publish_time_type or 0,
            "owner_user_id": getattr(task, "owner_user_id", "") or "",
        }
    finally:
        if need_close:
            await session.close()


class PromoConfig(BaseModel):
    product_name: str = "AI聚合平台"
    product_desc: str = "一站式AI工具平台，集成ChatGPT、Claude、Gemini等主流大模型"
    promo_link: str = ""
    contact_wechat: str = ""
    price_info: str = ""
    discount_info: str = ""
    free_quota: str = ""
    solution_desc: str = ""
    tutorial_name: str = ""
    tutorial_desc: str = ""
    cooperation_desc: str = ""
    commission_rate: str = ""


class TaskCreateRequest(BaseModel):
    name: str
    platform: str
    keywords: List[str]
    crawl_type: str = "search"
    data_types: List[str] = ["note", "comment"]
    max_notes: int = 10000
    min_lead_score: int = 50
    enable_lead_capture: bool = True
    schedule_type: str = "once"
    status: str = "pending"
    created_ts: Optional[int] = None
    promo_config: Optional[PromoConfig] = None
    publish_time_type: int = 0


class UpdatePromoRequest(BaseModel):
    promo_config: PromoConfig


class TaskResponse(BaseModel):
    id: str
    name: str
    platform: str
    keywords: List[str]
    crawl_type: str
    data_types: List[str]
    max_notes: int
    min_lead_score: int
    enable_lead_capture: bool
    schedule_type: str
    status: str
    created_ts: int
    total_crawled: int
    total_leads: int
    comment_count: int = 0
    promo_config: Optional[dict] = None
    publish_time_type: int = 0
    owner_user_id: str = ""


@router.get("", response_model=List[TaskResponse])
async def list_tasks(current_user: dict = Depends(get_current_user)):
    """获取任务列表 - 包含实时统计数据(按用户隔离)"""
    session = await _get_db_session()
    try:
        stmt = select(CrawlerTaskModel).order_by(desc(CrawlerTaskModel.created_ts))
        stmt = _apply_owner_filter(stmt, current_user, CrawlerTaskModel)
        result = await session.execute(stmt)
        tasks = result.scalars().all()
        return [await _task_to_dict(t, session) for t in tasks]
    finally:
        await session.close()


@router.post("", response_model=dict)
async def create_task(request: TaskCreateRequest, current_user: dict = Depends(get_current_user)):
    """创建新任务

    商业化校验(v6.6):
    - 检查用户套餐是否在有效期内
    - 检查任务数是否超限
    - 根据套餐限制 max_notes 和 publish_time_type
    """
    from ..services.plan import (
        check_task_quota, clamp_max_notes, clamp_publish_time_type, is_plan_active
    )

    # 套餐有效性校验
    if not is_plan_active(current_user):
        raise HTTPException(status_code=403, detail="套餐已过期,请续费后继续使用")

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    now = int(time.time() * 1000)

    session = await _get_db_session()
    try:
        # 配额校验:检查用户当前任务数
        if not is_admin(current_user):
            count_result = await session.execute(
                select(func.count()).where(CrawlerTaskModel.owner_user_id == str(current_user["id"]))
            )
            current_task_count = count_result.scalar() or 0
            allowed, msg = await check_task_quota(current_user, current_task_count)
            if not allowed:
                raise HTTPException(status_code=403, detail=msg)

        # 根据套餐限制 max_notes 和 publish_time_type
        adjusted_max_notes, notes_msg = clamp_max_notes(current_user, request.max_notes)
        adjusted_publish_time, time_msg = clamp_publish_time_type(current_user, request.publish_time_type)

        promo_config_json = ""
        if request.promo_config:
            promo_data = request.promo_config.model_dump()
            # 自动去掉推广链接中的 https:// 和 http:// 前缀
            link = promo_data.get("promo_link", "") or ""
            if link.startswith("https://"):
                promo_data["promo_link"] = link[8:]
            elif link.startswith("http://"):
                promo_data["promo_link"] = link[7:]
            promo_config_json = json.dumps(promo_data, ensure_ascii=False)

        task = CrawlerTaskModel(
            id=task_id,
            name=request.name,
            platform=request.platform,
            keywords=json.dumps(request.keywords, ensure_ascii=False),
            crawl_type=request.crawl_type,
            data_types=json.dumps(request.data_types, ensure_ascii=False),
            max_notes=adjusted_max_notes,
            min_lead_score=request.min_lead_score,
            enable_lead_capture=1 if request.enable_lead_capture else 0,
            schedule_type=request.schedule_type,
            schedule_time=getattr(request, 'schedule_time', '09:00') or '09:00',
            schedule_weekday=getattr(request, 'schedule_weekday', 1) or 1,
            status=request.status,
            created_ts=request.created_ts or now,
            updated_ts=now,
            total_crawled=0,
            total_leads=0,
            promo_config=promo_config_json,
            publish_time_type=adjusted_publish_time,
            owner_user_id=_owner_id(current_user),
        )
        # 计算 next_scheduled_ts
        if request.schedule_type in ("daily", "weekly"):
            from ..services.task_scheduler import schedule_task_now
            task.next_scheduled_ts = schedule_task_now(
                task_id, request.schedule_type,
                task.schedule_time, task.schedule_weekday
            )
        session.add(task)
        await session.commit()

        # 更新缓存
        _tasks_cache[task_id] = await _task_to_dict(task)

        # 构建提示信息
        notices = []
        if notes_msg:
            notices.append(notes_msg)
        if time_msg:
            notices.append(time_msg)
        message = "任务创建成功"
        if notices:
            message += "(" + "; ".join(notices) + ")"

        return {"success": True, "task_id": task_id, "message": message}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        import traceback
        error_detail = f"创建任务失败: {str(e)}\n请求参数: name={request.name}, platform={request.platform}, keywords={request.keywords}\n用户信息: id={current_user.get('id')}, username={current_user.get('username')}\n堆栈:\n{traceback.format_exc()}"
        print(f"[ERROR] {error_detail}")
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")
    finally:
        await session.close()


async def _sync_logs_to_task(task_id: str):
    """后台任务：将 crawler_manager 的日志同步到数据库，并同步爬虫状态"""
    from ..services import crawler_manager
    
    last_log_id = 0
    while True:
        try:
            await asyncio.sleep(1)
            
            # 检查 crawler_manager 是否还在运行该任务
            if not crawler_manager.is_running(task_id):
                print(f"[tasks] Task {task_id} no longer running in crawler_manager, updating status")
                # 同步状态到数据库
                session = await _get_db_session()
                try:
                    result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
                    task = result.scalar_one_or_none()
                    if task and task.status == "running":
                        # 实时查询采集到的数据量（task.total_crawled 字段不会被爬虫子进程更新，一直是0）
                        # 通过查询实际的 aweme/comment 表来统计
                        actual_crawled = 0
                        try:
                            if task.platform in ("dy", "douyin"):
                                r = await session.execute(
                                    select(func.count()).select_from(DouyinAweme).where(DouyinAweme.task_id == task_id)
                                )
                                actual_crawled = r.scalar() or 0
                            elif task.platform in ("xhs", "xiaohongshu"):
                                r = await session.execute(
                                    select(func.count()).select_from(XhsNote).where(XhsNote.task_id == task_id)
                                )
                                actual_crawled = r.scalar() or 0
                            elif task.platform in ("ks", "kuaishou"):
                                from database.models import KuaishouVideo
                                r = await session.execute(
                                    select(func.count()).select_from(KuaishouVideo).where(KuaishouVideo.task_id == task_id)
                                )
                                actual_crawled = r.scalar() or 0
                            elif task.platform in ("wb", "weibo"):
                                from database.models import WeiboNote
                                r = await session.execute(
                                    select(func.count()).select_from(WeiboNote).where(WeiboNote.task_id == task_id)
                                )
                                actual_crawled = r.scalar() or 0
                            elif task.platform in ("bili", "bilibili"):
                                from database.models import BilibiliVideoComment
                                r = await session.execute(
                                    select(func.count(func.distinct(BilibiliVideoComment.video_id)))
                                    .where(BilibiliVideoComment.task_id == task_id)
                                )
                                actual_crawled = r.scalar() or 0
                            elif task.platform == "tieba":
                                from database.models import TiebaNote
                                r = await session.execute(
                                    select(func.count()).select_from(TiebaNote).where(TiebaNote.task_id == task_id)
                                )
                                actual_crawled = r.scalar() or 0
                        except Exception as e:
                            print(f"[tasks] Error counting actual crawled data: {e}")
                        
                        # 更新 task.total_crawled 字段（保持数据库字段与实际一致）
                        task.total_crawled = actual_crawled
                        
                        # 判断任务是否成功：有数据则 completed，无数据则 failed
                        if actual_crawled > 0:
                            task.status = "completed"
                        else:
                            task.status = "failed"
                            # 从日志中提取错误信息写入 error_message
                            try:
                                logs = crawler_manager.get_task_logs(task_id)
                                error_logs = [l for l in logs if l.get("level") in ("error", "critical")]
                                if error_logs:
                                    task.error_message = error_logs[-1].get("message", "")[:500]
                            except Exception:
                                pass
                        task.updated_ts = int(time.time() * 1000)
                        await session.commit()
                        _tasks_cache.pop(task_id, None)
                        print(f"[tasks] Task {task_id} status updated to: {task.status}")

                        # === 商业化用量统计(v6.6) ===
                        # 任务完成时统计本次采集量,记入用户用量(用于配额校验和按量计费)
                        try:
                            from ..services.plan import record_usage
                            _owner_str = (getattr(task, "owner_user_id", "") or "").strip()
                            if _owner_str:
                                _owner_uid = int(_owner_str)
                                # 统计本次任务的评论数
                                comments_count = 0
                                if task.platform in ("dy", "douyin"):
                                    r = await session.execute(
                                        select(func.count()).select_from(DouyinAwemeComment).where(DouyinAwemeComment.task_id == task_id)
                                    )
                                    comments_count = r.scalar() or 0
                                elif task.platform in ("xhs", "xiaohongshu"):
                                    r = await session.execute(
                                        select(func.count()).select_from(XhsNoteComment).where(XhsNoteComment.task_id == task_id)
                                    )
                                    comments_count = r.scalar() or 0
                                # 统计本次任务的线索数
                                leads_count = task.total_leads or 0
                                # 记录用量(仅非管理员)
                                result = await record_usage(
                                    user_id=_owner_uid,
                                    notes_count=actual_crawled,
                                    comments_count=comments_count,
                                    leads_count=leads_count,
                                )
                                print(f"[tasks] Usage recorded for user {_owner_uid}: {result.get('message')}, charged={result.get('charged')}分")
                        except Exception as e:
                            print(f"[tasks] Error recording usage: {e}")
                except Exception as e:
                    await session.rollback()
                    print(f"[tasks] Error updating task status: {e}")
                finally:
                    await session.close()
                break
            
            # 检查任务是否还在运行
            session = await _get_db_session()
            try:
                result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
                task = result.scalar_one_or_none()
                if not task or task.status not in ["running", "pending"]:
                    break
            finally:
                await session.close()
                
            # 获取 crawler_manager 中该任务的新日志
            logs = crawler_manager.logs(task_id)
            if logs and len(logs) > last_log_id:
                new_logs = logs[last_log_id:]
                session = await _get_db_session()
                try:
                    for entry in new_logs:
                        log = TaskLogModel(
                            task_id=task_id,
                            level=entry.level,
                            message=entry.message,
                            add_ts=int(time.time() * 1000),
                        )
                        session.add(log)
                    await session.commit()
                except Exception as e:
                    await session.rollback()
                    print(f"[tasks] Save logs error: {e}")
                finally:
                    await session.close()
                last_log_id = len(logs)
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[tasks] Log sync error: {e}")
            await asyncio.sleep(2)


@router.post("/{task_id}/start")
async def start_task(task_id: str, current_user: dict = Depends(get_current_user)):
    """启动任务"""
    global _log_sync_tasks

    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)
        
        # 调用实际爬虫
        from ..schemas import PlatformEnum, LoginTypeEnum, CrawlerTypeEnum, SaveDataOptionEnum, CrawlerStartRequest
        from ..services import crawler_manager
        
        platform_map = {
            "xhs": PlatformEnum.XHS,
            "douyin": PlatformEnum.DOUYIN,
            "dy": PlatformEnum.DOUYIN,
            "kuaishou": PlatformEnum.KUAISHOU,
            "ks": PlatformEnum.KUAISHOU,
            "bilibili": PlatformEnum.BILIBILI,
            "bili": PlatformEnum.BILIBILI,
            "weibo": PlatformEnum.WEIBO,
            "wb": PlatformEnum.WEIBO,
            "tieba": PlatformEnum.TIEBA,
            "zhihu": PlatformEnum.ZHIHU,
            "x_twitter": PlatformEnum.X_TWITTER,
            "twitter": PlatformEnum.X_TWITTER,
        }
        
        keywords = json.loads(task.keywords) if task.keywords else []
        keywords_str = ",".join(keywords) if isinstance(keywords, list) else str(keywords)
        
        # 智能处理关键词：拆分长关键词、去除无意义词
        cleaned_keywords = []
        noise_words = ["寻找", "求", "的人", "有没有", "谁知道", "推荐", "求推荐", "哪里有", "怎么找", "的人"]
        for kw in keywords_str.split(","):
            kw = kw.strip()
            if not kw:
                continue
            # 空格分隔的词拆成多个关键词
            for sub_kw in kw.split():
                sub_kw = sub_kw.strip()
                if not sub_kw:
                    continue
                # 去除无意义前缀/后缀
                for noise in noise_words:
                    if sub_kw.startswith(noise):
                        sub_kw = sub_kw[len(noise):].strip()
                    if sub_kw.endswith(noise):
                        sub_kw = sub_kw[:-len(noise)].strip()
                if sub_kw and len(sub_kw) >= 2:
                    cleaned_keywords.append(sub_kw)
        
        # 去重
        cleaned_keywords = list(dict.fromkeys(cleaned_keywords))
        if cleaned_keywords:
            keywords_str = ",".join(cleaned_keywords)
        
        if cleaned_keywords:
            print(f"[tasks] Keywords cleaned: {keywords} -> {keywords_str}")

        # 商业化校验(v6.6):启动前再次校验套餐有效性,并根据套餐限制 max_notes/publish_time
        from ..services.plan import (
            is_plan_active, clamp_max_notes, clamp_publish_time_type,
            get_min_comments_target, get_max_comments_limit
        )
        if not is_plan_active(current_user):
            raise HTTPException(status_code=403, detail="套餐已过期,请续费后启动任务")

        # 启动时根据套餐再次限制(防止用户在任务创建后套餐降级)
        runtime_max_notes, _ = clamp_max_notes(current_user, task.max_notes or 10000)
        runtime_publish_time, _ = clamp_publish_time_type(current_user, task.publish_time_type or 0)
        # 如果运行时限制更严格,同步更新任务配置
        if runtime_max_notes != task.max_notes:
            task.max_notes = runtime_max_notes
        if runtime_publish_time != task.publish_time_type:
            task.publish_time_type = runtime_publish_time

        # 评论数保障:根据套餐设置最低评论采集目标(确保关键数据)
        min_comments_target = get_min_comments_target(current_user)
        max_comments_limit = get_max_comments_limit(current_user)

        config = CrawlerStartRequest(
            platform=platform_map.get(task.platform, PlatformEnum.DOUYIN),
            login_type=LoginTypeEnum.COOKIE,
            crawler_type=CrawlerTypeEnum.SEARCH,
            keywords=keywords_str,
            save_option=SaveDataOptionEnum.POSTGRES,
            max_notes_count=runtime_max_notes,
            publish_time_type=runtime_publish_time,
            # 评论数保障(v6.6):限制单视频评论采集数,避免低级套餐过度采集
            # 默认单视频最多1000条评论(足够覆盖大部分热门视频的高意向评论)
            max_comments_count=max_comments_limit if max_comments_limit > 0 else 1000,
            headless=False,
            task_id=task_id,
        )
        
        # 提取任务创建者的 user_id(用于加载该用户的 Cookie,实现用户隔离)
        _owner_str = (getattr(task, "owner_user_id", "") or "").strip()
        _owner_uid_int = None
        if _owner_str:
            try:
                _owner_uid_int = int(_owner_str)
            except (ValueError, TypeError):
                _owner_uid_int = None

        success = await crawler_manager.start(config, task_id=task_id, owner_user_id=_owner_uid_int)
        if success:
            task.status = "running"
            task.updated_ts = int(time.time() * 1000)
            await session.commit()
            
            # 为该任务启动独立的日志同步
            if task_id in _log_sync_tasks and not _log_sync_tasks[task_id].done():
                _log_sync_tasks[task_id].cancel()
            _log_sync_tasks[task_id] = asyncio.create_task(_sync_logs_to_task(task_id))
            
            return {"success": True, "message": "Crawler started"}
        else:
            return {"success": False, "message": "Crawler already running for this task"}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.post("/{task_id}/pause")
async def pause_task(task_id: str, current_user: dict = Depends(get_current_user)):
    """暂停任务"""
    global _log_sync_tasks

    # 停止爬虫进程
    from ..services import crawler_manager
    await crawler_manager.stop(task_id=task_id)

    # 取消该任务的日志同步
    if task_id in _log_sync_tasks and not _log_sync_tasks[task_id].done():
        _log_sync_tasks[task_id].cancel()
        del _log_sync_tasks[task_id]

    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)
        task.status = "paused"
        task.updated_ts = int(time.time() * 1000)
        await session.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, current_user: dict = Depends(get_current_user)):
    """重启任务（将失败/已完成的任务重置为待启动状态，然后启动）"""
    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        # 重置任务状态
        task.status = "pending"
        task.total_crawled = 0
        task.total_leads = 0
        task.error_message = ""
        task.updated_ts = int(time.time() * 1000)
        await session.commit()

        # 清空旧日志
        from sqlalchemy import delete
        await session.execute(delete(TaskLogModel).where(TaskLogModel.task_id == task_id))
        await session.commit()

        # 调用启动逻辑
        return await start_task(task_id, current_user)
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.put("/{task_id}/promo")
async def update_task_promo(task_id: str, request: UpdatePromoRequest, current_user: dict = Depends(get_current_user)):
    """更新任务推广配置"""
    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        if request.promo_config:
            promo_data = request.promo_config.model_dump()
            # 自动去掉推广链接中的 https:// 和 http:// 前缀
            link = promo_data.get("promo_link", "") or ""
            if link.startswith("https://"):
                promo_data["promo_link"] = link[8:]
            elif link.startswith("http://"):
                promo_data["promo_link"] = link[7:]
            task.promo_config = json.dumps(promo_data, ensure_ascii=False)
            task.updated_ts = int(time.time() * 1000)
            await session.commit()
            # 清除缓存
            if task_id in _tasks_cache:
                del _tasks_cache[task_id]
            return {"success": True, "message": "推广配置已更新"}
        else:
            return {"success": False, "message": "推广配置为空"}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.delete("/{task_id}")
async def delete_task(task_id: str, current_user: dict = Depends(get_current_user)):
    """删除任务"""
    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        # 删除关联的日志和线索
        from sqlalchemy import delete
        await session.execute(delete(TaskLogModel).where(TaskLogModel.task_id == task_id))
        await session.execute(delete(CustomerLead).where(CustomerLead.task_id == task_id))
        
        # 删除关联的评论数据
        platform = task.platform or ""
        platform_comment_map = {
            "dy": DouyinAwemeComment,
            "douyin": DouyinAwemeComment,
        }
        try:
            from database.models import XhsNoteComment
            platform_comment_map["xhs"] = XhsNoteComment
        except ImportError:
            pass
        try:
            from database.models import KuaishouVideoComment
            platform_comment_map["ks"] = KuaishouVideoComment
            platform_comment_map["kuaishou"] = KuaishouVideoComment
        except ImportError:
            pass
        try:
            from database.models import BiliVideoComment
            platform_comment_map["bili"] = BiliVideoComment
            platform_comment_map["bilibili"] = BiliVideoComment
        except ImportError:
            pass
        try:
            from database.models import WeiboNoteComment
            platform_comment_map["wb"] = WeiboNoteComment
            platform_comment_map["weibo"] = WeiboNoteComment
        except ImportError:
            pass
        
        comment_model = platform_comment_map.get(platform)
        if comment_model and hasattr(comment_model, 'task_id'):
            await session.execute(delete(comment_model).where(comment_model.task_id == task_id))
        
        # 删除关联的获客任务
        await session.execute(delete(AutoOutreachJobModel).where(AutoOutreachJobModel.task_id == task_id))

        await session.delete(task)
        await session.commit()

        if task_id in _tasks_cache:
            del _tasks_cache[task_id]
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.delete("/{task_id}/comments")
async def delete_task_comments(task_id: str, current_user: dict = Depends(get_current_user)):
    """删除指定任务的爬虫数据（评论）"""
    from sqlalchemy import delete as sql_delete

    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        platform = task.platform or ""
        deleted_count = 0

        # 根据平台删除对应评论表的数据
        platform_comment_map = {
            "dy": DouyinAwemeComment,
            "douyin": DouyinAwemeComment,
        }
        # 尝试其他平台模型
        try:
            from database.models import XhsNoteComment
            platform_comment_map["xhs"] = XhsNoteComment
        except ImportError:
            pass
        try:
            from database.models import KuaishouVideoComment
            platform_comment_map["ks"] = KuaishouVideoComment
            platform_comment_map["kuaishou"] = KuaishouVideoComment
        except ImportError:
            pass
        try:
            from database.models import BiliVideoComment
            platform_comment_map["bili"] = BiliVideoComment
            platform_comment_map["bilibili"] = BiliVideoComment
        except ImportError:
            pass
        try:
            from database.models import WeiboNoteComment
            platform_comment_map["wb"] = WeiboNoteComment
            platform_comment_map["weibo"] = WeiboNoteComment
        except ImportError:
            pass

        model = platform_comment_map.get(platform)
        if model and hasattr(model, 'task_id'):
            res = await session.execute(
                sql_delete(model).where(model.task_id == task_id)
            )
            deleted_count = res.rowcount

        # 更新任务的爬取计数
        task.total_crawled = 0
        task.total_leads = 0
        await session.commit()

        return {"success": True, "deleted_count": deleted_count}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.get("/dashboard", response_model=dict)
async def get_dashboard(current_user: dict = Depends(get_current_user)):
    """获取Dashboard数据(按用户隔离)"""
    from database.models import CustomerLead
    from datetime import datetime, timedelta, timezone

    session = await _get_db_session()
    try:
        # 从数据库计算实时统计(按用户过滤)
        stmt = select(func.sum(CrawlerTaskModel.total_leads))
        stmt = _apply_owner_filter(stmt, current_user, CrawlerTaskModel)
        result = await session.execute(stmt)
        total_leads = result.scalar() or 0

        stmt = select(func.count()).select_from(CrawlerTaskModel).where(CrawlerTaskModel.status == "running")
        stmt = _apply_owner_filter(stmt, current_user, CrawlerTaskModel)
        result = await session.execute(stmt)
        running_count = result.scalar() or 0

        stmt = select(func.count()).select_from(CrawlerTaskModel).where(CrawlerTaskModel.status == "pending")
        stmt = _apply_owner_filter(stmt, current_user, CrawlerTaskModel)
        result = await session.execute(stmt)
        pending_count = result.scalar() or 0

        # 从 CustomerLead 表统计真实数据(按用户隔离)
        # 今日新线索数
        now = datetime.now(timezone.utc)
        today_start_ms = int((now - timedelta(hours=now.hour, minutes=now.minute, seconds=now.second, microseconds=now.microsecond)).timestamp() * 1000)

        today_stmt = select(func.count()).select_from(CustomerLead)
        today_cond = user_scope_filter(current_user, CustomerLead)
        if today_cond is not None:
            today_stmt = today_stmt.where(today_cond)
        today_stmt = today_stmt.where(CustomerLead.add_ts >= today_start_ms)
        today_result = await session.execute(today_stmt)
        today_new = today_result.scalar() or 0

        # 待处理线索数(status=new)
        pending_leads_stmt = select(func.count()).select_from(CustomerLead)
        pending_leads_cond = user_scope_filter(current_user, CustomerLead)
        if pending_leads_cond is not None:
            pending_leads_stmt = pending_leads_stmt.where(pending_leads_cond)
        pending_leads_stmt = pending_leads_stmt.where(CustomerLead.status == "new")
        pending_leads_result = await session.execute(pending_leads_stmt)
        pending_leads_count = pending_leads_result.scalar() or 0

        # 已转化线索数(status=converted)
        converted_stmt = select(func.count()).select_from(CustomerLead)
        converted_cond = user_scope_filter(current_user, CustomerLead)
        if converted_cond is not None:
            converted_stmt = converted_stmt.where(converted_cond)
        converted_stmt = converted_stmt.where(CustomerLead.status == "converted")
        converted_result = await session.execute(converted_stmt)
        converted_count = converted_result.scalar() or 0

        # 从 CustomerLead 表统计真实总线索数
        total_leads_stmt = select(func.count()).select_from(CustomerLead)
        total_leads_cond = user_scope_filter(current_user, CustomerLead)
        if total_leads_cond is not None:
            total_leads_stmt = total_leads_stmt.where(total_leads_cond)
        total_leads_result = await session.execute(total_leads_stmt)
        total_leads_real = total_leads_result.scalar() or 0

        # 转化率
        conversion_rate = round(converted_count / total_leads_real * 100, 1) if total_leads_real > 0 else 0.0

        # 近7天趋势数据(从线索表统计)
        trends = []
        for i in range(6, -1, -1):
            day_start = now - timedelta(days=i)
            day_start_ms = int(day_start.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            day_end_ms = day_start_ms + 86400000
            day_stmt = select(func.count()).select_from(CustomerLead)
            day_cond = user_scope_filter(current_user, CustomerLead)
            if day_cond is not None:
                day_stmt = day_stmt.where(day_cond)
            day_stmt = day_stmt.where(CustomerLead.add_ts >= day_start_ms).where(CustomerLead.add_ts < day_end_ms)
            day_result = await session.execute(day_stmt)
            day_count = day_result.scalar() or 0
            trends.append({"date": day_start.strftime("%Y-%m-%d"), "leads": day_count})

        return {
            "summary": {
                "today_new": today_new,
                "total_leads": total_leads_real,
                "pending_count": pending_leads_count,
                "converted_count": converted_count,
                "conversion_rate": conversion_rate,
                "running_tasks": running_count,
            },
            "trends": trends,
            "recent_leads": [],
        }
    finally:
        await session.close()


@router.get("/outreach-records")
async def get_all_outreach_records(limit: int = 50, offset: int = 0, current_user: dict = Depends(get_current_user)):
    """获取所有触达记录（管理后台用,按用户隔离）"""
    engine = get_async_engine(config.SAVE_DATA_OPTION)
    if not engine:
        return {"records": [], "total": 0}

    try:
        AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionFactory() as session:
            count_stmt = select(func.count()).select_from(OutreachRecord)
            count_stmt = _apply_owner_filter(count_stmt, current_user, OutreachRecord)
            count_result = await session.execute(count_stmt)
            total = count_result.scalar() or 0

            sel_stmt = select(OutreachRecord).order_by(desc(OutreachRecord.send_time))
            sel_stmt = _apply_owner_filter(sel_stmt, current_user, OutreachRecord)
            result = await session.execute(
                sel_stmt.offset(offset).limit(limit)
            )
            records = result.scalars().all()

            return {
                "records": [
                    {
                        "id": r.id,
                        "task_id": r.task_id,
                        "platform": r.platform,
                        "user_id": r.user_id,
                        "sec_uid": r.sec_uid,
                        "nickname": r.nickname,
                        "user_url": r.user_url,
                        "message_content": r.message_content,
                        "status": r.status,
                        "error_message": r.error_message,
                        "screenshot": r.screenshot,
                        "send_time": r.send_time,
                        "add_ts": r.add_ts,
                    }
                    for r in records
                ],
                "total": total,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auto-outreach/jobs")
async def list_auto_outreach_jobs(task_id: str = None, limit: int = 20, offset: int = 0, current_user: dict = Depends(get_current_user)):
    """获取自动获客任务列表，按task_id隔离 + 用户隔离"""
    session = await _get_db_session()
    try:
        # 构建查询，按task_id过滤 + owner_user_id 过滤
        query = select(AutoOutreachJobModel)
        count_query = select(func.count()).select_from(AutoOutreachJobModel)
        if task_id:
            query = query.where(AutoOutreachJobModel.task_id == task_id)
            count_query = count_query.where(AutoOutreachJobModel.task_id == task_id)
        query = _apply_owner_filter(query, current_user, AutoOutreachJobModel)
        count_query = _apply_owner_filter(count_query, current_user, AutoOutreachJobModel)
        
        # 先合并内存中运行中的任务
        if task_id:
            running_job_ids = [jid for jid, j in _auto_outreach_jobs.items() if j.get("status") == "running" and j.get("task_id") == task_id]
        else:
            running_job_ids = [jid for jid, j in _auto_outreach_jobs.items() if j.get("status") == "running"]
        
        result = await session.execute(
            query.order_by(desc(AutoOutreachJobModel.created_at))
            .offset(offset).limit(limit)
        )
        jobs = result.scalars().all()
        
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0
        
        job_list = []
        for j in jobs:
            # 如果内存中有更新的数据，优先用内存的
            mem_job = _auto_outreach_jobs.get(j.job_id)
            if mem_job:
                job_list.append({
                    "job_id": mem_job["job_id"],
                    "task_id": mem_job["task_id"],
                    "status": mem_job["status"],
                    "total": mem_job["total"],
                    "completed": mem_job["completed"],
                    "success": mem_job["success"],
                    "failed": mem_job["failed"],
                    "skipped": mem_job.get("skipped", 0),
                    "created_at": mem_job["created_at"],
                    "current_index": mem_job.get("current_index", 0),
                    "platform": j.platform,
                    "intent_level": j.intent_level,
                    "data_source": mem_job.get("data_source", j.data_source or "comment"),
                })
            else:
                job_list.append({
                    "job_id": j.job_id,
                    "task_id": j.task_id,
                    "status": j.status,
                    "total": j.total,
                    "completed": j.completed,
                    "success": j.success,
                    "failed": j.failed,
                    "skipped": j.skipped,
                    "created_at": j.created_at,
                    "current_index": j.current_index,
                    "platform": j.platform,
                    "intent_level": j.intent_level,
                    "finished_at": j.finished_at,
                    "data_source": j.data_source or "comment",
                })
        
        return {"total": total, "jobs": job_list, "running_count": len(running_job_ids)}
    finally:
        await session.close()


@router.get("/auto-outreach/stats")
async def get_auto_outreach_stats(current_user: dict = Depends(get_current_user)):
    """获取自动获客全局统计(按用户隔离)"""
    from ..services.outreach_automation import _risk_control_cooldown_until

    session = await _get_db_session()
    try:
        now = int(time.time() * 1000)
        today_start = now - (now % 86400000)  # 今天0点

        # 总计(按用户隔离)
        total_stmt = select(
            func.count(AutoOutreachJobModel.id),
            func.sum(AutoOutreachJobModel.success),
            func.sum(AutoOutreachJobModel.failed),
            func.sum(AutoOutreachJobModel.total),
        )
        total_stmt = _apply_owner_filter(total_stmt, current_user, AutoOutreachJobModel)
        total_result = await session.execute(total_stmt)
        row = total_result.one()
        total_jobs = row[0] or 0
        total_success = row[1] or 0
        total_failed = row[2] or 0
        total_targets = row[3] or 0
        
        # 今日
        today_result = await session.execute(
            select(
                func.count(AutoOutreachJobModel.id),
                func.sum(AutoOutreachJobModel.success),
                func.sum(AutoOutreachJobModel.failed),
            ).where(AutoOutreachJobModel.created_at >= today_start)
        )
        today_row = today_result.one()
        today_jobs = today_row[0] or 0
        today_success = today_row[1] or 0
        today_failed = today_row[2] or 0
        
        # 最近7天每日统计
        daily_stats = []
        for day_offset in range(6, -1, -1):
            day_start = today_start - day_offset * 86400000
            day_end = day_start + 86400000
            day_result = await session.execute(
                select(
                    func.sum(AutoOutreachJobModel.success),
                    func.sum(AutoOutreachJobModel.failed),
                ).where(
                    AutoOutreachJobModel.created_at >= day_start,
                    AutoOutreachJobModel.created_at < day_end,
                )
            )
            day_row = day_result.one()
            daily_stats.append({
                "date": time.strftime("%m-%d", time.localtime(day_start / 1000)),
                "success": day_row[0] or 0,
                "failed": day_row[1] or 0,
            })
        
        # 运行中的任务数
        running_count = len([j for j in _auto_outreach_jobs.values() if j.get("status") == "running"])
        
        # 风控冷却状态
        cooldown_remaining = max(0, int(_risk_control_cooldown_until - time.time()))
        
        return {
            "total_jobs": total_jobs,
            "total_success": total_success,
            "total_failed": total_failed,
            "total_targets": total_targets,
            "success_rate": round(total_success / total_targets * 100, 1) if total_targets > 0 else 0,
            "today_jobs": today_jobs,
            "today_success": today_success,
            "today_failed": today_failed,
            "daily_stats": daily_stats,
            "running_count": running_count,
            "cooldown_remaining": cooldown_remaining,
        }
    finally:
        await session.close()


@router.get("/{task_id}")
async def get_task_detail(task_id: str, comment_offset: int = 0, comment_limit: int = 100, current_user: dict = Depends(get_current_user)):
    """获取任务详情（评论分页）"""
    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)
        
        # 获取日志
        result = await session.execute(
            select(TaskLogModel).where(TaskLogModel.task_id == task_id).order_by(TaskLogModel.add_ts)
        )
        logs = result.scalars().all()
        
        # 根据任务平台和时间范围查询爬取的数据
        crawled_data = []
        comment_data = []
        data_count = 0
        comment_count = 0
        raw_keywords = json.loads(task.keywords) if task.keywords else []
        
        # 将关键词扁平化：把包含空格的字符串拆分成多个关键词
        keywords = []
        for kw in raw_keywords:
            if isinstance(kw, str):
                # 按空格、逗号、中文逗号分割
                parts = re.split(r'[\s,，]+', kw.strip())
                keywords.extend([p for p in parts if p and len(p) > 1])  # 过滤空字符串和单字符
        # 去重
        keywords = list(dict.fromkeys(keywords))

        # 提取核心词用于视频匹配(去除"寻找/的人"等无意义前缀后缀,避免匹配失败)
        # 例:["寻找宋氏家具", "宋式家具", "的人"] → ["宋氏家具", "宋式家具", "宋氏", "宋式", "家具"]
        _LEADING_VERBS_D = ["寻找", "找", "学", "买", "做", "看", "想", "要", "求", "寻"]
        _TAIL_NOISE_D = ["的人", "的客户", "的用户", "的买家", "群体", "人群"]
        core_keywords = set()
        for kw in keywords:
            k = kw
            for tail in _TAIL_NOISE_D:
                if k.endswith(tail) and len(k) > len(tail) + 2:
                    k = k[:-len(tail)]
                    break
            core_keywords.add(k)
            for vb in sorted(_LEADING_VERBS_D, key=len, reverse=True):
                if k.startswith(vb) and len(k) > len(vb) + 1:
                    core_keywords.add(k[len(vb):])
                    break
        # 额外:对"宋氏家具"等含"氏/式"的词,提取主体("宋氏家具"→"家具")
        for kw in list(core_keywords):
            for marker in ["氏", "式"]:
                if marker in kw:
                    suffix_part = kw.split(marker, 1)[1]
                    if len(suffix_part) >= 2:
                        core_keywords.add(suffix_part)
                    break
        # 过滤掉过短或纯停用词
        core_keywords = {k for k in core_keywords if len(k) >= 2 and k not in ("寻找", "的人", "目标", "客户")}
        
        try:
            if task.platform in ("dy", "douyin"):
                # 查询抖音数据 - 根据关键词和时间范围
                # 使用任务创建时间作为起始时间，任务更新时间或当前时间作为结束时间
                start_ts = task.created_ts
                end_ts = task.updated_ts or int(time.time() * 1000)
                
                # 查询视频数据 - 只按任务ID过滤，隔离不同任务数据
                query = select(DouyinAweme).where(
                    DouyinAweme.task_id == task_id
                )
                if core_keywords:
                    # 用核心词匹配(去除前导动词/无意义后缀,避免"寻找宋氏家具"匹配不上"宋氏家具")
                    from sqlalchemy import or_
                    keyword_conditions = []
                    for kw in core_keywords:
                        if kw:
                            keyword_conditions.append(DouyinAweme.source_keyword.ilike(f"%{kw}%"))
                            keyword_conditions.append(DouyinAweme.title.ilike(f"%{kw}%"))
                            keyword_conditions.append(DouyinAweme.desc.ilike(f"%{kw}%"))
                    if keyword_conditions:
                        query = query.where(or_(*keyword_conditions))

                query = query.order_by(desc(DouyinAweme.add_ts)).limit(50)
                result = await session.execute(query)
                aweme_list = result.scalars().all()
                
                for aweme in aweme_list:
                    crawled_data.append({
                        "type": "video",
                        "id": aweme.aweme_id,
                        "title": aweme.title or aweme.desc or "",
                        "content": aweme.desc or "",
                        "author": aweme.nickname or "",
                        "url": aweme.aweme_url or "",
                        "stats": {
                            "likes": aweme.liked_count or "0",
                            "comments": aweme.comment_count or "0",
                            "shares": aweme.share_count or "0",
                        },
                        "add_ts": aweme.add_ts,
                    })
                
                data_count = len(crawled_data)
                
                # 查询评论数据（用于获客）- 只按任务ID过滤，分页查询
                # 先查总数
                from sqlalchemy import func as sa_func
                count_result = await session.execute(
                    select(sa_func.count(DouyinAwemeComment.comment_id)).where(
                        DouyinAwemeComment.task_id == task_id
                    )
                )
                comment_count = count_result.scalar() or 0
                
                # 分页查询评论
                comment_query = select(DouyinAwemeComment).where(
                    DouyinAwemeComment.task_id == task_id
                ).order_by(desc(DouyinAwemeComment.add_ts)).offset(comment_offset).limit(comment_limit)
                comment_result = await session.execute(comment_query)
                comment_list = comment_result.scalars().all()
                
                for comment in comment_list:
                    value = calculate_user_value(comment.content or "", comment.like_count or "0")
                    comment_data.append({
                        "type": "comment",
                        "id": comment.comment_id,
                        "content": comment.content or "",
                        "author": comment.nickname or "",
                        "user_id": comment.user_id or "",
                        "sec_uid": comment.sec_uid or "",
                        "avatar": comment.avatar or "",
                        "ip_location": comment.ip_location or "",
                        "like_count": comment.like_count or "0",
                        "aweme_id": comment.aweme_id or "",
                        "add_ts": comment.add_ts,
                        "value_score": value["score"],
                        "value_level": value["level"],
                        "intent": value["intent"],
                        "value_reason": value["reason"],
                    })
                # comment_count already set from DB count query
                
                # 如果数据库中没有数据，尝试从 jsonl 文件读取
                if data_count == 0:
                    try:
                        import glob
                        # 获取项目根目录（api/routers/tasks.py -> api/ -> 项目根目录）
                        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        data_dir = os.path.join(project_root, "data", "douyin", "jsonl")
                        jsonl_files = glob.glob(os.path.join(data_dir, "*.jsonl"))
                        # 按修改时间排序，取最新的文件
                        jsonl_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                        
                        for jsonl_file in jsonl_files[:5]:  # 检查最近5个文件
                            # 优先读取文件名包含当前 task_id 的文件
                            file_basename = os.path.basename(jsonl_file)
                            is_task_file = task_id in file_basename
                            
                            with open(jsonl_file, "r", encoding="utf-8") as f:
                                for line in f:
                                    if not line.strip():
                                        continue
                                    try:
                                        item = json.loads(line)
                                        # 严格按task_id过滤，隔离不同任务数据
                                        item_task_id = item.get("task_id", "") or ""
                                        if item_task_id != task_id:
                                            continue
                                        
                                        # 检查是否匹配关键词
                                        item_title = item.get("title", "") or ""
                                        item_desc = item.get("desc", "") or ""
                                        item_keyword = item.get("source_keyword", "") or ""
                                        
                                        matched = False
                                        if not keywords:
                                            matched = True
                                        else:
                                            # 宽松匹配：source_keyword 包含任意关键词前缀，或关键词包含 source_keyword
                                            for kw in keywords:
                                                if not kw:
                                                    continue
                                                if kw in item_title or kw in item_desc or kw in item_keyword:
                                                    matched = True
                                                    break
                                                # 前缀匹配：如 "寻找ai" 匹配 "寻找ai聚合平台的人"
                                                if item_keyword and (item_keyword in kw or kw.startswith(item_keyword)):
                                                    matched = True
                                                    break
                                                # 如果 source_keyword 不为空，且是搜索内容文件，直接匹配
                                                if item_keyword and "search_contents" in jsonl_file:
                                                    matched = True
                                                    break
                                        
                                        if matched:
                                            crawled_data.append({
                                                "type": "video",
                                                "id": str(item.get("aweme_id", "")),
                                                "title": item_title or item_desc,
                                                "content": item_desc,
                                                "author": item.get("nickname", "") or "",
                                                "url": item.get("aweme_url", "") or "",
                                                "stats": {
                                                    "likes": str(item.get("liked_count", "0")),
                                                    "comments": str(item.get("comment_count", "0")),
                                                    "shares": str(item.get("share_count", "0")),
                                                },
                                                "add_ts": item.get("create_time", 0) * 1000 if item.get("create_time") else 0,
                                            })
                                    except json.JSONDecodeError:
                                        continue
                            
                            # 如果是当前任务的文件，读取完就退出
                            if is_task_file and len(crawled_data) > 0:
                                break
                            if len(crawled_data) >= 50:
                                break
                        
                        data_count = len(crawled_data)
                    except Exception as file_e:
                        print(f"[tasks] Error reading jsonl files: {file_e}")
                
                # 如果数据库中没有评论数据，尝试从 jsonl 评论文件读取
                if comment_count == 0:
                    try:
                        import glob
                        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        data_dir = os.path.join(project_root, "data", "douyin", "jsonl")
                        jsonl_files = glob.glob(os.path.join(data_dir, "*comments*.jsonl"))
                        jsonl_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                        
                        for jsonl_file in jsonl_files[:5]:
                            # 优先读取文件名包含当前 task_id 的文件
                            file_basename = os.path.basename(jsonl_file)
                            is_task_file = task_id in file_basename
                            
                            with open(jsonl_file, "r", encoding="utf-8") as f:
                                for line in f:
                                    if not line.strip():
                                        continue
                                    try:
                                        item = json.loads(line)
                                        # 严格按task_id过滤，隔离不同任务数据
                                        item_task_id = item.get("task_id", "") or ""
                                        if item_task_id != task_id:
                                            continue
                                        
                                        content = item.get("content", "") or ""
                                        like_count = str(item.get("like_count", "0"))
                                        value = calculate_user_value(content, like_count)
                                        comment_data.append({
                                            "type": "comment",
                                            "id": str(item.get("comment_id", "")),
                                            "content": content,
                                            "author": item.get("nickname", "") or "",
                                            "user_id": str(item.get("user_id", "")),
                                            "sec_uid": item.get("sec_uid", "") or "",
                                            "avatar": item.get("avatar", "") or "",
                                            "ip_location": item.get("ip_location", "") or "",
                                            "like_count": like_count,
                                            "aweme_id": str(item.get("aweme_id", "")),
                                            "add_ts": item.get("create_time", 0) * 1000 if item.get("create_time") else 0,
                                            "value_score": value["score"],
                                            "value_level": value["level"],
                                            "intent": value["intent"],
                                            "value_reason": value["reason"],
                                        })
                                    except json.JSONDecodeError:
                                        continue
                            
                            # 如果是当前任务的文件，读取完就退出
                            if is_task_file and len(comment_data) > 0:
                                break
                            if len(comment_data) >= 100:
                                break
                        
                        comment_count = len(comment_data)
                    except Exception as file_e:
                        print(f"[tasks] Error reading comment jsonl files: {file_e}")
                
            elif task.platform in ("xhs", "xiaohongshu"):
                # 查询小红书数据
                start_ts = task.created_ts
                end_ts = task.updated_ts or int(time.time() * 1000)
                
                # 查询小红书笔记数据 - 严格按task_id隔离
                query = select(XhsNote).where(
                    XhsNote.task_id == task_id
                )
                if keywords:
                    from sqlalchemy import or_
                    keyword_conditions = []
                    for kw in keywords:
                        if kw:
                            keyword_conditions.append(XhsNote.title.ilike(f"%{kw}%"))
                            keyword_conditions.append(XhsNote.desc.ilike(f"%{kw}%"))
                    if keyword_conditions:
                        query = query.where(or_(*keyword_conditions))
                
                query = query.order_by(desc(XhsNote.add_ts)).limit(50)
                result = await session.execute(query)
                note_list = result.scalars().all()
                
                for note in note_list:
                    crawled_data.append({
                        "type": "note",
                        "id": note.note_id,
                        "title": note.title or "",
                        "content": note.desc or "",
                        "author": note.nickname or "",
                        "url": note.note_url or "",
                        "stats": {
                            "likes": note.liked_count or "0",
                            "comments": note.comment_count or "0",
                            "shares": note.share_count or "0",
                        },
                        "add_ts": note.add_ts,
                    })
                
                data_count = len(crawled_data)
                
                # 查询小红书评论数据 - 严格按task_id隔离
                comment_query = select(XhsNoteComment).where(
                    XhsNoteComment.task_id == task_id
                ).order_by(desc(XhsNoteComment.add_ts))
                comment_result = await session.execute(comment_query)
                comment_list = comment_result.scalars().all()
                
                for comment in comment_list:
                    value = calculate_user_value(comment.content or "", str(comment.like_count or "0"))
                    comment_data.append({
                        "type": "comment",
                        "id": comment.comment_id,
                        "content": comment.content or "",
                        "author": comment.nickname or "",
                        "user_id": comment.user_id or "",
                        "avatar": comment.avatar or "",
                        "ip_location": comment.ip_location or "",
                        "like_count": str(comment.like_count or "0"),
                        "note_id": comment.note_id or "",
                        "add_ts": comment.add_ts,
                        "value_score": value["score"],
                        "value_level": value["level"],
                        "intent": value["intent"],
                        "value_reason": value["reason"],
                    })
                comment_count = len(comment_data)
                
                # 如果数据库中没有数据，尝试从 jsonl 文件读取
                if data_count == 0:
                    try:
                        import glob
                        # 获取项目根目录
                        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                        data_dir = os.path.join(project_root, "data", "xhs", "jsonl")
                        jsonl_files = glob.glob(os.path.join(data_dir, "*.jsonl"))
                        jsonl_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                        
                        for jsonl_file in jsonl_files[:3]:
                            # 优先读取文件名包含当前 task_id 的文件
                            file_basename = os.path.basename(jsonl_file)
                            is_task_file = task_id in file_basename
                            
                            with open(jsonl_file, "r", encoding="utf-8") as f:
                                for line in f:
                                    if not line.strip():
                                        continue
                                    try:
                                        item = json.loads(line)
                                        # 严格按task_id过滤，隔离不同任务数据
                                        item_task_id = item.get("task_id", "") or ""
                                        if item_task_id and item_task_id != task_id:
                                            continue
                                        # 如果没有task_id，跳过（不兼容旧数据）
                                        if not item_task_id:
                                            continue
                                        
                                        item_title = item.get("title", "") or ""
                                        item_desc = item.get("desc", "") or ""
                                        
                                        matched = False
                                        if not keywords:
                                            matched = True
                                        else:
                                            for kw in keywords:
                                                if kw and (kw in item_title or kw in item_desc):
                                                    matched = True
                                                    break
                                        
                                        if matched:
                                            crawled_data.append({
                                                "type": "note",
                                                "id": str(item.get("note_id", "")),
                                                "title": item_title,
                                                "content": item_desc,
                                                "author": item.get("nickname", "") or "",
                                                "url": item.get("note_url", "") or "",
                                                "stats": {
                                                    "likes": str(item.get("liked_count", "0")),
                                                    "comments": str(item.get("comment_count", "0")),
                                                    "shares": str(item.get("share_count", "0")),
                                                },
                                                "add_ts": item.get("time", 0) * 1000 if item.get("time") else 0,
                                            })
                                    except json.JSONDecodeError:
                                        continue
                            
                            if is_task_file and len(crawled_data) > 0:
                                break
                            if len(crawled_data) >= 50:
                                break
                        
                        data_count = len(crawled_data)
                    except Exception as file_e:
                        print(f"[tasks] Error reading xhs jsonl files: {file_e}")
        except Exception as e:
            print(f"[tasks] Error fetching crawled data: {e}")
            # 数据查询失败不影响任务详情返回
        
        return {
            "task": await _task_to_dict(task),
            "logs": [{"time": log.add_ts, "level": log.level, "message": log.message} for log in logs],
            "log_count": len(logs),
            "data": crawled_data,
            "data_count": data_count,
            "comments": comment_data,
            "comment_count": comment_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


# 评论表与平台映射(用于扫描全部评论生成线索)
_COMMENT_TABLE_MAP = {
    "dy": ("douyin", DouyinAwemeComment, "comment_id"),
    "douyin": ("douyin", DouyinAwemeComment, "comment_id"),
    "xhs": ("xhs", XhsNoteComment, "comment_id"),
    "ks": ("kuaishou", KuaishouVideoComment, "comment_id"),
    "wb": ("weibo", WeiboNoteComment, "comment_id"),
    "bili": ("bilibili", BilibiliVideoComment, "comment_id"),
}

# 源视频/作品表映射: platform -> (SourceModel, source_id_field, comment_ref_field, source_url_template)
# source_id_field: 源视频表的主键字段名; comment_ref_field: 评论表里关联源视频的字段名
# 用于扫描评论时关联源视频信息(标题/作者/链接/封面),方便后期回复评论时知道上下文
_SOURCE_VIDEO_TABLE_MAP = {
    "douyin": (DouyinAweme, "aweme_id", "aweme_id", "https://www.douyin.com/video/{sid}"),
    "xhs": (XhsNote, "note_id", "note_id", "https://www.xiaohongshu.com/explore/{sid}"),
    # 其他平台按需补充,缺失时源视频信息留空
}


@router.post("/{task_id}/scan-leads")
async def scan_task_leads(
    task_id: str,
    force_full: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """扫描该任务的评论,使用任务上下文评分,写入 CustomerLead 表

    - 默认增量扫描:只处理上次扫描后的新评论(基于 last_modify_ts 水位),大幅降低资源消耗
    - force_full=true 时全量重扫:清空旧线索 + 重扫全部评论
    - 遍历评论,计算意向评分
    - 评分规则结合任务关键词/名称/需求(命中任务相关词加分,无关降分)
    - 写入前先清理该任务旧的 CustomerLead 记录,避免重复
    - 返回扫描结果统计
    """
    session = await _get_db_session()
    try:
        # 校验任务存在且属于当前用户
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        platform = (task.platform or "").lower()
        if platform not in _COMMENT_TABLE_MAP:
            raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

        platform_str, CommentModel, comment_id_field = _COMMENT_TABLE_MAP[platform]

        # 提取任务关键词(扁平化)
        raw_keywords = json.loads(task.keywords) if task.keywords else []
        task_keywords = []
        for kw in raw_keywords:
            if isinstance(kw, str):
                parts = re.split(r'[\s,，]+', kw.strip())
                task_keywords.extend([p for p in parts if p and len(p) > 1])
        task_keywords = list(dict.fromkeys(task_keywords))

        task_name = task.name or ""
        task_desc = getattr(task, "description", "") or ""

        # 增量扫描:查询该任务已有线索的最大 add_ts(上次扫描水位)
        # 只处理 last_modify_ts > 水位 的新评论,避免全量重扫
        owner_uid = str(current_user["id"])
        last_scan_ts_result = await session.execute(
            select(func.max(CustomerLead.add_ts))
            .where(CustomerLead.task_id == task_id)
            .where(CustomerLead.owner_user_id == owner_uid)
        )
        last_scan_ts = last_scan_ts_result.scalar() or 0
        incremental_mode = (last_scan_ts > 0) and (not force_full)

        # 加载源视频映射(全量加载,源视频数量通常很少)
        source_map: Dict[str, Dict] = {}
        if platform_str in _SOURCE_VIDEO_TABLE_MAP:
            SourceModel, source_id_field, _comment_ref_field, url_template = _SOURCE_VIDEO_TABLE_MAP[platform_str]
            try:
                src_result = await session.execute(
                    select(SourceModel).where(SourceModel.task_id == task_id)
                )
                for src in src_result.scalars().all():
                    sid = getattr(src, source_id_field, "") or ""
                    if not sid:
                        continue
                    source_map[sid] = {
                        "source_aweme_id": sid,
                        "source_video_title": getattr(src, "title", "") or getattr(src, "desc", "") or "",
                        "source_video_desc": getattr(src, "desc", "") or "",
                        "source_video_url": getattr(src, "aweme_url", "") or getattr(src, "note_url", "") or url_template.format(sid=sid),
                        "source_cover_url": getattr(src, "cover_url", "") or "",
                        "source_author_nickname": getattr(src, "nickname", "") or "",
                    }
            except Exception as e:
                utils.logger.warning(f"[scan_task_leads] Failed to load source videos: {e}")

        if incremental_mode:
            # 增量模式:只查询 last_modify_ts > 水位 的新评论
            comment_result = await session.execute(
                select(CommentModel)
                .where(CommentModel.task_id == task_id)
                .where(CommentModel.last_modify_ts > last_scan_ts)
            )
            all_comments = comment_result.scalars().all()
            # 增量模式不清空旧线索,只追加/更新
        else:
            # 全量模式:查询全部评论,然后清空旧线索
            comment_result = await session.execute(
                select(CommentModel).where(CommentModel.task_id == task_id)
            )
            all_comments = comment_result.scalars().all()
            # 清理该任务旧的 CustomerLead 记录(只清当前用户的)
            await session.execute(
                delete(CustomerLead).where(
                    CustomerLead.task_id == task_id,
                    CustomerLead.owner_user_id == owner_uid,
                )
            )
            await session.commit()  # 先提交删除,释放锁

        if not all_comments:
            return {
                "success": True,
                "task_id": task_id,
                "scanned": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "saved": 0,
                "incremental": incremental_mode,
                "message": "该任务暂无评论数据" if not incremental_mode else "无新增评论,无需扫描",
            }

        # 增量模式:构建已有线索的 data_id 集合,用于 upsert 去重
        existing_data_ids: set = set()
        if incremental_mode:
            existing_result = await session.execute(
                select(CustomerLead.data_id)
                .where(CustomerLead.task_id == task_id)
                .where(CustomerLead.owner_user_id == owner_uid)
            )
            existing_data_ids = {row[0] for row in existing_result.all() if row[0]}

        # 评分常量
        now_ms = int(time.time() * 1000)
        intent_map = {
            "购买意向": "purchase", "合作意向": "cooperation",
            "咨询意向": "inquiry", "潜在需求": "potential", "一般关注": "discussion", "无": "discussion",
        }
        # 评论表关联源视频的字段名
        comment_ref_field = ""
        if platform_str in _SOURCE_VIDEO_TABLE_MAP:
            _, _, comment_ref_field, _ = _SOURCE_VIDEO_TABLE_MAP[platform_str]

        # 评分 + 批量插入优化:
        # 1. 构建 dict 而非 ORM 对象(省去 SQLAlchemy 状态管理开销)
        # 2. 用 execute(insert(...), list_of_dicts) 批量插入(SQLAlchemy 2.0 async 推荐方式)
        # 3. 每 1000 条 commit 一次(避免单次事务过大导致锁等待和内存峰值)
        BATCH_SIZE = 1000
        high_count = medium_count = low_count = 0
        total_scanned = len(all_comments)
        total_saved = 0
        skipped_existing = 0  # 增量模式下跳过的已存在评论数
        batch_dicts: List[Dict] = []

        async def flush_batch():
            """批量插入当前批次并清空 buffer"""
            nonlocal total_saved
            if not batch_dicts:
                return
            # SQLAlchemy 2.0 async 批量插入:execute(insert(Table), [dict, dict, ...])
            await session.execute(insert(CustomerLead), batch_dicts)
            await session.commit()
            total_saved += len(batch_dicts)
            batch_dicts.clear()

        # 低质量内容过滤:空/纯表情/极短内容跳过(提高线索数据质量)
        import re as _re
        def _is_low_quality(text: str) -> bool:
            if not text or not text.strip():
                return True
            # 去掉表情符号[xx]和emoji后,有效内容少于2字视为低质量
            cleaned = _re.sub(r'\[.*?\]', '', text).strip()
            # 去掉常见emoji
            cleaned = _re.sub(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF]', '', cleaned).strip()
            if len(cleaned) < 2:
                return True
            # 纯标点/纯数字
            if _re.fullmatch(r'[\d\s\W]+', cleaned):
                return True
            return False

        # 同任务内 content 去重集合(避免不同用户发相同表情/简短内容重复入库)
        seen_contents: set = set()
        skipped_low_quality = 0

        for comment in all_comments:
            content = comment.content or ""
            comment_id_val = getattr(comment, comment_id_field, "") or ""
            comment_id_str = str(comment_id_val)
            # 增量模式:已有线索的评论跳过(避免重复插入)
            if incremental_mode and comment_id_str in existing_data_ids:
                skipped_existing += 1
                continue
            # 低质量内容过滤(空/纯表情/极短)
            if _is_low_quality(content):
                skipped_low_quality += 1
                continue
            # 同任务内 content 去重(避免不同用户发相同简短内容重复)
            content_key = content.strip()
            if content_key in seen_contents:
                continue
            seen_contents.add(content_key)
            value = calculate_user_value_for_task(
                content=content,
                like_count=str(comment.like_count or "0"),
                task_name=task_name,
                task_keywords=task_keywords,
                task_desc=task_desc,
            )
            level_cn = value.get("level", "低")
            if level_cn == "高":
                high_count += 1
            elif level_cn == "中":
                medium_count += 1
            else:
                low_count += 1
            # 源视频信息
            src_info = source_map.get(getattr(comment, comment_ref_field, "") or "", {}) if comment_ref_field else {}
            batch_dicts.append({
                "task_id": task_id,
                "platform": platform_str,
                "data_type": "comment",
                "data_id": comment_id_str,
                "user_id": comment.user_id or "",
                "sec_uid": getattr(comment, "sec_uid", "") or "",
                "nickname": comment.nickname or "",
                "avatar": comment.avatar or "",
                "ip_location": getattr(comment, "ip_location", "") or "",
                "content": content,
                "title": src_info.get("source_video_title", ""),
                "url": src_info.get("source_video_url", ""),
                "matched_keywords": ",".join(value.get("matched_keywords", [])),
                "intent_type": intent_map.get(value.get("intent", ""), "discussion"),
                "lead_score": value.get("score", 0),
                "status": "new",
                "notes": value.get("reason", ""),
                "add_ts": now_ms,
                "last_modify_ts": now_ms,
                "create_time": getattr(comment, "create_time", None),
                "owner_user_id": owner_uid,
                "source_aweme_id": src_info.get("source_aweme_id", ""),
                "source_video_title": src_info.get("source_video_title", ""),
                "source_video_desc": src_info.get("source_video_desc", ""),
                "source_video_url": src_info.get("source_video_url", ""),
                "source_cover_url": src_info.get("source_cover_url", ""),
                "source_author_nickname": src_info.get("source_author_nickname", ""),
            })
            if len(batch_dicts) >= BATCH_SIZE:
                await flush_batch()

        # 提交最后一批
        await flush_batch()

        # 推送新线索事件到对应用户的 WebSocket(前端收到后自动刷新列表)
        if total_saved > 0:
            try:
                from .websocket import notify_new_leads
                await notify_new_leads(
                    owner_uid, task_id, platform_str,
                    total_saved, high_count, medium_count, low_count,
                )
            except Exception as _e:
                print(f"[notify_new_leads] 推送失败(不影响主流程): {_e}")

        # 释放评论对象内存(显式清引用,帮助 GC)
        all_comments.clear()
        existing_data_ids.clear()  # 释放去重集合内存

        mode_label = "增量扫描" if incremental_mode else "全量扫描"
        if incremental_mode and skipped_existing > 0:
            msg = f"[{mode_label}] 新增评论 {total_scanned} 条(跳过已存在 {skipped_existing} 条,低质量 {skipped_low_quality} 条),生成 {total_saved} 条新线索(高{high_count}/中{medium_count}/低{low_count})"
        else:
            msg = f"[{mode_label}] 已扫描 {total_scanned} 条评论(过滤低质量 {skipped_low_quality} 条),生成 {total_saved} 条线索(高{high_count}/中{medium_count}/低{low_count})"

        return {
            "success": True,
            "task_id": task_id,
            "scanned": total_scanned,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
            "saved": total_saved,
            "incremental": incremental_mode,
            "skipped_existing": skipped_existing,
            "message": msg,
        }
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")
    finally:
        await session.close()


@router.get("/{task_id}/leads-summary")
async def get_task_leads_summary(task_id: str, current_user: dict = Depends(get_current_user)):
    """获取任务的线索统计(从 CustomerLead 表查,不受评论分页限制)"""
    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        # 总数
        total_result = await session.execute(
            select(func.count()).select_from(CustomerLead)
            .where(CustomerLead.task_id == task_id)
            .where(CustomerLead.owner_user_id == str(current_user["id"]))
        )
        total = total_result.scalar() or 0

        # 按意向等级分布(CustomerLead 没有 level 字段,用 lead_score 重新计算)
        # 高: score>=50, 中: 25<=score<50, 低: score<25
        high_result = await session.execute(
            select(func.count()).select_from(CustomerLead)
            .where(CustomerLead.task_id == task_id)
            .where(CustomerLead.owner_user_id == str(current_user["id"]))
            .where(CustomerLead.lead_score >= 50)
        )
        high_count = high_result.scalar() or 0

        medium_result = await session.execute(
            select(func.count()).select_from(CustomerLead)
            .where(CustomerLead.task_id == task_id)
            .where(CustomerLead.owner_user_id == str(current_user["id"]))
            .where(CustomerLead.lead_score >= 25)
            .where(CustomerLead.lead_score < 50)
        )
        medium_count = medium_result.scalar() or 0

        low_result = await session.execute(
            select(func.count()).select_from(CustomerLead)
            .where(CustomerLead.task_id == task_id)
            .where(CustomerLead.owner_user_id == str(current_user["id"]))
            .where(CustomerLead.lead_score < 25)
        )
        low_count = low_result.scalar() or 0

        return {
            "task_id": task_id,
            "total": total,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
            "scanned": total > 0,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.get("/{task_id}/logs")
async def get_task_logs(task_id: str, limit: int = 100, current_user: dict = Depends(get_current_user)):
    """获取任务运行日志"""
    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        query = select(TaskLogModel).where(TaskLogModel.task_id == task_id).order_by(TaskLogModel.add_ts)
        result = await session.execute(query)
        logs = result.scalars().all()

        if limit > 0 and len(logs) > limit:
            logs = logs[-limit:]

        return {
            "task_id": task_id,
            "logs": [{"time": log.add_ts, "level": log.level, "message": log.message} for log in logs],
            "total": len(logs),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.post("/{task_id}/logs")
async def add_task_log(task_id: str, log_data: dict, current_user: dict = Depends(get_current_user)):
    """添加任务日志（内部使用）"""
    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        log = TaskLogModel(
            task_id=task_id,
            level=log_data.get("level", "info"),
            message=log_data.get("message", ""),
            add_ts=log_data.get("time", int(time.time() * 1000)),
        )
        session.add(log)
        await session.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.delete("/{task_id}/logs")
async def clear_task_logs(task_id: str, current_user: dict = Depends(get_current_user)):
    """清空任务日志"""
    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        from sqlalchemy import delete
        await session.execute(delete(TaskLogModel).where(TaskLogModel.task_id == task_id))
        await session.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


# ==================== 自动化获客功能 ====================

# 需求类型定义
NEED_TYPE_MAP = {
    "link_request": {
        "name": "求链接/网址",
        "keywords": ["网址", "链接", "发个", "发一下", "求", "有吗", "在哪", "怎么进", "入口", "地址", "网站"],
        "strategy": "直接发送链接+简短介绍",
    },
    "product_inquiry": {
        "name": "产品咨询",
        "keywords": ["哪里买", "多少钱", "怎么买", "下单", "入手", "必入", "闭眼入", "想要", "求推荐"],
        "strategy": "直接推荐产品+优惠码",
    },
    "price_sensitive": {
        "name": "价格敏感",
        "keywords": ["多少钱", "贵", "便宜", "免费", "优惠", "折扣", "性价比", "值得"],
        "strategy": "强调性价比+限时优惠",
    },
    "tutorial_request": {
        "name": "教程需求",
        "keywords": ["教程", "怎么学", "入门", "新手", "带带我", "教教我", "怎么做", "方法", "攻略"],
        "strategy": "提供免费教程+进阶付费",
    },
    "cooperation": {
        "name": "合作意向",
        "keywords": ["合作", "代理", "加盟", "商务", "联系", "想做", "资源"],
        "strategy": "介绍合作模式+分佣方案",
    },
    "comparison": {
        "name": "产品对比",
        "keywords": ["对比", "哪个好", "vs", "区别", "怎么样", "好用吗"],
        "strategy": "提供对比分析+推荐自家",
    },
    "frustration": {
        "name": "使用痛点",
        "keywords": ["麻烦", "不行", "坑", "难用", "注册", "验证", "国外", "手机号"],
        "strategy": "强调便捷性+专属服务",
    },
    "general": {
        "name": "一般关注",
        "keywords": [],
        "strategy": "品牌曝光+引导关注",
    },
}

# 文案模板库
def get_message_templates():
    """获取文案模板 - 支持从文件动态加载"""
    templates_file = Path(__file__).parent.parent.parent / "config" / "message_templates.json"
    if templates_file.exists():
        try:
            with open(templates_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_MESSAGE_TEMPLATES


DEFAULT_MESSAGE_TEMPLATES = {
    "link_request": {
        "friendly": [
            "{nickname} 来啦！链接给你 👇 {product_desc} {link} {free_quota_text}有问题随时问我～",
            "嗨 {nickname}！你要的链接在这 👉 {link} {product_desc} {free_quota_text}有啥不懂的随时找我哈",
            "{nickname} 你好！看到你想要链接，发你啦 📎 {link} {product_desc} {free_quota_text}需要帮助随时说",
            "来啦 {nickname}！这是你要的 👇 {link} {product_desc} {free_quota_text}不懂的可以问我哦",
        ],
        "direct": [
            "{product_desc} {link} {free_quota_text}",
            "{link} {product_desc} {free_quota_text}",
            "链接: {link} {product_desc} {free_quota_text}",
        ],
    },
    "product_inquiry": {
        "friendly": [
            "嗨 {nickname}！看到你在找{product}，我们刚好有解决方案 😊 {product_desc} {link} 现在注册还有专属优惠，要不要了解一下？",
            "{nickname} 你好！你提到的{product}我们正好做这个 🎯 {product_desc} {link} {free_quota_text}感兴趣可以试试看",
            "哈喽 {nickname}！找{product}？看这里 👀 {product_desc} {link} {free_quota_text}有问题随时问我哈",
            "嗨 {nickname}！关于{product}，我推荐你看看这个 {product_desc} {link} {free_quota_text}可以先体验一下～",
        ],
        "professional": [
            "您好 {nickname}，注意到您对{product}感兴趣。我们是{company}，专注于{field}。{product_desc} {link} 如有兴趣，可以安排一次免费演示。联系方式：{contact}",
            "{nickname} 您好，了解到您在关注{product}领域。{company}提供专业解决方案：{product_desc} {link} 欢迎咨询 {contact}",
        ],
    },
    "price_sensitive": {
        "friendly": [
            "嗨 {nickname}！理解你想找性价比高的方案 💰 我们目前有{product}，{price_info} 比同类产品便宜{discount}，功能还更全面！现在注册送{free_quota}次免费调用，够你体验一个月了～ {link}",
            "{nickname} 你好！想省钱的话看这里 💡 {product}现在{price_info}，比同类便宜{discount}！{free_quota_text} {link} 先免费用着不亏",
            "哈喽 {nickname}！找便宜好用的？看这个 👉 {product} {price_info}，比同类省{discount}！{free_quota_text} {link}",
        ],
    },
    "tutorial_request": {
        "friendly": [
            "嗨 {nickname}！新手入门确实不容易 😅 我们整理了一份《{tutorial_name}》，免费送你！{tutorial_desc} 需要的话回复\"教程\"就行，我发你～ 或者加微信：{wechat} 直接发你",
            "{nickname} 你好！入门教程我们有 📚 《{tutorial_name}》免费分享！{tutorial_desc} 加我微信 {wechat} 我直接发你",
            "哈喽 {nickname}！别担心，新手也能快速上手 💪 我们有《{tutorial_name}》{tutorial_desc} 需要的话加微信 {wechat} 我发你～",
        ],
    },
    "cooperation": {
        "professional": [
            "您好 {nickname}，看到您提到有{resource_type}，我们的{product}正好可以互补。{cooperation_desc} 合作模式：代理分佣{commission}% | 专属支持1对1客服 | 定制方案根据您的资源定制 有兴趣详细聊聊吗？微信：{wechat}",
            "{nickname} 您好！我们有{product}，和您的{resource_type}可以形成互补。{cooperation_desc} 分佣{commission}%+1对1支持，有兴趣聊聊吗？微信：{wechat}",
        ],
    },
    "frustration": {
        "friendly": [
            "嗨 {nickname}！理解你的困扰 😔 {problem}确实是个麻烦事。我们有一款{product}，正好解决了这个问题：{solution} 无需国外手机号 | 微信一键登录 | 中文界面，操作简单 现在注册送{free_quota}次免费调用！ {link}",
            "{nickname} 你好！别愁了 😊 {problem}我们正好能解决！{product}：{solution} 微信直接登录，中文界面超简单 {free_quota_text} {link}",
            "哈喽 {nickname}！这个烦恼我懂 💡 试试{product}吧，{solution} 不用翻墙不用国外手机号，中文界面 {free_quota_text} {link}",
        ],
    },
    "general": {
        "friendly": [
            "嗨 {nickname}！感谢关注 😊 我们是{company}，专注于{field}。{product_desc} {link} 感兴趣的话可以点个关注，后续会有更多干货分享！有问题随时私信我～",
            "{nickname} 你好！我们是{company}，{product_desc} {link} {free_quota_text}有问题随时找我哈",
            "哈喽 {nickname}！看到你关注这个领域，推荐你看看 👉 {product_desc} {link} {free_quota_text}欢迎交流～",
            "嗨 {nickname}！刚好你感兴趣的领域我们也在做 🙌 {product_desc} {link} {free_quota_text}随时可以问我",
        ],
    },
}


def classify_need_type(comment: str) -> str:
    """根据评论内容分类需求类型"""
    comment_lower = comment.lower()
    scores = {}
    
    for need_type, config in NEED_TYPE_MAP.items():
        score = 0
        for kw in config["keywords"]:
            if kw in comment_lower:
                score += 1
        scores[need_type] = score
    
    # 返回得分最高的类型
    best_type = max(scores, key=scores.get)
    if scores[best_type] == 0:
        return "general"
    return best_type


def extract_pain_points(comment: str) -> List[str]:
    """提取用户痛点"""
    pain_indicators = [
        ("无法使用", ["用不了", "不能用", "不行", "失败", "错误", "报错"]),
        ("注册困难", ["注册", "手机号", "验证", "验证码", "收不到"]),
        ("价格太高", ["贵", "太贵", "买不起", "舍不得", "没钱"]),
        ("操作复杂", ["麻烦", "复杂", "难用", "不会用", "看不懂"]),
        ("找不到", ["找不到", "搜不到", "没有", "缺货", "下架"]),
        ("网络问题", ["翻墙", "国外", "海外", "节点", "代理"]),
        ("功能不足", ["功能少", "不够用", "缺少", "想要", "需要"]),
    ]
    
    comment_lower = comment.lower()
    pains = []
    
    for pain_name, keywords in pain_indicators:
        for kw in keywords:
            if kw in comment_lower:
                pains.append(pain_name)
                break
    
    return pains


def analyze_budget_sensitivity(comment: str) -> str:
    """分析预算敏感度"""
    comment_lower = comment.lower()
    
    high_price = ["贵", "太贵", "买不起", "舍不得", "没钱", "免费", "白嫖"]
    medium_price = ["多少钱", "价格", "优惠", "折扣", "性价比", "值得"]
    
    for kw in high_price:
        if kw in comment_lower:
            return "high"
    
    for kw in medium_price:
        if kw in comment_lower:
            return "medium"
    
    return "low"


def analyze_urgency(comment: str) -> str:
    """分析紧急程度"""
    comment_lower = comment.lower()
    
    urgent = ["急", "赶紧", "马上", "立刻", "现在", "今天", " ASAP", "求"]
    for kw in urgent:
        if kw in comment_lower:
            return "urgent"
    
    normal = ["准备", "打算", "计划", "想", "要"]
    for kw in normal:
        if kw in comment_lower:
            return "normal"
    
    return "low"


def generate_pitch(need_type: str, pain_points: List[str], comment: str) -> str:
    """生成推荐话术"""
    if need_type == "product_inquiry":
        return "根据您的需求，推荐我们的AI聚合平台，一站式解决多模型调用需求"
    elif need_type == "price_sensitive":
        return "我们提供免费额度+低价套餐，性价比远超同类产品"
    elif need_type == "tutorial_request":
        return "我们有完整的入门教程和社群支持，新手也能快速上手"
    elif need_type == "cooperation":
        return "欢迎合作！我们提供代理分佣+专属支持"
    elif need_type == "frustration":
        if "手机号" in comment or "国外" in comment:
            return "无需国外手机号，微信扫码即可使用"
        return "我们的解决方案更简单、更稳定"
    elif need_type == "comparison":
        return "我们整合了多个主流模型，一个平台搞定所有需求"
    else:
        return "感谢关注！我们有专业的AI解决方案，欢迎了解"


def _obfuscate_link_in_text(text: str, link: str) -> str:
    """将文本中的URL混淆处理，绕过抖音/小红书私信链接过滤
    
    策略：随机选择一种混淆方式，核心思路是将域名拆散到无法被正则匹配
    1. 用中文描述拆分URL，如"搜 hropenai 加 cn"
    2. 在域名各部分之间插入中文/emoji
    3. 用谐音/拼音替代
    4. 用换行拆分
    """
    import random
    
    if not link or link not in text:
        return text
    
    # 解析URL组成部分
    url = link.strip()
    
    # 去掉协议前缀
    clean_url = url
    for proto in ["https://", "http://"]:
        if clean_url.startswith(proto):
            clean_url = clean_url[len(proto):]
    
    # 分离各部分
    parts = clean_url.split(".")
    
    # 构建多种混淆变体
    variants = []
    
    if len(parts) >= 2:
        # 解析域名组成部分
        # ai.hropenai.cn → prefix=ai, domain=hropenai, tld=cn
        # www.zhiranhome.com → prefix=www, domain=zhiranhome, tld=com
        # zhiranhome.com → prefix="", domain=zhiranhome, tld=com
        if len(parts) == 2:
            prefix, domain, tld = "", parts[0], parts[1]
        elif len(parts) == 3:
            prefix, domain, tld = parts[0], parts[1], parts[2]
        else:
            prefix, domain, tld = ".".join(parts[:-2]), parts[-2], parts[-1]
        
        # 变体1: 搜 + 域名 + 加 + 后缀 — "搜 hropenai 加 cn"
        variants.append(f"搜 {domain} 加 {tld}")
        
        # 变体2: 域名 + 中文点 + 后缀 — "hropenai 点 cn"
        variants.append(f"{domain} 点 {tld}")
        
        # 变体3: 搜索 + 域名 + 点后缀 — "搜索 hropenai 点cn"
        variants.append(f"搜索 {domain} 点{tld}")
        
        # 变体4: 域名 + emoji + 后缀 — "hropenai✨cn"
        sep_emoji = random.choice(["✨", "🌟", "💫", "⭐", "🔗", "👉"])
        variants.append(f"{domain}{sep_emoji}{tld}")
        
        # 变体5: 带前缀的完整混淆 — "ai点hropenai点cn"
        if prefix:
            variants.append(f"{prefix}点{domain}点{tld}")
            variants.append(f"搜 {prefix}点{domain}点{tld}")
        else:
            variants.append(f"搜 {domain}点{tld}")
        
        # 变体6: 域名 + (点) + 后缀 — "hropenai(点)cn"
        variants.append(f"{domain}(点){tld}")
        
        # 变体7: 域名 + 空格 + 点 + 空格 + 后缀 — "hropenai . cn"
        variants.append(f"{domain} . {tld}")
        
        # 变体8: 换行拆分 — "hropenai\n点cn"
        variants.append(f"{domain}\n点{tld}")
        
        # 变体9: 中文谐音提示 — "hropenai 点 c n"
        tld_spaced = " ".join(tld)
        variants.append(f"{domain} 点 {tld_spaced}")
        
        # 变体10: 搜索引擎提示 — "百度搜 hropenai"
        search_engines = ["百度搜", "搜狗搜", "浏览器搜", "搜索"]
        variants.append(f"{random.choice(search_engines)} {domain}")
    
    # 随机选一个变体
    obfuscated = random.choice(variants)
    
    # 替换文本中的原始链接
    result = text.replace(link, obfuscated)
    
    return result


def generate_ad_content(need_type: str, user_info: dict, tone: str = "friendly", promo_config: dict = None) -> dict:
    """生成个性化广告内容 - 支持自定义推广配置，每次随机选择模板并微调"""
    import random
    
    nickname = user_info.get("author", "朋友")
    comment = user_info.get("content", "")
    pc = promo_config or {}
    
    # 从推广配置读取，没有则使用默认值
    product = pc.get("product_name", "AI聚合平台") or "AI聚合平台"
    product_desc = pc.get("product_desc", "一站式AI工具平台，集成ChatGPT、Claude、Gemini等主流大模型") or "一站式AI工具平台，集成ChatGPT、Claude、Gemini等主流大模型"
    promo_link = pc.get("promo_link", "") or ""
    contact_wechat = pc.get("contact_wechat", "") or ""
    price_info = pc.get("price_info", "") or ""
    discount_info = pc.get("discount_info", "") or ""
    free_quota = pc.get("free_quota", "") or ""
    solution_desc = pc.get("solution_desc", "") or ""
    tutorial_name = pc.get("tutorial_name", "") or ""
    tutorial_desc = pc.get("tutorial_desc", "") or ""
    cooperation_desc = pc.get("cooperation_desc", "") or ""
    commission_rate = pc.get("commission_rate", "") or ""
    
    # 构建联系方式文本
    contact = f"微信: {contact_wechat}" if contact_wechat else ""
    wechat = contact_wechat or ""
    
    # 获取模板（支持动态加载）
    message_templates = get_message_templates()
    templates = message_templates.get(need_type, message_templates["general"])
    tone_templates = templates.get(tone, templates.get("friendly", []))
    
    # 从模板列表中随机选择一个
    if isinstance(tone_templates, list) and tone_templates:
        template = random.choice(tone_templates)
    elif isinstance(tone_templates, str):
        template = tone_templates
    else:
        template = "{nickname} 你好！{product_desc} {link} {free_quota_text}"
    
    # 构建免费额度文本
    if free_quota:
        if "注册送" in free_quota or "免费" in free_quota or "额度" in free_quota:
            free_quota_text = f"{free_quota}！"
        else:
            free_quota_text = f"注册送{free_quota}！"
    else:
        free_quota_text = ""

    # 填充变量
    content = template.format(
        nickname=nickname,
        product=product,
        product_desc=product_desc,
        company=product,
        field=product_desc[:20],
        link=promo_link,
        contact=contact,
        wechat=wechat,
        price_info=price_info,
        discount=discount_info,
        free_quota=free_quota,
        free_quota_text=free_quota_text,
        tutorial_name=tutorial_name,
        tutorial_desc=tutorial_desc,
        resource_type="客户资源",
        cooperation_desc=cooperation_desc,
        commission=commission_rate,
        problem="国外AI工具注册困难",
        solution=solution_desc,
    )
    # 整合成一条记录：去掉换行符
    content = content.replace('\n', ' ').strip()
    # 去除连续空格
    while '  ' in content:
        content = content.replace('  ', ' ')
    
    # ===== 额外随机化处理，确保每条文案不完全相同 =====
    # 1. 随机替换问候语
    greetings = ["嗨", "哈喽", "你好", "嘿", "Hi"]
    for g in greetings:
        if content.startswith(g + " ") or content.startswith(g + "！"):
            new_g = random.choice(greetings)
            if new_g != g:
                content = new_g + content[len(g):]
            break
    
    # 2. 随机添加语气词
    tone_particles = ["", "呀", "哦", "哈", "呢", "哇"]
    if random.random() > 0.5:
        # 在感叹号前随机加语气词
        for particle in tone_particles[1:]:
            if particle in content:
                new_particle = random.choice(tone_particles)
                content = content.replace(particle, new_particle, 1)
                break
    
    # 3. 随机微调标点
    if random.random() > 0.6:
        content = content.replace("！", random.choice(["！", "～", "😊"]))
    if random.random() > 0.7:
        content = content.replace("？", random.choice(["？", "🤔"]))
    
    # 4. 随机添加/移除 emoji
    emojis = ["😊", "👍", "🎯", "💡", "✨", "🙌", "💪", "🔥"]
    if random.random() > 0.5:
        # 移除现有 emoji 中的一个
        for e in emojis:
            if e in content:
                if random.random() > 0.5:
                    content = content.replace(e, "", 1)
                break
    if random.random() > 0.6:
        # 添加一个随机 emoji
        pos = random.randint(0, max(len(content) - 1, 1))
        content = content[:pos] + random.choice(emojis) + content[pos:]
    
    # 5. 随机调整链接位置（有链接时）
    if promo_link and promo_link in content:
        link_part = promo_link
        if random.random() > 0.5:
            # 把链接移到末尾
            content_without_link = content.replace(link_part, "").strip()
            content = content_without_link + " " + link_part
    
    # 清理：去除连续空格和首尾空格
    while '  ' in content:
        content = content.replace('  ', ' ')
    content = content.strip()
    
    # ===== 链接混淆处理，绕过抖音私信URL过滤 =====
    if promo_link:
        content = _obfuscate_link_in_text(content, promo_link)

    # 构建行动号召
    if promo_link:
        call_to_action = "复制上方网址到浏览器打开即可体验 👆"
    elif contact_wechat:
        call_to_action = f"添加微信咨询: {contact_wechat}"
    else:
        call_to_action = "欢迎私信了解更多详情"
    
    return {
        "direct_message": content,
        "comment_reply": f"@{nickname} {content[:100]}...",
        "profile_message": content,
        "tone": tone,
        "products": [product],
        "call_to_action": call_to_action,
    }


class AnalyzeNeedRequest(BaseModel):
    user_ids: Optional[List[str]] = None
    max_users: int = 999


class GenerateContentRequest(BaseModel):
    user_ids: List[str]
    content_type: str = "direct_message"  # direct_message | comment_reply
    tone: str = "friendly"  # friendly | professional | casual


class OutreachExecuteRequest(BaseModel):
    user_id: str
    sec_uid: str
    platform: str = "douyin"
    method: str = "direct_message"  # direct_message | comment_reply
    content: str
    nickname: str = ""
    note_id: str = ""       # 视频/笔记ID，评论回复时必填
    comment_id: str = ""    # 评论ID，评论回复时选填
    require_confirm: bool = True


@router.post("/{task_id}/analyze-needs")
async def analyze_user_needs(task_id: str, request: AnalyzeNeedRequest, current_user: dict = Depends(get_current_user)):
    """分析用户需求 - 基于评论内容"""
    session = await _get_db_session()
    try:
        # 获取任务详情中的评论数据
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)
        
        # 从数据库读取评论数据（与getTaskDetail保持一致）
        comment_data = []
        
        # 查询评论数据 - 根据任务ID，不限制数量
        comment_query = select(DouyinAwemeComment).where(
            DouyinAwemeComment.task_id == task_id
        ).order_by(desc(DouyinAwemeComment.add_ts))
        comment_result = await session.execute(comment_query)
        comment_list = comment_result.scalars().all()
        print(f"[analyze-needs] Found {len(comment_list)} comments from DB for task {task_id}")
        
        for comment in comment_list:
            value = calculate_user_value(comment.content or "", comment.like_count or "0")
            # 如果指定了用户ID，不限制意向等级；否则只分析高/中意向用户
            if request.user_ids or value["level"] in ("高", "中"):
                comment_data.append({
                    "user_id": str(comment.user_id or ""),
                    "short_user_id": str(comment.short_user_id or "") or str(comment.user_unique_id or ""),
                    "comment_id": str(comment.comment_id or ""),
                    "aweme_id": str(comment.aweme_id or ""),
                    "sec_uid": comment.sec_uid or "",
                    "nickname": comment.nickname or "",
                    "content": comment.content or "",
                    "value_score": value["score"],
                    "value_level": value["level"],
                    "intent": value["intent"],
                })
        
        # 如果数据库中没有数据，尝试从jsonl文件读取
        if not comment_data:
            try:
                import glob
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                data_dir = os.path.join(project_root, "data", task.platform if task.platform != "douyin" else "douyin", "jsonl")
                jsonl_files = glob.glob(os.path.join(data_dir, "*comments*.jsonl"))
                jsonl_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                
                for jsonl_file in jsonl_files[:2]:
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                item = json.loads(line)
                                value = calculate_user_value(item.get("content", ""), str(item.get("like_count", "0")))
                                # 如果指定了用户ID，不限制意向等级；否则只分析高/中意向用户
                                if request.user_ids or value["level"] in ("高", "中"):
                                    comment_data.append({
                                        "user_id": str(item.get("user_id", "")),
                                        "short_user_id": str(item.get("short_user_id", "")) or str(item.get("user_unique_id", "")),
                                        "comment_id": str(item.get("comment_id", "")),
                                        "aweme_id": str(item.get("aweme_id", "")),
                                        "sec_uid": item.get("sec_uid", "") or "",
                                        "nickname": item.get("nickname", "") or "",
                                        "content": item.get("content", "") or "",
                                        "value_score": value["score"],
                                        "value_level": value["level"],
                                        "intent": value["intent"],
                                    })
                            except json.JSONDecodeError:
                                continue
                    if len(comment_data) >= 1000:  # 增加读取数量以确保能找到指定用户
                        break
            except Exception as e:
                print(f"[analyze-needs] Error reading comments: {e}")
        
        # 如果指定了user_ids，支持通过用户ID、comment_id或昵称查询
        if request.user_ids:
            # 统一转为字符串，避免 jsonl 中 user_id 为 int 导致匹配失败
            user_id_set = set(str(uid) for uid in request.user_ids)
            print(f"[analyze-needs] Searching for users: {request.user_ids}")
            print(f"[analyze-needs] Total comment_data before filtering: {len(comment_data)}")
            
            # 优先通过精确ID匹配（user_id / short_user_id / comment_id）
            id_matches = [
                c for c in comment_data
                if str(c.get("user_id", "")) in user_id_set 
                   or str(c.get("short_user_id", "")) in user_id_set
                   or str(c.get("comment_id", "")) in user_id_set
            ]
            print(f"[analyze-needs] ID matches: {len(id_matches)}")
            
            if id_matches:
                comment_data = id_matches
            else:
                # 如果ID没有匹配到，尝试通过昵称匹配（支持模糊匹配）
                nickname_matches = []
                for item in request.user_ids:
                    search_str = str(item).lower()
                    for comment in comment_data:
                        nickname = str(comment.get("nickname", "")).lower()
                        if search_str in nickname or nickname in search_str:
                            nickname_matches.append(comment)
                            print(f"[analyze-needs] Nickname match found: {comment.get('nickname')} (search: {item})")
                
                if nickname_matches:
                    comment_data = nickname_matches
                    print(f"[analyze-needs] Using nickname matches: {len(comment_data)}")
                else:
                    comment_data = []
                    print(f"[analyze-needs] No matches found")
        
        # 限制分析数量
        comment_data = comment_data[:request.max_users]
        
        # 分析每个用户的需求
        results = []
        for comment in comment_data:
            need_type = classify_need_type(comment["content"])
            pain_points = extract_pain_points(comment["content"])
            budget = analyze_budget_sensitivity(comment["content"])
            urgency = analyze_urgency(comment["content"])
            pitch = generate_pitch(need_type, pain_points, comment["content"])
            
            results.append({
                "user_id": comment["user_id"],
                "sec_uid": comment["sec_uid"],
                "nickname": comment["nickname"],
                "need_type": need_type,
                "need_type_name": NEED_TYPE_MAP.get(need_type, {}).get("name", "一般关注"),
                "need_summary": NEED_TYPE_MAP.get(need_type, {}).get("strategy", ""),
                "pain_points": pain_points,
                "budget_sensitivity": budget,
                "urgency": urgency,
                "recommended_pitch": pitch,
                "value_score": comment["value_score"],
                "value_level": comment["value_level"],
                "intent": comment["intent"],
                "confidence": min(0.95, 0.6 + len(pain_points) * 0.1),
            })
        
        return {
            "analyzed_count": len(results),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.post("/{task_id}/generate-content")
async def generate_ad_content_api(task_id: str, request: GenerateContentRequest, current_user: dict = Depends(get_current_user)):
    """生成个性化广告文案"""
    session = await _get_db_session()
    try:
        # 获取任务详情中的评论数据
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)
        
        # 从jsonl文件读取评论数据
        user_comments = {}
        try:
            import glob
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            data_dir = os.path.join(project_root, "data", task.platform if task.platform != "douyin" else "douyin", "jsonl")
            jsonl_files = glob.glob(os.path.join(data_dir, "*comments*.jsonl"))
            jsonl_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            
            for jsonl_file in jsonl_files[:2]:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            item = json.loads(line)
                            user_id = str(item.get("user_id", ""))
                            if user_id in request.user_ids:
                                user_comments[user_id] = {
                                    "user_id": user_id,
                                    "sec_uid": item.get("sec_uid", "") or "",
                                    "nickname": item.get("nickname", "") or "",
                                    "content": item.get("content", "") or "",
                                    "avatar": item.get("avatar", "") or "",
                                }
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            print(f"[generate-content] Error reading comments: {e}")
        
        # 读取任务推广配置
        promo_config = {}
        if task.promo_config:
            try:
                promo_config = json.loads(task.promo_config)
            except:
                promo_config = {}
        
        # 生成文案
        contents = []
        for user_id in request.user_ids:
            user_info = user_comments.get(user_id, {"user_id": user_id, "author": "用户", "content": ""})
            need_type = classify_need_type(user_info.get("content", ""))
            ad_content = generate_ad_content(need_type, user_info, request.tone, promo_config)
            
            contents.append({
                "user_id": user_id,
                "sec_uid": user_info.get("sec_uid", ""),
                "nickname": user_info.get("nickname", ""),
                "need_type": need_type,
                "need_type_name": NEED_TYPE_MAP.get(need_type, {}).get("name", "一般关注"),
                "direct_message": ad_content["direct_message"],
                "comment_reply": ad_content["comment_reply"],
                "profile_message": ad_content["profile_message"],
                "tone": ad_content["tone"],
                "products": ad_content["products"],
                "call_to_action": ad_content["call_to_action"],
            })
        
        return {
            "generated_count": len(contents),
            "contents": contents,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


@router.post("/{task_id}/outreach")
async def create_outreach_task(task_id: str, request: OutreachExecuteRequest, current_user: dict = Depends(get_current_user)):
    """创建触达任务 - 使用自动化引擎"""
    from ..services.outreach_automation import create_outreach_task_data, execute_outreach_async

    # 校验任务归属
    session = await _get_db_session()
    try:
        t_result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        t = t_result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(t, current_user)
    finally:
        await session.close()

    # 去重检查：如果该用户已成功发送过私信，则跳过（评论回复不做去重）
    if request.method == "direct_message":
        session = await _get_db_session()
        try:
            existing = await session.execute(
                select(OutreachTaskModel).where(
                    OutreachTaskModel.sec_uid == request.sec_uid,
                    OutreachTaskModel.status == "success",
                )
            )
            if existing.scalar_one_or_none():
                return {
                    "task_id": "",
                    "status": "skipped",
                    "message": f"用户 {request.nickname or request.sec_uid} 已发送过私信，跳过重复发送",
                    "user_homepage": f"https://www.douyin.com/user/{request.sec_uid}",
                }
        except Exception:
            pass
        finally:
            await session.close()

    # 创建任务（已自动落库）
    task = await create_outreach_task_data(
        user_id=request.user_id,
        sec_uid=request.sec_uid,
        platform=request.platform or "douyin",
        content=request.content,
        nickname=request.nickname,
        method=request.method,
        note_id=request.note_id,
        comment_id=request.comment_id,
    )

    # 如果不需要确认，立即执行
    if not request.require_confirm:
        await execute_outreach_async(task.id)

    return {
        "task_id": task.id,
        "status": task.status.value,
        "message": "触达任务已创建" + ("，等待确认后执行" if request.require_confirm else "，正在自动执行"),
        "user_homepage": f"https://www.douyin.com/user/{request.sec_uid}",
    }


@router.post("/{task_id}/outreach/{outreach_id}/execute")
async def execute_outreach_task(task_id: str, outreach_id: str, current_user: dict = Depends(get_current_user)):
    """执行触达任务 - 启动浏览器自动发送私信"""
    from ..services.outreach_automation import get_outreach_task_from_db, execute_outreach_async

    # 校验任务归属
    session = await _get_db_session()
    try:
        t_result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        t = t_result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(t, current_user)
    finally:
        await session.close()

    task = await get_outreach_task_from_db(outreach_id)
    if not task:
        raise HTTPException(status_code=404, detail="Outreach task not found")

    # 异步启动自动化流程
    await execute_outreach_async(outreach_id)

    return {
        "task_id": outreach_id,
        "status": "running",
        "user_homepage": f"https://www.douyin.com/user/{task.sec_uid}",
        "content": task.content,
        "message": "自动化触达已启动，正在打开浏览器发送私信...",
    }


@router.get("/{task_id}/outreach/{outreach_id}/status")
async def get_outreach_status(task_id: str, outreach_id: str, current_user: dict = Depends(get_current_user)):
    """获取触达任务执行状态和进度"""
    from ..services.outreach_automation import get_outreach_task_from_db

    # 校验任务归属
    session = await _get_db_session()
    try:
        t_result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        t = t_result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(t, current_user)
    finally:
        await session.close()

    task = await get_outreach_task_from_db(outreach_id)
    if not task:
        raise HTTPException(status_code=404, detail="Outreach task not found")

    return {
        "task_id": task.id,
        "status": task.status.value,
        "steps": [
            {
                "step": s.step,
                "name": s.name,
                "status": s.status,
                "message": s.message,
                "screenshot": s.screenshot,
            }
            for s in task.steps
        ],
        "result": task.result,
        "error_message": task.error_message,
        "logs": task.logs,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


@router.get("/{task_id}/outreach-records")
async def get_outreach_records(task_id: str, limit: int = 50, offset: int = 0, current_user: dict = Depends(get_current_user)):
    """获取任务的触达记录列表"""
    # 校验任务归属
    session = await _get_db_session()
    try:
        t_result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        t = t_result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(t, current_user)
    finally:
        await session.close()

    engine = get_async_engine(config.SAVE_DATA_OPTION)
    if not engine:
        return {"records": [], "total": 0}

    try:
        AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionFactory() as session:
            # 统计总数
            count_result = await session.execute(
                select(func.count()).select_from(OutreachRecord).where(OutreachRecord.task_id == task_id)
            )
            total = count_result.scalar() or 0

            # 查询记录
            result = await session.execute(
                select(OutreachRecord)
                .where(OutreachRecord.task_id == task_id)
                .order_by(desc(OutreachRecord.send_time))
                .offset(offset)
                .limit(limit)
            )
            records = result.scalars().all()

            return {
                "records": [
                    {
                        "id": r.id,
                        "task_id": r.task_id,
                        "platform": r.platform,
                        "user_id": r.user_id,
                        "sec_uid": r.sec_uid,
                        "nickname": r.nickname,
                        "user_url": r.user_url,
                        "message_content": r.message_content,
                        "status": r.status,
                        "error_message": r.error_message,
                        "screenshot": r.screenshot,
                        "send_time": r.send_time,
                        "add_ts": r.add_ts,
                    }
                    for r in records
                ],
                "total": total,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# ==================== 自动获客 ====================

class AutoOutreachRequest(BaseModel):
    intent_level: str = "high"  # high | medium | all
    max_users: int = 999
    tone: str = "friendly"
    auto_send: bool = True  # 是否自动发送私信
    interval_seconds: int = 180  # 每个用户之间的发送间隔（秒），建议3分钟以上
    method: str = "direct_message"  # direct_message | comment_reply


# 自动获客任务状态（内存缓存，执行完成后落库）
_auto_outreach_jobs: Dict[str, dict] = {}


@router.post("/{task_id}/auto-outreach")
async def start_auto_outreach(task_id: str, request: AutoOutreachRequest, current_user: dict = Depends(get_current_user)):
    """一键自动获客：筛选高意向→分析需求→生成文案→自动发送私信

    优先从 customer_lead 表获取已分析的用户，如果没有则从评论表筛选
    """
    session = await _get_db_session()
    try:
        result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(task, current_user)

        # 1. 优先从 customer_lead 表获取已分析的用户
        target_users = []
        platform = task.platform or ""

        # 尝试从 customer_lead 表获取
        lead_query = select(CustomerLead).where(CustomerLead.task_id == task_id)
        # 按意向等级过滤
        if request.intent_level == "high":
            lead_query = lead_query.where(CustomerLead.intent_type.in_(["inquiry", "purchase", "strong_interest"]))
        elif request.intent_level == "medium":
            lead_query = lead_query.where(CustomerLead.intent_type.in_(["inquiry", "purchase", "strong_interest", "discussion", "comparison"]))
        # 排除已发送的
        lead_query = lead_query.where(CustomerLead.status.in_(["new", "pending"]))
        lead_query = lead_query.order_by(desc(CustomerLead.lead_score))
        
        lead_result = await session.execute(lead_query)
        lead_list = lead_result.scalars().all()
        
        if lead_list:
            utils.logger.info(f"[AutoOutreach] Found {len(lead_list)} customer leads for task {task_id}")
            
            # 收集需要补充sec_uid的user_id
            need_sec_uid_user_ids = []
            for lead in lead_list:
                if not lead.sec_uid and lead.user_id:
                    need_sec_uid_user_ids.append(lead.user_id)
            
            # 从评论表补充sec_uid
            sec_uid_map = {}
            if need_sec_uid_user_ids and platform in ("dy", "douyin"):
                try:
                    comment_result = await session.execute(
                        select(DouyinAwemeComment).where(
                            DouyinAwemeComment.task_id == task_id,
                            DouyinAwemeComment.sec_uid != "",
                            DouyinAwemeComment.sec_uid != None,
                        )
                    )
                    for comment in comment_result.scalars().all():
                        if comment.nickname and comment.sec_uid:
                            sec_uid_map[comment.nickname] = comment.sec_uid
                except Exception as e:
                    utils.logger.warning(f"[AutoOutreach] Failed to supplement sec_uid from comments: {e}")
            
            for lead in lead_list:
                # 意向等级映射
                intent_level = "低"
                if lead.lead_score and lead.lead_score >= 80:
                    intent_level = "高"
                elif lead.lead_score and lead.lead_score >= 50:
                    intent_level = "中"
                
                if request.intent_level == "high" and intent_level != "高":
                    continue
                elif request.intent_level == "medium" and intent_level not in ("高", "中"):
                    continue
                
                # 补充sec_uid（如果customer_lead中没有，从评论表补充）
                sec_uid = lead.sec_uid or ""
                if not sec_uid and lead.nickname and lead.nickname in sec_uid_map:
                    sec_uid = sec_uid_map[lead.nickname]
                
                # 抖音平台没有sec_uid则跳过（无法访问用户主页）
                if not sec_uid and platform in ("dy", "douyin"):
                    continue
                
                target_users.append({
                    "user_id": lead.user_id or "",
                    "sec_uid": sec_uid,
                    "nickname": lead.nickname or "",
                    "content": lead.content or "",
                    "value_score": lead.lead_score or 0,
                    "value_level": intent_level,
                    "intent": lead.intent_type or "",
                    "platform": platform,
                    "lead_id": lead.id,  # 保存lead_id用于后续更新状态
                })
        
        # 如果 customer_lead 没有数据，回退到从评论表筛选
        use_comment_fallback = len(target_users) == 0
        
        # 定义各平台评论模型和字段映射
        platform_config = {
            "dy": {
                "model": DouyinAwemeComment,
                "id_field": "sec_uid",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "like_count",
                "has_task_id": True,
            },
            "douyin": {
                "model": DouyinAwemeComment,
                "id_field": "sec_uid",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "like_count",
                "has_task_id": True,
            },
            "xhs": {
                "model": XhsNoteComment,
                "id_field": "user_id",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "like_count",
                "has_task_id": True,
            },
            "xiaohongshu": {
                "model": XhsNoteComment,
                "id_field": "user_id",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "like_count",
                "has_task_id": True,
            },
            "ks": {
                "model": KuaishouVideoComment,
                "id_field": "user_id",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "sub_comment_count",
                "has_task_id": True,
            },
            "kuaishou": {
                "model": KuaishouVideoComment,
                "id_field": "user_id",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "sub_comment_count",
                "has_task_id": True,
            },
            "wb": {
                "model": WeiboNoteComment,
                "id_field": "user_id",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "comment_like_count",
                "has_task_id": True,
            },
            "weibo": {
                "model": WeiboNoteComment,
                "id_field": "user_id",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "comment_like_count",
                "has_task_id": True,
            },
            "bili": {
                "model": BilibiliVideoComment,
                "id_field": "user_id",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "like_count",
                "has_task_id": True,
            },
            "bilibili": {
                "model": BilibiliVideoComment,
                "id_field": "user_id",
                "nickname_field": "nickname",
                "content_field": "content",
                "like_field": "like_count",
                "has_task_id": True,
            },
            "tieba": {
                "model": TiebaComment,
                "id_field": "user_link",
                "nickname_field": "user_nickname",
                "content_field": "content",
                "like_field": "sub_comment_count",
                "has_task_id": True,
            },
            "zhihu": {
                "model": ZhihuComment,
                "id_field": "user_id",
                "nickname_field": "user_nickname",
                "content_field": "content",
                "like_field": "like_count",
                "has_task_id": True,
            },
        }

        if use_comment_fallback:
            pconf = platform_config.get(platform)
            if not pconf:
                return {
                    "job_id": "",
                    "status": "error",
                    "message": f"不支持的平台: {platform}，支持的平台: dy、xhs、ks、wb、bili、tieba、zh",
                    "total_targets": 0,
                }

            model = pconf["model"]
            # 构建查询条件 - 严格按task_id隔离
            if pconf["has_task_id"] and hasattr(model, 'task_id'):
                comment_query = select(model).where(
                    model.task_id == task_id
                ).order_by(desc(model.add_ts))
            else:
                comment_query = select(model).order_by(desc(model.add_ts))

            comment_result = await session.execute(comment_query)
            comment_list = comment_result.scalars().all()

            for comment in comment_list:
                content = getattr(comment, pconf["content_field"], "") or ""
                like_count = getattr(comment, pconf["like_field"], "0") or "0"
                value = calculate_user_value(content, str(like_count))
                if request.intent_level == "high" and value["level"] != "高":
                    continue
                elif request.intent_level == "medium" and value["level"] not in ("高", "中"):
                    continue
                # 获取用户唯一标识
                user_identifier = str(getattr(comment, pconf["id_field"], "") or "")
                if not user_identifier:
                    continue
                nickname = getattr(comment, pconf["nickname_field"], "") or ""
                target_users.append({
                    "user_id": user_identifier,
                    "sec_uid": user_identifier if platform in ("dy", "douyin") else "",
                    "nickname": nickname,
                    "content": content,
                    "value_score": value["score"],
                    "value_level": value["level"],
                    "intent": value["intent"],
                    "platform": platform,
                })

        # 按评分降序排列，取前 max_users 个
        target_users.sort(key=lambda x: x["value_score"], reverse=True)
        target_users = target_users[:request.max_users]

        # 去重：排除已发送过私信的用户
        sent_ids = set()
        # 查询 OutreachRecord（已发送记录）
        sent_records = await session.execute(
            select(OutreachRecord.sec_uid).where(OutreachRecord.status == "success")
        )
        for row in sent_records.scalars().all():
            if row:
                sent_ids.add(row)
        # 查询 OutreachTaskModel（触达任务记录）
        sent_tasks = await session.execute(
            select(OutreachTaskModel.sec_uid).where(OutreachTaskModel.status == "success")
        )
        for row in sent_tasks.scalars().all():
            if row:
                sent_ids.add(row)

        # 过滤已发送用户（抖音用 sec_uid，小红书用 user_id）
        before_count = len(target_users)
        target_users = [u for u in target_users if (u.get("sec_uid") or u.get("user_id")) not in sent_ids]
        skipped_count = before_count - len(target_users)

        if not target_users:
            return {
                "job_id": "",
                "status": "no_targets",
                "message": f"未找到符合条件的用户（意向等级: {request.intent_level}），已跳过 {skipped_count} 个已发送用户",
                "total_targets": 0,
                "skipped": skipped_count,
            }

        # 2. 为每个用户生成文案
        promo_config = {}
        if task.promo_config:
            try:
                promo_config = json.loads(task.promo_config)
            except Exception:
                pass

        outreach_list = []
        for user in target_users:
            need_type = classify_need_type(user["content"])
            ad_content = generate_ad_content(need_type, user, request.tone, promo_config)
            outreach_list.append({
                "user_id": user["user_id"],
                "sec_uid": user["sec_uid"],
                "nickname": user["nickname"],
                "content": user["content"],
                "value_score": user["value_score"],
                "value_level": user["value_level"],
                "intent": user["intent"],
                "need_type": need_type,
                "need_type_name": NEED_TYPE_MAP.get(need_type, {}).get("name", "一般关注"),
                "direct_message": ad_content["direct_message"],
                "comment_reply": ad_content["comment_reply"],
                "method": request.method,  # direct_message | comment_reply
                "note_id": user.get("note_id", user.get("aweme_id", "")),
                "comment_id": user.get("comment_id", ""),
                "lead_id": user.get("lead_id"),  # 客户线索ID，用于更新状态
            })

        # 3. 创建自动获客任务
        job_id = f"auto_outreach_{uuid.uuid4().hex[:8]}"
        job = {
            "job_id": job_id,
            "task_id": task_id,
            "task_platform": platform,
            "status": "running",
            "total": len(outreach_list),
            "completed": 0,
            "success": 0,
            "failed": 0,
            "skipped": skipped_count,
            "results": [],
            "outreach_list": outreach_list,
            "auto_send": request.auto_send,
            "interval_seconds": request.interval_seconds,
            "created_at": int(time.time() * 1000),
            "current_index": 0,
            "data_source": "customer_lead" if not use_comment_fallback else "comment",  # 数据来源
        }
        _auto_outreach_jobs[job_id] = job

        # 4. 持久化到数据库
        now_ms = int(time.time() * 1000)
        db_job = AutoOutreachJobModel(
            job_id=job_id,
            task_id=task_id,
            platform=platform,
            intent_level=request.intent_level,
            status="running",
            total=len(outreach_list),
            completed=0,
            success=0,
            failed=0,
            skipped=skipped_count,
            results="[]",
            outreach_list=json.dumps(outreach_list, ensure_ascii=False),
            auto_send=1 if request.auto_send else 0,
            interval_seconds=request.interval_seconds,
            current_index=0,
            created_at=now_ms,
            updated_at=now_ms,
            data_source="customer_lead" if not use_comment_fallback else "comment",
        )
        session.add(db_job)
        await session.commit()

        # 4.5 标记 customer_lead 为 pending（正在触达）
        if not use_comment_fallback:
            lead_ids = [u.get("lead_id") for u in target_users if u.get("lead_id")]
            if lead_ids:
                try:
                    await session.execute(
                        update(CustomerLead).where(CustomerLead.id.in_(lead_ids)).values(status="pending", last_modify_ts=int(time.time() * 1000))
                    )
                    await session.commit()
                    utils.logger.info(f"[AutoOutreach] Marked {len(lead_ids)} customer leads as pending")
                except Exception as e:
                    utils.logger.warning(f"[AutoOutreach] Failed to mark leads as pending: {e}")

        # 5. 异步执行发送
        if request.auto_send:
            asyncio.create_task(_execute_auto_outreach(job_id))

        return {
            "job_id": job_id,
            "status": "running" if request.auto_send else "ready",
            "message": f"已筛选 {len(outreach_list)} 个高意向用户（跳过 {skipped_count} 个已发送），{'正在自动发送私信' if request.auto_send else '文案已生成，等待手动发送'}",
            "total_targets": len(outreach_list),
            "skipped": skipped_count,
            "targets": outreach_list,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await session.close()


async def _execute_auto_outreach(job_id: str):
    """后台执行自动获客：逐个发送私信，每完成一个用户持久化到数据库"""
    from ..services.outreach_automation import (
        create_outreach_task_data, execute_outreach_automation,
    )

    job = _auto_outreach_jobs.get(job_id)
    if not job:
        # 尝试从数据库加载
        session = await _get_db_session()
        try:
            result = await session.execute(
                select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
            )
            db_obj = result.scalar_one_or_none()
            if db_obj:
                job = {
                    "job_id": db_obj.job_id,
                    "task_id": db_obj.task_id,
                    "task_platform": db_obj.platform,
                    "status": db_obj.status,
                    "total": db_obj.total,
                    "completed": db_obj.completed,
                    "success": db_obj.success,
                    "failed": db_obj.failed,
                    "skipped": db_obj.skipped,
                    "results": json.loads(db_obj.results or '[]'),
                    "outreach_list": json.loads(db_obj.outreach_list or '[]'),
                    "auto_send": bool(db_obj.auto_send),
                    "interval_seconds": db_obj.interval_seconds,
                    "created_at": db_obj.created_at,
                    "current_index": db_obj.current_index,
                }
                _auto_outreach_jobs[job_id] = job
        finally:
            await session.close()

    if not job:
        utils.logger.error(f"[AutoOutreach] Job {job_id} not found")
        return

    try:
        # 主执行逻辑
        await _execute_auto_outreach_inner(job_id, job)
    except Exception as e:
        utils.logger.error(f"[AutoOutreach] Job {job_id} crashed unexpectedly: {e}")
        # 确保任务状态被更新为失败
        job["status"] = "completed"
        session = await _get_db_session()
        try:
            result = await session.execute(
                select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
            )
            db_obj = result.scalar_one_or_none()
            if db_obj:
                db_obj.status = "completed"
                db_obj.completed = job.get("completed", 0)
                db_obj.success = job.get("success", 0)
                db_obj.failed = job.get("failed", 0)
                db_obj.current_index = job.get("current_index", 0)
                db_obj.results = json.dumps(job.get("results", []), ensure_ascii=False)
                db_obj.updated_at = int(time.time() * 1000)
                await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()


async def _execute_auto_outreach_inner(job_id: str, job: dict):
    """自动获客执行核心逻辑"""
    from ..services.outreach_automation import (
        create_outreach_task_data, execute_outreach_automation,
    )
    if not job:
        return

    # 从数据库加载已完成的进度（支持断点续传）
    session = await _get_db_session()
    try:
        db_job = await session.execute(
            select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
        )
        db_job_obj = db_job.scalar_one_or_none()
        start_index = 0
        if db_job_obj and db_job_obj.current_index > 0:
            start_index = db_job_obj.current_index
            # 恢复内存状态
            job["success"] = db_job_obj.success
            job["failed"] = db_job_obj.failed
            job["completed"] = db_job_obj.completed
            job["results"] = json.loads(db_job_obj.results or '[]')
    except Exception:
        start_index = 0
    finally:
        await session.close()

    utils.logger.info(f"[AutoOutreach] Starting job {job_id}: total={len(job['outreach_list'])} targets, start_index={start_index}")

    for i in range(start_index, len(job["outreach_list"])):
        # 检查是否被取消
        if job.get("status") == "cancelled":
            utils.logger.info(f"[AutoOutreach] Job {job_id} cancelled at index {i}")
            break

        # 连续失败检测：如果连续2次以上"未找到私信按钮"，等待更长时间让浏览器重置
        consecutive_pm_fail = 0
        for r in reversed(job["results"]):
            if not r.get("success") and "私信按钮" in r.get("error", ""):
                consecutive_pm_fail += 1
            else:
                break
        if consecutive_pm_fail >= 2:
            utils.logger.warning(f"[AutoOutreach] {consecutive_pm_fail} consecutive PM button failures, waiting 30s for browser reset...")
            await asyncio.sleep(30)

        target = job["outreach_list"][i]
        utils.logger.info(f"[AutoOutreach] Processing user {i+1}/{len(job['outreach_list'])}: {target.get('nickname', '?')} ({target.get('user_id', '')[:20]}...)")
        try:
            # 根据触达方式选择内容
            method = target.get("method", "direct_message")
            content = target["direct_message"]
            if method == "comment_reply":
                content = target.get("comment_reply", target["direct_message"])
            
            # 创建触达任务
            outreach_task = await create_outreach_task_data(
                user_id=target["user_id"],
                sec_uid=target["sec_uid"],
                platform=target.get("platform", job.get("task_platform", "douyin")),
                content=content,
                nickname=target["nickname"],
                method=method,
                note_id=target.get("note_id", ""),
                comment_id=target.get("comment_id", ""),
            )

            # 执行发送（频率限制时自动重试）
            max_retries = 3
            for retry in range(max_retries):
                result = await execute_outreach_automation(outreach_task.id)

                # 如果是频率限制错误，等待后重试
                error_msg = result.get("error", "")
                if not result.get("success") and "频繁" in error_msg and retry < max_retries - 1:
                    import re
                    wait_match = re.search(r'等待\s*(\d+)\s*秒', error_msg)
                    wait_seconds = int(wait_match.group(1)) if wait_match else 60
                    wait_seconds = min(wait_seconds + 10, 300)  # 多等10秒，最多5分钟
                    utils.logger.info(f"[AutoOutreach] Rate limited for {target.get('nickname','?')}, waiting {wait_seconds}s (retry {retry+1}/{max_retries})...")
                    await asyncio.sleep(wait_seconds)
                    # 重新创建任务（因为上一个已经标记失败了）
                    outreach_task = await create_outreach_task_data(
                        user_id=target["user_id"],
                        sec_uid=target["sec_uid"],
                        platform=target.get("platform", job.get("task_platform", "douyin")),
                        content=content,
                        nickname=target["nickname"],
                        method=method,
                        note_id=target.get("note_id", ""),
                        comment_id=target.get("comment_id", ""),
                    )
                    continue
                break

            job["results"].append({
                "user_id": target["user_id"],
                "nickname": target["nickname"],
                "sec_uid": target["sec_uid"],
                "outreach_task_id": outreach_task.id,
                "success": result.get("success", False),
                "message": result.get("message", result.get("error", "")),
                "error": result.get("error", ""),
                "skip_retry": result.get("skip_retry", False),
                "direct_message": target["direct_message"],
            })

            if result.get("success"):
                job["success"] += 1
            else:
                job["failed"] += 1

            # 更新 customer_lead 状态
            lead_id = target.get("lead_id")
            if lead_id:
                try:
                    lead_session = await _get_db_session()
                    try:
                        lead_result = await lead_session.execute(
                            select(CustomerLead).where(CustomerLead.id == lead_id)
                        )
                        lead_obj = lead_result.scalar_one_or_none()
                        if lead_obj:
                            if result.get("success"):
                                lead_obj.status = "contacted"
                                lead_obj.notes = f"私信发送成功 - {time.strftime('%Y-%m-%d %H:%M')}"
                            else:
                                lead_obj.status = "failed"
                                lead_obj.notes = f"私信发送失败: {result.get('error', '未知错误')} - {time.strftime('%Y-%m-%d %H:%M')}"
                            lead_obj.last_modify_ts = int(time.time() * 1000)
                            await lead_session.commit()
                    except Exception:
                        await lead_session.rollback()
                    finally:
                        await lead_session.close()
                except Exception as e:
                    utils.logger.warning(f"[AutoOutreach] Failed to update customer_lead status: {e}")

        except Exception as e:
            job["results"].append({
                "user_id": target["user_id"],
                "nickname": target["nickname"],
                "sec_uid": target["sec_uid"],
                "success": False,
                "message": str(e),
                "error": str(e),
            })
            job["failed"] += 1

        job["completed"] = job["success"] + job["failed"]
        job["current_index"] = i + 1

        # 每完成一个用户，持久化到数据库
        session = await _get_db_session()
        try:
            db_job = await session.execute(
                select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
            )
            db_obj = db_job.scalar_one_or_none()
            if db_obj:
                db_obj.completed = job["completed"]
                db_obj.success = job["success"]
                db_obj.failed = job["failed"]
                db_obj.current_index = i + 1
                db_obj.results = json.dumps(job["results"], ensure_ascii=False)
                db_obj.updated_at = int(time.time() * 1000)
                await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()

        # 如果不是最后一个，等待间隔
        if i < len(job["outreach_list"]) - 1 and job.get("status") != "cancelled":
            await asyncio.sleep(job["interval_seconds"])

    utils.logger.info(f"[AutoOutreach] Job {job_id} loop finished: success={job['success']}, failed={job['failed']}, completed={job['completed']}/{len(job['outreach_list'])}")

    # 任务完成，更新数据库
    job["status"] = "completed"
    session = await _get_db_session()
    try:
        db_job = await session.execute(
            select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
        )
        db_obj = db_job.scalar_one_or_none()
        if db_obj:
            db_obj.status = "completed"
            db_obj.completed = job["completed"]
            db_obj.success = job["success"]
            db_obj.failed = job["failed"]
            db_obj.current_index = len(job["outreach_list"])
            db_obj.results = json.dumps(job["results"], ensure_ascii=False)
            db_obj.finished_at = int(time.time() * 1000)
            db_obj.updated_at = int(time.time() * 1000)
            await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()


@router.get("/{task_id}/auto-outreach/{job_id}/status")
async def get_auto_outreach_status(task_id: str, job_id: str, current_user: dict = Depends(get_current_user)):
    """获取自动获客任务状态 — 优先从内存读取，fallback到数据库"""
    # 校验任务归属
    session = await _get_db_session()
    try:
        t_result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        t = t_result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(t, current_user)
    finally:
        await session.close()

    job = _auto_outreach_jobs.get(job_id)
    if job:
        return {
            "job_id": job["job_id"],
            "task_id": job["task_id"],
            "status": job["status"],
            "total": job["total"],
            "completed": job["completed"],
            "success": job["success"],
            "failed": job["failed"],
            "skipped": job.get("skipped", 0),
            "results": job["results"],
            "targets": job.get("outreach_list", []),
            "created_at": job["created_at"],
            "current_index": job.get("current_index", 0),
        }

    # 内存中没有，从数据库读取
    session = await _get_db_session()
    try:
        result = await session.execute(
            select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
        )
        db_obj = result.scalar_one_or_none()
        if not db_obj:
            raise HTTPException(status_code=404, detail="Auto outreach job not found")
        return {
            "job_id": db_obj.job_id,
            "task_id": db_obj.task_id,
            "status": db_obj.status,
            "total": db_obj.total,
            "completed": db_obj.completed,
            "success": db_obj.success,
            "failed": db_obj.failed,
            "skipped": db_obj.skipped,
            "results": json.loads(db_obj.results or '[]'),
            "targets": json.loads(db_obj.outreach_list or '[]'),
            "created_at": db_obj.created_at,
            "current_index": db_obj.current_index,
        }
    finally:
        await session.close()


@router.post("/{task_id}/auto-outreach/{job_id}/cancel")
async def cancel_auto_outreach_job(task_id: str, job_id: str, current_user: dict = Depends(get_current_user)):
    """取消运行中的自动获客任务"""
    # 校验任务归属
    session = await _get_db_session()
    try:
        t_result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        t = t_result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(t, current_user)
    finally:
        await session.close()

    job = _auto_outreach_jobs.get(job_id)
    if not job:
        # 尝试从数据库加载
        session = await _get_db_session()
        try:
            result = await session.execute(
                select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
            )
            db_obj = result.scalar_one_or_none()
            if db_obj:
                job = {
                    "job_id": db_obj.job_id,
                    "task_id": db_obj.task_id,
                    "status": db_obj.status,
                    "total": db_obj.total,
                    "completed": db_obj.completed,
                    "success": db_obj.success,
                    "failed": db_obj.failed,
                    "skipped": db_obj.skipped,
                    "results": json.loads(db_obj.results or '[]'),
                    "outreach_list": json.loads(db_obj.outreach_list or '[]'),
                    "auto_send": bool(db_obj.auto_send),
                    "interval_seconds": db_obj.interval_seconds,
                    "created_at": db_obj.created_at,
                    "current_index": db_obj.current_index,
                }
                _auto_outreach_jobs[job_id] = job
        finally:
            await session.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Auto outreach job not found")
    
    if job["status"] != "running":
        raise HTTPException(status_code=400, detail="Job is not running")
    
    job["status"] = "cancelled"
    
    # 更新数据库
    session = await _get_db_session()
    try:
        result = await session.execute(
            select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
        )
        db_obj = result.scalar_one_or_none()
        if db_obj:
            db_obj.status = "cancelled"
            db_obj.completed = job["completed"]
            db_obj.success = job["success"]
            db_obj.failed = job["failed"]
            db_obj.current_index = job.get("current_index", 0)
            db_obj.results = json.dumps(job["results"], ensure_ascii=False)
            db_obj.finished_at = int(time.time() * 1000)
            db_obj.updated_at = int(time.time() * 1000)
            await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()
    
    return {"success": True, "message": "任务已取消"}


@router.get("/outreach-task/{outreach_task_id}/logs")
async def get_outreach_task_logs(outreach_task_id: str):
    """获取单个获客任务的详细执行日志"""
    session = await _get_db_session()
    try:
        result = await session.execute(
            select(OutreachTaskModel).where(OutreachTaskModel.id == outreach_task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Outreach task not found")
        return {
            "id": task.id,
            "nickname": task.nickname,
            "user_id": task.user_id,
            "platform": task.platform,
            "status": task.status,
            "error_message": task.error_message,
            "steps": json.loads(task.steps) if task.steps else [],
            "logs": json.loads(task.logs) if task.logs else [],
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
    finally:
        await session.close()


@router.post("/{task_id}/auto-outreach/{job_id}/retry")
async def retry_auto_outreach_job(task_id: str, job_id: str, current_user: dict = Depends(get_current_user)):
    """重试失败的获客任务 - 只重试失败的目标"""
    # 校验任务归属
    session = await _get_db_session()
    try:
        t_result = await session.execute(select(CrawlerTaskModel).where(CrawlerTaskModel.id == task_id))
        t = t_result.scalar_one_or_none()
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        _require_task_owned_by(t, current_user)
    finally:
        await session.close()

    job = _auto_outreach_jobs.get(job_id)

    # 如果内存中没有，从数据库加载
    if not job:
        session = await _get_db_session()
        try:
            result = await session.execute(
                select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
            )
            db_obj = result.scalar_one_or_none()
            if not db_obj:
                raise HTTPException(status_code=404, detail="Auto outreach job not found")

            job = {
                "job_id": db_obj.job_id,
                "task_id": db_obj.task_id,
                "task_platform": db_obj.platform,
                "status": db_obj.status,
                "total": db_obj.total,
                "completed": db_obj.completed,
                "success": db_obj.success,
                "failed": db_obj.failed,
                "skipped": db_obj.skipped,
                "results": json.loads(db_obj.results or '[]'),
                "outreach_list": json.loads(db_obj.outreach_list or '[]'),
                "auto_send": bool(db_obj.auto_send),
                "interval_seconds": db_obj.interval_seconds,
                "created_at": db_obj.created_at,
                "current_index": db_obj.current_index,
            }
            _auto_outreach_jobs[job_id] = job
        finally:
            await session.close()

    if job["status"] == "running":
        raise HTTPException(status_code=400, detail="任务正在运行中，无法重试")

    # 筛选出失败的目标（排除"用户未开启私信"等不可重试的失败）
    failed_results = [r for r in job["results"] if not r.get("success")]
    # 区分可重试和不可重试的失败
    retryable_results = [r for r in failed_results if r.get("error") not in ("用户未开启私信",)]
    non_retryable_count = len(failed_results) - len(retryable_results)

    # 计算未执行的目标（completed < total 且没有对应result的用户）
    completed_user_ids = {r["user_id"] for r in job["results"]}
    untried_targets = [t for t in job["outreach_list"] if t["user_id"] not in completed_user_ids]

    # 可重试目标 = 失败可重试 + 未执行
    retryable_user_ids = {r["user_id"] for r in retryable_results}
    failed_targets = [t for t in job["outreach_list"] if t["user_id"] in retryable_user_ids]
    # 合并：失败目标 + 未执行目标（去重）
    all_retry_targets = failed_targets + [t for t in untried_targets if t["user_id"] not in retryable_user_ids]

    if not all_retry_targets:
        detail = "没有可重试的任务"
        if non_retryable_count > 0:
            detail = f"所有失败任务均为不可重试（{non_retryable_count}个用户未开启私信）"
        raise HTTPException(status_code=400, detail=detail)

    # 保存原始total（不修改，保持任务总量不变）
    original_total = job["total"]

    # 从 results 中移除失败记录（重试后会重新添加）
    job["results"] = [r for r in job["results"] if r.get("success")]
    job["failed"] = 0
    job["completed"] = job["success"]

    # 只将可重试目标放入outreach_list用于执行
    job["outreach_list"] = all_retry_targets
    job["current_index"] = 0
    # total保持原始值，不修改
    job["total"] = original_total
    job["status"] = "running"

    # 更新数据库
    session = await _get_db_session()
    try:
        result = await session.execute(
            select(AutoOutreachJobModel).where(AutoOutreachJobModel.job_id == job_id)
        )
        db_obj = result.scalar_one_or_none()
        if db_obj:
            db_obj.status = "running"
            db_obj.total = job["total"]
            db_obj.completed = job["completed"]
            db_obj.success = job["success"]
            db_obj.failed = 0
            db_obj.current_index = 0
            db_obj.results = json.dumps(job["results"], ensure_ascii=False)
            db_obj.outreach_list = json.dumps(job["outreach_list"], ensure_ascii=False)
            db_obj.finished_at = None
            db_obj.updated_at = int(time.time() * 1000)
            await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()

    # 异步执行重试
    if job.get("auto_send", True):
        asyncio.create_task(_execute_auto_outreach(job_id))

    return {
        "success": True,
        "message": f"正在重试 {len(all_retry_targets)} 个任务" + (f"（{non_retryable_count}个用户未开启私信已跳过）" if non_retryable_count > 0 else ""),
        "retry_count": len(all_retry_targets),
        "skipped_count": non_retryable_count,
    }
