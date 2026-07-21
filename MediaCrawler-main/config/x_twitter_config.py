# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/x_twitter_config.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1


import os

# Twitter/X platform configuration

# X.com cookies for authentication (from browser DevTools)
# 获取方式: 打开 x.com → F12 → Application → Cookies → 复制所有cookie
X_TWITTER_COOKIES = os.getenv("X_TWITTER_COOKIES", "")

# Search keywords for trending posts
X_TWITTER_KEYWORDS = os.getenv("X_TWITTER_KEYWORDS", "AI,技术,编程")

# Maximum number of trending posts to crawl
X_TWITTER_MAX_POSTS = int(os.getenv("X_TWITTER_MAX_POSTS", "20"))

# Maximum comments per post
X_TWITTER_MAX_COMMENTS = int(os.getenv("X_TWITTER_MAX_COMMENTS", "100"))

# Auto-comment configuration
X_TWITTER_AUTO_COMMENT_ENABLED = os.getenv("X_TWITTER_AUTO_COMMENT_ENABLED", "true").lower() == "true"

# Comment templates - randomly selected for each post
X_TWITTER_COMMENT_TEMPLATES = [
    "Great post! 👍 What are your thoughts on this?",
    "Interesting perspective! 😊",
    "This is really helpful, thanks for sharing! 🙏",
    "I completely agree with you! 💯",
    "Fascinating! Would love to hear more details!",
    "Well said! 💪",
    "Excellent points! 🎯",
    "Thanks for this valuable insight! ✨",
    "This resonates with me! 🙌",
    "Perfect timing, I was just thinking about this! 🤔",
]

# Auto-reply configuration
X_TWITTER_AUTO_REPLY_ENABLED = os.getenv("X_TWITTER_AUTO_REPLY_ENABLED", "true").lower() == "true"

# Reply check interval (seconds)
X_TWITTER_REPLY_CHECK_INTERVAL = int(os.getenv("X_TWITTER_REPLY_CHECK_INTERVAL", "120"))

# AI service configuration for generating replies
X_TWITTER_AI_REPLY_ENABLED = os.getenv("X_TWITTER_AI_REPLY_ENABLED", "true").lower() == "true"

# AI API configuration
X_TWITTER_AI_API_KEY = os.getenv("X_TWITTER_AI_API_KEY", "")
X_TWITTER_AI_BASE_URL = os.getenv("X_TWITTER_AI_BASE_URL", "https://api.openai.com/v1")
X_TWITTER_AI_MODEL = os.getenv("X_TWITTER_AI_MODEL", "gpt-3.5-turbo")

# Video breakdown configuration
X_TWITTER_VIDEO_BREAKDOWN_ENABLED = os.getenv("X_TWITTER_VIDEO_BREAKDOWN_ENABLED", "true").lower() == "true"

# Maximum concurrent tasks
X_TWITTER_MAX_CONCURRENCY = int(os.getenv("X_TWITTER_MAX_CONCURRENCY", "3"))

# ========== AI 回复策略增强配置 ==========

# 关键词匹配回复模板: 当评论内容包含关键词时，使用对应模板回复
# 格式: {"keywords": ["关键词1", "关键词2"], "replies": ["回复1", "回复2"], "priority": 1}
X_TWITTER_KEYWORD_REPLY_RULES = [
    {
        "keywords": ["问", "怎么", "如何", "how", "what", "why", "？", "?"],
        "replies": [
            "Great question! Here's my take: 😊",
            "好问题！我觉得可以这样看 👇",
            "Interesting question! Let me share my perspective.",
        ],
        "priority": 1,
    },
    {
        "keywords": ["赞", "好", "棒", "great", "awesome", "nice", "cool", "love", "喜欢"],
        "replies": [
            "Thank you! Glad you liked it! 🙏",
            "谢谢支持！会继续分享更多内容 💪",
            "Thanks for the love! ✨",
        ],
        "priority": 2,
    },
    {
        "keywords": ["不", "差", "坏", "bad", "terrible", "hate", "stupid", "烂"],
        "replies": [
            "I appreciate your honest feedback! Let's discuss further. 🤝",
            "谢谢你的反馈，会认真考虑改进的 🙏",
            "Sorry to hear that. Could you share more details?",
        ],
        "priority": 3,
    },
    {
        "keywords": ["链接", "link", "地址", "url", "where", "哪"],
        "replies": [
            "You can find it in the original post! Check the thread 📎",
            "链接在原帖中，可以查看完整内容 👆",
        ],
        "priority": 1,
    },
]

# AI 回复系统提示词 - 控制 AI 回复的风格和语气
X_TWITTER_AI_REPLY_SYSTEM_PROMPT = os.getenv(
    "X_TWITTER_AI_REPLY_SYSTEM_PROMPT",
    "你是一个活跃的社交媒体用户，擅长用轻松友好的语气回复评论。回复要求：1)友好积极 2)适当使用表情 3)1-2句话 4)自然口语化 5)避免广告感"
)

# 是否启用关键词匹配优先于 AI 回复
X_TWITTER_KEYWORD_MATCH_FIRST = os.getenv("X_TWITTER_KEYWORD_MATCH_FIRST", "true").lower() == "true"

# 回复频率限制: 同一用户每天最多回复次数
X_TWITTER_REPLY_DAILY_LIMIT = int(os.getenv("X_TWITTER_REPLY_DAILY_LIMIT", "10"))

# ========== 任务调度配置 ==========

# 是否启用定时爬取
X_TWITTER_SCHEDULED_CRAWL_ENABLED = os.getenv("X_TWITTER_SCHEDULED_CRAWL_ENABLED", "true").lower() == "true"

# 定时爬取间隔（分钟）
X_TWITTER_CRAWL_INTERVAL_MINUTES = int(os.getenv("X_TWITTER_CRAWL_INTERVAL_MINUTES", "60"))

# 定时爬取时间点（24小时制，逗号分隔，如 "09:00,12:00,18:00,21:00"）
X_TWITTER_CRAWL_SCHEDULE_TIMES = os.getenv("X_TWITTER_CRAWL_SCHEDULE_TIMES", "")

# ========== 批量操作配置 ==========

# 批量视频拆解每批最大数量
X_TWITTER_BATCH_BREAKDOWN_SIZE = int(os.getenv("X_TWITTER_BATCH_BREAKDOWN_SIZE", "5"))

# 批量评论每批最大数量
X_TWITTER_BATCH_COMMENT_SIZE = int(os.getenv("X_TWITTER_BATCH_COMMENT_SIZE", "3"))

# 批量操作间隔（秒）
X_TWITTER_BATCH_INTERVAL_SECONDS = int(os.getenv("X_TWITTER_BATCH_INTERVAL_SECONDS", "10"))
