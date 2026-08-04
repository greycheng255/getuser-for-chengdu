"""
网站分析模块
用于抓取和分析网站内容，提供GEO诊断
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import ssl
import socket
from datetime import datetime


@dataclass
class WebsiteData:
    """网站数据"""
    url: str
    title: str
    description: str
    headings: List[Dict]
    paragraphs: List[str]
    links: List[Dict]
    images: List[Dict]
    schema_markup: List[Dict]
    meta_tags: Dict
    word_count: int
    load_time: float
    ssl_valid: bool
    ssl_expiry: Optional[str]


@dataclass
class GEODiagnosis:
    """GEO诊断结果"""
    overall_score: float
    content_score: float
    structure_score: float
    authority_score: float
    technical_score: float
    issues: List[Dict]
    suggestions: List[Dict]
    priority_actions: List[str]
    competitive_position: str


class WebsiteCrawler:
    """网站爬虫"""
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    
    def crawl(self, url: str) -> Optional[WebsiteData]:
        """抓取网站内容"""
        try:
            # 确保URL格式正确
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            print(f"开始爬取网站: {url}")
            start_time = datetime.now()
            
            # 发送请求，增加重试和更长的超时
            session = requests.Session()
            session.headers.update(self.headers)
            
            # 先尝试获取首页
            try:
                response = session.get(url, timeout=(10, 60), allow_redirects=True)
                response.raise_for_status()
                print(f"成功获取响应，状态码: {response.status_code}")
            except requests.exceptions.Timeout:
                print(f"请求超时: {url}")
                return None
            except requests.exceptions.ConnectionError as e:
                print(f"连接错误: {url} - {str(e)}")
                return None
            
            load_time = (datetime.now() - start_time).total_seconds()
            
            # 解析HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 提取数据
            title = self._extract_title(soup)
            description = self._extract_description(soup)
            headings = self._extract_headings(soup)
            paragraphs = self._extract_paragraphs(soup)
            links = self._extract_links(soup, url)
            images = self._extract_images(soup, url)
            schema_markup = self._extract_schema_markup(soup)
            meta_tags = self._extract_meta_tags(soup)
            
            # 计算字数
            word_count = sum(len(p.split()) for p in paragraphs)
            
            # 检查SSL
            ssl_valid, ssl_expiry = self._check_ssl(url)
            
            return WebsiteData(
                url=url,
                title=title,
                description=description,
                headings=headings,
                paragraphs=paragraphs,
                links=links,
                images=images,
                schema_markup=schema_markup,
                meta_tags=meta_tags,
                word_count=word_count,
                load_time=load_time,
                ssl_valid=ssl_valid,
                ssl_expiry=ssl_expiry
            )
            
        except Exception as e:
            print(f"爬取失败 {url}: {str(e)}")
            return None
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """提取标题"""
        title_tag = soup.find('title')
        return title_tag.get_text(strip=True) if title_tag else ''
    
    def _extract_description(self, soup: BeautifulSoup) -> str:
        """提取描述"""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            return meta_desc.get('content', '')
        
        meta_desc = soup.find('meta', attrs={'property': 'og:description'})
        if meta_desc:
            return meta_desc.get('content', '')
        
        return ''
    
    def _extract_headings(self, soup: BeautifulSoup) -> List[Dict]:
        """提取标题层级"""
        headings = []
        for i in range(1, 7):
            for tag in soup.find_all(f'h{i}'):
                headings.append({
                    'level': i,
                    'text': tag.get_text(strip=True)
                })
        return headings
    
    def _extract_paragraphs(self, soup: BeautifulSoup) -> List[str]:
        """提取段落文本"""
        paragraphs = []
        for p in soup.find_all('p'):
            text = p.get_text(strip=True)
            if len(text) > 20:  # 过滤短文本
                paragraphs.append(text)
        return paragraphs
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """提取链接"""
        links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            full_url = urljoin(base_url, href)
            links.append({
                'text': a.get_text(strip=True),
                'url': full_url,
                'is_external': not full_url.startswith(base_url)
            })
        return links
    
    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """提取图片"""
        images = []
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src:
                full_url = urljoin(base_url, src)
                images.append({
                    'url': full_url,
                    'alt': img.get('alt', ''),
                    'has_alt': bool(img.get('alt'))
                })
        return images
    
    def _extract_schema_markup(self, soup: BeautifulSoup) -> List[Dict]:
        """提取Schema.org标记"""
        schemas = []
        
        # JSON-LD格式
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                schemas.append({
                    'type': data.get('@type', 'Unknown'),
                    'format': 'JSON-LD',
                    'data': data
                })
            except:
                pass
        
        # Microdata格式
        for tag in soup.find_all(attrs={'itemscope': True}):
            itemtype = tag.get('itemtype', '')
            if itemtype:
                schemas.append({
                    'type': itemtype.split('/')[-1],
                    'format': 'Microdata',
                    'data': {'itemtype': itemtype}
                })
        
        return schemas
    
    def _extract_meta_tags(self, soup: BeautifulSoup) -> Dict:
        """提取Meta标签"""
        meta_tags = {}
        
        for meta in soup.find_all('meta'):
            name = meta.get('name') or meta.get('property')
            content = meta.get('content')
            if name and content:
                meta_tags[name] = content
        
        return meta_tags
    
    def _check_ssl(self, url: str) -> Tuple[bool, Optional[str]]:
        """检查SSL证书"""
        try:
            parsed = urlparse(url)
            if parsed.scheme != 'https':
                return False, None
            
            hostname = parsed.hostname
            context = ssl.create_default_context()
            
            with socket.create_connection((hostname, 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    expiry_date = cert.get('notAfter')
                    return True, expiry_date
                    
        except Exception as e:
            return False, None


class GEODiagnostician:
    """GEO诊断专家"""
    
    def __init__(self):
        self.crawler = WebsiteCrawler()
    
    def diagnose(self, url: str) -> Dict:
        """对网站进行GEO诊断"""
        # 抓取网站数据
        website_data = self.crawler.crawl(url)
        
        if not website_data:
            # 如果无法爬取，返回错误信息
            print(f"无法爬取网站 {url}")
            return {
                'success': False,
                'error': '无法访问该网站',
                'message': f'无法连接到 {url}，请检查网址是否正确或网站是否可访问',
                'url': url,
                'suggestions': [
                    '请确认网址格式正确（例如：www.example.com）',
                    '检查网站是否已上线并可公开访问',
                    '如果网站需要特定地区访问，请确保服务器可以访问该网站'
                ]
            }
        
        # 进行各项评分
        content_score = self._score_content(website_data)
        structure_score = self._score_structure(website_data)
        authority_score = self._score_authority(website_data)
        technical_score = self._score_technical(website_data)
        
        # 计算总分
        overall_score = (content_score * 0.3 + 
                        structure_score * 0.25 + 
                        authority_score * 0.25 + 
                        technical_score * 0.2)
        
        # 发现问题
        issues = self._find_issues(website_data, content_score, structure_score, authority_score, technical_score)
        
        # 生成建议
        suggestions = self._generate_suggestions(website_data, issues)
        
        # 优先级行动
        priority_actions = self._get_priority_actions(issues)
        
        # 竞争定位
        competitive_position = self._get_competitive_position(overall_score)
        
        return {
            'url': website_data.url,
            'domain': urlparse(website_data.url).netloc,
            'scan_time': datetime.now().isoformat(),
            'basic_info': {
                'title': website_data.title,
                'description': website_data.description,
                'word_count': website_data.word_count,
                'load_time': website_data.load_time,
                'ssl_valid': website_data.ssl_valid,
                'headings_count': len(website_data.headings),
                'links_count': len(website_data.links),
                'images_count': len(website_data.images),
                'schema_count': len(website_data.schema_markup)
            },
            'scores': {
                'overall': round(overall_score, 1),
                'content': round(content_score, 1),
                'structure': round(structure_score, 1),
                'authority': round(authority_score, 1),
                'technical': round(technical_score, 1)
            },
            'issues': issues,
            'suggestions': suggestions,
            'priority_actions': priority_actions,
            'competitive_position': competitive_position,
            'geo_readiness': self._get_geo_readiness(overall_score)
        }
    
    def _score_content(self, data: WebsiteData) -> float:
        """内容质量评分"""
        score = 50.0  # 基础分
        
        # 字数评估
        if data.word_count > 2000:
            score += 15
        elif data.word_count > 1000:
            score += 10
        elif data.word_count > 500:
            score += 5
        
        # 描述质量
        if len(data.description) > 100:
            score += 10
        elif len(data.description) > 50:
            score += 5
        
        # 段落数量
        if len(data.paragraphs) > 10:
            score += 10
        elif len(data.paragraphs) > 5:
            score += 5
        
        # 内容多样性（通过段落长度变化评估）
        if len(data.paragraphs) > 3:
            lengths = [len(p) for p in data.paragraphs[:10]]
            avg_length = sum(lengths) / len(lengths)
            variance = sum((l - avg_length) ** 2 for l in lengths) / len(lengths)
            if variance > 1000:  # 有足够的变化
                score += 10
        
        return min(100, score)
    
    def _score_structure(self, data: WebsiteData) -> float:
        """结构评分"""
        score = 50.0
        
        # 标题层级
        h1_count = sum(1 for h in data.headings if h['level'] == 1)
        h2_count = sum(1 for h in data.headings if h['level'] == 2)
        h3_count = sum(1 for h in data.headings if h['level'] == 3)
        
        if h1_count == 1:
            score += 10
        if h2_count >= 3:
            score += 10
        if h3_count >= 3:
            score += 5
        
        # 标题层级完整性
        has_hierarchy = h1_count > 0 and h2_count > 0
        if has_hierarchy:
            score += 10
        
        # 内部链接
        internal_links = [l for l in data.links if not l['is_external']]
        if len(internal_links) > 10:
            score += 10
        elif len(internal_links) > 5:
            score += 5
        
        return min(100, score)
    
    def _score_authority(self, data: WebsiteData) -> float:
        """权威性评分"""
        score = 40.0
        
        # Schema.org标记
        if len(data.schema_markup) > 0:
            score += 20
            # 多种类型的Schema
            schema_types = set(s['type'] for s in data.schema_markup)
            if len(schema_types) > 1:
                score += 10
        
        # Open Graph标签
        og_tags = [k for k in data.meta_tags.keys() if k.startswith('og:')]
        if len(og_tags) >= 4:
            score += 15
        elif len(og_tags) >= 2:
            score += 10
        
        # Twitter Card
        if 'twitter:card' in data.meta_tags:
            score += 10
        
        # 外部链接（权威性指标）
        external_links = [l for l in data.links if l['is_external']]
        if len(external_links) > 5:
            score += 5
        
        return min(100, score)
    
    def _score_technical(self, data: WebsiteData) -> float:
        """技术评分"""
        score = 50.0
        
        # SSL证书
        if data.ssl_valid:
            score += 20
        
        # 加载速度
        if data.load_time < 1:
            score += 20
        elif data.load_time < 2:
            score += 15
        elif data.load_time < 3:
            score += 10
        
        # 图片ALT标签
        images_with_alt = sum(1 for img in data.images if img['has_alt'])
        if len(data.images) > 0:
            alt_ratio = images_with_alt / len(data.images)
            score += alt_ratio * 10
        
        return min(100, score)
    
    def _find_issues(self, data: WebsiteData, content_score: float, 
                     structure_score: float, authority_score: float, 
                     technical_score: float) -> List[Dict]:
        """发现问题"""
        issues = []
        
        # 内容问题
        if content_score < 60:
            if data.word_count < 500:
                issues.append({
                    'category': 'content',
                    'severity': 'high',
                    'title': '内容量不足',
                    'description': f'页面字数仅{data.word_count}字，建议至少1000字以上'
                })
            
            if len(data.description) < 50:
                issues.append({
                    'category': 'content',
                    'severity': 'medium',
                    'title': '描述标签缺失或过短',
                    'description': 'Meta description有助于AI理解页面内容'
                })
        
        # 结构问题
        if structure_score < 60:
            h1_count = sum(1 for h in data.headings if h['level'] == 1)
            if h1_count == 0:
                issues.append({
                    'category': 'structure',
                    'severity': 'high',
                    'title': '缺少H1标题',
                    'description': 'H1标题是页面主题的核心标识'
                })
            elif h1_count > 1:
                issues.append({
                    'category': 'structure',
                    'severity': 'medium',
                    'title': '多个H1标题',
                    'description': '建议每个页面只有一个H1标题'
                })
        
        # 权威性問題
        if authority_score < 60:
            if len(data.schema_markup) == 0:
                issues.append({
                    'category': 'authority',
                    'severity': 'high',
                    'title': '缺少Schema.org标记',
                    'description': '结构化数据帮助AI理解内容语义'
                })
            
            og_tags = [k for k in data.meta_tags.keys() if k.startswith('og:')]
            if len(og_tags) < 2:
                issues.append({
                    'category': 'authority',
                    'severity': 'medium',
                    'title': '缺少Open Graph标签',
                    'description': 'OG标签提升社交媒体和AI可见性'
                })
        
        # 技术问题
        if technical_score < 60:
            if not data.ssl_valid:
                issues.append({
                    'category': 'technical',
                    'severity': 'high',
                    'title': 'SSL证书无效或缺失',
                    'description': 'HTTPS是信任的基础'
                })
            
            if data.load_time > 3:
                issues.append({
                    'category': 'technical',
                    'severity': 'medium',
                    'title': '页面加载过慢',
                    'description': f'加载时间{data.load_time:.1f}秒，建议优化到2秒以内'
                })
        
        return issues
    
    def _generate_suggestions(self, data: WebsiteData, issues: List[Dict]) -> List[Dict]:
        """生成优化建议"""
        suggestions = []
        
        # 内容建议
        if data.word_count < 1000:
            suggestions.append({
                'category': 'content',
                'priority': 'high',
                'title': '扩充内容深度',
                'description': '增加详细的产品介绍、使用案例、FAQ等内容',
                'action': '撰写至少2000字的深度内容',
                'expected_impact': '提升AI引用率20-30%'
            })
        
        # 结构建议
        h2_count = sum(1 for h in data.headings if h['level'] == 2)
        if h2_count < 3:
            suggestions.append({
                'category': 'structure',
                'priority': 'high',
                'title': '优化内容结构',
                'description': '使用H2/H3标签创建清晰的内容层级',
                'action': '添加3-5个H2小标题，每个H2下添加H3子标题',
                'expected_impact': '提升可读性和AI理解度'
            })
        
        # Schema建议
        if len(data.schema_markup) == 0:
            suggestions.append({
                'category': 'authority',
                'priority': 'high',
                'title': '添加结构化数据',
                'description': '实施Schema.org标记帮助AI理解内容',
                'action': '添加Organization、Product或Article类型的Schema',
                'expected_impact': '显著提升AI引用概率'
            })
        
        # ERE框架建议
        suggestions.append({
            'category': 'geo_strategy',
            'priority': 'high',
            'title': '实施ERE内容框架',
            'description': 'Entity-Relation-Evidence框架优化内容',
            'action': '明确定义实体、建立关系、提供证据支撑',
            'expected_impact': 'GEO合规性提升40%'
        })
        
        # 技术建议
        suggestions.append({
            'category': 'technical',
            'priority': 'medium',
            'title': '优化页面性能',
            'description': '提升加载速度和用户体验',
            'action': '压缩图片、启用缓存、使用CDN',
            'expected_impact': '改善用户留存和AI抓取效率'
        })
        
        return suggestions
    
    def _get_priority_actions(self, issues: List[Dict]) -> List[str]:
        """获取优先级行动清单"""
        actions = []
        
        high_priority = [i for i in issues if i['severity'] == 'high']
        
        for issue in high_priority[:5]:  # 最多5个高优先级
            if issue['category'] == 'content':
                actions.append(f"【内容】{issue['title']}: {issue['description']}")
            elif issue['category'] == 'structure':
                actions.append(f"【结构】{issue['title']}: {issue['description']}")
            elif issue['category'] == 'authority':
                actions.append(f"【权威】{issue['title']}: {issue['description']}")
            elif issue['category'] == 'technical':
                actions.append(f"【技术】{issue['title']}: {issue['description']}")
        
        return actions
    
    def _get_competitive_position(self, score: float) -> str:
        """获取竞争定位"""
        if score >= 80:
            return '领先者 - 您的网站GEO表现优秀，在AI搜索中具有竞争优势'
        elif score >= 60:
            return '追赶者 - 网站具备基础GEO能力，需要针对性优化'
        elif score >= 40:
            return '起步者 - GEO基础薄弱，建议系统性地实施优化策略'
        else:
            return '落后者 - 急需全面优化，否则将在AI搜索时代失去可见性'
    
    def _get_geo_readiness(self, score: float) -> Dict:
        """获取GEO准备度"""
        if score >= 80:
            return {
                'level': '高',
                'description': '网站已做好AI搜索准备',
                'next_steps': '持续监测、扩展内容覆盖、建立权威信源'
            }
        elif score >= 60:
            return {
                'level': '中',
                'description': '具备基础，需要针对性改进',
                'next_steps': '优先解决高严重度问题，实施ERE框架'
            }
        else:
            return {
                'level': '低',
                'description': '需要系统性优化',
                'next_steps': '制定GEO策略，逐步实施技术、内容、权威度优化'
            }

    def _generate_mock_diagnosis(self, url: str) -> Dict:
        """生成模拟诊断数据（当无法爬取网站时使用）"""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc or url
        
        # 基于域名生成一致的分数
        import hashlib
        hash_val = int(hashlib.md5(domain.encode()).hexdigest(), 16)
        
        # 生成 50-85 之间的分数
        overall_score = 50 + (hash_val % 36)
        content_score = 45 + (hash_val % 40)
        structure_score = 50 + (hash_val % 35)
        authority_score = 40 + (hash_val % 45)
        technical_score = 55 + (hash_val % 30)
        
        # 生成问题列表
        issues = []
        if content_score < 60:
            issues.append({
                'type': 'content',
                'severity': 'high',
                'title': '内容深度不足',
                'description': '网站内容字数较少，建议增加详细的产品描述和行业知识',
                'impact': '影响AI对网站专业度的理解'
            })
        if structure_score < 60:
            issues.append({
                'type': 'structure',
                'severity': 'medium',
                'title': '页面结构待优化',
                'description': '建议优化标题层级和内部链接结构',
                'impact': '影响AI对网站内容的抓取效率'
            })
        if technical_score < 70:
            issues.append({
                'type': 'technical',
                'severity': 'medium',
                'title': '技术SEO需改进',
                'description': '建议添加Schema标记和优化页面加载速度',
                'impact': '影响AI对网站技术质量的评估'
            })
        
        # 生成建议
        suggestions = [
            {
                'category': '内容优化',
                'priority': 'high',
                'title': '增加高质量内容',
                'description': '创建详细的行业指南和产品说明，提升内容深度',
                'expected_impact': '提升AI对网站专业度的认知'
            },
            {
                'category': '技术优化',
                'priority': 'medium',
                'title': '添加结构化数据',
                'description': '实施Schema.org标记，帮助AI更好理解网站内容',
                'expected_impact': '提升在AI搜索中的展示效果'
            },
            {
                'category': '权威度建设',
                'priority': 'medium',
                'title': '建立外部链接',
                'description': '获取行业相关的高质量外链，提升网站权威度',
                'expected_impact': '提升AI对网站可信度的评估'
            }
        ]
        
        return {
            'url': url,
            'domain': domain,
            'scan_time': datetime.now().isoformat(),
            'basic_info': {
                'title': f'{domain} - 专业网站',
                'description': f'欢迎来到{domain}，我们提供专业的服务和产品',
                'word_count': 1500 + (hash_val % 2000),
                'load_time': 1.5 + (hash_val % 30) / 10,
                'ssl_valid': True,
                'headings_count': 8 + (hash_val % 10),
                'links_count': 25 + (hash_val % 50),
                'images_count': 10 + (hash_val % 20),
                'schema_count': hash_val % 5
            },
            'scores': {
                'overall': round(overall_score, 1),
                'content': round(content_score, 1),
                'structure': round(structure_score, 1),
                'authority': round(authority_score, 1),
                'technical': round(technical_score, 1)
            },
            'issues': issues,
            'suggestions': suggestions,
            'priority_actions': [
                '增加网站内容深度，创建行业指南',
                '优化页面加载速度和移动端体验',
                '添加Schema结构化数据标记'
            ],
            'competitive_position': self._get_competitive_position(overall_score),
            'geo_readiness': self._get_geo_readiness(overall_score),
            'note': '由于网络限制，此诊断为基于网站域名的模拟分析结果'
        }


# 全局实例
diagnostician = GEODiagnostician()

if __name__ == '__main__':
    # 测试
    result = diagnostician.diagnose('example.com')
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
