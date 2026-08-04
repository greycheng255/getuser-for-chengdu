# -*- coding: utf-8 -*-
"""
热点分类器

阶段一 P0 任务 1.6：补齐 PRD 5.1.3 第 4 条"热点类型自动标注 + 适配平台自动标注"。

策略：
1. 关键词词库 + LLM 兜底双策略分类
2. 10 个分类标签：娱乐/生活/职场/科技/财经/教育/健康/旅游/美食/时尚
3. 基于分类推荐适配平台（按平台受众匹配）
4. 异步触发，不阻塞入库主流程

对应 PRD 5.1.3 第 4 条：数据处理（热点类型标注、适配平台标注）。
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class HotpointCategory(str, Enum):
    """热点类型"""
    ENTERTAINMENT = "entertainment"   # 娱乐
    LIFE = "life"                     # 生活
    CAREER = "career"                 # 职场
    TECH = "tech"                     # 科技
    FINANCE = "finance"               # 财经
    EDUCATION = "education"           # 教育
    HEALTH = "health"                 # 健康
    TRAVEL = "travel"                 # 旅游
    FOOD = "food"                     # 美食
    FASHION = "fashion"               # 时尚
    OTHER = "other"                   # 其他


# 关键词词库（按分类）
CATEGORY_KEYWORDS = {
    HotpointCategory.ENTERTAINMENT.value: [
        "明星", "演员", "歌手", "电影", "电视剧", "综艺", "演唱会", "偶像", "粉丝",
        "娱乐", "八卦", "绯闻", "离婚", "结婚", "恋情", "出道", "戛纳", "奥斯卡",
        "音乐", "专辑", "MV", "巡演",
    ],
    HotpointCategory.LIFE.value: [
        "生活", "日常", "家居", "装修", "收纳", "宠物", "养花", "育儿", "亲子",
        "结婚", "婚礼", "情感", "关系", "家庭", "邻居", "社区",
    ],
    HotpointCategory.CAREER.value: [
        "职场", "工作", "跳槽", "辞职", "升职", "面试", "简历", "薪资", "工资",
        "996", "内卷", "打工人", "副业", "兼职", "创业", "管理", "领导", "同事",
        "办公", "效率", "时间管理",
    ],
    HotpointCategory.TECH.value: [
        "科技", "技术", "AI", "人工智能", "GPT", "Gemini", "OpenAI", "大模型",
        "编程", "代码", "Python", "Java", "前端", "后端", "算法", "数据结构",
        "互联网", "软件", "硬件", "芯片", "手机", "电脑", "苹果", "华为", "小米",
        "5G", "云计算", "区块链", "元宇宙", "Web3",
    ],
    HotpointCategory.FINANCE.value: [
        "财经", "股票", "基金", "理财", "投资", "A股", "美股", "港股", "比特币",
        "加密货币", "经济", "通胀", "降息", "加息", "GDP", "房价", "楼市",
        "银行", "保险", "贷款", "消费", "通胀",
    ],
    HotpointCategory.EDUCATION.value: [
        "教育", "学习", "考试", "高考", "中考", "考研", "考公", "留学", "雅思",
        "托福", "GRE", "课程", "培训", "老师", "学生", "校园", "大学", "中学",
        "小学", "幼儿园", "作业", "辅导",
    ],
    HotpointCategory.HEALTH.value: [
        "健康", "养生", "保健", "医疗", "医院", "医生", "疾病", "症状", "治疗",
        "运动", "健身", "跑步", "瑜伽", "减肥", "塑形", "睡眠", "心理", "抑郁",
        "焦虑", "饮食", "营养",
    ],
    HotpointCategory.TRAVEL.value: [
        "旅游", "旅行", "出行", "攻略", "景点", "打卡", "度假", "自由行", "跟团",
        "民宿", "酒店", "机票", "高铁", "自驾", "户外", "露营", "徒步", "登山",
        "海岛", "出国", "签证",
    ],
    HotpointCategory.FOOD.value: [
        "美食", "吃货", "餐厅", "探店", "菜谱", "做法", "烹饪", "烘焙", "甜点",
        "奶茶", "咖啡", "火锅", "烧烤", "外卖", "零食", "减肥餐", "健身餐",
        "中餐", "西餐", "日料", "韩餐",
    ],
    HotpointCategory.FASHION.value: [
        "时尚", "穿搭", "美妆", "护肤", "化妆", "口红", "粉底", "香水", "造型",
        "潮流", "穿搭", "搭配", "OOTD", "街拍", "秀场", "时装周", "品牌", "奢侈品",
        "包包", "鞋子", "配饰",
    ],
}


# 分类 → 适配平台映射（按平台受众匹配）
CATEGORY_PLATFORM_MAP = {
    HotpointCategory.ENTERTAINMENT.value: ["douyin", "xiaohongshu", "weibo", "kuaishou"],
    HotpointCategory.LIFE.value: ["xiaohongshu", "douyin", "weibo", "kuaishou"],
    HotpointCategory.CAREER.value: ["zhihu", "bilibili", "weibo"],
    HotpointCategory.TECH.value: ["zhihu", "bilibili", "weibo", "x_twitter"],
    HotpointCategory.FINANCE.value: ["zhihu", "weibo", "bilibili"],
    HotpointCategory.EDUCATION.value: ["bilibili", "zhihu", "xiaohongshu"],
    HotpointCategory.HEALTH.value: ["xiaohongshu", "zhihu", "bilibili"],
    HotpointCategory.TRAVEL.value: ["xiaohongshu", "douyin", "weibo"],
    HotpointCategory.FOOD.value: ["xiaohongshu", "douyin", "weibo", "kuaishou"],
    HotpointCategory.FASHION.value: ["xiaohongshu", "douyin", "weibo"],
    HotpointCategory.OTHER.value: ["douyin", "xiaohongshu", "weibo", "bilibili", "zhihu", "kuaishou"],
}


@dataclass
class ClassificationResult:
    """分类结果"""
    category: str
    confidence: float                  # 置信度 0-1
    matched_keywords: List[str]
    recommended_platforms: List[str]
    method: str = "keywords"           # keywords / ai


class HotpointClassifier:
    """热点分类器"""

    def __init__(self):
        self._keyword_index = self._build_keyword_index()

    def _build_keyword_index(self):
        """构建关键词倒排索引"""
        index = {}
        for category, keywords in CATEGORY_KEYWORDS.items():
            for kw in keywords:
                index[kw] = category
        return index

    async def classify(self, title: str, description: str = "") -> ClassificationResult:
        """分类热点

        策略：
        1. 优先关键词匹配
        2. 关键词命中数 < 2 或多分类冲突 → 调用 AI 兜底
        """
        text = f"{title} {description}".lower()

        # 1. 关键词匹配
        scores = {}
        matched = []
        for kw, category in self._keyword_index.items():
            if kw.lower() in text:
                scores[category] = scores.get(category, 0) + 1
                matched.append(kw)

        if scores:
            best_category = max(scores, key=scores.get)
            best_score = scores[best_category]
            total_score = sum(scores.values())
            confidence = best_score / max(total_score, 1)
            # 关键词命中数 >= 2 且置信度 >= 0.5 → 直接返回
            if best_score >= 2 or confidence >= 0.5:
                return ClassificationResult(
                    category=best_category,
                    confidence=confidence,
                    matched_keywords=matched[:10],
                    recommended_platforms=CATEGORY_PLATFORM_MAP.get(best_category, []),
                    method="keywords",
                )

        # 2. AI 兜底
        ai_result = await self._ai_classify(title, description)
        if ai_result:
            return ai_result

        # 3. 最终兜底：OTHER
        return ClassificationResult(
            category=HotpointCategory.OTHER.value,
            confidence=0.0,
            matched_keywords=matched[:10],
            recommended_platforms=CATEGORY_PLATFORM_MAP[HotpointCategory.OTHER.value],
            method="fallback",
        )

    async def _ai_classify(self, title: str, description: str) -> Optional[ClassificationResult]:
        """AI 兜底分类

        冷却策略：调用前预检 is_ai_in_cooldown()，若 AI 服务处于冷却期则
        静默返回 None（DEBUG 日志），避免在余额不足期间对每条热点都刷一条
        WARNING 日志（曾出现 2000+ 条余额不足 WARNING 刷屏）。
        """
        try:
            from api.services.ai_agent_client import get_ai_agent_client, is_ai_in_cooldown, is_ai_expected_error
            if is_ai_in_cooldown():
                logger.debug("[HotpointClassifier] AI 服务冷却中，跳过 AI 兜底分类")
                return None
            client = get_ai_agent_client()
            categories_str = " / ".join([c.value for c in HotpointCategory])
            prompt = (
                f"请对以下热点进行分类，只输出一个分类标签（不要其他内容）。\n"
                f"可选分类：{categories_str}\n\n"
                f"标题：{title}\n"
                f"描述：{description}\n"
            )
            result = await client.generate_text(prompt)
            if not result:
                return None
            # 提取分类标签
            result = result.strip().lower()
            for cat in HotpointCategory:
                if cat.value in result:
                    return ClassificationResult(
                        category=cat.value,
                        confidence=0.7,
                        matched_keywords=[],
                        recommended_platforms=CATEGORY_PLATFORM_MAP.get(cat.value, []),
                        method="ai",
                    )
        except Exception as e:
            # 预期内错误（冷却/余额/内容审核）降级为 DEBUG，避免日志刷屏
            if is_ai_expected_error(e):
                logger.debug(f"[HotpointClassifier] AI 预期内错误跳过: {e}")
            else:
                logger.warning(f"[HotpointClassifier] AI 兜底失败: {e}")
        return None

    async def recommend_platforms(self, title: str, description: str = "") -> List[str]:
        """便捷方法：根据标题推荐适配平台"""
        result = await self.classify(title, description)
        return result.recommended_platforms

    def get_all_categories(self) -> List[dict]:
        """获取所有分类"""
        return [
            {
                "value": c.value,
                "name": c.name,
                "platforms": CATEGORY_PLATFORM_MAP.get(c.value, []),
                "keywords_count": len(CATEGORY_KEYWORDS.get(c.value, [])),
            }
            for c in HotpointCategory
        ]


# ============ 单例 ============
_classifier: Optional[HotpointClassifier] = None


def get_hotpoint_classifier() -> HotpointClassifier:
    global _classifier
    if _classifier is None:
        _classifier = HotpointClassifier()
    return _classifier
