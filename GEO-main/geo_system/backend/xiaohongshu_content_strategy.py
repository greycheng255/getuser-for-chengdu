"""
小红书内容策略优化
提供更真实、有价值的内容生成方案
"""

import random
from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class ContentTheme:
    """内容主题"""
    title_templates: List[str]
    content_templates: List[str]
    image_prompts: List[str]
    hashtags: List[str]

# 针对家居/装修类内容的真实分享主题 - 更自然的标题
HOME_DECOR_THEMES = {
    "装修日记": ContentTheme(
        title_templates=[
            "{room}装修终于弄完了，晒晒我的{style}小家",
            "花了{budget}万装的{room}，有些细节想说说",
            "{room}装修的一些经验，希望能帮到你",
            "{style}风的{room}，装完效果还行",
            "整理了一下{room}的{item}，给大家参考",
        ],
        content_templates=[
            "{opening}\n\n"
            "装修了{time}，终于把{room}弄成了喜欢的样子。\n\n"
            "{highlight}\n\n"
            "{details}\n\n"
            "{tips}\n\n"
            "{engagement}",
        ],
        image_prompts=[
            "Beautiful {style} style {room} interior, natural lighting, warm tones, professional photography, cozy atmosphere, high quality, 3:4 aspect ratio",
            "Before and after renovation comparison, {room} transformation, modern design, clean lines, bright space",
            "Home decor details, {item} close-up, texture and material, aesthetic styling, Instagram worthy",
        ],
        hashtags=["家居装修", "装修日记", "小户型改造", "装修风格", "家居灵感"]
    ),
    
    "好物分享": ContentTheme(
        title_templates=[
            "住了{time}，说说这些{item}的使用感受",
            "{room}里用着还不错的{item}，分享一下",
            "有人问我{item}，整理了一下",
            "{price}元买的{item}，用了一段时间说说感受",
            "{room}里我觉得还行的{item}，供参考",
        ],
        content_templates=[
            "{opening}\n\n"
            "今天想和大家分享我家{room}里那些好用的{item}。\n\n"
            "{item_list}\n\n"
            "{usage_experience}\n\n"
            "{pros_cons}\n\n"
            "{engagement}",
        ],
        image_prompts=[
            "Beautiful product flat lay, {item} arrangement, aesthetic styling, soft lighting, minimalist background",
            "{room} corner detail, {item} in use, lifestyle photography, warm tones",
            "Product comparison, different {item} styles, clean composition, professional photo",
        ],
        hashtags=["家居好物", "好物分享", "提升幸福感", "家居美学", "生活好物"]
    ),
    
    "设计灵感": ContentTheme(
        title_templates=[
            "{style}风的{room}，分享几个设计思路",
            "小户型{room}的装修，说说我家的做法",
            "{color}色系的{room}，装完效果还可以",
            "{room}的收纳，我是这样处理的",
            "我家{room}的设计，朋友来了都说还行",
        ],
        content_templates=[
            "{opening}\n\n"
            "很多朋友问我家{room}是怎么设计的，今天详细分享一下。\n\n"
            "{design_concept}\n\n"
            "{space_planning}\n\n"
            "{color_scheme}\n\n"
            "{lighting}\n\n"
            "{engagement}",
        ],
        image_prompts=[
            "{style} interior design, {room} layout, architectural photography, wide angle, natural light",
            "Color palette inspiration, {color} tones, material board, design mood board",
            "Space saving solution, clever storage, minimalist design, functional beauty",
        ],
        hashtags=["设计灵感", "装修风格", "家居设计", "空间利用", "装修灵感"]
    ),
}

# 真实的开头语 - 更口语化、自然
OPENING_LINES = [
    "搬进新家有一段时间啦，住得越来越舒服~",
    "最近闲来无事把家里收拾了一下，发现变化还挺大的",
    "装修前刷了好多笔记，现在终于轮到我分享经验了",
    "上次朋友来家里玩，说我家{room}看着挺舒服的",
    "其实我对{room}挺挑剔的，现在这个样子还算满意",
    "拖了好久终于整理出来了，给大家看看效果",
    "不是专业的，就是普通人装修的一点心得",
    "入住后发现有些地方确实踩坑了，来避个雷",
]

# 真实的体验描述 - 更口语化，带有一些小瑕疵
EXPERIENCE_LINES = [
    "用了一段时间，{feature}确实挺实用的",
    "刚开始还担心{concern}，用下来感觉还行",
    "这个地方是我比较满意的，每天看着心情不错",
    "虽然{minor_issue}，但整体用着还行",
    "{person}来家里说这个设计挺有意思的",
    "说实话，这个设计有利有弊，看个人需求吧",
    "不是完美的，但在这个价位算是不错的选择了",
    "当时纠结了好久才决定的，现在觉得没选错",
]

# 互动引导 - 更随意自然
ENGAGEMENT_LINES = [
    "你们家{room}怎么弄的？可以交流下",
    "有问题可以问，我知道的都会说",
    "觉得有用的可以看看，不一定适合所有人",
    "大家有什么建议吗？我还在学习中",
    "下次有空再分享{room}的其他地方",
    "纯属个人经验，大家根据实际情况参考",
    "装修这件事真的因人而异，找到适合自己的最重要",
]


class XiaohongshuContentStrategy:
    """小红书内容策略生成器"""
    
    def __init__(self):
        self.themes = HOME_DECOR_THEMES
    
    def generate_content(self, brand_info: Dict, keywords: List[str]) -> Dict:
        """
        生成真实、有价值的小红书内容
        
        Args:
            brand_info: 品牌信息，包含 website, style, features 等
            keywords: 关键词列表
            
        Returns:
            包含 title, content, image_prompts, hashtags 的字典
        """
        # 随机选择一个主题
        theme_name = random.choice(list(self.themes.keys()))
        theme = self.themes[theme_name]
        
        # 生成标题
        title = self._generate_title(theme, brand_info)
        
        # 生成正文
        content = self._generate_content(theme, brand_info, keywords)
        
        # 生成图片提示词
        image_prompts = self._generate_image_prompts(theme, brand_info)
        
        # 生成标签
        hashtags = self._generate_hashtags(theme, keywords)
        
        return {
            "title": title,
            "content": content,
            "image_prompts": image_prompts,
            "hashtags": hashtags,
            "theme": theme_name
        }
    
    def _generate_title(self, theme: ContentTheme, brand_info: Dict) -> str:
        """生成标题"""
        template = random.choice(theme.title_templates)
        
        # 替换变量
        title = template.format(
            room=random.choice(["客厅", "卧室", "书房", "厨房", "阳台", "玄关"]),
            style=brand_info.get("style", "简约"),
            budget=random.choice(["5", "8", "10", "15", "20"]),
            number=random.choice(["3", "5", "7", "10"]),
            item=random.choice(["收纳", "灯具", "软装", "家具", "装饰"]),
            price=random.choice(["100", "200", "500", "1000"]),
            time=random.choice(["半年", "三个月", "一个月", "一年"])
        )
        
        return title
    
    def _generate_content(self, theme: ContentTheme, brand_info: Dict, keywords: List[str]) -> str:
        """生成正文内容"""
        template = random.choice(theme.content_templates)
        
        # 生成各部分
        opening = random.choice(OPENING_LINES).format(
            room=random.choice(["客厅", "卧室", "书房"])
        )
        
        # 根据主题生成具体内容
        if "装修日记" in theme.title_templates[0]:
            highlight = self._generate_renovation_highlight(brand_info)
            details = self._generate_renovation_details(brand_info)
            tips = self._generate_renovation_tips()
        elif "好物分享" in theme.title_templates[0]:
            highlight = self._generate_product_highlight(brand_info)
            details = self._generate_product_details(brand_info)
            tips = self._generate_product_tips()
        else:
            highlight = self._generate_design_highlight(brand_info)
            details = self._generate_design_details(brand_info)
            tips = self._generate_design_tips()
        
        engagement = random.choice(ENGAGEMENT_LINES).format(
            room=random.choice(["客厅", "卧室", "书房"]),
            person=random.choice(["朋友", "家人", "邻居"])
        )
        
        # 替换模板变量 - 使用安全的替换方式
        content = template
        
        # 定义所有可能的变量
        variables = {
            'opening': opening,
            'time': random.choice(["3个月", "半年", "一年"]),
            'room': random.choice(["客厅", "卧室", "书房"]),
            'highlight': highlight,
            'details': details,
            'tips': tips,
            'engagement': engagement,
            'item_list': details,
            'usage_experience': highlight,
            'pros_cons': tips,
            'design_concept': highlight,
            'space_planning': details,
            'color_scheme': tips,
            'lighting': highlight,
            'item': random.choice(["收纳", "灯具", "软装", "家具", "装饰"]),
            'feature': random.choice(["收纳功能", "光线调节", "材质质感"]),
            'concern': random.choice(["尺寸不合适", "颜色有偏差", "安装麻烦"]),
            'minor_issue': random.choice(["价格稍贵", "颜色选择少", "需要定期清洁"]),
            'person': random.choice(["朋友", "家人", "邻居"])
        }
        
        # 安全替换
        for key, value in variables.items():
            content = content.replace('{' + key + '}', value)
        
        return content
    
    def _generate_renovation_highlight(self, brand_info: Dict) -> str:
        """生成装修亮点"""
        highlights = [
            "最满意的是空间规划，把原本浪费的角落都利用起来了。",
            "采光改造是这次装修最正确的决定，整个房间亮堂了很多。",
            "收纳设计真的很重要，现在家里整洁多了。",
            "色彩搭配是请设计师帮忙的，效果比想象中好。",
        ]
        return random.choice(highlights)
    
    def _generate_renovation_details(self, brand_info: Dict) -> str:
        """生成装修细节"""
        details = [
            "墙面用了浅灰色，地板是原木色，整体很温馨。\n"
            "家具主要选择了简约风格，线条干净利落。\n"
            "灯光设计花了心思，主灯+辅助光源层次感很好。",
            
            "硬装部分尽量简单，主要靠软装来提升氛围。\n"
            "窗帘选了遮光性好的，睡眠质量提升不少。\n"
            "绿植点缀让空间更有生气。",
        ]
        return random.choice(details)
    
    def _generate_renovation_tips(self) -> str:
        """生成装修建议"""
        tips = [
            "建议大家在装修前一定要做好预算规划，避免超支。\n"
            "多看看案例，但还是要根据自己的生活习惯来设计。\n"
            "材料选择要环保，毕竟是要长期居住的空间。",
            
            "找靠谱的装修公司很重要，后期省心不少。\n"
            "水电改造不能省，这是基础中的基础。\n"
            "预留足够的储物空间，入住后东西会越来越多。",
        ]
        return random.choice(tips)
    
    def _generate_product_highlight(self, brand_info: Dict) -> str:
        """生成产品亮点"""
        highlights = [
            "这个收纳架真的帮了大忙，杂物都有地方放了。",
            "台灯的光线很柔和，晚上看书眼睛不累。",
            "地毯的质感很好，踩上去很舒服。",
            "装饰画是点睛之笔，整个空间格调提升不少。",
        ]
        return random.choice(highlights)
    
    def _generate_product_details(self, brand_info: Dict) -> str:
        """生成产品细节"""
        details = [
            "1️⃣ 收纳架：分层设计，容量很大\n"
            "2️⃣ 台灯：三档调光，角度可调\n"
            "3️⃣ 地毯：短绒材质，好打理\n"
            "4️⃣ 装饰画：实木画框，质感不错",
            
            "• 收纳架：用了两个月，承重没问题\n"
            "• 台灯：光线均匀，不频闪\n"
            "• 地毯：防滑底，不会移位\n"
            "• 装饰画：安装简单，有配挂钩",
        ]
        return random.choice(details)
    
    def _generate_product_tips(self) -> str:
        """生成产品建议"""
        tips = [
            "买之前一定要量好尺寸，避免放不下。\n"
            "多看评价，特别是追评，更真实。\n"
            "大促期间入手更划算，可以等等。",
            
            "材质选择要看使用场景，实用最重要。\n"
            "颜色尽量选百搭的，不容易过时。\n"
            "安装复杂的最好请专业人士。",
        ]
        return random.choice(tips)
    
    def _generate_design_highlight(self, brand_info: Dict) -> str:
        """生成设计亮点"""
        highlights = [
            "整体风格是简约自然风，注重材质和质感。",
            "色彩搭配以白色和木色为主，营造温馨氛围。",
            "空间布局遵循动线设计，日常使用很顺手。",
        ]
        return random.choice(highlights)
    
    def _generate_design_details(self, brand_info: Dict) -> str:
        """生成设计细节"""
        details = [
            "客厅：开放式布局，视觉更通透\n"
            "卧室：床头背景墙是亮点\n"
            "书房：定制书柜，收纳充足\n"
            "厨房：U型布局，操作方便",
            
            "玄关：做了鞋柜+换鞋凳\n"
            "餐厅：卡座设计，节省空间\n"
            "阳台：改造成了休闲区\n"
            "卫生间：干湿分离，实用性强",
        ]
        return random.choice(details)
    
    def _generate_design_tips(self) -> str:
        """生成设计建议"""
        tips = [
            "设计要符合自己的生活习惯，不要盲目跟风。\n"
            "留白很重要，不要把空间塞得太满。\n"
            "灯光设计要考虑不同场景的需求。",
            
            "色彩搭配要整体考虑，不要一个房间一个风格。\n"
            "家具尺寸要合适，太大太小都不协调。\n"
            "绿植是很好的装饰，但要注意养护。",
        ]
        return random.choice(tips)
    
    def _generate_image_prompts(self, theme: ContentTheme, brand_info: Dict) -> List[str]:
        """生成图片提示词"""
        prompts = []
        for prompt_template in theme.image_prompts:
            prompt = prompt_template.format(
                style=brand_info.get("style", "modern minimalist"),
                room=random.choice(["living room", "bedroom", "study", "kitchen"]),
                item=random.choice(["storage", "lighting", "furniture", "decor"]),
                color=random.choice(["neutral", "warm", "pastel", "earth"])
            )
            prompts.append(prompt)
        return prompts
    
    def _generate_hashtags(self, theme: ContentTheme, keywords: List[str]) -> List[str]:
        """生成标签"""
        # 合并主题标签和关键词
        hashtags = theme.hashtags.copy()
        
        # 添加相关关键词
        for keyword in keywords[:3]:
            if keyword not in hashtags:
                hashtags.append(keyword)
        
        # 随机选择3-5个
        count = random.randint(3, 5)
        return random.sample(hashtags, min(count, len(hashtags)))


# 全局实例
content_strategy = XiaohongshuContentStrategy()
