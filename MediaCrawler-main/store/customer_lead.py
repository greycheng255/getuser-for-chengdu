# -*- coding: utf-8 -*-
"""
获客功能模块 - 识别和捕获潜在客户咨询
"""
import re
import time
import hashlib
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


# ============ 内容归一化与相似度去重工具 ============
# 用于识别同一用户在不同视频下复制粘贴的高度相似广告模板评论
# (如"Coco琵琶老师"发的多条首句不同、主体相同的推广文案)

# 匹配 [微笑] 这类表情占位符
_BRACKET_RE = re.compile(r'\[.*?\]')
# 匹配 unicode emoji(符号、表情、旗帜等)
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\U0001F900-\U0001F9FF"
    "]+", flags=re.UNICODE
)
# 非文字字符(只保留中英文、数字、下划线)
_NON_WORD_RE = re.compile(r'[^\w\u4e00-\u9fff]')

# 相似度阈值:归一化后 SequenceMatcher.ratio() >= 此值视为同一模板的重复评论
SIMILAR_CONTENT_THRESHOLD = 0.8


def normalize_content_for_dedup(content: str) -> str:
    """归一化内容用于去重比对。

    处理步骤:转小写 → 去表情占位符[xx] → 去 unicode emoji → 去标点/空白(只留中英文+数字)。
    例如 "用最少的钱爆改自己、去学琵琶。🔥不管你是..." 与
         "逼自己看完10页纸，你的琵琶会很牛。🔥不管你是..." 归一化后主体高度相似。
    """
    if not content:
        return ""
    s = str(content).lower()
    s = _BRACKET_RE.sub('', s)
    s = _EMOJI_RE.sub('', s)
    s = _NON_WORD_RE.sub('', s)
    return s


def content_fingerprint(content: str) -> str:
    """计算归一化内容的 md5 指纹(用于精确去重的快速命中)。"""
    norm = normalize_content_for_dedup(content)
    if not norm:
        return ""
    return hashlib.md5(norm.encode('utf-8')).hexdigest()


def is_similar_content(a: str, b: str, threshold: float = SIMILAR_CONTENT_THRESHOLD) -> bool:
    """判断两段内容(归一化后)是否高度相似。

    用于识别同一用户发的广告模板评论(首句可能不同,主体相同)。
    先做精确匹配与长度粗筛,再用 SequenceMatcher 计算相似度,避免无谓计算。
    """
    na = normalize_content_for_dedup(a)
    nb = normalize_content_for_dedup(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    la, lb = len(na), len(nb)
    # 长度差异超过 30% 直接判不相似
    if min(la, lb) / max(la, lb) < 0.7:
        return False
    ratio = SequenceMatcher(None, na, nb).ratio()
    return ratio >= threshold


@dataclass
class LeadMatchResult:
    """匹配结果"""
    is_lead: bool
    matched_keywords: List[str]
    intent_type: str
    lead_score: int
    # 新增:意向等级(high/medium/low/none),用于精准判定
    intent_level: str = "none"
    # 新增:匹配模式(strict_double/legacy_inquiry/llm),用于调试
    match_mode: str = ""
    # 新增:角色标签(supplier供方/consumer求方/neutral中性),由 classify_role 得出
    role_tag: str = "neutral"


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

    # ============ 供方/求方角色分类信号词(行业无关,分级阈值) ============
    # 信号词按强度分三级,不同级别用不同阈值:
    #   S级: 命中1个即判定为供方(这些词几乎只出现在服务商/厂家广告中)
    #   A级: 命中2个判定为供方(可能被普通用户使用,需叠加确认); 1个A级+1个B级也判定
    #   B级: 辅助信号,单独不判定,需配合A级命中
    #
    # 求方信号:命中1个即判定(但会检查否定模式,避免"不需要"匹配"需要"等误判)
    #
    # 配合任务 target_role 使用:
    #   target_role=c端用户 → 排除 supplier(服务商广告)
    #   target_role=厂家供应商/不限 → 全部保留并打标,前端筛选

    # S级供方信号:命中1个即判定为供方(极强的供方特征,几乎不会误伤)
    SUPPLIER_SIGNALS_S = [
        # 代xx服务(极强的供方信号,普通用户几乎不会用)
        '代优化', '代运营', '代办', '代做', '代写', '代发', '代注册', '代认证',
        '代开户', '代投', '代跑', '代发布', '代更新', '代管理', '代维护', '代建',
        # 工具/系统售卖
        '卖工具', '卖系统', '工具系统', '卖软件', '系统出售', '出售系统',
        # 招商/代理(极强的供方信号)
        '招代理', '招商', '加盟', '诚招',
        # 厂家直销(极强的供方信号)
        '源头厂家', '厂家直销', '厂家直供', '一手资源', '直供',
        # 接单引导(极强的供方信号)
        '全国可做', '可接单', '接单中',
        # 供方软文强信号(几乎只出现在服务商广告中)
        '全行业案例', '保障排名',
    ]

    # A级供方信号:命中2个判定为供方(单独1个可能被普通用户使用,需叠加确认)
    SUPPLIER_SIGNALS_A = [
        # 自称机构/团队
        '我们公司', '我们团队', '我们机构', '我们工作室', '我们厂', '我们平台', '我们这边', '我公司',
        # 引导联系
        '找我们', '联系我', '私信我', '加我微信', '加我v', '加微信', '戳我',
        '滴滴我', '后台私信', '主页联系', '可以私', '可以找我',
        # 销售话术
        '免费咨询', '限时优惠', '名额有限', '先到先得',
        '欢迎咨询', '欢迎合作',
        # 自我标榜
        '专业团队', '专注多年', '经验丰富', '实力商家',
        # 案例展示/服务承诺
        '全程跟进', '一对一服务', '手把手带', '有案例', '案例库',
        '保驾护航', '包教包会', '包满意',
        # 公司标榜
        '头部企业', '上市公司', '正规集团', '正规公司',
        # 其他引导
        '加个微信', '加个联系方式', '加个v', '价格私信',
        '免费发资料', '免费介绍', '营销顾问',
        # 供方软文引导/案例分享
        '可以留言', '我客户',
        # ★供方引流/广告话术(普通C端用户几乎不会用)
        # "想要方案直接私我""想要一周上榜吗？这个我可以"——供方推销/接单引导
        '直接私我', '私我联系', '这个我可以', '一周上榜', '一夜暴富',
        # ★供方经验自述/专家人设(普通C端用户几乎不会用这类"过来人/导师"口吻)
        # "做GEO优化这么久,最欣慰的是...""很多创业者问我...我都会推荐GEO优化"
        # 命中2个即判供方,可精准识别伪装成讨论的供方软文
        '最欣慰', '很多创业者问我', '我都会推荐', '稳定变现', '摆脱了获客',
        '靠这套方法', '做优化这么久', '获客需求一直都在', '最欣慰的是',
        '看到越来越多', '靠这套', '这套方法', '摆脱获客',
    ]

    # B级供方信号:辅助信号,单独不判定,需配合至少1个A级命中
    SUPPLIER_SIGNALS_B = [
        '自有网站', '官方授权', '自研', '自己研发',
        '汇报工作进度', '全透明运作', '透明运作',
        '在线销售', '背调',
    ]

    # 代x服务词(从 SUPPLIER_SIGNALS_S 抽取):这类词在求方"问价/求购问句"语境下
    # 是消费者询问代办服务(如"代办需要多少费用？""可以代办吗？"),而非供方推销。
    # classify_role 会对代x服务词做问价上下文检测,避免"代xx+问句"误判供方。
    _AGENT_SERVICE_WORDS = frozenset({
        '代优化', '代运营', '代办', '代做', '代写', '代发', '代注册', '代认证',
        '代开户', '代投', '代跑', '代发布', '代更新', '代管理', '代维护', '代建',
    })
    # 问价/求购问句信号(与代x服务词共现=求方询问代办服务)
    # 注意:不含单独"收费/价格"子串,避免"收费便宜/价格优惠"等供方推销误判
    _PRICE_INQUIRY_SIGNALS = frozenset({
        '多少钱', '多少费用', '如何收费', '怎么收费', '收费多少', '费用多少',
        '需要多少', '要多少', '价格多少', '价钱', '收费吗', '怎么算',
    })
    # 供方引流引导词(代x问价求购时的否决:含这些词仍判供方,如"代办多少钱 联系我")
    _SUPPLIER_GUIDE_WORDS = frozenset({
        '联系我', '私信我', '加我微信', '加我v', '加微信', '戳我', '滴滴我',
        '后台私信', '主页联系', '可以私', '可以找我', '找我们', '加个微信',
        '加个联系方式', '加个v', '价格私信', '直接私我', '私我联系', '免费咨询',
    })

    # 求方信号词:命中1个即判定为求方(C端咨询求购)
    CONSUMER_SIGNALS = [
        # 咨询/求购(核心)
        '哪里有', '哪里可以', '哪里能', '怎么找', '怎么买', '哪里买',
        '去哪买', '去哪学', '去哪找',
        '求推荐', '求分享', '求告知', '请问', '谁知道',
        '有没有', '有吗', '能推荐吗', '可以推荐吗',
        # 意向表达
        '想学', '想买', '想要', '需要', '急需', '想了解',
        '想注册', '想申请', '想办理', '想做', '想搞',
        '想咨询', '咨询下', '咨询一下', '咨询',
        '求助', '求', '推荐',
        # 比价/选择
        '哪个好', '哪家好', '怎么选', '对比', '区别',
        '怎么样', '好用吗', '值得买吗', '靠谱吗',
        # 求链接/入口/联系方式
        '求链接', '求网址', '求入口', '怎么联系', '如何联系',
        '留个联系方式', '留个联系', '留联系方式',
        # 价格咨询
        '多少钱', '价格', '收费', '付费',
        # 求带/求教
        '求带', '带带我', '带带我吧',
        # 报名/参加/注册/申请(通用办事咨询)
        '怎么报名', '怎么参加', '怎么注册', '怎么申请', '怎么办理',
        '怎么弄', '怎么搞',
        # 新手咨询
        '新手适合吗', '零基础能学吗', '零基础',
    ]

    # 求方信号否定模式:这些模式出现时,对应的求方信号不算命中
    # 避免"不需要"匹配"需要"、"不想买"匹配"想买"等否定语境误判。
    # ★"推荐"是最高频误伤词:供方软文/科普/质疑里大量出现"被推荐/我都会推荐/
    #   推荐品牌/推荐的都是/ai推荐"等非咨询用法,需全面覆盖(含带问号的长文案场景)。
    _CONSUMER_NEGATIVE_MAP = {
        '需要': [
            '不需要', '不需', '没需要', '无需要', '被需要', '需要的话', '有需要',
            '获客需求', '商家的获客需求',
            # 供方引流:"需要老板的联系""需要客户联系"是供方在找客户,不是客户在找服务
            '需要老板', '需要客户', '需要联系', '需要老板联系', '需要客户联系',
        ],
        '想要': ['不想要', '不想'],
        '想买': ['不想买'],
        '想学': ['不想学'],
        '求': ['不求', '不要求', '不求助', '需求', '谋求', '诉求'],
        # "推荐"否定模式:覆盖供方/中性非咨询语境(被推荐/自荐推荐/描述推荐/质疑推荐)
        '推荐': [
            '不推荐', '没推荐', '不会推荐', '推荐给', '帮忙推荐', '可以推荐给',
            # 被动/客观描述(非求方主动咨询)
            '被推荐', '被ai推荐', 'ai推荐', '豆包推荐', '主动推荐', '推荐结果', '推荐方案',
            # 供方自荐/推销("我都会推荐X"是供方在推荐别人,非求方咨询)
            '我会推荐', '我都会推荐', '推荐我们', '推荐学生', '推荐别人',
            '推荐你', '推荐品牌', '推荐的都是', '推荐完再问',
            # 质疑/吐槽推荐机制("推荐的都是花钱的""推荐？你怕是要被操控"是吐槽,非咨询)
            '推荐的都是', '推荐谁家', '推荐哪家有', '推荐？',
        ],
        '有吗': ['没有吗'],
        # "有没有"在销售话术/同行交流里误伤:"有没有时间"是话术示例,"有没有老板交流"是同行找交流
        '有没有': ['有没有时间', '有没有老板'],
        # "价格"在讨论/吐槽里误伤:"价格战""打价格战""性价比"等是讨论,非求方咨询
        '价格': ['无价格', '没价格', '价格战', '打价格战', '性价比', '伤人伤己'],
        # "多少钱"在供方自述/吐槽里误伤:"赚了多少钱/花了多少钱"是供方谈收益,"骗他多少钱"是吐槽被骗
        '多少钱': ['赚了多少钱', '花了多少钱', '多少钱赚', '多少钱能赚', '多少钱能搞',
                  '骗他多少钱', '骗多少钱', '骗多少', '被骗多少钱'],
        # "想要"在广告话术里误伤:"想要一夜暴富/想要一周上榜"是供方广告,非求方意向
        # 注:"想要方案直接私我"由供方信号"直接私我"判定,此处不否定"想要方案"以免误伤真求方
        '想要': ['不想要', '不想', '想要一夜', '想要一周'],
        '想了解': ['想了解的朋友', '想了解的可以', '想了解的'],
        # "怎么做"在讨论/吐槽里误伤:"怎么做出来的"是讨论现象,非求方咨询
        '怎么做': ['怎么做出来', '怎么做的出来', '怎么做到的'],
    }

    # ============ 结构化信号(零成本正则匹配,不需要LLM) ============
    # 联系方式正则:评论中留联系方式 → 极强供方信号(服务商引流)
    # 手机号(前后不能是数字,避免匹配@用户ID中的子串) | 微信号 | QQ号
    _PHONE_RE = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')
    _WECHAT_RE = re.compile(r'加我[vv x]|微信\s*[:：]?\s*[a-zA-Z0-9_]{4,}|[vx]\s*[:：]\s*[a-zA-Z0-9_]{4,}|微信号\s*[:：]?\s*\S')
    _QQ_RE = re.compile(r'[Qq][Qq]\s*[:：]?\s*\d{5,}')

    # 长文案推广词:>100字 + 推广用语 → 供方(广告文案通常较长且含推广话术)
    _PROMO_KEYWORDS = ['帮您', '帮你', '为您', '帮你们', '提供', '承接', '专业做', '专注于']
    _PROMO_MIN_LENGTH = 100

    # 供方科普术语:长文案中出现这些词 → 供方专家人设(普通C端用户几乎不会用)
    _SUPPLIER_SCREENCEST_TERMS = [
        '底层逻辑', '核心区别', '行业趋势', '数字基建', '流量入口',
        '生成式引擎', '不可逆的趋势', '增量流量',
    ]
    _SCREENCEST_MIN_LENGTH = 40

    # 额外问句求方信号(问号 + 咨询语境,补充CONSUMER_SIGNALS未覆盖的)
    _QUESTION_CONSUMER_PATTERNS = [
        '能不能', '行不行', '有没有人', '有人吗', '请问一下',
        '可以吗', '行吗', '好吗', '有没有人知道',
        '能不能教', '能不能带', '可不可以',
    ]

    # @用户名正则:剥离@后面的非空白字符片段(用户名可含中文/英文/emoji/符号)
    # 抖音/小红书评论里 @用户名 是社交@行为,如"@落雨.（求推荐）"里的"求推荐"
    # 是@行为的一部分,不是真实的求方咨询,剥离后可避免误判。
    _MENTION_RE = re.compile(r'@\S+')

    # 引用/质疑/否定语境信号词:评论里出现这些词时,即使命中"源头厂家""我们公司"
    # 等供方信号,也更可能是在"引用/吐槽"供方,而非自报供方。此时跳过 S/A/B 级
    # 供方判定,避免误判。
    # 例如:"能打击掉源头厂家才是真的"——命中"源头厂家"但在质疑语境,应判 neutral
    # 注意:单字"骗/坑"太宽泛(骗流量/坑位),只保留复合词
    _QUOTE_CONTEXT_SIGNALS = [
        '能打击', '才是真的', '才是真正', '假的', '别信', '不可信', '不可靠',
        '骗子', '坑人', '太差', '垃圾', '真不行', '不要去', '别去',
        '都是骗', '都是坑', '都是假', '忽悠', '之前被骗', '被骗了',
        '上过当', '踩过坑', '智商税',
    ]

    # 白名单短评论保护阈值:<此字数的评论跳过 A/B 级供方判定
    # 短评论无法承载完整供方广告,单个A级词(如"我们公司"出现在5字吐槽里)可能是误伤
    _SHORT_TEXT_THRESHOLD = 10
    
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
    def _has_consumer_signal(cls, full_text: str) -> bool:
        """检查求方信号,处理否定语境误判。

        "不需要"不应匹配"需要"、"不想买"不应匹配"想买"。
        对每个命中的信号词,检查是否存在对应的否定模式。

        ★长文案分级否决机制(行业无关,核心防误判策略):
        1. 长文案(>=60字,不管有无问号):供方科普/吐槽/经验分享常带反问句
           (如"能不能支撑优势""有没有持续回答"),弱信号(推荐/有没有/需要)和
           模糊问句(能不能/行吗)在此高度误伤,只认强信号+明确求方问句。
        2. 中文案(>=30字)+无问号:供方软文特征,同样只认强信号。
        3. 短文案(<30字)或中文案有问号:全部信号有效(真求方通常是短评论+问句)。

        真正的求方评论通常是短评论+问句(如"怎么联系""多少钱""请问哪里买"),
        或长文案里仍带明确强信号(如"老师你好请问...怎么做好GEO...求教")。
        """
        # 中文案+无问号:供方软文特征,弱信号需强确认
        is_long_no_question = (
            len(full_text) >= 30
            and '?' not in full_text
            and '？' not in full_text
        )
        # 长文案(>=60字,不管有无问号):供方科普/吐槽常带反问句,弱信号高度误伤
        is_long_text = len(full_text) >= 60
        # 超长文案(>=150字):讨论/歌词/经验分享/答题语境,"请问/谁知道/有没有人"
        # 等在此高度误伤(如178字歌词"谁知道"、282字讨论"请问"),真求方极少超150字,
        # 只认极强联系/求购信号。
        is_very_long_text = len(full_text) >= 150
        # 强求方信号词(明确咨询/求购,几乎不会误伤)
        _STRONG_CONSUMER_SIGNALS = {
            '请问', '谁知道', '怎么联系', '如何联系',
            '哪里买', '怎么买', '去哪买', '去哪学',
            '多少钱', '求推荐', '求链接', '求带',
        }
        # 超长文案极强信号(排除"请问/谁知道"——在讨论/文学里误伤,保留明确求购/联系意向)
        _VERY_STRONG_CONSUMER_SIGNALS = {
            '怎么联系', '如何联系', '求带', '求推荐', '求链接',
            '多少钱', '哪里买', '怎么买', '去哪买', '去哪学',
        }
        # 明确求方问句(区别于"能不能/行吗/可以吗"等可作反问的模糊问句)
        _STRONG_QUESTION_SIGNALS = {
            '有没有人', '有人吗', '请问一下', '有没有人知道',
            '能不能教', '能不能带', '可不可以',
        }
        # 超长文案极强问句(只认明确求教,否决"有没有人/可不可以"等讨论/答题用法)
        _VERY_STRONG_QUESTION_SIGNALS = {'能不能教', '能不能带'}

        for sig in cls.CONSUMER_SIGNALS:
            if sig in full_text:
                # 检查否定模式:如果文本包含否定词,该信号不算命中
                negatives = cls._CONSUMER_NEGATIVE_MAP.get(sig)
                if negatives and any(neg in full_text for neg in negatives):
                    continue
                # 中文案+无问号:只认强求方信号词,跳过"推荐""有没有""需要"等弱信号
                if is_long_no_question and sig not in _STRONG_CONSUMER_SIGNALS:
                    continue
                # 长文案(>=60字):只认强信号(覆盖带反问句的供方科普/吐槽)
                if is_long_text and sig not in _STRONG_CONSUMER_SIGNALS:
                    continue
                # 超长文案(>=150字):只认极强信号(否决"请问/谁知道"在讨论/文学里误伤)
                if is_very_long_text and sig not in _VERY_STRONG_CONSUMER_SIGNALS:
                    continue
                return True
        # 问句求方信号:长文案时只认明确求方问句,避免"能不能支撑优势"等反问误判
        for pat in cls._QUESTION_CONSUMER_PATTERNS:
            if pat in full_text:
                if is_long_text and pat not in _STRONG_QUESTION_SIGNALS:
                    continue
                # 超长文案:只认极强求教问句(否决"有没有人/可不可以"在答题/分享里误伤)
                if is_very_long_text and pat not in _VERY_STRONG_QUESTION_SIGNALS:
                    continue
                return True
        return False

    @classmethod
    def _is_agent_service_inquiry(cls, text: str) -> bool:
        """检测"代x服务词 + 问价/求购问句"模式(求方询问代办服务)。

        修复"代xx+问句"边界误判:求方询问代办服务价格/能否代办时
        (如"郑州代理记账代办需要多少费用？""武汉财务处理代办如何收费"
        "郑州代理记账可以代办吗？"),"代办"等代x词是S级供方词会误判供方。
        这里识别求方问价/求购问句语境。

        判定:含问价词 OR 含"能/可以...代x...吗"求购问句。
        注意:不含单独"收费/价格"子串,避免"收费便宜/价格优惠"供方推销误判。
        """
        # 问价词共现(多少钱/如何收费/需要多少费用等明确问价)
        for sig in cls._PRICE_INQUIRY_SIGNALS:
            if sig in text:
                return True
        # 求购问句:"能/可以/能不能/可不可以 ... 代办/代做 ... 吗"
        if re.search(r'(能|可以|能不能|可不可以|能不|可不).{0,6}代(办|做|写|发|注册|认证|开户|投|跑|发布|更新|管理|维护|建|优化|运营).{0,4}吗', text):
            return True
        return False

    @classmethod
    def _has_supplier_guide(cls, text: str) -> bool:
        """检测供方引流引导词(联系我/私信我/加微信等)。

        代x问价求购否决用:含这些词说明是供方引流(如"代办多少钱 联系我"),
        即使带问价词也判供方,避免供方用问价话术伪装求方。
        """
        for w in cls._SUPPLIER_GUIDE_WORDS:
            if w in text:
                return True
        return False

    @classmethod
    def _has_contact_info(cls, full_text: str) -> bool:
        """检测评论中是否包含联系方式(手机号/微信号/QQ号)。

        在评论里留联系方式是极强的供方(服务商)引流信号,
        普通C端用户几乎不会在评论里留自己的手机号/微信号。
        """
        if cls._PHONE_RE.search(full_text):
            return True
        if cls._WECHAT_RE.search(full_text):
            return True
        if cls._QQ_RE.search(full_text):
            return True
        return False

    @classmethod
    def _is_promo_text(cls, full_text: str) -> bool:
        """检测长文案推广(>100字 + 推广用语)。

        服务商广告通常篇幅较长(详细介绍服务+案例+引导),
        且包含"帮您/为你/提供/承接"等推广话术。
        """
        if len(full_text) < cls._PROMO_MIN_LENGTH:
            return False
        for kw in cls._PROMO_KEYWORDS:
            if kw in full_text:
                return True
        return False

    @classmethod
    def _is_supplier_screencast(cls, full_text: str) -> bool:
        """检测供方科普软文(长文案 + 行业科普术语)。

        供方专家人设的典型用语,如"底层逻辑/核心区别/数字基建/流量入口"等,
        普通C端用户几乎不会在评论里用这些词。长文案+科普术语=供方软文。
        """
        for term in cls._SUPPLIER_SCREENCEST_TERMS:
            if term in full_text:
                return True
        return False

    # 视频内容评论/吐槽信号:评论者在评论视频作者/内容,而非表达自己的需求
    # 例如:"不知道作者为什么会把这样的价格放在平台上""都在打价格战吗"
    _VIDEO_CRITIQUE_SIGNALS = [
        '不知道作者', '作者为什么', '作者怎么', '作者是不是',
        '伤人伤己', '害人害己', '打价格战', '价格战',
        '套路', '坑', '割韭菜', '智商税',
    ]

    # 供方寻找客户引流信号:供方说"需要老板联系""需要客户"是在找客户,不是客户在找服务
    # 例如:"公司注销400元～～又需要老板的联系喔"
    _SUPPLIER_CUSTOMER_SEEKING_PATTERNS = [
        r'需要.{0,4}(老板|客户|客户联系|老板联系)',
        r'(老板|客户).{0,4}(联系|咨询|合作)',
    ]

    @classmethod
    def _is_supplier_seeking_customer(cls, full_text: str) -> bool:
        """检测"供方寻找客户"的引流模式。

        供方在评论中说"需要老板的联系""需要客户联系"等,
        是在主动寻找客户,而非客户在寻找服务,应判定为 supplier。

        示例:
        - "公司注销400元～～又需要老板的联系喔" → 供方在找客户
        - "专业代账,有需要的老板联系" → 供方引流
        """
        for pat in cls._SUPPLIER_CUSTOMER_SEEKING_PATTERNS:
            if re.search(pat, full_text):
                return True
        return False

    @classmethod
    def _is_video_comment_critique(cls, full_text: str) -> bool:
        """检测评论是否是在吐槽/评论视频内容,而非表达自己的需求。

        评论者在评论视频作者/内容时,即使命中"价格""怎么做"等词,
        也不是真实的求方需求,应判定为 neutral。

        示例:
        - "不知道作者为什么会把这样的价格放在平台上,伤人伤己" → 吐槽视频
        - "都在打价格战吗?这么低怎么做出来的" → 讨论行业
        """
        for sig in cls._VIDEO_CRITIQUE_SIGNALS:
            if sig in full_text:
                return True
        return False

    @classmethod
    def _strip_mentions(cls, full_text: str) -> str:
        """剥离 @用户名 片段,避免 @ 拉人文本里的词触发求方/供方信号。

        抖音/小红书评论里 @用户名 是社交 @ 行为,如 "@落雨.（求推荐）" 里的
        "求推荐" 是 @ 行为的一部分,不是真实求方咨询;又如 "@某某源头厂家"
        里的 "源头厂家" 也非自报供方。剥离后用 cleaned_text 做后续判定。
        """
        return cls._MENTION_RE.sub(' ', full_text)

    @classmethod
    def _is_quoting_context(cls, full_text: str) -> bool:
        """检测评论是否处于"引用/质疑/否定"供方词的语境。

        评论里出现质疑/否定/被骗等词时,即使命中 "源头厂家" "我们公司" 等
        供方信号,也更可能是在 "引用/吐槽" 供方,而非自报供方。此时应跳过
        S/A/B 级供方判定,避免误判。

        例如:"能打击掉源头厂家才是真的"——命中"源头厂家"但在质疑语境,应判 neutral
        """
        for sig in cls._QUOTE_CONTEXT_SIGNALS:
            if sig in full_text:
                return True
        return False

    @classmethod
    def classify_role(cls, full_text: str, task_keywords: List[str] = None) -> str:
        """通过行业无关的行为信号分析评论,判定供方/求方/中性角色。

        不依赖具体行业热词(避免每个行业都要预先配置排除词),而是看评论本身的
        "行为方向":是自报机构+推销服务(供方),还是咨询求购(求方)。

        分级判定规则(由强到弱):
        0. 联系方式(手机/微信/QQ) → "supplier"
           (评论里留联系方式=服务商引流,极强的供方信号,任何语境下都判供方)
        --- 以下使用 cleaned_text(剥离 @用户名 后的文本) ---
        1. 引用语境检测:出现质疑/否定/被骗词 → 跳过 S/A/B 级供方判定
           (避免"能打击掉源头厂家才是真的"误判为供方)
        2. S级供方信号命中1个 → "supplier"
           (代优化/源头厂家/招商加盟等,这些词几乎只出现在服务商广告中)
        3. A级供方信号命中2个 → "supplier"
           (我们公司+联系我/私信我+有案例等,需叠加确认)
        4. A级1个 + B级1个 → "supplier"
           (A级弱命中+B级辅助确认)
           ★ 极短评论(<10字)跳过 3/4 步:短评论无法承载完整供方广告,
             单个A级词(如"我们公司"出现在5字吐槽里)可能是误伤
        5. 长文案(>100字)+推广词 → "supplier"
           (帮您/为你/提供/承接等推广话术+长文案=广告)
        6. 求方信号命中1个(排除否定语境 + 问句模式) → "consumer"
        7. 以上都不满足 → "neutral"

        配合任务 target_role 使用:
        - target_role=c端用户 + role=supplier → 排除(不写入线索)
        - target_role=厂家供应商/不限 → 全部保留,role_tag 供前端筛选

        Args:
            full_text: 已 lower() 的完整文本(标题+评论)

        Returns:
            "supplier" | "consumer" | "neutral"
        """
        # 0. 联系方式检测(最强供方信号:服务商引流)
        #    联系方式是极强信号,任何语境下都判供方(无需剥离@或检查引用语境)
        if cls._has_contact_info(full_text):
            return "supplier"

        # 0.5 视频内容评论/吐槽检测:评论者在评论视频作者/内容,而非表达需求
        #    例如:"不知道作者为什么会把这样的价格放在平台上""都在打价格战吗"
        #    这类评论即使命中"价格""怎么做"等词,也不是真实求方需求
        if cls._is_video_comment_critique(full_text):
            return "neutral"

        # 0.6 供方寻找客户引流检测:供方在主动找客户,而非客户在找服务
        #    例如:"公司注销400元～～又需要老板的联系喔"
        #    这类评论应判定为 supplier(供方引流)
        if cls._is_supplier_seeking_customer(full_text):
            return "supplier"

        # 剥离 @用户名 片段,避免 @ 拉人文本里的词触发求方/供方信号
        # 例如 "@落雨.（求推荐）" 里的 "求推荐" 不是真实求方咨询
        cleaned_text = cls._strip_mentions(full_text)

        # 1. 引用语境检测:出现质疑/否定/被骗词 → 跳过 S/A/B 级供方判定
        #    (但联系方式和长文案仍生效,因为它们是更强的独立信号)
        is_quoting = cls._is_quoting_context(cleaned_text)

        # 2. S级供方信号:命中1个即判定(引用语境下跳过,避免"能打击掉源头厂家"误判)
        #   ★代x服务词(代办/代做/代写等)结合任务上下文判定(不一刀切):
        #     - 代账任务"代办需要多少费用"(问价+与任务相关) → 求方(客户问价)
        #     - GEO任务"代办geo"(陈述提供,无问价) → 厂家(同行服务商自述)
        #     - 代x问价但与任务无关 → 维持供方(无关问价不误判,体现"结合任务出发点")
        if not is_quoting:
            hit_agent_service = False   # 仅命中代x服务词
            hit_other_s = False         # 命中非代x的S级词(几乎只在供方广告出现)
            for sig in cls.SUPPLIER_SIGNALS_S:
                if sig in cleaned_text:
                    if sig in cls._AGENT_SERVICE_WORDS:
                        hit_agent_service = True
                    else:
                        hit_other_s = True
            # 命中非代x的S级词 → 供方(源头厂家/招商加盟/全国可做等强供方信号)
            if hit_other_s:
                return "supplier"
            # 仅命中代x服务词:按"问价求购 vs 陈述提供"行为信号判定 role_tag(评论者客观角色,
            #   行业无关)。任务出发点通过 detect 层的 task_related 过滤 + target_role 保留/排除
            #   起作用(不一刀切,见"角色判定全局原则"):
            #   - 代x+问价/求购问句 → 求方(问价=求购本质,如"代办需要多少费用""代办如何收费")
            #   - 代x无问价(陈述提供) → 厂家(同行服务商自述,如"代办geo")
            #   - 代x+供方引流词 → 厂家(引流否决,供方伪装问价)
            # 注:role_tag 是评论者客观属性,不随任务变。曾尝试"任务相关性兜底"(代x问价须与
            #   task_keywords 词交集才判求方),但 core_terms 提取词与评论用词常不重叠(如
            #   "做geo的用户"vs"geo"、"代理记账"vs"财务处理"),纯规则词交集无法处理同义/相关
            #   服务,会误伤真实求方,故取消。改为"classify_role 宽松判 + detect.task_related
            #   过滤无关评论"的多层机制,既避免同义词误伤又过滤无关问价,体现结合任务出发点。
            if hit_agent_service:
                if cls._has_supplier_guide(cleaned_text):
                    return "supplier"  # 引流否决
                if cls._is_agent_service_inquiry(cleaned_text):
                    return "consumer"  # 代x+问价/求购问句→求方(客户问价)
                return "supplier"  # 代x无问价(陈述提供)→厂家(同行服务商)

        # 3-4. A级/B级供方信号:
        #   - 引用语境下跳过(避免"我们公司之前被骗"误判)
        #   - 极短评论(<10字)跳过:短评论无法承载完整供方广告,
        #     单个A级词可能是吐槽里的误伤(白名单短评论保护)
        #   - 正常情况:A级2个判供方,A级1+B级1判供方,A级1+长文案判供方
        a_hits = 0  # 提到外面,供后续求方否决用
        if not is_quoting and len(cleaned_text) >= cls._SHORT_TEXT_THRESHOLD:
            for sig in cls.SUPPLIER_SIGNALS_A:
                if sig in cleaned_text:
                    a_hits += 1

            # A级命中2个 → 判定供方
            if a_hits >= 2:
                return "supplier"

            # A级1个 + B级1个 → 判定供方
            if a_hits >= 1:
                for sig in cls.SUPPLIER_SIGNALS_B:
                    if sig in cleaned_text:
                        return "supplier"

            # ★A级1个 + 长文案(>25字) → 判定供方
            #   供方软文通常篇幅长+自报机构/引导联系,单个A级词在长文案里足以确认供方
            if a_hits >= 1 and len(cleaned_text) >= 25:
                return "supplier"

        # ★供方科普软文检测:长文案(>60字) + 行业科普术语 → 供方
        #   供方专家人设的典型用语(底层逻辑/数字基建等),普通C端用户几乎不会用
        if not is_quoting and len(cleaned_text) >= cls._SCREENCEST_MIN_LENGTH:
            if cls._is_supplier_screencast(cleaned_text):
                return "supplier"

        # 5. 长文案+推广词 → 判定供方(>100字自然不受短评论保护影响)
        if cls._is_promo_text(cleaned_text):
            return "supplier"

        # 6. 求方信号(处理否定语境 + 问句模式)
        #    ★命中A级供方信号时否决求方:供方软文里的"有没有/需要"不算求方
        if a_hits == 0 and cls._has_consumer_signal(cleaned_text):
            return "consumer"

        # 7. 中性
        return "neutral"

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
    def detect(
        cls,
        content: str,
        title: str = "",
        task_keywords: List[str] = None,
        intent_keywords: List[str] = None,
        exclude_keywords: List[str] = None,
        business_intent: str = "",
        target_role: str = "不限"
    ) -> LeadMatchResult:
        """
        检测内容是否包含潜在客户咨询(精准模式)

        匹配策略(优先级从高到低):
        1. 排除词过滤:命中任一排除词 → 直接返回非线索
        2. 供方/求方角色分类:基于行业无关的行为信号判定 role_tag
           - target_role=c端用户 + role=supplier(服务商广告) → 排除
           - target_role=厂家供应商/不限 → 保留并打标
        3. 严格双词命中(推荐):评论必须同时包含[业务词]和[意向词]才算线索
           - 业务词:从 task_keywords 提取核心词(如"agent"、"订单")
           - 意向词:从 intent_keywords 读取(如"接单"、"找活"、"外包")
        4. 回退模式(未配置 intent_keywords 时):使用旧的 INQUIRY_PATTERNS + AI_PRODUCT_KEYWORDS

        Args:
            content: 内容文本(评论)
            title: 标题文本(评论所属视频标题)
            task_keywords: 任务关键词列表(搜索词,如["agent 寻找订单"])
            intent_keywords: 意向判定关键词(如["接单","找活","外包","赚钱"])
            exclude_keywords: 排除词列表(如["豆包","mcp","skill","学习agent"])
            business_intent: 业务意图描述(用于 LLM 判定或调试,如"找想接单赚钱的开发者")
            target_role: 目标客户类型(c端用户/厂家供应商/不限),决定供方过滤方向

        Returns:
            LeadMatchResult: 匹配结果,包含 is_lead/intent_level/match_mode/role_tag
        """
        if not content and not title:
            return LeadMatchResult(False, [], "", 0, "none", "empty")

        full_text = f"{title} {content}".lower()
        matched_keywords = []
        intent_type = ""
        lead_score = 0

        # ============ 1. 排除词过滤(最高优先级) ============
        if exclude_keywords:
            for ex_kw in exclude_keywords:
                ex_kw_lower = ex_kw.lower().strip()
                if ex_kw_lower and ex_kw_lower in full_text:
                    # 命中排除词,直接返回非线索
                    return LeadMatchResult(
                        False, [], "excluded", 0, "none", "excluded"
                    )

        # ============ 2. 供方/求方角色分类(行业无关行为信号) ============
        # 通过评论本身的行为方向判断是供方(服务商推销)还是求方(C端咨询),
        # 而非预先为每个行业配置排除词。再结合任务 target_role 决定保留/排除。
        # 注意:只用content做角色分类,不用title — 因为视频标题可能含"代注册"等
        # 供方信号词,如果用title+content会导致该视频下所有评论都被误判为供方。
        role = cls.classify_role((content or "").lower(), task_keywords=task_keywords)
        if target_role == "c端用户" and role == "supplier":
            # 找C端用户时,服务商/厂家广告直接排除(非目标客户)
            return LeadMatchResult(
                False, matched_keywords, "supplier_excluded", 0, "none",
                "supplier_excluded", role
            )

        # ============ 3. 任务关键词相关性检查(业务词) ============
        # 内容或标题必须与任务关键词相关,才可能是线索
        # 避免采集到无关评论(如学琵琶任务里评论提到豆包/AI等不相关词被误判)
        task_related = True  # 默认相关(向后兼容,无关键词时不过滤)
        matched_business_terms = []
        if task_keywords:
            task_related = False
            # 任务关键词的核心词(去掉"学/教学/启蒙/练习/入门"等修饰,保留主词如"琵琶")
            core_terms = cls._extract_core_terms(task_keywords)
            # 检查 full_text 是否包含任一核心词
            for term in core_terms:
                if term and term in full_text:
                    task_related = True
                    matched_business_terms.append(term)
                    matched_keywords.append(f"biz:{term}")
            # 任务关键词不相关,直接返回非线索
            if not task_related:
                return LeadMatchResult(False, [], "", 0, "none", "unrelated", role)

        # ============ 2.5 供方保留逻辑(找厂家/不限时,供方广告直接作为线索) ============
        # target_role=厂家供应商/不限 时,供方广告(服务商/厂家推销)本身就是目标客户,
        # 不需要命中意向词(意向词是给C端求方用的),只要与任务关键词相关即可保留并打标。
        # target_role=c端用户 的供方已在前面步骤2排除,不会走到这里。
        if role == "supplier" and target_role in ("厂家供应商", "不限") and task_related:
            # 供方广告命中业务词 → 作为线索保留(评分中等,供前端筛选)
            matched_keywords = list(set(matched_keywords))
            return LeadMatchResult(
                True, matched_keywords, "supplier_ad", 60, "medium",
                "supplier_kept", role
            )

        # ============ 3. 严格双词命中模式(配置了 intent_keywords 时启用) ============
        if intent_keywords:
            # 检查意向词命中
            matched_intent_terms = []
            for intent_kw in intent_keywords:
                intent_kw_lower = intent_kw.lower().strip()
                if intent_kw_lower and intent_kw_lower in full_text:
                    matched_intent_terms.append(intent_kw)
                    matched_keywords.append(f"intent:{intent_kw}")

            # 严格双词命中:业务词 AND 意向词都命中才算线索
            if matched_business_terms and matched_intent_terms:
                # 命中多个意向词 → high,单个 → medium
                if len(matched_intent_terms) >= 2 or len(matched_business_terms) >= 2:
                    intent_level = "high"
                    lead_score = 90
                else:
                    intent_level = "medium"
                    lead_score = 70
                intent_type = "strict_double_match"
                # 去重
                matched_keywords = list(set(matched_keywords))
                return LeadMatchResult(
                    True, matched_keywords, intent_type, lead_score,
                    intent_level, "strict_double", role
                )
            else:
                # 业务词命中但意向词未命中 → 不算线索(严格模式)
                return LeadMatchResult(
                    False, matched_keywords, "no_intent", 0, "none", "strict_double", role
                )

        # ============ 4. 回退模式:旧的 INQUIRY_PATTERNS + AI_PRODUCT_KEYWORDS ============
        # (未配置 intent_keywords 时使用,保持向后兼容)
        # 1. 检查是否包含咨询意图
        has_inquiry = False
        for pattern in cls.INQUIRY_PATTERNS:
            if re.search(pattern, full_text, re.IGNORECASE):
                has_inquiry = True
                matched_keywords.append(pattern)
                lead_score += 10
        # ★求方判定经验扩展到全局(角色判定全局原则):INQUIRY_PATTERNS 是旧词表,无否定模式/
        # 长文案分级否决,会把长文案里的"推荐/需要/有没有"等误判为咨询意图(如"推荐品牌的产品"
        # "供方软文含推荐")。用 classify_role 的 consumer 判定 gate:长文案(>=30字)neutral +
        # INQUIRY命中 = classify_role 已用长文案否决排除求方,INQUIRY 命中是误判,否决。
        # 短文案 neutral 保留(可能是真求方短评论,避免误伤)。consumer 不受影响;supplier 已被
        # 上行保留逻辑处理。不一刀切,结合任务出发点。
        if has_inquiry and role == "neutral" and len(content or "") >= 30:
            has_inquiry = False

        # 2. 检查是否包含AI产品关键词
        has_ai_product = False
        for _, keywords in cls.AI_PRODUCT_KEYWORDS.items():
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

        # 当提供了任务关键词时:即使有咨询意图,也必须内容与任务相关
        # (前面已检查 task_related,此处再次确保)
        if task_keywords and not task_related:
            is_lead = False
            lead_score = 0

        # 意向等级(回退模式)
        if is_lead:
            if has_inquiry and has_ai_product:
                intent_level = "high"
            elif has_inquiry:
                intent_level = "medium"
            else:
                intent_level = "low"
        else:
            intent_level = "none"

        # ★求方经验扩展到全局 is_lead(角色判定全局原则):classify_role 判 consumer(求方)
        # 的评论,即使没命中 INQUIRY_PATTERNS(想学/想买/求带/怎么联系/如何联系/怎么报名/零基础
        # 等求方信号未收录),只要与任务相关(task_related)也算线索。让 classify_role 的求方判定
        # 经验(长文案分级否决/否定模式/强信号分级)直接驱动 is_lead,而非仅依赖旧的
        # INQUIRY_PATTERNS(覆盖不全)。与 supplier 保留逻辑(上行 963)对称:
        # supplier+task_related→线索,consumer+task_related→线索。不一刀切,结合任务出发点。
        if role == "consumer" and task_related and not is_lead:
            is_lead = True
            lead_score = max(lead_score, 60)
            intent_level = "medium"
            if not intent_type:
                intent_type = "consumer_signal"

        # 去重
        matched_keywords = list(set(matched_keywords))

        return LeadMatchResult(
            is_lead, matched_keywords, intent_type, lead_score,
            intent_level, "legacy_inquiry", role
        )


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
    # 过滤系统默认昵称的异常号(如"用户1926838812871"),这类号多为新注册/未完善资料/机器人,
    # 主页无有效联系方式,采集会浪费配额且无法转化为线索
    if nickname and re.match(r'^用户\d+$', nickname):
        return None

    if detector is None:
        detector = CustomerLeadDetector()
    
    # 从任务配置加载关键词,要求评论与任务关键词相关才算是线索
    # 同时获取 owner_user_id 用于数据隔离(修复:线索未继承任务 owner 导致用户看不到数据)
    # 同时加载精准获客字段:business_intent/intent_keywords/exclude_keywords/target_role
    task_keywords = None
    task_owner_uid = ""
    intent_keywords = None
    exclude_keywords = None
    business_intent = ""
    task_target_role = "不限"
    task_target_regions = []
    if task_id:
        try:
            import json
            from database.db_session import get_session
            from sqlalchemy import text as sa_text
            async with get_session() as session:
                r = await session.execute(
                    sa_text(
                        "SELECT keywords, owner_user_id, business_intent, intent_keywords, exclude_keywords, target_role, target_regions "
                        "FROM crawler_task WHERE id=:tid"
                    ),
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
                    # 精准获客字段
                    business_intent = row[2] or ""
                    if row[3]:
                        try:
                            ikw = json.loads(row[3])
                            if isinstance(ikw, list):
                                intent_keywords = ikw
                            elif isinstance(ikw, str):
                                intent_keywords = [ikw]
                        except Exception:
                            pass
                    if row[4]:
                        try:
                            ekw = json.loads(row[4])
                            if isinstance(ekw, list):
                                exclude_keywords = ekw
                            elif isinstance(ekw, str):
                                exclude_keywords = [ekw]
                        except Exception:
                            pass
                    # 目标客户类型(c端用户/厂家供应商/不限),决定供方过滤方向
                    task_target_role = row[5] or "不限"
                    # 目标地区过滤
                    if row[6]:
                        try:
                            tr = json.loads(row[6])
                            if isinstance(tr, list):
                                task_target_regions = [str(r) for r in tr if r]
                        except Exception:
                            pass
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"[save_customer_lead] Failed to load task config for {task_id}: {e}"
            )

    # 目标地区过滤:如果任务配置了 target_regions,只保留 ip_location 包含任一目标地区的线索
    if task_target_regions:
        if not ip_location or not any(region in (ip_location or "") for region in task_target_regions):
            return None

    # 将额外标题(如评论所属视频标题)拼接到标题中,用于关键词相关性判断
    combined_title = title
    if extra_title:
        combined_title = f"{title} {extra_title}" if title else extra_title

    result = detector.detect(
        content, combined_title,
        task_keywords=task_keywords,
        intent_keywords=intent_keywords,
        exclude_keywords=exclude_keywords,
        business_intent=business_intent,
        target_role=task_target_role,
    )
    
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
        # intent_type 同时记录匹配模式+意向等级,便于后续筛选
        # 例如 "strict_double:high" / "legacy_inquiry:medium" / "excluded"
        "intent_type": f"{result.match_mode}:{result.intent_level}" if result.match_mode else result.intent_type,
        "lead_score": result.lead_score,
        # 角色标签:供方/求方/中性(由行业无关行为信号分析得出,配合 target_role 过滤)
        "role_tag": result.role_tag or "neutral",
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
        from sqlalchemy import select, desc

        # === 同用户相似内容去重 ===
        # 同一任务下、同一用户发的高度相似广告模板评论只保留1条,
        # 并在已有线索上累计 dup_count,避免线索列表被同一广告用户的重复文案淹没。
        normalized_hash = content_fingerprint(content)
        now_ms_dedup = int(time.time() * 1000)

        async with get_session() as session:
            dup_target = None
            if user_id and task_id:
                # 查同 task + 同 user 的已有线索(限制最近 50 条,按时间倒序)
                existing_result = await session.execute(
                    select(CustomerLead)
                    .where(CustomerLead.task_id == task_id)
                    .where(CustomerLead.user_id == user_id)
                    .order_by(desc(CustomerLead.add_ts))
                    .limit(50)
                )
                for existing in existing_result.scalars():
                    # 先精确比对指纹(快路径)
                    if normalized_hash and existing.content_hash and existing.content_hash == normalized_hash:
                        dup_target = existing
                        break
                    # 再相似度比对(慢路径,仅对同用户候选,数量有限)
                    if is_similar_content(content, existing.content or ""):
                        dup_target = existing
                        break

            if dup_target:
                # 命中重复:不新增,在已有线索上累加重复次数 + 更新时间
                dup_target.dup_count = (dup_target.dup_count or 1) + 1
                dup_target.last_modify_ts = now_ms_dedup
                # 保留更高分(同一广告用户在不同视频下可能命中不同评分,取最高代表)
                if lead_score > (dup_target.lead_score or 0):
                    dup_target.lead_score = lead_score
                # 若已有线索缺失指纹,顺便回填
                if not dup_target.content_hash and normalized_hash:
                    dup_target.content_hash = normalized_hash
                await session.flush()
                return None  # 去重跳过,不新增

            lead_data["content_hash"] = normalized_hash
            lead_data["dup_count"] = 1
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