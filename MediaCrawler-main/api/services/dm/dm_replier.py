# -*- coding: utf-8 -*-
"""
AI 私信回复器

对应 PRD 5.4 私信自动回复 - AI 自动回复 + 转人工触发（阶段四任务 4.1 增强）：
1. 意图识别：AI 分类私信意图（咨询/投诉/合作/闲聊/高价值）
2. 生成回复：结合营销素材库自然回复
3. 转人工触发：复杂问题/高价值客户/投诉升级
4. 多语言支持：海外平台英文回复
5. 跨平台回复：通过 Interactor.send_dm_reply 实际发送到对应平台

复用 MediaCrawler ai_agent_client + marketing 素材库。
"""

import logging
from typing import Optional

from .dm_models import DirectMessage, MessageIntent, ConversationState
from .dm_platform_capabilities import get_dm_platform_registry

logger = logging.getLogger(__name__)

# 转人工触发关键词
HUMAN_ESCALATION_KEYWORDS = [
    "投诉", "维权", "退款", "报警", "起诉", "律师", "曝光",
    "代理", "加盟", "批发", "大单", "团购", "企业采购",
    "complaint", "refund", "lawsuit", "lawyer", "scam",
]

# 高价值客户关键词
HIGH_VALUE_KEYWORDS = [
    "代理", "加盟", "批发", "团购", "企业", "采购",
    "大量", "长期合作", "经销商", "分销",
    "wholesale", "partnership", "reseller", "distributor", "bulk order",
    "agency", "business cooperation",
]

# 多语言默认回复
DEFAULT_REPLIES = {
    "high_value": {
        "zh": "您好！感谢您的关注，您咨询的合作事宜非常重要，已为您转接专属顾问，请稍候。",
        "en": "Hi! Thanks for reaching out. Your partnership inquiry is very important to us. A dedicated advisor will contact you shortly.",
    },
    "complaint": {
        "zh": "非常抱歉给您带来不便，您的反馈我们非常重视，已为您转接人工客服，将尽快为您处理。",
        "en": "We sincerely apologize for the inconvenience. Your feedback has been escalated to our support team and will be handled promptly.",
    },
    "fallback": {
        "zh": "感谢您的私信，已为您转接人工客服，请稍候。",
        "en": "Thanks for your message. Our support team will get back to you shortly.",
    },
    "error": {
        "zh": "感谢您的私信，客服将尽快回复您。",
        "en": "Thanks for your message. Our customer service will reply as soon as possible.",
    },
}


class DMReplier:
    """AI 私信回复器（多平台、多语言）"""

    async def classify_and_reply(self, dm: DirectMessage) -> DirectMessage:
        """识别意图并生成回复

        Returns:
            更新后的 DirectMessage（含 reply_text / needs_human / state）
        """
        text = dm.message_text or ""
        lang = self._detect_language(dm.platform, text)

        # 1. 规则预判：高价值/转人工关键词
        if any(kw in text.lower() for kw in HIGH_VALUE_KEYWORDS):
            dm.intent = MessageIntent.HIGH_VALUE.value
            dm.confidence = 0.9
            dm.needs_human = True
            dm.state = ConversationState.NEEDS_HUMAN.value
            dm.reply_text = DEFAULT_REPLIES["high_value"][lang]
            return dm

        if any(kw in text.lower() for kw in HUMAN_ESCALATION_KEYWORDS):
            dm.intent = MessageIntent.COMPLAINT.value
            dm.confidence = 0.85
            dm.needs_human = True
            dm.state = ConversationState.NEEDS_HUMAN.value
            dm.reply_text = DEFAULT_REPLIES["complaint"][lang]
            return dm

        # 2. AI 意图识别 + 回复生成
        try:
            intent, confidence = await self._classify_intent(text, lang)
            dm.intent = intent
            dm.confidence = confidence

            # 闲聊/简单咨询用 AI 回复
            if intent in (
                MessageIntent.CHAT.value,
                MessageIntent.INQUIRY.value,
                MessageIntent.COOPERATION.value,
            ):
                reply = await self._generate_reply(text, intent, dm.platform, lang)
                if reply:
                    dm.reply_text = reply
                    dm.is_replied = True
                    dm.state = ConversationState.REPLIED.value
                    return dm

            # 兜底转人工
            dm.needs_human = True
            dm.state = ConversationState.NEEDS_HUMAN.value
            dm.reply_text = DEFAULT_REPLIES["fallback"][lang]
        except Exception as e:
            logger.warning(f"[DMReplier] AI 回复失败，转人工: {e}")
            dm.needs_human = True
            dm.state = ConversationState.NEEDS_HUMAN.value
            dm.reply_text = DEFAULT_REPLIES["error"][lang]

        return dm

    # ==================== 跨平台实际回复 ====================

    async def reply_cross_platform(
        self, dm: DirectMessage, force: bool = False
    ) -> DirectMessage:
        """对已生成 reply_text 的私信，调用对应平台 Interactor 实际发送回复

        Args:
            dm: 必须已经过 classify_and_reply 流程
            force: 即使 needs_human=True 也强制发送（用于人工确认后）

        Returns:
            更新后的 dm（含实际发送结果）
        """
        if not dm.reply_text:
            return dm
        if dm.needs_human and not force:
            return dm  # 转人工的不自动发送
        if not dm.conversation_id:
            logger.warning(f"[DMReplier] 缺少 conversation_id，无法发送")
            return dm

        # 校验平台能力
        cap = get_dm_platform_registry().get(dm.platform)
        if cap is None or not cap.supports_reply:
            logger.info(f"[DMReplier] 平台 {dm.platform} 暂不支持回复")
            return dm

        try:
            from api.services.interactor.interactor_factory import InteractorFactory
            from api.services.publisher.account_service import get_account_service

            if not InteractorFactory.is_supported(dm.platform):
                logger.info(f"[DMReplier] 平台 {dm.platform} 暂无 Interactor 实现")
                return dm

            account = await get_account_service().acquire_cookie(dm.platform, user_id=1)
            if not account:
                logger.warning(f"[DMReplier] 平台 {dm.platform} 无可用账号")
                return dm

            interactor = InteractorFactory.create(
                dm.platform, cookies=account.cookies, user_id=1
            )
            if not await interactor._init_browser():
                await interactor._close_browser()
                return dm
            try:
                result = await interactor.send_dm_reply(
                    dm.conversation_id, dm.reply_text
                )
                if result.success:
                    dm.is_replied = True
                    dm.state = ConversationState.REPLIED.value
                    logger.info(
                        f"[DMReplier][{dm.platform}] 私信已实际回复: {dm.reply_text[:30]}"
                    )
                else:
                    dm.is_replied = False
                    logger.warning(
                        f"[DMReplier][{dm.platform}] 实际回复失败: {result.error}"
                    )
            finally:
                await interactor._close_browser()
        except Exception as e:
            logger.warning(f"[DMReplier] 跨平台回复失败: {e}")

        return dm

    # ==================== 内部方法 ====================

    def _detect_language(self, platform: str, text: str) -> str:
        """根据平台和文本判断语言"""
        cap = get_dm_platform_registry().get(platform)
        if cap and cap.region == "overseas":
            # 海外平台默认英文
            if any("\u4e00" <= ch <= "\u9fff" for ch in text):
                return "zh"
            return cap.default_language or "en"
        # 国内平台默认中文
        return "zh"

    async def _classify_intent(self, text: str, lang: str = "zh") -> tuple:
        """AI 意图分类

        Returns:
            (intent, confidence)
        """
        try:
            from api.services.ai_agent_client import get_ai_agent_client, is_ai_in_cooldown, is_ai_expected_error

            if is_ai_in_cooldown():
                logger.debug("[DMReplier] AI 服务冷却中，跳过意图识别")
                return (MessageIntent.UNKNOWN.value, 0.0)
            if lang == "en":
                prompt = (
                    "Classify the intent of the following user message. "
                    "Output only one label (no explanation):\n"
                    "- inquiry: asking about product/price/service\n"
                    "- complaint: complaint/dissatisfaction\n"
                    "- cooperation: business/cooperation\n"
                    "- chat: casual greeting\n\n"
                    f"Message: {text}\n\nLabel:"
                )
            else:
                prompt = (
                    "请判断以下用户私信的意图，只输出一个类别词（不加解释）：\n"
                    "- inquiry: 咨询产品/价格/服务\n"
                    "- complaint: 投诉/不满\n"
                    "- cooperation: 合作/商务\n"
                    "- chat: 闲聊/打招呼\n\n"
                    f"私信内容：{text}\n\n类别："
                )
            client = get_ai_agent_client()
            result = await client.generate_text(prompt)
            result = (result or "").strip().lower()
            valid = {
                "inquiry": MessageIntent.INQUIRY.value,
                "complaint": MessageIntent.COMPLAINT.value,
                "cooperation": MessageIntent.COOPERATION.value,
                "chat": MessageIntent.CHAT.value,
            }
            intent = valid.get(result, MessageIntent.UNKNOWN.value)
            return (intent, 0.7 if intent != MessageIntent.UNKNOWN.value else 0.3)
        except Exception as e:
            if is_ai_expected_error(e):
                logger.debug(f"[DMReplier] AI 预期内错误跳过意图识别: {e}")
            else:
                logger.warning(f"[DMReplier] 意图识别失败: {e}")
            return (MessageIntent.UNKNOWN.value, 0.0)

    async def _generate_reply(
        self, text: str, intent: str, platform: str, lang: str = "zh"
    ) -> Optional[str]:
        """AI 生成回复（结合营销素材库）"""
        try:
            from api.services.ai_agent_client import get_ai_agent_client, is_ai_in_cooldown, is_ai_expected_error
            from api.services.marketing.material_library import get_material_library

            if is_ai_in_cooldown():
                logger.debug("[DMReplier] AI 服务冷却中，跳过回复生成")
                return None
            # 获取营销素材
            library = get_material_library()
            slogans = await library.get_active_slogans()
            link = await library.get_active_link()

            marketing_info = ""
            if slogans:
                marketing_info += f"品牌口号参考: {slogans[0]}\n"
            if link:
                marketing_info += f"引流链接: {link}\n"

            if lang == "en":
                prompt = (
                    f"Someone sent me a DM on {platform} with intent '{intent}'.\n"
                    f"They said: {text}\n\n"
                    f"{marketing_info}"
                    "Generate a short, natural, friendly reply (within 50 words):\n"
                    "1. Address their intent directly\n"
                    "2. Optionally weave in the marketing info naturally\n"
                    "3. Output the reply text only, no explanation\n"
                )
            else:
                prompt = (
                    f"有人通过{platform}私信我，意图是「{intent}」。\n"
                    f"对方说：{text}\n\n"
                    f"{marketing_info}"
                    "请生成一条简短、自然、有人情味的回复（50字以内）：\n"
                    "1. 针对对方意图回应\n"
                    "2. 可适当植入引流信息但要自然\n"
                    "3. 直接输出回复内容，不要解释\n"
                )
            client = get_ai_agent_client()
            reply = await client.generate_text(prompt)
            return reply.strip() if reply else None
        except Exception as e:
            if is_ai_expected_error(e):
                logger.debug(f"[DMReplier] AI 预期内错误跳过回复生成: {e}")
            else:
                logger.warning(f"[DMReplier] 生成回复失败: {e}")
            return None


_replier: Optional[DMReplier] = None


def get_dm_replier() -> DMReplier:
    global _replier
    if _replier is None:
        _replier = DMReplier()
    return _replier
