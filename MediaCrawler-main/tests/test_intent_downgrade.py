# -*- coding: utf-8 -*-
"""意向精准化降级 _apply_intent_downgrade 单元测试

覆盖 PRD §10.1.1:回忆/讨论/过去式购买/长篇陈述 的降级逻辑
"""
import pytest

from api.routers.tasks import (
    _apply_intent_downgrade,
    NOSTALGIA_PATTERNS,
    DISCUSSION_PATTERNS,
    PAST_PURCHASE_PATTERNS,
    STRONG_INTENT_SIGNALS,
)


def _base(level="高", score=80, reason="命中强意向"):
    return {"level": level, "score": score, "reason": reason}


# ---------- 回忆性内容 ----------

def test_nostalgia_downgrades_high_to_medium():
    """回忆性内容应把"高"降到"中",且分数封顶 45"""
    content = "以前小时候也想要一个"  # 命中"以前"类回忆词
    # 确保确实命中回忆模式
    assert any(p in content for p in NOSTALGIA_PATTERNS)

    base = _base(level="高", score=80)
    _apply_intent_downgrade(base, content)
    assert base["level"] == "中"
    assert base["score"] <= 45
    assert "回忆" in base["reason"]


def test_nostalgia_not_downgrade_when_nostal_as_high():
    """nostal_as_high=True 时回忆不降级"""
    content = "以前小时候也想要一个"
    base = _base(level="高", score=80)
    _apply_intent_downgrade(base, content, nostal_as_high=True)
    assert base["level"] == "高"
    assert base["score"] == 80


def test_nostalgia_does_not_affect_medium():
    """已经是"中"的回忆内容不应再降"""
    content = "以前小时候也想要一个"
    base = _base(level="中", score=30)
    _apply_intent_downgrade(base, content)
    assert base["level"] == "中"


# ---------- 讨论性内容(无强意向) ----------

def test_discussion_without_strong_intent_downgrades():
    """讨论性内容(无强意向)应从高降到中"""
    # 用一个讨论词但不命中强意向信号
    content = "大家觉得这个怎么样"
    assert any(p in content for p in DISCUSSION_PATTERNS)
    assert not any(s in content for s in STRONG_INTENT_SIGNALS)

    base = _base(level="高", score=70)
    _apply_intent_downgrade(base, content)
    assert base["level"] == "中"
    assert base["score"] <= 45
    assert "讨论" in base["reason"]


def test_strong_intent_overrides_discussion():
    """命中强意向信号时,讨论性内容不降级"""
    strong = STRONG_INTENT_SIGNALS[0]
    discussion = DISCUSSION_PATTERNS[0]
    content = f"{strong} {discussion}"
    base = _base(level="高", score=85)
    _apply_intent_downgrade(base, content)
    assert base["level"] == "高"
    assert base["score"] == 85


# ---------- 过去式购买 ----------

def test_past_purchase_without_strong_intent_downgrades():
    """过去式购买陈述(无强意向)应降级"""
    content = PAST_PURCHASE_PATTERNS[0] if PAST_PURCHASE_PATTERNS else "之前买过"
    assert any(p in content for p in PAST_PURCHASE_PATTERNS)
    # 确保不命中强意向
    if any(s in content for s in STRONG_INTENT_SIGNALS):
        pytest.skip("默认 past_purchase 词与强意向重叠,跳过")
    base = _base(level="高", score=75)
    _apply_intent_downgrade(base, content)
    assert base["level"] == "中"
    assert "过去式" in base["reason"] or "降级" in base["reason"]


# ---------- 长篇陈述 ----------

def test_long_narrative_downgrades():
    """长文本(>50字)+ 零星意向词 + 讨论标志 → 降级"""
    discussion = DISCUSSION_PATTERNS[0]
    # 构造 >50 字文本,只命中 1 个强意向词,且含讨论词
    strong = STRONG_INTENT_SIGNALS[0]
    content = (strong + " ") + "今天是不错的一天天气挺好我想出去走走看看风景顺便聊聊最近的生活和工作压力大家都在忙什么" + discussion + "顺便聊聊天"
    assert len(content) > 50
    base = _base(level="高", score=70)
    _apply_intent_downgrade(base, content)
    assert base["level"] == "中"
    assert base["score"] <= 45


def test_short_strong_intent_not_downgraded():
    """短文本命中强意向 → 不降级"""
    strong = STRONG_INTENT_SIGNALS[0]
    content = strong + "多少钱"
    base = _base(level="高", score=90)
    _apply_intent_downgrade(base, content)
    assert base["level"] == "高"


# ---------- 无任何降级标志 ----------

def test_pure_strong_intent_not_downgraded():
    """纯强意向、无回忆/讨论/过去式 → 不降级"""
    strong = STRONG_INTENT_SIGNALS[0]
    content = strong
    base = _base(level="高", score=95)
    _apply_intent_downgrade(base, content)
    assert base["level"] == "高"
    assert base["score"] == 95
    assert "降级" not in base["reason"]


def test_low_level_never_downgraded():
    """低意向不会被降级(本来就低)"""
    content = "以前小时候也想要一个大家觉得怎么样"
    base = _base(level="低", score=10)
    _apply_intent_downgrade(base, content)
    assert base["level"] == "低"
    assert base["score"] == 10
